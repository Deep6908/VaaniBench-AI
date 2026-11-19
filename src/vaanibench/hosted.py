"""Single-instance hosted adapter: public mock, optional owner-only live execution."""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import threading
import time
import tempfile
import base64
import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager, ExitStack
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from .costs import ExecutionDenied
from .demo import DemoController, DemoRequest, DOWNLOADS, execute_comparison
from .hosted_auth import verify_password
from .hosted_state import RateLimited, StateStore
from .models import ExecutionPolicy
from .runner import preflight

COOKIE = "vaanibench_session"
WEB = Path(__file__).parent / "web"
SECURITY = {"Cache-Control":"no-store", "X-Content-Type-Options":"nosniff",
    "Referrer-Policy":"no-referrer", "Content-Security-Policy":"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"}


@dataclass
class Settings:
    root: Path
    state_dir: Path
    origin: str = "http://127.0.0.1:8765"
    production: bool = False
    live_enabled: bool = False
    persistent_storage_confirmed: bool = False
    owner_password_hash: str = field(default="", repr=False)
    database_url: str | None = field(default=None, repr=False)
    daily_usd: Decimal = Decimal("0.50")
    daily_calls: int = 50
    job_timeout_seconds: int = 180
    mock_pace_seconds: float = .1

    def __post_init__(self):
        self.root, self.state_dir = self.root.resolve(), self.state_dir.resolve()
        parsed = urlsplit(self.origin)
        if parsed.scheme not in {"http","https"} or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            raise ValueError("Configure one exact HTTP(S) origin without a path")
        if self.production and parsed.scheme != "https":
            raise ValueError("Production origin must use HTTPS")
        if not self.daily_usd.is_finite() or not Decimal("0") < self.daily_usd <= Decimal("100") or not 1 <= self.daily_calls <= 10000:
            raise ValueError("Invalid daily limits")
        if not 30 <= self.job_timeout_seconds <= 600:
            raise ValueError("Invalid job timeout")
        if self.database_url:
            database = urlsplit(self.database_url)
            from urllib.parse import parse_qs
            secure=parse_qs(database.query).get("sslmode", [""])[0] in {"require","verify-ca","verify-full"}
            local_development=not self.production and database.hostname in {'localhost','127.0.0.1','::1'}
            if database.scheme not in {"postgres", "postgresql"} or not database.hostname or not (secure or local_development):
                raise ValueError("Configure a PostgreSQL session/direct URL with TLS")
        if self.live_enabled and (not self.owner_password_hash or not (self.database_url or self.persistent_storage_confirmed)):
            raise ValueError("Live hosting requires owner authentication and confirmed persistent storage")
        if self.production and self.live_enabled and not self.database_url and (self.state_dir.is_relative_to(self.root) or self.state_dir.is_relative_to(Path(tempfile.gettempdir()).resolve())):
            raise ValueError("Live production state must be on a persistent mount outside project and temporary storage")
        if self.owner_password_hash:
            parts = self.owner_password_hash.split("$")
            if len(parts) != 4 or parts[0] != "pbkdf2_sha256" or not parts[1].isdigit() or not 600000 <= int(parts[1]) <= 2000000:
                raise ValueError("Invalid owner password hash")
            if not 16 <= len(base64.b64decode(parts[2],validate=True)) <= 64 or len(base64.b64decode(parts[3],validate=True)) != 32:
                raise ValueError("Invalid owner password hash")

    @classmethod
    def from_env(cls):
        return cls(root=Path.cwd(), state_dir=Path(os.environ.get("VAANIBENCH_STATE_DIR", "artifacts/hosted")),
            origin=os.environ.get("VAANIBENCH_ORIGIN", os.environ.get("RENDER_EXTERNAL_URL", "http://127.0.0.1:8765")).rstrip("/"),
            production=os.environ.get("VAANIBENCH_ENV") == "production",
            live_enabled=os.environ.get("VAANIBENCH_LIVE_ENABLED", "false") == "true",
            persistent_storage_confirmed=os.environ.get("VAANIBENCH_PERSISTENT_STORAGE", "false") == "true",
            owner_password_hash=os.environ.get("VAANIBENCH_OWNER_PASSWORD_HASH", ""),
            database_url=os.environ.get("VAANIBENCH_DATABASE_URL") or None,
            daily_usd=Decimal(os.environ.get("VAANIBENCH_DAILY_USD", "0.50")),
            daily_calls=int(os.environ.get("VAANIBENCH_DAILY_CALLS", "50")))


