"""build_config_snapshot — 후보 하나를 '실행할 수 있는 완성 구성'으로 합침 (담당 ①, 부르는 쪽 ④).

④는 실험에 후보를 넣을 때 이 함수로 config_snapshot·config_hash 를 만들어 experiment_candidates 에 저장한다.
①의 워커는 후보 구성을 이 묶음에서만 읽는다 (agent_versions·candidates 를 다시 읽지 않음).
문항(tasks.prompt·seed)과 연습 환경(data_snapshots.location)은 평가팩에서 읽는다.

합치는 규칙 (tool_bundle / custom_tool / tool_search)
1. agent_spec.tools 에서 자리 (service, access) 와 같은 도구를 모두 뺀다
2. 후보 component_spec.tools 를 넣는다
3. 이름순 정렬, 이름이 겹치면 오류
4. write_tools = access 가 write 인 도구 이름 전부 (쓰기 가로채기 대상)
5. mcp_servers = 남은 도구가 실제로 쓰는 서버만 (후보가 서버를 주면 같은 이름을 바꿔 끼움)
   단, 자리 밖 도구도 그 서버를 쓰는데 내용(버전 등)이 다르면 거절 — 다른 자리까지 바뀌어 "한 자리만 바꿈"이 깨짐
6. tool_search 는 1~5 를 똑같이 하고, tool_search 칸에 검색 설정과 deferred(검색해야 보이는 도구 이름)를 붙인다
prompt / model 후보는 도구는 그대로 두고 지시문·모델만 바꾼다.

실행 때 정해지는 값은 스냅숏에 넣지 않는다 (11/22 검토 36)
- 엔진 버전: 워커가 trials.harness_version 에 기록 (0003)
- 풀이별 seed: trial_seed(task.seed, rep) → spans.attributes['model.seed']
- 모델 고정 버전: spans.attributes['model.resolved']
"""
from __future__ import annotations

from typing import Any, Mapping

import hashlib

from . import checks, contracts, db_names
from .hashing import agent_spec_hash, canonical_hash

PHASE1_KINDS = ("tool_bundle", "custom_tool", "tool_search")   # 기획서 1.3: Tool 자리 먼저. Skill·MCP 서버 교체·프롬프트는 그다음
HARNESS_VERSION = "0.1.0"   # 워커가 trials.harness_version 에 기록. 스냅숏에는 넣지 않음
DEFAULT_RUNTIME = {"max_steps": 30, "timeout_sec": 300, "max_api_retries": 3}


def trial_seed(task_seed: int, rep: int) -> int:
    """풀이 하나의 seed. 같은 (문항, 반복)이면 후보가 달라도 같은 값 → 짝지은 비교. 0 ~ 2^31-1."""
    return int.from_bytes(hashlib.sha256(f"{task_seed}:{rep}".encode()).digest()[:4], "big") & 0x7FFFFFFF


class SnapshotError(ValueError):
    pass


