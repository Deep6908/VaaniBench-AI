import io
import json
import time
from decimal import Decimal
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from vaanibench.hosted import Settings, create_app, instance_lock
from vaanibench.hosted_auth import password_hash

ROOT=Path(__file__).resolve().parents[1]
PASSWORD="a long test owner password"
PASSWORD_HASH=password_hash(PASSWORD)


@pytest.fixture
def settings(tmp_path):
    return Settings(root=ROOT,state_dir=tmp_path/"state",origin="https://testserver",mock_pace_seconds=0)


def boot(client):
    response=client.get("/api/bootstrap")
    assert response.status_code==200
    return response.json()


def headers(data):
    return {"Origin":"https://testserver","X-VaaniBench-Token":data["token"]}


def selection(**changes):
    return dict(baseline="mock-baseline",candidate="mock-degraded",case_ids=["vb-001","vb-005"]) | changes


def wait(client,job):
    for _ in range(300):
        response=client.get("/api/jobs/"+job)
        assert response.status_code==200
        if response.json()["status"]!="running": return response.json()
        time.sleep(.01)
    pytest.fail("Hosted job did not finish")


def login(client,data):
    response=client.post("/api/login",headers=headers(data),json={"password":PASSWORD})
    assert response.status_code==200
    return boot(client)


def test_public_mock_health_secure_cookie_and_headers(settings):
    with TestClient(create_app(settings),base_url=settings.origin) as client:
        assert client.get("/healthz").status_code==200
        response=client.get("/api/bootstrap")
        cookie=response.headers["set-cookie"]
        assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
        data=response.json()
        assert data["hosted"] and not data["live_enabled"]
        assert not data["login_available"]
        assert not any(data["providers"].values())
        assert all(config["provider"]=="mock" for config in data["configs"])
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        for path in ["/", "/styles.css", "/app.js"]:
            assert client.get(path).status_code==200
        assert client.get("/.env").status_code==404
        result=client.post("/api/runs",headers=headers(data),json=selection())
        assert result.status_code==202
        job=result.json()["job_id"]
        assert wait(client,job)["status"]=="completed"
        assert client.get(f"/api/jobs/{job}/download/comparison.json").status_code==200


def test_cross_user_jobs_and_downloads_are_hidden(settings):
    with TestClient(create_app(settings),base_url=settings.origin) as client:
        alice=boot(client)
        job=client.post("/api/runs",headers=headers(alice),json=selection()).json()["job_id"]
        wait(client,job)
        client.cookies.clear()
        boot(client)
        assert client.get("/api/jobs/"+job).status_code==404
        assert client.get(f"/api/jobs/{job}/download/comparison.json").status_code==404


def test_bad_host_origin_csrf_and_payload(settings):
    with TestClient(create_app(settings),base_url=settings.origin) as client:
        data=boot(client)
        assert client.get("/api/bootstrap",headers={"Host":"attacker.invalid"}).status_code==400
        assert client.post("/api/runs",headers={"Origin":"https://attacker.invalid","X-VaaniBench-Token":data["token"]},json=selection()).status_code==403
        assert client.post("/api/runs",headers={"Origin":settings.origin},json=selection()).status_code==403
        assert client.post("/api/runs",headers=headers(data),json={"secret":"never echo"}).status_code==400
        response=client.post("/api/runs",headers=headers(data),json={"big":"x"*9000})
        assert response.status_code==400 and "x"*100 not in response.text


