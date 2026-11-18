import pytest


def test_progress_order_and_payload(execute):
    events = []
    run = execute(on_event=events.append)
    assert events[0]["event"] == "run_started"
    assert events[-1]["event"] == "run_completed"
    assert len([e for e in events if e["event"] == "case_started"]) == 20
    assert len([e for e in events if e["event"] == "case_completed"]) == 20
    assert [e["result"]["scenario_id"] for e in events if e["event"] == "case_completed"] == [c.scenario_id for c in run.cases]


def test_progress_failure_does_not_abort_or_echo_exception(execute):
    def bad(event): raise RuntimeError("secret-from-listener")
    with pytest.warns(RuntimeWarning, match="Progress listener failed") as warnings:
        run = execute(on_event=bad)
    assert len(run.cases) == 20
    assert all("secret-from-listener" not in str(w.message) for w in warnings)
