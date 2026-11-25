"""① 실험 API 독립 감사. 일회용 DB와 로컬 ASGI·HTTP 요청만 사용합니다."""

import socket
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Thread

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from test_eng_api import draft as draft
from test_eng_worker import dependencies
from test_eng_worker import engine_db as engine_db
from test_eng_worker import experiment as experiment

from slotagent.api import eng_experiments
from slotagent.api.eng_app import create_app
from slotagent.common import contracts
from slotagent.common.checks import CheckError
from slotagent.engine import lock, worker
from slotagent.engine.loop import RunCancelled
from slotagent.workers import eng_main


@pytest.fixture(autouse=True)
def cleanup_api_jobs(engine_db):
    yield
    with psycopg.connect(engine_db, autocommit=True) as conn:
        conn.execute(
            "UPDATE sa_jobs SET status='cancelled',leased_by=NULL,lease_until=NULL WHERE status IN ('queued','leased')"
        )


@pytest.fixture
def client(engine_db):
    return TestClient(create_app(lambda: psycopg.connect(engine_db, autocommit=True)), raise_server_exceptions=False)


def url(exp, action):
    return f"/api/experiments/{exp}/{action}"


def validate_response(response, part="status_response"):
    assert response.status_code == 200, response.text
    return contracts.validate("api", response.json(), part=part)


def error_response(response, status=None):
    if status is not None:
        assert response.status_code == status, response.text
    return contracts.validate("api", response.json(), part="error")


def counts(conn, exp):
    return (
        conn.execute("SELECT count(*) FROM sa_trials WHERE experiment_id=%s", (exp,)).fetchone()[0],
        conn.execute(
            "SELECT count(*) FROM sa_jobs j JOIN sa_trials t ON t.trial_id=(j.payload->>'trial_id')::bigint WHERE j.kind='run_trial' AND t.experiment_id=%s",
            (exp,),
        ).fetchone()[0],
    )


@pytest.mark.parametrize("actions", [("run", "run"), ("run", "stop")])
def test_api_races(client, draft, actions):
    conn, exp = draft
    start = Barrier(2)

    def request(action):
        start.wait(timeout=5)
        return client.post(url(exp, action))

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(request, action) for action in actions]
        responses = [f.result(timeout=15) for f in futures]
    assert all(r.status_code in {200, 409} for r in responses), [r.text for r in responses]
    assert any(r.status_code == 200 for r in responses)
    assert counts(conn, exp) == (2, 2)
    body = validate_response(client.get(url(exp, "status")))
    assert body["status"] in {"running", "stopped"}
    if body["status"] == "stopped":
        assert body["trials"]["cancelled"] == 2


@pytest.mark.parametrize("first", ["stop", "save"])
def test_stop_and_final_save_order(client, experiment, monkeypatch, first):
    conn, data = experiment
    trial, exp = data["trials"][0], data["experiment"]
    original, seen = worker._save_result, []

    def interleave(connection, *a, **kw):
        if first == "stop":
            seen.append(client.post(url(exp, "stop")))
        value = original(connection, *a, **kw)
        if first == "save":
            seen.append(client.post(url(exp, "stop")))
        return value

    monkeypatch.setattr(worker, "_save_result", interleave)
    if first == "stop":
        with pytest.raises(RunCancelled):
            worker.run_trial(conn, trial, deps=dependencies())
    else:
        worker.run_trial(conn, trial, deps=dependencies())
    body = validate_response(client.get(url(exp, "status")))
    assert seen[0].status_code == 200 and body["status"] == "stopped"
    assert body["cost_krw"] > 0
    assert body["trials"]["finished"] == (first == "save")
    assert body["trials"]["cancelled"] == (2 if first == "stop" else 1)


def test_stop_and_leased_worker_final_save_race(client, draft, engine_db, monkeypatch):
    conn, exp = draft
    validate_response(client.post(url(exp, "run")), "run_response")
    ready = Barrier(2)
    original = worker._save_result

    def saving(*a, **kw):
        ready.wait(timeout=5)
        return original(*a, **kw)

    def execute():
        try:
            return eng_main.run_once(
                lambda: psycopg.connect(engine_db, autocommit=True),
                "save-race",
                deps=dependencies(),
                heartbeat_sec=0.05,
            )
        except RunCancelled:
            return False

    def stop():
        ready.wait(timeout=5)
        return client.post(url(exp, "stop"))

    monkeypatch.setattr(worker, "_save_result", saving)
    with ThreadPoolExecutor(2) as pool:
        work, stopping = pool.submit(execute), pool.submit(stop)
        work.result(timeout=15)
        assert stopping.result(timeout=15).status_code == 200
    body = validate_response(client.get(url(exp, "status")))
    assert body["status"] == "stopped" and body["trials"]["running"] == 0
    assert body["trials"]["finished"] + body["trials"]["cancelled"] == 2
    assert body["cost_krw"] == pytest.approx(0.264)