def merge_snapshot(agent_version: Mapping[str, Any], slot: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict:
    """DB 행(dict) 3개로 config_snapshot 을 만든다. 순수 함수 (DB 안 씀)."""
    spec = contracts.validate("agent_spec", agent_version["spec"])
    comp = contracts.validate("component_spec", candidate["component_spec"])
    if comp["kind"] != candidate.get("component_kind", "tool_bundle"):
        raise SnapshotError("component_spec.kind 와 candidates.component_kind 가 다릅니다")
    if comp["kind"] not in PHASE1_KINDS:
        raise SnapshotError(f"{comp['kind']} 후보는 다음 단계입니다 (기획서 1.3: Tool 자리 먼저)")
    if candidate["slot_id"] != slot["id"] or slot["agent_version_id"] != agent_version["id"]:
        raise SnapshotError("후보·자리·에이전트 버전이 서로 이어지지 않습니다")

    model, temperature, instructions = agent_version["model"], agent_version["temperature"], agent_version["instructions"]
    tools = list(spec["tools"])
    servers = {s["name"]: s for s in spec.get("mcp_servers", [])}

    search = None
    if comp["kind"] in ("tool_bundle", "custom_tool", "tool_search"):
        try:
            checks.check_component(comp, slot)
        except checks.CheckError as e:
            raise SnapshotError(str(e)) from e
        if candidate.get("is_baseline"):
            try:
                checks.check_baseline(comp, spec, slot)
            except checks.CheckError as e:
                raise SnapshotError(str(e)) from e
        kept = [t for t in tools if (t["service"], t["access"]) != (slot["service"], slot["access"])]
        new_server = comp.get("mcp_server")
        if new_server and new_server["name"] in servers and canonical_hash(servers[new_server["name"]]) != canonical_hash(new_server):
            shared = sorted(t["name"] for t in kept if t["origin"] == f"mcp:{new_server['name']}")
            if shared:
                name = new_server["name"]
                raise SnapshotError(f"MCP 서버 {name} 을(를) 바꾸면 다른 자리 도구({', '.join(shared)})도 함께 바뀝니다. "
                                    f"후보의 서버 이름을 다르게 하세요 (예: {name}-b)")
        if new_server and (new_server["name"] not in servers or canonical_hash(servers[new_server["name"]]) != canonical_hash(new_server)):
            raise SnapshotError("MCP 서버를 새로 넣거나 바꾸는 후보는 다음 단계입니다 (기획서 1.3: Tool 자리 = 같은 MCP 서버 안의 도구·자체 도구)")
        tools = kept + list(comp["tools"])
        if new_server:
            servers[new_server["name"]] = new_server
        if comp["kind"] == "tool_search":
            always = set(comp["search"].get("always_loaded", []))
            search = {"method": comp["search"]["method"], "top_k": comp["search"]["top_k"],
                      "deferred": sorted(t["name"] for t in comp["tools"] if t["name"] not in always)}
    elif comp["kind"] == "prompt":
        instructions = comp["instructions"]
    elif comp["kind"] == "model":
        model = comp["model"]
        temperature = comp.get("temperature", temperature)
    else:  # skill, workflow
        raise SnapshotError(f"{comp['kind']} 후보는 아직 실행하지 않습니다 (확장)")

    names = [t["name"] for t in tools]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise SnapshotError(f"도구 이름이 겹칩니다: {', '.join(dup)}")
    tools.sort(key=lambda t: t["name"])
    used = {t["origin"].split(":", 1)[1] for t in tools if t["origin"].startswith("mcp:")}
    missing = used - servers.keys()
    if missing:
        raise SnapshotError(f"도구가 쓰는 MCP 서버 정보가 없습니다: {', '.join(sorted(missing))}")

    snap = {
        "schema_version": 1,
        "source": {
            "agent_version_id": agent_version["id"],
            "slot_id": slot["id"],
            "candidate_id": candidate["id"],
            "agent_spec_hash": agent_spec_hash(agent_version["model"], agent_version["temperature"],
                                               agent_version["instructions"], spec),
            "component_spec_hash": canonical_hash(comp),
        },
        "model": {"name": model, "provider": agent_version["model_provider"], "temperature": float(temperature)},
        "instructions": instructions,
        "tools": tools,
        "write_tools": sorted(t["name"] for t in tools if t["access"] == "write"),
        "mcp_servers": [servers[n] for n in sorted(used)],
        "runtime": {**DEFAULT_RUNTIME, **spec.get("runtime", {})},
    }
    if search:
        snap["tool_search"] = search
    return contracts.validate("config_snapshot", snap)


def build_config_snapshot(conn, candidate_id: int) -> tuple[dict, str]:
    """④가 부르는 DB 판. (config_snapshot, config_hash) 를 돌려준다. conn = psycopg 연결 (dict_row 아니어도 됨)."""
    cur = conn.cursor()

    def row(table: str, arg: int) -> dict | None:
        """DB 칸 이름(db_names 대응표)을 짧은 이름으로 바꿔 돌려줌 — merge_snapshot 은 예시 JSON 과 같은 모양(id, slot_id, spec …)을 읽음."""
        r = cur.execute(f"SELECT * FROM {db_names.table(table)} WHERE {db_names.col(table, 'id')} = %s", (arg,)).fetchone()
        if r is None:
            return None
        return db_names.plain(table, dict(zip([c.name for c in cur.description], r)))

    cand = row("candidates", candidate_id)
    if cand is None:
        raise SnapshotError(f"후보 {candidate_id} 가 없습니다")
    slot = row("slots", cand["slot_id"])
    av = row("agent_versions", slot["agent_version_id"])
    snap = merge_snapshot(av, slot, cand)
    return snap, canonical_hash(snap)
