"""④ Agent 등록 입력 검증 테스트."""

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import psycopg
import pytest
from conftest import ROOT, load
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from slotagent.api.eng_app import create_app
from slotagent.common import checks, contracts, proposal
from slotagent.common.snapshot import build_config_snapshot
from slotagent.intake.service import add_candidate, create_experiment_draft, register_agent, register_candidate


@pytest.fixture
def agent_request():
    """읽기·쓰기 도구를 포함한 Agent 등록 요청 데이터."""
    req = load("api_and_jobs.json")["api.register_agent_request"]

    av = load("agent_version.json")

    req["version"]["spec"] = av["spec"]
    req["version"]["connection_type"] = av["connection_type"]
    req["version"]["control_level"] = av["control_level"]

    # 정상 요청인지 먼저 확인
    contracts.validate(
        "api",
        req,
        part="register_agent_request",
    )

    return req


@pytest.fixture
def conn():
    """실제 DB 대신 DB 접근 여부를 확인하는 객체."""
    return Mock()


# AG-01: 필수 항목 누락
def test_register_agent_missing_name(conn, agent_request):
    del agent_request["name"]

    with pytest.raises(contracts.ContractError):
        register_agent(conn, agent_request, owner_id=1)

    conn.transaction.assert_not_called()
    conn.execute.assert_not_called()


# AG-02: temperature 범위 초과
def test_register_agent_invalid_temperature(conn, agent_request):
    agent_request["version"]["temperature"] = 3

    with pytest.raises(contracts.ContractError):
        register_agent(conn, agent_request, owner_id=1)

    conn.transaction.assert_not_called()
    conn.execute.assert_not_called()


# AG-03: 예약 도구 이름 사용
def test_register_agent_reserved_tool(conn, agent_request):
    tools = agent_request["version"]["spec"]["tools"]
    tools[0]["name"] = "get_work_state"

    with pytest.raises(checks.CheckError) as exc:
        register_agent(conn, agent_request, owner_id=1)

    assert exc.value.code == "invalid_spec"
    assert "get_work_state" in str(exc.value)

    conn.transaction.assert_not_called()
    conn.execute.assert_not_called()


# AG-04: 쓰기 도구 capabilities 누락
def test_register_agent_missing_capabilities(conn, agent_request):
    tools = agent_request["version"]["spec"]["tools"]
    write_tool = next(t for t in tools if t["access"] == "write")
    write_tool["capabilities"] = []

    with pytest.raises(checks.CheckError) as exc:
        register_agent(conn, agent_request, owner_id=1)

    assert exc.value.code == "invalid_spec"
    assert "capabilities" in str(exc.value)

    conn.transaction.assert_not_called()
    conn.execute.assert_not_called()


# AG-05: 연결 방식에 맞지 않는 write_mode
def test_register_agent_invalid_write_mode(conn, agent_request):
    version = agent_request["version"]
    version["connection_type"] = "spec_upload"

    write_tool = next(t for t in version["spec"]["tools"] if t["access"] == "write")
    write_tool["write_mode"] = "test_space"

    with pytest.raises(checks.CheckError) as exc:
        register_agent(conn, agent_request, owner_id=1)

    assert exc.value.code == "invalid_spec"

    conn.transaction.assert_not_called()
    conn.execute.assert_not_called()


# AG-06: API 연결에서 C2 사용
def test_register_agent_api_c2(conn, agent_request):
    version = agent_request["version"]
    version["connection_type"] = "api"
    version["control_level"] = "C2"

    for tool in version["spec"]["tools"]:
        if tool["access"] == "write":
            tool["write_mode"] = "dry_run"

    with pytest.raises(checks.CheckError) as exc:
        register_agent(conn, agent_request, owner_id=1)

    assert exc.value.code == "invalid_spec"
    assert "C2" in str(exc.value)

    conn.transaction.assert_not_called()
    conn.execute.assert_not_called()


@pytest.fixture
def agent_db_context(pg):
    """Agent 등록 테스트용 DB 환경."""
    with psycopg.connect(pg) as db_conn:
        with db_conn.transaction(force_rollback=True):
            # 1. 테스트 사용자 생성
            user_id = db_conn.execute(
                """
                INSERT INTO sa_users(email, name)
                VALUES (
                    'agent-test@example.test',
                    'Agent 테스트 사용자'
                )
                RETURNING user_id
                """
            ).fetchone()[0]

            # 2. 테스트 도메인 생성
            db_conn.execute(
                """
                INSERT INTO sa_domains(
                    domain_code, name, status
                )
                VALUES ('it_ops', 'IT 운영', 'active')
                ON CONFLICT (domain_code) DO NOTHING
                """
            )

            yield db_conn, user_id


