"""packs/it_ops/v1.0/pack.json (contracts/examples/pack.json 모양) → DB. 잠그기 전 검사: 골든 궤적 4종 채점 결과 = expected"""

import json
from pathlib import Path

from psycopg.types.json import Jsonb

from slotagent.common import checks, contracts
from slotagent.common.hashing import canonical_hash


def confirmation_for_storage(task: dict) -> dict | None:
    """생략/NULL은 SQL NULL. 유효한 정책만 저장하고 slot_values에는 넣지 않는다."""
    policy = task.get("confirmation")
    if policy is not None:
        contracts.validate("pack", policy, part="confirmation")
    return policy


def store_task_confirmation(conn, task_id: int, task: dict) -> None:
    """기존 문항에 정책 저장. 트랜잭션은 호출자가 관리, 잠긴 문항은 DB 트리거가 차단."""
    policy = confirmation_for_storage(task)
    result = conn.execute("UPDATE sa_tasks SET confirmation = %s WHERE task_id = %s",
                          (Jsonb(policy) if policy is not None else None, task_id))
    if result.rowcount != 1:
        raise ValueError(f"Unknown task_id: {task_id}")


def pack_content_hash(pack: dict) -> str:
    """① 해시에 사용할 원본 해시. confirmation 포함, 생략과 NULL은 같은 의미로 정규화."""
    tasks = [{**task, "confirmation": confirmation_for_storage(task)} for task in pack["tasks"]]
    return canonical_hash({**pack, "tasks": tasks})


def read_pack(pack_dir):
    """파일·참조·계약을 DB 변경 전에 검사한다. 로컬 동결 JSON만 지원."""
    root = Path(pack_dir).resolve()
    pack = json.loads((root / "pack.json").read_text(encoding="utf-8"))
    contracts.validate("pack", pack["pack_version"]["premises"], part="premises")
    templates = {t["code"]: t for t in pack["templates"]}
    if len(templates) != len(pack["templates"]):
        raise ValueError("Duplicate template code")
    tasks = {t["code"]: t for t in pack["tasks"]}
    if len(tasks) != len(pack["tasks"]):
        raise ValueError("Duplicate task code")
    for template in templates.values():
        contracts.validate("pack", template.get("required_capabilities", []), part="required_capabilities")
        if template.get("split", "held") not in {"dev", "held"}:
            raise ValueError("Invalid template split")
    for task in tasks.values():
        if task["template"] not in templates:
            raise ValueError("Unknown task template")
        confirmation_for_storage(task)
        seqs = [c["seq"] for c in task["conditions"]]
        if len(set(seqs)) != len(seqs) or any(type(seq) is not int or seq < 1 for seq in seqs):
            raise ValueError("Invalid condition sequence")
        for condition in task["conditions"]:
            contracts.validate("answer_condition", condition["spec"], part=condition["kind"])
        checks.check_task_conditions(task["conditions"])
    snapshots = []
    locations = set()
    for snapshot in pack["data_snapshots"]:
        contracts.validate("pack", snapshot["design"], part="data_design")
        key = (snapshot["source_kind"], snapshot["location"])
        if key in locations:
            raise ValueError("Duplicate data snapshot")
        locations.add(key)
        path = (root / snapshot["location"]).resolve()
        if not path.is_relative_to(root / "data"):
            raise ValueError("Snapshot must be a local file inside data/")
        snapshots.append((snapshot, canonical_hash(json.loads(path.read_text(encoding="utf-8")))))
    golden = []
    keys = set()
    for entry in pack.get("golden", []):
        key = (entry["template"], entry["kind"])
        if key in keys or entry["template"] not in templates or entry["kind"] not in {
            "success", "alt_success", "near_miss", "forbidden"
        }:
            raise ValueError("Invalid golden registration")
        keys.add(key)
        target = tasks.get(entry.get("task_code"))
        if target is None or target["template"] != entry["template"]:
            raise ValueError("Golden requires an explicit matching task_code")
        path = (root / entry["trace"]).resolve()
        if not path.is_relative_to(root / "golden"):
            raise ValueError("Golden trace must stay inside golden/")
        trace = json.loads(path.read_text(encoding="utf-8"))
        contracts.validate("trace", trace)
        contracts.validate("pack", entry["expected"], part="golden_expected")
        golden.append((entry, trace))
    return pack, snapshots, golden


