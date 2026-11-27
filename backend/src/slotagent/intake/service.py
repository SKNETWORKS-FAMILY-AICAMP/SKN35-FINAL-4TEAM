"""④ 저장 함수. 형식 검사(contracts) → 내용 검사(common.checks) → DB 저장 → DB 오류를 api.error 로 바꿈."""

from psycopg.types.json import Jsonb

from slotagent.common import checks, contracts
from slotagent.common.hashing import agent_spec_hash, canonical_hash
from slotagent.common.snapshot import build_config_snapshot


def _check_registration_tools(
    tools: list[dict],
    *,
    is_tool_search: bool = False,
) -> None:
    """등록 시 예약 도구 이름과 쓰기 도구의 capabilities를 검사한다."""
    errors = []

    reserved = checks.RESERVED_TOOL_NAMES
    if not is_tool_search:
        reserved = reserved - {"search_tools"}

    for tool in tools:
        name = tool["name"]

        # 1. 엔진 예약 도구 이름 충돌 검사
        if name in reserved:
            errors.append(f"{name}은(는) 엔진 예약 도구 이름입니다.")

        # 2. 쓰기 도구의 capabilities 누락 검사
        if tool["access"] == "write":
            if not tool.get("capabilities"):
                errors.append(f"쓰기 도구 {name}에는 capabilities가 필요합니다.")

    if errors:
        raise checks.CheckError("invalid_spec", errors)


def register_agent(conn, req: dict, owner_id: int) -> dict:
    """api.register_agent_request → agents·agent_versions + (service, access) 마다 slots + 자리마다 기준 후보 A.
    기준 후보는 checks.baseline_component(spec, slot) 로 만듦 (손으로 받지 않음). 돌려주는 값: api.register_agent_response"""
    contracts.validate("api", req, part="register_agent_request")

    # ② Agent 버전 및 도구 구성 추출
    version = req["version"]
    spec = version["spec"]

    checks.check_registration(version["connection_type"], spec)

    # ⑤ API 연결의 제어 수준 검사
    if version["connection_type"] == "api" and version["control_level"] == "C2":
        raise checks.CheckError(
            "invalid_spec",
            ["API 연결에서는 C2 제어 수준을 사용할 수 없습니다."],
        )

    # ⑥ 트랜잭션 시작
    with conn.transaction():
        # ⑦ Agent 기본 정보 저장
        agent_row = conn.execute(
            """
            INSERT INTO sa_agents (
                owner_id,
                name,
                purpose,
                domain_code,
                expected_monthly_calls
            )
            VALUES (%s, %s, %s, %s, %s)
            RETURNING agent_id
            """,
            (
                owner_id,
                req["name"],
                req.get("purpose"),
                req.get("domain_code"),
                req.get("expected_monthly_calls"),
            ),
        ).fetchone()

        agent_id = agent_row[0]

        # ⑧ Agent 구성 해시 생성
        spec_hash = agent_spec_hash(
            version["model"],
            version["temperature"],
            version["instructions"],
            spec,
        )

        # ⑨ Agent 첫 번째 버전 저장
        version_row = conn.execute(
            """
            INSERT INTO sa_agent_versions (
                agent_id,
                version_no,
                connection_type,
                model_provider,
                control_level,
                model,
                temperature,
                instructions,
                spec,
                spec_schema_version,
                spec_hash
            )
            VALUES (%s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s)
            RETURNING agent_version_id
            """,
            (
                agent_id,
                1,
                version["connection_type"],
                version["model_provider"],
                version["control_level"],
                version["model"],
                version["temperature"],
                version["instructions"],
                Jsonb(spec),
                spec["schema_version"],
                spec_hash,
            ),
        ).fetchone()

        agent_version_id = version_row[0]
        slots = []
        for slot in checks.build_slots(version["connection_type"], version["control_level"], spec):
            slot_id = conn.execute(
                """
                INSERT INTO sa_slots (
                    agent_version_id, name, service, access, comparable, not_comparable_reason
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING slot_id
                """,
                (
                    agent_version_id,
                    slot["name"],
                    slot["service"],
                    slot["access"],
                    slot["comparable"],
                    slot["not_comparable_reason"],
                ),
            ).fetchone()[0]
            comp = checks.baseline_component(spec, slot)
            candidate_id = conn.execute(
                """
                INSERT INTO sa_candidates (
                    slot_id, label, name, component_kind, component_spec,
                    spec_schema_version, spec_hash, is_baseline
                )
                VALUES (%s, 'A', %s, %s, %s, %s, %s, TRUE)
                RETURNING candidate_id
                """,
                (
                    slot_id,
                    slot["name"],
                    comp["kind"],
                    Jsonb(comp),
                    comp["schema_version"],
                    canonical_hash(comp),
                ),
            ).fetchone()[0]
            slots.append({"slot_id": slot_id, **slot, "baseline_candidate_id": candidate_id})

        return {"agent_id": agent_id, "agent_version_id": agent_version_id, "slots": slots}


