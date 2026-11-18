import io
import json
from decimal import Decimal
from urllib.error import HTTPError

import pytest

from vaanibench.cli import main
from vaanibench.costs import BudgetLedger, ExecutionDenied, load_prices
from vaanibench.models import ExecutionPolicy, Experiment
from vaanibench.providers import OpenAIProvider, ProviderError, NoRedirect
from vaanibench.report import compare, summary, Thresholds
from vaanibench.schemas import Message

MESSAGES = [Message(role="user", content="What is 2 + 3? Return only the number.")]


def body(text="5", finish="stop", usage=True):
    data = dict(model="gpt-4.1-mini-2025-04-14", choices=[dict(finish_reason=finish, message=dict(content=text))])
    if usage:
        data["usage"] = dict(prompt_tokens=100, completion_tokens=20, prompt_tokens_details=dict(cached_tokens=40))
    return data


def success(*args, **kwargs):
    return io.BytesIO(json.dumps(body()).encode())


def failure(code=429, error_code="rate_limit_exceeded", headers=None):
    return HTTPError("https://api.openai.com", code, "never log this secret body", headers or {},
        io.BytesIO(json.dumps(dict(error=dict(code=error_code))).encode()))


@pytest.mark.parametrize("live,selection,key,model", [
    (False, ["vb-001"], True, "gpt-4.1-mini"),
    (True, [], True, "gpt-4.1-mini"),
    (True, ["vb-999"], True, "gpt-4.1-mini"),
    (True, ["vb-001"], False, "gpt-4.1-mini"),
    (True, ["vb-001"], True, "unknown-model"),
])
def test_runner_preflight_blocks_without_transport(execute, authorized_config, monkeypatch, live, selection, key, model):
    config = authorized_config(model=model, execution=ExecutionPolicy(allow_live=live, case_ids=selection))
    if not key:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    def forbidden(*args, **kwargs):
        pytest.fail("Preflight must prevent all transport calls")
    with pytest.raises(ExecutionDenied):
        execute(config=config, provider=OpenAIProvider(config, transport=forbidden))


def test_missing_pricing_blocks_all_calls(execute, authorized_config, tmp_path):
    config = authorized_config()
    config.execution.pricing_path = str(tmp_path / "absent.json")
    with pytest.raises(OSError):
        execute(config=config)


def test_direct_adapter_cannot_bypass_opt_in(ledger):
    with pytest.raises(ExecutionDenied, match="live_not_enabled"):
        OpenAIProvider(Experiment(name="test"), ledger=ledger, transport=success).generate(MESSAGES)
    with pytest.raises(ExecutionDenied):
        OpenAIProvider(Experiment(name="test")).generate(MESSAGES)


def test_retry_backoff_and_attempt_accounting(authorized_config, ledger):
    waits, calls = [], []
    def transport(request, timeout):
        calls.append((json.loads(request.data)["model"], timeout))
        if len(calls) < 3:
            raise failure(429 if len(calls) == 1 else 503)
        return success()
    response = OpenAIProvider(authorized_config(), ledger=ledger, transport=transport,
        sleeper=waits.append, jitter=lambda: .5).generate(MESSAGES)
    assert waits == [1.5, 2.5]
    assert len(calls) == len(ledger.attempts) == 3
    assert all(model == "gpt-4.1-mini" for model, _ in calls)
    assert response.text == "5"
    assert [a.status for a in ledger.attempts] == ["http_429", "http_503", "ok"]
    assert [a.retry_index for a in ledger.attempts] == [0, 1, 2]
    assert ledger.attempts[0].estimated_cost_usd is None
    assert ledger.attempts[-1].estimated_cost_usd == Decimal("0.00006")


