"""① 마지막 취소 검사 뒤 attempt가 바뀌어도 저장 직전 펜싱해야 합니다."""

from decimal import Decimal

import pytest
from test_eng_worker import dependencies
from test_eng_worker import engine_db as engine_db
from test_eng_worker import experiment as experiment

from slotagent.engine import worker
from slotagent.engine.loop import RunCancelled


def test_attempt_changed_after_last_cancel_check(experiment, monkeypatch):
    conn, ids = experiment
    trial = ids["trials"][0]
    validate = worker.contracts.validate
    changed = []

    def late_change(name, value, *args, **kwargs):
        if name == "trace" and value.get("trial_id") == trial:
            conn.execute("UPDATE sa_trials SET attempt=attempt+1 WHERE trial_id=%s", (trial,))
            changed.append(True)
        return validate(name, value, *args, **kwargs)

    monkeypatch.setattr(worker.contracts, "validate", late_change)
    with pytest.raises(RunCancelled, match="소유권"):
        worker.run_trial(conn, trial, deps=dependencies())
    assert changed == [True]
    assert conn.execute("SELECT status,attempt FROM sa_trials WHERE trial_id=%s", (trial,)).fetchone() == ("running", 2)
    assert conn.execute("SELECT count(*) FROM sa_spans WHERE trial_id=%s", (trial,)).fetchone() == (0,)
    assert conn.execute("SELECT count(*),sum(cost_krw) FROM sa_cost_ledger WHERE ref_id=%s", (trial,)).fetchone() == (
        2,
        Decimal("0.264"),
    )
