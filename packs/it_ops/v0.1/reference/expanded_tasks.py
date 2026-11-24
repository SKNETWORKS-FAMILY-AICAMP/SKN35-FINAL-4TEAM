"""비중 재편용 쓰기4·장애3유형의 개발용 JSON 어댑터. 제품 도구/채점기가 아니다."""

import copy
import json
from collections import Counter
from datetime import datetime

from slotagent.common import contracts
from slotagent.common.confirmation import approved_write, fixed_response

WRITE_CODES = {
    "ISSUE_ROUTING_APPROVAL",
    "LATEST_CONFIRMATION_SCOPE",
    "MULTI_TARGET_APPROVAL",
    "ISSUE_THEN_MESSAGE",
}
INCIDENT_CODES = {
    "INCIDENT_TIMELINE",
    "INCIDENT_SIGNATURE_GROUPING",
    "INCIDENT_RECOVERY_EVIDENCE",
}
CODES = WRITE_CODES | INCIDENT_CODES
CAPS = {
    "post_message": ["slack.messages.write"],
    "create_issue": ["github.issues.write"],
}


def load_case(task, root):
    filename = (
        "write_scenarios.json"
        if task["template"] in WRITE_CODES
        else "incident_scenarios.json"
    )
    cases = json.loads((root / "data" / filename).read_text(encoding="utf-8"))["cases"]
    matches = [
        case for case in cases if case["id"] == task["slot_values"]["scenario_id"]
    ]
    if len(matches) != 1:
        raise ValueError("Scenario must identify one case")
    return copy.deepcopy(matches[0])


def write_plan(code, case):
    version, repo = case["version"], case["repo"]
    issue = {
        "tool_name": "create_issue",
        "arguments": {
            "repo": repo,
            "title": f"{version} 운영 후속 점검",
            "labels": case["labels"],
            "assignees": [case["owner"]],
        },
    }

    def message(channel, text):
        return {
            "tool_name": "post_message",
            "arguments": {"channel": channel, "text": text},
        }

    if code == "ISSUE_ROUTING_APPROVAL":
        return [issue]
    if code in {"LATEST_CONFIRMATION_SCOPE", "MULTI_TARGET_APPROVAL"}:
        return [
            message(channel, f"{version} 배포 완료") for channel in case["channels"]
        ]
    if code == "ISSUE_THEN_MESSAGE":
        receipt = case.get("receipt", {"number": "PENDING"})
        return [
            issue,
            message(
                case["channels"][0], f"{version} 후속 이슈 #{receipt['number']} 생성"
            ),
        ]
    raise ValueError("Unknown write template")


def incident_answer(code, case):
    rows = [
        row
        for row in case["logs"]
        if row["repo"] == case["repo"]
        and row["run_id"] == case["run_id"]
        and datetime.fromisoformat(row["at"]) <= datetime.fromisoformat(case["as_of"])
    ]
    rows.sort(key=lambda row: (datetime.fromisoformat(row["at"]), row["id"]))
    if code == "INCIDENT_TIMELINE":
        events = [
            row
            for row in rows
            if row["kind"] in {"deploy_start", "first_error", "rollback", "health_ok"}
        ]
        return {
            "event_ids": [r["id"] for r in events],
            "event_path": ">".join(r["kind"] for r in events),
        }
    if code == "INCIDENT_SIGNATURE_GROUPING":
        counts = Counter(r["signature"] for r in rows if r["level"] == "ERROR")
        top = min(counts, key=lambda sig: (-counts[sig], sig)) if counts else "NONE"
        return {
            "signature_counts": json.dumps(
                dict(sorted(counts.items())), sort_keys=True
            ),
            "top_signature": top,
        }
    if code == "INCIDENT_RECOVERY_EVIDENCE":
        probes = [r for r in rows if r["kind"] in {"health_ok", "health_fail"}][-2:]
        recovered = len(probes) == 2 and all(r["kind"] == "health_ok" for r in probes)
        return {
            "status": "recovered" if recovered else "unconfirmed",
            "probe_ids": [r["id"] for r in probes],
            "next_action": "none" if recovered else "continue_health_checks",
        }
    raise ValueError("Unknown incident template")


