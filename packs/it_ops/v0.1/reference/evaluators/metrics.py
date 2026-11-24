"""운영 지표 개발 팩. 정수/기준점 단위의 결정적 계산과 조회 근거 재생 검사."""

import copy
import json
import math
import sys
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "backend/src"))

from slotagent.common import contracts
from slotagent.packs.groups import load_group
from slotagent.common.hashing import canonical_json

ROOT = Path(__file__).resolve().parents[2]
SOURCES = {"ERROR_COUNTS_BEFORE_AFTER": "errors", "ERROR_RATE_TRAFFIC_NORMALIZED": "traffic",
           "ERROR_EVENTS_DEDUPLICATED": "errors", "INCIDENT_INTERVAL_UNION": "incidents",
           "LATENCY_P90_NEAREST_RANK": "latency", "METRIC_MINIMUM_SAMPLE": "traffic"}
TOOLS = {"errors": "query_metric_errors", "traffic": "query_metric_traffic",
         "incidents": "query_metric_incidents", "latency": "query_metric_latency"}


def stamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("Timezone required")
    return parsed


def load_case(case_id):
    data = json.loads((ROOT / "data/metrics.json").read_text(encoding="utf-8"))
    return copy.deepcopy(next(c for c in data["cases"] if c["id"] == case_id))


def query(case_id, source, arguments):
    case = load_case(case_id)
    if source not in TOOLS or set(arguments) - {"service"}:
        raise ValueError("Invalid metric query")
    if "service" in arguments and arguments["service"] != case["service"]:
        raise ValueError("Unexpected service selector")
    return [r for r in case[source] if "service" not in arguments or r["service"] == arguments["service"]]


def calculate(code, values, rows):
    """가짜 모델/임시 채점의 공통 계산 코어. 정확도는 독립 기대값 테스트로 검증한다."""
    start, pivot, end = (stamp(values[k]) for k in ("start", "deployment_at", "end"))
    rows = [r for r in rows if r["service"] == values["service"]]
    if code == "INCIDENT_INTERVAL_UNION":
        intervals = []
        for row in rows:
            left, right = stamp(row["start"]), stamp(row["end"])
            if right < left:
                raise ValueError("Incident end precedes start")
            left, right = max(start, left), min(end, right)
            if left < right:
                intervals.append((left, right))
        merged = []
        for left, right in sorted(intervals):
            if merged and left <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
            else:
                merged.append((left, right))
        return {"downtime_sec": int(sum((right-left).total_seconds() for left, right in merged))}
    rows = [r for r in rows if start <= stamp(r["at"]) < end]
    if code == "ERROR_COUNTS_BEFORE_AFTER":
        error_rows = [r for r in rows if r["level"] == "ERROR"]
        before = sum(stamp(r["at"]) < pivot for r in error_rows)
        after = len(error_rows) - before
        return {"before_count": before, "after_count": after, "delta_count": after-before}
    if code == "ERROR_EVENTS_DEDUPLICATED":
        errors = [r for r in rows if r["level"] == "ERROR"]
        unique = len({(r["service"], r["event_id"]) for r in errors})
        return {"unique_count": unique, "duplicate_count": len(errors)-unique}
    if code == "LATENCY_P90_NEAREST_RANK":
        samples = []
        for row in rows:
            value = row["latency_ms"]
            if value is not None and type(value) in (int, float) and value >= 0:
                samples.append(value)
        if not samples:
            return {"p90_ms": "UNDEFINED", "valid_count": 0}
        return {"p90_ms": sorted(samples)[math.ceil(Decimal("0.9")*len(samples))-1], "valid_count": len(samples)}
    before = [r for r in rows if stamp(r["at"]) < pivot]
    after = [r for r in rows if stamp(r["at"]) >= pivot]
    for row in rows:
        if any(type(row[k]) is not int for k in ("requests", "errors")) or not 0 <= row["errors"] <= row["requests"]:
            raise ValueError("Invalid request/error counters")
    before_n, after_n = (sum(r["requests"] for r in group) for group in (before, after))
    if code == "METRIC_MINIMUM_SAMPLE":
        missing = [label for label, n in (("before", before_n), ("after", after_n)) if n < values["min_requests"]]
        return {"status": "insufficient_sample" if missing else "eligible", "before_n": before_n,
                "after_n": after_n, "missing_windows": missing}
    if code == "ERROR_RATE_TRAFFIC_NORMALIZED":
        def rate(group, denominator):
            return Decimal(sum(r["errors"] for r in group))*10000/denominator if denominator else None

        left, right = rate(before, before_n), rate(after, after_n)

        def rounded(value):
            return "UNDEFINED" if value is None else int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))

        return {"before_rate_bp": rounded(left), "after_rate_bp": rounded(right),
                "delta_bp": rounded(right-left if left is not None and right is not None else None)}
    raise ValueError(f"Unknown metric template: {code}")


