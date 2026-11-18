# Original four-hour build plan (superseded schedule)

The latest execution brief allows one five-hour usage window, asks the mentor to
implement and explain automatically, expands the dataset to 20 scenarios, and
defers frontend/deployment infrastructure. The historical schedule below records
the original proposal. Current status lives in docs/progress.md and README.md.

This is a time budget, not a promise that every feature will be production ready.
The target is a tested evaluation MVP and a deployed read-only demo. Preserve
correctness and honest claims if a checkpoint overruns; cut optional features.

## Working agreement

You implement the core logic in short exercises. I explain design choices, review
diffs, help debug, and verify outcomes. I handle agreed setup and supporting work.
No implementation checkpoint is marked done until its acceptance check passes.

## Schedule from session start

| Minutes | Deliverable | Acceptance check |
| --- | --- | --- |
| 0–20 | Plan, architecture, Git, package scaffold, environment | Imports and dependency install work; no secrets tracked |
| 20–60 | Schema, loader, ten synthetic cases and manifest | Valid cases accepted; bad records and duplicate IDs rejected with locations |
| 60–100 | Provider boundary, mock, runner, CLI | Offline end-to-end run; failures captured; repeatable response/score fields |
| 100–140 | Deterministic metrics, reports, paired A/B; optional real adapter | Correct denominators; documented applicability; real results clearly separated |
| 140–175 | Tracing, latency/error/usage summaries | Local spans inspected; no credentials/content leakage; unknown costs preserved |
| 175–205 | CI regression gate and deployment preparation | Positive run passes; deliberately regressed fixture fails; clean install works |
| 205–240 | Read-only demo deploy, smoke check, reproducibility guide | Shared URL works; report reproducible; limitations and measured results documented |

If time is short, use inspected local OpenTelemetry output instead of a hosted
tracing backend; defer LLM judging and speech. If real API access is unavailable,
ship the offline demo labeled as mock-only. Do not describe it as a real-model
benchmark. If hosting is unavailable, report a local MVP rather than a deployment.

## Planned repository

```text
VaaniBench/
  pyproject.toml
  uv.lock                       # generated on dependency installation
  .gitignore
  .env.example
  README.md
  docs/
    build-plan.md
    architecture.md
    milestone-1.md
  data/
    scenarios.jsonl             # checkpoint 1, ten reviewed records
    manifest.json               # dataset version and provenance
  src/vaanibench/
    __init__.py
    schemas.py
    providers.py
    evaluators.py
    runner.py
    report.py
    telemetry.py
    cli.py
  tests/
    test_schemas.py
    test_providers.py           # added alongside implementation
    test_runner.py
    test_evaluators.py
    test_report.py
    test_cli.py
  .github/workflows/ci.yml       # checkpoint 5
  demo/                         # sanitized report viewer, checkpoint 6
  artifacts/                    # generated local runs; ignored by Git
```

Only the scaffold exists initially. Planned paths are not implemented features.

## Evidence needed before resume wording

- Reproducible command, passing tests, and actual case/language counts.
- Actual adapters and metrics implemented, including scoring limitations.
- Inspected traces and measured latency/error/usage with model/run identifiers.
- Demonstrated CI gate failure on an intentional regression.
- Deployment URL and successful smoke check if claiming deployment.
- Judge calibration or model improvements only after measured validation.

Do not claim production readiness, child safety, broad language coverage, model
quality improvement, cost savings, or calibrated judging from the mock demo.
