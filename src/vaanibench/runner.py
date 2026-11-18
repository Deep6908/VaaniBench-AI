"""One outcome per case, reproducibility metadata, isolated provider/judge errors."""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from opentelemetry.trace import Status, StatusCode
from pydantic import ValidationError

from .evaluators import JUDGE_PROMPT, JUDGE_PROMPT_HASH, evaluate, judge_response
from .models import CaseResult, Experiment, Run
from .providers import OpenAIProvider, Provider, ProviderError, make_provider
from .schemas import digest, validate_dataset
from .telemetry import TraceSession


def git_metadata(root: Path) -> tuple[str | None, bool | None]:
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, stderr=subprocess.DEVNULL, timeout=5).decode().strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root, timeout=5))
        return revision, dirty
    except (OSError, subprocess.SubprocessError):
        return None, None


def run_evaluation(dataset: Path, manifest: Path, config: Experiment, output: Path,
                   *, provider: Provider | None = None, judge: Provider | None = None,
                   clock: Callable[[], float] = time.perf_counter) -> Run:
    cases, dataset_manifest = validate_dataset(dataset, manifest)
    output.mkdir(parents=True, exist_ok=True)
    if any((output / name).exists() for name in ["run.json", "traces.jsonl"]):
        raise ValueError("output already contains a run; use a new directory")
    provider = provider or make_provider(config)
    if config.judge_model and judge is None:
        judge_config = Experiment(name="judge", provider="openai", model=config.judge_model,
            system_prompt=JUDGE_PROMPT, seed=config.seed, max_tokens=1024,
            timeout_seconds=config.timeout_seconds)
        judge = OpenAIProvider(judge_config, json_mode=True)
    if judge is not None and config.judge_model is None:
        raise ValueError("judge requires config.judge_model for provenance")
    trace = TraceSession(output / "traces.jsonl")
    outcomes = []
    run_id = uuid.uuid4().hex
    started_at = datetime.now(timezone.utc).isoformat()
    root = Path.cwd()
    revision, dirty = git_metadata(root)
    try:
        with trace.tracer.start_as_current_span("evaluation", attributes={"run.id": run_id,
                "dataset.version": dataset_manifest.dataset_version, "provider": config.provider}) as parent:
            for case in cases:
                case_hash = hashlib.sha256(case.model_dump_json().encode()).hexdigest()
                with trace.tracer.start_as_current_span("case", attributes={"scenario.id": case.id,
                        "scenario.language": case.language, "scenario.category": case.category},
                        record_exception=False, set_status_on_exception=False) as span:
                    base = dict(scenario_id=case.id, scenario_hash=case_hash, language=case.language,
                        category=case.category, trace_id=format(span.get_span_context().trace_id, "032x"))
                    start = clock()
                    try:
                        response = provider.generate(case.messages)
                    except ProviderError as exc:
                        code = str(exc)
                        # Only known operational codes enter persisted diagnostics/traces.
                        if code not in {"timeout", "transport_error", "missing_api_key", "invalid_provider_response", "incomplete_response", "simulated_failure"} and not (code.startswith("http_") and code[5:].isdigit()):
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
                        if judge:
                            judge_start = clock()
                            with trace.tracer.start_as_current_span("judge", attributes={"judge.model": config.judge_model},
                                    record_exception=False, set_status_on_exception=False) as judge_span:
                                try:
                                    scores, judged = judge_response(case, response.text, judge)
                                    result.judge = scores
                                    result.judge_usage = judged.usage
                                    judge_span.set_attribute("judge.status", "ok")
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
            parent.set_attribute("case.count", len(outcomes))
    finally:
        trace.close()
    run = Run(run_id=run_id, started_at=started_at, dataset_version=dataset_manifest.dataset_version,
        dataset_sha256=digest(dataset), git_revision=revision, git_dirty=dirty,
        dependency_sha256=digest(root / "uv.lock") if (root / "uv.lock").exists() else None,
        config=config, judge_prompt_sha256=JUDGE_PROMPT_HASH if judge else None, cases=outcomes)
    temp = output / "run.json.tmp"
    temp.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    temp.replace(output / "run.json")
    return run
