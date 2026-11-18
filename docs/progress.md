# Implementation checklist

- [x] Checkpoint 1: strict schema, JSONL loader, version/hash manifest, 20 scenarios.
- [x] Checkpoint 2: mock provider, runner, deterministic metrics, CLI, results/reports.
- [x] Checkpoint 3: transport-tested live adapter, optional rubric judge, paired A/B.
- [x] Checkpoint 4: local OpenTelemetry traces, usage/error/latency summaries, gates.
- [x] Checkpoint 5: 68 passing tests, fresh locked environment install, local
  equivalent of CI gates, executed mock benchmark, final README and limitations.

Live API calls: not executed; no OPENAI_API_KEY configured. Judge calibration:
not performed. Hosted trace backend, speech, frontend, and deployment: deferred.
GitHub Actions: workflow prepared; remote execution requires a GitHub repository.

Offline results: 20 requests per configuration; 12 scored and eight unscored.
Baseline/repeat: 12/12 deterministic case checks; degraded: 5/12. Repeated
configuration gate passes; intentionally degraded gate fails. These are mock
fixture results, not LLM quality measurements. See docs/benchmarks/mock-v1/.
