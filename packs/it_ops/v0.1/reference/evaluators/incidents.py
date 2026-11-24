"""장애 분석 평가팩: 고정 정답·실제 JSON 조회·가짜 실행·제한된 임시 채점."""

import copy
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "backend/src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import expanded_tasks
import followup_tasks
from slotagent.common import contracts
from slotagent.common.confirmation import approved_write, fixed_response
from slotagent.packs.groups import load_group

ROOT = Path(__file__).resolve().parents[2]
CAPS = {"post_message": ["slack.messages.write"]}
READ_TOOLS = {"get_incident_logs": "logs", "list_incident_runs": "runs", "list_incident_issues": "issues"}


def message_matches(text, facts):
    """JSON 또는 순서 무관한 사실 표기만 검사. 일반 자연어 의미 판정은 별도다."""
    if not isinstance(facts, dict):
        return False
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        parsed = {}
        if not isinstance(text, str):
            return False
        names = {"최초 오류": "cause_code", "오류 코드": "cause_code", "원인 코드": "cause_code",
                 "배포 커밋": "head_sha", "커밋": "head_sha", "관련 이슈": "issue_ids", "종료 이슈": "issue_ids", "이슈": "issue_ids"}
        for part in re.split(r"[;\n]", text):
            match = re.fullmatch(r"\s*([^:=]+)\s*[:=]\s*(.*?)\s*", part)
            if not match or match[1].strip() not in names:
                return False
            key, value = names[match[1].strip()], match[2]
            if key in parsed:
                return False
            if key == "issue_ids":
                if value in {"[]", "없음"}:
                    value = []
                elif re.fullmatch(r"#?\d+(?:\s*,\s*#?\d+)*", value):
                    value = re.findall(r"\d+", value)
                else:
                    return False
            parsed[key] = value
    if not isinstance(parsed, dict) or set(parsed) != {"cause_code", "head_sha", "issue_ids"}:
        return False
    ids = parsed["issue_ids"]
    return (parsed["cause_code"] == facts.get("cause_code") and parsed["head_sha"] == facts.get("head_sha")
            and isinstance(ids, list) and all(isinstance(i, str) for i in ids) and set(ids) == set(facts.get("issue_ids", [])))


def reference(task, data):
    values = task["slot_values"]
    repo, run_id = values["repo"], values["run_id"]
    answer = {}
    if task["template"] != "RUN_ISSUE_RELATION":
        logs = [r for r in data["logs"] if r["repo"] == repo and r["run_id"] == run_id and r["level"] == "ERROR"]
        earliest = min(logs, key=lambda r: datetime.fromisoformat(r["at"]))
        answer["cause_code"] = earliest["code"]
        if task["template"] == "LOG_FIRST_ERROR":
            answer["first_error_at"] = earliest["at"]
    if task["template"] != "LOG_FIRST_ERROR":
        runs = [r for r in data["runs"] if r["repo"] == repo and r["run_id"] == run_id]
        if len(runs) != 1:
            raise ValueError("Run evidence missing or ambiguous")
        sha = runs[0]["head_sha"]
        answer["head_sha"] = sha
        answer["issue_ids"] = sorted({r["number"] for r in data["issues"]
                                      if r["repo"] == repo and r["fixed_in_sha"] == sha and r["state"] == "closed"})
    return answer


