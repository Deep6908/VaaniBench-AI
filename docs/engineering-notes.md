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
| CI | Locked install, tests, mock benchmark and intentional regression rejection | workflow plus locally executed equivalent | Remote CI not verified until pushed and run |

Operational caveats: no retries (one bounded paid attempt per call); transport
timeouts are socket timeouts, not a hard total run deadline. Output persistence
occurs after the run, so an interrupted process may leave traces without a final
run.json. Never reuse an output directory. Synthetic run.json files contain
response text; inspect before sharing. Model names/config support and credentials
must be checked during the first live smoke test. Unknown token counts/costs stay
unknown; billed usage on failed/truncated calls may be unavailable.

API/trace references used for implementation:
- https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create
- https://opentelemetry.io/docs/languages/python/instrumentation/
