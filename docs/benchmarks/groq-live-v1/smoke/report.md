# VaaniBench: groq-one-case-smoke

Run: `3d882a4fc7f9453dadbfd57ad8c01af5`
Provider: **groq**; model: `openai/gpt-oss-20b`.
Dataset: `0.1.0` / `f00e0ebc21535082094c13035e6d61e42527fe084dc5d163f5541113001beab2`.

Live-model run; inspect configuration and limitations before interpreting scores.

Requests: 1/1 successful; 0 errors; 0 skipped.
Deterministic scored cases: 1/1; mean: 1.0.
Unscored/failed: 0. Semantic safety/quality is not inferred from format checks.
Latency p50/p95 (ms, all attempts): 588.6942999986786 / 588.6942999986786.
Judge scored: 1; judge errors: 0. Judge ratings are uncalibrated.
Estimated USD: 0.0000732; accounted USD including uncertain reservations: 0.0000732; live attempts: 2.
Estimates are not invoices. Mock token usage/cost is unknown, not zero.

## Failure analysis

| Case | Language | Category | Status | Deterministic score | Error | Judge |
| --- | --- | --- | --- | --- | --- | --- |
| vb-001 | en | factual | ok | 1.0 | - | scored |

## Operational summary

```json
{
  "total": 1,
  "successful": 1,
  "errors": 0,
  "skipped": 0,
  "error_rate": 0.0,
  "uncompleted_rate": 0.0,
  "scored": 1,
  "not_scored": 0,
  "deterministic_score": 1.0,
  "latency_ms": {
    "p50": 588.6942999986786,
    "p95": 588.6942999986786,
    "scope": "all attempts, including errors"
  },
  "input_tokens": {
    "known_total": 112,
    "known_requests": 1,
    "successful_requests": 1
  },
  "output_tokens": {
    "known_total": 16,
    "known_requests": 1,
    "successful_requests": 1
  },
  "judge_scored": 1,
  "judge_errors": 0,
  "judge_input_tokens": 388,
  "cost_usd": "0.0000732",
  "known_estimated_cost_usd": "0.0000732",
  "accounted_usd": "0.0000732",
  "live_api_calls": 2,
  "unknown_cost_attempts": 0,
  "api_usage": {
    "generation": {
      "attempts": 1,
      "input_tokens": 112,
      "output_tokens": 16,
      "cached_input_tokens": 0,
      "usage_unknown_attempts": 0,
      "accounted_usd": "0.0000132"
    },
    "judge": {
      "attempts": 1,
      "input_tokens": 388,
      "output_tokens": 103,
      "cached_input_tokens": 0,
      "usage_unknown_attempts": 0,
      "accounted_usd": "0.00006"
    }
  },
  "cost_reason": "USD values are estimates, not invoices. Accounted USD retains reservations for unknown usage; mock costs/usage remain unknown.",
  "stop_reason": null,
  "groups": {
    "language": {
      "en": {
        "total": 1,
        "errors": 0,
        "scored": 1,
        "score": 1.0
      }
    },
    "category": {
      "factual": {
        "total": 1,
        "errors": 0,
        "scored": 1,
        "score": 1.0
      }
    }
  }
}
```

Stored run.json contains responses; traces.jsonl contains operational metadata only.
Synthetic convenience sample; no child-safety certification or population-level claims.