@pytest.mark.parametrize("state", ["draft", "locked", "running", "done", "stopped", "failed"])
def test_status_all_states_contract(client, draft, state):
    conn, exp = draft
    if state != "draft":
        validate_response(client.post(url(exp, "run")), "run_response")
        with conn.transaction():
            conn.execute("SET LOCAL session_replication_role=replica")
            conn.execute(
                "UPDATE sa_experiments SET status=%s,stop_reason=%s WHERE experiment_id=%s",
                (state, "user" if state == "stopped" else "job_failed" if state == "failed" else None, exp),
            )
    response = client.get(url(exp, "status"))
    assert validate_response(response)["status"] == state


@pytest.mark.parametrize("tasks", [None, {}, "wrong", 1, False, []])
def test_draft_bad_plan_returns_domain_error(client, draft, tasks):
    conn, exp = draft
    plan = conn.execute("SELECT plan FROM sa_experiments WHERE experiment_id=%s", (exp,)).fetchone()[0]
    if tasks is None:
        plan.pop("tasks", None)
    else:
        plan["tasks"] = tasks
    conn.execute("UPDATE sa_experiments SET plan=%s WHERE experiment_id=%s", (Jsonb(plan), exp))
    result = client.get(url(exp, "status"))
    assert error_response(result, 422)["code"] == "invalid_plan"
    assert counts(conn, exp) == (0, 0)


def test_draft_counts_match_lock(client, draft):
    conn, exp = draft
    conn.execute("UPDATE sa_experiments SET reps=3 WHERE experiment_id=%s", (exp,))
    pending = validate_response(client.get(url(exp, "status")))["trials"]["pending"]
    assert pending == validate_response(client.post(url(exp, "run")), "run_response")["trials_total"] == 6


@pytest.mark.parametrize("value", ["0", "-1", str(2**63), str(2**63 - 1), "1.5", "abc"])
@pytest.mark.parametrize("action", ["status", "run", "stop"])
def test_boundary_ids(client, value, action):
    method = client.get if action == "status" else client.post
    response = method(url(value, action))
    assert error_response(response, 404 if value == str(2**63 - 1) else 422)["code"] in {"not_found", "invalid_spec"}


@pytest.mark.parametrize(
    "raw,content_type",
    [("broken", "application/json"), ('{"x":1}', "application/json"), ("x" * 2_000_000, "text/plain")],
)
def test_run_body_ignored_observation(client, draft, raw, content_type):
    conn, exp = draft
    response = client.post(url(exp, "run"), content=raw, headers={"Content-Type": content_type})
    validate_response(response, "run_response")
    assert counts(conn, exp) == (2, 2)


@pytest.mark.parametrize("method", ["head", "options", "put", "delete"])
def test_methods_are_safe(client, draft, method):
    conn, exp = draft
    response = getattr(client, method)(url(exp, "run"))
    assert response.status_code == 405
    if method != "head":
        error_response(response)
    else:
        assert response.content == b""
    assert counts(conn, exp) == (0, 0)


def test_database_hint_does_not_leak_message(engine_db):
    secret = "password=SECRET_AUDIT host=PRIVATE_HOST D:/private/config.env"
    with psycopg.connect(engine_db, autocommit=True) as conn:
        try:
            conn.execute(
                "DO $$ BEGIN RAISE EXCEPTION 'password=SECRET_AUDIT host=PRIVATE_HOST D:/private/config.env' USING HINT='not_lockable'; END $$"
            )
        except psycopg.Error as captured:
            db_error = captured

    def broken():
        raise db_error

    response = TestClient(create_app(broken), raise_server_exceptions=False).get(url(1, "status"))
    assert error_response(response, 409)["code"] == "not_lockable"
    assert secret not in response.text


def test_internal_errors_do_not_leak_to_response_or_app_log(caplog):
    def broken():
        raise psycopg.OperationalError("password=SECRET_AUDIT D:/private/config.env")

    response = TestClient(create_app(broken), raise_server_exceptions=False).post(url(1, "run"))
    error_response(response, 503)
    assert "SECRET_AUDIT" not in response.text + caplog.text


def test_unexpected_error_does_not_leak_in_real_server_log(caplog):
    import uvicorn

    def broken():
        raise RuntimeError("SECRET_AUDIT D:/private/config.env")

    app = create_app(broken)
    server = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False, lifespan="off"))
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    thread = Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    try:
        for _ in range(300):
            if server.started:
                break
            Event().wait(0.01)
        assert server.started
        response = httpx.get(f"http://127.0.0.1:{port}/api/experiments/1/status", timeout=5, trust_env=False)
        assert response.status_code == 500 and "SECRET_AUDIT" not in response.text
    finally:
        server.should_exit = True
        thread.join(5)
        listener.close()
    assert not thread.is_alive()
    assert "SECRET_AUDIT" not in caplog.text


