"""Explicit local disposable-DB tests; no model API transport is ever used.

Opt in with VAANIBENCH_TEST_POSTGRES_URL. This database MUST be disposable.
"""
import os
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from contextlib import ExitStack
import time
from urllib.parse import urlsplit

import pytest
from starlette.testclient import TestClient

from vaanibench.storage import connect_postgres,postgres_lease
from vaanibench.hosted_state import StateStore
from vaanibench.costs import ExecutionDenied
from vaanibench.models import APIAttempt
from vaanibench.hosted import Settings,create_app
from tests.test_hosted import ROOT,PASSWORD_HASH,boot,headers,login,selection,wait

URL=os.environ.get('VAANIBENCH_TEST_POSTGRES_URL')
pytestmark=pytest.mark.skipif(not URL,reason='Explicit disposable local PostgreSQL URL not configured')


@pytest.fixture
def pg(tmp_path):
    parsed=urlsplit(URL)
    if parsed.hostname not in {'localhost','127.0.0.1','postgres'} or parsed.path!='/vaanibench_test':
        pytest.fail('Integration tests require a local disposable database named vaanibench_test')
    # This destructive reset is restricted to the explicitly named test database.
    with connect_postgres(URL) as connection: connection.execute('DROP SCHEMA IF EXISTS vaanibench CASCADE')
    return StateStore(tmp_path,database_url=URL,daily_usd=Decimal('.01'),daily_calls=2)


def test_postgres_atomic_budget_migration_and_lease(pg,tmp_path):
    def reserve(_):
        try:
            pg.daily_guard('job').reserve(APIAttempt(number=1,purpose='generation',model='fixture',retry_index=0,
                reserved_usd=Decimal('.005'),accounted_usd=Decimal('.005')))
            return True
        except ExecutionDenied: return False
    with ThreadPoolExecutor(max_workers=6) as pool: assert sum(pool.map(reserve,range(8)))==2
    restarted=StateStore(tmp_path,database_url=URL)
    assert restarted.daily_usage()['accounted_usd']=='0.01'
    assert restarted.daily_usage()['calls']==2
    with restarted.db() as db: assert db.execute('SELECT max(version) FROM schema_migrations').fetchone()[0]==2
    with ThreadPoolExecutor(max_workers=5) as pool:
        submissions=list(pool.map(lambda _:restarted.create_submission('operator','same-key','same-payload'),range(5)))
    assert len({job for job,created in submissions})==1 and sum(created for job,created in submissions)==1
    with postgres_lease(URL):
        with pytest.raises(RuntimeError,match='Another hosted instance'):
            with postgres_lease(URL): pass


def test_postgres_owner_jobs_reports_and_budget_survive_new_scratch_directory(pg,tmp_path,monkeypatch):
    from vaanibench import runner
    from vaanibench.providers import GroqProvider
    import io
    monkeypatch.setenv('GROQ_API_KEY','test-only-not-a-key')
    calls=[]
    def transport(request,timeout):
        calls.append(1)
        return io.BytesIO(json.dumps(dict(model='openai/gpt-oss-20b',choices=[dict(finish_reason='stop',message=dict(content='5'))],usage=dict(prompt_tokens=10,completion_tokens=1))).encode())
    monkeypatch.setattr(runner,'make_provider',lambda config,ledger,**kw:GroqProvider(config,ledger=ledger,transport=transport,**kw))
    settings=Settings(ROOT,tmp_path/'first',origin='https://testserver',database_url=URL,owner_password_hash=PASSWORD_HASH,live_enabled=True,mock_pace_seconds=0,daily_calls=2)
    with TestClient(create_app(settings),base_url=settings.origin) as client:
        owner=login(client,boot(client))
        auth=headers(owner)|{'Idempotency-Key':'postgres-submission-test'}
        body=selection(baseline='groq-baseline',candidate='groq-candidate',case_ids=['vb-001'],confirm_live=True)
        job=client.post('/api/runs',headers=auth,json=body).json()['job_id']
        assert wait(client,job)['status']=='completed'
        assert len(calls)==2
        assert client.post('/api/runs',headers=auth,json=body).json()['job_id']==job
        assert client.get('/api/operations').json()['daily_usage']['calls']==2
        cookies=dict(client.cookies)
    shutil.rmtree(settings.state_dir)
    settings.state_dir=tmp_path/'second'
    with TestClient(create_app(settings),base_url=settings.origin) as client:
        client.cookies.update(cookies)
        owner=boot(client)
        assert owner['authenticated'] and owner['daily_usage']['calls']==2
        assert client.get(f'/api/jobs/{job}/download/baseline-run.json').status_code==200
        assert client.get('/api/history').json()['jobs'][0]['id']==job
        new=client.post('/api/runs',headers=headers(owner),json=body).json()['job_id']
        assert wait(client,new)['result']['runs']['baseline']['cases'][0]['status']=='skipped'
        assert len(calls)==2


def test_rolling_deploy_standby_does_not_recover_active_predecessor(pg,tmp_path):
    old_settings=Settings(ROOT,tmp_path/'old',origin='https://testserver',database_url=URL,
        owner_password_hash=PASSWORD_HASH,mock_pace_seconds=0)
    from vaanibench.hosted_auth import password_hash
    new_settings=Settings(ROOT,tmp_path/'new',origin='https://testserver',database_url=URL,
        owner_password_hash=password_hash('new deployment owner password'),mock_pace_seconds=0)
    with ExitStack() as old_stack:
        old=old_stack.enter_context(TestClient(create_app(old_settings),base_url=old_settings.origin))
        owner=login(old,boot(old))
        store=old.app.state.service.store
        job=store.create_job('operator')
        store.daily_guard(job).reserve(APIAttempt(number=1,purpose='generation',model='fixture',retry_index=0,
            reserved_usd=Decimal('.005'),accounted_usd=Decimal('.005')))
        with TestClient(create_app(new_settings),base_url=new_settings.origin) as replacement:
            health=replacement.get('/healthz')
            assert health.status_code==200
            assert health.json()['deployment_state']=='standby' and not health.json()['execution_ready']
            assert replacement.get('/api/bootstrap').status_code==503
            assert replacement.post('/api/runs',headers=headers(owner),json=selection()).status_code==503
            assert replacement.get('/api/history').status_code==503
            assert store.snapshot(job,'operator')['status']=='running'
            assert boot(old)['authenticated']  # standby has not rotated owner credentials
            old_stack.close()  # Render retires the predecessor after the new health check passes
            for _ in range(100):
                if replacement.app.state.service.ready.is_set(): break
                time.sleep(.05)
            assert replacement.get('/healthz').json()['deployment_state']=='active'
            current=replacement.app.state.service.store
            assert current.snapshot(job,'operator')['status']=='interrupted'
            assert current.daily_usage()['accounted_usd']=='0.005'
            visitor=boot(replacement)
            submitted=replacement.post('/api/runs',headers=headers(visitor),json=selection())
            assert submitted.status_code==202
            assert wait(replacement,submitted.json()['job_id'])['status']=='completed'
