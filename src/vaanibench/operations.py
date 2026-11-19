"""Owner operational snapshot over retained jobs, with explicit denominators."""
import json
from decimal import Decimal

from .report import percentile


def snapshot(store,thresholds):
    with store.db() as db:
        rows=db.execute('SELECT status,result FROM jobs WHERE owner=? AND created>=? ORDER BY created DESC LIMIT 100',('operator',store.clock()-store.retention_seconds)).fetchall()
    cases=[];attempts=0;failed_jobs=0;judge_errors=0;mode_counts=dict(mock=0,live=0)
    for row in rows:
        failed_jobs+=row['status'] in {'failed','interrupted','cancelled'}
        if not row['result']: continue
        result=json.loads(row['result'])
        for run in result.get('runs',{}).values():
            mode='mock' if run['config']['provider']=='mock' else 'live'
            mode_counts[mode]+=len(run['cases'])
            if mode=='mock': continue
            cases.extend(run['cases'])
            attempts+=run['summary']['live_api_calls']
            judge_errors+=run['summary']['judge_errors']
    attempted=[c for c in cases if c['status']!='skipped']
    errors=sum(c['status']=='error' for c in attempted)
    error_rate=errors/len(attempted) if attempted else None
    p95=percentile([c['latency_ms'] for c in attempted],.95)
    daily=store.daily_usage()
    fraction=max(daily['calls']/daily['max_calls'],float(Decimal(daily['accounted_usd'])/Decimal(daily['max_usd'])))
    alerts=[]
    if fraction>=thresholds['daily_budget_fraction_warning']: alerts.append('Daily budget/call allowance nearing exhaustion; reduce or pause live runs.')
    if len(attempted)>=thresholds['minimum_request_samples']:
        if error_rate>=thresholds['error_rate_warning']: alerts.append('Generation errors exceed threshold; inspect failed case trace IDs and provider status.')
        if p95>=thresholds['p95_latency_ms_warning']: alerts.append('Generation p95 latency exceeds threshold; inspect provider/retry traces.')
    if failed_jobs: alerts.append('Retained jobs include failed/interrupted/cancelled work; inspect history before retrying.')
    return dict(retained_jobs=len(rows),attempted_cases=len(attempted),generation_errors=errors,error_rate=error_rate,
        skipped_cases=sum(c['status']=='skipped' for c in cases),judge_errors=judge_errors,p95_latency_ms=p95,
        live_attempts_in_retained_results=attempts,daily_usage=daily,alerts=alerts,
        scope='Live owner cases in retained jobs (maximum 100 jobs). Case latency includes retry time, excludes judge. Mode counts also show mock cases; incomplete jobs may lack result-level metrics.',
        by_mode=mode_counts,thresholds=thresholds)
