"""① plan-proposal 본체 common.proposal.propose: settings 기본값 + ③ sample_size + ② 문항 고르기, as_of 로 같은 제안."""

import pathlib
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from test_eng_worker import engine_db as engine_db
from test_eng_worker import experiment as experiment

from slotagent.api import eng_plan_proposal
from slotagent.api.eng_app import create_app
from slotagent.common import contracts, proposal
from slotagent.common.checks import CheckError
from slotagent.packs.select import select_tasks

SEEDS = pathlib.Path(__file__).resolve().parents[1] / "db" / "seeds" / "0001_settings_defaults.sql"
OLD = datetime(2000, 1, 1, tzinfo=UTC)
CALLS = []


def fake_sample_size(margin_pp, alpha, power, p_base):
    CALLS.append((margin_pp, alpha, power, p_base))
    return {"n_templates": 1}


@pytest.fixture
def setup(experiment, monkeypatch):
    """시드 기본값을 오래전 시각으로 넣어 as_of 가 과거여도 읽히게 함 (모듈마다 DB 가 따로라 다른 시험에 안 섞임)."""
    conn, ids = experiment
    if conn.execute("SELECT count(*) FROM sa_settings WHERE key='power'").fetchone()[0] == 0:
        # settings 는 추가만이라 시드 SQL 을 임시 표에 넣었다가 valid_from 만 바꿔 옮김
        conn.execute("CREATE TEMP TABLE seed_settings (scope text, scope_ref text, key text, value jsonb, note text)")
        for seed in (SEEDS, SEEDS.with_name("0003_settings_proposal.sql")):
            conn.execute(seed.read_text(encoding="utf-8").replace("INSERT INTO sa_settings", "INSERT INTO seed_settings"))
        conn.execute("""INSERT INTO sa_settings(scope,scope_ref,key,value,note,valid_from)
                        SELECT scope,scope_ref,key,value,note,%s FROM seed_settings""", (OLD,))
        conn.execute("DROP TABLE seed_settings")
    row = conn.execute("SELECT agent_version_id, slot_id, pack_version_id FROM sa_experiments WHERE experiment_id=%s",
                       (ids["experiment"],)).fetchone()
    cands = [r[0] for r in conn.execute(
        "SELECT candidate_id FROM sa_experiment_candidates WHERE experiment_id=%s ORDER BY candidate_id", (ids["experiment"],))]
    task = conn.execute("SELECT task_id FROM sa_trials WHERE experiment_id=%s LIMIT 1", (ids["experiment"],)).fetchone()[0]
    req = {"agent_version_id": row[0], "slot_id": row[1], "pack_version_id": row[2], "candidate_ids": cands}
    monkeypatch.setattr("slotagent.stats.analyze.sample_size", fake_sample_size)
    CALLS.clear()
    return conn, req, task


def test_proposal_from_settings_and_selection(setup):
    conn, req, task = setup
    out = contracts.validate("api", eng_plan_proposal.handle(conn, req), part="plan_proposal_response")
    assert CALLS == [(5, 0.05, 0.8, 0.7)]
    assert not out.get("warnings")
    assert out["plan"] == {"schema_version": 1, "tasks": [{"task_id": task, "batch_no": 1}]}
    assert (out["reps"], out["n_templates"], out["n_tasks"], out["trials"]) == (3, 1, 1, 6)
    p = out["prereg"]
    assert (p["margin_pp"], p["alpha"], p["regression_limit"], p["max_env_retries"], p["test"]) == (5, 0.05, 0.05, 1, "ni_then_sup")
    assert p["outcome_rules"]["out_of_scope"] == "fail" and "env_mcp_server_down" in p["outcome_rules"]["env_error_reasons"]
    contracts.validate("prereg", p)
    assert proposal.propose(conn, {**req, "reps": 2}, sample_size=fake_sample_size)["trials"] == 4


