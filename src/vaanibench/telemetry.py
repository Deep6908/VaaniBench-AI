"""Local OpenTelemetry export; only allowlisted operational fields enter spans."""
import json
import warnings
import os
import logging
from urllib.parse import urlsplit
from pathlib import Path

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import get_current_span


def record_api_attempt(attempt):
    attributes = {"api.attempt": attempt.number, "api.purpose": attempt.purpose,
        "api.model": attempt.model, "api.provider": attempt.provider, "api.status": attempt.status,
        "api.retry_index": attempt.retry_index, "api.latency_ms": attempt.latency_ms,
        "api.reserved_usd": str(attempt.reserved_usd),
        "api.accounted_usd": str(attempt.accounted_usd)}
    attributes.update({k: v for k, v in attempt.usage.model_dump().items() if v is not None})
    if attempt.estimated_cost_usd is not None:
        attributes["api.estimated_cost_usd"] = str(attempt.estimated_cost_usd)
    get_current_span().add_event("api.attempt", attributes)


class JsonlExporter(SpanExporter):
    def __init__(self, path: Path):
        self.path = path
        self.failed = False

    def export(self, spans):
        try:
            with self.path.open("a", encoding="utf-8") as stream:
                for span in spans:
                    stream.write(json.dumps(json.loads(span.to_json()), ensure_ascii=False) + "\n")
            return SpanExportResult.SUCCESS
        except OSError:
            self.failed = True
            warnings.warn("Trace export failed; evaluation results are preserved.", RuntimeWarning)
            return SpanExportResult.FAILURE


class TraceSession:
    def __init__(self, path: Path):
        self.provider = TracerProvider(resource=Resource.create({"service.name": "vaanibench"}))
        self.exporter = JsonlExporter(path)
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.remote = None
        if os.environ.get('VAANIBENCH_OTLP_ENABLED')=='true':
            try:
                endpoint=os.environ.get('OTEL_EXPORTER_OTLP_TRACES_ENDPOINT','')
                parsed=urlsplit(endpoint)
                if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                    raise ValueError('Explicit HTTPS collector URL required')
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                # Library delivery errors can include response bodies or URLs.
                # Replace their diagnostics with one non-sensitive message.
                for name in ['opentelemetry.exporter.otlp.proto.http.trace_exporter',
                             'opentelemetry.exporter.http_transport']:
                    target=logging.getLogger(name)
                    if not any(isinstance(f,RedactedExporterLog) for f in target.filters): target.addFilter(RedactedExporterLog())
                self.remote=SafeExporter(OTLPSpanExporter(endpoint=endpoint,timeout=3))
                self.provider.add_span_processor(BatchSpanProcessor(self.remote,max_queue_size=512,max_export_batch_size=128,export_timeout_millis=5000))
            except Exception:
                warnings.warn('Remote tracing unavailable; local traces remain enabled.',RuntimeWarning)
        self.tracer = self.provider.get_tracer("vaanibench", "0.1.0")

    def close(self):
        self.provider.shutdown()


class RedactedExporterLog(logging.Filter):
    def filter(self,record):
        record.msg='Telemetry exporter reported a delivery error.'
        record.args=()
        record.exc_info=None
        record.exc_text=None
        return True


class SafeExporter(SpanExporter):
    def __init__(self,delegate): self.delegate,self.failed=delegate,False

    def export(self,spans):
        try: result=self.delegate.export(spans)
        except Exception: result=SpanExportResult.FAILURE
        if result!=SpanExportResult.SUCCESS:
            self.failed=True
            warnings.warn('Remote trace delivery failed; local traces and results are retained.',RuntimeWarning)
        return result

    def shutdown(self):
        try: self.delegate.shutdown()
        except Exception: warnings.warn('Remote tracing shutdown failed.',RuntimeWarning)
