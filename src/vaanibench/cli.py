"""CLI: 0 success, 1 execution/validation error, 2 regression gate failure."""
import argparse
import json
import os
from pathlib import Path

from .models import Experiment
from .report import Thresholds, compare, load_run, summary, write_comparison, write_report
from .runner import run_evaluation
from .schemas import DatasetError, validate_dataset


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="vaanibench")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ["validate", "run"]:
        command = commands.add_parser(name)
        command.add_argument("--dataset", type=Path, default=Path("data/scenarios.jsonl"))
        command.add_argument("--manifest", type=Path, default=Path("data/manifest.json"))
        if name == "run":
            command.add_argument("--config", type=Path, required=True)
            command.add_argument("--out", type=Path, required=True)
            command.add_argument("--judge-model", help="Optional paid, uncalibrated judge model")
    comp = commands.add_parser("compare")
    comp.add_argument("--baseline", type=Path, required=True)
    comp.add_argument("--candidate", type=Path, required=True)
    comp.add_argument("--out", type=Path, required=True)
    comp.add_argument("--thresholds", type=Path)
    report = commands.add_parser("report")
    report.add_argument("--run", type=Path, required=True)
    report.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            cases, manifest = validate_dataset(args.dataset, args.manifest)
            print(json.dumps(dict(valid_cases=len(cases), dataset_version=manifest.dataset_version,
                                  sha256=manifest.sha256)))
        elif args.command == "run":
            config = Experiment.model_validate_json(args.config.read_text(encoding="utf-8"))
            if args.judge_model:
                config.judge_model = args.judge_model
            if (config.provider == "openai" or config.judge_model) and not os.environ.get("OPENAI_API_KEY"):
                raise ValueError("OPENAI_API_KEY is missing; configure it locally, never in Git")
            run = run_evaluation(args.dataset, args.manifest, config, args.out)
            write_report(run, args.out / "report.md")
            print(json.dumps(summary(run)))
            if any(c.status == "error" or c.judge_error for c in run.cases):
                return 1
        elif args.command == "compare":
            thresholds = Thresholds.model_validate_json(args.thresholds.read_text(encoding="utf-8")) if args.thresholds else Thresholds()
            data = compare(load_run(args.baseline), load_run(args.candidate), thresholds)
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / "comparison.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
            write_comparison(data, args.out / "comparison.md")
            print(json.dumps({k: v for k, v in data.items() if k not in {"pairs", "judge_pairs"}}))
            return 0 if data["passed"] else 2
        else:
            write_report(load_run(args.run), args.out)
    except DatasetError as exc:
        print(f"Dataset validation failed: {exc}")
        return 1
    except (ValueError, OSError):
        # Do not echo arbitrary provider/file data through a validation traceback.
        print("Command failed. Check input paths, configuration, dataset validation, and local credentials.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