def test_same_as_of_gives_same_proposal_and_verify_is_unedited(setup):
    conn, req, task = setup
    first = proposal.propose(conn, req)
    as_of = datetime.fromisoformat(first["as_of"])
    # 제안 뒤에 생긴 노출·기본값 변경은 그 시각의 제안을 바꾸지 않음
    user = conn.execute("SELECT user_id FROM sa_users LIMIT 1").fetchone()[0]
    conn.execute("INSERT INTO sa_task_exposures(task_id,seen_by,reason,seen_at) VALUES (%s,%s,'검사',%s)",
                 (task, user, as_of + timedelta(seconds=1)))
    conn.execute("INSERT INTO sa_settings(scope,scope_ref,key,value,valid_from) VALUES ('global','','ni_margin_pp',%s,%s)",
                 (Jsonb(3), as_of + timedelta(seconds=1)))
    again = proposal.propose(conn, req, as_of=as_of)
    assert again == first
    saved = proposal.proposed_values(req, first)
    rec = proposal.verify(conn, {"request": req, "as_of": first["as_of"]}, saved, now=as_of + timedelta(minutes=1))
    assert (rec["edited"], rec["edited_fields"]) == (False, [])
    # 지금 시각이면 노출된 유형은 빠지고, 남은 새 유형이 없어 제안할 수 없음
    with pytest.raises(CheckError) as e:
        proposal.propose(conn, req, as_of=as_of + timedelta(seconds=2))
    assert e.value.code == "invalid_plan"


@pytest.mark.parametrize(
    "change,code",
    [
        ({"pack_version_id": 2**62}, "not_found"),
        ({"slot_id": 2**62}, "not_found"),
        ({"agent_version_id": 2**62}, "not_found"),
        ({"candidate_ids": [2**62]}, "wrong_slot"),
        ({"split": "dev"}, "invalid_plan"),
    ],
)
def test_refused_requests(setup, change, code):
    conn, req, _ = setup
    with pytest.raises(CheckError) as e:
        proposal.propose(conn, {**req, **change}, as_of=datetime.now(UTC))
    assert e.value.code == code


def test_missing_setting(setup):
    conn, req, _ = setup
    with pytest.raises(CheckError) as e:
        proposal.propose(conn, req, as_of=OLD - timedelta(days=1))
    assert e.value.code == "invalid_plan" and "settings" in e.value.errors[0]


def test_sample_size_other_error_propagates(setup):
    conn, req, _ = setup
    failure = RuntimeError("sample size calculation failed")

    def broken_sample_size(*args):
        raise failure

    with pytest.raises(RuntimeError) as exc:
        proposal.propose(conn, req, sample_size=broken_sample_size)
    assert exc.value is failure