def test_registered_agent_can_create_experiment_draft(agent_db_context, agent_request, monkeypatch):
    conn, user_id = agent_db_context
    agent = register_agent(conn, agent_request, user_id)
    slot = next(slot for slot in agent["slots"] if slot["comparable"])
    candidate_request = load("api_and_jobs.json")["api.register_candidate_request"]
    candidate_request["label"] = "B"
    candidate_id = register_candidate(conn, slot["slot_id"], candidate_request)
    pack_id = conn.execute(
        """INSERT INTO sa_pack_versions (domain_code, pack_code, version)
           VALUES ('it_ops', 'draft_test', '1') RETURNING pack_version_id"""
    ).fetchone()[0]
    template_id = conn.execute(
        """INSERT INTO sa_templates (pack_version_id, code, question_pattern)
           VALUES (%s, 'T1', 'List issues') RETURNING template_id""",
        (pack_id,),
    ).fetchone()[0]
    task_id = conn.execute(
        """INSERT INTO sa_tasks (template_id, code, prompt, seed)
           VALUES (%s, 'T1-1', 'List issues', 1) RETURNING task_id""",
        (template_id,),
    ).fetchone()[0]
    req = load("api_and_jobs.json")["api.create_experiment_request"]
    baseline_id = slot["baseline_candidate_id"]
    req.update(agent_version_id=agent["agent_version_id"], slot_id=slot["slot_id"], pack_version_id=pack_id,
               candidates=[baseline_id, candidate_id])
    req["plan"]["tasks"][0]["task_id"] = task_id
    req["proposal"]["request"].update(
        agent_version_id=req["agent_version_id"], slot_id=req["slot_id"],
        pack_version_id=pack_id, candidate_ids=req["candidates"],
    )
    req["proposal"]["as_of"] = datetime.now(UTC).isoformat()
    response = {"prereg": req["prereg"], "plan": req["plan"], "reps": req["reps"]}
    monkeypatch.setattr(proposal, "propose", Mock(return_value=response))

    experiment_id = create_experiment_draft(conn, req, user_id)

    status, plan = conn.execute(
        "SELECT status, plan FROM sa_experiments WHERE experiment_id = %s", (experiment_id,)
    ).fetchone()
    assert status == "draft"
    assert plan["tasks"] == req["plan"]["tasks"]
    assert not plan["proposal"]["edited"]
    assert "proposal" not in req["plan"]
    candidates = conn.execute(
        """SELECT candidate_id, role, config_snapshot, config_hash, template_scope
           FROM sa_experiment_candidates WHERE experiment_id = %s ORDER BY candidate_id""",
        (experiment_id,),
    ).fetchall()
    assert candidates == [
        (baseline_id, "baseline", *build_config_snapshot(conn, baseline_id), {"T1": "in_scope"}),
        (candidate_id, "candidate", *build_config_snapshot(conn, candidate_id), {"T1": "in_scope"}),
    ]

    conn.execute(
        "UPDATE sa_templates SET required_capabilities = %s WHERE template_id = %s",
        (Jsonb(["unknown"]), template_id),
    )
    with pytest.raises(checks.CheckError, match="범위 확인"):
        create_experiment_draft(conn, req, user_id)
    assert conn.execute("SELECT count(*) FROM sa_experiments WHERE created_by = %s", (user_id,)).fetchone()[0] == 1

    req["candidates"] = [baseline_id]
    req["proposal"]["request"]["candidate_ids"] = [baseline_id]
    conn.execute(
        "UPDATE sa_templates SET required_capabilities = %s WHERE template_id = %s",
        (Jsonb([]), template_id),
    )
    draft_id = create_experiment_draft(conn, req, user_id)
    experiment_candidate_id = add_candidate(conn, draft_id, candidate_id)
    assert conn.execute(
        """SELECT label, role, config_snapshot, config_hash, template_scope
           FROM sa_experiment_candidates WHERE experiment_candidate_id = %s AND experiment_id = %s""",
        (experiment_candidate_id, draft_id),
    ).fetchone() == ("B", "candidate", *build_config_snapshot(conn, candidate_id), {"T1": "in_scope"})
    tracking = conn.execute(
        "SELECT plan->'proposal' FROM sa_experiments WHERE experiment_id = %s", (draft_id,)
    ).fetchone()[0]
    assert tracking["edited"] and tracking["edited_fields"] == ["candidates"]

    with pytest.raises(checks.CheckError, match="이미 있습니다") as duplicate:
        add_candidate(conn, draft_id, candidate_id)
    assert duplicate.value.code == "label_taken"
    wrong_slot_id = next(item["baseline_candidate_id"] for item in agent["slots"] if item != slot)
    with pytest.raises(checks.CheckError) as wrong_slot:
        add_candidate(conn, draft_id, wrong_slot_id)
    assert wrong_slot.value.code == "wrong_slot"

    candidate_request["label"] = "C"
    third_id = register_candidate(conn, slot["slot_id"], candidate_request)
    conn.execute(
        "UPDATE sa_templates SET required_capabilities = %s WHERE template_id = %s",
        (Jsonb(["unknown"]), template_id),
    )
    with pytest.raises(checks.CheckError, match="범위 확인"):
        add_candidate(conn, draft_id, third_id)
    assert conn.execute(
        "SELECT count(*) FROM sa_experiment_candidates WHERE experiment_id = %s", (draft_id,)
    ).fetchone()[0] == 2


