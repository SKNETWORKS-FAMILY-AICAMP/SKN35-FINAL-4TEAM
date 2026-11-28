"""① 등록·실험 초안 HTTP: 등록 → 후보 → plan-proposal → 초안 → 상태를 HTTP 로만 이어 봅니다."""

from contextlib import nullcontext

import pytest
from conftest import ROOT, load
from fastapi.testclient import TestClient
from test_register_agent import agent_db_context as agent_db_context
from test_register_agent import agent_request as agent_request

from slotagent.api.eng_app import create_app
from slotagent.common import contracts


def refused(response, status, code):
    assert (response.status_code, response.json()["code"]) == (status, code), response.text
    contracts.validate("api", response.json(), part="error")


def locked_pack(conn) -> int:
    for seed in ("0001_settings_defaults.sql", "0003_settings_proposal.sql"):
        conn.execute((ROOT / "backend/db/seeds" / seed).read_text(encoding="utf-8"))
    pack_id = conn.execute(
        "INSERT INTO sa_pack_versions (domain_code, pack_code, version) VALUES ('it_ops','api_intake','1') "
        "RETURNING pack_version_id"
    ).fetchone()[0]
    conn.execute(
        """WITH t AS (INSERT INTO sa_templates (pack_version_id, code, question_pattern, split)
                      VALUES (%s,'T1','List issues','held'), (%s,'T2','Read issue','held') RETURNING template_id, code)
           INSERT INTO sa_tasks (template_id, code, prompt, seed) SELECT template_id, code, 'Read issues', 1 FROM t""",
        (pack_id, pack_id),
    )
    conn.execute(
        "INSERT INTO sa_data_snapshots (pack_version_id, source_kind, location, content_hash, frozen_at) "
        "VALUES (%s,'fixed_response','api-intake','frozen',now())", (pack_id,),
    )
    conn.execute("UPDATE sa_pack_versions SET status='locked', locked_at=now() WHERE pack_version_id=%s", (pack_id,))
    return pack_id


def test_register_to_draft_over_http(agent_db_context, agent_request, monkeypatch):
    conn, user_id = agent_db_context
    client = TestClient(create_app(lambda: nullcontext(conn)), raise_server_exceptions=False)

    monkeypatch.delenv("SLOTAGENT_USER_ID", raising=False)
    refused(client.post("/api/agents", json=agent_request), 501, "internal")
    monkeypatch.setenv("SLOTAGENT_USER_ID", str(user_id))
    refused(client.post("/api/agents", json={"name": "x"}), 422, "invalid_spec")
    refused(client.post("/api/agents", json=[1]), 422, "invalid_spec")

    response = client.post("/api/agents", json=agent_request)
    assert response.status_code == 200, response.text
    agent = contracts.validate("api", response.json(), part="register_agent_response")
    slot = next(s for s in agent["slots"] if s["comparable"])

    candidate = load("api_and_jobs.json")["api.register_candidate_request"]
    refused(client.post("/api/slots/1/candidates", json={"label": "B"}), 422, "invalid_spec")
    refused(client.post(f"/api/slots/{2**62}/candidates", json=candidate), 404, "not_found")
    response = client.post(f"/api/slots/{slot['slot_id']}/candidates", json=candidate)
    assert response.status_code == 200, response.text
    candidate_id = response.json()["candidate_id"]

    pack_id = locked_pack(conn)
    proposal_req = {"agent_version_id": agent["agent_version_id"], "slot_id": slot["slot_id"],
                    "pack_version_id": pack_id, "candidate_ids": [slot["baseline_candidate_id"], candidate_id]}
    proposed = client.post("/api/experiments/plan-proposal", json=proposal_req).json()
    create = {"agent_version_id": agent["agent_version_id"], "slot_id": slot["slot_id"], "pack_version_id": pack_id,
              "candidates": proposal_req["candidate_ids"], "reps": proposed["reps"], "prereg": proposed["prereg"],
              "plan": proposed["plan"], "proposal": {"request": proposal_req, "as_of": proposed["as_of"]}}

    refused(client.post("/api/experiments", json={k: v for k, v in create.items() if k != "proposal"}),
            422, "invalid_spec")
    refused(client.post("/api/experiments", json={**create, "candidates": [candidate_id]}), 422, "invalid_spec")
    response = client.post("/api/experiments", json=create)
    assert response.status_code == 200, response.text
    draft = contracts.validate("api", response.json(), part="create_experiment_response")
    assert conn.execute("SELECT created_by, status FROM sa_experiments WHERE experiment_id=%s",
                        (draft["experiment_id"],)).fetchone() == (user_id, "draft")

    status = client.get(f"/api/experiments/{draft['experiment_id']}/status").json()
    assert (status["status"], status["trials"]["pending"]) == ("draft", 2 * 2 * proposed["reps"])
    # DB 오류로 거절 → 시험 트랜잭션이 깨지므로 맨 끝에
    refused(client.post(f"/api/slots/{slot['slot_id']}/candidates", json=candidate), 409, "label_taken")


@pytest.mark.parametrize("value", ["", "abc", "-1"])
def test_user_must_be_a_number(value, monkeypatch):
    monkeypatch.setenv("SLOTAGENT_USER_ID", value)
    client = TestClient(create_app(lambda: nullcontext(None)), raise_server_exceptions=False)
    refused(client.post("/api/agents", json=load("api_and_jobs.json")["api.register_agent_request"]), 501, "internal")
