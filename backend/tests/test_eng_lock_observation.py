"""① 변경 전 실제 SQL 상태 조건을 유지한 FK·중단 경합 관찰."""

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import psycopg
import pytest
from test_eng_costs import receipt
from test_eng_worker import dependencies
from test_eng_worker import engine_db as engine_db
from test_eng_worker import experiment as experiment

from slotagent.common import queue
from slotagent.engine import advance
from slotagent.engine.costs import record_trial_cost
from slotagent.engine.worker import run_trial


class Observe:
    def __init__(self, conn, hook):
        self.conn, self.hook = conn, hook

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def execute(self, query, *args, **kwargs):
        result = self.conn.execute(query, *args, **kwargs)
        self.hook(str(query))
        return result

    def cursor(self, *args, **kwargs):
        owner = self
        raw = self.conn.cursor(*args, **kwargs)

        class Cursor:
            def __enter__(self):
                raw.__enter__()
                return self

            def __exit__(self, *args):
                return raw.__exit__(*args)

            def execute(self, query, *args, **kwargs):
                result = raw.execute(query, *args, **kwargs)
                owner.hook(str(query))
                return result

        return Cursor()


def blocked(observer, pid, blocker):
    until = time.monotonic() + 5
    while time.monotonic() < until:
        if blocker in observer.execute("SELECT pg_blocking_pids(%s)", (pid,)).fetchone()[0]:
            return
        time.sleep(0.005)
    raise AssertionError("지정한 DB 잠금 대기를 관찰하지 못했습니다.")


def test_cost_fk_observation(experiment, engine_db):
    observer, ids = experiment
    elapsed = []
    for index in range(20):
        with psycopg.connect(engine_db, autocommit=True) as final, psycopg.connect(engine_db, autocommit=True) as cost:
            cost.execute("SET statement_timeout='8s'")
            with ThreadPoolExecutor(1) as pool:
                with final.transaction():
                    final.execute(
                        "SELECT experiment_id FROM sa_experiments WHERE experiment_id=%s FOR UPDATE",
                        (ids["experiment"],),
                    )
                    start = time.monotonic()
                    pending = pool.submit(record_trial_cost, cost, **receipt(ids, ids["trials"][0], seq=index + 1))
                    blocked(observer, cost.info.backend_pid, final.info.backend_pid)
                    assert not pending.done()
                pending.result(timeout=8)
                elapsed.append(time.monotonic() - start)
    assert observer.execute(
        "SELECT count(*) FROM sa_cost_ledger WHERE experiment_id=%s", (ids["experiment"],)
    ).fetchone() == (20,)
    print(f"FK FOR UPDATE: 20/20 대기, 해제 후 20/20 저장, 대기 포함 초 {min(elapsed):.3f}~{max(elapsed):.3f}")


@pytest.mark.parametrize("mode", ["guard", "lease", "resume"])
@pytest.mark.parametrize("iteration", range(20))
def test_stop_overlap_observation(experiment, engine_db, mode, iteration):
    observer, ids = experiment
    trial = ids["trials"][0]
    job_id = advance.enqueue(observer, {"schema_version": 1, "kind": "run_trial", "trial_id": trial})
    job = queue.lease(observer, "observe") if mode == "guard" else None
    if mode == "resume":
        observer.execute("UPDATE sa_jobs SET status='failed' WHERE job_id=%s", (job_id,))
    experiment_locked, job_locked, continue_stop, release_lease = (Event() for _ in range(4))
    with (
        psycopg.connect(engine_db, autocommit=True) as stopping,
        psycopg.connect(engine_db, autocommit=True) as working,
    ):
        for conn in (stopping, working):
            conn.execute("SET statement_timeout='8s'")
            conn.execute("SET deadlock_timeout='100ms'")

        def stop_hook(query):
            if query.startswith("UPDATE sa_experiments"):
                experiment_locked.set()
                assert continue_stop.wait(5)

        def work_hook(query):
            target = (
                (mode == "guard" and "SELECT job_id FROM sa_jobs" in query)
                or (mode == "resume" and "FOR UPDATE" in query and "sa_jobs" in query)
                or (mode == "lease" and "WITH ready AS" in query)
            )
            if target and not job_locked.is_set():
                job_locked.set()
                assert (release_lease if mode == "lease" else experiment_locked).wait(5)

        def stop():
            with stopping.transaction():
                return advance.stop_experiment(Observe(stopping, stop_hook), ids["experiment"], "user")

        def work():
            proxy = Observe(working, work_hook)
            if mode == "guard":
                return run_trial(proxy, trial, deps=dependencies(), job=job)
            if mode == "lease":
                return queue.lease(proxy, "observe")
            try:
                advance.resume_failed_trial(proxy, trial)
            except ValueError as exc:
                assert "중단" in str(exc)
                return "stopped"
            raise AssertionError("중단된 실험을 재개하면 안 됩니다.")

        with ThreadPoolExecutor(2) as pool:
            worker = pool.submit(work)
            try:
                assert job_locked.wait(5)
                stopper = pool.submit(stop)
                assert experiment_locked.wait(5)
                if mode == "lease":
                    continue_stop.set()
                    blocked(observer, stopping.info.backend_pid, working.info.backend_pid)
                    release_lease.set()
                else:
                    blocked(observer, working.info.backend_pid, stopping.info.backend_pid)
                    continue_stop.set()
                stopper.result(timeout=8)
                worker.result(timeout=8)
            finally:
                continue_stop.set()
                release_lease.set()
    assert observer.execute("SELECT status FROM sa_trials WHERE trial_id=%s", (trial,)).fetchone() == ("cancelled",)
