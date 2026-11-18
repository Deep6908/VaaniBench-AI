"""One outcome per case, reproducibility metadata, isolated provider/judge errors."""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
import uuid
import os
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from opentelemetry.trace import Status, StatusCode
from pydantic import ValidationError

from .evaluators import JUDGE_PROMPT, JUDGE_PROMPT_HASH, evaluate, request_judgment
from .models import CaseResult, Experiment, Run, JudgeScores
from .providers import OpenAIProvider, Provider, ProviderError, make_provider, judge_provider_name, KEY_NAMES
from .schemas import digest, validate_dataset
from .telemetry import TraceSession
from .costs import BudgetLedger, ExecutionDenied, load_prices


def preflight(cases, config: Experiment) -> tuple[list, BudgetLedger | None]:
    ids = config.execution.case_ids
    if ids and not set(ids).issubset({c.id for c in cases}):
        raise ExecutionDenied("unknown_case_selection")
    selected = [c for c in cases if not ids or c.id in ids]
    live = config.provider != "mock" or config.judge_model is not None
    if not live:
        return selected, None
    ledger = BudgetLedger(config.execution, load_prices(config.execution.pricing_path))
    for model in ([config.model] if config.provider != "mock" else []) + ([config.judge_model] if config.judge_model else []):
        ledger.prices.price(model)
    needed = ({config.provider} if config.provider != "mock" else set()) | ({judge_provider_name(config)} if config.judge_model else set())
    if any(not os.environ.get(KEY_NAMES[p]) for p in needed):
        raise ExecutionDenied("missing_api_key")
    return selected, ledger


def git_metadata(root: Path) -> tuple[str | None, bool | None]:
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, stderr=subprocess.DEVNULL, timeout=5).decode().strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root, timeout=5))
        return revision, dirty
    except (OSError, subprocess.SubprocessError):
        return None, None


