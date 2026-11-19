# Evaluation evidence and review protocol

## Dataset proposal and draft

Keep data/scenarios.jsonl (20 cases) and existing demo defaults unchanged.
data/candidate-v0.2 contains a reproducible **unreviewed** 60-case candidate:

| Category | English | Hindi | Hinglish | Total |
| --- | ---: | ---: | ---: | ---: |
| Factual | 4 | 4 | 4 | 12 |
| Instruction | 4 | 4 | 4 | 12 |
| Context | 4 | 4 | 4 | 12 |
| Uncertainty | 4 | 4 | 4 | 12 |
| Privacy | 4 | 4 | 4 | 12 |

The 20 originals are development examples. Forty new assistant-authored examples
include corrections of false premises, instruction injection, history updates,
unjustified certainty, impersonation and privacy solicitation. Every case is
child-oriented synthetic text, not a real child's data or a safety certification.
Age appropriateness is a cross-cutting human/judge dimension. Fixed assistant
history is not a turn-by-turn conversation simulator.

Reproduce with `uv run --no-sync python scripts/build_candidate_dataset.py`.
Run validate with the candidate dataset and manifest explicitly selected. Byte
hashes and stable IDs are recorded. Registry metadata lists provenance, family,
review_status and split. Split sizes: development 20, calibration 15, heldout 25.
Translations/variants within the same new family remain in one split. All
review_status fields are pending. Reviewers must also inspect cross-family
near-duplicates before freezing the benchmark; family grouping is not proof that
there is no semantic leakage. Held-out prompts are public, not a secret test set.

## Independent review and calibration

1. Recruit at least two independent reviewers with relevant language competency.
   Record reviewer qualifications and pseudonymous IDs outside public artifacts.
2. Independently review prompts, references and rubrics before scoring outputs.
   Record issues and resolutions; maintain a new version/hash when editing cases.
3. On development/calibration data only, refine the judge prompt and scoring
   anchors. Keep held-out outputs and labels out of this tuning process.
4. Freeze judge provider/model, prompt hash/version, seed and output settings.
5. Generate an annotation pack from actual recorded runs. No model calls occur:

```text
vaanibench annotate --dataset data/candidate-v0.2/scenarios.jsonl --manifest data/candidate-v0.2/manifest.json --registry data/candidate-v0.2/registry.json --runs PATH_TO_RUN_JSON --out artifacts/review
```

Give each reviewer reviewer-samples.jsonl and their own reviewer-a/b.jsonl
template, not samples.jsonl (which contains judge scores/model metadata). The
reviewer view is blinded to judge/model identity. Replace null scores with human
ratings 1–5 for correctness, instruction_following, privacy_safety and
age_appropriateness, with a brief evidence-based rationale. Reviewers work
independently before discussing disagreements. Never have an LLM fill these files
and call them human labels. Tooling cannot verify reviewer independence by itself.

```text
vaanibench calibration --samples artifacts/review/samples.jsonl --labels artifacts/review/reviewer-a.jsonl artifacts/review/reviewer-b.jsonl --split heldout --out artifacts/review/agreement.json
```

The command rejects missing/invalid ratings, duplicate reviewer/sample pairs,
unknown samples, missing second reviewers and mixed frozen judge identities.
It reports human exact agreement and quadratic weighted kappa, judge deviation
from mean human scores, within-one agreement, missing judgments and disagreement
examples by language/dimension. Constant ratings can give degenerate agreement;
inspect distributions and examples rather than trusting a single statistic.

Agreement tooling is implemented; **independent labels and calibration are not**.
Define acceptance criteria with reviewers before interpreting held-out results.
Do not fit a threshold to held-out labels or certify child safety. Judge scores
remain excluded from deterministic CI gates, even after an agreement report.

## Repeated real-model benchmark: plan before spending

This command is a dry plan by default and makes no model calls:

```text
vaanibench benchmark --baseline configs/groq-baseline.json --candidate configs/groq-candidate.json --case-ids vb-001 vb-005 --repeats 2
```

It lists exact cases/configurations, repeats, pricing, implementation/dependency
hashes, a conservative generation reservation estimate, potential retries, maximum
authorized accounted USD and attempt count, and an approval hash. Judge request
cost depends on actual responses; the aggregate guard, not a dry estimate, bounds
authorized accounting. Defaults: $0.10 and 20 total attempts across all A/B runs,
repeats, retries and judges. Budget constraints may prevent completion.

Only after explicit user approval rerun the identical command with --execute,
--approve-plan HASH, --live, optional --env-file .env and a fresh --out directory.
A changed configuration, dataset, implementation or pricing changes the plan hash.
Do not automatically approve plans or run the entire dataset. Mock benchmarks
also support this workflow without --live and with zero provider spending.

Outputs include per-run manifests, responses, metrics, traces and reports,
benchmark.json and benchmark.md. Uncertainty uses a seeded percentile cluster
bootstrap by scenario; repeats do not count as independent scenario samples.
Only scenarios scored in every repeat contribute to the interval and mean;
partial-repeat coverage and omitted IDs are reported. Intervals are omitted
with fewer than two complete scored scenarios. Report all errors,
skips, unscored cases and judge failures. A narrow convenience-sample interval
does not establish population-level performance or improved child safety.

Existing real evidence remains the small checked-in Groq smoke/A/B bundle.
No new real-model benchmark was executed for this implementation.
