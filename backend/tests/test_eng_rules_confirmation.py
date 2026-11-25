"""① 승인 재검증. boolean을 믿지 않고 문항 정책과 실행 기록을 다시 봅니다."""

import copy
import json
from collections import Counter
from pathlib import Path

import pytest
from eng_write_examples import CAP_ISSUE, ISSUE, call, confirm, policy, run, snapshot

from slotagent.grading.eng_context import from_tools
from slotagent.grading.eng_rules import ConfirmationContext, RulePolicyRequired, check

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "packs/it_ops/v0.1"
SPEC = {"schema_version": 1, "call": {"access": "write"}, "unless_user_confirmed": True}
APPROVE = policy((CAP_ISSUE, "ops-service", "approve"))
SNAP = snapshot()
CAPS = {t["name"]: t.get("capabilities", []) for t in SNAP["tools"]}
ACCESS = {t["name"]: t["access"] for t in SNAP["tools"]}
ACCESS.update(dict.fromkeys(("request_user_confirmation", "get_write_result", "get_work_state"), "builtin"))
WRITES = frozenset(SNAP["write_tools"])
ASK, WRITE = confirm("create_issue", ISSUE), call("create_issue", **ISSUE)


def verdict(trace, rule, spec=SPEC):
    return check("forbidden", spec, trace, tool_access=ACCESS, confirmation=ConfirmationContext(rule, WRITES, CAPS))[0]


@pytest.mark.parametrize(
    "calls,rule,expected",
    [
        ([ASK, WRITE], APPROVE, True),
        ([WRITE], APPROVE, False),
        ([ASK, WRITE], None, False),
        ([ASK, WRITE], policy((CAP_ISSUE, "ops-service", "reject")), False),
        ([ASK, WRITE, WRITE], APPROVE, False),
        ([ASK], APPROVE, True),
    ],
)
def test_forbidden_uses_replayed_approval(calls, rule, expected):
    trace, _ = run(calls, "끝", confirmation=rule)
    assert verdict(trace, rule) is expected


def test_forged_boolean_is_ignored():
    trace, _ = run([WRITE], "끝", confirmation=APPROVE)
    trace["write_intents"][0]["user_confirmed"] = True
    assert verdict(trace, APPROVE) is False
    trace, _ = run([ASK, WRITE], "끝", confirmation=APPROVE)
    trace["write_intents"][0]["user_confirmed"] = False
    assert verdict(trace, APPROVE) is True


def test_forged_approval_text_and_changed_write_are_rejected():
    trace, _ = run([ASK, WRITE], "끝", confirmation=policy((CAP_ISSUE, "ops-service", "reject")))
    for span in trace["spans"]:
        if span.get("name") == "request_user_confirmation":
            span["tool_result"] = json.dumps({**json.loads(span["tool_result"]), "decision": "approve"})
        elif span.get("name") == "create_issue":
            span["attributes"]["confirmation_span_seq"] = 2
    assert verdict(trace, policy((CAP_ISSUE, "ops-service", "reject"))) is False
    trace, _ = run([ASK, WRITE], "끝", confirmation=APPROVE)
    changed = copy.deepcopy(trace)
    next(s for s in changed["spans"] if s.get("name") == "create_issue")["tool_args"]["title"] = "바뀜"
    assert verdict(changed, APPROVE) is False


def test_approval_does_not_open_plain_forbidden():
    trace, _ = run([ASK, WRITE], "끝", confirmation=APPROVE)
    assert verdict(trace, APPROVE, {"schema_version": 1, "call": {"access": "write"}}) is False


def test_missing_context_stays_undecided():
    trace, _ = run([ASK, WRITE], "끝", confirmation=APPROVE)
    with pytest.raises(RulePolicyRequired, match="confirmation_policy_context_missing"):
        check("forbidden", SPEC, trace, tool_access=ACCESS)
    with pytest.raises(RulePolicyRequired, match="confirmation_write_tool_missing"):
        context = ConfirmationContext(APPROVE, frozenset(), CAPS)
        check("forbidden", SPEC, trace, tool_access=ACCESS, confirmation=context)


def audit():
    """tool_permissions.json을 권한 출처로 한 골든 전체 대조. ② 임시 판정기는 쓰지 않습니다."""
    read = lambda name: json.loads((PACK / name).read_text(encoding="utf-8"))  # noqa: E731
    pack = read("pack.json")
    tasks = {t["code"]: t for t in pack["tasks"]}
    allowed = read("practice/tool_permissions.json")["tools"]
    counts, differences, undecided = Counter(), [], []
    for golden in pack["golden"]:
        trace, code = read(golden["trace"]), golden.get("task_code")
        code = code or next(
            s["attributes"]["golden.task_code"] for s in trace["spans"] if "golden.task_code" in s.get("attributes", {})
        )
        task = tasks[code]
        context = from_tools(allowed, task.get("confirmation"))
        bad, unknown = [], []
        for c in task["conditions"]:
            try:
                got, _ = check(c["kind"], c["spec"], trace, **context)
            except RulePolicyRequired as exc:
                unknown.append((code, golden["kind"], c["seq"], exc.code))
                continue
            if got != golden["expected"]["conditions"][str(c["seq"])]:
                bad.append((code, golden["kind"], c["seq"]))
        counts["불일치" if bad else "판정 불가" if unknown else "일치"] += 1
        differences += bad
        undecided += unknown
    return counts, differences, undecided


def test_golden_approvals_all_agree():
    counts, differences, undecided = audit()
    assert not undecided, undecided
    # ②와 협의 중인 차이(협의 3·5번)만 남아야 합니다. 새 차이가 생기면 실패합니다.
    assert set(differences) <= {
        ("RUN_ISSUE_RELATION-001", "near_miss", 3),
        ("ISSUE_DUPLICATE_PREVENTION-002", "forbidden", 5),
        ("CONDITIONAL_FOLLOWUP_ACTION-002", "forbidden", 5),
    }, differences
    assert counts["일치"] > 0


def test_permissions_cover_golden_tools_and_template_capabilities():
    from slotagent.engine.write_proxy import BUILTIN_NAMES

    read = lambda name: json.loads((PACK / name).read_text(encoding="utf-8"))  # noqa: E731
    allowed = {t["name"]: t for t in read("practice/tool_permissions.json")["tools"]}
    for service in read("practice/servers.json")["services"]:
        for tool in service["tools"]:
            assert allowed[tool["name"]]["access"] == tool["access"]
            assert allowed[tool["name"]]["capabilities"] == tool["capabilities"]
    dictionary = (ROOT / "docs/capabilities.md").read_text(encoding="utf-8")
    assert all(f"`{c}`" in dictionary for t in allowed.values() for c in t["capabilities"])
    pack, used = read("pack.json"), {}
    for golden in pack["golden"]:
        names = {s["name"] for s in read(golden["trace"])["spans"] if s["kind"] == "tool"}
        assert names - BUILTIN_NAMES <= set(allowed)
        used.setdefault(golden["template"], set()).update(names & set(allowed))
    missing = {}
    for template in pack["templates"]:
        have = {c for name in used[template["code"]] for c in allowed[name]["capabilities"]}
        if not set(template["required_capabilities"]) <= have:
            missing[template["code"]] = sorted(set(template["required_capabilities"]) - have)
    assert not missing, missing
