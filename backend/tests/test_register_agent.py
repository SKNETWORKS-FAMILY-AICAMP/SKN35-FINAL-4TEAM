"""④ Agent 등록 입력 검증 테스트."""

from unittest.mock import Mock

import psycopg
import pytest
from conftest import load

from slotagent.common import checks, contracts
from slotagent.intake.service import register_agent


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


def test_register_agent_rollback(
    agent_db_context,
    agent_request,
):
    db_conn, user_id = agent_db_context

    # 1. 등록 전 Agent 개수 확인
    before_agents = db_conn.execute("SELECT COUNT(*) FROM sa_agents").fetchone()[0]

    # 2. 등록 전 Agent Version 개수 확인
    before_versions = db_conn.execute("SELECT COUNT(*) FROM sa_agent_versions").fetchone()[0]

    # 3. Agent 등록 시도
    # 현재 미구현 부분에서 오류 발생
    with pytest.raises(NotImplementedError):
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