@contextmanager
def instance_lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    stream = (directory / "instance.lock").open("a+b")
    try:
        stream.seek(0, 2)
        if not stream.tell(): stream.write(b"1"); stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        stream.close()


class HostedService:
    def __init__(self, settings, *, defer_activation=False):
        self.settings = settings
        self.store = StateStore(settings.state_dir, daily_usd=settings.daily_usd, daily_calls=settings.daily_calls,
            database_url=settings.database_url, retention_seconds=7*86400 if settings.database_url else 3600)
        self.catalog = DemoController(settings.root, allow_live=settings.live_enabled, pace_seconds=0)
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="evaluation")
        self.stopping = threading.Event()
        self.submission_lock = threading.Lock()
        self.lease = None
        self.ready = threading.Event()
        self.leadership_shutdown = threading.Event()
        self.leadership_thread = None
        if not defer_activation: self.activate()

    def activate(self):
        # Recover only after acquiring the singleton lease. A standby instance
        # must never interrupt the predecessor's jobs or rotate its sessions.
        self.store.auth_revision(hashlib.sha256(self.settings.owner_password_hash.encode()).hexdigest())
        self.store.recover()
        self.store.cleanup()
        if not self.stopping.is_set(): self.ready.set()

    def await_leadership(self):
        from .storage import postgres_lease, LeaseBusy
        def take_over():
            while not self.stopping.is_set():
                try:
                    with postgres_lease(self.settings.database_url) as connection:
                        if self.stopping.is_set(): return
                        self.lease=connection
                        self.activate()
                        # Hold leadership until evaluation threads have drained,
                        # not merely until shutdown has been requested.
                        self.leadership_shutdown.wait()
                        self.ready.clear()
                        return
                except LeaseBusy:
                    pass
                except Exception:
                    self.ready.clear()
                    logging.getLogger(__name__).warning('Database activation unavailable; retrying without executing evaluations.')
                if self.stopping.wait(1): return
        self.leadership_thread=threading.Thread(target=take_over,name='database-handoff',daemon=True)
        self.leadership_thread.start()

    def start(self, selection, session, request_key=None):
        if not self.ready.is_set():
            raise RateLimited('Deployment handoff in progress. Try again shortly.')
        with self.submission_lock:
            fingerprint = hashlib.sha256(selection.model_dump_json().encode()).hexdigest()
            existing = self.store.find_submission(session["owner"],request_key,fingerprint)
            if existing: return existing
            return self._start(selection,session,request_key,fingerprint)

    def _start(self, selection, session, request_key, fingerprint):
        if self.stopping.is_set():
            raise RateLimited("Service is stopping. Try again shortly.")
        if len(set(selection.case_ids)) != len(selection.case_ids) or not set(selection.case_ids).issubset({c.id for c in self.catalog.cases}):
            raise ValueError("Select valid, unique conversations")
        configs = [self.catalog.configs[k].model_copy(deep=True) for k in [selection.baseline, selection.candidate]]
        if configs[0].provider != configs[1].provider:
            raise ValueError("Choose configurations from the same provider")
        live = any(c.provider != "mock" or c.judge_model for c in configs) or selection.judge
        if live and (not self.settings.live_enabled or session["role"] != "owner" or not selection.confirm_live):
            raise ExecutionDenied("Owner sign-in and live confirmation are required")
        if selection.judge and configs[0].provider == "mock":
            raise ValueError("Choose a live provider before adding a judge")
        for config in configs:
            config.execution = ExecutionPolicy.model_validate(config.execution.model_dump() | dict(
                allow_live=live, case_ids=selection.case_ids, all_cases=False,
                max_run_usd=min(config.execution.max_run_usd, Decimal("0.10")),
                max_live_calls=min(config.execution.max_live_calls, 20), pricing_path=str(self.settings.root / "configs/pricing.json")))
            config.judge_model = ("openai/gpt-oss-20b" if config.provider == "groq" else "gpt-4.1-mini") if selection.judge else None
            config.judge_provider = config.provider if selection.judge else None
            preflight(self.catalog.cases, config)
        job = self.store.create_job(session["owner"],request_key=request_key,request_hash=fingerprint)
        try:
            self.executor.submit(self._work, job, configs)
        except RuntimeError:
            self.store.finish(job,error="Service stopped before work could start.")
            raise RateLimited("Service is stopping. Try again shortly.") from None
        return job

    def _work(self, job, configs):
        deadline = time.monotonic() + self.settings.job_timeout_seconds
        def cancelled():
            if self.stopping.is_set() or time.monotonic() >= deadline: return True
            if self.lease is not None:
                try:
                    # A lost singleton lease stops further calls, never reconnects
                    # silently while another instance might own the database.
                    with self.submission_lock:
                        self.lease.execute("SELECT 1")
                        self.lease.commit()
                except Exception:
                    self.ready.clear()
                    self.stopping.set()
                    return True
            return self.store.cancelled(job)
        try:
            result = execute_comparison(self.settings.root, configs, self.settings.state_dir / "runs" / job,
                on_event=lambda side,event:self.store.event(job,side,event), pace_seconds=self.settings.mock_pace_seconds,
                daily_guard=self.store.daily_guard(job,stop_when=cancelled),
                should_stop=cancelled)
            artifacts={name:(self.settings.state_dir / "runs" / job / side / filename).read_text(encoding="utf-8")
                for name,(side,filename) in DOWNLOADS.items()}
            stopped=cancelled()
            self.store.finish(job, result=result, artifacts=artifacts,
                cancelled=stopped, error="Evaluation cancelled or interrupted; completed requests remain accounted." if stopped else None)
        except ExecutionDenied as exc:
            allowed = {"quota_exhausted", "http_401", "http_403", "resolved_model_pricing_mismatch", "daily_call_limit_reached", "daily_spend_limit_reached"}
            self.store.finish(job, error="Execution stopped: " + (str(exc) if str(exc) in allowed else "execution_denied"))
        except Exception:
            self.store.finish(job, error="Evaluation failed; no automatic retry was made.")

    def close(self):
        self.ready.clear()
        self.stopping.set()
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.leadership_shutdown.set()
        if self.leadership_thread: self.leadership_thread.join()


class BoundaryMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        settings = request.app.state.service.settings
        if request.url.path != "/healthz":
            expected = urlsplit(settings.origin).netloc
            if request.headers.get("host", "") != expected:
                return JSONResponse({"error":"Unrecognized host"}, status_code=400, headers=SECURITY)
            if request.url.path.startswith('/api/') and not request.app.state.service.ready.is_set():
                return JSONResponse({'error':'Deployment handoff in progress. The previous instance is draining; please retry shortly.'},
                    status_code=503,headers=SECURITY | {'Retry-After':'3'})
            if request.method in {"GET","HEAD"} and request.url.path.startswith("/api/"):
                store = request.app.state.service.store
                try:
                    await asyncio.to_thread(store.rate,"api_reads",2400,60)
                    identity = await asyncio.to_thread(store.session,request.cookies.get(COOKIE))
                    request.state.identity=identity
                    if identity: await asyncio.to_thread(store.rate,"read:"+identity["owner"],600,60)
                except RateLimited:
                    return JSONResponse({"error":"Read rate limit reached. Try again shortly."},status_code=429,headers=SECURITY | {"Retry-After":"60"})
            if request.method not in {"GET","HEAD"}:
                if request.headers.get("origin") != settings.origin:
                    return JSONResponse({"error":"Same-origin request required"}, status_code=403, headers=SECURITY)
                session = await asyncio.to_thread(request.app.state.service.store.session,request.cookies.get(COOKIE))
                request.state.identity=session
                supplied = request.headers.get("x-vaanibench-token", "")
                if not session or len(supplied)>128 or not secrets.compare_digest(supplied.encode(),session["csrf"].encode()):
                    return JSONResponse({"error":"Session authorization required"}, status_code=403, headers=SECURITY)
        response = await call_next(request)
        response.headers.update(SECURITY)
        if settings.production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response


