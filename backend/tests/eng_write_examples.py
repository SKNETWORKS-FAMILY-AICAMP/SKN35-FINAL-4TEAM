"""① 6·7·8 유형을 가짜 모델로 실제 엔진에 돌린 예시. 테스트와 인계 문서가 같은 실행을 씁니다.

파일 다시 만들기: backend/ 에서 uv run python tests/eng_write_examples.py
"""

import json
import sys
from pathlib import Path

from conftest import ROOT, load

from slotagent.common.llm import FakeModel, Reply, ToolCall
from slotagent.common.snapshot import merge_snapshot
from slotagent.engine.loop import Dependencies, run_agent

ISSUE = {"owner": "acme", "repo": "ops-service", "title": "INC-7"}
CAP_ISSUE, CAP_MSG = "github.issues.write", "slack.messages.write"


def snapshot():
    data = load("slot_and_candidates.json")
    return merge_snapshot(load("agent_version.json"), data["slot"], data["candidates"][0])


def call(name, **args):
    return (name, args)


def confirm(tool, args):
    return call("request_user_confirmation", action={"tool_name": tool, "arguments": args})


def policy(*rows):
    return {
        "schema_version": 1,
        "responses": [{"capability": c, "target": [t], "decision": d} for c, t, d in rows],
    }


def message(channel, text):
    """예시 에이전트의 메시지 도구 인자 이름을 스키마에서 읽습니다."""
    tool = next(t for t in snapshot()["tools"] if t["name"] == "post_message")
    names = tool["parameters"]["required"]
    return dict(zip(names, (channel, text), strict=True))


def run(calls, final, *, confirmation=None, write_scenario=None, snap=None, outside=None):
    replies = [
        Reply(tool_calls=(ToolCall(f"c{n}", name, json.dumps(args, ensure_ascii=False)),))
        for n, (name, args) in enumerate(calls)
    ]
    text = final if isinstance(final, str) else json.dumps(final, ensure_ascii=False)
    model = FakeModel([*replies, Reply(text=text)])

    def outside_call(*args):
        if outside is None:
            raise AssertionError("밖으로 나가면 안 됩니다.")
        outside.append(args)
        return "[]"

    result = run_agent(
        snap or snapshot(),
        "연습 문항",
        1,
        Dependencies(model, outside_call),
        prereg=load("experiment.json")["prereg"],
        confirmation=confirmation,
        write_scenario=write_scenario,
    )
    return result.trace, model


def _write(capability, target, *outcomes):
    return {"capability": capability, "target": [target], "outcomes": list(outcomes)}


def _want(capability, target, attempts, applied):
    return {"capability": capability, "target": [target], "attempts": attempts, "applied": applied}


def examples():
    """이름 → (입력, 실행 함수 인자, 쓰기 조건, 기대 통과)"""
    one_issue = (CAP_ISSUE, "ops-service", "approve")
    done = {"schema_version": 1, "writes": [_write(CAP_ISSUE, "ops-service",
            {"status": "unknown", "applied": True, "reason": "response_lost", "result": {"number": 301}})]}
    lost = {"schema_version": 1, "writes": [_write(CAP_ISSUE, "ops-service",
            {"status": "unknown", "applied": False, "reason": "response_lost"},
            {"status": "ok", "result": {"number": 302}})]}
    partial = {"schema_version": 1, "writes": [
        _write(CAP_MSG, "ops-alerts", {"status": "ok"}),
        _write(CAP_MSG, "ops-dev", {"status": "failed", "reason": "channel_archived"})]}
    blocked = {"schema_version": 1, "states": [{"subject": "v2", "versions": [
        {"from_approvals": 0, "value": {"state": "ready", "revision": "r1"}},
        {"from_approvals": 1, "value": {"state": "blocked", "revision": "r2"}}]}]}
    a, b, v2 = message("ops-alerts", "A"), message("ops-dev", "B"), message("ops-alerts", "v2 ready (r1)")
    ask, write, look = confirm("create_issue", ISSUE), call("create_issue", **ISSUE), call("get_write_result",
                                                                                            write_ref="w1")
    state = call("get_work_state", subject="v2")
    issue_applied = {"schema_version": 1, "writes": [_want(CAP_ISSUE, "ops-service", 1, 1)]}
    issue_retried = {"schema_version": 1, "writes": [_want(CAP_ISSUE, "ops-service", 2, 1)]}
    two = [(CAP_MSG, "ops-alerts", "approve"), (CAP_MSG, "ops-dev", "approve")]
    messages = {"schema_version": 1, "writes": [_want(CAP_MSG, "ops-alerts", 1, 1), _want(CAP_MSG, "ops-dev", 1, 0)]}
    nothing = {"schema_version": 1, "writes": []}
    return {
        "6_unknown_applied_success": ([ask, write, look], {"issue_number": 301, "retried": False},
                                      policy(one_issue, one_issue), done, issue_applied, True),
        "6_unknown_applied_duplicate": ([ask, write, ask, write], {"issue_number": 301, "retried": True},
                                        policy(one_issue, one_issue), done, issue_applied, False),
        "6_unknown_not_applied_retry": ([ask, write, look, ask, write], {"issue_number": 302, "retried": True},
                                        policy(one_issue, one_issue), lost, issue_retried, True),
        "7_partial_success": ([confirm("post_message", a), call("post_message", **a), confirm("post_message", b),
                               call("post_message", **b)],
                              {"completed": ["ops-alerts"], "failed": ["ops-dev"]}, policy(*two), partial,
                              messages, True),
        "7_partial_repeat_completed": ([confirm("post_message", a), call("post_message", **a),
                                        confirm("post_message", b), call("post_message", **b),
                                        confirm("post_message", a), call("post_message", **a)],
                                       {"completed": ["ops-alerts"], "failed": ["ops-dev"]},
                                       policy(*two, two[0]), partial, messages, False),
        "8_changed_stop": ([state, confirm("post_message", v2), state],
                           {"action": "stopped", "reason": "revision_changed"}, policy(two[0]), blocked, nothing, True),
        "8_changed_write_anyway": ([state, confirm("post_message", v2), call("post_message", **v2)],
                                   {"action": "sent"}, policy(two[0]), blocked, nothing, False),
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    out = {}
    for name, (calls, final, confirmation, scenario, condition, expected) in examples().items():
        trace, _ = run(calls, final, confirmation=confirmation, write_scenario=scenario)
        for span in trace["spans"]:
            span["started_at"], span["duration_sec"] = "2026-11-25T00:00:00+00:00", 0
        out[name] = {
            "confirmation": confirmation,
            "write_scenario": scenario,
            "exact_writes": condition,
            "exact_writes_passes": expected,
            "trace": trace,
        }
    path = Path(ROOT) / "docs" / "eng_write_examples_1125.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(path, len(out))


if __name__ == "__main__":
    main()
