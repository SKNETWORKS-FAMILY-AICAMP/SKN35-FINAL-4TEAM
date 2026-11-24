"""정보 충돌 팩의 고정 근거·가짜 실행·구조화 답 검사. 실제 모델은 호출하지 않는다."""

import copy
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "backend/src"))

from slotagent.common import contracts
from slotagent.packs.groups import load_group
from slotagent.common.hashing import canonical_json

ROOT = Path(__file__).resolve().parents[2]
PRIMARY = {"deployment_api", "deployment_replica"}


def load_case(case_id):
    data = json.loads((ROOT / "data/evidence.json").read_text(encoding="utf-8"))
    return copy.deepcopy(next(case for case in data["cases"] if case["id"] == case_id))


def relevant(record, values):
    return all(record.get(key) == values[key] for key in ("repo", "run_id", "environment"))


def oracle(values, facts, evidence):
    as_of = datetime.fromisoformat(values["as_of"])
    start = as_of - timedelta(hours=values["max_age_hours"])
    primary = [r for r in evidence if relevant(r, values) and r["field"] == "version" and r["source"] in PRIMARY
               and start <= datetime.fromisoformat(r["observed_at"]) <= as_of]
    versions = sorted({r["value"] for r in primary})
    status = "insufficient" if not versions else "conflict" if len(versions) > 1 else "resolved"
    if not relevant(facts, values):
        raise ValueError("Facts refer to a different execution")
    return {"status": status, "selected_version": versions[0] if status == "resolved" else "UNRESOLVED",
            "known_status": facts["status"], "primary_versions": versions,
            "evidence_ids": sorted({r["evidence_id"] for r in primary}),
            "missing_fields": [] if status == "resolved" else ["version"],
            "next_action": {"conflict": "reconcile_primary_sources", "insufficient": "request_primary_version",
                            "resolved": "none"}[status]}


def query(case_id, tool, arguments):
    case = load_case(case_id)
    if tool not in {"get_run_facts", "list_version_evidence"}:
        raise ValueError("Unknown evidence tool")
    expected_keys = {"repo", "run_id", "environment"}
    if set(arguments) != expected_keys or not relevant(case["facts"], arguments):
        raise ValueError("Invalid execution selector")
    return case["facts"] if tool == "get_run_facts" else case["evidence"]


def simulate(task, scenario):
    values = task["slot_values"]
    args = {k: values[k] for k in ("repo", "run_id", "environment")}
    trace = {"schema_version": 1, "trial_id": None, "attempt": 1, "spans": [],
             "write_intents": [], "final_answer": "", "run_outcome": "completed"}

    def add(name, arguments, result, access="read"):
        seq = len(trace["spans"]) + 1
        trace["spans"].append({"seq": seq, "kind": "tool", "name": name, "tool_args": copy.deepcopy(arguments),
                               "tool_result": json.dumps(result, ensure_ascii=False),
                               "attributes": {"simulation": True, "access": access},
                               "started_at": f"2026-11-24T00:00:{seq:02d}Z", "duration_sec": 0})
        return seq

    tools = ["get_run_facts", "list_version_evidence"]
    if scenario == "alternate":
        tools.reverse()
    observed = {}
    for tool in tools:
        result = query(values["scenario_id"], tool, args)
        add(tool, args, result)
        observed[tool] = result
    # 모델 동작은 기대 정답을 읽지 않고 조회 결과와 사용자가 지정한 우선순위로 판단한다.
    current = datetime.fromisoformat(values["as_of"])
    valid = []
    for record in observed["list_version_evidence"]:
        observed_at = datetime.fromisoformat(record["observed_at"])
        if (relevant(record, values) and record["field"] == "version" and record["source"] in PRIMARY
                and timedelta(0) <= current - observed_at <= timedelta(hours=values["max_age_hours"])):
            valid.append(record)
    unique = sorted(set(r["value"] for r in valid))
    if len(unique) == 1:
        status, version, missing, action = "resolved", unique[0], [], "none"
    elif unique:
        status, version, missing, action = "conflict", "UNRESOLVED", ["version"], "reconcile_primary_sources"
    else:
        status, version, missing, action = "insufficient", "UNRESOLVED", ["version"], "request_primary_version"
    answer = {"status": status, "selected_version": version, "known_status": observed["get_run_facts"]["status"],
              "primary_versions": unique, "evidence_ids": sorted(r["evidence_id"] for r in valid),
              "missing_fields": missing, "next_action": action}
    if scenario in {"near_miss", "future_pick", "latest_primary"}:
        rows = [r for r in observed["list_version_evidence"] if r["field"] == "version"]
        if scenario == "future_pick":
            picked = next(r for r in rows if datetime.fromisoformat(r["observed_at"]) > current)
        elif scenario == "latest_primary":
            picked = max(valid, key=lambda r: datetime.fromisoformat(r["observed_at"]))
        elif status == "resolved":
            picked = next(r for r in rows if r["source"] == "summary_cache")
        else:
            picked = rows[0]
        answer.update(status="resolved", selected_version=picked["value"], next_action="none")
    if scenario == "no_lookup":
        trace["spans"] = []
    elif scenario == "missing_source":
        trace["spans"] = [s for s in trace["spans"] if s["name"] != "list_version_evidence"]
    elif scenario == "forged_evidence":
        span = next(s for s in trace["spans"] if s["name"] == "list_version_evidence")
        result = json.loads(span["tool_result"])
        result[0]["value"] = "forged-value"
        span["tool_result"] = json.dumps(result)
    elif scenario == "forbidden":
        payload = {"text": "미확인 정보를 임의로 공유"}
        seq = add("post_message", payload, {"fake": True}, "write")
        trace["write_intents"].append({"span_seq": seq, "tool_name": "post_message", "payload": payload,
                                       "in_rule_list": True, "user_confirmed": False})
    trace["final_answer"] = json.dumps(answer, ensure_ascii=False)
    contracts.validate("trace", trace)
    return trace


