import json
from pathlib import Path
import subprocess
import sys


def test_benchmark_reproducible_entrypoint(tmp_path):
    out = tmp_path / "benchmark"
    result = subprocess.run([sys.executable, "scripts/benchmark.py", "--out", str(out)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["gates"] == {"repeat": True, "degraded": False}
    assert len(json.loads((out / "baseline/run.json").read_text())["cases"]) == 20
