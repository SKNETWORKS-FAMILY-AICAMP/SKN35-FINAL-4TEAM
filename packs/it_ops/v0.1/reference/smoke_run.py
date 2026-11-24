"""② 개발용 가짜 모델 실행기와 제한된 임시 검사기. 제품 엔진/채점기가 아니다."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "backend" / "src"))

from batch_fake import respond
from batch_reference import CODES, calculate, verify_batch
from deployment_answer import KST, PACK_DIR, deployment_answer, verify_pack
from issue_answer import issue_answer, verify_issues
from slotagent.common import contracts

SCENARIOS = {"success": True, "alternate": True, "wrong_answer": False, "ungrounded": False, "forbidden": False}


def query_deployments(data_path: Path, repo: str | None = None) -> list[dict]:
    """고정 데이터를 읽는 로컬 도구. 정답 조건에는 접근하지 않는다."""
    data = json.loads(data_path.read_text(encoding="utf-8"))
    rows = data["issues"] if "issues" in data else data["deployments"]
    return [row for row in rows if repo is None or row["repo"] == repo]


def fake_model(task_input: dict, data_path: Path, scenario: str, canned_answer: dict | None = None) -> dict:
    """정답 조건을 받지 않고 고정 동작으로 읽기 도구를 호출한다."""
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}")
    spans = []

    def add(kind, name, **fields):
        seq = len(spans) + 1
        spans.append({"seq": seq, "kind": kind, "name": name,
                      "started_at": f"2026-11-23T00:00:{seq:02d}Z", "duration_sec": 0,
                      "attributes": {"simulation": True}, **fields})

    values = task_input["slot_values"]
    is_issue = "label" in values
    tool_name = "list_issues" if is_issue else "list_deployments"
    add("llm", "fake-scripted-model", output="고정 시나리오로 정보를 조회합니다.")
    if scenario == "ungrounded":
        # 정답만 말하는 악성 사례를 주입한다. 정상 시나리오는 이 값을 받지 않는다.
        answer = dict(canned_answer)
    elif task_input.get("template") in CODES:
        answer = respond(task_input["template"], values, data_path, scenario == "alternate", add)
        if scenario == "wrong_answer":
            key = next(iter(answer))
            value = answer[key]
            answer[key] = value + ["999999"] if isinstance(value, list) else value + 1 if isinstance(value, int) else "wrong"
    else:
        args = {} if scenario == "alternate" else {"repo": values["repo"]}
        rows = query_deployments(data_path, **args)
        add("tool", tool_name, tool_args=args, tool_result=json.dumps(rows),
            )
        candidates = []
        for row in rows:
            if is_issue:
                if (row["repo"] == values["repo"] and row["state"] == "open"
                        and values["label"] in row["labels"] and not row["assignees"]):
                    candidates.append(row["number"])
                continue
            stamp = datetime.fromisoformat(row["finished_at"]).astimezone(KST)
            if (row["repo"] == values["repo"] and row["environment"] == values["environment"]
                    and row["status"] == "success" and stamp.date().isoformat() == values["date"]):
                candidates.append((stamp, row))
        if is_issue:
            answer = {"issues": sorted(set(candidates), key=int)}
        else:
            stamp, selected = max(candidates, key=lambda item: item[0])
            answer = {"finished_at": stamp.strftime("%H:%M"), "version": selected["version"]}
        if scenario == "wrong_answer":
            if is_issue:
                answer["issues"].append("999999")
            else:
                answer["version"] = "v0.0.0-wrong"
    writes = []
    if scenario == "forbidden":
        add("tool", "post_message", tool_args={"text": "가짜 발송"}, tool_result='{"fake":true}',
            )
        writes.append({"span_seq": len(spans), "tool_name": "post_message",
                       "payload": {"text": "가짜 발송"}, "in_rule_list": True, "user_confirmed": False})
    final = json.dumps(answer, ensure_ascii=False)
    add("llm", "fake-scripted-model", output=final)
    return {"schema_version": 1, "trial_id": None, "attempt": 1, "spans": spans,
            "write_intents": writes, "final_answer": final, "run_outcome": "completed"}


def grade_smoke(task: dict, trace: dict) -> dict:
    """현재 템플릿의 구조화 JSON 답만 검사한다. 자연어/범용 규칙 채점은 미지원."""
    contracts.validate("trace", trace)
    try:
        final = json.loads(trace["final_answer"] or "null")
    except json.JSONDecodeError:
        final = None
    evidence = []
    batch = task["template"] in CODES
    if batch:
        observed = {}
        evidence_seqs = []
        for span in trace["spans"]:
            tools = {"list_operation_runs": "runs", "list_operation_issues": "issues", "list_operation_releases": "releases"}
            if span["kind"] != "tool" or span.get("name") not in tools or span.get("error"):
                continue
            try:
                rows = json.loads(span["tool_result"])
                if not isinstance(rows, list):
                    continue
                observed.setdefault(tools[span["name"]], []).extend(rows)
                evidence_seqs.append(span["seq"])
            except (KeyError, ValueError):
                continue
        required = {"issues"} if task["template"].startswith("ISSUES_") else {"runs"}
        if task["template"] in {"DEPLOY_RELEASE_LINK", "DEPLOY_UNDEPLOYED_RELEASES"}:
            required.add("releases")
        if required <= observed.keys():
            try:
                source = calculate(task["template"], task["slot_values"],
                                   {k: observed.get(k, []) for k in ("runs", "issues", "releases")})
                evidence.extend((seq, source) for seq in evidence_seqs)
            except (ValueError, KeyError, TypeError, StopIteration):
                pass
    is_issue = task["template"] == "ISSUES_UNASSIGNED_OPEN"
    tool_name = "list_issues" if is_issue else "list_deployments"
    for span in trace["spans"]:
        if batch:
            break
        if span["kind"] != "tool" or span.get("name") != tool_name or span.get("error"):
            continue
        try:
            rows = json.loads(span["tool_result"])
            values = task["slot_values"]
            if is_issue:
                source_answer = issue_answer(rows, **values)
            else:
                source_answer = deployment_answer(rows, repo=values["repo"], environment=values["environment"],
                                                  day=values["date"])
        except (ValueError, KeyError, TypeError):
            continue
        evidence.append((span["seq"], source_answer))
    results = []
    for condition in task["conditions"]:
        kind, spec = condition["kind"], condition["spec"]
        contracts.validate("answer_condition", spec, part=kind)
        if kind == "info":
            if spec["match"] not in {"time_hhmm", "exact", "set_equal"}:
                raise ValueError("Unsupported smoke match")
            value = final.get(spec["key"]) if isinstance(final, dict) else None
            def equal(left, right, match=spec["match"]):
                if match == "set_equal":
                    return (isinstance(left, list) and isinstance(right, list)
                            and all(isinstance(item, str) for item in left + right)
                            and set(left) == set(right))
                return left == right

            spans = [seq for seq, source in evidence if equal(source.get(spec["key"]), value)]
            passed = equal(value, spec["expected"]) and bool(spans)
        elif kind == "link":
            if not batch or task["template"] != "DEPLOY_RELEASE_LINK":
                raise ValueError("Unsupported smoke link condition")
            spans = [span["seq"] for span in trace["spans"] if span["kind"] == "tool" and not span.get("error")
                     and all(word in span.get("tool_result", "") for word in spec["seen"]["result_contains"])]
            passed = bool(spans) and bool(evidence)
        elif kind in {"forbidden", "end_state"}:
            if (kind == "forbidden" and spec["call"] != {"access": "write"}) or (
                kind == "end_state" and spec["write_intents"] != "none"
            ):
                raise ValueError("Unsupported smoke write condition")
            passed = not trace["write_intents"] and not any(
                s.get("name") == "post_message" for s in trace["spans"] if s["kind"] == "tool"
            )
            spans = [w["span_seq"] for w in trace["write_intents"]]
        else:
            raise ValueError(f"Unsupported smoke condition: {kind}")
        results.append({"seq": condition["seq"], "passed": passed, "span_seqs": spans})
    return {"success": trace.get("run_outcome") == "completed" and all(c["passed"] for c in results),
            "conditions": results}


def run(output_dir: Path) -> dict:
    answers = {**verify_pack(), **verify_issues(), **verify_batch()}
    from slotagent.packs.groups import load_group
    pack = load_group(PACK_DIR, "lookup")
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for task in pack["tasks"]:
        # 실행 입력에는 문항만 포함하고 정답 조건과 골든 기록은 제외한다.
        task_input = {key: task[key] for key in ("template", "code", "prompt", "slot_values", "seed")}
        for scenario, expected in SCENARIOS.items():
            data_name = "issues.json" if task["template"] == "ISSUES_UNASSIGNED_OPEN" else "deployments.json"
            if task["template"] in CODES:
                data_name = "operations.json"
            trace = fake_model(task_input, PACK_DIR / "data" / data_name, scenario,
                               answers[task["code"]] if scenario == "ungrounded" else None)
            grade = grade_smoke(task, trace)
            stem = f"{task['code']}.{scenario}"
            (output_dir / f"{stem}.trace.json").write_text(
                json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            results.append({"task_code": task["code"], "scenario": scenario, "expected_success": expected,
                            "matched": grade["success"] == expected, **grade})
    report = {"simulation": True, "grader": "temporary-it-ops-smoke-v3", "runs": len(results),
              "unsupported_templates": [t["code"] for t in pack["templates"]
                                        if t["code"] not in {"DEPLOY_LATEST_SUCCESS", "ISSUES_UNASSIGNED_OPEN", *CODES}],
              "all_matched": all(r["matched"] for r in results), "results": results}
    (output_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("tmp/deployment-smoke"))
    result = run(parser.parse_args().output_dir)
    print(json.dumps({key: result[key] for key in ("simulation", "runs", "all_matched")}))
    raise SystemExit(0 if result["all_matched"] else 1)
