import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from vaanibench.schemas import DatasetError, Message, Scenario, load_scenarios, validate_dataset

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def record():
    return dict(schema_version="1.0", id="vb-001", language="en", age_years=8,
                category="factual", messages=[dict(role="user", content=" What is 2 + 3? ")],
                rubric=" Answer briefly. ", reference_answer="5")


def test_round_trip(record):
    scenario = Scenario.model_validate(record)
    assert scenario.messages[0].content == "What is 2 + 3?"
    assert scenario.rubric == "Answer briefly."
    assert Scenario.model_validate_json(scenario.model_dump_json()) == scenario


@pytest.mark.parametrize("field,value", [
    ("id", 1), ("id", "vb-001x"), ("age_years", "8"), ("age_years", True),
    ("age_years", 5), ("age_years", 13), ("language", "fr"),
    ("category", "other"), ("schema_version", "2.0"), ("rubric", " "),
    ("reference_answer", "\n"), ("unexpected", 1), ("messages", []),
])
def test_bad_fields(record, field, value):
    record[field] = value
    with pytest.raises(ValidationError):
        Scenario.model_validate(record)


@pytest.mark.parametrize("roles", [["assistant"], ["user", "assistant"], ["user", "user", "user"]])
def test_bad_turn_order(record, roles):
    record["messages"] = [dict(role=r, content="hello") for r in roles]
    with pytest.raises(ValidationError, match="alternate"):
        Scenario.model_validate(record)


def test_valid_context(record):
    record["messages"] = [dict(role=r, content="hello") for r in ["user", "assistant", "user"]]
    assert len(Scenario.model_validate(record).messages) == 3


@pytest.mark.parametrize("message", [dict(role="system", content="hello"),
    dict(role="user", content=" "), dict(role="user", content=1),
    dict(role="user", content="hi", extra=True), dict(role="user")])
def test_bad_message(message):
    with pytest.raises(ValidationError):
        Message.model_validate(message)


def test_missing_required(record):
    for field in list(record):
        with pytest.raises(ValidationError):
            Scenario.model_validate({k: v for k, v in record.items() if k != field})


@pytest.mark.parametrize("mode", ["blank", "invalid_json", "duplicate", "invalid_record", "empty"])
def test_loader_locations(tmp_path, record, mode):
    good = json.dumps(record)
    content = {"blank": good + "\n\n", "invalid_json": good + "\n{",
               "duplicate": good + "\n" + good, "invalid_record": good + '\n{}', "empty": ""}[mode]
    path = tmp_path / "cases.jsonl"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(DatasetError, match=rf"cases.jsonl:{1 if mode == 'empty' else 2}:"):
        load_scenarios(path)


def test_canonical_dataset():
    cases, manifest = validate_dataset(ROOT / "data/scenarios.jsonl", ROOT / "data/manifest.json")
    assert len(cases) == manifest.case_count == 20
    assert {c.language for c in cases} == {"en", "hi", "hi-en"}
    assert len({c.category for c in cases}) == 5


def test_tampered_dataset(tmp_path):
    path = tmp_path / "scenarios.jsonl"
    path.write_bytes((ROOT / "data/scenarios.jsonl").read_bytes() + b" ")
    with pytest.raises(DatasetError):
        validate_dataset(path, ROOT / "data/manifest.json")
