# Design, verification, and trade-offs

| Component | Purpose and design | Verification | Trade-off |
| --- | --- | --- | --- |
| Schemas/loader | Fail early on bad data; manifest hashes exact LF-normalized dataset bytes | test_schemas.py; CLI validate | Strict contracts require explicit schema migration |
| Provider boundary | Messages-only inference prevents answer leakage; mock avoids API cost | test_providers.py; fake HTTP transport | Mock measures plumbing, never model quality |
| Runner | One result per case, monotonic timing, hashes/config/code metadata | test_runner.py; repeat runs | Sequential execution is simple; no concurrency/load testing |
| Metrics | Explicit applicable checks separate format from semantic quality | test_evaluators.py | Exact/line-count checks cover only constrained tasks |
| Judge | Opt-in rubric ratings with strict 1–5 schema and separate errors | tests use fake judge; see judging.md | No human calibration or ground-truth claim |
| Comparison | Paired case identity checks plus score/error/coverage gates | test_report.py and CLI degraded gate | Small sample, descriptive differences only; no statistical claim |
| Tracing | Per-run/case/judge OTel spans; content-free local export | test_telemetry.py; inspect traces.jsonl | Local export only; backend delivery and retention not implemented |
| CI | Locked install, tests, mock benchmark and intentional regression rejection | Local suite and passing remote Python 3.11/3.13 workflow, run 44331956136 | Live APIs and browser QA are intentionally separate from offline CI |
| Hosted HTTP | Starlette/Uvicorn reuses comparison orchestration; public mock with optional owner-only live | test_hosted.py and hosted browser check | Single worker/instance; cloud deployment still needs an actual HTTPS smoke check |
| Hosted state | SQLite persists sessions, job ownership/results, throttling and daily reservations | test_hosted_state.py, concurrent reservation and restart tests | Requires durable disk for live mode; interrupted jobs are not resumed automatically |

Operational caveats: up to two budgeted retries for transient rate limits and
selected server errors, with capped exponential backoff/jitter and Retry-After.
Quota/authentication errors halt the run; ambiguous timeouts are not retried.
Transport timeouts are socket timeouts; a checked deadline bounds further
requests/backoff, not a hard process-interruption guarantee. Output persistence
occurs after the run, so an interrupted process may leave traces without a final
run.json. Never reuse an output directory. Synthetic run.json files contain
response text; inspect before sharing. Model names/config support and credentials
must be checked during the first live smoke test. Unknown token counts/costs stay
unknown and retain reservations. Available usage on truncated/invalid judge
responses is retained. See api-integration.md for the accounting policy.

API/trace references used for implementation:
- https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create
- https://opentelemetry.io/docs/languages/python/instrumentation/
