import psycopg
import pytest
from slotagent.common import checks
from conftest import load
from psycopg.types.json import Jsonb

from slotagent.common.hashing import (
    agent_spec_hash,
    canonical_hash,
)
from slotagent.intake.service import register_candidate


@pytest.fixture
def candidate_context(pg):
    with psycopg.connect(pg) as conn:
        with conn.transaction(force_rollback=True):

            # 1. 테스트 사용자 생성
            user_id = conn.execute(
                """
                INSERT INTO sa_users(email, name)
                VALUES ('candidate-test@example.test', '테스트 사용자')
                RETURNING user_id
                """
            ).fetchone()[0]

            # 2. 도메인 생성
            conn.execute(
                """
                INSERT INTO sa_domains(domain_code, name, status)
                VALUES ('it_ops', 'IT 운영', 'active')
                ON CONFLICT (domain_code) DO NOTHING
                """
            )

            # 3. Agent 생성
            av = load("agent_version.json")

            agent_id = conn.execute(
                """
                INSERT INTO sa_agents(
                    owner_id, name,
                    expected_monthly_calls, domain_code
                )
                VALUES (%s, %s, %s, %s)
                RETURNING agent_id
                """,
                (
                    user_id,
                    av["_agent"]["name"],
                    av["_agent"]["expected_monthly_calls"],
                    av["_agent"]["domain_code"],
                ),
            ).fetchone()[0]

            # 4. Agent Version 생성
            spec = av["spec"]

            version_id = conn.execute(
                """
                INSERT INTO sa_agent_versions(
                    agent_id, version_no, connection_type,
                    questions_used, model_provider,
                    control_level, model, temperature,
                    instructions, spec, spec_hash
                )
                VALUES (%s, 1, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s)
                RETURNING agent_version_id
                """,
                (
                    agent_id,
                    av["connection_type"],
                    av["questions_used"],
                    av["model_provider"],
                    av["control_level"],
                    av["model"],
                    av["temperature"],
                    av["instructions"],
                    Jsonb(spec),
                    agent_spec_hash(
                        av["model"],
                        av["temperature"],
                        av["instructions"],
                        spec,
                    ),
                ),
            ).fetchone()[0]

            # 5. Slot 생성
            example = load("slot_and_candidates.json")
            slot = example["slot"]

            slot_id = conn.execute(
                """
                INSERT INTO sa_slots(
                    agent_version_id, name,
                    service, access, comparable
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING slot_id
                """,
                (
                    version_id,
                    slot["name"],
                    slot["service"],
                    slot["access"],
                    slot["comparable"],
                ),
            ).fetchone()[0]

            yield conn, slot_id


def test_register_candidate_success(candidate_context):
    conn, slot_id = candidate_context

    # 6. 후보 B의 요청 데이터 준비
    candidate = load("slot_and_candidates.json")["candidates"][1]

    req = {
        "label": candidate["label"],
        "name": candidate["name"],
        "component_spec": candidate["component_spec"],
    }

    # 7. 내가 구현한 함수 실행
    candidate_id = register_candidate(conn, slot_id, req)

    # 8. 실제 DB 저장 결과 확인
    row = conn.execute(
        """
        SELECT slot_id, label, name, component_kind,
               component_spec, spec_schema_version,
               spec_hash, is_baseline
        FROM sa_candidates
        WHERE candidate_id = %s
        """,
        (candidate_id,),
    ).fetchone()

    # 9. 기대 결과와 비교
    assert isinstance(candidate_id, int)
    assert row is not None
    assert row == (
        slot_id,
        req["label"],
        req["name"],
        req["component_spec"]["kind"],
        req["component_spec"],
        req["component_spec"]["schema_version"],
        canonical_hash(req["component_spec"]),
        False,
    )

def test_register_candidate_slot_not_found(candidate_context):
    conn, slot_id = candidate_context

    candidate = load("slot_and_candidates.json")["candidates"][1]

    req = {
        "label": candidate["label"],
        "name": candidate["name"],
        "component_spec": candidate["component_spec"],
    }

    with pytest.raises(checks.CheckError) as exc:
        register_candidate(conn, -1, req)

    assert exc.value.code == "not_found"


def test_register_candidate_service_mismatch(candidate_context):
    conn, slot_id = candidate_context

    candidate = load("slot_and_candidates.json")["candidates"][1]

    req = {
        "label": candidate["label"],
        "name": candidate["name"],
        "component_spec": candidate["component_spec"],
    }

    # GitHub Slot에 Slack 후보 등록 시도
    req["component_spec"]["service"] = "slack"

    with pytest.raises(checks.CheckError) as exc:
        register_candidate(conn, slot_id, req)

    assert exc.value.code == "invalid_spec"


def test_register_candidate_access_mismatch(candidate_context):
    conn, slot_id = candidate_context

    candidate = load("slot_and_candidates.json")["candidates"][1]

    req = {
        "label": candidate["label"],
        "name": candidate["name"],
        "component_spec": candidate["component_spec"],
    }

    # 조회 전용 Slot에 쓰기 후보 등록 시도
    req["component_spec"]["access"] = "write"

    with pytest.raises(checks.CheckError) as exc:
        register_candidate(conn, slot_id, req)

    assert exc.value.code == "invalid_spec"