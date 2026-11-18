from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from vaanibench.costs import BudgetLedger, ExecutionDenied, load_prices
from vaanibench.hosted_auth import password_hash, verify_password
from vaanibench.hosted_state import StateStore, RateLimited
from vaanibench.models import APIAttempt, ExecutionPolicy, Usage


def attempt(amount="0.01"):
    return APIAttempt(number=1,purpose="generation",model="gpt-4.1-mini",retry_index=0,
        reserved_usd=Decimal(amount),accounted_usd=Decimal(amount))


def test_password_hash_and_verification():
    value=password_hash("a long owner test password")
    assert verify_password("a long owner test password",value)
    assert not verify_password("wrong",value)
    assert not verify_password("anything","not-a-hash")
    with pytest.raises(ValueError): password_hash("short")


def test_sessions_rotate_and_expire(tmp_path):
    now=[1795003200.0]
    store=StateStore(tmp_path,clock=lambda:now[0])
    first,identity=store.new_session()
    second,owner=store.new_session(role="owner",old_token=first)
    assert store.session(first) is None
    assert owner["role"] == "owner" and owner["owner"] == "operator"
    assert owner["csrf"] != identity["csrf"]
    now[0]+=3601
    assert store.session(second) is None


def test_job_ownership_and_restart(tmp_path):
    store=StateStore(tmp_path)
    job=store.create_job("alice")
    store.event(job,"baseline",dict(event="case_started",scenario_id="vb-001"))
    with pytest.raises(KeyError): store.snapshot(job,"bob")
    restarted=StateStore(tmp_path)
    restarted.recover()
    info=restarted.snapshot(job,"alice")
    assert info["status"] == "interrupted" and len(info["events"]) == 1


def test_daily_reservations_survive_restart_and_unknown_usage(tmp_path):
    store=StateStore(tmp_path,daily_calls=1)
    reservation=store.daily_guard("job").reserve(attempt())
    restarted=StateStore(tmp_path,daily_calls=1)
    restarted.recover()
    assert restarted.daily_usage()["accounted_usd"] == "0.01"
    with pytest.raises(ExecutionDenied,match="daily_call_limit"):
        restarted.daily_guard("other").reserve(attempt())
    restarted.daily_guard("job").reconcile(reservation,Decimal("0.002"))
    assert restarted.daily_usage()["accounted_usd"] == "0.002"


def test_daily_usd_atomic_boundary(tmp_path):
    store=StateStore(tmp_path,daily_usd=Decimal("0.01"))
    def reserve(_):
        try: store.daily_guard("job").reserve(attempt("0.005")); return True
        except ExecutionDenied: return False
    with ThreadPoolExecutor(max_workers=6) as pool:
        results=list(pool.map(reserve,range(8)))
    assert sum(results)==2
    assert store.daily_usage()["accounted_usd"] == "0.01"


def test_daily_guard_integrates_before_attempt_and_reconciles(tmp_path):
    store=StateStore(tmp_path,daily_calls=1)
    ledger=BudgetLedger(ExecutionPolicy(allow_live=True,all_cases=True),load_prices("configs/pricing.json"))
    ledger.daily_guard=store.daily_guard("job")
    item=ledger.reserve("gpt-4.1-mini","generation",[],256,0)
    assert item.daily_reservation_id
    ledger.reconcile(item,Usage(input_tokens=10,output_tokens=1))
    assert store.daily_usage()["accounted_usd"] == str(item.accounted_usd)
    with pytest.raises(ExecutionDenied): ledger.reserve("gpt-4.1-mini","judge",[],256,0)
    assert len(ledger.attempts)==1


def test_cleanup_retains_budget_but_removes_expired_results(tmp_path):
    now=[1795003200.0]
    store=StateStore(tmp_path,clock=lambda:now[0],retention_seconds=30)
    job=store.create_job("alice")
    store.finish(job,result={"done":True})
    output=tmp_path/"runs"/job
    output.mkdir(parents=True)
    (output/"run.json").write_text("{}")
    store.daily_guard(job).reserve(attempt())
    now[0]+=31
    with pytest.raises(KeyError): store.snapshot(job,"alice")
    store.cleanup()
    assert not output.exists()
    assert store.daily_usage()["calls"] == 1
    with pytest.raises(KeyError): store.snapshot(job,"alice")


def test_concurrency_and_persistent_rate_limits(tmp_path):
    store=StateStore(tmp_path)
    store.create_job("one")
    with pytest.raises(RateLimited): store.create_job("one")
    store.create_job("two")
    with pytest.raises(RateLimited): store.create_job("three")
    store.rate("login",1,60)
    with pytest.raises(RateLimited): StateStore(tmp_path).rate("login",1,60)


def test_auth_change_revokes_owner_sessions_without_resetting_budget(tmp_path):
    store=StateStore(tmp_path)
    store.auth_revision("first")
    owner,_=store.new_session(role="owner")
    visitor,_=store.new_session()
    store.daily_guard("job").reserve(attempt())
    store.auth_revision("second")
    assert store.session(owner) is None
    assert store.session(visitor) is not None
    assert store.daily_usage()["calls"]==1


def test_job_history_eviction_is_bounded_without_resetting_budget(tmp_path):
    store=StateStore(tmp_path)
    with store.db(write=True) as db:
        db.executemany("INSERT INTO jobs VALUES(?,?,'completed',?,'[]','{}',NULL)",
            [(f"{i:024x}","old",store.clock()-10+i*.001) for i in range(100)])
    store.daily_guard("0"*24).reserve(attempt())
    store.create_job("new")
    with store.db() as db:
        assert db.execute("SELECT count(*) FROM jobs").fetchone()[0]==100
    assert store.daily_usage()["calls"]==1


def test_cancelled_job_cannot_reserve_another_http_attempt(tmp_path):
    store=StateStore(tmp_path)
    guard=store.daily_guard("job",stop_when=lambda:True)
    with pytest.raises(ExecutionDenied,match="execution_cancelled"):
        guard.reserve(attempt())
    assert store.daily_usage()["calls"]==0


def test_existing_session_can_rotate_when_visitor_capacity_is_full(tmp_path):
    store=StateStore(tmp_path)
    token,_=store.new_session()
    with store.db(write=True) as db:
        db.executemany("INSERT INTO sessions VALUES(?,?,?,?,?)",[(str(i),str(i),"visitor","csrf",store.clock()+3600) for i in range(999)])
    new,identity=store.new_session(role="owner",old_token=token)
    assert identity["role"]=="owner" and store.session(token) is None
    assert store.session(new) is not None