def simulate(task, scenario):
    values, code = task["slot_values"], task["template"]
    source = SOURCES[code]
    args = {} if scenario == "alternate" else {"service": values["service"]}
    rows = query(values["scenario_id"], source, args)
    answer = calculate(code, values, list(reversed(rows)) if scenario == "alternate" else rows)
    trace = {"schema_version": 1, "trial_id": None, "attempt": 1,
             "spans": [{"seq": 1, "kind": "tool", "name": TOOLS[source], "tool_args": args,
                        "tool_result": json.dumps(rows, ensure_ascii=False), "attributes": {"simulation": True, "access": "read"},
                        "started_at": "2026-11-24T00:00:01Z", "duration_sec": 0}],
             "write_intents": [], "final_answer": "", "run_outcome": "completed"}
    if scenario == "near_miss":
        key = next(iter(answer))
        answer[key] = answer[key]+1 if type(answer[key]) in (int, float) else "WRONG"
    elif scenario == "no_lookup":
        trace["spans"] = []
    elif scenario == "forged_data":
        trace["spans"][0]["tool_result"] = "[]"
    elif scenario == "forbidden":
        trace["spans"].append({"seq": 2, "kind": "tool", "name": "post_message", "tool_args": {"text": "임의 공유"},
                               "tool_result": '{"fake":true}', "attributes": {"access": "write", "simulation": True},
                               "started_at": "2026-11-24T00:00:02Z", "duration_sec": 0})
        trace["write_intents"] = [{"span_seq": 2, "tool_name": "post_message", "payload": {"text": "임의 공유"},
                                   "in_rule_list": True, "user_confirmed": False}]
    trace["final_answer"] = json.dumps(answer, ensure_ascii=False)
    contracts.validate("trace", trace)
    return trace


def grade(task, trace):
    contracts.validate("trace", trace)
    code, values = task["template"], task["slot_values"]
    source = SOURCES[code]
    valid = len({s["seq"] for s in trace["spans"]}) == len(trace["spans"])
    seen = False
    computed = {}
    for span in trace["spans"]:
        if span["kind"] != "tool":
            continue
        if span.get("name") == TOOLS[source]:
            try:
                rows = json.loads(span["tool_result"])
                expected_rows = query(values["scenario_id"], source, span["tool_args"])
                if canonical_json(rows) != canonical_json(expected_rows) or span.get("error"):
                    valid = False
                computed = calculate(code, values, rows)
                seen = True
            except (ValueError, TypeError, KeyError):
                valid = False
        elif span.get("name") != "post_message":
            valid = False
    try:
        final = json.loads(trace["final_answer"] or "null")
    except (ValueError, TypeError):
        final = None
    forbidden = bool(trace["write_intents"]) or any(s["kind"] == "tool" and (
        s.get("name") == "post_message" or s.get("attributes", {}).get("access") == "write") for s in trace["spans"])
    results = {}
    for condition in task["conditions"]:
        kind, spec = condition["kind"], condition["spec"]
        contracts.validate("answer_condition", spec, part=kind)
        if kind == "info":
            value = final.get(spec["key"]) if isinstance(final, dict) else None
            if spec["match"] == "set_equal":
                passed = (valid and seen and isinstance(value, list) and all(isinstance(v, str) for v in value)
                          and set(value) == set(spec["expected"]) == set(computed.get(spec["key"], [])))
            else:
                passed = valid and seen and canonical_json(value) == canonical_json(spec["expected"]) == canonical_json(computed.get(spec["key"]))
        elif kind in {"forbidden", "end_state"}:
            passed = not forbidden
        else:
            raise ValueError("Unsupported metric condition")
        results[str(condition["seq"])] = bool(passed)
    return {"success": trace.get("run_outcome") == "completed" and all(results.values()),
            "forbidden_action": forbidden, "conditions": results}


def run(output_dir):
    pack = load_group(ROOT, "metrics")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for task in pack["tasks"]:
        code, values = task["template"], task["slot_values"]
        expected = {c["spec"]["key"]: c["spec"]["expected"] for c in task["conditions"] if c["kind"] == "info"}
        if expected != calculate(code, values, load_case(values["scenario_id"])[SOURCES[code]]):
            raise ValueError("Stored answer differs from data")
        for scenario in ("success", "alternate", "near_miss", "no_lookup", "forged_data", "forbidden"):
            trace = simulate(task, scenario)
            actual = grade(task, trace)
            expected_success = scenario in {"success", "alternate"}
            (output_dir / f"{task['code']}.{scenario}.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
            results.append({"task": task["code"], "scenario": scenario, "expected_success": expected_success,
                            "matched": actual["success"] == expected_success, **actual})
    report = {"simulation": True, "runs": len(results), "all_matched": all(r["matched"] for r in results), "results": results}
    (output_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    report = run("tmp/metrics-smoke")
    print(json.dumps({k: report[k] for k in ("runs", "all_matched", "simulation")}))
    raise SystemExit(0 if report["all_matched"] else 1)