@pytest.mark.parametrize(("fresh_count", "expected"), [(16, 15), (14, 14), (0, 0)])
def test_pilot_template_limit(setup, fresh_count, expected):
    conn, req, _ = setup
    source_pack = req["pack_version_id"]
    pack_id = conn.execute(
        """INSERT INTO sa_pack_versions (domain_code, pack_code, version)
           SELECT domain_code, pack_code, 'pilot-limit' FROM sa_pack_versions WHERE pack_version_id = %s
           RETURNING pack_version_id""",
        (source_pack,),
    ).fetchone()[0]
    conn.execute(
        """INSERT INTO sa_data_snapshots (pack_version_id, source_kind, location, content_hash, frozen_at)
           VALUES (%s, 'repo', 'fake://pilot-limit', 'frozen', now())""",
        (pack_id,),
    )
    conn.execute(
        """WITH templates AS (
               INSERT INTO sa_templates (pack_version_id, code, question_pattern, split)
               SELECT %s, 'T' || n, 'Pilot question', 'held' FROM generate_series(0, %s) AS n
               RETURNING template_id, code
           )
           INSERT INTO sa_tasks (template_id, code, prompt, seed)
           SELECT template_id, code, 'Pilot question', 1 FROM templates
           UNION ALL SELECT template_id, 'T0-sibling', 'Pilot question', 2 FROM templates WHERE code='T0'""",
        (pack_id, fresh_count),
    )
    conn.execute(
        """WITH template AS (
               INSERT INTO sa_templates (pack_version_id, code, question_pattern, split)
               VALUES (%s, 'DEV', 'Development question', 'dev') RETURNING template_id
           )
           INSERT INTO sa_tasks (template_id, code, prompt, seed)
           SELECT template_id, 'DEV-1', 'Development question', 1 FROM template""",
        (pack_id,),
    )
    conn.execute(
        "UPDATE sa_pack_versions SET status='locked', locked_at=now() WHERE pack_version_id=%s",
        (pack_id,),
    )
    conn.execute(
        """INSERT INTO sa_task_exposures (task_id, seen_by, reason, seen_at)
           SELECT k.task_id, (SELECT min(user_id) FROM sa_users), 'pilot limit test', %s
           FROM sa_tasks k JOIN sa_templates t USING (template_id)
           WHERE t.pack_version_id=%s AND k.code='T0'""",
        (OLD, pack_id),
    )

    def unavailable_sample_size(*args):
        raise NotImplementedError

    request = {**req, "pack_version_id": pack_id, "split": "dev"}
    if expected == 0:
        with pytest.raises(CheckError) as exc:
            proposal.propose(conn, request, sample_size=unavailable_sample_size)
        assert exc.value.code == "invalid_plan"
        return

    result = proposal.propose(conn, request, sample_size=unavailable_sample_size)
    assert (result["n_templates"], result["n_tasks"]) == (expected, expected)
    assert len(result["plan"]["tasks"]) == expected
    selected_ids = [task["task_id"] for task in result["plan"]["tasks"]]
    assert conn.execute(
        """SELECT count(*) FROM sa_tasks k JOIN sa_templates t USING (template_id)
           WHERE task_id = ANY(%s) AND (t.code = 'T0' OR t.split <> 'held')""",
        (selected_ids,),
    ).fetchone()[0] == 0
    assert result["warnings"]
    as_of = datetime.fromisoformat(result["as_of"])
    assert proposal.propose(conn, request, as_of=as_of, sample_size=unavailable_sample_size) == result
    options = {"as_of": as_of, "seed": "pilot-replay", "looks": 2}
    plan = select_tasks(conn, pack_id, 2, **options)
    assert [task["batch_no"] for task in plan] == [1, 2]
    assert select_tasks(conn, pack_id, 2, **options) == plan


def test_http_route(setup, engine_db, monkeypatch):
    _, req, task = setup
    client = TestClient(create_app(lambda: psycopg.connect(engine_db, autocommit=True)), raise_server_exceptions=False)
    url = "/api/experiments/plan-proposal"
    r = client.post(url, json=req)
    assert r.status_code == 200, r.text
    out = contracts.validate("api", r.json(), part="plan_proposal_response")
    assert out["plan"]["tasks"] == [{"task_id": task, "batch_no": 1}]
    # 계약 밖 칸·JSON 객체가 아닌 본문은 invalid_spec
    for bad in ({**req, "extra": 1}, [req]):
        r = client.post(url, json=bad)
        assert (r.status_code, r.json()["code"]) == (422, "invalid_spec")
    def unavailable_sample_size(*args):
        raise NotImplementedError

    monkeypatch.setattr("slotagent.stats.analyze.sample_size", unavailable_sample_size)
    r = client.post(url, json=req)
    assert r.status_code == 200, r.text
    pilot = contracts.validate("api", r.json(), part="plan_proposal_response")
    assert pilot["warnings"]
    assert pilot["plan"]["tasks"] == [{"task_id": task, "batch_no": 1}]
    assert (pilot["reps"], pilot["n_templates"], pilot["n_tasks"], pilot["trials"]) == (3, 1, 1, 6)
