"""Providers see messages/config only, never evaluator references or rubrics."""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import ValidationError

from .models import Experiment, Response, Usage
from .schemas import Message


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
    """Bounded single-attempt Chat Completions adapter; no implicit paid retries."""

    def __init__(self, config: Experiment, *, json_mode: bool = False, transport=urlopen):
        self.config = config
        self.json_mode = json_mode
        self.transport = transport

    def generate(self, messages: list[Message]) -> Response:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ProviderError("missing_api_key")
        payload = dict(model=self.config.model,
            messages=[dict(role="system", content=self.config.system_prompt)] + [m.model_dump() for m in messages],
            temperature=self.config.temperature, seed=self.config.seed,
            max_completion_tokens=self.config.max_tokens)
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        request = Request("https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
        try:
            with self.transport(request, timeout=self.config.timeout_seconds) as response:
                body = json.load(response)
            choice = body["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise ProviderError("incomplete_response")
            usage = body.get("usage") or {}
            return Response(text=choice["message"]["content"], usage=Usage(
                input_tokens=usage.get("prompt_tokens"), output_tokens=usage.get("completion_tokens")),
                finish_reason=choice["finish_reason"], resolved_model=body.get("model"))
        except HTTPError as exc:
            raise ProviderError(f"http_{exc.code}") from None
        except (TimeoutError, socket.timeout):
            raise ProviderError("timeout") from None
        except URLError:
            raise ProviderError("transport_error") from None
        except (ValueError, KeyError, IndexError, TypeError, ValidationError):
            raise ProviderError("invalid_provider_response") from None


def make_provider(config: Experiment) -> Provider:
    return MockProvider(config) if config.provider == "mock" else OpenAIProvider(config)
