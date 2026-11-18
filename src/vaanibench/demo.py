"""Loopback-only presentation app that reuses the evaluation engine."""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import Field

from .costs import ExecutionDenied
from .models import Experiment, ExecutionPolicy
from .report import Thresholds, compare, summary, write_comparison, write_report
from .runner import preflight, run_evaluation
from .providers import KEY_NAMES
from .schemas import Contract, Text, validate_dataset

CONFIGS = {name: f"{name}.json" for name in ["mock-baseline", "mock-degraded", "openai-example", "openai-candidate", "groq-baseline", "groq-candidate"]}
DEMO_IDS = ["vb-001", "vb-005", "vb-009", "vb-013", "vb-017", "vb-018"]
DOWNLOADS = {f"{side}-{name}": (side, name) for side in ["baseline", "candidate"]
    for name in ["run.json", "report.md", "traces.jsonl"]}
DOWNLOADS.update({"comparison.json": ("", "comparison.json"), "comparison.md": ("", "comparison.md")})


class DemoRequest(Contract):
    baseline: Literal["mock-baseline", "mock-degraded", "openai-example", "openai-candidate", "groq-baseline", "groq-candidate"]
    candidate: Literal["mock-baseline", "mock-degraded", "openai-example", "openai-candidate", "groq-baseline", "groq-candidate"]
    case_ids: Annotated[list[Text], Field(min_length=1, max_length=6)]
    judge: bool = False
    confirm_live: bool = False


def execute_comparison(root, configs, output, *, on_event, pace_seconds=0, daily_guard=None, should_stop=None):
    """Shared orchestration for local and hosted adapters; inference remains in runner."""
    runs = {}
    for side, config in zip(["baseline", "candidate"], configs):
        def listener(event, side=side, config=config):
            on_event(side, event)
            if config.provider == "mock" and event["event"] == "case_completed" and pace_seconds:
                time.sleep(pace_seconds)
        run = run_evaluation(root / "data/scenarios.jsonl", root / "data/manifest.json",
            config, output / side, on_event=listener, daily_guard=daily_guard, should_stop=should_stop)
        write_report(run, output / side / "report.md")
        runs[side] = run
        if run.stop_reason in {"quota_exhausted", "http_401", "http_403", "resolved_model_pricing_mismatch"}:
            raise ExecutionDenied(run.stop_reason)
    comparison = compare(runs["baseline"], runs["candidate"], Thresholds())
    (output / "comparison.json").write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    write_comparison(comparison, output / "comparison.md")
    return dict(comparison=comparison, runs={side: dict(summary=summary(run),
        config=run.config.model_dump(mode="json"), cases=[c.model_dump(mode="json") for c in run.cases])
        for side, run in runs.items()}, downloads=list(DOWNLOADS))


