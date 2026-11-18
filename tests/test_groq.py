import io
import json

import pytest

from vaanibench.costs import BudgetLedger, ExecutionDenied, load_prices
from vaanibench.credentials import load_api_key_file
from vaanibench.models import Experiment, ExecutionPolicy
from vaanibench.providers import GroqProvider, make_provider
from vaanibench.schemas import Message


def test_groq_payload_separate_credentials_and_ledger(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")
    config = Experiment(name="groq", provider="groq", model="openai/gpt-oss-20b",
        execution=ExecutionPolicy(allow_live=True, case_ids=["vb-001"]))
    ledger = BudgetLedger(config.execution, load_prices("configs/pricing.json"))
    def transport(request, timeout):
        assert request.full_url == "https://api.groq.com/openai/v1/chat/completions"
        assert request.get_header("Authorization") == "Bearer test-groq-key"
        assert request.get_header("User-agent") == "VaaniBench/0.1"
        payload = json.loads(request.data)
        assert "store" not in payload
        assert payload["reasoning_format"] == "hidden"
        assert payload["response_format"] == {"type":"json_object"}
        assert "reference_answer" not in payload and "rubric" not in payload
        return io.BytesIO(json.dumps(dict(model=config.model, choices=[dict(finish_reason="stop",
            message=dict(content='{"answer":5}'))], usage=dict(prompt_tokens=10,completion_tokens=4))).encode())
    response = GroqProvider(config, ledger=ledger, transport=transport, json_mode=True).generate([Message(role="user",content="2+3?")])
    assert response.usage.input_tokens == 10
    assert ledger.attempts[0].provider == "groq" and ledger.attempts[0].estimated_cost_usd is not None
    assert isinstance(make_provider(config, ledger), GroqProvider)


def test_groq_generation_and_judge_share_provider(execute, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = Experiment(name="groq", provider="groq", model="openai/gpt-oss-20b", judge_model="openai/gpt-oss-20b",
        execution=ExecutionPolicy(allow_live=True, case_ids=["vb-001"], max_live_calls=1))
    def transport(*args, **kwargs):
        return io.BytesIO(json.dumps(dict(model=config.model, choices=[dict(finish_reason="stop",message=dict(content="5"))],usage=dict(prompt_tokens=10,completion_tokens=1))).encode())
    run = execute(config=config, provider=GroqProvider(config, transport=transport))
    assert run.cases[0].response.text == "5"
    assert run.cases[0].judge_error == "call_limit_reached"
    assert len(run.api_attempts) == 1 and run.api_attempts[0].provider == "groq"


def test_groq_never_uses_openai_key(execute, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-key")
    config = Experiment(name="groq", provider="groq", model="openai/gpt-oss-20b",
        execution=ExecutionPolicy(allow_live=True, case_ids=["vb-001"]))
    with pytest.raises(ExecutionDenied, match="missing_api_key"):
        execute(config=config)


def test_explicit_env_loader_atomic_and_private(tmp_path, monkeypatch, capsys):
    path = tmp_path / ".env"
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    path.write_text("# local\nOPENAI_API_KEY=\nexport GROQ_API_KEY='test-groq'\nOTHER=ignored\n")
    load_api_key_file(path)
    import os
    assert os.environ["GROQ_API_KEY"] == "test-groq"
    assert not capsys.readouterr().out
    path.write_text("GROQ_API_KEY=first\nGROQ_API_KEY=second\n")
    with pytest.raises(ExecutionDenied):
        load_api_key_file(path)
    assert os.environ["GROQ_API_KEY"] == "test-groq"