def test_plan_proposal_can_be_replayed_to_save_experiment(agent_db_context, agent_request):
    conn, user_id = agent_db_context
    conn.execute((ROOT / "backend/db/seeds/0001_settings_defaults.sql").read_text(encoding="utf-8"))
    agent = register_agent(conn, agent_request, user_id)
    slot = next(slot for slot in agent["slots"] if slot["comparable"])
    candidate_id = register_candidate(conn, slot["slot_id"], load("api_and_jobs.json")["api.register_candidate_request"])
    pack_id = conn.execute(
        """INSERT INTO sa_pack_versions (domain_code, pack_code, version)
           VALUES ('it_ops', 'proposal_test', '1') RETURNING pack_version_id"""
    ).fetchone()[0]
    task_ids = conn.execute(
        """WITH templates AS (
               INSERT INTO sa_templates (pack_version_id, code, question_pattern, split)
               VALUES (%s, 'T1', 'List issues', 'held'), (%s, 'T2', 'Read issue', 'held'),
                      (%s, 'T3', 'Search issues', 'dev')
               RETURNING template_id, code
           )
           INSERT INTO sa_tasks (template_id, code, prompt, seed)
           SELECT template_id, code, 'Read issues', 1 FROM templates RETURNING task_id, code""",
        (pack_id, pack_id, pack_id),
    ).fetchall()
    conn.execute(
        """INSERT INTO sa_data_snapshots (pack_version_id, source_kind, location, content_hash, frozen_at)
           VALUES (%s, 'fixed_response', 'proposal-test', 'frozen', now())""",
        (pack_id,),
    )
    conn.execute("UPDATE sa_pack_versions SET status = 'locked', locked_at = now() WHERE pack_version_id = %s", (pack_id,))
    req = {
        "agent_version_id": agent["agent_version_id"], "slot_id": slot["slot_id"], "pack_version_id": pack_id,
        "candidate_ids": [slot["baseline_candidate_id"], candidate_id], "reps": 2,
    }
    with TestClient(create_app(lambda: nullcontext(conn))) as client:
        response = client.post("/api/experiments/plan-proposal", json=req)
        assert client.post("/api/experiments/plan-proposal", json={}).status_code == 422
    assert response.status_code == 200, response.text
    result = response.json()
    held_tasks = {task_id for task_id, code in task_ids if code != "T3"}
    assert {task["task_id"] for task in result["plan"]["tasks"]} == held_tasks
    assert (result["n_templates"], result["n_tasks"], result["trials"]) == (2, 2, 8)
    assert result["warnings"]
    assert conn.execute("SELECT count(*) FROM sa_experiments WHERE created_by = %s", (user_id,)).fetchone()[0] == 0

    later = datetime.fromisoformat(result["as_of"]) + timedelta(seconds=1)
    conn.execute(
        "INSERT INTO sa_task_exposures (task_id, seen_by, seen_at, reason) VALUES (%s, %s, %s, 'review')",
        (min(held_tasks), user_id, later),
    )
    assert proposal.propose(conn, req, as_of=later)["n_tasks"] == 1
    experiment_id = create_experiment_draft(conn, {
        "agent_version_id": req["agent_version_id"], "slot_id": req["slot_id"], "pack_version_id": pack_id,
        "candidates": req["candidate_ids"], "reps": result["reps"], "prereg": result["prereg"],
        "plan": result["plan"], "proposal": {"request": req, "as_of": result["as_of"]},
    }, user_id)
    tracking = conn.execute(
        "SELECT plan->'proposal' FROM sa_experiments WHERE experiment_id = %s", (experiment_id,),
    ).fetchone()[0]
    assert tracking["edited_fields"] == []
    assert tracking["hash"] == proposal.proposal_hash(result["prereg"], result["plan"])


