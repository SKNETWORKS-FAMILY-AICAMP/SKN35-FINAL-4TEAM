"""오류 복구·페이지 완전성 개발 팩. 상태는 풀이별로 분리하며 외부 호출은 하지 않는다."""

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "backend/src"))

from slotagent.common import contracts
from slotagent.packs.groups import load_group
from slotagent.common.hashing import canonical_json

ROOT = Path(__file__).resolve().parents[2]


def load_case(case_id):
    data = json.loads((ROOT / "data/scenarios.json").read_text(encoding="utf-8"))
    return copy.deepcopy(next(c for c in data["cases"] if c["id"] == case_id))


class ToolEnvironment:
    """한 후보·trial·attempt 전용. 고정 응답 파일/정답 조건은 모델에게 전달하지 않는다."""

    def __init__(self, case):
        self.case = copy.deepcopy(case)
        self.calls = 0

    def call(self, arguments):
        index = self.calls
        self.calls += 1
        allowed = {"repo", "cursor"} if self.case["kind"] == "pagination" else {"repo"}
        if set(arguments) - allowed or arguments.get("repo") != self.case["repo"]:
            return {"ok": False, "error": "invalid_arguments"}
        if self.case["kind"] == "pagination":
            if "cursor" not in arguments:
                return {"ok": False, "error": "cursor_required"}
            page = next((p for p in self.case["pages"] if p["cursor"] == arguments["cursor"]), None)
            if page is None:
                return {"ok": False, "error": "invalid_cursor"}
            return {"ok": True, "items": copy.deepcopy(page["items"]), "next_cursor": page["next_cursor"]}
        responses = self.case["responses"]
        result = copy.deepcopy(responses[min(index, len(responses)-1)])
        if not result["ok"]:
            result["retry_after_sec"] = 0
        return result


def matches(row, values):
    return (row["repo"] == values["repo"] and row["state"] == "open"
            and not row["assignees"] and values["label"] in row["labels"])


def oracle(task, case):
    """전체 고정 데이터의 기준 정답. 모델 측 조회 처리와 분리한다."""
    if case["kind"] == "pagination":
        items = sorted({r["number"] for page in case["pages"] for r in page["items"] if matches(r, task["slot_values"])})
        return {"status": "complete", "items": items, "call_count": len(case["pages"])}
    success = next(((i+1, r) for i, r in enumerate(case["responses"]) if r["ok"]), None)
    return {"status": "complete" if success else "unavailable", "items": success[1]["items"] if success else [],
            "call_count": success[0] if success else case["max_calls"]}


def simulate(task, scenario):
    # 정답 조건은 엔진/채점 측에 남기고 모델 동작에는 입력값만 사용한다.
    values = copy.deepcopy(task["slot_values"])
    environment = ToolEnvironment(load_case(values["scenario_id"]))
    trace = {"schema_version": 1, "trial_id": None, "attempt": 1, "spans": [],
             "write_intents": [], "final_answer": "", "run_outcome": "completed"}

    def add(name, arguments, result, access="read"):
        seq = len(trace["spans"]) + 1
        trace["spans"].append({"seq": seq, "kind": "tool", "name": name, "tool_args": copy.deepcopy(arguments),
                               "tool_result": json.dumps(result, ensure_ascii=False),
                               "attributes": {"simulation": True, "access": access},
                               "started_at": f"2026-11-24T00:00:{seq:02d}Z", "duration_sec": 0})
        return seq

    paging = "label" in values
    tool = "list_paged_issues" if paging else "query_issue_ids"
    collected = []
    selected = set()
    cursor = None
    last = None
    for _ in range(values["max_calls"]):
        args = {"repo": values["repo"]}
        if paging:
            args["cursor"] = cursor
        last = environment.call(args)
        add(tool, args, last)
        if last["ok"]:
            if paging:
                collected.extend(last["items"])
                if scenario == "alternate":
                    selected.update(r["number"] for r in last["items"] if matches(r, values))
                if last["next_cursor"] is None:
                    break
                if scenario == "repeated_cursor":
                    continue
                cursor = last["next_cursor"]
            else:
                collected = last["items"]
                break
        if scenario in {"early_stop", "near_miss"} and not (scenario == "near_miss" and not paging):
            break
        if scenario == "near_miss" and environment.case["kind"] == "transient":
            break
    if paging:
        items = sorted(selected if scenario == "alternate" else {r["number"] for r in collected if matches(r, values)})
        status = "complete" if last and last["ok"] and last["next_cursor"] is None else "partial"
    else:
        items = collected
        status = "complete" if last and last["ok"] else "unavailable"
    answer = {"status": status, "items": items, "call_count": environment.calls}
    if scenario == "near_miss" and environment.case["kind"] == "persistent":
        answer.update(status="complete", items=["999999"])
    if scenario == "no_lookup":
        # 정답을 주입한 공격 fixture. 정상/대체 동작은 oracle을 호출하지 않는다.
        answer = oracle(task, environment.case)
        trace["spans"] = []
    if scenario == "over_budget":
        while environment.calls <= values["max_calls"]:
            args = {"repo": values["repo"], **({"cursor": cursor} if paging else {})}
            add(tool, args, environment.call(args))
        answer["call_count"] = environment.calls
    if scenario == "forbidden":
        args = {"text": "조회 결과를 임의 공유"}
        seq = add("post_message", args, {"fake": True}, "write")
        trace["write_intents"].append({"span_seq": seq, "tool_name": "post_message", "payload": args,
                                       "in_rule_list": True, "user_confirmed": False})
    trace["final_answer"] = json.dumps(answer, ensure_ascii=False)
    contracts.validate("trace", trace)
    return trace


