"""Build tool observations and blinded human-review material; never assign labels."""

import argparse
import copy
import csv
import hashlib
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "packs/it_ops/v0.1"
INVENTORY = PACK / "practice/tool_inventory.json"
PILOT = PACK / "practice/pilot_selection.json"
# Representative selection only: does not mutate pack split or selection gates.
PILOT_CODES = {
    "DEPLOY_LATEST_SUCCESS": "마지막 성공 배포와 날짜 경계",
    "ISSUES_UNASSIGNED_OPEN": "조건 필터와 빈 결과",
    "DEPLOY_RELEASE_LINK": "배포와 릴리스 근거 연결",
    "CONFIRMED_RELEASE_SHARE": "승인·거절·무응답 후 메시지 처리",
    "CONFIRMED_ISSUE_CREATE": "승인 후 이슈 생성",
    "LATEST_CONFIRMATION_SCOPE": "새 확인이 이전 승인을 대체",
    "LOG_FIRST_ERROR": "최초 오류와 관측 근거 구분",
    "INCIDENT_TIMELINE": "장애 이벤트 순서 복원",
    "INCIDENT_RECOVERY_EVIDENCE": "복구 증거 확인",
    "RETRY_TRANSIENT_READ": "일시 오류 복구와 호출 한도",
    "RETRY_EXHAUSTED_READ": "재시도 소진과 답변 유보",
    "CONFLICT_EQUAL_AUTHORITY": "동급 근거 충돌 시 단정 방지",
    "ERROR_COUNTS_BEFORE_AFTER": "배포 전후 오류 계산",
    "CONFIG_OVERRIDE_PRECEDENCE": "설정 우선순위와 null·0 구분",
    "UNTRUSTED_ISSUE_INSTRUCTIONS": "조회 데이터에 포함된 지시문 무시",
}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def encoded(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def trace_for(pack_dir, entry):
    path = (pack_dir / entry["trace"]).resolve()
    if not path.is_relative_to((pack_dir / "golden").resolve()):
        raise ValueError("Trace path must stay inside golden")
    return read(path)


def inventory(pack_dir=PACK):
    pack = read(pack_dir / "pack.json")
    manifest_path = pack_dir / "practice/servers.json"
    manifest = read(manifest_path)
    defined = {tool["name"]: tool for service in manifest["services"] for tool in service["tools"]}
    observed = {}
    for entry in pack["golden"]:
        for span in trace_for(pack_dir, entry)["spans"]:
            if span["kind"] != "tool":
                continue
            item = observed.setdefault(span["name"], {"templates": set(), "argument_keys": set(), "calls": 0})
            item["templates"].add(entry["template"])
            item["argument_keys"].update(span.get("tool_args", {}))
            item["calls"] += 1
    tools = []
    for name, observation in sorted(observed.items()):
        definition = defined.get(name)
        builtin = name == "request_user_confirmation"
        tools.append({
            "name": name,
            "access": definition["access"] if definition else (None if builtin else "write" if name in {"create_issue", "post_message"} else "read"),
            "access_basis": "servers.json" if definition else "local_simulator_semantics_pending_engine_review",
            "capabilities": definition["capabilities"] if definition else [],
            "mapping_status": "practice_manifest_defined" if definition else "engine_review_required",
            "implementation": "practice_mcp" if definition else "confirmation_protocol" if builtin else "local_simulator",
            "candidate_authority_source": False,
            "definition": definition,
            "observed": {"templates": sorted(observation["templates"]),
                         "argument_keys": sorted(observation["argument_keys"]), "calls": observation["calls"]},
        })
    return {"schema_version": 1, "purpose": "review_inventory_only_not_candidate_permissions",
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "notes": ["Observed arguments are not an input schema.",
                      "Local access describes simulator behavior, not candidate authority.",
                      "Empty capabilities and null access require engine/runner review; never infer from task requirements.",
                      "Manifest definitions describe practice tools only; real candidate mapping is separate."],
            "tools": tools}


def review_material(pack_dir=PACK, all_templates=False, seed=1124):
    pack = read(pack_dir / "pack.json")
    groups = read(pack_dir / "groups.json")["groups"]
    selected = {t["code"] for t in pack["templates"]} if all_templates else {
        group["template_codes"][0] for group in groups.values()
    }
    entries = [entry for entry in pack["golden"] if entry["template"] in selected]
    random.Random(seed).shuffle(entries)
    tasks = {task["code"]: task for task in pack["tasks"]}
    public, private = [], []
    for index, entry in enumerate(entries, 1):
        case_id = f"review-{index:03d}"
        trace = copy.deepcopy(trace_for(pack_dir, entry))
        for span in trace["spans"]:
            # Keep behavior and tool results, remove fixture/expected provenance.
            span["attributes"] = {k: v for k, v in span.get("attributes", {}).items()
                                  if not k.startswith("golden.") and k not in {"fixture", "expected"}}
            if span["kind"] == "llm":
                span["name"] = "review-model"
        task = tasks[entry["task_code"]]
        public.append({"case_id": case_id, "prompt": task["prompt"], "trace": trace,
                       "annotation": {"reviewer": None, "result_class": None, "first_fail_type": None,
                                      "first_fail_seq": None, "success": None,
                                      "needs_adjudication": None, "reason": None}})
        private.append({"case_id": case_id, "template": entry["template"], "task_code": entry["task_code"],
                        "kind": entry["kind"], "expected": entry["expected"],
                        "conditions": task["conditions"], "confirmation": task.get("confirmation"),
                        "trace_source": entry["trace"]})
    fingerprint = hashlib.sha256((pack_dir / "pack.json").read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    return ({"schema_version": 1, "pack_sha256": fingerprint, "file_hash_policy": "sha256_crlf_to_lf_v1",
             "notice": "Synthetic golden review, not a held set or LLM calibration dataset. Unobservable policy: request adjudication.",
             "cases": public},
            {"schema_version": 1, "pack_sha256": fingerprint, "file_hash_policy": "sha256_crlf_to_lf_v1", "seed": seed,
             "notice": "Private answer key. Do not give to reviewers before independent annotation.", "cases": private})


def pilot_selection(pack_dir=PACK):
    pack = read(pack_dir / "pack.json")
    groups = read(pack_dir / "groups.json")["groups"]
    tools = {item["name"]: item for item in inventory(pack_dir)["tools"]}
    items = []
    for template in pack["templates"]:
        code = template["code"]
        if code not in PILOT_CODES:
            continue
        group_name = next(name for name, group in groups.items() if code in group["template_codes"])
        entries = [entry for entry in pack["golden"] if entry["template"] == code]
        # Success examples describe a local path, never mandatory tools or candidate permissions.
        names = sorted({span["name"] for entry in entries if entry["kind"] in {"success", "alt_success"}
                        for span in trace_for(pack_dir, entry)["spans"] if span["kind"] == "tool"})
        ready = all(tools[name]["definition"] is not None for name in names)
        items.append({"template": code, "group": group_name, "reason": PILOT_CODES[code],
                      "task_codes": [task["code"] for task in pack["tasks"] if task["template"] == code],
                      "required_capabilities": template["required_capabilities"],
                      "example_local_tools": names, "snapshot_paths": groups[group_name]["snapshot_paths"],
                      "connection_status": "practice_mcp_defined" if ready else "local_simulator_only_mapping_pending",
                      "product_ready": False,
                      "review_requests": ["④ 후보 도구의 기능·인자·대상 범위 확인", "① 실행·제품 채점 통합 확인"]
                      + (["① P-05 확인 도구·fake 쓰기 통합 확인"] if group_name == "writes" else [])
                      + (["① tool_error trace와 ② 임시 채점기 대응 보류 해제 후 확인"] if group_name == "reliability" else [])})
    if len(items) != 15:
        raise ValueError("Pilot must contain exactly 15 active templates")
    return {"schema_version": 1, "status": "role2_proposal_team_review_pending",
            "pack_sha256": hashlib.sha256((pack_dir / "pack.json").read_bytes()).hexdigest(),
            "notice": "Not runner input, not held selection, not candidate authority; example tools are not required paths.",
            "templates": items}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check inventory freshness without writing")
    parser.add_argument("--export-review", action="store_true")
    parser.add_argument("--all", action="store_true", help="review all templates rather than one per group")
    args = parser.parse_args()
    content = encoded(inventory())
    if args.check:
        if not INVENTORY.exists() or INVENTORY.read_text(encoding="utf-8") != content:
            raise SystemExit("Tool inventory is stale")
        if not PILOT.exists() or PILOT.read_text(encoding="utf-8") != encoded(pilot_selection()):
            raise SystemExit("Pilot selection is stale")
    else:
        INVENTORY.write_text(content, encoding="utf-8")
        PILOT.write_text(encoded(pilot_selection()), encoding="utf-8")
    if args.export_review:
        # Ignored disposable material, deliberately separate reviewer and coordinator directories.
        output = ROOT / "tmp/pack_review"
        public, private = review_material(all_templates=args.all)
        previous = output / "reviewer/cases.json"
        if previous.exists() and read(previous) != public:
            raise SystemExit("Existing review differs: preserve completed annotations and move the review folder before exporting")
        for folder, value in (("reviewer", public), ("coordinator_private", private)):
            target = output / folder
            target.mkdir(parents=True, exist_ok=True)
            (target / "cases.json").write_text(encoded(value), encoding="utf-8")
        sheet = output / "reviewer/annotations.csv"
        # Preserve annotations on re-export. Versioned JSON identifies the pack being reviewed.
        if not sheet.exists():
            with sheet.open("w", encoding="utf-8-sig", newline="") as stream:
                fields = ["case_id", "pack_sha256", "reviewer", "result_class", "first_fail_type",
                          "first_fail_seq", "success", "needs_adjudication", "prompt_clear",
                          "excessive_hint", "alternative_path_accepted", "reason", "revision_request"]
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows({"case_id": case["case_id"], "pack_sha256": public["pack_sha256"]}
                                 for case in public["cases"])
        print(f"Exported {len(public['cases'])} cases to {output}")
    print("Tool inventory checked" if args.check else "Tool inventory updated")


if __name__ == "__main__":
    main()
