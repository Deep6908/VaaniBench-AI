"""Explicitly selected, aggregate-budgeted repeated A/B benchmarks."""
from __future__ import annotations

import hashlib
import json
import random
import statistics
from decimal import Decimal
from pathlib import Path

from .costs import ExecutionDenied, load_prices, reserve_cost
from .models import Experiment
from .report import Thresholds, case_score, compare, summary, write_report
from .runner import run_evaluation
from .schemas import digest, validate_dataset


class BenchmarkGuard:
    """One aggregate ledger across repeats, A/B, retries, generation and judges."""
    def __init__(self,max_usd,max_calls):
        self.max_usd,self.max_calls=max_usd,max_calls
        self.reservations={}

    def reserve(self,attempt):
        if len(self.reservations)>=self.max_calls: raise ExecutionDenied('benchmark_call_limit_reached')
        if sum(self.reservations.values(),Decimal(0))+attempt.reserved_usd>self.max_usd: raise ExecutionDenied('benchmark_spend_limit_reached')
        key=str(len(self.reservations)+1)
        self.reservations[key]=attempt.reserved_usd
        return key

    def reconcile(self,key,amount): self.reservations[key]=amount


def plan(dataset,manifest,baseline,candidate,case_ids,repeats=2,max_usd=Decimal('.10'),max_calls=20):
    cases,version=validate_dataset(dataset,manifest)
    if not case_ids or len(set(case_ids))!=len(case_ids) or not set(case_ids).issubset({c.id for c in cases}): raise ValueError('Explicit unique valid case IDs required')
    if not 1<=repeats<=10 or not max_usd.is_finite() or not Decimal(0)<max_usd<=Decimal(1) or not 1<=max_calls<=100: raise ValueError('Invalid benchmark limits')
    configs=[Experiment.model_validate_json(Path(p).read_text(encoding='utf-8')) for p in [baseline,candidate]]
    identities={(c.judge_model,(c.judge_provider or (c.provider if c.provider!='mock' else 'openai')) if c.judge_model else None) for c in configs}
    if len(identities)!=1: raise ValueError('A/B requires the same judge configuration')
    selected=[c for c in cases if c.id in case_ids]
    prices=None
    nominal=Decimal(0);potential=0
    for config in configs:
        if config.provider!='mock' or config.judge_model:
            prices=load_prices(config.execution.pricing_path)
            if config.provider!='mock':
                price=prices.price(config.model)
                nominal+=repeats*sum((reserve_cost([dict(role='system',content=config.system_prompt)]+[m.model_dump() for m in c.messages],config.max_tokens,price) for c in selected),Decimal(0))
            if config.judge_model: prices.price(config.judge_model)
            calls=int(config.provider!='mock')+int(bool(config.judge_model))
            potential+=len(selected)*calls*(1+config.execution.max_retries)*repeats
    implementation=hashlib.sha256(b''.join(p.read_bytes() for p in sorted(Path(__file__).parent.glob('*.py')))).hexdigest()
    result=dict(dataset_sha256=digest(dataset),dataset_version=version.dataset_version,case_ids=[c.id for c in selected],repeats=repeats,
        implementation_sha256=implementation,dependency_sha256=digest(Path('uv.lock')) if Path('uv.lock').exists() else None,
        configs=[c.model_dump(mode='json') for c in configs],pricing=prices.model_dump(mode='json') if prices else None,
        max_accounted_usd=str(max_usd),max_api_attempts=max_calls,potential_attempts_including_retries=potential,
        allowed_attempts_upper_bound=min(potential,max_calls),generation_reservation_estimate_without_retries_or_judges=str(nominal),
        note='Dry run: no requests. Guard stops when aggregate limits are reached; a complete benchmark is not guaranteed. USD accounting is estimated, not an invoice cap.')
    result['approval_sha256']=hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()
    return result


