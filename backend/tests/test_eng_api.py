"""① 실험 실행·중지·상태 API: HTTP 로 부르고 실제 임시 DB 를 확인합니다."""

import psycopg
import pytest
from fastapi.testclient import TestClient
from test_eng_pipeline import by_rules, prepare
from test_eng_worker import dependencies
from test_eng_worker import engine_db as engine_db
from test_eng_worker import experiment as experiment

from slotagent.api.eng_app import create_app
from slotagent.common import contracts
from slotagent.engine.worker import run_trial
from slotagent.grading.eng_pipeline import grade


@pytest.fixture
def client(engine_db):
    app = create_app(lambda: psycopg.connect(engine_db, autocommit=True))
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def draft(experiment):
    """이미 잠긴 픽스처를 복사해 초안 실험을 만듭니다."""
    conn, data = experiment
    source = data["experiment"]
    new = conn.execute(
        """INSERT INTO sa_experiments(kind,agent_version_id,slot_id,pack_version_id,reps,prereg,plan,budget_krw,created_by)
           SELECT kind,agent_version_id,slot_id,pack_version_id,reps,prereg,plan,budget_krw,created_by
           FROM sa_experiments WHERE experiment_id=%s RETURNING experiment_id""",
        (source,),
    ).fetchone()[0]
    conn.execute(
        """INSERT INTO sa_experiment_candidates(experiment_id,candidate_id,label,role,config_snapshot,config_hash,template_scope)
           SELECT %s,candidate_id,label,role,config_snapshot,config_hash,template_scope
           FROM sa_experiment_candidates WHERE experiment_id=%s""",
        (new, source),
    )
    return conn, new


def url(exp, action):
    return f"/api/experiments/{exp}/{action}"


def ok(response, part="status_response"):
    assert response.status_code == 200, response.text
    return contracts.validate("api", response.json(), part=part)


def refused(response, status, code):
    assert (response.status_code, response.json()["code"]) == (status, code), response.text
    contracts.validate("api", response.json(), part="error")


def run_jobs(conn, exp):
    return conn.execute(
        """SELECT count(*) FROM sa_jobs j JOIN sa_trials t ON t.trial_id=(j.payload->>'trial_id')::bigint
           WHERE j.kind='run_trial' AND t.experiment_id=%s""",
        (exp,),
    ).fetchone()[0]


def test_draft_run_stop(client, draft):
    conn, exp = draft
    before = ok(client.get(url(exp, "status")))
    assert (before["status"], before["trials_total"], before["trials"]["pending"]) == ("draft", 2, 2)
    first = ok(client.post(url(exp, "run")), "run_response")
    assert first == {"experiment_id": exp, "status": "running", "trials_total": 2}
    assert ok(client.post(url(exp, "run")), "run_response") == first and run_jobs(conn, exp) == 2
    stopped = ok(client.post(url(exp, "stop")))
    assert (stopped["status"], stopped["stop_reason"], stopped["trials"]["cancelled"]) == ("stopped", "user", 2)
    assert ok(client.post(url(exp, "stop"), json={})) == stopped
    refused(client.post(url(exp, "run")), 409, "experiment_locked")
    left = conn.execute(
        """SELECT DISTINCT j.status FROM sa_jobs j JOIN sa_trials t ON t.trial_id=(j.payload->>'trial_id')::bigint
           WHERE j.kind='run_trial' AND t.experiment_id=%s""",
        (exp,),
    ).fetchall()
    assert left == [("cancelled",)]


def test_status_follows_run_and_grading(client, experiment):
    conn, data, run_id = prepare(experiment)
    body = ok(client.get(url(data["experiment"], "status")))
    assert body["trials"]["finished"] == body["trials_total"] == 2 and body["cost_krw"] == pytest.approx(0.528)
    assert (body["budget_krw"], body["latest_grading_run_id"], body["latest_analysis_id"]) == (100, run_id, None)
    grade(conn, run_id, classify=by_rules)
    assert ok(client.get(url(data["experiment"], "status")))["latest_grading_run_id"] == run_id


