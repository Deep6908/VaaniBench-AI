"""Local OpenTelemetry export; only allowlisted operational fields enter spans."""
import json
import warnings
from pathlib import Path

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult


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