def test_public_live_forbidden_even_with_key(settings,monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY","fake-key-never-use")
    with TestClient(create_app(settings),base_url=settings.origin) as client:
        data=boot(client)
        response=client.post("/api/runs",headers=headers(data),json=selection(baseline="groq-baseline",candidate="groq-candidate",confirm_live=True))
        assert response.status_code==403
        assert client.app.state.service.store.daily_usage()["calls"]==0


def test_live_startup_requires_auth_and_persistence(tmp_path):
    for kwargs in [dict(live_enabled=True),dict(live_enabled=True,owner_password_hash=PASSWORD_HASH)]:
        with pytest.raises(ValueError):
            Settings(ROOT,tmp_path,**kwargs)
    with pytest.raises(ValueError):
        Settings(ROOT,tmp_path,origin="http://testserver",production=True)
    with pytest.raises(ValueError):
        Settings(ROOT,tmp_path,origin="https://testserver",production=True,live_enabled=True,
            owner_password_hash=PASSWORD_HASH,persistent_storage_confirmed=True)


def test_login_rotation_logout_and_failed_login(settings):
    settings.owner_password_hash=PASSWORD_HASH
    with TestClient(create_app(settings),base_url=settings.origin) as client:
        before=boot(client)
        response=client.post("/api/login",headers=headers(before),json={"password":"wrong"})
        assert response.status_code==401 and "wrong" not in response.text
        owner=login(client,before)
        assert owner["authenticated"] and owner["token"]!=before["token"]
        assert not owner["live_enabled"]
        assert client.post("/api/logout",headers=headers(before)).status_code==403
        assert client.post("/api/logout",headers=headers(owner)).status_code==200
        assert not boot(client)["authenticated"]


def test_owner_live_uses_shared_daily_limit_and_survives_restart(settings,monkeypatch):
    from vaanibench import runner
    from vaanibench.providers import GroqProvider
    monkeypatch.setenv("GROQ_API_KEY","test-only-fake-key")
    settings.live_enabled=True
    settings.persistent_storage_confirmed=True
    settings.owner_password_hash=PASSWORD_HASH
    settings.daily_calls=1
    calls=[]
    def transport(request,timeout):
        calls.append(1)
        return io.BytesIO(json.dumps(dict(model="openai/gpt-oss-20b",choices=[dict(finish_reason="stop",message=dict(content="5"))],usage=dict(prompt_tokens=10,completion_tokens=1))).encode())
    monkeypatch.setattr(runner,"make_provider",lambda config,ledger,**kwargs:GroqProvider(config,ledger=ledger,transport=transport,**kwargs))
    with TestClient(create_app(settings),base_url=settings.origin) as client:
        owner=login(client,boot(client))
        request=selection(baseline="groq-baseline",candidate="groq-candidate",case_ids=["vb-001"],confirm_live=True)
        job=client.post("/api/runs",headers=headers(owner),json=request).json()["job_id"]
        result=wait(client,job)
        assert result["status"]=="completed"
        assert result["result"]["runs"]["candidate"]["cases"][0]["status"]=="skipped"
        assert len(calls)==1
        cookies=dict(client.cookies)
    with TestClient(create_app(settings),base_url=settings.origin) as client:
        client.cookies.update(cookies)
        owner=boot(client)
        assert owner["authenticated"] and owner["daily_usage"]["calls"]==1
        assert client.get("/api/jobs/"+job).status_code==200
        job2=client.post("/api/runs",headers=headers(owner),json=request).json()["job_id"]
        wait(client,job2)
        assert len(calls)==1


def test_saved_evidence_is_read_only_and_public(settings):
    with TestClient(create_app(settings),base_url=settings.origin) as client:
        response=client.get("/api/evidence")
        assert response.status_code==200
        assert len(response.json()["runs"]["baseline"]["cases"])==3
        assert client.get("/api/evidence/comparison.json").status_code==200
        assert client.get("/api/evidence/.env").status_code==404


def test_login_rate_limit(settings):
    settings.owner_password_hash=PASSWORD_HASH
    with TestClient(create_app(settings),base_url=settings.origin) as client:
        data=boot(client)
        for _ in range(5):
            assert client.post("/api/login",headers=headers(data),json={"password":"wrong"}).status_code==401
        response=client.post("/api/login",headers=headers(data),json={"password":"wrong"})
        assert response.status_code==429 and "retry-after" in response.headers


def test_single_worker_lock(tmp_path):
    with instance_lock(tmp_path):
        with pytest.raises(OSError):
            with instance_lock(tmp_path): pass


def test_health_reports_storage_failure(settings):
    with TestClient(create_app(settings),base_url=settings.origin) as client:
        client.app.state.service.store.database=settings.state_dir/"missing"/"unavailable.sqlite3"
        assert client.get("/healthz").status_code==503


def test_api_read_throttling_keeps_health_available(settings):
    with TestClient(create_app(settings),base_url=settings.origin) as client:
        boot(client)
        store=client.app.state.service.store
        identity=store.session(client.cookies.get("vaanibench_session"))
        window=int(store.clock()//60)
        with store.db(write=True) as db:
            db.execute("INSERT INTO rates VALUES(?,?,600,?)",("read:"+identity["owner"],window,(window+1)*60))
        assert client.get("/api/evidence").status_code==429
        assert client.get("/healthz").status_code==200


def test_standby_liveness_passes_but_api_cannot_execute(settings):
    with TestClient(create_app(settings),base_url=settings.origin) as client:
        data=boot(client)
        service=client.app.state.service
        service.ready.clear()
        health=client.get('/healthz')
        assert health.status_code==200 and health.json()['deployment_state']=='standby'
        assert not health.json()['execution_ready']
        assert client.get('/').status_code==200
        assert client.get('/api/bootstrap').status_code==503
        response=client.post('/api/runs',headers=headers(data),json=selection())
        assert response.status_code==503 and response.headers['retry-after']=='3'
        assert service.store.history('operator')==[]
