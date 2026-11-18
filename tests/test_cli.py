import json
import os
from pathlib import Path
import subprocess
import sys

from vaanibench.cli import main


def test_cli_vertical_slice(tmp_path):
    assert main(["validate"]) == 0
    a, b = tmp_path / "a", tmp_path / "b"
    for config, out in [("mock-baseline", a), ("mock-degraded", b)]:
        assert main(["run", "--config", f"configs/{config}.json", "--out", str(out)]) == 0
        assert (out / "run.json").exists()
        assert (out / "report.md").exists()
        assert (out / "traces.jsonl").exists()
    args = ["compare", "--baseline", str(a / "run.json"), "--candidate", str(a / "run.json"), "--out", str(tmp_path / "good")]
    assert main(args) == 0
    args[4] = str(b / "run.json")
    args[-1] = str(tmp_path / "bad")
    assert main(args) == 2
    assert not json.loads((tmp_path / "bad/comparison.json").read_text())["passed"]


def test_missing_key_no_paid_request(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert main(["run", "--config", "configs/openai-example.json", "--out", str(tmp_path)]) == 1


def test_module_entrypoint():
    result = subprocess.run([sys.executable, "-m", "vaanibench.cli", "validate"], capture_output=True, text=True)
    assert result.returncode == 0
    assert json.loads(result.stdout)["valid_cases"] == 20
