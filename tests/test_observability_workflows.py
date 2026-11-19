import json
import logging
from pathlib import Path

import pytest
from opentelemetry.sdk.trace.export import SpanExporter,SpanExportResult

from vaanibench.telemetry import TraceSession,SafeExporter,RedactedExporterLog
from vaanibench.hosted_state import StateStore
from vaanibench.operations import snapshot


def test_explicit_remote_export_keeps_local_and_redacts_errors(tmp_path,monkeypatch):
    from opentelemetry.exporter.otlp.proto.http import trace_exporter
    received=[]
    class Fake(SpanExporter):
        def __init__(self,**kwargs): pass
        def export(self,spans): received.extend(spans);return SpanExportResult.SUCCESS
        def shutdown(self): pass
    monkeypatch.setattr(trace_exporter,'OTLPSpanExporter',Fake)
    monkeypatch.setenv('VAANIBENCH_OTLP_ENABLED','true')
    monkeypatch.setenv('OTEL_EXPORTER_OTLP_TRACES_ENDPOINT','https://collector.invalid/v1/traces')
    trace=TraceSession(tmp_path/'traces.jsonl')
    with trace.tracer.start_as_current_span('fixture',attributes={'run.id':'test'}): pass
    trace.close()
    assert len(received)==1 and json.loads((tmp_path/'traces.jsonl').read_text())['name']=='fixture'
    record=logging.LogRecord('exporter',40,'',0,'secret %s',('DO-NOT-LOG',),None)
    RedactedExporterLog().filter(record)
    assert 'DO-NOT-LOG' not in record.getMessage()


def test_remote_failure_does_not_erase_results_or_leak_diagnostics():
    class Broken:
        def export(self,spans): raise RuntimeError('secret response body')
        def shutdown(self): raise RuntimeError('secret credential')
    safe=SafeExporter(Broken())
    with pytest.warns(RuntimeWarning) as captured:
        assert safe.export([])==SpanExportResult.FAILURE
        safe.shutdown()
    assert safe.failed and all('secret' not in str(item.message) for item in captured)


def test_invalid_remote_url_preserves_local_export(tmp_path,monkeypatch):
    monkeypatch.setenv('VAANIBENCH_OTLP_ENABLED','true')
    monkeypatch.setenv('OTEL_EXPORTER_OTLP_TRACES_ENDPOINT','https://secret:password@collector.invalid/v1/traces')
    with pytest.warns(RuntimeWarning,match='Remote tracing unavailable'):
        trace=TraceSession(tmp_path/'traces.jsonl')
    with trace.tracer.start_as_current_span('local'): pass
    trace.close()
    assert (tmp_path/'traces.jsonl').exists()


def test_generation_span_contains_no_response_content(execute,tmp_path):
    execute()
    spans=[json.loads(line) for line in (tmp_path/'baseline/traces.jsonl').read_text().splitlines()]
    assert len([span for span in spans if span['name']=='generation'])==20
    assert all('content' not in json.dumps(span['attributes']) for span in spans)


def test_operational_snapshot_empty_and_budget_alert(tmp_path):
    store=StateStore(tmp_path)
    limits=json.loads((Path(__file__).resolve().parents[1]/'configs/operations-thresholds.json').read_text())
    result=snapshot(store,limits)
    assert result['error_rate'] is None and result['p95_latency_ms'] is None
    assert result['alerts']==[] and result['by_mode']==dict(mock=0,live=0)
