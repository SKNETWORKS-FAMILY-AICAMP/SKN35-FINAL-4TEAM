"""① 명시적으로 실행하는 장시간 재점검. 기본 전체 회귀에서 중복 실행하지 않습니다."""

import json
import os
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from threading import Lock, local

import psycopg
import pytest
from eng_stress_fixture import large_experiment as large_experiment
from test_eng_docker import config, owned
from test_eng_docker import docker_cli as docker_cli
from test_eng_docker import docker_resources as docker_resources
from test_eng_queue import clean_queue as clean_queue
from test_eng_stdio import wait_dead
from test_eng_worker import dependencies
from test_eng_worker import engine_db as engine_db
from test_eng_worker import experiment as experiment

from slotagent.common import queue
from slotagent.engine import advance
from slotagent.engine.lock import lock_and_enqueue
from slotagent.workers.eng_main import run_once

POINTS = [
    "leased",
    "container_start",
    "model_pre_cost",
    "model_post_cost",
    "tool",
    "final_before",
    "final_after",
    "cleanup",
]


@pytest.mark.parametrize("point", POINTS)
@pytest.mark.parametrize("iteration", range(5))
def test_kill_recovery(experiment, engine_db, docker_resources, tmp_path, point, iteration):
    conn, ids = experiment
    trial = ids["trials"][0]
    job = advance.enqueue(conn, {"schema_version": 1, "kind": "run_trial", "trial_id": trial})
    marker = tmp_path / "gate.json"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(Path.cwd() / "src"), str(Path.cwd() / "tests")])}
    process = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).with_name("eng_reaudit_worker.py")),
            engine_db,
            docker_resources["image"],
            docker_resources["scope"],
            docker_resources["cli"],
            point,
            str(marker),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        deadline = time.monotonic() + 20
        while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists(), process.communicate(timeout=3) if process.poll() is not None else "gate 미도달"
        data = json.loads(marker.read_text(encoding="utf-8"))
        before = conn.execute("SELECT count(*) FROM sa_cost_ledger WHERE ref_id=%s", (trial,)).fetchone()[0]
        expected = (
            0
            if point in {"leased", "container_start", "model_pre_cost"}
            else 1
            if point in {"model_post_cost", "tool"}
            else 2
        )
        assert before == expected
        process.kill()
        process.communicate(timeout=5)
        wait_dead(process.pid)
        if data["client"]:
            wait_dead(data["client"])
        deadline = time.monotonic() + 5
        while conn.execute("SELECT count(*) FROM pg_stat_activity WHERE pid=%s", (data["backend"],)).fetchone()[0]:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        conn.execute("UPDATE sa_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE job_id=%s", (job,))
        assert run_once(
            lambda: psycopg.connect(engine_db, autocommit=True),
            "replacement",
            deps=dependencies(),
            stdio=config(docker_resources),
            heartbeat_sec=0.1,
        )
        assert conn.execute("SELECT status,attempt FROM sa_trials WHERE trial_id=%s", (trial,)).fetchone() == (
            "finished",
            1 if point == "leased" else 2,
        )
        assert conn.execute("SELECT status,attempts FROM sa_jobs WHERE job_id=%s", (job,)).fetchone() == ("done", 2)
        assert conn.execute("SELECT count(*) FROM sa_cost_ledger WHERE ref_id=%s", (trial,)).fetchone() == (before + 2,)
        assert conn.execute(
            "SELECT count(*),count(DISTINCT seq) FROM sa_spans WHERE trial_id=%s", (trial,)
        ).fetchone() == (3, 3)
        assert owned(docker_resources) == []
        print(f"kill {point}/{iteration}: cost {before}->{before + 2}, attempt=2, job=done, container/PID=0")
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
        remaining = owned(docker_resources)
        if remaining:
            subprocess.run([docker_resources["cli"], "rm", "-f", *remaining], check=True, capture_output=True)


@pytest.mark.parametrize("seed", [1124, 20261124, 8675309])
def test_four_workers_100_trials(large_experiment, engine_db, monkeypatch, seed):
    conn, ids = large_experiment
    exp = ids["experiment"]
    assert lock_and_enqueue(conn, exp)["trials_total"] == 100
    for trial in ids["trials"]:
        advance.enqueue(conn, {"schema_version": 1, "kind": "run_trial", "trial_id": trial})
    context, lock, keys, replies, failures = local(), Lock(), [], [], []
    original = queue.lease

    def lease(*args, **kwargs):
        job = original(*args, **kwargs)
        context.job = job
        if job:
            with lock:
                keys.append((job["job_id"], job["attempts"]))
        return job

    monkeypatch.setattr(queue, "lease", lease)

    def work(index):
        while True:
            deps = dependencies()
            chat = deps.model.chat

            def send(_deps=deps, _chat=chat, **kwargs):
                job = context.job
                rng = random.Random(seed + job["payload"]["trial_id"] * 71 + job["attempts"])
                if not _deps.model.requests and job["attempts"] == 1 and rng.random() < 0.15:
                    with lock:
                        failures.append(job["job_id"])
                    time.sleep(rng.random() * 0.03)
                    raise RuntimeError("응답 전 일시 실패")
                time.sleep(rng.random() * 0.01)
                reply = _chat(**kwargs)
                with lock:
                    replies.append(reply.cost_krw)
                return reply

            deps.model.chat = send
            try:
                if not run_once(
                    lambda: psycopg.connect(engine_db, autocommit=True), f"stress-{index}", deps=deps, heartbeat_sec=0.1
                ):
                    return
            except RuntimeError as exc:
                assert str(exc) == "응답 전 일시 실패"

    started = time.monotonic()
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(work, range(4)))
    assert len(keys) == len(set(keys))
    assert conn.execute(
        "SELECT status,count(*) FROM sa_trials WHERE experiment_id=%s GROUP BY status", (exp,)
    ).fetchall() == [("finished", 100)]
    assert conn.execute(
        "SELECT count(*),sum(cost_krw) FROM sa_cost_ledger WHERE experiment_id=%s", (exp,)
    ).fetchone() == (200, Decimal("26.4"))
    assert len(replies) == 200 and sum(replies) == Decimal("26.4")
    assert conn.execute(
        "SELECT count(*) FROM sa_spans s JOIN sa_trials t USING(trial_id) WHERE t.experiment_id=%s", (exp,)
    ).fetchone() == (300,)
    assert conn.execute(
        "SELECT count(*) FROM sa_grading_runs WHERE experiment_id=%s AND purpose='initial'", (exp,)
    ).fetchone() == (1,)
    assert conn.execute(
        "SELECT count(*) FROM sa_jobs j JOIN sa_grading_runs g ON (j.payload->>'grading_run_id')::bigint=g.grading_run_id WHERE j.kind='grade' AND g.experiment_id=%s",
        (exp,),
    ).fetchone() == (1,)
    assert conn.execute(
        "SELECT count(*),max(attempts) FROM sa_jobs WHERE kind='run_trial' AND (payload->>'trial_id')::bigint IN (SELECT trial_id FROM sa_trials WHERE experiment_id=%s) AND status='done'",
        (exp,),
    ).fetchone() == (100, 2)
    print(
        f"seed={seed}: finished=100, transient={len(failures)}, replies/ledger=200/200, cost=26.4/26.4, spans=300, grade=1, duplicate=0, sec={time.monotonic() - started:.2f}"
    )