def test_env_rerun_counts_last_run_only(client, experiment):
    from slotagent.engine.loop import ToolEnvironmentError

    def down(*a):
        raise ToolEnvironmentError()

    conn, data = experiment
    trial = data["trials"][0]
    run_trial(conn, trial, deps=dependencies(down))
    conn.execute(
        """INSERT INTO sa_trials(experiment_id,experiment_candidate_id,task_id,rep,run_no,batch_no)
           SELECT experiment_id,experiment_candidate_id,task_id,rep,2,batch_no FROM sa_trials WHERE trial_id=%s""",
        (trial,),
    )
    body = ok(client.get(url(data["experiment"], "status")))
    assert (body["trials_total"], body["env_reruns"]) == (2, 1)
    assert body["trials"] == {"pending": 2, "running": 0, "finished": 0, "error": 0, "cancelled": 0}


def test_stop_keeps_finished_trials(client, experiment):
    conn, data = experiment
    run_trial(conn, data["trials"][0], deps=dependencies())
    body = ok(client.post(url(data["experiment"], "stop")))
    assert (body["trials"]["finished"], body["trials"]["cancelled"]) == (1, 1)


@pytest.mark.parametrize("state", ["done", "failed"])
def test_ended_experiment_is_not_changed(client, experiment, state):
    conn, data = experiment
    conn.execute("SET session_replication_role = replica")
    conn.execute("UPDATE sa_experiments SET status=%s WHERE experiment_id=%s", (state, data["experiment"]))
    conn.execute("SET session_replication_role = DEFAULT")
    for action in ("stop", "run"):
        refused(client.post(url(data["experiment"], action)), 409, "experiment_locked")
    assert conn.execute(
        "SELECT count(*) FROM sa_trials WHERE experiment_id=%s AND status='cancelled'", (data["experiment"],)
    ).fetchone() == (0,)


def test_draft_cannot_be_stopped(client, draft):
    refused(client.post(url(draft[1], "stop")), 409, "not_lockable")
    assert ok(client.get(url(draft[1], "status")))["status"] == "draft"


def test_draft_without_candidates(client, draft):
    conn, exp = draft
    conn.execute("DELETE FROM sa_experiment_candidates WHERE experiment_id=%s", (exp,))
    refused(client.get(url(exp, "status")), 422, "invalid_plan")
    refused(client.post(url(exp, "run")), 409, "not_lockable")
    assert run_jobs(conn, exp) == 0


@pytest.mark.parametrize("method,action", [("post", "run"), ("post", "stop"), ("get", "status")])
def test_missing_and_bad_ids(client, method, action):
    refused(getattr(client, method)(url(10**12, action)), 404, "not_found")
    for bad in ("0", "-1", "abc", str(2**63)):
        refused(getattr(client, method)(url(bad, action)), 422, "invalid_spec")


@pytest.mark.parametrize("raw", ["[]", '{"reason":"x"}', "not json", "null", "[" * 100000])
def test_stop_body_is_rejected_without_stopping(client, experiment, raw):
    exp = experiment[1]["experiment"]
    refused(client.post(url(exp, "stop"), content=raw), 422, "invalid_spec")
    assert ok(client.get(url(exp, "status")))["status"] in {"locked", "running"}


def test_unknown_path_and_method(client):
    refused(client.get("/api/nothing"), 404, "not_found")
    refused(client.get(url(1, "run")), 405, "invalid_spec")


def test_locked_row_returns_503(client, experiment, engine_db):
    exp = experiment[1]["experiment"]
    with psycopg.connect(engine_db) as other:
        other.execute("SELECT 1 FROM sa_experiments WHERE experiment_id=%s FOR UPDATE", (exp,))
        refused(client.post(url(exp, "stop")), 503, "internal")
    assert ok(client.get(url(exp, "status")))["status"] in {"locked", "running"}


@pytest.mark.parametrize(
    "error,status",
    [
        (psycopg.OperationalError("password=secret"), 503),
        (psycopg.errors.CheckViolation("secret"), 500),
        (RuntimeError("secret"), 500),
        (ValueError("secret"), 500),
        (NotImplementedError("secret"), 501),
    ],
)
def test_internal_errors_hide_details(error, status):
    def broken():
        raise error

    response = TestClient(create_app(broken), raise_server_exceptions=False).get(url(1, "status"))
    refused(response, status, "internal")
    assert "secret" not in response.text


def test_missing_database_setting(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    refused(TestClient(create_app(), raise_server_exceptions=False).get(url(1, "status")), 503, "internal")
