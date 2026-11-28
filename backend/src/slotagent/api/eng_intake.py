"""① 등록·실험 초안 HTTP. 저장은 ④ intake.service 함수가 하고 여기서는 계약 검사·사용자·응답 모양만.

POST /api/agents                      에이전트 + 첫 버전 + 자리별 기준 후보 A
POST /api/slots/{slot_id}/candidates  기준이 아닌 후보
POST /api/experiments                 실험 초안 (plan-proposal 응답 값 + proposal 출처)

로그인이 정해지기 전이라 만든 사람은 SLOTAGENT_USER_ID (MCP 서버와 같은 값). 없으면 501.
"""

import os
from typing import Annotated

from fastapi import APIRouter, Body, Path, Request

from slotagent.common import contracts
from slotagent.common.checks import CheckError
from slotagent.intake import service

router = APIRouter(prefix="/api")
Id = Annotated[int, Path(ge=1, le=2**63 - 1)]


def _user() -> int:
    # shortcut: 환경 변수 하나로 사용자를 정함, 로그인이 정해지면 요청의 사용자로 바꿈
    user = os.environ.get("SLOTAGENT_USER_ID", "")
    if not user.isdigit():
        raise NotImplementedError("SLOTAGENT_USER_ID 가 없습니다.")
    return int(user)


def _checked(body, part: str) -> dict:
    # ④ 함수의 contracts.validate 는 ContractError(500) 라 여기서 먼저 422 로 돌려보냄
    if errs := contracts.errors("api", body, part=part):
        raise CheckError("invalid_spec", errs[:5])
    return body


@router.post("/agents")
def register_agent_route(request: Request, body: Annotated[dict, Body()]):
    req, user = _checked(body, "register_agent_request"), _user()
    with request.app.state.connect() as conn:
        return contracts.validate("api", service.register_agent(conn, req, user), part="register_agent_response")


@router.post("/slots/{slot_id}/candidates")
def register_candidate_route(request: Request, slot_id: Id, body: Annotated[dict, Body()]):
    req = _checked(body, "register_candidate_request")
    with request.app.state.connect() as conn:
        # 계약에 응답 모양이 없어 저장한 ID 만 돌려줌
        return {"candidate_id": service.register_candidate(conn, slot_id, req)}


@router.post("/experiments")
def create_experiment_route(request: Request, body: Annotated[dict, Body()]):
    req, user = _checked(body, "create_experiment_request"), _user()
    with request.app.state.connect() as conn:
        experiment_id = service.create_experiment_draft(conn, req, user)
    return contracts.validate("api", {"experiment_id": experiment_id, "status": "draft"},
                              part="create_experiment_response")
