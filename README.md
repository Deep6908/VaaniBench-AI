# VaaniBench

A CLI-first conversational AI evaluation and observability MVP built with Python
3.11+, Pydantic, pytest, and OpenTelemetry. It evaluates fixed synthetic
conversations, compares configurations, and enforces deterministic regressions.

**Status:** working offline MVP. Live adapter and rubric judging are transport/unit
tested, not live-validated. No production deployment or child-safety claim.

## Quick start

Run commands from the repository root. Install Python 3.11+ and uv first.
The development machine uses Python 3.13.1 and uv 0.11.6.

```powershell
uv sync --locked --cache-dir .uv-cache
uv run --no-sync pytest -q
uv run --no-sync vaanibench validate
uv run --no-sync python scripts/benchmark.py --out artifacts/my-first-benchmark
```

Use a new output directory for every benchmark. The benchmark generates baseline,
repeat, and deliberately degraded mock runs. It verifies that repeat passes and
known degradation fails. Results include JSON, Markdown, and OpenTelemetry JSONL.
No API key, paid request, or external tracing account is needed.

## Commands

```powershell
uv run --no-sync vaanibench run --config configs/mock-baseline.json --out artifacts/baseline-1
uv run --no-sync vaanibench run --config configs/mock-degraded.json --out artifacts/candidate-1
uv run --no-sync vaanibench compare --baseline artifacts/baseline-1/run.json --candidate artifacts/candidate-1/run.json --thresholds configs/thresholds.json --out artifacts/comparison-1
uv run --no-sync vaanibench report --run artifacts/baseline-1/run.json --out artifacts/regenerated-report.md
```

Exit codes: 0 success; 1 invalid input, provider/judge execution failure, or I/O
failure; 2 failed regression gate. A degraded response is a successful request
with a failing metric, so `run` may return 0 and `compare` return 2.

## Dataset and evaluation methodology

`data/scenarios.jsonl` contains 20 synthetic scenarios: four each for factual,
instruction, context, uncertainty, and privacy behaviors. Language labels: English
(10), Hindi (5), and Hindi-English code-switching (5). These are convenience
fixtures, not a representative multilingual or child-safety benchmark. No real
child data is used; language/rubric review has not been independently performed.

Strict input validation rejects bad types, extra fields, blank content, broken
turn order, duplicate IDs, malformed JSON, and blank lines. `data/manifest.json`
records version 0.1.0, schema 1.1, case count, provenance, and the dataset SHA-256.
Git attributes preserve LF bytes across platforms. Dataset edits require a new
version/hash and review. Schema 1.0 is accepted by the loader without explicit
checks; the canonical manifest requires 1.1.

The runner generates only the next response after a fixed conversation; history
is fixture data, not a simulated interactive agent. Providers receive messages
and experiment settings, never references, rubrics, or metric expectations.
The mock is a handwritten protocol fixture; its seed controls deterministic
injected degradation. Its canned answers do not demonstrate model intelligence.

Twelve cases have deterministic checks: normalized exact equality for constrained
answers, or nonempty line count for format. Eight privacy/uncertainty cases have
no deterministic correctness score. A line-count pass does not verify content;
an exact pass does not establish general factuality. Per-case means are averaged
only across scored successful cases. Reports display scored, unscored, failed,
and total denominators, plus language/category breakdowns.

Optional rubric judging returns four 1–5 ratings and evidence, validates the
response strictly, and records judge failures separately. It is **uncalibrated**,
excluded from deterministic CI gates, and not ground truth. See
[Judging and calibration](docs/judging.md).

## Reproducibility and A/B gates

Each `run.json` stores configuration, dataset/scenario hashes, requested/resolved
model identity, seed/settings, metric versions, UTC timestamp, Git revision/dirty
state, dependency-lock hash, responses, usage, errors, and durations. Runs have
unique IDs. Identical mock inputs produce identical response/score fields; IDs,
timestamps, traces, and timings naturally differ. Live seeds do not guarantee
identical model outputs.