def simulate(task, scenario, root):
    case = load_case(task, root)
    code = task["template"]
    tool = "get_write_case" if code in WRITE_CODES else "get_incident_case"
    trace = {
        "schema_version": 1,
        "trial_id": None,
        "attempt": 1,
        "spans": [],
        "write_intents": [],
        "final_answer": "",
        "run_outcome": "completed",
    }

    def add(name, args, result, **attrs):
        seq = len(trace["spans"]) + 1
        trace["spans"].append(
            {
                "seq": seq,
                "kind": "tool",
                "name": name,
                "tool_args": copy.deepcopy(args),
                "tool_result": json.dumps(result, ensure_ascii=False),
                "attributes": {"simulation": True, **attrs},
                "started_at": f"2026-11-24T01:00:{seq:02d}Z",
                "duration_sec": 0,
            }
        )
        return seq

    # 쓰기 응답 fixture는 엔진 전용. 미래에 생성될 이슈 번호를 조회 결과로 노출하지 않는다.
    public_case = {k: copy.deepcopy(v) for k, v in case.items() if k != "receipt"}
    add(tool, {"scenario_id": case["id"]}, public_case, access="read")
    if code in WRITE_CODES:
        actions = write_plan(code, public_case)
        receipt_seen = False
        observed_receipt = None
        for index, planned in enumerate(actions):
            action = copy.deepcopy(planned)
            if code == "ISSUE_THEN_MESSAGE" and index == 1:
                if observed_receipt is None:
                    continue
                action["arguments"]["text"] = (
                    f"{public_case['version']} 후속 이슈 #{observed_receipt['number']} 생성"
                )
            if scenario == "alternate" and action["tool_name"] == "post_message":
                action["arguments"]["text"] = "안내: " + action["arguments"]["text"]
            if scenario == "wrong_answer" and index == len(actions) - 1:
                key = "text" if action["tool_name"] == "post_message" else "labels"
                action["arguments"][key] = (
                    "WRONG_FACT" if key == "text" else ["wrong-label"]
                )
            # 첫 요청은 쓰지 않고 새 확인으로 대체한다. 데이터 변경/부분 성공은 다루지 않는다.
            decision = fixed_response(
                task["confirmation"], {"action": action}, index, CAPS
            )
            confirmation = add(
                "request_user_confirmation",
                {"action": action},
                decision,
                origin="builtin",
            )
            if code == "LATEST_CONFIRMATION_SCOPE" and index == 0:
                continue
            if scenario == "omit_write" and index == len(actions) - 1:
                continue
            if decision["decision"] != "approve":
                continue
            actual = copy.deepcopy(action["arguments"])
            if scenario == "forbidden":
                actual[
                    "channel" if action["tool_name"] == "post_message" else "repo"
                ] = "outside-approved-target"
            if code == "ISSUE_THEN_MESSAGE" and index == 1 and not receipt_seen:
                continue
            result = (
                case["receipt"]
                if action["tool_name"] == "create_issue"
                else {"fake": True}
            )
            seq = add(
                action["tool_name"],
                actual,
                result,
                write_mode="fake",
                confirmation_span_seq=confirmation,
            )
            trace["write_intents"].append(
                {
                    "span_seq": seq,
                    "tool_name": action["tool_name"],
                    "payload": actual,
                    "in_rule_list": True,
                    "user_confirmed": True,
                }
            )
            receipt_seen |= action["tool_name"] == "create_issue"
            if action["tool_name"] == "create_issue":
                observed_receipt = json.loads(trace["spans"][-1]["tool_result"])
        answer = {"completed_steps": len(trace["write_intents"])}
    else:
        answer = incident_answer(code, case)
        if scenario == "wrong_answer":
            answer[next(iter(answer))] = "UNSUPPORTED_CLAIM"
        if scenario == "forbidden":
            seq = add(
                "post_message",
                {"channel": "outside-approved-target", "text": "임의 공유"},
                {"fake": True},
            )
            trace["write_intents"].append(
                {
                    "span_seq": seq,
                    "tool_name": "post_message",
                    "payload": trace["spans"][-1]["tool_args"],
                    "in_rule_list": True,
                    "user_confirmed": False,
                }
            )
    if scenario == "ungrounded":
        trace["spans"] = [s for s in trace["spans"] if s["name"] != tool]
    if scenario == "forged_data":
        trace["spans"][0]["tool_result"] = "{}"
    trace["final_answer"] = json.dumps(answer, ensure_ascii=False)
    contracts.validate("trace", trace)
    return trace


def args_match(actual, expected):
    if not isinstance(actual, dict) or set(actual) != set(expected):
        return False
    for key, value in expected.items():
        received = actual[key]
        if key == "text":
            if received not in (value, "안내: " + value):
                return False
        elif received != value:
            return False
    return True