def test_no_candidates_is_domain_error(client, draft):
    conn, exp = draft
    conn.execute("DELETE FROM sa_experiment_candidates WHERE experiment_id=%s", (exp,))
    assert error_response(client.get(url(exp, "status")), 422)["code"] == "invalid_plan"
    assert error_response(client.post(url(exp, "run")), 409)["code"] == "not_lockable"
    assert counts(conn, exp) == (0, 0)


@pytest.mark.parametrize("raw", ["null", "[]", '{"reason":"x"}', "[" * 100000])
def test_invalid_stop_body_preserves_state(client, draft, raw):
    conn, exp = draft
    validate_response(client.post(url(exp, "run")), "run_response")
    assert error_response(client.post(url(exp, "stop"), content=raw), 422)["code"] == "invalid_spec"
    assert validate_response(client.get(url(exp, "status")))["status"] == "running"
    assert counts(conn, exp) == (2, 2)


@pytest.mark.parametrize("content_type", ["text/plain", "application/x-www-form-urlencoded"])
def test_stop_json_with_wrong_content_type_observation(client, draft, content_type):
    conn, exp = draft
    validate_response(client.post(url(exp, "run")), "run_response")
    assert (
        validate_response(client.post(url(exp, "stop"), content="{}", headers={"Content-Type": content_type}))["status"]
        == "stopped"
    )


def test_stop_503_after_commit_retry_is_safe(client, experiment, monkeypatch):
    conn, data = experiment
    exp = data["experiment"]
    original = eng_experiments.status
    with monkeypatch.context() as patch:
        patch.setattr(
            eng_experiments, "status", lambda *_: (_ for _ in ()).throw(psycopg.OperationalError("readback lost"))
        )
        error_response(client.post(url(exp, "stop")), 503)
    assert eng_experiments.status is original
    assert conn.execute("SELECT status FROM sa_experiments WHERE experiment_id=%s", (exp,)).fetchone() == ("stopped",)
    assert validate_response(client.post(url(exp, "stop")))["trials"]["cancelled"] == 2


def test_run_503_after_commit_retry_is_safe(engine_db, draft):
    conn, exp = draft
    failed = []

    class Connection:
        def __enter__(self):
            self.connection = psycopg.connect(engine_db, autocommit=True)
            return self.connection

        def __exit__(self, *args):
            self.connection.close()
            if not failed:
                failed.append(True)
                raise psycopg.OperationalError("commit acknowledgement lost")

    client = TestClient(create_app(Connection), raise_server_exceptions=False)
    error_response(client.post(url(exp, "run")), 503)
    assert counts(conn, exp) == (2, 2)
    validate_response(client.post(url(exp, "run")), "run_response")
    assert counts(conn, exp) == (2, 2)


def test_lock_checkerror_retains_valueerror_compatibility(experiment):
    conn, _ = experiment
    with pytest.raises(ValueError) as caught:
        lock.lock_and_enqueue(conn, 2**63 - 1)
    assert isinstance(caught.value, CheckError) and caught.value.code == "not_found"


@pytest.mark.parametrize("action", ["run", "stop"])
def test_cross_origin_simple_post_changes_state_observation(client, draft, action):
    conn, exp = draft
    if action == "stop":
        validate_response(client.post(url(exp, "run")), "run_response")
    response = client.post(
        url(exp, action),
        headers={
            "Origin": "https://unrelated.example",
            "Sec-Fetch-Site": "cross-site",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    assert response.status_code == 200
    assert conn.execute("SELECT status FROM sa_experiments WHERE experiment_id=%s", (exp,)).fetchone()[0] == (
        "running" if action == "run" else "stopped"
    )
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("mutation", ["lock", "stop", "redact"])
def test_existing_api_tests_detect_memory_mutations(experiment, draft, engine_db, monkeypatch, mutation):
    import test_eng_api as existing

    original_lock, original_stop = eng_experiments.lock_and_enqueue, eng_experiments.advance.stop_experiment
    with monkeypatch.context() as patch:
        if mutation == "lock":
            patch.setattr(
                eng_experiments,
                "lock_and_enqueue",
                lambda conn, exp: {"experiment_id": exp, "status": "running", "trials_total": 2},
            )
        elif mutation == "stop":
            patch.setattr(eng_experiments.advance, "stop_experiment", lambda *_: 0)
        else:
            import slotagent.api.eng_app as app_module

            patch.setattr(app_module, "_database", lambda request, exc: app_module._error("internal", str(exc), 503))
        with pytest.raises(AssertionError):
            if mutation == "redact":
                existing.test_internal_errors_hide_details(psycopg.OperationalError("secret"), 503)
            else:
                client = TestClient(
                    create_app(lambda: psycopg.connect(engine_db, autocommit=True)), raise_server_exceptions=False
                )
                existing.test_draft_run_stop(client, draft)
    assert (
        eng_experiments.lock_and_enqueue is original_lock and eng_experiments.advance.stop_experiment is original_stop
    )
