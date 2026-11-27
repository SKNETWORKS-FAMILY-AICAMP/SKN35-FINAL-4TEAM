"""① 실험 사전 등록(prereg.process_policy)의 과정 정책 판정. 순수 함수이며 DB 저장은 eng_pipeline 이 합니다.

정책은 문항이 아니라 조직 단위 규칙입니다. 실행 전에 고정되고, 판정은 config_snapshot 의 도구 정의만 믿습니다.

- approved_tools: 칸이 없으면 검사 안 함, [] 이면 외부 도구 호출을 모두 금지. 엔진 내장 도구는 항상 허용.
  MCP 도구는 (서버 이름, 도구 이름, 서버 버전), 서버 없는 자체 도구는 (도구 이름, 도구 정의 해시)로 알아봄.
- read_before_write: 쓰기 호출마다 그보다 앞선 정상 조회 중에 같은 서비스·대상 종류의 read 기능이고
  저장소·대상 ID 가 같은 것이 있어야 함. 대상 ID 가 없는 쓰기(생성)는 create_writes 에 따라 건너뛰거나 판정 불가.

결과는 규칙마다 하나: passed True/False, 또는 None(판정 불가, undecided 에 이유). 적용할 것이 없으면 결과를 만들지 않습니다.
위반이 하나라도 확정되면 다른 호출의 판정 불가와 섞여 있어도 위반입니다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from slotagent.common import contracts
from slotagent.common.hashing import canonical_hash
from slotagent.grading.eng_rules import RulePolicyRequired, call_capability, is_unexecuted

RULES = ("approved_tools", "read_before_write")


@dataclass(frozen=True)
class PolicyResult:
    rule: str
    passed: bool | None  # None = 판정 불가
    evidence: dict = field(default_factory=dict)
    undecided: str | None = None


@dataclass(frozen=True)
class PolicyContext:
    """config_snapshot 에서만 만든 도구 신원·대상 인자. trace 값은 쓰지 않습니다."""

    identity: Mapping[str, dict]
    target_args: Mapping[str, dict]


def policy_context(snapshot: Mapping) -> PolicyContext:
    versions = {server["name"]: server["version"] for server in snapshot.get("mcp_servers", [])}
    identity, targets = {}, {}
    for tool in snapshot["tools"]:
        origin = tool["origin"]
        if origin.startswith("mcp:"):
            server = origin[4:]
            identity[tool["name"]] = {"source": "mcp", "server": server, "version": versions.get(server)}
        else:
            identity[tool["name"]] = {"source": origin, "def_hash": canonical_hash(tool)}
        if tool.get("target_args"):
            targets[tool["name"]] = dict(tool["target_args"])
    return PolicyContext(identity, targets)


def _evidence(seqs, found):
    result = {"span_seqs": sorted(set(seqs)), "found": sorted(set(found))}
    contracts.validate("grading", result, part="condition_evidence")
    return result


def _decide(rule, violations, undecided, applicable):
    if violations:
        return PolicyResult(rule, False, _evidence([s for s, _ in violations], [n for _, n in violations]))
    if undecided:
        return PolicyResult(rule, None, undecided=min(undecided))
    if applicable:
        return PolicyResult(rule, True, _evidence([], []))
    return None


def _approved(entry, name, ident):
    if entry["tool"] not in ("*", name) or entry["source"] != ident["source"]:
        return False
    if ident["source"] == "mcp":
        if entry["server"] != ident["server"]:
            return False
        if "version" in entry:
            if ident["version"] is None:
                raise RulePolicyRequired("tool_version_missing")
            return entry["version"] == ident["version"]
        return True
    return entry.get("def_hash") == ident["def_hash"]


def _check_approved(entries, spans, ctx, tool_access):
    violations, undecided, applicable = [], [], False
    for span in spans:
        name = span["name"]
        if is_unexecuted(span, tool_access, True):
            continue  # 엔진 내장 도구는 필수 절차라 항상 허용, 실행 전에 거절된 호출은 도구를 쓴 것이 아님
        if name not in ctx.identity:
            undecided.append("tool_identity_missing")
            continue
        applicable = True
        unknown = []
        approved = False
        for entry in entries:
            try:
                if _approved(entry, name, ctx.identity[name]):
                    approved = True
                    break
            except RulePolicyRequired as exc:
                unknown.append(exc.code)  # 다른 항목이 승인하면 상관없음
        if approved:
            continue
        if unknown:
            undecided.append(min(unknown))
        else:
            violations.append((span["seq"], name))
    return _decide("approved_tools", violations, undecided, applicable)


def _target(span, capability, ctx):
    """(서비스, 대상 종류, (저장소 매핑 여부, 값), (대상 ID 매핑 여부, 값)). 매핑이 없으면 판정 불가, 값이 없으면 None."""
    parts = capability.split(".")
    args = ctx.target_args.get(span["name"])
    if args is None:
        raise RulePolicyRequired("target_args_missing")
    values = span.get("tool_args", {})

    def value(role):
        if role not in args:
            return None
        found = values.get(args[role])
        return None if found is None or isinstance(found, (dict, list, bool)) else str(found)

    return parts[0], parts[1], ("repo" in args, value("repo")), ("target_id" in args, value("target_id"))


def _check_read_before_write(config, spans, write_seqs, confirmation, tool_access, ctx):
    violations, undecided, applicable = [], [], False
    create = config.get("create_writes", "skip")
    for span in spans:
        if span["seq"] not in write_seqs:
            continue
        try:
            capability = call_capability(span, confirmation, tool_access, True)
            if capability is None:
                continue
            service, kind, repo, target_id = _target(span, capability, ctx)
        except RulePolicyRequired as exc:
            undecided.append(exc.code)
            continue
        if not target_id[0]:
            # 대상 ID 인자가 없는 도구 = 생성 쓰기
            if create == "undecided":
                undecided.append("create_write_policy")
            continue
        applicable = True
        if target_id[1] is None or (repo[0] and repo[1] is None):
            # ID·저장소 인자가 있는 도구인데 값이 없음 → 생성으로 보지 않고 대상 확인 불가
            undecided.append("write_target_missing")
            continue
        proven, unsure = False, False
        for read in spans:
            if read["seq"] >= span["seq"] or "error" in read or read["seq"] in write_seqs:
                continue
            try:
                read_cap = call_capability(read, confirmation, tool_access, True)
            except RulePolicyRequired:
                unsure = True
                continue
            if read_cap is None or read_cap.split(".")[:2] != [service, kind] or not read_cap.endswith(".read"):
                continue
            try:
                _, _, read_repo, read_id = _target(read, read_cap, ctx)
            except RulePolicyRequired:
                unsure = True  # 같은 종류를 읽었지만 대상을 알 수 없음
                continue
            if repo[0] and read_repo[0] and read_repo[1] is not None and read_repo[1] != repo[1]:
                continue  # 다른 저장소를 읽은 것은 확실히 같은 대상이 아님
            if not read_id[0] or read_id[1] is None or (repo[0] and (not read_repo[0] or read_repo[1] is None)):
                unsure = True  # 목록 조회처럼 대상 ID 를 인자로 받지 않는 도구
                continue
            if read_id[1] == target_id[1] and (not repo[0] or read_repo[1] == repo[1]):
                proven = True
                break
        if proven:
            continue
        if unsure:
            undecided.append("read_target_unproven")
        else:
            violations.append((span["seq"], span["name"]))
    return _decide("read_before_write", violations, undecided, applicable)


def check_policy(policy: Mapping | None, trace: dict, *, tool_access, confirmation, policy_ctx: PolicyContext,
                 **_ignored) -> tuple[PolicyResult, ...]:
    """정책 규칙별 결과. policy 가 없으면 ()."""
    if not policy:
        return ()
    spans = sorted((s for s in trace["spans"] if s["kind"] == "tool"), key=lambda s: s["seq"])
    results = []
    if "approved_tools" in policy:
        results.append(_check_approved(policy["approved_tools"], spans, policy_ctx, tool_access))
    if "read_before_write" in policy:
        write_seqs = {w["span_seq"] for w in trace["write_intents"]}
        results.append(
            _check_read_before_write(policy["read_before_write"], spans, write_seqs, confirmation, tool_access, policy_ctx)
        )
    return tuple(r for r in results if r is not None)