def load_pack(conn, pack_dir) -> int:
    """검증된 팩을 draft로 원자적 저장. 중복 버전은 DB UNIQUE로 거절, 임의 덮어쓰기 없음.

    confirmation 칼럼은 ① 마이그레이션 책임. 읽기 팩은 칼럼 없이도 저장 가능하다.
    전체 load/lock 게이트 검증 완료를 의미하지 않는다. 해시는 pack_content_hash로 별도 제공.
    """
    pack, snapshots, golden = read_pack(pack_dir)
    with conn.transaction():
        has_confirmation = conn.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() "
            "AND table_name = 'sa_tasks' AND column_name = 'confirmation')"
        ).fetchone()[0]
        if not has_confirmation and any(confirmation_for_storage(t) is not None for t in pack["tasks"]):
            raise ValueError("sa_tasks.confirmation is missing; ① must apply the P-05 migration first")
        version = pack["pack_version"]
        pack_id = conn.execute(
            "INSERT INTO sa_pack_versions(domain_code, pack_code, version, premises) VALUES (%s,%s,%s,%s) "
            "RETURNING pack_version_id",
            (version["domain_code"], version["pack_code"], version["version"], Jsonb(version["premises"])),
        ).fetchone()[0]
        for snapshot, content_hash in snapshots:
            conn.execute(
                "INSERT INTO sa_data_snapshots(pack_version_id,source_kind,location,design,content_hash,frozen_at) "
                "VALUES (%s,%s,%s,%s,%s,now())",
                (pack_id, snapshot["source_kind"], snapshot["location"], Jsonb(snapshot["design"]), content_hash),
            )
        template_ids = {}
        for template in pack["templates"]:
            template_ids[template["code"]] = conn.execute(
                "INSERT INTO sa_templates(pack_version_id,code,question_pattern,value_rule,is_representative,split,"
                "required_capabilities) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING template_id",
                (pack_id, template["code"], template["question_pattern"], Jsonb(template.get("value_rule", {})),
                 template.get("is_representative", False), template.get("split", "held"),
                 Jsonb(template.get("required_capabilities", []))),
            ).fetchone()[0]
        for task in pack["tasks"]:
            task_id = conn.execute(
                "INSERT INTO sa_tasks(template_id,code,prompt,slot_values,seed) VALUES (%s,%s,%s,%s,%s) RETURNING task_id",
                (template_ids[task["template"]], task["code"], task["prompt"], Jsonb(task["slot_values"]), task["seed"]),
            ).fetchone()[0]
            if has_confirmation:
                store_task_confirmation(conn, task_id, task)
            for condition in task["conditions"]:
                conn.execute(
                    "INSERT INTO sa_answer_conditions(task_id,seq,kind,spec,spec_schema_version) VALUES (%s,%s,%s,%s,%s)",
                    (task_id, condition["seq"], condition["kind"], Jsonb(condition["spec"]), condition["spec"]["schema_version"]),
                )
        for entry, trace in golden:
            # DB에는 task_id 칼럼이 없으므로 기존 trace.attributes에 검증 대상 코드를 보존한다.
            if trace["spans"]:
                attrs = trace["spans"][0].setdefault("attributes", {})
                attrs["golden.task_code"] = entry["task_code"]
            else:
                raise ValueError("Golden trace must have at least one span to retain task binding")
            conn.execute(
                "INSERT INTO sa_golden_trajectories(template_id,kind,trace,expected) VALUES (%s,%s,%s,%s)",
                (template_ids[entry["template"]], entry["kind"], Jsonb(trace), Jsonb(entry["expected"])),
            )
        return pack_id


