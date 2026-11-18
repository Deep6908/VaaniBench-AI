# Implementation checklist

- [x] Checkpoint 1: strict schema, JSONL loader, version/hash manifest, 20 scenarios.
- [x] Checkpoint 2: mock provider, runner, deterministic metrics, CLI, results/reports.
- [x] Checkpoint 3: transport-tested live adapter, optional rubric judge, paired A/B.
- [x] Checkpoint 4: local OpenTelemetry traces, usage/error/latency summaries, gates.
- [x] Checkpoint 5: 68 passing tests, fresh locked environment install, local
  equivalent of CI gates, executed mock benchmark, final README and limitations.

Initial MVP verification was offline; subsequent live evidence appears below. Judge calibration:
not performed. Hosted trace backend, speech, and public deployment: deferred.
The later local frontend and passing remote workflow are described below.

Offline results: 20 requests per configuration; 12 scored and eight unscored.
Baseline/repeat: 12/12 deterministic case checks; degraded: 5/12. Repeated
configuration gate passes; intentionally degraded gate fails. These are mock
fixture results, not LLM quality measurements. See docs/benchmarks/mock-v1/.

## Secure API integration

Implemented explicit live authorization/selection; shared default $0.10 and
20-attempt limits; versioned pricing and Decimal USD accounting; usage retention
on truncated/invalid judge output; bounded retries/backoff/Retry-After; safe API
attempt trace events; partial/skipped-result persistence and skip-aware gates.
API guard verification at that checkpoint: 120 tests passed, using fake transports and a network-blocking
test fixture. No live calls were made. See api-integration.md for operational limits.

## Local presentation and Groq

Added Groq provider and independent judge-provider selection, explicit local
credential loading, safe application transport header, runner progress callbacks,
and a loopback-only web comparison interface. Mock mode remains default; live
mode requires server enablement plus confirmation and explicit case selection.
Each server session permits only two live configuration runs.

Groq one-case generation+judge smoke succeeded. A three-case/two-configuration
real A/B run completed (six generation requests): both configurations passed all
three applicable checks; paired delta 0.0. One check counts Hindi fruit-response
lines only, so this is not three semantic correctness judgments. See the raw
evidence under docs/benchmarks/groq-live-v1. Earlier OpenAI calls returned quota
exhaustion. All real calls were explicitly authorized and outside unit tests.

Browser QA passed in Chrome: six-case mock run, progress, details, downloads,
mobile width, no page errors. Screenshots are under artifacts/demo-preview/.
Local unit/integration suite: 138 tests. Published to
https://github.com/Deep6908/VaaniBench-AI with remote CI passed for commit 89398e6:
https://github.com/Deep6908/VaaniBench-AI/actions/runs/44331956136.

## Deployment preparation

Implemented a separate Starlette/Uvicorn hosted adapter, Render public mock-only
Blueprint, health checks, exact host/origin validation, secure session cookies and
CSRF, owner password hashing/sign-in/rotation/logout, and per-owner job/download
access. Public mode never enables model calls, even if a provider key exists.

SQLite persists job progress/results, rate limits and daily API reservations.
Limits survive restart/password rotation; unknown spend is retained. Retention,
bounded history, one-instance locking, cancellation/deadline checks before further
HTTP attempts, and interrupted-job recovery are covered. Hosted refresh recovery
and public read-only Groq evidence reuse the dark interface.

Verification: 164 tests passed; hosted browser checks passed for mock presets, progress,
refresh/resume, details, download, saved evidence, owner sign-in/out and mobile
layout. A fresh runtime-only locked install and wheel build passed. No live model
requests were made for this work. Actual Render build/HTTPS/restart verification
is still pending; no paid service or disk was created. See deployment.md.