@pytest.mark.parametrize("header,expected_waits,expected_calls", [("3", [3.0], 2), ("120", [], 1), ("invalid", [1.0], 2)])
def test_retry_after_is_respected_or_stops(authorized_config, ledger, header, expected_waits, expected_calls):
    waits, calls = [], []
    def transport(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise failure(headers={"Retry-After": header})
        return success()
    provider = OpenAIProvider(authorized_config(), ledger=ledger, transport=transport,
        sleeper=waits.append, jitter=lambda: 0)
    if expected_calls == 1:
        with pytest.raises(ProviderError, match="retry_deadline_exceeded"):
            provider.generate(MESSAGES)
    else:
        provider.generate(MESSAGES)
    assert waits == expected_waits and len(calls) == expected_calls


@pytest.mark.parametrize("code,error", [(401, "invalid_api_key"), (403, "forbidden"),
    (400, "invalid_request"), (429, "insufficient_quota"), (429, "organization_usage_limit_exceeded")])
def test_terminal_errors_not_retried(authorized_config, ledger, code, error):
    calls = []
    def transport(*a, **k):
        calls.append(1)
        raise failure(code, error)
    with pytest.raises(ProviderError):
        OpenAIProvider(authorized_config(), ledger=ledger, transport=transport,
            sleeper=lambda _: pytest.fail("must not back off")).generate(MESSAGES)
    assert len(calls) == len(ledger.attempts) == 1


def test_deadline_bounds_retry_and_socket_timeout(authorized_config, ledger):
    class Clock:
        now = 0.0
        def read(self): return self.now
        def sleep(self, seconds): self.now += seconds
    clock = Clock()
    ledger.policy.request_deadline_seconds = 3.0
    timeouts = []
    def transport(request, timeout):
        timeouts.append(timeout)
        clock.now += 1.0
        raise failure()
    with pytest.raises(ProviderError, match="retry_deadline_exceeded"):
        OpenAIProvider(authorized_config(), ledger=ledger, transport=transport,
            clock=clock.read, sleeper=clock.sleep, jitter=lambda: 0).generate(MESSAGES)
    assert timeouts == [3.0, 1.0]


def test_timeout_not_retried_and_reservation_retained(authorized_config, ledger):
    def transport(*a, **k): raise TimeoutError("sensitive")
    with pytest.raises(ProviderError, match="timeout"):
        OpenAIProvider(authorized_config(), ledger=ledger, transport=transport).generate(MESSAGES)
    assert len(ledger.attempts) == 1
    assert ledger.attempts[0].estimated_cost_usd is None
    assert ledger.accounted_usd == ledger.attempts[0].reserved_usd


def test_incomplete_response_retains_usage(authorized_config, ledger):
    with pytest.raises(ProviderError, match="incomplete_response"):
        OpenAIProvider(authorized_config(), ledger=ledger, transport=lambda *a, **k:
            io.BytesIO(json.dumps(body(finish="length")).encode())).generate(MESSAGES)
    assert ledger.attempts[0].usage.input_tokens == 100
    assert ledger.attempts[0].estimated_cost_usd == Decimal("0.00006")


def test_retry_cannot_exceed_call_limit(authorized_config, ledger):
    ledger.policy.max_live_calls = 1
    def transport(*a, **k): raise failure()
    with pytest.raises(ExecutionDenied, match="call_limit_reached"):
        OpenAIProvider(authorized_config(), ledger=ledger, transport=transport,
            sleeper=lambda _: pytest.fail("do not wait when no retry budget remains"), jitter=lambda: 0).generate(MESSAGES)
    assert len(ledger.attempts) == 1


def test_selected_run_partial_results_and_judge_share_budget(execute, authorized_config, tmp_path):
    config = authorized_config(judge_model="gpt-4.1-mini", execution=ExecutionPolicy(
        allow_live=True, case_ids=["vb-001", "vb-002"], max_live_calls=1))
    adapter = OpenAIProvider(config, transport=success)
    judge = OpenAIProvider(config, transport=lambda *a, **k: pytest.fail("judge budget should be exhausted"))
    run = execute(config=config, provider=adapter, judge=judge)
    assert len(run.cases) == 2 and len(run.api_attempts) == 1
    assert run.cases[0].status == "ok" and run.cases[0].judge_error == "call_limit_reached"
    assert run.cases[1].status == "skipped"
    assert run.stop_reason == "call_limit_reached"
    assert (tmp_path / "baseline/run.json").exists()
    data = summary(run)
    assert data["skipped"] == 1 and data["errors"] == 0
    assert data["cost_usd"] == "0.00006"
    assert data["api_usage"]["generation"]["input_tokens"] == 100


def test_invalid_judge_preserves_billed_usage_and_purpose(execute, authorized_config):
    config = authorized_config(provider="mock", judge_model="gpt-4.1-mini",
        execution=ExecutionPolicy(allow_live=True, case_ids=["vb-001"]))
    judge = OpenAIProvider(config, json_mode=True, transport=lambda *a, **k:
        io.BytesIO(json.dumps(body(text='{"correctness":99}')).encode()))
    run = execute(config=config, judge=judge)
    assert run.cases[0].judge_error == "judge_failed_or_invalid"
    assert run.cases[0].judge_usage.input_tokens == 100
    assert run.api_attempts[0].purpose == "judge"
    assert run.api_attempts[0].estimated_cost_usd == Decimal("0.00006")


def test_spend_limit_blocks_before_first_call(execute, authorized_config):
    config = authorized_config(execution=ExecutionPolicy(allow_live=True,
        case_ids=["vb-001", "vb-002"], max_run_usd=Decimal("0.00000001")))
    run = execute(config=config, provider=OpenAIProvider(config,
        transport=lambda *a, **k: pytest.fail("budget must block transport")))
    assert [c.status for c in run.cases] == ["skipped", "skipped"]
    assert run.stop_reason == "spend_limit_reached" and not run.api_attempts


def test_mock_key_never_triggers_network(execute, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-do-not-use")
    assert not execute().api_attempts


def test_cli_requires_live_and_selection(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-do-not-use")
    base = ["run", "--config", "configs/openai-example.json", "--out", str(tmp_path)]
    assert main(base) == 1
    assert main(base + ["--live"]) == 1


def test_redirect_never_forwards_credentials():
    with pytest.raises(HTTPError):
        NoRedirect().redirect_request(type("R", (), {"full_url": "https://api.openai.com"})(),
            None, 302, "redirect", {}, "https://elsewhere.invalid")


def test_attempt_traces_and_artifacts_redact_secrets(execute, authorized_config, tmp_path, capsys):
    config = authorized_config(execution=ExecutionPolicy(allow_live=True, case_ids=["vb-001"]))
    run = execute(config=config, provider=OpenAIProvider(config, transport=success))
    raw = (tmp_path / "baseline/traces.jsonl").read_text()
    assert '"api.attempt"' in raw and '"api.estimated_cost_usd"' in raw
    for content in [raw, run.model_dump_json(), capsys.readouterr().out]:
        assert "test-key-not-real" not in content and "Authorization" not in content


def test_skip_cannot_hide_unscored_case_regression(execute):
    baseline = execute()
    candidate = baseline.model_copy(deep=True)
    candidate.cases[-1].status = "skipped"
    decision = compare(baseline, candidate, Thresholds())
    assert decision["mean_paired_delta"] == 0.0
    assert not decision["passed"]
    assert "uncompleted rate" in decision["failures"][0]


def test_late_response_preserves_usage_but_fails_deadline(authorized_config, ledger):
    now = [0.0]
    def transport(*a, **k):
        now[0] = 61.0
        return success()
    with pytest.raises(ProviderError, match="deadline_exceeded"):
        OpenAIProvider(authorized_config(), ledger=ledger, clock=lambda: now[0],
            transport=transport).generate(MESSAGES)
    assert ledger.attempts[0].estimated_cost_usd is not None


def test_attempt_cap_includes_generation_and_judge_requests(execute, authorized_config):
    config = authorized_config(judge_model="gpt-4.1-mini", execution=ExecutionPolicy(
        allow_live=True, case_ids=["vb-001", "vb-002"], max_live_calls=2))
    judge_json = json.dumps(dict(correctness=5, instruction_following=5,
        privacy_safety=5, age_appropriateness=5, rationale="fixture"))
    run = execute(config=config, provider=OpenAIProvider(config, transport=success),
        judge=OpenAIProvider(config, transport=lambda *a, **k:
            io.BytesIO(json.dumps(body(text=judge_json)).encode())))
    assert [a.purpose for a in run.api_attempts] == ["generation", "judge"]
    assert run.cases[0].judge is not None
    assert run.cases[1].status == "skipped"
    assert summary(run)["cost_usd"] == "0.00012"


def test_unknown_usage_report_retains_reservation(execute, authorized_config):
    config = authorized_config(execution=ExecutionPolicy(allow_live=True, case_ids=["vb-001"]))
    run = execute(config=config, provider=OpenAIProvider(config, transport=lambda *a, **k:
        io.BytesIO(json.dumps(body(usage=False)).encode())))
    data = summary(run)
    assert data["cost_usd"] is None and data["unknown_cost_attempts"] == 1
    assert Decimal(data["accounted_usd"]) > 0


def test_retry_exhausted_budget_marks_attempted_case_error(execute, authorized_config):
    config = authorized_config(execution=ExecutionPolicy(allow_live=True,
        case_ids=["vb-001", "vb-002"], max_live_calls=1))
    def transport(*a, **k): raise failure()
    run = execute(config=config, provider=OpenAIProvider(config, transport=transport,
        sleeper=lambda _: pytest.fail("no retry budget")))
    assert [c.status for c in run.cases] == ["error", "skipped"]
    assert len(run.api_attempts) == 1


def test_http_date_retry_after(monkeypatch):
    from datetime import datetime, timezone
    from vaanibench import providers
    class FixedDateTime:
        @staticmethod
        def now(tz): return datetime(2026, 11, 18, 10, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(providers, "datetime", FixedDateTime)
    quota, delay = providers.http_error_info(failure(headers={"Retry-After": "Wed, 18 Nov 2026 10:00:03 GMT"}))
    assert not quota and delay == 3.0


def test_quota_error_halts_remaining_cases(execute, authorized_config):
    config = authorized_config(execution=ExecutionPolicy(allow_live=True, case_ids=["vb-001", "vb-002"]))
    def transport(*a, **k): raise failure(error_code="insufficient_quota")
    run = execute(config=config, provider=OpenAIProvider(config, transport=transport))
    assert len(run.api_attempts) == 1
    assert run.stop_reason == "quota_exhausted"
    assert [c.status for c in run.cases] == ["error", "skipped"]


def test_cli_flags_budget_stop_even_if_final_response_succeeded(execute, monkeypatch, tmp_path):
    from vaanibench import cli
    run = execute()
    run.stop_reason = "resolved_model_pricing_mismatch"
    monkeypatch.setattr(cli, "run_evaluation", lambda *a, **k: run)
    assert main(["run", "--config", "configs/mock-baseline.json", "--out", str(tmp_path)]) == 1
