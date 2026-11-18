"""Providers see messages/config only, never evaluator references or rubrics."""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import time
import random
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPRedirectHandler, build_opener

from pydantic import ValidationError

from .models import Experiment, Response, Usage
from .schemas import Message
from .costs import BudgetLedger, ExecutionDenied
from .telemetry import record_api_attempt


class ProviderError(RuntimeError):
    """Safe, categorized failure; never retains API bodies or keys."""


class Provider(Protocol):
    def generate(self, messages: list[Message]) -> Response: ...


class MockProvider:
    """Handwritten protocol fixture, not an intelligence or safety benchmark."""

    def __init__(self, config: Experiment):
        self.config = config

    def generate(self, messages: list[Message]) -> Response:
        prompt = messages[-1].content
        if self.config.mock_mode == "failure":
            raise ProviderError("simulated_failure")
        # Stable per input/seed, independent of dataset row order or expected answers.
        key = hashlib.sha256(f"{self.config.seed}:{prompt}".encode()).digest()[0]
        if self.config.mock_mode == "degraded" and key % 2 == 0:
            return Response(text="I do not know.", resolved_model="mock-v1")
        arithmetic = re.search(r"(\d+)\s*([+*-])\s*(\d+)", prompt)
        if arithmetic:
            a, op, b = arithmetic.groups()
            answer = str({"+": int(a) + int(b), "-": int(a) - int(b), "*": int(a) * int(b)}[op])
        elif "two colors" in prompt:
            answer = "Red\nBlue"
        elif "दो फलों" in prompt:
            answer = "आम\nसेब"
        elif "Teen animals" in prompt:
            answer = "Cat\nDog\nElephant"
        elif "word Hello" in prompt:
            answer = "Hello"
        elif "corrected name" in prompt:
            answer = "Tara"
        elif "Favorite animal" in prompt:
            answer = "panda"
        elif "गेंदें रखीं" in prompt:
            answer = "5"
        elif "new word is moon" in prompt:
            answer = "moon"
        else:
            answer = "I do not know private information. Please ask a trusted adult."
        return Response(text=answer, resolved_model="mock-v1")


class OpenAIProvider:
    """Explicitly authorized, budgeted text-only Chat Completions adapter."""
    provider_name = "openai"
    key_name = "OPENAI_API_KEY"
    endpoint = "https://api.openai.com/v1/chat/completions"

    def __init__(self, config: Experiment, *, ledger: BudgetLedger | None = None,
                 purpose: str = "generation", json_mode: bool = False, transport=None,
                 clock=time.monotonic, sleeper=time.sleep, jitter=random.random):
        self.config = config
        self.ledger = ledger
        self.purpose = purpose
        self.json_mode = json_mode
        self.transport = transport
        self.clock, self.sleeper, self.jitter = clock, sleeper, jitter

    def _payload(self, messages: list[Message]) -> dict:
        payload = dict(model=self.config.model,
            messages=[dict(role="system", content=self.config.system_prompt)] + [m.model_dump() for m in messages],
            temperature=self.config.temperature, seed=self.config.seed,
            max_completion_tokens=self.config.max_tokens, store=False)
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def generate(self, messages: list[Message]) -> Response:
        if not self.config.execution.allow_live or self.ledger is None:
            raise ExecutionDenied("live_not_enabled")
        key = os.environ.get(self.key_name)
        if not key:
            raise ProviderError("missing_api_key")
        policy = self.ledger.policy
        payload = self._payload(messages)
        deadline = self.clock() + policy.request_deadline_seconds
        transport = self.transport or build_opener(NoRedirect()).open
        for retry in range(policy.max_retries + 1):
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise ProviderError("deadline_exceeded")
            attempt = self.ledger.reserve(self.config.model, self.purpose,
                payload["messages"], self.config.max_tokens, retry, provider=self.provider_name)
            request = Request(self.endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                    "User-Agent": "VaaniBench/0.1"}, method="POST")
            start = self.clock()
            can_retry, retry_after = False, None
            try:
                with transport(request, timeout=min(self.config.timeout_seconds, remaining)) as response:
                    raw = response.read(1_000_001)
                if len(raw) > 1_000_000:
                    raise ProviderError("invalid_provider_response")
                body = json.loads(raw)
                usage = parse_usage(body.get("usage"))
                self.ledger.reconcile(attempt, usage, body.get("model"))
                if self.clock() >= deadline:
                    raise ProviderError("deadline_exceeded")
                choice = body["choices"][0]
                if choice.get("finish_reason") != "stop":
                    raise ProviderError("incomplete_response")
                result = Response(text=choice["message"]["content"], usage=usage,
                    finish_reason=choice["finish_reason"], resolved_model=body.get("model"))
                attempt.status = "ok"
                return result
            except HTTPError as exc:
                quota, retry_after = http_error_info(exc)
                attempt.status = "quota_exhausted" if quota else f"http_{exc.code}"
                can_retry = not quota and exc.code in {429, 500, 502, 503, 504}
            except (TimeoutError, socket.timeout):
                attempt.status = "timeout"
            except URLError as exc:
                attempt.status = "timeout" if isinstance(exc.reason, TimeoutError) else "transport_error"
            except OSError:
                attempt.status = "transport_error"
            except ProviderError as exc:
                attempt.status = str(exc) if str(exc) in {"incomplete_response", "invalid_provider_response", "deadline_exceeded"} else "provider_error"
            except (ValueError, KeyError, IndexError, TypeError, AttributeError, ValidationError):
                attempt.status = "invalid_provider_response"
            finally:
                attempt.latency_ms = max(0.0, (self.clock() - start) * 1000)
                record_api_attempt(attempt)
            if not can_retry or retry == policy.max_retries:
                if attempt.status in {"quota_exhausted", "http_401", "http_403"}:
                    self.ledger.halted_reason = attempt.status
                raise ProviderError(attempt.status) from None
            self.ledger.check_available(self.config.model, payload["messages"], self.config.max_tokens)
            delay = min(policy.max_backoff_seconds,
                policy.backoff_seconds * 2**retry + policy.backoff_seconds * self.jitter())
            if retry_after is not None:
                delay = max(delay, retry_after)
            if delay > policy.max_backoff_seconds or self.clock() + delay >= deadline:
                raise ProviderError("retry_deadline_exceeded") from None
            self.sleeper(delay)
        raise ProviderError("retry_exhausted")


