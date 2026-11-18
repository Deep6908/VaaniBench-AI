"""Strict contracts and location-aware, fail-fast dataset validation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Contract(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", validate_assignment=True)


class Message(Contract):
    role: Literal["user", "assistant"]
    content: Text


class ExactCheck(Contract):
    kind: Literal["exact"]
    expected: Text


class LinesCheck(Contract):
    kind: Literal["lines"]
    count: Annotated[int, Field(ge=1, le=10)]


Check = Annotated[ExactCheck | LinesCheck, Field(discriminator="kind")]


class Scenario(Contract):
    schema_version: Literal["1.0", "1.1"]
    id: Annotated[str, StringConstraints(pattern=r"^vb-[0-9]{3}$")]
    language: Literal["en", "hi", "hi-en"]
    age_years: Annotated[int, Field(ge=6, le=12)]
    category: Literal["factual", "instruction", "context", "uncertainty", "privacy"]
    messages: Annotated[list[Message], Field(min_length=1)]
    rubric: Text
    reference_answer: Text
    checks: list[Check] = Field(default_factory=list)

    @model_validator(mode="after")
    def conversation_contract(self) -> Self:
        if any(m.role != ("user" if i % 2 == 0 else "assistant")
               for i, m in enumerate(self.messages)) or self.messages[-1].role != "user":
            raise ValueError("messages must alternate user/assistant, start and end with user")
        if self.schema_version == "1.0" and self.checks:
            raise ValueError("explicit checks require schema_version 1.1")
        if len({c.kind for c in self.checks}) != len(self.checks):
            raise ValueError("duplicate check kinds")
        return self


class DatasetError(ValueError):
    """Invalid JSONL or inconsistent dataset manifest."""


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_scenarios(path: str | Path) -> list[Scenario]:
    path = Path(path)
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise DatasetError(f"{path}: invalid UTF-8") from exc
    cases: list[Scenario] = []
    seen: set[str] = set()
    for line_no, line in enumerate(content.splitlines(), 1):
        try:
            if not line.strip():
                raise ValueError("blank lines are not allowed")
            case = Scenario.model_validate(json.loads(line))
            if case.id in seen:
                raise ValueError(f"duplicate ID {case.id}")
        except ValueError as exc:
            if isinstance(exc, ValidationError):
                detail = "; ".join(f"{e['loc']}: {e['type']}" for e in exc.errors())
            elif isinstance(exc, json.JSONDecodeError):
                detail = "malformed JSON"
            else:
                detail = str(exc)
            raise DatasetError(f"{path}:{line_no}: {detail}") from exc
        seen.add(case.id)
        cases.append(case)
    if not cases:
        raise DatasetError(f"{path}:1: empty dataset")
    return cases


class DatasetManifest(Contract):
    dataset_version: Text
    schema_version: Literal["1.1"]
    sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    case_count: Annotated[int, Field(ge=1)]
    provenance: Text


def validate_dataset(path: str | Path, manifest_path: str | Path) -> tuple[list[Scenario], DatasetManifest]:
    path = Path(path)
    cases = load_scenarios(path)
    manifest = DatasetManifest.model_validate_json(Path(manifest_path).read_text(encoding="utf-8"))
    if digest(path) != manifest.sha256 or len(cases) != manifest.case_count:
        raise DatasetError("dataset bytes/count differ from version manifest")
    if any(c.schema_version != manifest.schema_version for c in cases):
        raise DatasetError("dataset schema version differs from manifest")
    return cases, manifest
