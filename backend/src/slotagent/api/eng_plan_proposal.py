"""[①] POST /api/experiments/plan-proposal — 라우터만. 응답 모양(api plan_proposal_response)은 ①이 책임.

값을 만드는 본체는 common.proposal.propose (④ 저장 함수도 같은 함수로 다시 만들어 비교하므로 common 에 둠, 3차 5).
응답에는 as_of(제안 시각)가 있고 plan 에는 proposal 칸이 없음. ④는 create 요청에 proposal = {request, as_of} 를 넣음.
"""
from slotagent.common import contracts
from slotagent.common.proposal import propose


def handle(conn, req: dict) -> dict:
    contracts.validate("api", req, part="plan_proposal_request")
    return contracts.validate("api", propose(conn, req), part="plan_proposal_response")
