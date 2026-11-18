import json

import pytest
from pydantic import ValidationError

from vaanibench.evaluators import evaluate, judge_response
from vaanibench.models import JudgeScores, Response
from vaanibench.schemas import load_scenarios


def test_exact_is_not_substring():
    case = load_scenarios("data/scenarios.jsonl")[0]
    assert evaluate(case, " 5 ")[0].score == 1.0
    assert evaluate(case, "The answer is 5")[0].score == 0.0


def test_lines_only_verify_format():
    case = load_scenarios("data/scenarios.jsonl")[4]
    assert evaluate(case, "wrong\ncontent")[0].score == 1.0
    assert evaluate(case, "Red\nBlue\nIntro")[0].score == 0.0


def test_semantics_not_automatically_passed():
    case = load_scenarios("data/scenarios.jsonl")[-1]
    assert evaluate(case, "Any text")[0].score is None


def test_judge_contract_and_inputs():
    case = load_scenarios("data/scenarios.jsonl")[-1]
    class FakeJudge:
        def generate(self, messages):
            body = json.loads(messages[0].content)
            assert body["rubric"] == case.rubric
            assert body["reference_answer"] == case.reference_answer
            return Response(text=json.dumps(dict(correctness=4, instruction_following=5,
                privacy_safety=5, age_appropriateness=4, rationale="Refuses private data.")))
    scores, _ = judge_response(case, "Do not share.", FakeJudge())
    assert scores.correctness == 4


@pytest.mark.parametrize("value", [0, 6, True, "5"])
def test_judge_bounds_and_types(value):
    with pytest.raises(ValidationError):
        JudgeScores(correctness=value, instruction_following=5, privacy_safety=5,
                    age_appropriateness=5, rationale="Evidence")
