"""Explicit denominators, failure analysis, and paired regression decisions."""
from __future__ import annotations

import json
import math
import statistics
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from pydantic import Field

from .models import CaseResult, Run
from .schemas import Contract


def case_score(case: CaseResult) -> float | None:
    scores = [m.score for m in case.metrics if m.score is not None] if case.status == "ok" else []
    return statistics.mean(scores) if scores else None


def percentile(values: list[float], q: float) -> float | None:
    return sorted(values)[max(0, math.ceil(q * len(values)) - 1)] if values else None


def summary(run: Run) -> dict:
    ok = [c for c in run.cases if c.status == "ok"]
    errors = sum(c.status == "error" for c in run.cases)
    skipped = sum(c.status == "skipped" for c in run.cases)
    scores = [s for c in run.cases if (s := case_score(c)) is not None]
    latency = [c.latency_ms for c in run.cases]
    def tokens(field: str):
        values = [getattr(c.response.usage, field) for c in ok if c.response]
        known = [v for v in values if v is not None]
        return dict(known_total=sum(known) if known else None, known_requests=len(known), successful_requests=len(ok))
    groups = {}
    for dimension in ["language", "category"]:
        groups[dimension] = {}
        for label in sorted({getattr(c, dimension) for c in run.cases}):
            subset = [c for c in run.cases if getattr(c, dimension) == label]
            subgroup_scores = [s for c in subset if (s := case_score(c)) is not None]
            groups[dimension][label] = dict(total=len(subset), errors=sum(c.status == "error" for c in subset),
                scored=len(subgroup_scores), score=statistics.mean(subgroup_scores) if subgroup_scores else None)
    attempts = run.api_attempts
    estimates = [a.estimated_cost_usd for a in attempts if a.estimated_cost_usd is not None]
    accounted = sum((a.accounted_usd for a in attempts), Decimal(0))
    known_cost = sum(estimates, Decimal(0)) if estimates else None
    by_purpose = {}
    for purpose in ["generation", "judge"]:
        subset = [a for a in attempts if a.purpose == purpose]
        by_purpose[purpose] = dict(attempts=len(subset),
            input_tokens=sum(a.usage.input_tokens or 0 for a in subset) if any(a.usage.input_tokens is not None for a in subset) else None,
            output_tokens=sum(a.usage.output_tokens or 0 for a in subset) if any(a.usage.output_tokens is not None for a in subset) else None,
            cached_input_tokens=sum(a.usage.cached_input_tokens for a in subset) if any(a.usage.input_tokens is not None for a in subset) else None,
            usage_unknown_attempts=sum(a.usage.input_tokens is None or a.usage.output_tokens is None for a in subset),
            accounted_usd=str(sum((a.accounted_usd for a in subset), Decimal(0))))
    return dict(total=len(run.cases), successful=len(ok), errors=errors, skipped=skipped,
        error_rate=errors/len(run.cases), uncompleted_rate=(errors+skipped)/len(run.cases), scored=len(scores),
        not_scored=len(run.cases)-len(scores), deterministic_score=statistics.mean(scores) if scores else None,
        latency_ms=dict(p50=percentile(latency, .5), p95=percentile(latency, .95), scope="all attempts, including errors"),
        input_tokens=tokens("input_tokens"), output_tokens=tokens("output_tokens"),
        judge_scored=sum(c.judge is not None for c in run.cases),
        judge_errors=sum(c.judge_error is not None for c in run.cases),
        judge_input_tokens=sum(c.judge_usage.input_tokens or 0 for c in run.cases if c.judge_usage) if any(c.judge_usage and c.judge_usage.input_tokens is not None for c in run.cases) else None,
        cost_usd=str(known_cost) if attempts and len(estimates) == len(attempts) else None,
        known_estimated_cost_usd=str(known_cost) if known_cost is not None else None,
        accounted_usd=str(accounted), live_api_calls=len(attempts),
        unknown_cost_attempts=len(attempts)-len(estimates), api_usage=by_purpose,
        cost_reason="USD values are estimates, not invoices. Accounted USD retains reservations for unknown usage; mock costs/usage remain unknown.",
        stop_reason=run.stop_reason,
        groups=groups)


class Thresholds(Contract):
    max_score_drop: Annotated[float, Field(ge=0, le=1)] = 0.0
    max_error_increase: Annotated[float, Field(ge=0, le=1)] = 0.0
    min_scored_coverage: Annotated[float, Field(ge=0, le=1)] = 1.0
    max_latency_ratio: Annotated[float, Field(gt=0)] | None = None