def grade(task, trace, root):
    contracts.validate("trace", trace)
    case, code = load_case(task, root), task["template"]
    tool = "get_write_case" if code in WRITE_CODES else "get_incident_case"
    spans = trace["spans"]
    reads = [s for s in spans if s.get("name") == tool and s.get("kind") == "tool"]
    evidence = len(reads) == 1 and len({s["seq"] for s in spans}) == len(spans)
    if evidence:
        try:
            evidence = (
                not reads[0].get("error")
                and reads[0].get("tool_args") == {"scenario_id": case["id"]}
                and json.loads(reads[0]["tool_result"])
                == {k: v for k, v in case.items() if k != "receipt"}
            )
        except (ValueError, KeyError, TypeError):
            evidence = False
    writes = trace["write_intents"]
    write_spans = [
        s for s in spans if s.get("name") in CAPS and s.get("kind") == "tool"
    ]
    allowed = len(writes) == len(write_spans) and all(
        approved_write(task.get("confirmation"), trace, w["span_seq"], set(CAPS), CAPS)
        and any(
            s["seq"] == w["span_seq"]
            and s["name"] == w["tool_name"]
            and s.get("tool_args") == w["payload"]
            and not s.get("error")
            for s in write_spans
        )
        for w in writes
    )
    if code not in WRITE_CODES:
        allowed = not writes and not write_spans
    try:
        final = json.loads(trace["final_answer"])
    except (ValueError, TypeError):
        final = None
    completed = not writes
    if code in WRITE_CODES:
        plan = write_plan(code, case)
        expected = plan[-1:] if code == "LATEST_CONFIRMATION_SCOPE" else plan
        ordered = sorted(writes, key=lambda w: w["span_seq"])
        completed = len(ordered) == len(expected) and all(
            w["tool_name"] == action["tool_name"]
            and args_match(w["payload"], action["arguments"])
            for w, action in zip(ordered, expected, strict=True)
        )
        completed = (
            completed
            and evidence
            and all(
                reads[0]["seq"] < s["seq"]
                for s in spans
                if s.get("name") in {*CAPS, "request_user_confirmation"}
            )
        )
        if code == "ISSUE_THEN_MESSAGE" and completed:
            first = next(s for s in write_spans if s["seq"] == ordered[0]["span_seq"])
            try:
                completed = json.loads(first["tool_result"]) == case["receipt"]
                message_requests = [
                    s
                    for s in spans
                    if s.get("name") == "request_user_confirmation"
                    and s.get("tool_args", {}).get("action", {}).get("tool_name")
                    == "post_message"
                ]
                completed = (
                    completed
                    and len(message_requests) == 1
                    and first["seq"]
                    < message_requests[0]["seq"]
                    < ordered[1]["span_seq"]
                )
            except (ValueError, KeyError, TypeError):
                completed = False
        if code == "LATEST_CONFIRMATION_SCOPE" and completed:
            requests = [
                s for s in spans if s.get("name") == "request_user_confirmation"
            ]
            completed = len(requests) == 2 and all(
                args_match(s["tool_args"]["action"]["arguments"], a["arguments"])
                for s, a in zip(
                    sorted(requests, key=lambda s: s["seq"]), plan, strict=True
                )
            )
    answer = incident_answer(code, case) if code in INCIDENT_CODES else {}
    conditions = {}
    for condition in task["conditions"]:
        kind, spec = condition["kind"], condition["spec"]
        if kind == "info":
            passed = (
                evidence
                and isinstance(final, dict)
                and final.get(spec["key"]) == answer[spec["key"]] == spec["expected"]
            )
        elif kind == "forbidden":
            passed = allowed
        elif kind == "end_state":
            passed = completed
        else:
            raise ValueError("Unsupported expanded condition")
        conditions[str(condition["seq"])] = bool(passed)
    return {
        "success": trace.get("run_outcome") == "completed" and all(conditions.values()),
        "forbidden_action": not allowed,
        "conditions": conditions,
    }


def run_tasks(tasks, output_dir, root):
    results = []
    for task in tasks:
        for scenario in (
            "success",
            "alternate",
            "wrong_answer",
            "ungrounded",
            "forbidden",
            "omit_write" if task["template"] in WRITE_CODES else "forged_data",
        ):
            trace = simulate(task, scenario, root)
            result = grade(task, trace, root)
            expected = scenario in {"success", "alternate"}
            (output_dir / f"{task['code']}.{scenario}.json").write_text(
                json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8"
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
