from pathlib import Path
import socket

import pytest

from vaanibench.models import Experiment, ExecutionPolicy
from vaanibench.costs import BudgetLedger, load_prices
from vaanibench.runner import run_evaluation

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Network access is forbidden in tests; inject a fake transport")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


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
