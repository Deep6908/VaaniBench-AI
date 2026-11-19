# Rubric judging and calibration limits

Judging is opt-in because it adds a paid model request per successful candidate
response. Use the same judge model, seed, prompt version, and dataset for A/B.
Judge attempts and retries share the generation run's dollar/call limits. A judge
on mock generation still requires explicit live authorization, case selection,
and a key. Usage is retained even if the returned judge JSON fails validation.
`judge_max_tokens` configures its output cap independently of generation.
The prompt lives in evaluators.py; its SHA-256 and judge version are stored in
each judged run. The recorded config identifies the requested judge model.

Each scenario contains an explicit rubric and a reference example. The judge
sees the conversation, age/language, rubric, reference, and candidate response.
It returns strict integer scores in four dimensions (1–5), plus a rationale:
correctness, instruction following, privacy/safety, and age appropriateness.
Anchors and dimensions are in JUDGE_PROMPT. Invalid JSON, wrong keys/types, and
out-of-range values become judge errors, not passing scores. Candidate generation
never receives the reference/rubric. Judge time and usage are separate from
candidate latency/usage. Judges have no tools and do not follow candidate content
as instructions by design, but prompt injection and bias remain risks.

No calibration has been performed. The optional judge is not ground truth and
its scores are excluded from deterministic CI gates. Even a 5 in privacy/safety
cannot certify child safety. Same-family self-judging, language ability, reference
bias, verbosity bias, and non-determinism can affect results. JSON mode constrains
syntax; Pydantic validates structure; neither establishes judgment validity.

Before claiming calibrated judging:

1. Expand beyond this convenience sample; independently review language/rubrics.
2. Obtain human labels from at least two reviewers with a documented protocol.
3. Separate prompt-development/calibration cases from held-out evaluation cases.
4. Report human agreement, judge-human agreement, confusion/disagreement by
   dimension and language, and failure examples; retain all denominators.
5. Freeze judge prompt/model settings and evaluate on held-out labels before
   using any judge-derived regression threshold.

The current fake-judge tests establish parsing and error handling only.

Annotation-pack and agreement commands now implement this workflow without
manufacturing labels. See evaluation-protocol.md. They preserve split identity,
blind reviewer packets to model/judge identity, and reject incomplete or duplicate
human ratings. This tooling does not mean the judge has been calibrated.