def register_candidate(conn, slot_id: int, req: dict) -> int:
    """후보 등록 요청과 Slot 적합성을 검사하고 저장된 후보 ID를 반환한다."""
    # ① 요청 JSON 검증
    contracts.validate("api", req, part="register_candidate_request")
    comp = req["component_spec"]

    # ② Slot 조회 (comparable 포함)
    row = conn.execute(
        """
        SELECT service, access, comparable
        FROM sa_slots
        WHERE slot_id = %s
        """,
        (slot_id,),
    ).fetchone()

    # ③ Slot 존재 여부 확인
    if row is None:
        raise checks.CheckError("not_found", ["존재하지 않는 Slot입니다."])

    # ④ 비교 불가능한 Slot 등록 차단
    if not row[2]:
        raise checks.CheckError("wrong_slot", ["비교할 수 없는 Slot에는 Candidate를 등록할 수 없습니다."])

    slot = {
        "service": row[0],
        "access": row[1],
    }

    # ⑤ 후보가 Slot에 적합한지 확인
    checks.check_component(comp, slot)

    # ⑤-1 도구 등록 제약 검사
    _check_registration_tools(
        comp.get("tools", []),
        is_tool_search=comp["kind"] == "tool_search",
    )

    # ⑥ 후보 저장
    result = conn.execute(
        """
        INSERT INTO sa_candidates (
            slot_id, label, name, component_kind,
            component_spec, spec_schema_version,
            spec_hash, is_baseline
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE)
        RETURNING candidate_id
        """,
        (
            slot_id,
            req["label"],
            req["name"],
            comp["kind"],
            Jsonb(comp),
            comp["schema_version"],
            canonical_hash(comp),
        ),
    ).fetchone()

    return result[0]


def create_experiment_draft(conn, req: dict, user_id: int) -> int:
    """api.create_experiment_request → experiments(draft) + experiment_candidates.
    prereg·plan 은 plan-proposal 이 준 값(고쳤으면 고친 값). checks.check_plan(plan, template_of, prereg), checks.check_experiment_candidates(rows).
    plan.proposal 은 ④가 적지 않음: common.proposal.verify(conn, req["proposal"], saved) 가 제안을 다시 만들어 비교해 채움 (3차 5).
    저장 전 contracts.validate("plan", plan, part="stored").
    role = 'baseline' if candidates.is_baseline else 'candidate', label = candidates.label. 돌려주는 값: experiment_id"""
    contracts.validate("api", req, part="create_experiment_request")
    raise NotImplementedError


def add_candidate(conn, experiment_id: int, candidate_id: int) -> int:
    """experiment_candidates 한 행. config_snapshot 은 반드시 ①의 함수로.
    template_scope = checks.template_scope(snap["tools"], 평가팩 templates) 를 같이 저장 (기획서 1.3 5.4).
    needs_review 가 있으면 사람이 정한 뒤에만 저장 (DB 가 막음)"""
    snap, h = build_config_snapshot(conn, candidate_id)
    raise NotImplementedError
