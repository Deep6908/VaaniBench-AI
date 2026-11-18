# Executed Groq evidence

These are real, explicitly authorized requests through Groq, separate from unit
tests. Model: openai/gpt-oss-20b. The exact configs, usage, model IDs, hashes,
timestamps, responses, and trace events are retained in the raw files.

| Execution | Selected cases | Result | Paid-equivalent USD estimate |
| --- | --- | --- | --- |
| Generation + uncalibrated judge smoke | vb-001 | Response 5; valid judge output; two successful attempts | 0.0000732 |
| Baseline prompt | vb-001, vb-006, vb-009 | 3/3 applicable checks | 0.000048000 |
| Candidate prompt | same three cases | 3/3 applicable checks | 0.000053025 |

Paired delta: 0.0. The deterministic regression gate passes. This does not show
an improvement. vb-006 counts nonempty lines in a Hindi fruit response; it does
not automatically judge fruit correctness or Hindi quality. The two remaining
cases constrain the numeric answer and corrected fictional character name.

Prices use published conservative paid rates, not proof of actual billing. The
account plan determines whether requests are free. No pricing-table value or
token counter is presented as a confirmed cash charge.

- [Smoke report](smoke/report.md), [response and judge](smoke/run.json)
- [Baseline](baseline/report.md), [candidate](candidate/report.md)
- [Paired comparison](comparison.md), [structured comparison](comparison.json)
- [Baseline traces](baseline/traces.jsonl)

These runs were produced during development: raw metadata honestly records the
then-current Git revision and dirty=true. They are not falsely labeled clean
release runs. Source and this evidence are preserved in the subsequent local
commit. No API keys or authorization headers are included.

An earlier Groq request was rejected with HTTP 403 using Python's default
transport header. A model-list diagnostic with the application User-Agent
succeeded; the subsequent generation/judge run also succeeded with that header.
Earlier OpenAI attempts returned quota exhaustion and produced no generation.