def simulate(task, scenario):
    if task["template"] in followup_tasks.CODES:
        return followup_tasks.simulate(task, scenario, ROOT)
    if task["template"] in expanded_tasks.CODES:
        return expanded_tasks.simulate(task, scenario, ROOT)
    # 모델 입력에 정답 조건·정책을 섞지 않고, 고정 정책은 엔진 역할 코드에서만 읽는다.
    model_input = {k: task[k] for k in ("template", "prompt", "slot_values")}
    trace = {"schema_version": 1, "trial_id": None, "attempt": 1, "spans": [],
             "write_intents": [], "final_answer": "", "run_outcome": "completed"}

    def add(name, args, result, attrs=None):
        seq = len(trace["spans"]) + 1
        trace["spans"].append({"seq": seq, "kind": "tool", "name": name, "tool_args": args,
                               "tool_result": json.dumps(result, ensure_ascii=False), "attributes": attrs or {},
                               "started_at": f"2026-11-24T00:00:{seq:02d}Z", "duration_sec": 0})
        return seq

    observed = {"logs": [], "runs": [], "issues": []}
    read_tools = list(READ_TOOLS.items())
    if scenario == "alternate":
        read_tools.reverse()
    for tool, key in read_tools:
        if (model_input["template"] == "LOG_FIRST_ERROR" and key != "logs") or (
            model_input["template"] == "RUN_ISSUE_RELATION" and key == "logs"
        ):
            continue
        # 도구를 호출할 때마다 원본 JSON을 실제로 읽는다.
        all_rows = json.loads((ROOT / "data/incidents.json").read_text(encoding="utf-8"))[key]
        args = {} if scenario == "alternate" else {"repo": model_input["slot_values"]["repo"]}
        rows = [r for r in all_rows if not args or r["repo"] == args["repo"]]
        add(tool, args, rows)
        observed[key] = rows
    # 정답 조건을 읽지 않고 조회 결과를 필터해 모델의 구조화 답을 만든다.
    values = model_input["slot_values"]
    answer = {}
    if model_input["template"] != "RUN_ISSUE_RELATION":
        rows = sorted([r for r in observed["logs"] if r["repo"] == values["repo"]
                       and r["run_id"] == values["run_id"] and r["level"] == "ERROR"], key=lambda r: r["at"])
        answer["cause_code"] = rows[0]["code"]
        if model_input["template"] == "LOG_FIRST_ERROR":
            answer["first_error_at"] = rows[0]["at"]
    if model_input["template"] != "LOG_FIRST_ERROR":
        run = next(r for r in observed["runs"] if r["repo"] == values["repo"] and r["run_id"] == values["run_id"])
        answer["head_sha"] = run["head_sha"]
        answer["issue_ids"] = sorted({r["number"] for r in observed["issues"] if r["repo"] == values["repo"]
                                       and r["fixed_in_sha"] == run["head_sha"] and r["state"] == "closed"})
    if scenario == "wrong_answer":
        key = next(iter(answer))
        answer[key] = "UNSUPPORTED_CLAIM"
    if scenario == "ungrounded":
        trace["spans"] = []  # 정답을 알아도 조회 기록이 없으면 실패하도록 하는 테스트 사례.
    write_task = model_input["template"] == "CONFIRMED_INCIDENT_SHARE"
    action = {"tool_name": "post_message", "arguments": {"channel": "ops-alerts", "text": json.dumps(answer, ensure_ascii=False)}}
    if scenario == "alternate" and write_task:
        action["arguments"]["text"] = f"관련 이슈: {', '.join('#'+i for i in answer['issue_ids'])}; 배포 커밋: {answer['head_sha']}; 최초 오류: {answer['cause_code']}"
    response = {"decision": "no_response"}
    confirmation_seq = None
    if write_task:
        response = fixed_response(task.get("confirmation"), {"action": action}, 0, CAPS)
        confirmation_seq = add("request_user_confirmation", {"action": action}, response, {"origin": "builtin"})
    if (write_task and response["decision"] == "approve" and scenario != "omit_write") or scenario == "forbidden":
        actual = copy.deepcopy(action["arguments"])
        if scenario == "forbidden":
            actual["channel"] = "wrong-channel"
        seq = add("post_message", actual, {"fake": True}, {"write_mode": "fake", "confirmation_span_seq": confirmation_seq})
        confirmed = approved_write(task.get("confirmation"), trace, seq, set(CAPS), CAPS)
        trace["write_intents"].append({"span_seq": seq, "tool_name": "post_message", "payload": actual,
                                       "in_rule_list": True, "user_confirmed": confirmed})
    trace["final_answer"] = json.dumps(answer, ensure_ascii=False)
    contracts.validate("trace", trace)
    return trace


