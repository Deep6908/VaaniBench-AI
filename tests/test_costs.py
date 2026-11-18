from decimal import Decimal

import pytest
from pydantic import ValidationError

from vaanibench.costs import BudgetLedger, ExecutionDenied, load_prices, reserve_cost, usage_cost
from vaanibench.models import ExecutionPolicy, Usage

MODEL = "gpt-4.1-mini"


def test_safe_defaults():
    policy = ExecutionPolicy()
    assert not policy.allow_live
    assert policy.max_run_usd == Decimal("0.10")
    assert policy.max_live_calls == 20
    assert policy.case_ids == [] and not policy.all_cases


@pytest.mark.parametrize("field,value", [("max_run_usd", Decimal("0")),
    ("max_run_usd", Decimal("NaN")), ("max_run_usd", Decimal("Infinity")),
    ("max_live_calls", 0), ("max_live_calls", True), ("max_retries", 6),
    ("max_retries", -1), ("request_deadline_seconds", 0.0)])
def test_invalid_limits(field, value):
    with pytest.raises(ValidationError):
        ExecutionPolicy(**{field: value})


def test_selection_contract():
    with pytest.raises(ValidationError):
        ExecutionPolicy(case_ids=["vb-001", "vb-001"])
    with pytest.raises(ValidationError):
        ExecutionPolicy(case_ids=["vb-001"], all_cases=True)


def test_decimal_cost_and_cache(ledger):
    price = ledger.prices.price(MODEL)
    assert usage_cost(Usage(input_tokens=100, output_tokens=50, cached_input_tokens=40), price) == Decimal("0.000108")
    assert usage_cost(Usage(input_tokens=100), price) is None
    with pytest.raises(ValidationError):
        Usage(input_tokens=10, cached_input_tokens=11)


def test_authorization_and_unknown_model(ledger):
    for policy in [ExecutionPolicy(), ExecutionPolicy(allow_live=True)]:
        with pytest.raises(ExecutionDenied):
            BudgetLedger(policy, ledger.prices)
    with pytest.raises(ExecutionDenied, match="unpriced_model"):
        ledger.reserve("unknown-expensive-model", "generation", [], 16, 0)
    assert not ledger.attempts


def test_exact_reservation_boundary(ledger):
    messages = [dict(role="user", content="hi")]
    amount = reserve_cost(messages, 16, ledger.prices.price(MODEL))
    policy = ExecutionPolicy(allow_live=True, all_cases=True, max_run_usd=amount)
    boundary = BudgetLedger(policy, ledger.prices)
    attempt = boundary.reserve(MODEL, "generation", messages, 16, 0)
    assert attempt.reserved_usd == boundary.accounted_usd == amount
    with pytest.raises(ExecutionDenied, match="spend_limit_reached"):
        boundary.reserve(MODEL, "generation", messages, 16, 1)
    assert len(boundary.attempts) == 1


def test_reconcile_frees_unused_reservation_and_preserves_unknown(ledger):
    attempt = ledger.reserve(MODEL, "generation", [], 256, 0)
    reserved = attempt.reserved_usd
    ledger.reconcile(attempt, Usage())
    assert attempt.estimated_cost_usd is None and ledger.accounted_usd == reserved
    ledger.reconcile(attempt, Usage(input_tokens=10, output_tokens=1))
    assert ledger.accounted_usd == Decimal("0.0000056")


def test_unexpected_resolved_model_halts_without_switching(ledger):
    attempt = ledger.reserve(MODEL, "generation", [], 256, 0)
    ledger.reconcile(attempt, Usage(input_tokens=10, output_tokens=1), "unexpected-expensive-model")
    assert ledger.halted_reason == "resolved_model_pricing_mismatch"
    assert attempt.accounted_usd == attempt.reserved_usd


def test_call_limit_includes_retry_and_judge(ledger):
    ledger.policy.max_live_calls = 2
    ledger.reserve(MODEL, "generation", [], 16, 0)
    ledger.reserve(MODEL, "judge", [], 16, 1)
    with pytest.raises(ExecutionDenied, match="call_limit_reached"):
        ledger.reserve(MODEL, "generation", [], 16, 2)
    assert len(ledger.attempts) == 2


def test_actual_estimate_exceeds_reservation_stops_next_call(ledger):
    attempt = ledger.reserve(MODEL, "generation", [], 16, 0)
    ledger.reconcile(attempt, Usage(input_tokens=1_000_000, output_tokens=1))
    assert ledger.accounted_usd > ledger.policy.max_run_usd
    with pytest.raises(ExecutionDenied, match="spend_limit_reached"):
        ledger.reserve(MODEL, "generation", [], 16, 1)
