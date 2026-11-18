import io
import json
import shutil
import time
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

import pytest

from vaanibench.costs import ExecutionDenied
from vaanibench.demo import DemoController, DemoHandler, DemoRequest, DEMO_IDS

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def controller(tmp_path):
    for folder in ["data", "configs"]:
        shutil.copytree(ROOT / folder, tmp_path / folder)
    return DemoController(tmp_path, pace_seconds=0)


def mock_request(**updates):
    return DemoRequest(**(dict(baseline="mock-baseline", candidate="mock-degraded", case_ids=DEMO_IDS) | updates))


def wait_for_result(controller, job):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = controller.snapshot(job)
        if result["status"] != "running": return result
        time.sleep(.01)
    pytest.fail("Offline demo did not finish")


def test_demo_vertical_slice_and_artifacts(controller):
    job = controller.start(mock_request())
    result = wait_for_result(controller, job)
    assert result["status"] == "completed"
    assert result["result"]["comparison"]["passed"] is False
    assert len(result["result"]["runs"]["baseline"]["cases"]) == 6
    assert len(result["events"]) == 28
    assert controller.snapshot(job, result["cursor"])["events"] == []
    assert controller.download(job,"baseline-run.json").exists()
    with pytest.raises(KeyError): controller.download(job,"../../.env")


def test_demo_blocks_live_and_concurrency(controller):
    with pytest.raises(ExecutionDenied):
        controller.start(mock_request(baseline="groq-baseline",candidate="groq-candidate",confirm_live=True))
    controller.active = True
    with pytest.raises(ValueError, match="already running"):
        controller.start(mock_request())


def test_invalid_selection_and_mixed_providers(controller):
    with pytest.raises(ValueError): controller.start(mock_request(case_ids=["vb-999"]))
    with pytest.raises(ValueError): controller.start(mock_request(case_ids=["vb-001","vb-001"]))
    with pytest.raises(ValueError): controller.start(mock_request(candidate="groq-candidate"))
    with pytest.raises(ValueError): controller.start(mock_request(judge=True))


def handler(controller, path, *, token=True, origin=None, host="127.0.0.1:8765", body=None):
    h = object.__new__(DemoHandler)
    h.server = SimpleNamespace(server_port=8765,controller=controller)
    h.path = path
    h.headers = Message()
    h.headers["Host"] = host
    if origin: h.headers["Origin"] = origin
    if token: h.headers["X-VaaniBench-Token"] = controller.token
    raw = json.dumps(body or {}).encode()
    h.headers["Content-Length"] = str(len(raw))
    h.headers["Content-Type"] = "application/json"
    h.rfile = io.BytesIO(raw)
    responses=[]
    h._send=lambda *args, **kwargs: responses.append(args)
    return h, responses


@pytest.mark.parametrize("path", ["/", "/app.js", "/styles.css", "/api/bootstrap"])
def test_http_static_and_bootstrap(controller,path):
    h, responses = handler(controller,path)
    h.do_GET()
    assert responses[0][0] == 200


def test_http_blocks_cross_origin_unknown_host_and_missing_token(controller):
    for kwargs in [dict(origin="https://external.invalid"),dict(host="evil.invalid:8765"),dict(token=False)]:
        h,responses=handler(controller,"/api/runs",**kwargs)
        h.do_POST()
        assert responses[0][0] == 403
    h,responses=handler(controller,"/.env")
    h.do_GET()
    assert responses[0][0] == 404


def test_http_post_and_cursor(controller):
    h,responses=handler(controller,"/api/runs",body=mock_request().model_dump())
    h.do_POST()
    assert responses[0][0] == 202
    job=responses[0][1]["job_id"]
    wait_for_result(controller,job)
    h,responses=handler(controller,f"/api/jobs/{job}?after=999")
    h.do_GET()
    assert responses[0][1]["events"] == []


def test_bootstrap_does_not_expose_keys(controller,monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY","test-credential-do-not-expose")
    content=json.dumps(controller.bootstrap())
    assert "test-credential-do-not-expose" not in content
    assert not controller.bootstrap()["providers"]["groq"]


def test_live_session_cap_without_network(controller, monkeypatch):
    from vaanibench import demo
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    controller.allow_live = True
    class Deferred:
        def __init__(self, **kwargs): pass
        def start(self): pass
    monkeypatch.setattr(demo.threading, "Thread", Deferred)
    request=mock_request(baseline="groq-baseline", candidate="groq-candidate", confirm_live=True)
    controller.start(request)
    assert controller.live_runs_remaining == 0
    controller.active = False
    with pytest.raises(ExecutionDenied, match="session_live_limit"):
        controller.start(request)


def test_live_requires_confirmation_even_when_server_enabled(controller, monkeypatch):
    controller.allow_live = True
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    with pytest.raises(ExecutionDenied, match="confirmed"):
        controller.start(mock_request(baseline="groq-baseline",candidate="groq-candidate"))
