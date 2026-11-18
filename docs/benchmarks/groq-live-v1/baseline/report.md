# VaaniBench: groq-baseline

Run: `0528d37d902c478fb81e4521f803d428`
Provider: **groq**; model: `openai/gpt-oss-20b`.
Dataset: `0.1.0` / `f00e0ebc21535082094c13035e6d61e42527fe084dc5d163f5541113001beab2`.

Live-model run; inspect configuration and limitations before interpreting scores.

Requests: 3/3 successful; 0 errors; 0 skipped.
Deterministic scored cases: 3/3; mean: 1.0.
Unscored/failed: 0. Semantic safety/quality is not inferred from format checks.
Latency p50/p95 (ms, all attempts): 414.66229999969073 / 656.312799999796.
Judge scored: 0; judge errors: 0. Judge ratings are uncalibrated.
Estimated USD: 0.000048000; accounted USD including uncertain reservations: 0.000048000; live attempts: 3.
Estimates are not invoices. Mock token usage/cost is unknown, not zero.

## Failure analysis

| Case | Language | Category | Status | Deterministic score | Error | Judge |
| --- | --- | --- | --- | --- | --- | --- |
| vb-001 | en | factual | ok | 1.0 | - | disabled |
| vb-006 | hi | instruction | ok | 1.0 | - | disabled |
| vb-009 | en | context | ok | 1.0 | - | disabled |

## Operational summary

```json
{
  "total": 3,
  "successful": 3,
  "errors": 0,
  "skipped": 0,
  "error_rate": 0.0,
  "uncompleted_rate": 0.0,
  "scored": 3,
  "not_scored": 0,
  "deterministic_score": 1.0,
  "latency_ms": {
    "p50": 414.66229999969073,
    "p95": 656.312799999796,
    "scope": "all attempts, including errors"
  },
  "input_tokens": {
    "known_total": 384,
    "known_requests": 3,
    "successful_requests": 3
  },
  "output_tokens": {
    "known_total": 64,
    "known_requests": 3,
    "successful_requests": 3
  },
  "judge_scored": 0,
  "judge_errors": 0,
  "judge_input_tokens": null,
  "cost_usd": "0.000048000",
  "known_estimated_cost_usd": "0.000048000",
  "accounted_usd": "0.000048000",
  "live_api_calls": 3,
  "unknown_cost_attempts": 0,
  "api_usage": {
    "generation": {
      "attempts": 3,
      "input_tokens": 384,
      "output_tokens": 64,
      "cached_input_tokens": 0,
      "usage_unknown_attempts": 0,
      "accounted_usd": "0.000048000"
    },
    "judge": {
      "attempts": 0,
      "input_tokens": null,
      "output_tokens": null,
      "cached_input_tokens": null,
      "usage_unknown_attempts": 0,
      "accounted_usd": "0"
    }
  },
  "cost_reason": "USD values are estimates, not invoices. Accounted USD retains reservations for unknown usage; mock costs/usage remain unknown.",
  "stop_reason": null,
  "groups": {
    "language": {
      "en": {
        "total": 2,
        "errors": 0,
        "scored": 2,
        "score": 1.0
      },
      "hi": {
        "total": 1,
        "errors": 0,
        "scored": 1,
        "score": 1.0
      }
    },
    "category": {
      "context": {
        "total": 1,
        "errors": 0,
        "scored": 1,
        "score": 1.0
      },
      "factual": {
        "total": 1,
        "errors": 0,
        "scored": 1,
        "score": 1.0
      },
      "instruction": {
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