class DemoController:
    def __init__(self, root: Path, *, allow_live=False, pace_seconds=.2):
        self.root = root.resolve()
        self.allow_live, self.pace_seconds = allow_live, pace_seconds
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.active = False
        self.live_runs_remaining = 2
        self.jobs: dict[str, dict] = {}
        self.cases, self.manifest = validate_dataset(self.root / "data/scenarios.jsonl", self.root / "data/manifest.json")
        self.configs = {name: Experiment.model_validate_json((self.root / "configs" / filename).read_text(encoding="utf-8"))
            for name, filename in CONFIGS.items()}

    def bootstrap(self):
        return dict(token=self.token, dataset_version=self.manifest.dataset_version,
            live_enabled=self.allow_live and any(os.environ.get(k) for k in KEY_NAMES.values()),
            providers={name: self.allow_live and bool(os.environ.get(key)) for name, key in KEY_NAMES.items()},
            live_runs_remaining=self.live_runs_remaining, default_ids=DEMO_IDS,
            configs=[dict(id=k, name=v.name, provider=v.provider, model=v.model, system_prompt=v.system_prompt)
                for k, v in self.configs.items()],
            scenarios=[dict(id=c.id, language=c.language, category=c.category,
                prompt=c.messages[-1].content, rubric=c.rubric, turns=len(c.messages), checks=len(c.checks)) for c in self.cases])

    def start(self, request: DemoRequest) -> str:
        if len(set(request.case_ids)) != len(request.case_ids) or not set(request.case_ids).issubset({c.id for c in self.cases}):
            raise ValueError("Select one to six unique, valid scenarios.")
        configs = [self.configs[k].model_copy(deep=True) for k in [request.baseline, request.candidate]]
        if configs[0].provider != configs[1].provider:
            raise ValueError("Choose configurations from the same execution mode.")
        live = any(c.provider != "mock" or c.judge_model for c in configs) or request.judge
        if request.judge and configs[0].provider == "mock":
            raise ValueError("Judging requires explicitly enabled live generation.")
        if live and (not self.allow_live or not request.confirm_live):
            raise ExecutionDenied("live_not_enabled_or_confirmed")
        for config in configs:
            config.execution = ExecutionPolicy.model_validate(config.execution.model_dump() | dict(
                allow_live=live, case_ids=request.case_ids, all_cases=False,
                max_run_usd=min(config.execution.max_run_usd, Decimal("0.10")),
                max_live_calls=min(config.execution.max_live_calls, 20),
                pricing_path=str(self.root / "configs/pricing.json")))
            config.judge_model = ("openai/gpt-oss-20b" if config.provider == "groq" else "gpt-4.1-mini") if request.judge else None
            config.judge_provider = config.provider if request.judge else None
            preflight(self.cases, config)
        with self.lock:
            if self.active:
                raise ValueError("An evaluation is already running.")
            if len(self.jobs) >= 20:
                raise ValueError("Demo history is full. Restart the local server for a new session.")
            if live and self.live_runs_remaining < 2:
                raise ExecutionDenied("demo_session_live_limit_reached")
            if live:
                self.live_runs_remaining -= 2
            self.active = True
            job_id = secrets.token_hex(12)
            self.jobs[job_id] = dict(status="running", events=[], result=None, error=None)
        threading.Thread(target=self._execute, args=(job_id, configs), daemon=True).start()
        return job_id

    def _publish(self, job_id, side, event):
        with self.lock:
            self.jobs[job_id]["events"].append(dict(side=side, **event))

    def _execute(self, job_id, configs):
        try:
            result = execute_comparison(self.root, configs, self.root / "artifacts/demo" / job_id,
                on_event=lambda side, event: self._publish(job_id, side, event),
                pace_seconds=self.pace_seconds)
            with self.lock:
                self.jobs[job_id].update(status="completed", result=result)
        except ExecutionDenied as exc:
            with self.lock:
                self.jobs[job_id].update(status="failed", error=f"Live comparison stopped: {exc}. Completed artifacts remain saved locally.")
        except Exception:
            with self.lock:
                self.jobs[job_id].update(status="failed", error="Evaluation could not finish. Inspect local artifacts and configuration.")
        finally:
            with self.lock:
                self.active = False

    def snapshot(self, job_id: str, after=0):
        with self.lock:
            if job_id not in self.jobs:
                raise KeyError("Unknown evaluation")
            job = self.jobs[job_id]
            return dict(status=job["status"], events=job["events"][after:],
                cursor=len(job["events"]), result=job["result"], error=job["error"])

    def download(self, job_id, name):
        with self.lock:
            if job_id not in self.jobs or self.jobs[job_id]["status"] != "completed" or name not in DOWNLOADS:
                raise KeyError("Unknown artifact")
        side, filename = DOWNLOADS[name]
        return self.root / "artifacts/demo" / job_id / side / filename


class DemoHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, content, mime="application/json", filename=None):
        if not isinstance(content, bytes):
            content = json.dumps(content).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(content)

    def _trusted(self):
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        return host in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"} and (
            origin is None or origin == f"http://{host}")

    def do_GET(self):
        if not self._trusted():
            return self._send(403, {"error": "Local same-origin access required."})
        parsed = urlsplit(self.path)
        controller = self.server.controller
        static = {"/": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/styles.css": ("styles.css", "text/css; charset=utf-8")}
        try:
            if parsed.path in static:
                name, mime = static[parsed.path]
                return self._send(200, (Path(__file__).parent / "web" / name).read_bytes(), mime)
            if parsed.path == "/api/bootstrap":
                return self._send(200, controller.bootstrap())
            parts = parsed.path.strip("/").split("/")
            if len(parts) == 3 and parts[:2] == ["api", "jobs"]:
                after = max(0, int(parse_qs(parsed.query).get("after", ["0"])[0]))
                return self._send(200, controller.snapshot(parts[2], after))
            if len(parts) == 5 and parts[:2] == ["api", "jobs"] and parts[3] == "download":
                path = controller.download(parts[2], parts[4])
                return self._send(200, path.read_bytes(), "application/octet-stream", parts[4])
        except (KeyError, ValueError, OSError):
            pass
        self._send(404, {"error": "Not found."})

    def do_POST(self):
        if not self._trusted() or not secrets.compare_digest(self.headers.get("X-VaaniBench-Token", ""), self.server.controller.token):
            return self._send(403, {"error": "Local session authorization required."})
        if self.path != "/api/runs":
            return self._send(404, {"error": "Not found."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 8192 or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self._send(400, {"error": "A small JSON request is required."})
            request = DemoRequest.model_validate_json(self.rfile.read(length))
        except (ValueError, OSError):
            return self._send(400, {"error": "Invalid evaluation selection."})
        try:
            job_id = self.server.controller.start(request)
        except ExecutionDenied as exc:
            return self._send(403, {"error": str(exc)})
        except ValueError as exc:
            return self._send(409, {"error": str(exc)})
        self._send(202, {"job_id": job_id})


def make_server(root: Path, port=8765, *, allow_live=False, pace_seconds=.2):
    controller = DemoController(root, allow_live=allow_live, pace_seconds=pace_seconds)
    server = ThreadingHTTPServer(("127.0.0.1", port), DemoHandler)
    server.controller = controller
    return server


def serve(port=8765, *, allow_live=False):
    server = make_server(Path.cwd(), port, allow_live=allow_live)
    print(f"VaaniBench local demo: http://127.0.0.1:{server.server_port}", flush=True)
    print("Mock mode ready. Live mode requires local credentials and explicit confirmation.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
