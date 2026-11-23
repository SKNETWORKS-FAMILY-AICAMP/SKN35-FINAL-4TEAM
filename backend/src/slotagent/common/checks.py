"""JSON Schema 로는 표현이 안 되는 검사 (담당 ①, 부르는 쪽 ②③④). 11/22 검토 30·33 반영.

저장하기 전에 contracts.validate() 다음으로 부른다. 틀리면 CheckError (api 에서 code=invalid_spec / invalid_plan).

    check_component(comp, slot)                 # 30-a 도구의 service·access 가 자리와 같은지
    baseline_component(agent_spec, slot)        # 30-e 기준 후보 A 는 agent_spec 에서 자동으로 만듦
    check_baseline(comp, agent_spec, slot)      #      손으로 만든 기준이 실제 구성과 같은지
    check_task_conditions(conditions)           # 30-d link.supports 가 같은 문항의 info key 인지
    condition_gate(kind, spec)                  # 23  성공 판정에 쓰는 조건인지 (기본값 한 곳). forbidden 은 항상 true (3차 1)
    run_outcome_for(reason, prereg)             # 3차 6 outcome_reason → run_outcome (규칙 한 곳)
    check_plan(plan, template_of, prereg)       # 30-b·c 문항 겹침, 문항 유형이 한 묶음에만, looks = 마지막 묶음
    check_experiment_candidates(rows)           # 32  기준 후보(is_baseline) 정확히 1개
    check_method(method, prereg)                # 33  analyses.method 의 복사본이 prereg 와 같은지
    check_write_modes(connection_type, spec)    # 1.3 쓰기 도구 실행 방식(연결별 허용 값)·쓰기 도구 10개까지
    template_scope(tools, templates)            # 1.3 실행 전에 문항 유형별 범위 판정 (범위 밖 = 실패로 셈, P-01)
제안값 추적(plan.proposal)은 common.proposal 에서 (3차 5 — 서버가 다시 계산해 비교)
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from .hashing import canonical_hash


class CheckError(ValueError):
    def __init__(self, code: str, errors: list[str]):
        self.code, self.errors = code, errors
        super().__init__("; ".join(errors[:5]))


def _raise(code: str, errs: list[str]) -> None:
    if errs:
        raise CheckError(code, errs)


# ---- 쓰기 도구 실행 방식 (기획서 1.3 5.8·8.1) ------------------------------
WRITE_MODES = {                       # 연결 방식별로 사용자가 고를 수 있는 값. 플랫폼은 외부 시스템에 직접 쓰지 않음
    "spec_upload": ("fake", "exclude_tasks"),   # 가짜 도구로 대체 / 그 문항 빼기
    "runner": ("fake", "test_space"),           # 가짜 도구 / 사용자가 준비한 테스트 공간에 실제로 씀
    "api": ("dry_run",),                        # 운영 환경이라 드라이런으로 설정된 경우에만 실행
}
MAX_WRITE_TOOLS = 10


def check_write_modes(connection_type: str, agent_spec: Mapping[str, Any]) -> None:
    """등록 때 (④). write_mode 는 쓰기 도구에만, 연결 방식이 허용하는 값만. 비면 fake (API 는 dry_run 필수)."""
    allowed = WRITE_MODES[connection_type]
    errs = []
    writes = [t for t in agent_spec["tools"] if t["access"] == "write"]
    if len(writes) > MAX_WRITE_TOOLS:
        errs.append(f"쓰기 도구는 {MAX_WRITE_TOOLS}개까지입니다 (지금 {len(writes)}개)")
    for t in agent_spec["tools"]:
        mode = t.get("write_mode")
        if t["access"] != "write":
            if mode is not None:
                errs.append(f"{t['name']} 은(는) 읽기 도구라 write_mode 를 둘 수 없습니다")
        elif mode is None and connection_type == "api":
            errs.append(f"API 연결의 쓰기 도구 {t['name']} 은(는) 드라이런(dry_run)으로 설정해야 실행합니다")
        elif mode is not None and mode not in allowed:
            errs.append(f"{connection_type} 연결에서 {t['name']} 의 write_mode 는 {', '.join(allowed)} 중 하나입니다")
    _raise("invalid_spec", errs)


# ---- 문항 유형 범위 (기획서 1.3 5.4, P-01 = fail) ---------------------------
def template_scope(tools: Iterable[Mapping[str, Any]], templates: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """후보 구성(config_snapshot.tools)과 문항 유형으로 실행 전에 범위를 정한다. 결과를 보고 짐작하지 않음.
    돌려주는 값: {문항 유형 code: in_scope | out_of_scope | excluded_write | needs_review}
    - required_capabilities 가 비면 in_scope (판정 안 함)
    - 필요한 기능을 하는 도구가 없으면 out_of_scope → 1차 성공률에서 실패로 셈
      (capabilities 를 안 적은 도구가 있으면 그 도구가 할 수도 있어 needs_review → 평가팩 잠그기 전 사람 확인)
    - 필요한 기능을 하는 도구가 모두 write_mode = exclude_tasks 면 excluded_write → 그 문항 유형은 실험에서 뺌
    """
    tools = list(tools)
    provided: dict[str, list] = {}
    for t in tools:
        for c in t.get("capabilities", []):
            provided.setdefault(c, []).append(t)
    unknown = any(not t.get("capabilities") for t in tools)
    out = {}
    for tp in templates:
        status = "in_scope"
        for c in tp.get("required_capabilities") or []:
            if c not in provided:
                status = "needs_review" if unknown else "out_of_scope"
                break
            if all(t.get("write_mode") == "exclude_tasks" for t in provided[c]):
                status = "excluded_write"
        out[tp["code"]] = status
    return out


# ---- 후보 ---------------------------------------------------------------
def check_component(comp: Mapping[str, Any], slot: Mapping[str, Any]) -> None:
    """tool_bundle / custom_tool / tool_search: 묶음과 그 안의 도구가 모두 자리 (service, access) 와 같아야 함.
    tool_search 는 always_loaded 이름이 tools 안에 있어야 하고, 검색할 도구가 하나는 남아야 함."""
    if comp["kind"] not in ("tool_bundle", "custom_tool", "tool_search"):
        return
    want = (slot["service"], slot["access"])
    errs = []
    if (comp["service"], comp["access"]) != want:
        errs.append(f"후보는 {comp['service']}/{comp['access']} 자리용인데 자리는 {want[0]}/{want[1]} 입니다")
    for t in comp["tools"]:
        if (t["service"], t["access"]) != want:
            errs.append(f"도구 {t['name']} 은(는) {t['service']}/{t['access']} 라 {want[0]}/{want[1]} 자리에 넣을 수 없습니다")
    if comp["kind"] == "tool_search":
        names = {t["name"] for t in comp["tools"]}
        always = set(comp["search"].get("always_loaded", []))
        for n in sorted(always - names):
            errs.append(f"처음부터 보여 줄 도구 {n} 이(가) tools 에 없습니다")
        if not names - always:
            errs.append("검색할 도구가 없습니다 (tools 가 모두 always_loaded)")
    _raise("invalid_spec", errs)


def baseline_component(agent_spec: Mapping[str, Any], slot: Mapping[str, Any]) -> dict:
    """기준 후보 A 의 component_spec 을 agent_spec 에서 만든다 (등록 때 자리마다 자동으로)."""
    tools = sorted((t for t in agent_spec["tools"] if (t["service"], t["access"]) == (slot["service"], slot["access"])),
                   key=lambda t: t["name"])
    if not tools:
        raise CheckError("invalid_spec", [f"{slot['service']}/{slot['access']} 자리에 지금 켜진 도구가 없습니다"])
    comp: dict[str, Any] = {"schema_version": 1, "kind": "tool_bundle",
                            "service": slot["service"], "access": slot["access"], "tools": tools}
    used = {t["origin"].split(":", 1)[1] for t in tools if t["origin"].startswith("mcp:")}
    if len(used) == 1:
        (name,) = used
        server = next((s for s in agent_spec.get("mcp_servers", []) if s["name"] == name), None)
        if server:
            comp["mcp_server"] = server
    return comp


def check_baseline(comp: Mapping[str, Any], agent_spec: Mapping[str, Any], slot: Mapping[str, Any]) -> None:
    """기준 후보의 도구가 agent_spec 의 그 자리 도구와 같은지 (순서는 안 봄)."""
    want = baseline_component(agent_spec, slot)
    key = lambda ts: sorted(canonical_hash(t) for t in ts)  # noqa: E731
    if comp.get("kind") != "tool_bundle" or key(comp["tools"]) != key(want["tools"]):
        raise CheckError("invalid_spec", ["기준 후보가 지금 구성(agent_spec)의 이 자리 도구와 다릅니다. 기준은 자동으로 만든 것을 쓰세요"])


# ---- 정답 조건 ------------------------------------------------------------
GATE_DEFAULT = {"info": True, "order": True, "end_state": True, "link": False}


def condition_gate(kind: str, spec: Mapping[str, Any]) -> bool:
    """성공 = gate 가 true 인 조건이 모두 통과. 비어 있으면 kind 별 기본값.
    forbidden 은 gate 칸이 없고 항상 관문 — 금지 행동을 한 풀이는 성공일 수 없음 (DB CHECK 와 같게, 3차 1)."""
    if kind == "forbidden":
        return True
    return bool(spec.get("gate", GATE_DEFAULT[kind]))


def run_outcome_for(reason: str | None, prereg: Mapping[str, Any]) -> str:
    """outcome_reason → run_outcome (3차 6). 이유가 없으면 completed.
    prereg.outcome_rules.env_error_reasons 에 있으면 env_error, timeout_ 으로 시작하면 timeout, 나머지는 agent_error."""
    if reason is None:
        return "completed"
    if reason in prereg["outcome_rules"]["env_error_reasons"]:
        return "env_error"
    if reason.startswith("timeout_"):
        return "timeout"
    return "agent_error"


def check_task_conditions(conditions: Iterable[Mapping[str, Any]]) -> None:
    """한 문항의 조건 목록 [{kind, spec}] — key 겹침, link.supports 가 같은 문항 info key 인지, 성공 조건이 1개 이상인지."""
    conds = list(conditions)
    errs = []
    keys = [c["spec"]["key"] for c in conds if "key" in c["spec"]]
    dup = sorted({k for k in keys if keys.count(k) > 1})
    if dup:
        errs.append(f"조건 key 가 겹칩니다: {', '.join(dup)}")
    info_keys = {c["spec"]["key"] for c in conds if c["kind"] == "info"}
    for c in conds:
        if c["kind"] == "link":
            bad = [k for k in c["spec"]["supports"] if k not in info_keys]
            if bad:
                errs.append(f"link {c['spec']['key']} 이(가) 이 문항에 없는 info 조건을 가리킵니다: {', '.join(bad)}")
    if not any(condition_gate(c["kind"], c["spec"]) for c in conds):
        errs.append("성공 판정에 쓰는 조건(gate)이 하나도 없습니다")
    _raise("invalid_spec", errs)


# ---- 실험 ----------------------------------------------------------------
def check_plan(plan: Mapping[str, Any], template_of: Mapping[int, str], prereg: Mapping[str, Any] | None = None) -> None:
    """template_of = {task_id: 문항 유형 code} (실험의 평가팩 문항만). DB 원문 오류가 나기 전에 막음."""
    errs = []
    ids = [t["task_id"] for t in plan["tasks"]]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        errs.append(f"같은 문항이 계획에 두 번 있습니다: {dup}")
    missing = sorted(i for i in set(ids) if i not in template_of)
    if missing:
        errs.append(f"실험의 평가팩에 없는 문항입니다: {missing}")
    batches_of: dict[str, set[int]] = {}
    for t in plan["tasks"]:
        if t["task_id"] in template_of:
            batches_of.setdefault(template_of[t["task_id"]], set()).add(t["batch_no"])
    split = sorted(code for code, b in batches_of.items() if len(b) > 1)
    if split:
        errs.append(f"같은 문항 유형이 여러 묶음에 흩어져 있습니다 (문항 유형이 통계 단위): {', '.join(split)}")
    used = sorted({t["batch_no"] for t in plan["tasks"]})
    if used != list(range(1, len(used) + 1)):
        errs.append(f"묶음 번호는 1부터 빈틈 없이: {used}")
    if prereg is not None:
        seq = prereg.get("sequential", {"method": "none"})
        if seq["method"] == "group_sequential" and seq.get("looks") != (used[-1] if used else 0):
            errs.append(f"prereg.sequential.looks({seq.get('looks')})가 마지막 묶음 번호({used[-1] if used else 0})와 다릅니다")
        if seq["method"] == "none" and len(used) > 1:
            errs.append("순차 검정을 안 하면(method=none) 묶음은 1개여야 합니다")
    _raise("invalid_plan", errs)


def check_experiment_candidates(rows: Iterable[Mapping[str, Any]]) -> None:
    """rows = 넣을 candidates 행들. 기준(is_baseline) 1개, 같은 자리."""
    rows = list(rows)
    errs = []
    if sum(1 for r in rows if r["is_baseline"]) != 1:
        errs.append("기준 후보(지금 구성)를 정확히 1개 넣어야 합니다")
    if len({r["slot_id"] for r in rows}) > 1:
        errs.append("한 실험에는 한 자리의 후보만 넣습니다")
    _raise("invalid_spec", errs)


def check_method(method: Mapping[str, Any], prereg: Mapping[str, Any]) -> None:
    """analyses.method 의 alpha·looks 는 prereg 의 기록용 복사본 — 다르면 거절."""
    errs = []
    if method["correction"]["alpha"] != prereg["alpha"]:
        errs.append("analyses.method.correction.alpha 가 prereg.alpha 와 다릅니다")
    m_seq, p_seq = method.get("sequential", {}), prereg.get("sequential", {"method": "none"})
    if m_seq.get("method", "none") != p_seq["method"] or m_seq.get("looks") != p_seq.get("looks"):
        errs.append("analyses.method.sequential 이 prereg.sequential 과 다릅니다")
    _raise("invalid_spec", errs)