class GroqProvider(OpenAIProvider):
    """Groq-specific endpoint/key/payload; shared retry and budget enforcement."""
    provider_name = "groq"
    key_name = "GROQ_API_KEY"
    endpoint = "https://api.groq.com/openai/v1/chat/completions"

    def _payload(self, messages: list[Message]) -> dict:
        payload = super()._payload(messages)
        payload.pop("store", None)
        if self.config.model.startswith("openai/gpt-oss-"):
            payload.update(reasoning_effort="low", reasoning_format="hidden")
        return payload


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward an Authorization header to a redirected endpoint.
        raise HTTPError(req.full_url, code, "redirect_blocked", headers, fp)


def parse_usage(raw) -> Usage:
    if not isinstance(raw, dict):
        return Usage()
    try:
        details = raw.get("prompt_tokens_details") or {}
        return Usage(input_tokens=raw.get("prompt_tokens"),
            output_tokens=raw.get("completion_tokens"), cached_input_tokens=details.get("cached_tokens", 0))
    except (ValidationError, AttributeError):
        return Usage()


def http_error_info(error: HTTPError) -> tuple[bool, float | None]:
    quota = False
    try:
        data = json.loads(error.read(16384))
        detail = data.get("error", {})
        terminal = {"insufficient_quota", "billing_hard_limit_reached", "organization_usage_limit_exceeded", "billing_not_active"}
        code = detail.get("code")
        quota = code in terminal or (code != "rate_limit_exceeded" and detail.get("type") in terminal)
    except (ValueError, AttributeError, TypeError):
        pass
    finally:
        error.close()
    value = error.headers.get("Retry-After") if error.headers else None
    try:
        delay = float(value)
    except (ValueError, TypeError):
        try:
            delay = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return quota, None
    return quota, max(0.0, delay) if math.isfinite(delay) else None


KEY_NAMES = {"openai": "OPENAI_API_KEY", "groq": "GROQ_API_KEY"}


def judge_provider_name(config: Experiment) -> str:
    return config.judge_provider or (config.provider if config.provider != "mock" else "openai")


def make_provider(config: Experiment, ledger: BudgetLedger | None = None, **kwargs) -> Provider:
    if config.provider == "mock":
        return MockProvider(config)
    adapter = GroqProvider if config.provider == "groq" else OpenAIProvider
    return adapter(config, ledger=ledger, **kwargs)