Comparison requires the same dataset bytes, scenario IDs/hashes, metric version,
and judge configuration. It reports paired case deltas and missing scores. Gates
are configurable in `configs/thresholds.json`: maximum score drop, maximum error
rate increase, minimum paired scored coverage, and optional p95 latency ratio.
Latency gating is disabled by default because tiny mock timings are noisy. Judge
ratings are shown separately and never silently substituted for correctness.

## Observability and investigating failures

Every run writes `traces.jsonl` with OpenTelemetry evaluation/case spans, plus
judge spans when enabled. Result records retain the trace ID. Span attributes
contain operational IDs, categories/languages, status, latency, and known usage;
prompt/response text and API keys are excluded. Local exporter failure preserves
results and emits a warning. A hosted Langfuse/OTLP backend is not configured.

Inspect `run.json` for response text, safe error code, metric reason, judge error,
and usage; match its trace ID in `traces.jsonl`. Reports include error rate and
nearest-rank p50/p95 duration over all attempts (errors included). Unknown token
usage remains null. No verified pricing table is configured, so dollar cost is
unknown; model usage and judge usage are recorded separately.

## Optional live evaluations

No live API call was executed during offline verification. You need an API account,
model access, and billing. Review current provider pricing and limit the first run.
Never paste a key into chat, source files, configs, or Git. On PowerShell 7:

```powershell
$env:OPENAI_API_KEY = Read-Host "OpenAI API key" -MaskInput
uv run --no-sync vaanibench run --config configs/openai-example.json --out artifacts/live-a
uv run --no-sync vaanibench run --config configs/openai-candidate.json --out artifacts/live-b
```

For an optional paid judge, add `--judge-model gpt-4.1-mini` to **both** run
commands and use fresh output paths. Each successful case then adds one judge
request. Configured model names are examples; confirm access and supported
Chat Completions parameters before use. The adapter makes one bounded attempt
per request with no automatic retries. Incomplete responses become errors.
`.env` files are ignored by Git but are **not automatically loaded**.

## Tests and CI

Local verification: **68 tests passed**. The suite covers strict schemas/locations, dataset integrity, provider parsing and
safe errors, metric applicability, judge parsing/failure isolation, repeatability,
trace redaction/export failures, aggregation, regression thresholds, CLI exit
codes, and the end-to-end benchmark. Tests make no paid requests.
Pytest uses the ignored `.pytest-tmp` directory to keep Windows subprocess test
paths short; this directory is reserved for pytest and may be cleared by it.

`.github/workflows/ci.yml` installs locked dependencies on Python 3.11/3.13,
runs tests/validation, checks a passing repeated mock configuration, then asserts
that the deliberately degraded comparison exits 2. Mock artifacts are uploaded
for inspection. The equivalent workflow has been exercised locally; GitHub-hosted
execution is pending a remote repository and push.

## Architecture and engineering decisions

JSONL -> Pydantic validation -> provider adapter -> sequential runner -> metrics
-> JSON/Markdown reports -> paired gate. OpenTelemetry spans accompany execution.
There is no frontend, database, public paid-run endpoint, or deployment machinery.

See [architecture](docs/architecture.md), [component trade-offs](docs/engineering-notes.md),
[checkpoint status](docs/progress.md), and the original
[learning exercises](docs/milestone-1.md). `models.py` contains result/configuration
contracts; other modules retain the original documented boundaries.

## Limits and defensible claims

The [checked-in benchmark bundle](docs/benchmarks/mock-v1/README.md) contains
actual **mock-only** executions: baseline/repeat 12/12 deterministic case checks,
degraded 5/12, and eight unscored cases in every run. The gate detects the injected
regression; this is not evidence that any real LLM improved.

Fresh-environment installation and tests have been checked locally on Python 3.13
using cached locked dependencies. Python 3.11 and remote Actions still need CI
verification. LLM judging has no human calibration. Hosted tracing, speech,
production operations, and deployment remain out of scope. Persistent run.json is
written at completion; an interrupted process may leave only partial traces.
No claims of production readiness, child safety, language-wide quality, model
improvement, or cost savings are supported by this MVP.
