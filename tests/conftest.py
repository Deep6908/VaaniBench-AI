from pathlib import Path

import pytest

from vaanibench.models import Experiment
from vaanibench.runner import run_evaluation

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def execute(tmp_path):
    def run(name="baseline", mode="baseline", **kwargs):
        config = kwargs.pop("config", Experiment(name=name, mock_mode=mode))
        return run_evaluation(ROOT / "data/scenarios.jsonl", ROOT / "data/manifest.json",
                              config, tmp_path / name, **kwargs)
    return run
