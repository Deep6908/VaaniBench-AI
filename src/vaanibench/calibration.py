"""Human annotation and held-out judge agreement; never manufactures human labels."""
from __future__ import annotations

import hashlib
import json
import statistics
from collections import defaultdict,Counter
from pathlib import Path
from typing import Literal

from .models import JudgeScores
from .schemas import Contract, Text, digest, validate_dataset
from .report import load_run
from .providers import judge_provider_name

DIMENSIONS=("correctness","instruction_following","privacy_safety","age_appropriateness")


class HumanLabel(Contract):
    sample_id: Text
    reviewer_id: Text
    source: Literal["human"]
    scores: JudgeScores


def annotation_pack(dataset, manifest, registry, run_paths, output):
    cases,_=validate_dataset(dataset,manifest)
    cases={c.id:c for c in cases}
    metadata=json.loads(Path(registry).read_text(encoding="utf-8"))
    if set(metadata)!=set(cases): raise ValueError('Registry must identify every dataset case exactly once')
    families=defaultdict(set)
    for info in metadata.values():
        if info['split'] not in {'development','calibration','heldout'}: raise ValueError('Unknown evaluation split')
        families[info['family']].add(info['split'])
    if any(len(splits)>1 for splits in families.values()): raise ValueError('Scenario family leaks across splits')
    records=[]
    for path in run_paths:
        run=load_run(path)
        if run.dataset_sha256!=digest(dataset): raise ValueError("Run dataset differs from annotation dataset")
        for result in run.cases:
            if result.status!='ok' or not result.response: continue
            case=cases[result.scenario_id]
            if result.scenario_hash!=hashlib.sha256(case.model_dump_json().encode()).hexdigest():
                raise ValueError('Scenario content differs from recorded response')
            info=metadata[case.id]
            response_hash=hashlib.sha256(result.response.text.encode()).hexdigest()
            sample=hashlib.sha256(f'{run.run_id}:{case.id}:{response_hash}'.encode()).hexdigest()
            records.append(dict(sample_id=sample,run_id=run.run_id,scenario_id=case.id,
                split=info['split'],family=info['family'],language=case.language,
                dataset_sha256=run.dataset_sha256,response_sha256=response_hash,
                conversation=[m.model_dump() for m in case.messages],rubric=case.rubric,
                reference_answer=case.reference_answer,response=result.response.text,
                judge=result.judge.model_dump() if result.judge else None,
                judge_signature=dict(model=run.config.judge_model,provider=judge_provider_name(run.config),
                    prompt=run.judge_prompt_sha256,version=run.judge_version,seed=run.config.seed,
                    max_tokens=run.config.judge_max_tokens,temperature=0.0)))
    if len({r['sample_id'] for r in records})!=len(records): raise ValueError("Duplicate annotation samples")
    if not records: raise ValueError("No successful responses to annotate")
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    if (output/'samples.jsonl').exists(): raise ValueError("Annotation pack already exists")
    # Reviewers do not see model identity or judge scores, reducing anchoring.
    public=[{k:v for k,v in r.items() if k not in {'judge','judge_signature','run_id','split'}} for r in records]
    for name,values in [('samples.jsonl',records),('reviewer-samples.jsonl',public)]:
        (output/name).write_text(''.join(json.dumps(v,ensure_ascii=False)+'\n' for v in values),encoding='utf-8')
    for reviewer in ['reviewer-a','reviewer-b']:
        templates=[dict(sample_id=r['sample_id'],reviewer_id=reviewer,source='human',scores={**{k:None for k in DIMENSIONS},'rationale':''}) for r in records]
        (output/(reviewer+'.jsonl')).write_text(''.join(json.dumps(t)+'\n' for t in templates),encoding='utf-8')
    return dict(samples=len(records),status='awaiting independent human labels')


def quadratic_kappa(a,b):
    if not a: return None
    observed=sum((x-y)**2 for x,y in zip(a,b))/len(a)
    expected=sum((x-y)**2*nx*ny for x,nx in Counter(a).items() for y,ny in Counter(b).items())/(len(a)**2)
    return 1-observed/expected if expected else None


def agreement(samples_path, label_paths, *, split='heldout'):
    samples=[json.loads(line) for line in Path(samples_path).read_text(encoding='utf-8').splitlines()]
    if len({s['sample_id'] for s in samples})!=len(samples): raise ValueError('Duplicate samples')
    known={s['sample_id']:s for s in samples}
    labels=defaultdict(dict)
    for path in label_paths:
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            label=HumanLabel.model_validate_json(line)
            if label.sample_id not in known or label.reviewer_id in labels[label.sample_id]: raise ValueError('Unknown sample or duplicate reviewer rating')
            labels[label.sample_id][label.reviewer_id]=label.scores
    selected=[s for s in samples if s['split']==split]
    if not selected: raise ValueError('No samples in requested split')
    signatures={json.dumps(s['judge_signature'],sort_keys=True) for s in selected if s['judge']}
    if len(signatures)>1: raise ValueError('Mixed judge settings; analyze each frozen judge separately')
    if any(len(labels[s['sample_id']])<2 for s in selected): raise ValueError('Every selected sample requires at least two independent reviewers')
    groups={}
    for language in ['all']+sorted({s['language'] for s in selected}):
        group=[s for s in selected if language=='all' or s['language']==language]
        metrics={}
        for dimension in DIMENSIONS:
            human_a=[];human_b=[];judge=[];consensus=[];disagreements=[]
            for sample in group:
                values=[getattr(v,dimension) for _,v in sorted(labels[sample['sample_id']].items())]
                for i,a in enumerate(values):
                    for b in values[i+1:]: human_a.append(a);human_b.append(b)
                if sample['judge']:
                    score=JudgeScores.model_validate(sample['judge'])
                    j=getattr(score,dimension); mean=statistics.mean(values)
                    judge.append(j);consensus.append(mean)
                    if abs(j-mean)>=1: disagreements.append(dict(sample_id=sample['sample_id'],human_scores=values,judge=j))
            metrics[dimension]=dict(human_pairs=len(human_a),human_exact_agreement=sum(a==b for a,b in zip(human_a,human_b))/len(human_a),
                human_quadratic_kappa=quadratic_kappa(human_a,human_b),judge_samples=len(judge),
                judge_vs_human_mean_absolute_error=statistics.mean(abs(a-b) for a,b in zip(judge,consensus)) if judge else None,
                judge_within_one_of_human_mean=sum(abs(a-b)<=1 for a,b in zip(judge,consensus))/len(judge) if judge else None,
                disagreements=disagreements)
        groups[language]=dict(samples=len(group),judge_missing=sum(not s['judge'] for s in group),dimensions=metrics)
    return dict(split=split,samples=len(selected),groups=groups,
        labels_sha256=[digest(p) for p in label_paths],samples_sha256=digest(samples_path),
        status='Agreement evidence only; calibration acceptance requires documented human review. Judge scores remain excluded from CI gates.')
