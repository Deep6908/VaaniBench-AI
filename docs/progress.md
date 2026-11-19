# Implementation checklist

## Current extension status — November 19, 2026

This section supersedes historical checkpoint wording below. The public Render
mock deployment was verified on November 18 (homepage, /healthz, safe bootstrap,
one hosted mock comparison). Extension code is included in this release;
owner-live Render configuration remains pending.
Unrelated .vscode changes are preserved. No real API calls were made in this work.

| Phase | Implemented | Verification / remaining dependency |
| --- | --- | --- |
| 1: durable owner-live | Shared SQLite/PostgreSQL SQL boundary; additive versioned migrations; atomic spending/admission/idempotency; session singleton lease; persistent report downloads; cancellation and conservative restart recovery | Final suite: 185 tests passed including real disposable PostgreSQL checks. Owner sessions/downloads/budgets survived new scratch directory. External database setup and hosted restart smoke pending. |
| 2: evidence | Separate balanced 60-case draft (20 development, 15 calibration, 25 heldout); family split checks; blinded annotation templates; agreement analysis; approval-gated repeated A/B benchmark with aggregate cap and scenario-cluster uncertainty | Offline workflow tests passed. All new cases remain independently unreviewed. No human labels/calibration or new real benchmark exists. |
| 3: operations | Optional HTTPS OTLP export with safe failure diagnostics; generation spans; owner history/search/comparison; operational snapshot/threshold warnings; CI PostgreSQL/browser jobs | Hosted browser QA passed including cancellation, owner history, saved comparison, downloads, refresh and mobile layout. Fake-export tests, fresh runtime-only install/imports, credential scan and PostgreSQL dump/restore drill passed. Real collector, hosted alerts/uptime, release rollback exercise pending. |

Architecture choice: preserve the existing runner, providers, evaluator and dark UI.
Use psycopg behind existing state methods, not a new ORM/backend framework.
Store completed artifacts in PostgreSQL so ephemeral web storage is acceptable.
Retain a single hosted instance rather than claiming a distributed durable queue.

Setup and reproducible demo: reliability.md. Dataset/reviewer/benchmark protocol:
evaluation-protocol.md. External account provisioning, live spending, independent
review and production verification are explicit checkpoints, not completed claims.

Verification notes: one upstream Starlette/AnyIO deprecation warning; all provider
transports were fake. PostgreSQL 17 backup restored 2 spending reservations and
16 artifacts into a separate empty local database. New CI jobs are defined;
consult GitHub Actions for the published release's remote results. Browser QA
found and fixed a stale job-ID cancellation race without relaxing CSP.

External database checkpoint: the user's Supabase Oregon session pooler passed
an encrypted read-only connection using the application's driver settings. No
schema/table changes or model calls were made; owner-live cloud acceptance is
still pending. Database credentials remain outside the repository.

## Historical checkpoints

### Local deployment-handoff regression fix

The owner service exposed a rolling-deployment deadlock: the predecessor held
the singleton lease while Render waited for the replacement's health check.
The fix starts replacements in API-blocked standby, activates only after lease
handoff, and prevents late workers overwriting recovered jobs. Regression tests
cover overlapping app instances, preserved active jobs/sessions, takeover,
retained spending and resumed mock execution. Local verification passed: 188
tests with disposable PostgreSQL enabled, plus browser checks including standby
bootstrap recovery and the existing mock/owner workflows. This release includes
the fix; consult GitHub Actions and /healthz execution_ready/deployment_state for
remote verification. No live model calls or Supabase writes were used in testing.

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
