# Secure and cost-conscious OpenAI and Groq execution

Default execution is mock. A key alone does not authorize a paid request.
Keep OPENAI_API_KEY/GROQ_API_KEY in the process environment; .env files are ignored
and load only with explicit `--env-file .env`. Never place keys in config,
prompts, Git, or chat. Each provider has a fixed
HTTPS endpoint rejects redirects, avoids raw error-body logging, and sends
`store=false` for OpenAI. Generation never receives references/rubrics. Judging is separate,
explicitly uncalibrated, and optional.

## Execution policy

Experiment JSON may contain this optional object (defaults shown):

```json
{
  "execution": {
    "allow_live": false,
    "max_run_usd": "0.10",
    "max_live_calls": 20,
    "case_ids": [],
    "all_cases": false,
    "max_retries": 2,
    "backoff_seconds": 1.0,
    "max_backoff_seconds": 8.0,
    "request_deadline_seconds": 60.0,
    "pricing_path": "configs/pricing.json"
  }
}
```

For live generation or a live judge, set allow_live explicitly (CLI `--live`),
select case_ids (`--case-ids vb-001 vb-002`) or deliberately select all_cases
(`--all-cases`), and configure a local key. Both selection modes cannot be used
together. Unknown IDs/models or missing pricing/key block before transport.
Defaults remain safe in existing live example configs. CLI flags override their
corresponding policy fields; calling the Python runner enforces the same policy.

Unit tests never make live requests. Separate, explicitly authorized smoke tests
have been run; see docs/benchmarks/groq-live-v1. To perform a small
live smoke test yourself, use the one-case commands in README.md. Adding
`--judge-model gpt-4.1-mini` enables paid judging; `judge_max_tokens` defaults to
1024, separately from generation's `max_tokens` (256). Each run has its own budget;
two A/B runs do not share a session-wide dollar cap.

## Cost accounting

`configs/pricing.json` records source, verification date, version, currency, and
rates per million tokens for explicitly supported model IDs. Initially it supports
standard text Chat Completions with gpt-4.1-mini and its listed snapshot only.
No tools, images, audio, batch, priority tier, or automatic expensive fallback.
Review current official prices before live use and version any rate changes.
Each live run persists the complete rate snapshot used for its estimates.

Before every HTTP attempt, reserve uncached input cost plus maximum configured
output cost. Input estimation uses UTF-8 content bytes plus framing allowance,
including system/judge instructions. This deliberately conservative heuristic is
not an exact tokenizer or a guaranteed bound on provider billing.

When usage is returned, estimate USD as:

`((input - cached) * input_rate + cached * cached_rate + output * output_rate) / 1,000,000`

Decimal arithmetic avoids float rounding at budget boundaries. Missing cache
detail is treated as uncached input. Complete known usage replaces the attempt's
reservation with that estimate. Missing/invalid usage or an unknown resolved model
retains the reservation; unknown/differently priced resolved models halt the run.
If observed usage exceeds the estimate/limit, preserve it and stop further work.
This application cannot enforce a hard cap on the provider's final invoice.

Generation, judge requests, failed attempts, and retries all consume the same
20-attempt and $0.10 default budget. Denied attempts never reach transport or
consume an attempt slot. Stop reasons and skipped cases are persisted; output
directories cannot be reused. A limit exhausted during judging preserves the
successful generated response and marks the judge failure separately.

`run.json.api_attempts` records purpose, scenario ID, requested/resolved model,
retry index, status, available usage, reserved/accounted/estimated USD, and duration.
Available usage is captured before response completeness or judge-schema checks.
No raw HTTP error bodies or authorization headers enter these records. Unknown
usage is explicitly unknown, never free. Reports show known estimates, uncertain
attempt counts, total accounted reservations, and per-purpose usage. Historical
mock artifacts remain unchanged and contain no live billing evidence.

## Retries and timeouts

Retry HTTP 429 rate limits and HTTP 500/502/503/504, up to two retries. Delay is
exponential plus injected jitter, capped at eight seconds; honor numeric/date
Retry-After. If Retry-After exceeds the allowed wait or request deadline, stop
rather than retry early. Authentication, quota/billing exhaustion, invalid
requests, malformed/truncated output, and ambiguous timeouts are not retried.
Quota/authentication errors also halt remaining cases to avoid repeated failures.

Generation has a configurable socket timeout (default 30 seconds). A monotonic
60-second request deadline bounds subsequent attempts and waits, limits each
socket timeout to remaining time, and rejects late responses while retaining
usage. The standard-library socket timeout cannot forcibly interrupt a process
or guarantee an absolute wall-clock limit for a slowly arriving body. Unknown
timeout/failure usage retains reservations because the provider might have billed
the request. Never assume a retry is free or idempotent.

## Verification

Unit tests inject transports, clocks, jitter, and sleepers; no paid requests or
real backoff waits. An autouse fixture blocks socket connections. Tests cover
authorization/selection/pricing preflight, Decimal/cached-token calculations,
exact boundaries, retries/deadlines/rate limits, shared generation/judge caps,
truncation/invalid judge accounting, trace redaction, and saved partial results.
Skipped semantic cases also affect regression decisions through uncompleted rate.

Sources:
- [OpenAI model pricing](https://developers.openai.com/api/docs/models/gpt-4.1-mini)
- [Rate-limit guidance](https://developers.openai.com/api/docs/guides/rate-limits)
- [Error-code guidance](https://developers.openai.com/api/docs/guides/error-codes)

## Groq adapter

`provider: "groq"` uses GROQ_API_KEY and a fixed Groq Chat Completions endpoint.
It shares the tested budget/retry machinery with OpenAI; payload differences are
limited to provider options. The application User-Agent avoids the rejection
observed with Python's default transport header. GPT-OSS uses low reasoning and
hidden reasoning output. Usage, provider identity, model, latency, and estimates
are stored per attempt. No provider/model fallback occurs.

`judge_provider` optionally selects OpenAI or Groq independently. Otherwise the
judge uses the live generation provider (OpenAI for mock generation, preserving
the old convention). Preflight checks every required provider key. Judge models
must have a pricing entry, and generation/judging share one budget.

Groq examples use openai/gpt-oss-20b with conservative published paid rates;
cached input is priced as normal input because no cache discount is assumed.
Free-plan eligibility is determined by the account, not inferred from its key.
The application does not upgrade an account or switch to a paid plan. The pricing
snapshot records paid-equivalent estimates even if the account's actual charge
is zero. Verify account billing separately.

- [Groq API compatibility](https://console.groq.com/docs/openai)
- [Groq models/rates](https://console.groq.com/docs/models)
- [Groq Free plan limits](https://console.groq.com/docs/rate-limits)

## Hosted execution

The hosted adapter attaches a SQLite daily guard to the existing per-run ledger.
Reservations are committed before every generation/judge/retry transport call;
known usage reconciles them. Unknown usage and process interruption never trigger
an automatic refund. Defaults: $0.50 estimated and 50 attempts per UTC day across
the deployment. CLI/local-demo calls retain their existing per-run controls and
are outside the hosted daily ledger. See deployment.md for owner authentication,
persistent-storage requirements, and reset/recovery semantics. The public Blueprint
does not enable live execution or configure provider secrets.
