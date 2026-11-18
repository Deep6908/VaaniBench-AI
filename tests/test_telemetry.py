import json

import pytest

from vaanibench.models import Experiment, Response, Usage
from vaanibench.telemetry import JsonlExporter


def test_export_failure_preserves_results(execute, monkeypatch):
    from opentelemetry.sdk.trace.export import SpanExportResult
    def fail(self, spans):
        self.failed = True
        return SpanExportResult.FAILURE
    monkeypatch.setattr(JsonlExporter, "export", fail)
    result = execute()
    assert len(result.cases) == 20
    assert all(c.status == "ok" for c in result.cases)


def test_real_export_write_failure(tmp_path):
    from opentelemetry.sdk.trace.export import SpanExportResult
    exporter = JsonlExporter(tmp_path / "missing" / "traces.jsonl")
    with pytest.warns(RuntimeWarning, match="Trace export failed"):
        assert exporter.export([]) == SpanExportResult.FAILURE
    assert exporter.failed


def test_judge_success_and_usage_traced(execute, tmp_path):
    class FakeJudge:
        def generate(self, messages):
            return Response(text=json.dumps(dict(correctness=4, instruction_following=4,
                privacy_safety=5, age_appropriateness=4, rationale="fixture evidence")),
                usage=Usage(input_tokens=80, output_tokens=40))
    result = execute(config=Experiment(name="judged", judge_model="fake-model"), judge=FakeJudge())
    assert all(c.judge and c.judge_usage.input_tokens == 80 for c in result.cases)
    assert result.judge_prompt_sha256
    spans = [json.loads(line) for line in (tmp_path / "baseline/traces.jsonl").read_text().splitlines()]
    assert len([s for s in spans if s["name"] == "judge"]) == 20
