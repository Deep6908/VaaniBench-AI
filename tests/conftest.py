from pathlib import Path
import socket
import threading

import pytest

from vaanibench.models import Experiment, ExecutionPolicy
from vaanibench.costs import BudgetLedger, load_prices
from vaanibench.runner import run_evaluation

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    original_connect = socket.socket.connect
    original_pair = socket.socketpair
    local = threading.local()
    def blocked(connection, address, *args, **kwargs):
        # Windows asyncio uses the stdlib socketpair fallback for its wake-up pipe.
        # Permit that implementation's own loopback connection, never general I/O.
        if getattr(local,"socketpair",False) and isinstance(address,tuple) and address[0] in {"127.0.0.1","::1"}:
            return original_connect(connection,address,*args,**kwargs)
        raise AssertionError("Network access is forbidden in tests; inject a fake transport")
    def pair(*args, **kwargs):
        previous=getattr(local,"socketpair",False)
        local.socketpair=True
        try: return original_pair(*args,**kwargs)
        finally: local.socketpair=previous
    def blocked_connection(*args,**kwargs):
        raise AssertionError("Network access is forbidden in tests; inject a fake transport")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked_connection)
    monkeypatch.setattr(socket,"socketpair",pair)


@pytest.fixture
def authorized_config(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    def config(**changes):
        return Experiment(**(dict(name="test", provider="openai", model="gpt-4.1-mini",
            execution=ExecutionPolicy(allow_live=True, all_cases=True)) | changes))
    return config


@pytest.fixture
def ledger(authorized_config):
    return BudgetLedger(authorized_config().execution, load_prices(ROOT / "configs/pricing.json"))


@pytest.fixture
def execute(tmp_path):
    def run(name="baseline", mode="baseline", **kwargs):
        config = kwargs.pop("config", Experiment(name=name, mock_mode=mode))
        return run_evaluation(ROOT / "data/scenarios.jsonl", ROOT / "data/manifest.json",
                              config, tmp_path / name, **kwargs)
    return run
