"""④ 저장 함수. 형식 검사(contracts) → 내용 검사(common.checks) → DB 저장 → DB 오류를 api.error 로 바꿈."""
from slotagent.common import checks, contracts  # noqa: F401  checks 는 ④ 구현 때 씀
from slotagent.common.hashing import canonical_hash  # noqa: F401  ④ 구현 때 씀
from slotagent.common.snapshot import build_config_snapshot


def register_agent(conn, req: dict, owner_id: int) -> dict:
    """api.register_agent_request → agents·agent_versions + (service, access) 마다 slots + 자리마다 기준 후보 A.
    기준 후보는 checks.baseline_component(spec, slot) 로 만듦 (손으로 받지 않음). 돌려주는 값: api.register_agent_response"""
    contracts.validate("api", req, part="register_agent_request")
    raise NotImplementedError


def register_candidate(conn, slot_id: int, req: dict) -> int:
    """api.register_candidate_request → candidates 행 (기준 아님). checks.check_component 후 INSERT. 돌려주는 값: candidate_id"""
    contracts.validate("api", req, part="register_candidate_request")
    comp = req["component_spec"]  # noqa: F841  ④ 구현 자리
    raise NotImplementedError("INSERT INTO candidates(..., spec_hash=canonical_hash(comp))")


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
