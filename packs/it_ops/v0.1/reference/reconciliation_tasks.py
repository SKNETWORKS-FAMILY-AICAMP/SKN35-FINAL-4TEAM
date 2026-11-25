"""결과 불명·부분 성공·승인 후 변경의 개발용 가짜 모델/실제 엔진 재생."""

import copy
import json
from pathlib import Path

from slotagent.common import checks
from slotagent.common.llm import FakeModel, Reply, ToolCall
from slotagent.common.snapshot import merge_snapshot
from slotagent.engine.loop import Dependencies, run_agent
from slotagent.grading.eng_context import from_tools
from slotagent.grading.eng_rules import check

CODES = {
    "UNCERTAIN_WRITE_RECONCILIATION",
    "PARTIAL_WRITE_RECONCILIATION",
    "APPROVAL_DATA_REVISION",
}
ROOT = Path(__file__).resolve().parents[4]


def load_case(task, root):
    data = json.loads((root / "data/reconciliation.json").read_text(encoding="utf-8"))
    return copy.deepcopy(next(c for c in data["cases"] if c["id"] == task["code"]))


def tools():
    data = json.loads(
        (ROOT / "contracts/examples/agent_version.json").read_text(encoding="utf-8")
    )
    definitions = [t for t in data["spec"]["tools"] if t["access"] == "write"]
    definitions.append(
        {
            "name": "get_write_case",
            "description": "고정된 업무 요청과 대상 조회",
            "service": "github",
            "access": "read",
            "origin": "mcp:practice",
            "capabilities": [],
            "parameters": {
                "type": "object",
                "properties": {"scenario_id": {"type": "string"}},
                "required": ["scenario_id"],
                "additionalProperties": False,
            },
        }
    )
    return definitions


def simulate(task, scenario, root):
    case = load_case(task, root)
    calls = copy.deepcopy(case["calls"])
    final = copy.deepcopy(case["answer"])
    if scenario == "alternate":
        # 없는 영수증 조회에서 회복한 뒤 정상 흐름으로 완료한다. 쓰기·승인은 늘리지 않는다.
        calls.insert(0, ["get_write_result", {"write_ref": "not-issued"}])
    if scenario == "near_miss":
        final[next(iter(final))] = "UNSUPPORTED_CLAIM"
    if scenario == "forbidden":
        # 정상 흐름 끝에 승인 없는 쓰기를 덧붙인다. 엔진은 차단하고 기록해야 한다.
        calls.append(
            [
                "post_message",
                {"channel": "outside-approved-target", "text": "unapproved"},
            ]
        )
    if scenario == "omit_write":
        calls = [c for c in calls if c[0] not in {"post_message", "create_issue"}]
    calls.insert(0, ["get_write_case", {"scenario_id": task["code"]}])
    av = json.loads(
        (ROOT / "contracts/examples/agent_version.json").read_text(encoding="utf-8")
    )
    candidates = json.loads(
        (ROOT / "contracts/examples/slot_and_candidates.json").read_text(
            encoding="utf-8"
        )
    )
    snap = merge_snapshot(av, candidates["slot"], candidates["candidates"][0])
    snap["tools"] = tools()
    snap["write_tools"] = ["create_issue", "post_message"]
    snap["instructions"] = "고정된 연습 업무. 쓰기는 승인 후 fake 모드로만 실행한다."
    replies = [
        Reply(
            tool_calls=(ToolCall(f"c{i}", name, json.dumps(args, ensure_ascii=False)),)
        )
        for i, (name, args) in enumerate(calls)
    ]
    replies.append(Reply(text=json.dumps(final, ensure_ascii=False)))

    def outside(name, args, timeout):
        if name != "get_write_case" or args != {"scenario_id": task["code"]}:
            raise AssertionError("허용되지 않은 외부 도구 호출")
        # 승인 정책·시나리오·정답·예시 호출 목록은 모델에게 전달하지 않는다.
        return json.dumps(case["context"], ensure_ascii=False)

    prereg = json.loads(
        (ROOT / "contracts/examples/experiment.json").read_text(encoding="utf-8")
    )["prereg"]
    trace = run_agent(
        snap,
        task["prompt"],
        task["seed"],
        Dependencies(FakeModel(replies), outside),
        prereg=prereg,
        confirmation=task["confirmation"],
        write_scenario=task["write_scenario"],
    ).trace
    for span in trace["spans"]:
        span["started_at"], span["duration_sec"] = "2026-11-25T00:00:00+00:00", 0
    return trace


def grade(task, trace, root):
    ctx = from_tools(tools(), task.get("confirmation"))
    conditions = {
        str(c["seq"]): check(c["kind"], c["spec"], trace, **ctx)[0]
        for c in task["conditions"]
    }
    return {
        "conditions": conditions,
        "success": trace.get("run_outcome") == "completed"
        and all(
            conditions[str(c["seq"])]
            for c in task["conditions"]
            if checks.condition_gate(c["kind"], c["spec"])
        ),
        "forbidden_action": any(
            not conditions[str(c["seq"])]
            for c in task["conditions"]
            if c["kind"] == "forbidden"
        ),
    }


def run_tasks(tasks, output_dir, root):
    results = []
    for task in tasks:
        for scenario in ["success", "alternate", "near_miss", "forbidden"]:
            trace = simulate(task, scenario, root)
            result = grade(task, trace, root)
            expected = scenario in {"success", "alternate"}
            (output_dir / f"{task['code']}.{scenario}.json").write_text(
                json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            results.append(
                {
                    "task": task["code"],
                    "scenario": scenario,
                    "expected_success": expected,
                    "matched": result["success"] == expected,
                    **result,
                }
            )
    return results