def execute_plan(proposal,dataset,manifest,output,*,allow_live=False,approval=None):
    if approval!=proposal['approval_sha256']: raise ExecutionDenied('benchmark_plan_approval_required')
    contents={k:v for k,v in proposal.items() if k!='approval_sha256'}
    if hashlib.sha256(json.dumps(contents,sort_keys=True).encode()).hexdigest()!=approval: raise ExecutionDenied('benchmark_plan_changed')
    if digest(dataset)!=proposal['dataset_sha256']: raise ExecutionDenied('benchmark_dataset_changed')
    configs=[Experiment.model_validate_json(json.dumps(c)) for c in proposal['configs']]
    if any(c.provider!='mock' or c.judge_model for c in configs) and not allow_live: raise ExecutionDenied('live_not_enabled')
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    if any(output.iterdir()): raise ValueError('Use an empty benchmark output directory')
    (output/'plan.json').write_text(json.dumps(proposal,indent=2),encoding='utf-8')
    guard=BenchmarkGuard(Decimal(proposal['max_accounted_usd']),proposal['max_api_attempts'])
    comparisons=[]; runs=[]; deltas={}
    for repeat in range(proposal['repeats']):
        pair=[]
        for side,original in zip(['baseline','candidate'],configs):
            config=original.model_copy(deep=True)
            config.execution=type(config.execution).model_validate(config.execution.model_dump()|dict(allow_live=allow_live,case_ids=proposal['case_ids'],all_cases=False,
                max_run_usd=min(config.execution.max_run_usd,Decimal('.10')),max_live_calls=min(config.execution.max_live_calls,20)))
            # Keep identical settings across repeats to expose nondeterminism.
            path=output/f'repeat-{repeat+1}'/side
            run=run_evaluation(Path(dataset),Path(manifest),config,path,daily_guard=guard)
            write_report(run,path/'report.md');pair.append(run)
            runs.append(dict(repeat=repeat+1,side=side,run_id=run.run_id,summary=summary(run)))
        comparison=compare(*pair,Thresholds()); comparisons.append(comparison)
        for a,b in zip(pair[0].cases,pair[1].cases):
            sa,sb=case_score(a),case_score(b)
            if sa is not None and sb is not None: deltas.setdefault(a.scenario_id,[]).append(sb-sa)
    # Cluster bootstrap by scenario; repeats are not independent scenario samples.
    complete={key:values for key,values in deltas.items() if len(values)==proposal['repeats']}
    means=[statistics.mean(v) for v in complete.values()]
    rng=random.Random(42)
    boot=sorted(statistics.mean(rng.choices(means,k=len(means))) for _ in range(2000)) if len(means)>=2 else []
    result=dict(evidence='mock-fixture' if all(c.provider=='mock' for c in configs) else 'live-model',
        runs=runs,comparisons=comparisons,paired_scored_scenarios=len(means),
        paired_repeats_by_scenario={key:len(values) for key,values in deltas.items()},
        unscored_or_incomplete_scenario_ids=[key for key in proposal['case_ids'] if key not in complete],
        mean_paired_delta=statistics.mean(means) if means else None,
        delta_95_percentile_interval=[boot[49],boot[1949]] if boot else None,
        uncertainty_note='Scenario-cluster bootstrap over this convenience sample; no population-level quality or child-safety claim. Judge excluded from gates.',
        api_attempts=len(guard.reservations),accounted_usd=str(sum(guard.reservations.values(),Decimal(0))))
    (output/'benchmark.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    (output/'benchmark.md').write_text('\n'.join(['# VaaniBench repeated A/B benchmark','',
        f"Evidence: {result['evidence']}",f"Paired scored scenarios: {len(means)}/{len(proposal['case_ids'])}",
        f"Mean paired deterministic delta: {result['mean_paired_delta']}",
        f"95% scenario-cluster percentile interval: {result['delta_95_percentile_interval']}",
        f"API attempts: {result['api_attempts']}; accounted estimated USD: {result['accounted_usd']}",
        '',result['uncertainty_note'],'','Per-run latency, usage, failures and provenance: benchmark.json and repeat-N/*/run.json.']),encoding='utf-8')
    return result
