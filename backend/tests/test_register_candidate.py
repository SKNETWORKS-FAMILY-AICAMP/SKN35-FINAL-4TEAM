import psycopg
import pytest
from conftest import load
from psycopg.types.json import Jsonb

from slotagent.common import checks
from slotagent.common.hashing import (
    agent_spec_hash,
    canonical_hash,
)
from slotagent.intake.service import _check_registration_tools, register_candidate


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


@pytest.mark.parametrize(
    "name",
    [
        "request_user_confirmation",
        "get_write_result",
        "get_work_state",
    ],
)
def test_reserved_tool_name(name):
    tools = [{"name": name, "access": "read"}]

    with pytest.raises(checks.CheckError) as exc:
        _check_registration_tools(tools)

    assert exc.value.code == "invalid_spec"


def test_tool_search_reserved_name():
    tools = [{"name": "search_tools", "access": "read"}]

    with pytest.raises(checks.CheckError) as exc:
        _check_registration_tools(
            tools,
            is_tool_search=True,
        )

    assert exc.value.code == "invalid_spec"


def test_write_tool_without_capabilities():
    tools = [
        {
            "name": "create_issue",
            "access": "write",
            "capabilities": [],
        }
    ]

    with pytest.raises(checks.CheckError) as exc:
        _check_registration_tools(tools)

    assert exc.value.code == "invalid_spec"


def test_write_tool_with_capabilities():
    tools = [
        {
            "name": "create_issue",
            "access": "write",
            "capabilities": ["github.issues.write"],
        }
    ]

    _check_registration_tools(tools)


def test_valid_read_tool():
    tools = [
        {
            "name": "list_issues",
            "access": "read",
            "capabilities": ["github.issues.read"],
        }
    ]

    _check_registration_tools(tools)


def test_search_tools_in_normal_candidate():
    tools = [{"name": "search_tools", "access": "read"}]

    _check_registration_tools(
        tools,
        is_tool_search=False,
    )


def test_register_candidate_reserved_tool(candidate_context):
    conn, slot_id = candidate_context

    data = load("slot_and_candidates.json")
    candidate = data["candidates"][1]

    req = {
        "label": candidate["label"],
        "name": candidate["name"],
        "component_spec": candidate["component_spec"],
    }

    # 예약 도구 이름으로 변경
    req["component_spec"]["tools"][0]["name"] = "get_work_state"

    # 등록 전 후보 개수 확인
    before = conn.execute(
        "SELECT COUNT(*) FROM sa_candidates WHERE slot_id = %s",
        (slot_id,),
    ).fetchone()[0]

    # 실제 후보 등록 시도
    with pytest.raises(checks.CheckError) as exc:
        register_candidate(conn, slot_id, req)

    assert exc.value.code == "invalid_spec"
    assert "get_work_state" in str(exc.value)

    # 등록 후 후보 개수 확인
    after = conn.execute(
        "SELECT COUNT(*) FROM sa_candidates WHERE slot_id = %s",
        (slot_id,),
    ).fetchone()[0]

    # 잘못된 후보가 DB에 저장되지 않았는지 확인
    assert before == after
