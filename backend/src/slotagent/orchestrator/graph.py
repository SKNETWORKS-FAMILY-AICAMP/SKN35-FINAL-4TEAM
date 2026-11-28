"""① 오케스트레이터 그래프 (docs/eng_orchestrator_design_1127.md).

절차만 관리합니다. 표본 수·채점·판정·실험 상태 변경은 Backend(기존 API) 가 하고, 여기서는 요청과 승인만 다룹니다.
interrupt() 로 멈춘 노드는 재개 때 처음부터 다시 실행되므로, interrupt 하는 노드(goal_ok·plan_ok·run_ok·wait·blocked)
에는 부수 효과를 두지 않고 쓰기(save_draft·start_run)는 따로 둡니다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from slotagent.common import contracts
from slotagent.common.hashing import canonical_hash
from slotagent.common.llm import ModelError
from slotagent.common.snapshot import PHASE1_KINDS
from slotagent.orchestrator.brain import prose_problems

EDITABLE = ("reps", "budget_krw", "candidate_ids")
MAX_PICK = 2  # plan-proposal 후보 3개까지 = 기준 1 + 비교 2


class BackendError(Exception):
    """연결부가 돌려준 오류. code 는 API 오류 코드 (experiment_locked, not_ready, ...)."""

    def __init__(self, code: str, detail: Any = None):
        super().__init__(code)
        self.code = code
        self.detail = detail


class Backend(Protocol):
    def list_candidates(self, slot_id: int) -> list[dict]: ...  # 같은 자리·같은 MCP 서버로 거른 목록
    def plan_proposal(self, req: dict) -> dict: ...
    def create_experiment(self, req: dict, create_key: str) -> int: ...
    def run(self, experiment_id: int) -> dict: ...
    def status(self, experiment_id: int) -> dict: ...
    def final_result(self, experiment_id: int) -> dict | None: ...  # 최종 분석 + 리포트 2종, 없으면 None


class Brain(Protocol):
    def goal(self, text: str) -> dict: ...
    def pick(self, goal: dict, candidates: list[dict]) -> dict: ...  # {"candidate_ids": [...], "reason": str}
    def explain(self, goal: dict, result: dict) -> str: ...  # 숫자 없는 글. 숫자는 explanation.facts 로 코드가 보여 줌


class OrchState(TypedDict, total=False):
    # 대상 (호출자가 정해 넘김. LLM 은 목표만 구조화)
    user_id: int
    text: str
    agent_version_id: int
    slot_id: int
    pack_version_id: int
    goal: dict
    candidate_ids: list[int]
    pool: dict                     # 코드가 거른 후보 {"baseline": id, "allowed": [id...]} — 수정도 이 안에서만
    pick_reason: str
    edits: dict
    edit_error: str | None
    # 계획
    proposal: dict
    create_request: dict
    approval_hash: str
    proposed_at: str
    # 승인
    approvals: dict
    create_key: str
    # 진행
    experiment_id: int
    last_status: str
    last_error: dict | None
    # 근거
    analysis_id: int
    report_ids: list[int]
    explanation: dict  # {"facts": 저장된 값 그대로, "text": 글} — 숫자·판정은 facts 에만


NEXT_STEP = {"stopped": "멈춘 이유를 확인한 뒤 필요하면 새 실험을 만드세요.",
             "failed": "실패한 풀이의 원인을 확인한 뒤 새 실험을 만드세요."}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _blocked(node: str, code: str, detail: Any = None) -> Command:
    return Command(goto="blocked", update={"last_error": {"node": node, "code": code, "detail": detail}})


def _answer(value) -> dict:
    """재개 값은 dict 만. 그 밖은 빈 응답 = 같은 대기로 (입구 검사는 runtime.resume)."""
    return value if isinstance(value, dict) else {}


def _is_id(v) -> bool:
    return type(v) is int and v > 0  # bool 은 int 의 하위형이라 type 으로 거름


def _valid_pick(pool: dict, ids) -> bool:
    if not isinstance(ids, list) or not all(map(_is_id, ids)) or len(set(ids)) != len(ids) or not 2 <= len(ids) <= MAX_PICK + 1:
        return False
    return ids[0] == pool["baseline"] and set(ids[1:]) <= set(pool["allowed"])


def _approve(state: OrchState, action: str, answer: dict, expected: str) -> dict:
    return {**state.get("approvals", {}), action: {"by": answer["by"], "at": _now(), "hash": expected}}


def _approved(state: OrchState, action: str, expected: str) -> bool:
    return state.get("approvals", {}).get(action, {}).get("hash") == expected


def run_hash(state: OrchState) -> str:
    return canonical_hash({"experiment_id": state["experiment_id"], "approval_hash": state["approval_hash"]})


def build(backend: Backend, brain: Brain) -> StateGraph:
    def goal(state: OrchState):
        try:
            return Command(goto="goal_ok", update={"goal": brain.goal(state["text"])})
        except ModelError as e:
            return _blocked("goal", "model_error", str(e))

    def goal_ok(state: OrchState):
        ans = _answer(interrupt({"kind": "goal", "goal": state["goal"]}))
        action = ans.get("action")
        if action == "approve" and ans.get("by"):
            return Command(goto="candidates", update={
                "goal": state["goal"], "approvals": _approve(state, "goal", ans, canonical_hash(state["goal"])),
            })
        if action == "edit" and isinstance(ans.get("text"), str) and ans["text"].strip():
            return Command(goto="goal", update={"text": ans["text"]})
        # 명시적 거절만 끝냄. 오타·빈 응답은 다시 물음
        return Command(goto=END) if action == "reject" else Command(goto="goal_ok")

    def candidates(state: OrchState):
        try:
            listed = backend.list_candidates(state["slot_id"])
        except BackendError as e:
            return _blocked("candidates", e.code, e.detail)
        rows = [r for r in listed if r["component_kind"] in PHASE1_KINDS and _is_id(r["candidate_id"])]
        base = [r["candidate_id"] for r in rows if r["is_baseline"]]
        others = [r for r in rows if not r["is_baseline"]]
        if len(base) != 1 or not others:
            return _blocked("candidates", "no_candidates", {"baseline": len(base), "others": len(others)})
        try:
            picked = brain.pick(state["goal"], others)
        except ModelError as e:
            return _blocked("candidates", "model_error", str(e))
        allowed = {r["candidate_id"] for r in others}
        # LLM 이 고른 값은 코드가 거른 목록 안에서만, 순서 유지
        ids = [i for i in dict.fromkeys(x for x in picked.get("candidate_ids", []) if _is_id(x)) if i in allowed][:MAX_PICK]
        if not ids:
            return _blocked("candidates", "no_pick", picked.get("reason"))
        return Command(goto="propose", update={
            "candidate_ids": base + ids, "pick_reason": picked.get("reason", ""),
            "pool": {"baseline": base[0], "allowed": sorted(allowed)},
        })

    def propose(state: OrchState):
        edits = state.get("edits", {})
        req = {
            "agent_version_id": state["agent_version_id"],
            "slot_id": state["slot_id"],
            "pack_version_id": state["pack_version_id"],
            "candidate_ids": edits.get("candidate_ids", state["candidate_ids"]),
            **{k: edits[k] for k in ("reps", "budget_krw") if k in edits},
        }
        try:
            out = backend.plan_proposal(req)
        except BackendError as e:
            return _blocked("propose", e.code, e.detail)
        create = {
            "agent_version_id": req["agent_version_id"],
            "slot_id": req["slot_id"],
            "pack_version_id": req["pack_version_id"],
            "reps": out["reps"],
            "prereg": out["prereg"],
            "plan": out["plan"],
            "candidates": req["candidate_ids"],
            "proposal": {"request": req, "as_of": out["as_of"]},
            **({"budget_krw": req["budget_krw"]} if "budget_krw" in req else {}),
        }
        # 승인 비교는 보낼 요청 전체로 (proposal_hash 는 prereg·plan 만 봄)
        return Command(goto="plan_ok", update={
            "proposal": out, "create_request": create, "approval_hash": canonical_hash(create),
            "proposed_at": _now(), "candidate_ids": req["candidate_ids"],
        })

    def plan_ok(state: OrchState, config):
        out, create = state["proposal"], state["create_request"]
        ans = _answer(interrupt({"kind": "plan", "hash": state["approval_hash"], "summary": {
            "candidates": create["candidates"], "n_tasks": out.get("n_tasks"), "trials": out.get("trials"),
            "reps": create["reps"], "budget_krw": create.get("budget_krw"),
            "estimated_cost_krw": "산정 전",  # propose() 가 비용을 돌려주지 않음 (설계 7절 7)
            "reason": state.get("pick_reason", ""), "edit_error": state.get("edit_error"),
        }}))
        action = ans.get("action")
        if action == "approve":
            if ans.get("hash") != state["approval_hash"] or not ans.get("by"):  # 보여 준 계획과 다르거나 승인자 없음
                return Command(goto="plan_ok")
            key = f"{config['configurable']['thread_id']}:{state['approval_hash']}"
            return Command(goto="save_draft", update={
                "approvals": _approve(state, "save_draft", ans, state["approval_hash"]), "create_key": key,
            })
        if action == "edit":
            raw = ans.get("edits")
            new = {k: v for k, v in raw.items() if k in EDITABLE} if isinstance(raw, dict) else {}
            if not new:
                return Command(goto="plan_ok", update={"edit_error": f"고칠 수 있는 값: {', '.join(EDITABLE)}"})
            if "candidate_ids" in new and not _valid_pick(state["pool"], new["candidate_ids"]):
                # 서버는 자리만 확인하므로 기준 포함·1단계 종류는 여기서 막음
                return Command(goto="plan_ok", update={"edit_error": "기준 후보가 맨 앞에 있고, 거른 후보 안에서 1~2개여야 합니다."})
            trial = {"agent_version_id": state["agent_version_id"], "slot_id": state["slot_id"],
                     "pack_version_id": state["pack_version_id"], "candidate_ids": state["candidate_ids"],
                     **{k: v for k, v in state.get("edits", {}).items()}, **new}
            errs = contracts.errors("api", trial, part="plan_proposal_request")  # reps 1~10, 예산 > 0 등은 계약대로
            if errs:
                return Command(goto="plan_ok", update={"edit_error": "; ".join(errs)})
            return Command(goto="propose", update={"edits": {**state.get("edits", {}), **new}, "edit_error": None})
        return Command(goto=END) if action == "reject" else Command(goto="plan_ok")

    def save_draft(state: OrchState):
        if not _approved(state, "save_draft", state["approval_hash"]):
            return Command(goto="plan_ok")
        if state.get("experiment_id"):
            return Command(goto="run_ok")
        try:
            eid = backend.create_experiment(state["create_request"], state["create_key"])
        except BackendError as e:
            return _blocked("save_draft", e.code, e.detail)
        return Command(goto="run_ok", update={"experiment_id": eid})

    def run_ok(state: OrchState):
        try:
            st = backend.status(state["experiment_id"])
        except BackendError as e:
            return _blocked("run_ok", e.code, e.detail)
        expected = run_hash(state)
        ans = _answer(interrupt({"kind": "run", "hash": expected, "summary": {
            "experiment_id": state["experiment_id"], "trials_total": st.get("trials_total"),
            "budget_krw": st.get("budget_krw"),
        }}))
        if ans.get("action") == "approve":
            if ans.get("hash") != expected or not ans.get("by"):
                return Command(goto="run_ok")
            return Command(goto="start_run", update={"approvals": _approve(state, "start_run", ans, expected)})
        return Command(goto=END) if ans.get("action") == "reject" else Command(goto="run_ok")

    def start_run(state: OrchState):
        if not _approved(state, "start_run", run_hash(state)):
            return Command(goto="run_ok")
        try:
            backend.run(state["experiment_id"])
        except BackendError as e:
            # 실행 요청 뒤 체크포인트 전에 죽었고 그사이 실험이 끝났으면 여기로 옴 → 상태로 복구
            if e.code != "experiment_locked":
                return _blocked("start_run", e.code, e.detail)
        return Command(goto="watch")

    def watch(state: OrchState):
        try:
            st = backend.status(state["experiment_id"])["status"]
        except BackendError as e:
            return _blocked("watch", e.code, e.detail)
        goto = {"done": "explain", "stopped": "explain_partial", "failed": "explain_partial"}.get(st, "wait")
        return Command(goto=goto, update={"last_status": st})

    def wait(state: OrchState):
        ans = _answer(interrupt({"kind": "wait", "experiment_id": state["experiment_id"]}))
        return Command(goto="watch" if ans.get("action") == "tick" else "wait")

    def explain(state: OrchState):
        try:
            res = backend.final_result(state["experiment_id"])
        except BackendError as e:
            return _blocked("explain", e.code, e.detail)
        if res is None:  # done 이면 게이트가 확인했으므로 오지 않아야 함
            return _blocked("explain", "analysis_missing")
        try:
            text = brain.explain(state["goal"], res)
        except ModelError as e:
            return _blocked("explain", "model_error", str(e))
        problems = prose_problems(text)
        if problems:  # 모델 글에 숫자가 있으면 저장하지 않고 이유를 보여 줌
            return _blocked("explain", "explanation_rejected", problems)
        return Command(goto=END, update={"analysis_id": res["analysis_id"], "report_ids": res["report_ids"],
                                         "explanation": {"facts": res, "text": text}})

    def explain_partial(state: OrchState):
        try:
            st = backend.status(state["experiment_id"])
        except BackendError as e:
            return _blocked("explain_partial", e.code, e.detail)
        # 정상 완료가 아니면 모델을 부르지 않음 — 추천이 섞일 길을 없앰
        text = (f"실험이 {st['status']} 상태로 끝나 비교 결과를 추천에 쓰지 않습니다. "
                + NEXT_STEP.get(st["status"], "현재 상태를 확인하세요."))
        return Command(goto=END, update={"explanation": {"facts": st, "text": text}})

    def blocked(state: OrchState):
        err = state["last_error"]
        ans = _answer(interrupt({"kind": "blocked", "error": err}))
        if ans.get("action") == "reject":
            return Command(goto=END)
        if ans.get("action") != "retry":
            return Command(goto="blocked")
        node = err["node"]
        if state.get("experiment_id") and node in ("candidates", "propose"):
            node = "run_ok"  # 저장된 실험 문맥을 다시 시작하지 않음
        return Command(goto=node, update={"last_error": None})

    g = StateGraph(OrchState)
    for fn in (goal, goal_ok, candidates, propose, plan_ok, save_draft, run_ok, start_run, watch, wait,
               explain, explain_partial, blocked):
        g.add_node(fn.__name__, fn)
    g.add_edge(START, "goal")
    return g
