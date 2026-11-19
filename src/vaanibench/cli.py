"""CLI: 0 success, 1 execution/validation error, 2 regression gate failure."""
import argparse
import json
import os
from decimal import DecimalException
from pathlib import Path

from .models import Experiment
from .report import Thresholds, compare, load_run, summary, write_comparison, write_report
from .runner import run_evaluation
from .schemas import DatasetError, validate_dataset
from .costs import ExecutionDenied
from .credentials import load_api_key_file


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="vaanibench")
    commands = parser.add_subparsers(dest="command", required=True)
    benchmark=commands.add_parser("benchmark",help="Plan first; explicitly approve an aggregate-budgeted repeated A/B run")
    benchmark.add_argument('--dataset',type=Path,default=Path('data/scenarios.jsonl'))
    benchmark.add_argument('--manifest',type=Path,default=Path('data/manifest.json'))
    benchmark.add_argument('--baseline',type=Path,required=True)
    benchmark.add_argument('--candidate',type=Path,required=True)
    benchmark.add_argument('--case-ids',nargs='+',required=True)
    benchmark.add_argument('--repeats',type=int,default=2)
    benchmark.add_argument('--max-usd',default='0.10')
    benchmark.add_argument('--max-calls',type=int,default=20)
    benchmark.add_argument('--execute',action='store_true')
    benchmark.add_argument('--approve-plan')
    benchmark.add_argument('--live',action='store_true')
    benchmark.add_argument('--env-file',type=Path)
    benchmark.add_argument('--out',type=Path)
    annotate=commands.add_parser('annotate',help='Prepare blinded human review templates; no labels are generated')
    annotate.add_argument('--dataset',type=Path,required=True)
    annotate.add_argument('--manifest',type=Path,required=True)
    annotate.add_argument('--registry',type=Path,required=True)
    annotate.add_argument('--runs',nargs='+',type=Path,required=True)
    annotate.add_argument('--out',type=Path,required=True)
    calibration=commands.add_parser('calibration',help='Measure agreement from independent human ratings')
    calibration.add_argument('--samples',type=Path,required=True)
    calibration.add_argument('--labels',nargs='+',type=Path,required=True)
    calibration.add_argument('--split',choices=['calibration','heldout'],default='heldout')
    calibration.add_argument('--out',type=Path,required=True)
    demo = commands.add_parser("demo", help="Start the loopback-only presentation app")
    demo.add_argument("--port", type=int, default=8765)
    demo.add_argument("--allow-live", action="store_true")
    demo.add_argument("--env-file", type=Path, help="Explicit local API key file")
    for name in ["validate", "run"]:
        command = commands.add_parser(name)
        command.add_argument("--dataset", type=Path, default=Path("data/scenarios.jsonl"))
        command.add_argument("--manifest", type=Path, default=Path("data/manifest.json"))
        if name == "run":
            command.add_argument("--config", type=Path, required=True)
            command.add_argument("--out", type=Path, required=True)
            command.add_argument("--judge-model", help="Optional paid, uncalibrated judge model")
            command.add_argument("--live", action="store_true", help="Explicitly permit budgeted paid calls")
            command.add_argument("--env-file", type=Path, help="Explicitly load OPENAI_API_KEY from a local file")
            selection = command.add_mutually_exclusive_group()
            selection.add_argument("--case-ids", nargs="+", help="Explicit subset of scenario IDs")
            selection.add_argument("--all-cases", action="store_true", help="Explicitly select the entire dataset")
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
        if args.command=='benchmark':
            from decimal import Decimal
            from .benchmark import plan,execute_plan
            proposal=plan(args.dataset,args.manifest,args.baseline,args.candidate,args.case_ids,args.repeats,Decimal(args.max_usd),args.max_calls)
            if args.execute:
                if not args.out: raise ValueError('Output required')
                if args.env_file: load_api_key_file(args.env_file)
                result=execute_plan(proposal,args.dataset,args.manifest,args.out,allow_live=args.live,approval=args.approve_plan)
                print(json.dumps(result))
                if any(r['summary']['errors'] or r['summary']['skipped'] or r['summary']['judge_errors'] or r['summary']['stop_reason'] for r in result['runs']): return 1
            else: print(json.dumps(proposal,indent=2))
        elif args.command=='annotate':
            from .calibration import annotation_pack
            print(json.dumps(annotation_pack(args.dataset,args.manifest,args.registry,args.runs,args.out)))
        elif args.command=='calibration':
            from .calibration import agreement
            result=agreement(args.samples,args.labels,split=args.split)
            args.out.parent.mkdir(parents=True,exist_ok=True)
            args.out.write_text(json.dumps(result,indent=2),encoding='utf-8')
            print(json.dumps(result))
        elif args.command == "validate":
            cases, manifest = validate_dataset(args.dataset, args.manifest)
            print(json.dumps(dict(valid_cases=len(cases), dataset_version=manifest.dataset_version,
                                  sha256=manifest.sha256)))
        elif args.command == "run":
            if args.env_file:
                load_api_key_file(args.env_file)
            config = Experiment.model_validate_json(args.config.read_text(encoding="utf-8"))
            if args.judge_model:
                config.judge_model = args.judge_model
            updates = {}
            if args.live:
                updates["allow_live"] = True
            if args.case_ids:
                updates.update(case_ids=args.case_ids, all_cases=False)
            if args.all_cases:
                updates.update(case_ids=[], all_cases=True)
            config.execution = type(config.execution).model_validate(config.execution.model_dump() | updates)
            run = run_evaluation(args.dataset, args.manifest, config, args.out)
            write_report(run, args.out / "report.md")
            print(json.dumps(summary(run)))
            if run.stop_reason or any(c.status != "ok" or c.judge_error for c in run.cases):
                return 1
        elif args.command == "compare":
            thresholds = Thresholds.model_validate_json(args.thresholds.read_text(encoding="utf-8")) if args.thresholds else Thresholds()
            data = compare(load_run(args.baseline), load_run(args.candidate), thresholds)
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / "comparison.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
            write_comparison(data, args.out / "comparison.md")
            print(json.dumps({k: v for k, v in data.items() if k not in {"pairs", "judge_pairs"}}))
            return 0 if data["passed"] else 2
        elif args.command == "demo":
            from .demo import serve
            if args.env_file:
                load_api_key_file(args.env_file)
            if not 0 <= args.port <= 65535:
                raise ValueError("Invalid port")
            serve(args.port, allow_live=args.allow_live)
        else:
            write_report(load_run(args.run), args.out)
    except ExecutionDenied as exc:
        print(f"Execution blocked: {exc}")
        return 1
    except DatasetError as exc:
        print(f"Dataset validation failed: {exc}")
        return 1
    except (ValueError, OSError, DecimalException):
        # Do not echo arbitrary provider/file data through a validation traceback.
        print("Command failed. Check input paths, configuration, dataset validation, and local credentials.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
