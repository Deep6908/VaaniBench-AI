# VaaniBench

A conversational AI evaluation and observability project built with explicit
contracts, reproducible experiments, and evidence-backed conclusions.

Status: learning scaffold only. No evaluator or model-quality results exist yet.

## Development

Use Python 3.11 or newer. The local host currently has Python 3.13.

```powershell
uv sync --cache-dir .uv-cache
uv run --cache-dir .uv-cache pytest
```

The exercise files deliberately contain no implementation or tests yet.
Pytest will report no tests collected until Exercise 1 is implemented; this is
not a passing test suite. Commit uv.lock after the first successful sync so
other machines and CI can install the same dependency versions. The initial
dependency installation and uv.lock generation are now complete.

Read the [four-hour plan](docs/build-plan.md) and
[architecture](docs/architecture.md), then start with
[Milestone 1](docs/milestone-1.md).

## Planned flow

Versioned JSONL -> validated scenarios -> provider adapter -> turn-by-turn runner
-> metric results -> report. Each run will retain scenario content hashes,
provider configuration, metric versions, and errors. Later milestones add A/B
comparison, calibrated judging, tracing, operational monitoring, and CI gates.

Synthetic child-oriented prompts test defined behavior; they do not establish
that a system is safe for children. No real child data is needed for this project.

Only measured results from completed work may become resume claims.
