"""Local OpenTelemetry export; only allowlisted operational fields enter spans."""
import json
import warnings
from pathlib import Path

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
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
        self.tracer = self.provider.get_tracer("vaanibench", "0.1.0")

    def close(self):
        self.provider.shutdown()
