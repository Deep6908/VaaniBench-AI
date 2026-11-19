import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

from vaanibench.benchmark import plan,execute_plan,BenchmarkGuard
from vaanibench.calibration import agreement,annotation_pack,quadratic_kappa
from vaanibench.costs import ExecutionDenied
from vaanibench.schemas import validate_dataset
from vaanibench.models import APIAttempt,Experiment
from vaanibench.runner import run_evaluation

ROOT=Path(__file__).resolve().parents[1]
DRAFT=ROOT/'data/candidate-v0.2'


def test_candidate_dataset_balance_splits_and_provenance():
    cases,manifest=validate_dataset(DRAFT/'scenarios.jsonl',DRAFT/'manifest.json')
    assert len(cases)==60 and manifest.dataset_version.endswith('draft')
    assert set(Counter((c.language,c.category) for c in cases).values())=={4}
    registry=json.loads((DRAFT/'registry.json').read_text())
    assert set(registry)=={c.id for c in cases}
    families={}
    for info in registry.values():
        assert info['review_status']=='pending'
        families.setdefault(info['family'],set()).add(info['split'])
    assert all(len(splits)==1 for splits in families.values())


def test_benchmark_plan_no_calls_and_explicit_approval(tmp_path,monkeypatch):
    from vaanibench import benchmark
    calls=[]
    monkeypatch.setattr(benchmark,'run_evaluation',lambda *a,**k:calls.append(1))
    proposal=plan(ROOT/'data/scenarios.jsonl',ROOT/'data/manifest.json',ROOT/'configs/groq-baseline.json',ROOT/'configs/groq-candidate.json',['vb-001'],2)
    assert not calls and proposal['potential_attempts_including_retries']==12
    assert proposal['max_accounted_usd']=='0.10' and proposal['max_api_attempts']==20
    with pytest.raises(ExecutionDenied): execute_plan(proposal,ROOT/'data/scenarios.jsonl',ROOT/'data/manifest.json',tmp_path)
    with pytest.raises(ExecutionDenied,match='live_not_enabled'):
        execute_plan(proposal,ROOT/'data/scenarios.jsonl',ROOT/'data/manifest.json',tmp_path,approval=proposal['approval_sha256'])
    assert not calls


def test_mock_benchmark_repeats_and_cluster_interval(tmp_path):
    proposal=plan(ROOT/'data/scenarios.jsonl',ROOT/'data/manifest.json',ROOT/'configs/mock-baseline.json',ROOT/'configs/mock-baseline.json',['vb-001','vb-005'],2)
    result=execute_plan(proposal,ROOT/'data/scenarios.jsonl',ROOT/'data/manifest.json',tmp_path/'benchmark',approval=proposal['approval_sha256'])
    assert result['api_attempts']==0 and result['evidence']=='mock-fixture'
    assert result['mean_paired_delta']==0 and result['delta_95_percentile_interval']==[0,0]
    assert len(result['runs'])==4


def test_benchmark_budget_shared_across_configurations_and_unknown_usage():
    guard=BenchmarkGuard(Decimal('.01'),2)
    attempt=APIAttempt(number=1,purpose='generation',model='x',retry_index=0,reserved_usd=Decimal('.006'),accounted_usd=Decimal('.006'))
    key=guard.reserve(attempt)
    with pytest.raises(ExecutionDenied,match='spend'): guard.reserve(attempt)
    guard.reconcile(key,Decimal('.001'))
    guard.reserve(attempt)
    with pytest.raises(ExecutionDenied,match='call'): guard.reserve(attempt)


def test_benchmark_rejects_plan_tampering(tmp_path):
    proposal=plan(ROOT/'data/scenarios.jsonl',ROOT/'data/manifest.json',ROOT/'configs/mock-baseline.json',ROOT/'configs/mock-baseline.json',['vb-001'],1)
    proposal['repeats']=10
    with pytest.raises(ExecutionDenied,match='plan_changed'):
        execute_plan(proposal,ROOT/'data/scenarios.jsonl',ROOT/'data/manifest.json',tmp_path,approval=proposal['approval_sha256'])


def test_annotation_pack_blinds_judge_and_rejects_empty_human_labels(tmp_path):
    config=Experiment(name='annotation',execution={'case_ids':['vb-029']})
    run=run_evaluation(DRAFT/'scenarios.jsonl',DRAFT/'manifest.json',config,tmp_path/'run')
    annotation_pack(DRAFT/'scenarios.jsonl',DRAFT/'manifest.json',DRAFT/'registry.json',[tmp_path/'run/run.json'],tmp_path/'review')
    public=json.loads((tmp_path/'review/reviewer-samples.jsonl').read_text())
    assert 'judge' not in public and 'judge_signature' not in public
    with pytest.raises(ValueError): agreement(tmp_path/'review/samples.jsonl',[tmp_path/'review/reviewer-a.jsonl'])


def test_heldout_agreement_requires_two_reviewers_reports_missing_judge(tmp_path):
    scores=dict(correctness=4,instruction_following=4,privacy_safety=5,age_appropriateness=4,rationale='test fixture only')
    sample=dict(sample_id='example',split='heldout',language='hi',judge=scores,judge_signature={'version':'fixture'})
    samples=tmp_path/'samples.jsonl';samples.write_text(json.dumps(sample)+'\n')
    labels=tmp_path/'labels.jsonl'
    def write(reviewers):
        labels.write_text(''.join(json.dumps(dict(sample_id='example',source='human',reviewer_id=r,scores=scores))+'\n' for r in reviewers))
    write(['a'])
    with pytest.raises(ValueError,match='two independent'): agreement(samples,[labels])
    write(['a','b'])
    result=agreement(samples,[labels])
    assert result['groups']['hi']['dimensions']['correctness']['judge_vs_human_mean_absolute_error']==0
    assert 'excluded from CI' in result['status']
    sample['judge']=None;samples.write_text(json.dumps(sample)+'\n')
    result=agreement(samples,[labels])
    assert result['groups']['all']['judge_missing']==1
    assert quadratic_kappa([1,2,4],[1,2,4])==1
    assert quadratic_kappa([],[]) is None
    assert quadratic_kappa([5],[5]) is None  # exact agreement exists, kappa is undefined
