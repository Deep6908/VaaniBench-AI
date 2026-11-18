"""Reproduce offline reports and demonstrate both passing and failing gates."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from vaanibench.models import Experiment
from vaanibench.report import Thresholds, compare, summary, write_comparison, write_report
from vaanibench.runner import run_evaluation


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True, help="New directory for this benchmark")
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit("Choose a new benchmark directory; existing data is never overwritten.")
    runs = {}
    for name in ["baseline", "repeat", "degraded"]:
        config_path = Path("configs/mock-degraded.json" if name == "degraded" else "configs/mock-baseline.json")
        config = Experiment.model_validate_json(config_path.read_text(encoding="utf-8"))
        run = run_evaluation(Path("data/scenarios.jsonl"), Path("data/manifest.json"), config, args.out / name)
        write_report(run, args.out / name / "report.md")
        runs[name] = run
    decisions = {}
    for name in ["repeat", "degraded"]:
        data = compare(runs["baseline"], runs[name], Thresholds())
        (args.out / f"{name}-comparison.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        write_comparison(data, args.out / f"{name}-comparison.md")
        decisions[name] = data["passed"]
    if decisions != {"repeat": True, "degraded": False}:
        raise SystemExit("Benchmark verification failed: inspect comparison artifacts.")
    print(json.dumps(dict(gates=decisions, runs={k: summary(v) for k, v in runs.items()}), indent=2))


if __name__ == "__main__":
    main()