def create_app(settings=None):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        with ExitStack() as stack:
            stack.enter_context(instance_lock(settings.state_dir))
            lease = None
            service = HostedService(settings,defer_activation=bool(settings.database_url))
            if settings.database_url:
                from .storage import postgres_lease,LeaseBusy
                try:
                    lease = stack.enter_context(postgres_lease(settings.database_url))
                    service.lease = lease
                    service.activate()
                except LeaseBusy:
                    service.await_leadership()
                except Exception:
                    service.close()
                    raise RuntimeError('Database activation failed; check connection settings and availability') from None
            app.state.service = service
            try: yield
            finally: await asyncio.to_thread(service.close)

    async def session(request):
        value = getattr(request.state,'identity',None)
        if not value: raise ExecutionDenied("Session expired. Refresh the page.")
        return value

    def cookie(response, token):
        response.set_cookie(COOKIE, token, max_age=3600, httponly=True,
            secure=urlsplit(settings.origin).scheme == "https", samesite="strict", path="/")
        return response

    async def payload(request):
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            raise ValueError("JSON request required")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>8192: raise ValueError("Request too large")
        return json.loads(body)

    async def health(request):
        try:
            def probe():
                with request.app.state.service.store.db() as db: db.execute("SELECT 1")
            await asyncio.to_thread(probe)
            service=request.app.state.service
            # Liveness must pass during standby so Render can route traffic and
            # retire the predecessor. The API remains 503 until activation.
            return JSONResponse({"status":"ok","mode":"owner-live" if settings.live_enabled else "public-mock",
                'execution_ready':service.ready.is_set(),
                'deployment_state':'active' if service.ready.is_set() else 'draining' if service.stopping.is_set() else 'standby'})
        except Exception:
            return JSONResponse({"status":"unavailable"},status_code=503)

    async def bootstrap(request):
        service = request.app.state.service
        await asyncio.to_thread(service.store.cleanup)
        token = None
        identity = getattr(request.state,'identity',None)
        if not identity: token,identity = await asyncio.to_thread(service.store.new_session)
        data = service.catalog.bootstrap()
        owner = identity["role"] == "owner"
        enabled = owner and settings.live_enabled
        usage = await asyncio.to_thread(service.store.daily_usage) if owner else None
        available = bool(usage and usage["calls"] < settings.daily_calls and Decimal(usage["accounted_usd"]) < settings.daily_usd)
        data.update(token=identity["csrf"], hosted=True, authenticated=owner,
            login_available=bool(settings.owner_password_hash), live_enabled=enabled,
            providers={k: enabled and v for k,v in data["providers"].items()},
            live_runs_remaining=2 if enabled and available else 0,
            daily_usage=usage,
            evidence_available=True)
        data["configs"] = [config for config in data["configs"] if config["provider"] == "mock" or enabled]
        response = JSONResponse(data)
        return cookie(response,token) if token else response

    async def login(request):
        service = request.app.state.service
        if not settings.owner_password_hash: return JSONResponse({"error":"Sign-in unavailable"},status_code=404)
        identity = await session(request)
        await asyncio.to_thread(service.store.rate,"login:"+identity["owner"],5,300)
        await asyncio.to_thread(service.store.rate,"global_login",30,900)
        body = await payload(request)
        password = body.get("password") if isinstance(body,dict) else None
        valid = isinstance(password,str) and await asyncio.to_thread(verify_password,password,settings.owner_password_hash)
        if not valid: return JSONResponse({"error":"Sign-in failed"},status_code=401)
        token,_ = await asyncio.to_thread(service.store.new_session,role="owner", old_token=request.cookies.get(COOKIE))
        return cookie(JSONResponse({"authenticated":True}),token)

    async def logout(request):
        token,_ = await asyncio.to_thread(request.app.state.service.store.new_session,old_token=request.cookies.get(COOKIE))
        return cookie(JSONResponse({"authenticated":False}),token)

    async def start(request):
        identity = await session(request)
        selection = DemoRequest.model_validate(await payload(request))
        key=request.headers.get("idempotency-key")
        if key is not None and (not 16 <= len(key) <= 128 or not all(c.isalnum() or c in "-_" for c in key)):
            raise ValueError("Invalid submission key")
        job = await asyncio.to_thread(request.app.state.service.start,selection,identity,key)
        return JSONResponse({"job_id":job},status_code=202)

    async def cancel(request):
        identity=await session(request)
        await asyncio.to_thread(request.app.state.service.store.cancel,request.path_params["job"],identity["owner"])
        return JSONResponse({"cancellation_requested":True})

    async def history(request):
        identity=await session(request)
        if identity["role"] != "owner": raise ExecutionDenied("Owner sign-in required")
        query=request.query_params.get("q","")
        status=request.query_params.get("status","")
        if len(query)>100 or status not in {"","running","completed","failed","cancelled","interrupted"}: raise ValueError("Invalid filter")
        return JSONResponse({"jobs":await asyncio.to_thread(request.app.state.service.store.history,identity["owner"],query,status)})

    async def historical_compare(request):
        identity=await session(request)
        if identity["role"] != "owner": raise ExecutionDenied("Owner sign-in required")
        body=await payload(request)
        if not isinstance(body,dict) or set(body)!={"baseline_job","candidate_job","baseline_side","candidate_side"}: raise ValueError("Invalid comparison")
        from .models import Run
        from .report import compare,Thresholds
        runs=[]
        for side in ["baseline","candidate"]:
            chosen=body[side+"_side"]
            if chosen not in {"baseline","candidate"}: raise ValueError("Invalid side")
            content=await asyncio.to_thread(request.app.state.service.store.artifact,body[side+"_job"],identity["owner"],chosen+"-run.json")
            runs.append(Run.model_validate_json(content))
        return JSONResponse(compare(*runs,Thresholds()))

    async def operations(request):
        identity=await session(request)
        if identity['role']!='owner': raise ExecutionDenied('Owner sign-in required')
        from .operations import snapshot
        thresholds=json.loads((settings.root/'configs/operations-thresholds.json').read_text(encoding='utf-8'))
        return JSONResponse(await asyncio.to_thread(snapshot,request.app.state.service.store,thresholds))

    async def snapshot(request):
        identity = await session(request)
        after = int(request.query_params.get("after","0"))
        if not 0 <= after <= 10000: raise ValueError("Invalid cursor")
        return JSONResponse(await asyncio.to_thread(request.app.state.service.store.snapshot,request.path_params["job"],identity["owner"],after))

    async def download(request):
        identity = await session(request)
        job, name = request.path_params["job"],request.path_params["name"]
        status = (await asyncio.to_thread(request.app.state.service.store.snapshot,job,identity["owner"]))["status"]
        if status != "completed" or name not in DOWNLOADS: raise KeyError("Unknown artifact")
        try: content=await asyncio.to_thread(request.app.state.service.store.artifact,job,identity["owner"],name)
        except KeyError:
            # Existing SQLite jobs from before migration may still have files.
            side,filename = DOWNLOADS[name]
            path = settings.state_dir / "runs" / job / side / filename
            if not path.is_file(): raise KeyError("Artifact expired")
            content=path.read_text(encoding="utf-8")
        return Response(content,media_type="application/octet-stream",headers={"Content-Disposition":f'attachment; filename="{name}"'})

    async def static(request):
        name = request.path_params.get("name","index.html")
        mime = {"index.html":"text/html", "app.js":"text/javascript", "styles.css":"text/css"}
        if name not in mime: raise KeyError("Not found")
        return FileResponse(WEB/name,media_type=mime[name]+"; charset=utf-8")

    async def evidence(request):
        directory = settings.root / "docs/benchmarks/groq-live-v1"
        if "name" in request.path_params:
            name = request.path_params["name"]
            if name not in DOWNLOADS: raise KeyError("Unknown evidence")
            side,filename = DOWNLOADS[name]
            return FileResponse(directory/side/filename,filename=name)
        from .report import load_run,summary
        runs = {side:load_run(directory/side/"run.json") for side in ["baseline","candidate"]}
        return JSONResponse(dict(comparison=json.loads((directory/"comparison.json").read_text(encoding="utf-8")),
            runs={side:dict(summary=summary(run),config=run.config.model_dump(mode="json"),cases=[c.model_dump(mode="json") for c in run.cases]) for side,run in runs.items()},
            downloads=list(DOWNLOADS), download_base="/api/evidence"))

    async def error(request, exc):
        if isinstance(exc,RateLimited): code,message=429,str(exc)
        elif isinstance(exc,ExecutionDenied): code,message=403,str(exc)
        elif isinstance(exc,KeyError): code,message=404,"Not found"
        elif isinstance(exc,ValueError): code,message=400,"Invalid request"
        else: code,message=500,"Request failed"
        return JSONResponse({"error":message},status_code=code,headers=SECURITY | ({"Retry-After":"60"} if code==429 else {}))

    routes = [Route("/healthz",health),Route("/api/bootstrap",bootstrap),Route("/api/login",login,methods=["POST"]),
        Route("/api/logout",logout,methods=["POST"]),Route("/api/runs",start,methods=["POST"]),
        Route("/api/history",history),Route("/api/compare",historical_compare,methods=["POST"]),
        Route('/api/operations',operations),
        Route("/api/jobs/{job}/cancel",cancel,methods=["POST"]),
        Route("/api/jobs/{job}",snapshot),Route("/api/jobs/{job}/download/{name}",download),
        Route("/api/evidence",evidence),Route("/api/evidence/{name}",evidence),Route("/",static),Route("/{name}",static)]
    app = Starlette(routes=routes,lifespan=lifespan,exception_handlers={Exception:error,ValueError:error,KeyError:error,ExecutionDenied:error,RateLimited:error})
    app.add_middleware(BoundaryMiddleware)
    return app


app = create_app()
