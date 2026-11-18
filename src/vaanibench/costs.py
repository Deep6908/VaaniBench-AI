"""Estimated USD accounting. This is an application guard, not a billing guarantee."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from .models import APIAttempt, ExecutionPolicy, Money, Usage
from .schemas import Contract, Text


class ExecutionDenied(RuntimeError):
    """Safe authorization/budget diagnostic; contains no request or secret data."""


class Price(Contract):
    input_per_million: Money
    cached_input_per_million: Money
    output_per_million: Money


class PriceBook(Contract):
    version: Text
    verified_on: Text
    source: Text
    currency: Literal["USD"]
    models: dict[str, Price]

    def price(self, model: str) -> Price:
        if model not in self.models:
            raise ExecutionDenied("unpriced_model")
        return self.models[model]


def load_prices(path: str | Path) -> PriceBook:
    return PriceBook.model_validate_json(Path(path).read_text(encoding="utf-8"))


def usage_cost(usage: Usage, price: Price) -> Decimal | None:
    if usage.input_tokens is None or usage.output_tokens is None:
        return None
    return ((usage.input_tokens - usage.cached_input_tokens) * price.input_per_million
        + usage.cached_input_tokens * price.cached_input_per_million
        + usage.output_tokens * price.output_per_million) / Decimal(1_000_000)


def reserve_cost(messages: list[dict], max_output: int, price: Price) -> Decimal:
    # Deliberately conservative heuristic for the allowlisted text-only models.
    # Includes system/judge instructions, UTF-8 bytes and framing allowance.
    # Not an exact tokenizer or a guarantee of provider billing.
    tokens = sum(len(m["content"].encode("utf-8")) + 32 for m in messages) + 256
    return (tokens * price.input_per_million + max_output * price.output_per_million) / Decimal(1_000_000)


class BudgetLedger:
    def __init__(self, policy: ExecutionPolicy, prices: PriceBook):
        if not policy.allow_live:
            raise ExecutionDenied("live_not_enabled")
        if not policy.case_ids and not policy.all_cases:
            raise ExecutionDenied("explicit_case_selection_required")
        self.policy = policy
        self.prices = prices
        self.attempts: list[APIAttempt] = []
        self.scenario_id: str | None = None
        self.halted_reason: str | None = None
        self.daily_guard = None

    @property
    def accounted_usd(self) -> Decimal:
        return sum((a.accounted_usd for a in self.attempts), Decimal(0))

    def check_available(self, model: str, messages: list[dict], max_output: int) -> Decimal:
        if not self.policy.allow_live:
            raise ExecutionDenied("live_not_enabled")
        reason = self.halted_reason
        amount = reserve_cost(messages, max_output, self.prices.price(model))
        if reason is None and len(self.attempts) >= self.policy.max_live_calls:
            reason = "call_limit_reached"
        if reason is None and self.accounted_usd + amount > self.policy.max_run_usd:
            reason = "spend_limit_reached"
        if reason:
            self.halted_reason = reason
            raise ExecutionDenied(reason)
        return amount

    def reserve(self, model: str, purpose: str, messages: list[dict], max_output: int,
                retry_index: int, provider: str = "openai") -> APIAttempt:
        amount = self.check_available(model, messages, max_output)
        attempt = APIAttempt(number=len(self.attempts)+1, scenario_id=self.scenario_id,
            purpose=purpose, provider=provider, model=model, retry_index=retry_index,
            reserved_usd=amount, accounted_usd=amount)
        if self.daily_guard:
            try:
                attempt.daily_reservation_id = self.daily_guard.reserve(attempt)
            except ExecutionDenied as exc:
                self.halted_reason = str(exc)
                raise
        self.attempts.append(attempt)
        return attempt

    def reconcile(self, attempt: APIAttempt, usage: Usage, resolved_model: str | None = None):
        attempt.usage = usage
        attempt.resolved_model = resolved_model
        price = self.prices.price(attempt.model)
        if resolved_model:
            resolved = self.prices.models.get(resolved_model)
            if resolved is None or resolved != price:
                self.halted_reason = "resolved_model_pricing_mismatch"
                return
        estimate = usage_cost(usage, price)
        attempt.estimated_cost_usd = estimate
        if estimate is not None:
            attempt.accounted_usd = estimate
        if self.daily_guard and attempt.daily_reservation_id:
            self.daily_guard.reconcile(attempt.daily_reservation_id, attempt.accounted_usd)
        if self.accounted_usd > self.policy.max_run_usd:
            self.halted_reason = "spend_limit_reached"