def run_evaluation(dataset: Path, manifest: Path, config: Experiment, output: Path,
                   *, provider: Provider | None = None, judge: Provider | None = None,
                   clock: Callable[[], float] = time.perf_counter,
                   on_event: Callable[[dict], None] | None = None, daily_guard=None,
                   should_stop: Callable[[], bool] | None = None) -> Run:
    def emit(event: str, **details):
        if on_event:
            try:
                on_event(dict(event=event, **details))
            except Exception:
                warnings.warn("Progress listener failed; evaluation continues.", RuntimeWarning)
    cases, dataset_manifest = validate_dataset(dataset, manifest)
    cases, ledger = preflight(cases, config)
    if ledger:
        ledger.daily_guard = daily_guard
    output.mkdir(parents=True, exist_ok=True)
    if any((output / name).exists() for name in ["run.json", "traces.jsonl"]):
        raise ValueError("output already contains a run; use a new directory")
    provider = provider or make_provider(config, ledger)
    # Injected OpenAI adapters must use this run's shared ledger as well.
    if isinstance(provider, OpenAIProvider):
        provider.ledger = ledger
    if config.judge_model and judge is None:
        judge_config = Experiment(name="judge", provider=judge_provider_name(config), model=config.judge_model,
            system_prompt=JUDGE_PROMPT, seed=config.seed, max_tokens=config.judge_max_tokens,
            timeout_seconds=config.timeout_seconds, execution=config.execution)
        judge = make_provider(judge_config, ledger, purpose="judge", json_mode=True)
    if isinstance(judge, OpenAIProvider):
        judge.ledger = ledger
        judge.purpose = "judge"
    if judge is not None and config.judge_model is None:
        raise ValueError("judge requires config.judge_model for provenance")
    trace = TraceSession(output / "traces.jsonl")
    outcomes = []
    run_id = uuid.uuid4().hex
    started_at = datetime.now(timezone.utc).isoformat()
    root = Path.cwd()
    revision, dirty = git_metadata(root)
    emit("run_started", run_id=run_id, config_name=config.name, total=len(cases))
    try:
        with trace.tracer.start_as_current_span("evaluation", attributes={"run.id": run_id,
                "dataset.version": dataset_manifest.dataset_version, "provider": config.provider}) as parent:
            for case in cases:
                emit("case_started", scenario_id=case.id)
                case_hash = hashlib.sha256(case.model_dump_json().encode()).hexdigest()
                with trace.tracer.start_as_current_span("case", attributes={"scenario.id": case.id,
                        "scenario.language": case.language, "scenario.category": case.category},
                        record_exception=False, set_status_on_exception=False) as span:
                    base = dict(scenario_id=case.id, scenario_hash=case_hash, language=case.language,
                        category=case.category, trace_id=format(span.get_span_context().trace_id, "032x"))
                    if should_stop and should_stop():
                        outcomes.append(CaseResult(**base, status="skipped", latency_ms=0.0, error_code="execution_cancelled"))
                        emit("case_completed", result=outcomes[-1].model_dump(mode="json"))
                        span.set_attribute("case.status", "skipped")
                        continue
                    if ledger:
                        ledger.scenario_id = case.id
                        if ledger.halted_reason:
                            outcomes.append(CaseResult(**base, status="skipped", latency_ms=0.0,
                                error_code=ledger.halted_reason))
                            emit("case_completed", result=outcomes[-1].model_dump(mode="json"))
                            span.set_attribute("case.status", "skipped")
                            continue
                    start = clock()
                    attempts_before = len(ledger.attempts) if ledger else 0
                    try:
                        response = provider.generate(case.messages)
                    except ExecutionDenied as exc:
                        status = "error" if ledger and len(ledger.attempts) > attempts_before else "skipped"
                        result = CaseResult(**base, status=status, error_code=str(exc),
                            latency_ms=max(0.0, (clock() - start) * 1000))
                        span.set_attribute("budget.stop_reason", str(exc))
                    except ProviderError as exc:
                        code = str(exc)
                        # Only known operational codes enter persisted diagnostics/traces.
                        if code not in {"timeout", "transport_error", "missing_api_key", "invalid_provider_response", "incomplete_response", "simulated_failure", "deadline_exceeded", "retry_deadline_exceeded", "retry_exhausted", "quota_exhausted"} and not (code.startswith("http_") and code[5:].isdigit()):
                            code = "provider_error"
                        result = CaseResult(**base, status="error", error_code=code,
                            latency_ms=max(0.0, (clock() - start) * 1000))
                        span.set_status(Status(StatusCode.ERROR, code))
                    except Exception:
                        result = CaseResult(**base, status="error", error_code="unexpected_provider_error",
                            latency_ms=max(0.0, (clock() - start) * 1000))
                        span.set_status(Status(StatusCode.ERROR, "unexpected_provider_error"))
                    else:
                        result = CaseResult(**base, status="ok", response=response,
                            latency_ms=max(0.0, (clock() - start) * 1000), metrics=evaluate(case, response.text))
                        if judge and should_stop and should_stop():
                            result.judge_error = "execution_cancelled"
                        elif judge:
                            judge_start = clock()
                            with trace.tracer.start_as_current_span("judge", attributes={"judge.model": config.judge_model},
                                    record_exception=False, set_status_on_exception=False) as judge_span:
                                try:
                                    judged = request_judgment(case, response.text, judge)
                                    result.judge_usage = judged.usage
                                    result.judge = JudgeScores.model_validate_json(judged.text)
                                    judge_span.set_attribute("judge.status", "ok")
                                except ExecutionDenied as exc:
                                    result.judge_error = str(exc)
                                    judge_span.set_status(Status(StatusCode.ERROR, str(exc)))
                                except (ProviderError, ValidationError, ValueError):
                                    result.judge_error = "judge_failed_or_invalid"
                                    judge_span.set_status(Status(StatusCode.ERROR, "judge_failed_or_invalid"))
                                except Exception:
                                    result.judge_error = "unexpected_judge_error"
                                    judge_span.set_status(Status(StatusCode.ERROR, "unexpected_judge_error"))
                            result.judge_latency_ms = max(0.0, (clock() - judge_start) * 1000)
                    span.set_attribute("case.status", result.status)
                    span.set_attribute("latency_ms", result.latency_ms)
                    if result.response:
                        for name, value in result.response.usage.model_dump().items():
                            if value is not None:
                                span.set_attribute(name, value)
                    outcomes.append(result)
                    emit("case_completed", result=result.model_dump(mode="json"))
            parent.set_attribute("case.count", len(outcomes))
            if ledger:
                parent.set_attribute("api.attempt_count", len(ledger.attempts))
                parent.set_attribute("api.accounted_usd", str(ledger.accounted_usd))
    finally:
        trace.close()
    run = Run(run_id=run_id, started_at=started_at, dataset_version=dataset_manifest.dataset_version,
        dataset_sha256=digest(dataset), git_revision=revision, git_dirty=dirty,
        dependency_sha256=digest(root / "uv.lock") if (root / "uv.lock").exists() else None,
        config=config, judge_prompt_sha256=JUDGE_PROMPT_HASH if judge else None, cases=outcomes,
        api_attempts=ledger.attempts if ledger else [],
        pricing_snapshot=ledger.prices.model_dump(mode="json") if ledger else None,
        stop_reason=ledger.halted_reason if ledger else None)
    temp = output / "run.json.tmp"
    temp.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    temp.replace(output / "run.json")
    emit("run_completed", run_id=run_id, total=len(outcomes), stop_reason=run.stop_reason)
    return run
