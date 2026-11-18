# Implementation checklist

- [x] Checkpoint 1: strict schema, JSONL loader, version/hash manifest, 20 scenarios.
- [x] Checkpoint 2: mock provider, runner, deterministic metrics, CLI, results/reports.
- [x] Checkpoint 3: transport-tested live adapter, optional rubric judge, paired A/B.
- [x] Checkpoint 4: local OpenTelemetry traces, usage/error/latency summaries, gates.
- [x] Checkpoint 5: 68 passing tests, fresh locked environment install, local
  equivalent of CI gates, executed mock benchmark, final README and limitations.

Initial MVP verification was offline; subsequent live evidence appears below. Judge calibration:
not performed. Hosted trace backend, speech, frontend, and deployment: deferred.
GitHub Actions: workflow prepared; remote execution requires a GitHub repository.

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
Local unit/integration suite: 138 tests. Remote CI awaits the GitHub repository.