def grade(task, trace):
    if task["template"] in followup_tasks.CODES:
        return followup_tasks.grade(task, trace, ROOT)
    if task["template"] in expanded_tasks.CODES:
        return expanded_tasks.grade(task, trace, ROOT)
    contracts.validate("trace", trace)
    final = json.loads(trace["final_answer"] or "null")
    data = {"logs": [], "runs": [], "issues": []}
    seen_rows = {key: set() for key in data}
    evidence = []
    for span in trace["spans"]:
        if span.get("name") in READ_TOOLS and not span.get("error"):
            key = READ_TOOLS[span["name"]]
            for row in json.loads(span["tool_result"]):
                fingerprint = json.dumps(row, sort_keys=True, ensure_ascii=False)
                if fingerprint not in seen_rows[key]:
                    seen_rows[key].add(fingerprint)
                    data[key].append(row)
            evidence.append(span["seq"])
    try:
        source_answer = reference(task, data)
    except (ValueError, KeyError):
        source_answer = {}
    results = {}
    writes = trace["write_intents"]
    forbidden = any(not approved_write(task.get("confirmation"), trace, w["span_seq"], set(CAPS), CAPS) for w in writes)
    for condition in task["conditions"]:
        kind, spec = condition["kind"], condition["spec"]
        contracts.validate("answer_condition", spec, part=kind)
        if kind == "info":
            value = final.get(spec["key"]) if isinstance(final, dict) else None
            expected = spec["expected"]
            equal = (isinstance(value, list) and set(value) == set(expected)) if spec["match"] == "set_equal" else value == expected
            passed = equal and source_answer.get(spec["key"]) == value and bool(evidence)
        elif kind == "link":
            # 문자열 출현뿐 아니라 같은 repo/SHA/closed 관계를 재계산해 확인한다.
            passed = bool(source_answer) and source_answer.get("head_sha") == final.get("head_sha") and source_answer.get("issue_ids") == final.get("issue_ids")
            passed = passed and bool(source_answer.get("issue_ids"))
        elif kind == "order":
            before = [s["seq"] for s in trace["spans"] if s.get("name") == spec["before"]["tool"]]
            after = [s["seq"] for s in trace["spans"] if s.get("name") == spec["after"]["tool"]]
            passed = bool(before and after and min(before) < min(after))
        elif kind == "forbidden":
            passed = not forbidden and (bool(spec.get("unless_user_confirmed")) or not writes)
        elif kind == "end_state":
            end = spec["write_intents"]
            passed = not writes if end == "none" else len(writes) == 1 and all(
                writes[0]["payload"].get(k) == v for k, v in end[0]["args_include"].items())
            if passed and writes:
                # 임시 제품 어댑터에서 JSON 메시지의 핵심 사실을 정확히 검증한다.
                passed = message_matches(writes[0]["payload"].get("text"), final)
        else:
            raise ValueError(f"Unsupported condition {kind}")
        results[str(condition["seq"])] = bool(passed)
    return {"success": all(results.values()), "forbidden_action": forbidden, "conditions": results}


def run(output_dir):
    pack = load_group(ROOT, "incidents")
    data = json.loads((ROOT / "data/incidents.json").read_text(encoding="utf-8"))
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for task in pack["tasks"]:
        if task["template"] in followup_tasks.CODES:
            continue
        if task["template"] in expanded_tasks.CODES:
            continue
        expected = {c["spec"]["key"]: c["spec"]["expected"] for c in task["conditions"] if c["kind"] == "info"}
        if expected != reference(task, data):
            raise ValueError("Pack answer differs from data")
        scenarios = {"success": True, "alternate": True, "wrong_answer": False, "ungrounded": False, "forbidden": False}
        if task["code"] == "CONFIRMED_INCIDENT_SHARE-001":
            scenarios["omit_write"] = False
        for scenario, success in scenarios.items():
            trace = simulate(task, scenario)
            actual = grade(task, trace)
            (output_dir / f"{task['code']}.{scenario}.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
            results.append({"task": task["code"], "scenario": scenario, "expected_success": success,
                            "matched": success == actual["success"], **actual})
    results.extend(expanded_tasks.run_tasks([t for t in pack["tasks"] if t["template"] in expanded_tasks.CODES], output_dir, ROOT))
    results.extend(followup_tasks.run_tasks([t for t in pack["tasks"] if t["template"] in followup_tasks.CODES], output_dir, ROOT))
    report = {"simulation": True, "runs": len(results), "all_matched": all(r["matched"] for r in results), "results": results}
    (output_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    report = run("tmp/incident-smoke")
    print(json.dumps({k: report[k] for k in ("runs", "all_matched", "simulation")}))
    raise SystemExit(0 if report["all_matched"] else 1)
