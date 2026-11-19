"""Storage contracts and production-path tests; provider transport remains fake."""
import json
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from starlette.testclient import TestClient

from tests.test_hosted import ROOT, PASSWORD_HASH, boot, headers, login, selection, wait
from vaanibench.hosted import Settings, create_app
from vaanibench.hosted_state import StateStore


def test_old_sqlite_migrates_without_erasing_budget(tmp_path):
    import sqlite3
    db=sqlite3.connect(tmp_path/'state.sqlite3')
    db.executescript("CREATE TABLE attempts(id TEXT PRIMARY KEY,job_id TEXT,day TEXT,accounted INTEGER); INSERT INTO attempts VALUES('reservation','job','2099-01-01',123);")
    db.close()
    store=StateStore(tmp_path)
    with store.db() as db:
        assert db.execute('SELECT max(version) FROM schema_migrations').fetchone()[0]==2
        assert db.execute('SELECT accounted FROM attempts').fetchone()[0]==123
    assert StateStore(tmp_path).history('operator')==[]


def test_atomic_idempotency_and_payload_conflict(tmp_path):
    store=StateStore(tmp_path)
    with ThreadPoolExecutor(max_workers=5) as pool:
        results=list(pool.map(lambda _:store.create_submission('operator','key','hash'),range(5)))
    assert len({r[0] for r in results})==1
    assert sum(r[1] for r in results)==1
    with pytest.raises(ValueError): store.create_submission('operator','key','different')


def test_artifacts_and_cancellation_ownership_and_retention(tmp_path):
    store=StateStore(tmp_path)
    job=store.create_job('operator')
    with pytest.raises(KeyError): store.cancel(job,'stranger')
    store.cancel(job,'operator')
    assert store.cancelled(job)
    store.finish(job,result={'done':True},artifacts={'report.md':'saved'},cancelled=True)
    restarted=StateStore(tmp_path)
    assert restarted.snapshot(job,'operator')['status']=='cancelled'
    assert restarted.artifact(job,'operator','report.md')=='saved'
    with pytest.raises(KeyError): restarted.artifact(job,'stranger','report.md')


def test_hosted_replay_history_and_download_survive_missing_local_files(tmp_path):
    settings=Settings(ROOT,tmp_path/'state',origin='https://testserver',owner_password_hash=PASSWORD_HASH,mock_pace_seconds=0)
    with TestClient(create_app(settings),base_url=settings.origin) as client:
        owner=login(client,boot(client))
        auth=headers(owner)|{'Idempotency-Key':'a-unique-submission-key'}
        job=client.post('/api/runs',headers=auth,json=selection()).json()['job_id']
        assert wait(client,job)['status']=='completed'
        assert client.post('/api/runs',headers=auth,json=selection()).json()['job_id']==job
        assert client.post('/api/runs',headers=auth,json=selection(case_ids=['vb-001'])).status_code==400
        assert client.get('/api/history?q=mock-baseline').json()['jobs'][0]['id']==job
        assert client.get('/api/history?status=failed').json()['jobs']==[]
        comparison=client.post('/api/compare',headers=headers(owner),json=dict(baseline_job=job,candidate_job=job,baseline_side='baseline',candidate_side='candidate'))
        assert comparison.status_code==200 and not comparison.json()['passed']
        cookies=dict(client.cookies)
    shutil.rmtree(tmp_path/'state'/'runs')
    with TestClient(create_app(settings),base_url=settings.origin) as client:
        client.cookies.update(cookies)
        assert client.get(f'/api/jobs/{job}/download/baseline-run.json').json()['cases']
        client.cookies.clear(); visitor=boot(client)
        assert client.get('/api/history').status_code==403
        assert client.post(f'/api/jobs/{job}/cancel',headers=headers(visitor)).status_code==404


def test_cancellation_stops_following_cases(tmp_path,monkeypatch):
    from vaanibench import runner
    from vaanibench.providers import MockProvider
    from vaanibench.models import Experiment
    entered,release=threading.Event(),threading.Event()
    class Slow:
        def generate(self,messages):
            entered.set(); assert release.wait(5)
            return MockProvider(Experiment(name='slow')).generate(messages)
    monkeypatch.setattr(runner,'make_provider',lambda *a,**kw:Slow())
    settings=Settings(ROOT,tmp_path/'state',origin='https://testserver',mock_pace_seconds=0)
    with TestClient(create_app(settings),base_url=settings.origin) as client:
        visitor=boot(client)
        job=client.post('/api/runs',headers=headers(visitor),json=selection()).json()['job_id']
        assert entered.wait(5)
        assert client.post(f'/api/jobs/{job}/cancel',headers=headers(visitor)).status_code==200
        release.set()
        result=wait(client,job)
        assert result['status']=='cancelled'
        cases=[c for r in result['result']['runs'].values() for c in r['cases']]
        assert sum(c['status']=='skipped' for c in cases)>=3


def test_postgres_requires_tls_and_can_use_ephemeral_local_scratch(tmp_path):
    with pytest.raises(ValueError): Settings(ROOT,tmp_path,database_url='postgresql://invalid/db')
    settings=Settings(ROOT,tmp_path,origin='https://testserver',production=True,live_enabled=True,
        owner_password_hash=PASSWORD_HASH,database_url='postgresql://fake:fake@db.invalid/db?sslmode=require')
    assert settings.live_enabled and 'fake@' not in repr(settings)


def test_sqlite_backup_restore_and_newer_schema_fail_closed(tmp_path):
    import sqlite3
    store=StateStore(tmp_path/'source')
    job=store.create_job('operator')
    store.finish(job,result={'done':True},artifacts={'report.md':'retained'})
    with sqlite3.connect(store.database) as source,sqlite3.connect(tmp_path/'backup.sqlite3') as backup:
        source.backup(backup)
    target=tmp_path/'restored';target.mkdir()
    shutil.copy2(tmp_path/'backup.sqlite3',target/'state.sqlite3')
    restored=StateStore(target)
    assert restored.artifact(job,'operator','report.md')=='retained'
    with restored.db(write=True) as db: db.execute('INSERT INTO schema_migrations VALUES(99,0)')
    with pytest.raises(ValueError,match='newer'): StateStore(target)