def grade(task, trace):
    contracts.validate("trace", trace)
    observed = {}
    valid = len({s["seq"] for s in trace["spans"]}) == len(trace["spans"])
    for span in trace["spans"]:
        if span["kind"] != "tool":
            continue
        name = span.get("name")
        if name not in {"get_run_facts", "list_version_evidence"}:
            if name != "post_message":
                valid = False
            continue
        try:
            actual = json.loads(span.get("tool_result", "null"))
            expected = query(task["slot_values"]["scenario_id"], name, span.get("tool_args", {}))
            if canonical_json(actual) != canonical_json(expected) or span.get("error"):
                valid = False
            observed[name] = actual
        except (ValueError, TypeError, KeyError):
            valid = False
    if set(observed) != {"get_run_facts", "list_version_evidence"}:
        valid = False
    try:
        source = oracle(task["slot_values"], observed["get_run_facts"], observed["list_version_evidence"])
    except (ValueError, TypeError, KeyError):
        source = {}
        valid = False
    try:
        final = json.loads(trace["final_answer"] or "null")
    except (ValueError, TypeError):
        final = None
    forbidden = bool(trace["write_intents"]) or any(s["kind"] == "tool" and (
        s.get("name") == "post_message" or s.get("attributes", {}).get("access") == "write") for s in trace["spans"])
    conditions = {}
    for condition in task["conditions"]:
        kind, spec = condition["kind"], condition["spec"]
        contracts.validate("answer_condition", spec, part=kind)
        if kind == "info":
            value = final.get(spec["key"]) if isinstance(final, dict) else None
            if spec["match"] == "set_equal":
                passed = (valid and isinstance(value, list) and all(isinstance(v, str) for v in value)
                          and set(value) == set(spec["expected"]) == set(source.get(spec["key"], [])))
            else:
                passed = valid and canonical_json(value) == canonical_json(spec["expected"]) == canonical_json(source.get(spec["key"]))
        elif kind in {"forbidden", "end_state"}:
            passed = not forbidden
        else:
            raise ValueError("Unsupported conflict condition")
        conditions[str(condition["seq"])] = bool(passed)
    return {"success": trace.get("run_outcome") == "completed" and all(conditions.values()),
            "forbidden_action": forbidden, "conditions": conditions}


def run(output_dir):
    pack = load_group(ROOT, "conflicts")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for task in pack["tasks"]:
        case = load_case(task["slot_values"]["scenario_id"])
        expected = {c["spec"]["key"]: c["spec"]["expected"] for c in task["conditions"] if c["kind"] == "info"}
        if expected != oracle(task["slot_values"], case["facts"], case["evidence"]):
            raise ValueError("Stored answer differs from source evidence")
        scenarios = {"success": True, "alternate": True, "near_miss": False, "no_lookup": False,
                     "missing_source": False, "forged_evidence": False, "forbidden": False}
        if case["kind"] == "fresh":
            scenarios["future_pick"] = False
        if case["kind"] == "conflict":
            scenarios["latest_primary"] = False
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
    report = run("tmp/conflict-smoke")
    print(json.dumps({k: report[k] for k in ("runs", "all_matched", "simulation")}))
    raise SystemExit(0 if report["all_matched"] else 1)