def lock_pack(conn, pack_version_id: int) -> None:
    """DB 내용 fingerprint에 묶인 독립 환경/제품 골든 검증 기록이 있을 때만 잠근다."""
    with conn.transaction():
        row = conn.execute("SELECT status FROM sa_pack_versions WHERE pack_version_id=%s FOR UPDATE",
                           (pack_version_id,)).fetchone()
        if row is None or row[0] != "draft":
            raise ValueError("Only a draft pack can be locked")
        # 관련 쓰기를 차단해 점검 이후 자식 행이 바뀌는 것을 막는다. 잠금은 짧게 유지한다.
        conn.execute("LOCK TABLE sa_templates,sa_tasks,sa_answer_conditions,sa_data_snapshots,"
                     "sa_golden_trajectories IN SHARE MODE")
        report = pack_readiness(conn, pack_version_id)
        if report["blockers"]:
            raise ValueError("Pack lock blocked: " + "; ".join(report["blockers"]))
        conn.execute("UPDATE sa_pack_versions SET status='locked',locked_at=now() WHERE pack_version_id=%s",
                     (pack_version_id,))


def pack_readiness(conn, pack_version_id: int) -> dict:
    """제품 채점 완료를 위조하지 않고, 독립 검증 기록/DB fingerprint에 따라 준비 상태 제공."""
    version = conn.execute("SELECT domain_code,pack_code,version,premises FROM sa_pack_versions "
                           "WHERE pack_version_id=%s", (pack_version_id,)).fetchone()
    if version is None:
        raise ValueError("Unknown pack_version_id")
    queries = {
        "templates": "SELECT to_jsonb(t) FROM sa_templates t WHERE pack_version_id=%s ORDER BY template_id",
        "tasks": "SELECT to_jsonb(k) FROM sa_tasks k JOIN sa_templates t USING(template_id) "
                 "WHERE t.pack_version_id=%s ORDER BY k.task_id",
        "conditions": "SELECT to_jsonb(c) FROM sa_answer_conditions c JOIN sa_tasks k USING(task_id) "
                      "JOIN sa_templates t USING(template_id) WHERE t.pack_version_id=%s ORDER BY c.answer_condition_id",
        "snapshots": "SELECT to_jsonb(d)-'frozen_at' FROM sa_data_snapshots d WHERE pack_version_id=%s ORDER BY data_snapshot_id",
        "golden": "SELECT to_jsonb(g) FROM sa_golden_trajectories g JOIN sa_templates t USING(template_id) "
                  "WHERE t.pack_version_id=%s ORDER BY g.golden_trajectory_id",
    }
    state = {key: [r[0] for r in conn.execute(sql, (pack_version_id,)).fetchall()] for key, sql in queries.items()}
    fingerprint = canonical_hash({"version": version, **state})
    blockers = []
    if not state["templates"] or not state["tasks"]:
        blockers.append("No templates/tasks")
    if not state["snapshots"] or any(not d.get("content_hash") for d in state["snapshots"]):
        blockers.append("Missing frozen data")
    for template in state["templates"]:
        kinds = {g["kind"] for g in state["golden"] if g["template_id"] == template["template_id"]}
        needed = {"success", "alt_success", "near_miss", "forbidden"} if template["is_representative"] else {"success"}
        if not needed <= kinds:
            blockers.append(f"Missing golden: {template['code']}")
    checks_rows = conn.execute("SELECT kind,target,result,detail,checked_by FROM sa_env_checks "
                               "WHERE pack_version_id=%s ORDER BY checked_at,env_check_id", (pack_version_id,)).fetchall()
    latest = {(r[0], r[1]): r for r in checks_rows}
    targets = [(kind, "pack") for kind in ("tool_shape", "data_design", "prompt_leak")]
    targets += [("golden_test", t["code"]) for t in state["templates"]]
    for key in targets:
        check = latest.get(key)
        if (check is None or check[2] != "pass" or check[4] is None
                or check[3].get("pack_fingerprint") != fingerprint
                or (key[0] == "golden_test" and not check[3].get("product_grader_version"))):
            blockers.append(f"Independent current validation required: {key[0]}/{key[1]}")
    return {"pack_version_id": pack_version_id, "pack_fingerprint": fingerprint, "blockers": blockers,
            "ready": not blockers}