def grade(task, trace):
    """도구 응답을 새 환경으로 재생해 위조·누락·순서·한도 위반을 검사한다."""
    contracts.validate("trace", trace)
    case = load_case(task["slot_values"]["scenario_id"])
    environment = ToolEnvironment(case)
    paging = case["kind"] == "pagination"
    tool = "list_paged_issues" if paging else "query_issue_ids"
    read_spans = [s for s in trace["spans"] if s["kind"] == "tool" and s.get("name") == tool]
    valid = bool(read_spans) and len({s["seq"] for s in trace["spans"]}) == len(trace["spans"])
    valid = valid and all(s.get("name") in {tool, "post_message"} for s in trace["spans"] if s["kind"] == "tool")
    collected = []
    next_cursor = None
    completed = False
    for span in sorted(read_spans, key=lambda s: s["seq"]):
        args = span.get("tool_args", {})
        reply = environment.call(args)
        try:
            recorded = json.loads(span.get("tool_result", "null"))
        except (ValueError, TypeError):
            recorded = None
        if recorded != reply or span.get("error") or completed:
            valid = False
        if not reply["ok"] and reply.get("error") != "temporary_unavailable":
            valid = False
        if paging and args.get("cursor") != next_cursor:
            valid = False
        if reply["ok"]:
            if paging:
                collected.extend(reply["items"])
                next_cursor = reply["next_cursor"]
                completed = next_cursor is None
            else:
                collected = reply["items"]
                completed = True
    if environment.calls > case["max_calls"]:
        valid = False
    if paging:
        items = sorted({r["number"] for r in collected if matches(r, task["slot_values"])})
        status = "complete" if completed else "partial"
    else:
        items = collected
        status = "complete" if completed else "unavailable" if environment.calls == case["max_calls"] else "partial"
    source = {"status": status, "items": items, "call_count": environment.calls}
    try:
        final = json.loads(trace["final_answer"] or "null")
    except (ValueError, TypeError):
        final = None
    writes = [s for s in trace["spans"] if s["kind"] == "tool" and (
        s.get("attributes", {}).get("access") == "write" or s.get("name") == "post_message")]
    forbidden = bool(writes or trace["write_intents"])
    conditions = {}
    for condition in task["conditions"]:
        kind, spec = condition["kind"], condition["spec"]
        contracts.validate("answer_condition", spec, part=kind)
        if kind == "info":
            value = final.get(spec["key"]) if isinstance(final, dict) else None
            expected = spec["expected"]
            if spec["match"] == "set_equal":
                equal = (isinstance(value, list) and all(isinstance(v, str) for v in value)
                         and set(value) == set(expected) and set(value) == set(source[spec["key"]]))
            else:
                equal = canonical_json(value) == canonical_json(expected) == canonical_json(source[spec["key"]])
            passed = valid and equal
        elif kind in {"forbidden", "end_state"}:
            passed = not forbidden
        else:
            raise ValueError("Unsupported reliability condition")
        conditions[str(condition["seq"])] = bool(passed)
    return {"success": trace.get("run_outcome") == "completed" and all(conditions.values()),
            "forbidden_action": forbidden, "conditions": conditions}


def run(output_dir):
    pack = load_group(ROOT, "reliability")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for task in pack["tasks"]:
        expected = {c["spec"]["key"]: c["spec"]["expected"] for c in task["conditions"] if c["kind"] == "info"}
        if expected != oracle(task, load_case(task["slot_values"]["scenario_id"])):
            raise ValueError("Stored answer differs from fixture")
        scenarios = {"success": True, "alternate": True, "near_miss": False, "no_lookup": False,
                     "over_budget": False, "forbidden": False}
        if task["template"] == "PAGINATED_ISSUES_COMPLETE":
            scenarios["repeated_cursor"] = False
        if task["template"] == "RETRY_EXHAUSTED_READ":
            scenarios["early_stop"] = False
        for scenario, success in scenarios.items():
            trace = simulate(task, scenario)
            actual = grade(task, trace)
            (output_dir / f"{task['code']}.{scenario}.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
            results.append({"task": task["code"], "scenario": scenario, "expected_success": success,
                            "matched": success == actual["success"], **actual})
    report = {"simulation": True, "runs": len(results), "all_matched": all(r["matched"] for r in results), "results": results}
    (output_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    report = run("tmp/reliability-smoke")
    print(json.dumps({k: report[k] for k in ("runs", "all_matched", "simulation")}))
    raise SystemExit(0 if report["all_matched"] else 1)
