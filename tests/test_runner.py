import json

import pytest

from vaanibench.models import Experiment, Response
from vaanibench.providers import ProviderError


def test_repeatability_and_timing(execute):
    ticks = iter(float(i) for i in range(100))
    a = execute("first", clock=lambda: next(ticks))
    b = execute("second")
    for ca, cb in zip(a.cases, b.cases):
        assert ca.response == cb.response
        assert ca.metrics == cb.metrics
        assert ca.scenario_hash == cb.scenario_hash
        assert ca.latency_ms == 1000.0
    assert a.run_id != b.run_id


def test_failures_retained(execute):
    result = execute(mode="failure")
    assert len(result.cases) == 20
    assert all(c.status == "error" and c.response is None for c in result.cases)


def test_unexpected_error_redacted(execute):
    class Broken:
        def generate(self, messages):
            raise RuntimeError("private-secret-token")
    run = execute(provider=Broken())
    assert all(c.error_code == "unexpected_provider_error" for c in run.cases)
    assert "private-secret-token" not in run.model_dump_json()


def test_judge_failure_separate(execute, authorized_config):
    class BadJudge:
        def generate(self, messages):
            return Response(text='{"correctness":99}')
    run = execute(config=authorized_config(provider="mock", judge_model="gpt-4.1-mini"), judge=BadJudge())
    assert all(c.status == "ok" and c.judge_error == "judge_failed_or_invalid" for c in run.cases)


def test_trace_redaction_and_linkage(execute, tmp_path):
    run = execute()
    content = (tmp_path / "baseline/traces.jsonl").read_text(encoding="utf-8")
    spans = [json.loads(line) for line in content.splitlines()]
    assert len(spans) == 21
    case_spans = [s for s in spans if s["name"] == "case"]
    assert len(case_spans) == 20
    assert all(c.trace_id for c in run.cases)
    assert "What is 2" not in content
    assert "reference_answer" not in content
    assert "Authorization" not in content


def test_no_overwrite(execute):
    execute()
    with pytest.raises(ValueError, match="already contains"):
        execute()