def test_register_agent_saves_slots_and_baselines(agent_db_context, agent_request):
    db_conn, user_id = agent_db_context
    response = register_agent(db_conn, agent_request, owner_id=user_id)
    contracts.validate("api", response, part="register_agent_response")
    assert len(response["slots"]) == 3
    assert {(slot["service"], slot["access"]): slot["comparable"] for slot in response["slots"]} == {
        ("github", "read"): True,
        ("github", "write"): False,
        ("slack", "write"): False,
    }
    version = db_conn.execute(
        "SELECT agent_id, questions_used FROM sa_agent_versions WHERE agent_version_id = %s",
        (response["agent_version_id"],),
    ).fetchone()
    assert version == (response["agent_id"], False)

    spec = agent_request["version"]["spec"]
    for slot in response["slots"]:
        saved = db_conn.execute(
            """
            SELECT s.service, s.access, s.comparable, s.not_comparable_reason,
                   c.label, c.component_kind, c.is_baseline, c.component_spec
            FROM sa_slots s JOIN sa_candidates c ON c.slot_id = s.slot_id
            WHERE s.agent_version_id = %s AND s.slot_id = %s AND c.candidate_id = %s
            """,
            (response["agent_version_id"], slot["slot_id"], slot["baseline_candidate_id"]),
        ).fetchone()
        assert saved == (
            slot["service"],
            slot["access"],
            slot["comparable"],
            slot["not_comparable_reason"],
            "A",
            "tool_bundle",
            True,
            checks.baseline_component(spec, slot),
        )


def test_register_agent_rollback(
    agent_db_context,
    agent_request,
    monkeypatch,
):
    db_conn, user_id = agent_db_context

    # 1. 등록 전 Agent 개수 확인
    before_agents = db_conn.execute("SELECT COUNT(*) FROM sa_agents").fetchone()[0]

    # 2. 등록 전 Agent Version 개수 확인
    before_versions = db_conn.execute("SELECT COUNT(*) FROM sa_agent_versions").fetchone()[0]

    before_slots = db_conn.execute("SELECT COUNT(*) FROM sa_slots").fetchone()[0]
    before_candidates = db_conn.execute("SELECT COUNT(*) FROM sa_candidates").fetchone()[0]

    baseline_component = checks.baseline_component

    def fail_on_write(spec, slot):
        if slot["access"] == "write":
            raise RuntimeError("baseline creation failed")
        return baseline_component(spec, slot)

    monkeypatch.setattr(checks, "baseline_component", fail_on_write)
    with pytest.raises(RuntimeError, match="baseline creation failed"):
        register_agent(
            db_conn,
            agent_request,
            owner_id=user_id,
        )

    # 4. 등록 실패 후 Agent 개수 확인
    after_agents = db_conn.execute("SELECT COUNT(*) FROM sa_agents").fetchone()[0]

    # 5. 등록 실패 후 Agent Version 개수 확인
    after_versions = db_conn.execute("SELECT COUNT(*) FROM sa_agent_versions").fetchone()[0]

    # 6. 내부 트랜잭션 롤백 확인
    assert before_agents == after_agents
    assert before_versions == after_versions
    assert db_conn.execute("SELECT COUNT(*) FROM sa_slots").fetchone()[0] == before_slots
    assert db_conn.execute("SELECT COUNT(*) FROM sa_candidates").fetchone()[0] == before_candidates

    # 7. 외부 트랜잭션 유지 확인
    user = db_conn.execute(
        """
        SELECT user_id
        FROM sa_users
        WHERE user_id = %s
        """,
        (user_id,),
    ).fetchone()

    assert user is not None
    assert user[0] == user_id
