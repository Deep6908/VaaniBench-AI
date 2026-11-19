# VaaniBench

A CLI-first conversational AI evaluation and observability MVP built with Python
3.11+, Pydantic, pytest, and OpenTelemetry. It evaluates fixed synthetic
conversations, compares configurations, and enforces deterministic regressions.

**Status:** public mock demo deployed at https://vaanibench-ai.onrender.com. Groq generation/judging and a small
real A/B run have been executed; OpenAI is implemented but its account smoke test
returned quota exhaustion. No production deployment or child-safety claim.

## Deploy on Render

Use the tracked [render.yaml](render.yaml) Blueprint and
[deployment guide](docs/deployment.md). The initial hosted mode is public
mock-only, with no provider keys. It includes secure sessions, session-owned
results/downloads, throttling, bounded background jobs, a health endpoint, and
read-only recorded Groq evidence. The existing dark interface is reused.

Optional owner-only live hosting requires a password hash and durable storage:
external PostgreSQL (compatible with ephemeral web hosting), or a persistent
SQLite disk. The daily ledger survives restarts and covers both
configurations, judges, and retries. Defaults are $0.50 estimated and 50 attempts
per UTC day, in addition to existing per-run limits. Free Render storage is
ephemeral; use external PostgreSQL there. The public deployment remains mock-only;
the new PostgreSQL workflow requires external configuration before cloud verification.

Local additions include restart-safe report downloads, cancellation, idempotent
submissions, owner history/comparison, remote OTLP tracing, a separate 60-case
unreviewed draft dataset, human agreement tooling, and approval-gated repeated
benchmarks. See [reliability setup and demo](docs/reliability.md),
[evaluation protocol](docs/evaluation-protocol.md), and [progress](docs/progress.md).

## Present it live

```powershell
uv run --no-sync vaanibench demo
```

Open http://127.0.0.1:8765. Select cases/configurations, run a mock comparison,
watch case progress, expand responses and rubrics, and download results/traces.
The default six-case mock demo shows an intentional regression. Mock presentation
pacing is outside measured request latency. For the walkthrough and optional
credentialed Groq mode, see [the presentation guide](docs/demo.md).

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
judge spans when enabled, and a safe event for each live HTTP attempt. Result records retain the trace ID. Span attributes
contain operational IDs, categories/languages, status, latency, and known usage;
prompt/response text and API keys are excluded. Local exporter failure preserves
results and emits a warning. A hosted Langfuse/OTLP backend is not configured.

Inspect `run.json` for response text, safe error code, metric reason, judge error,
and usage; match its trace ID in `traces.jsonl`. Reports include error rate and
nearest-rank p50/p95 duration over all attempts (errors included). Unknown token
usage remains null. A versioned pricing snapshot estimates live USD costs;
generation and judge attempts/usage are recorded separately. Mock token usage and
cost remain unknown. `accounted_usd` includes conservative reservations when live
usage is unavailable; it is not a statement of actual billed spend.

## Optional live evaluations

Unit tests make no live API calls. For a live demonstration you need an API account,
model access, and billing. Review current provider pricing and limit the first run.
Never paste a key into chat, source files, configs, or Git. On PowerShell 7:

```powershell
$env:OPENAI_API_KEY = Read-Host "OpenAI API key" -MaskInput
uv run --no-sync vaanibench run --config configs/openai-example.json --live --case-ids vb-001 --out artifacts/live-a
uv run --no-sync vaanibench run --config configs/openai-candidate.json --live --case-ids vb-001 --out artifacts/live-b
```

For an optional paid judge, add `--judge-model gpt-4.1-mini` to **both** run
commands and use fresh output paths. Each successful case then adds one judge
request before retries. Live execution requires `--live` (or
`execution.allow_live=true`) and explicit `--case-ids` (or config case IDs).
`--all-cases` is a separate deliberate full-dataset opt-in. A key alone never
enables live execution, including a judge on mock generation. Configured model
names must have a verified entry in `configs/pricing.json`; no model fallback
occurs. Confirm access and supported Chat Completions parameters before use.
See [API safety and cost controls](docs/api-integration.md) for limits and retries.
`.env` files are ignored by Git but are **not automatically loaded**.
Load them explicitly with `--env-file .env`. The loader accepts only
OPENAI_API_KEY and GROQ_API_KEY, never executes variable expansion, and never
prints values. Groq configs use `provider: "groq"` and GROQ_API_KEY:

```powershell
uv run --no-sync vaanibench run --config configs/groq-baseline.json --env-file .env --live --case-ids vb-001 --out artifacts/groq-single-case
```

Groq's Free plan has provider-enforced limits; do not assume an arbitrary API key
is free-tier. Estimates use paid-equivalent rates, not evidence of a cash charge.
See the [executed Groq evidence](docs/benchmarks/groq-live-v1/README.md).

## Tests and CI

The original MVP had 68 passing tests. Current verification includes additional
API safety/accounting tests; see [checkpoint status](docs/progress.md).
The suite covers strict schemas/locations, dataset integrity, provider parsing and
safe errors, metric applicability, judge parsing/failure isolation, repeatability,
trace redaction/export failures, aggregation, regression thresholds, CLI exit
codes, and the end-to-end benchmark. Tests make no paid requests.
Pytest uses the ignored `.pytest-tmp` directory to keep Windows subprocess test
paths short; this directory is reserved for pytest and may be cleared by it.

`.github/workflows/ci.yml` installs locked dependencies on Python 3.11/3.13,
runs tests/validation, checks a passing repeated mock configuration, then asserts
that the deliberately degraded comparison exits 2. Mock artifacts are uploaded
for inspection. GitHub-hosted execution passed for implementation commit
`89398e6` on Python 3.11/3.13:
[verified workflow run](https://github.com/Deep6908/VaaniBench-AI/actions/runs/44331956136).
The hosted adapter adds security, isolation, persistence and deployment tests;
current verification is recorded in docs/progress.md.

## Architecture and engineering decisions

JSONL -> Pydantic validation -> provider adapter -> sequential runner -> metrics
-> JSON/Markdown reports -> paired gate. OpenTelemetry spans accompany execution.
The thin local and hosted web interfaces call the same engine. `demo` remains
loopback-only. The separate Starlette/Uvicorn hosted adapter uses SQLite for
sessions/jobs/daily accounting, exact public-origin checks, and owner-only live
execution. Its deployment target is one instance/worker; it is not a distributed
job queue or an authenticated multiuser SaaS service.

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
using cached locked dependencies; Python 3.11/3.13 are also covered by passing
remote CI for the deployed MVP. LLM judging has no human calibration. Remote OTLP
export is opt-in; real collector delivery and owner-live cloud operation remain
unverified. Speech and dynamic conversation simulation remain future work. Persistent run.json is
written at completion; an interrupted process may leave only partial traces.
No claims of production readiness, child safety, language-wide quality, model
improvement, or cost savings are supported by this MVP.