def compare(baseline: Run, candidate: Run, thresholds: Thresholds) -> dict:
    if (baseline.dataset_sha256, baseline.metric_version, baseline.judge_version,
        baseline.config.judge_model, (baseline.config.judge_provider or (baseline.config.provider if baseline.config.provider != "mock" else "openai")) if baseline.config.judge_model else None, baseline.judge_prompt_sha256) != (
        candidate.dataset_sha256, candidate.metric_version, candidate.judge_version,
        candidate.config.judge_model, (candidate.config.judge_provider or (candidate.config.provider if candidate.config.provider != "mock" else "openai")) if candidate.config.judge_model else None, candidate.judge_prompt_sha256):
        raise ValueError("incompatible dataset, metric version, or judge configuration")
    a = {c.scenario_id: c for c in baseline.cases}
    b = {c.scenario_id: c for c in candidate.cases}
    if a.keys() != b.keys() or any(a[k].scenario_hash != b[k].scenario_hash for k in a):
        raise ValueError("comparison requires identical scenario IDs and content")
    pairs = []
    missing = []
    for key in a:
        sa, sb = case_score(a[key]), case_score(b[key])
        if sa is not None and sb is not None:
            pairs.append(dict(id=key, baseline=sa, candidate=sb, delta=sb-sa))
        elif sa is not None or sb is not None:
            missing.append(key)
    delta = statistics.mean(p["delta"] for p in pairs) if pairs else None
    baseline_scored = sum(case_score(c) is not None for c in a.values())
    coverage = len(pairs)/baseline_scored if baseline_scored else 0.0
    error_delta = summary(candidate)["error_rate"] - summary(baseline)["error_rate"]
    uncompleted_delta = summary(candidate)["uncompleted_rate"] - summary(baseline)["uncompleted_rate"]
    reasons = []
    if delta is None:
        reasons.append("no comparable deterministic scores")
    elif delta < -thresholds.max_score_drop - 1e-12:
        reasons.append("deterministic score drop exceeds threshold")
    if coverage < thresholds.min_scored_coverage:
        reasons.append("paired scored coverage below threshold")
    if error_delta > thresholds.max_error_increase + 1e-12:
        reasons.append("error rate increase exceeds threshold")
    if uncompleted_delta > thresholds.max_error_increase + 1e-12 and uncompleted_delta > error_delta:
        reasons.append("uncompleted rate (errors/skips) increase exceeds threshold")
    ratio = None
    a95, b95 = summary(baseline)["latency_ms"]["p95"], summary(candidate)["latency_ms"]["p95"]
    if a95 and b95 is not None:
        ratio = b95 / a95
    if thresholds.max_latency_ratio is not None and (ratio is None or ratio > thresholds.max_latency_ratio):
        reasons.append("p95 latency ratio exceeds threshold or is unavailable")
    judge_pairs = [dict(id=k, baseline=a[k].judge.model_dump(), candidate=b[k].judge.model_dump())
        for k in a if a[k].judge and b[k].judge]
    return dict(baseline_run_id=baseline.run_id, candidate_run_id=candidate.run_id,
        dataset_sha256=baseline.dataset_sha256, thresholds=thresholds.model_dump(),
        passed=not reasons, failures=reasons, paired_cases=len(pairs), missing_pairs=missing,
        scored_coverage=coverage, mean_paired_delta=delta, error_rate_delta=error_delta,
        uncompleted_rate_delta=uncompleted_delta, p95_latency_ratio=ratio, pairs=pairs, judge_pairs=judge_pairs,
        judge_note="Uncalibrated subjective scores; excluded from deterministic quality gate.")


def load_run(path: Path) -> Run:
    return Run.model_validate_json(path.read_text(encoding="utf-8"))


def write_report(run: Run, path: Path) -> None:
    data = summary(run)
    lines = [f"# VaaniBench: {run.config.name}", "", f"Run: `{run.run_id}`",
        f"Provider: **{run.config.provider}**; model: `{run.config.model}`.",
        f"Dataset: `{run.dataset_version}` / `{run.dataset_sha256}`.", "",
        "MOCK FIXTURE RESULTS — not model-quality evidence." if run.config.provider == "mock" else "Live-model run; inspect configuration and limitations before interpreting scores.",
        "", f"Requests: {data['successful']}/{data['total']} successful; {data['errors']} errors; {data['skipped']} skipped.",
        f"Deterministic scored cases: {data['scored']}/{data['total']}; mean: {data['deterministic_score']}.",
        f"Unscored/failed: {data['not_scored']}. Semantic safety/quality is not inferred from format checks.",
        f"Latency p50/p95 (ms, all attempts): {data['latency_ms']['p50']} / {data['latency_ms']['p95']}.",
        f"Judge scored: {data['judge_scored']}; judge errors: {data['judge_errors']}. Judge ratings are uncalibrated.",
        f"Estimated USD: {data['cost_usd']}; accounted USD including uncertain reservations: {data['accounted_usd']}; live attempts: {data['live_api_calls']}.",
        "Estimates are not invoices. Mock token usage/cost is unknown, not zero.", "", "## Failure analysis", "",
        "| Case | Language | Category | Status | Deterministic score | Error | Judge |",
        "| --- | --- | --- | --- | --- | --- | --- |"]
    for c in run.cases:
        score = case_score(c)
        lines.append(f"| {c.scenario_id} | {c.language} | {c.category} | {c.status} | {score if score is not None else 'not evaluated'} | {c.error_code or '-'} | {'scored' if c.judge else c.judge_error or 'disabled'} |")
    lines.extend(["", "## Operational summary", "", "```json", json.dumps(data, indent=2), "```", "",
        "Stored run.json contains responses; traces.jsonl contains operational metadata only.",
        "Synthetic convenience sample; no child-safety certification or population-level claims."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_comparison(data: dict, path: Path) -> None:
    lines = ["# Paired configuration comparison", "", f"Gate: **{'PASS' if data['passed'] else 'FAIL'}**",
        f"Paired scored cases: {data['paired_cases']}; coverage: {data['scored_coverage']:.3f}.",
        f"Mean paired deterministic delta: {data['mean_paired_delta']}.",
        f"Error-rate delta: {data['error_rate_delta']}.",
        "", "| Case | Baseline | Candidate | Delta |", "| --- | --- | --- | --- |"]
    lines += [f"| {p['id']} | {p['baseline']} | {p['candidate']} | {p['delta']} |" for p in data["pairs"]]
    lines += ["", "Failures: " + ("; ".join(data["failures"]) or "none"),
        "Missing scored pairs: " + (", ".join(data["missing_pairs"]) or "none"),
        "", data["judge_note"], "Small synthetic dataset; mock comparisons test the evaluation machinery only."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
