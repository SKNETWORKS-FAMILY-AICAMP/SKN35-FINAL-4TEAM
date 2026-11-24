"""loader 사전 검증, 정책 저장 전제 및 실제 DB 롤백 테스트."""

import importlib.util
import json
import os
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from slotagent.common import contracts
from slotagent.packs.loader import load_pack, read_pack

ROOT = Path(__file__).resolve().parents[2]
READ_PACK = ROOT / "packs/it_ops/v0.1"
WRITE_PACK = ROOT / "packs/it_ops_writes/v0.1"


def test_read_and_write_pack_validation():
    pack, snapshots, golden = read_pack(READ_PACK)
    assert len(pack["tasks"]) == 47 and len(snapshots) == 3 and len(golden) == 60
    pack, snapshots, golden = read_pack(WRITE_PACK)
    assert len(pack["templates"]) == 2 and len(pack["tasks"]) == 6
    assert len(snapshots) == 1 and len(golden) == 8
    assert all("confirmation" not in task["slot_values"] for task in pack["tasks"])


@pytest.mark.parametrize("change", ["policy", "task_ref", "snapshot_path", "duplicate"])
def test_invalid_pack_rejected_before_database(tmp_path, change):
    shutil.copytree(WRITE_PACK, tmp_path / "pack")
    path = tmp_path / "pack/pack.json"
    pack = json.loads(path.read_text(encoding="utf-8"))
    if change == "policy":
        pack["tasks"][0]["confirmation"] = {"bad": True}
    elif change == "task_ref":
        pack["tasks"][0]["template"] = "unknown"
    elif change == "snapshot_path":
        pack["data_snapshots"][0]["location"] = "../secret.json"
    else:
        pack["tasks"].append(pack["tasks"][0])
    path.write_text(json.dumps(pack), encoding="utf-8")
    with pytest.raises(ValueError):
        load_pack(None, path.parent)


def test_write_scenarios(tmp_path):
    spec = importlib.util.spec_from_file_location("write_smoke", WRITE_PACK / "smoke.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.run(tmp_path)
    assert result["runs"] == 28 and result["all_matched"]
    for item in result["results"]:
        if item["scenario"] == "omit_write":
            assert not item["forbidden_action"] and not item["conditions"]["2"]
        if item["scenario"] in {"without_confirmation", "changed_after_approval"}:
            assert item["forbidden_action"]
    pack = json.loads((WRITE_PACK / "pack.json").read_text(encoding="utf-8"))
    for task in pack["tasks"]:
        trace = module.simulate(task, "normal")
        contracts.validate("trace", trace)
    for entry in pack["golden"]:
        trace = json.loads((WRITE_PACK / entry["trace"]).read_text(encoding="utf-8"))
        task = next(t for t in pack["tasks"] if t["code"] == entry["task_code"])
        assert module.grade(task, trace) == entry["expected"]


@pytest.mark.skipif(os.environ.get("SLOTAGENT_RUN_DB_TESTS") != "1", reason="Explicit local DB opt-in required")
def test_postgres_draft_load_and_missing_policy_column(tmp_path):
    from slotagent.common.db import connect

    shutil.copytree(READ_PACK, tmp_path / "pack")
    path = tmp_path / "pack/pack.json"
    pack = json.loads(path.read_text(encoding="utf-8"))
    version = "loader-test-" + uuid4().hex
    pack["pack_version"]["version"] = version
    path.write_text(json.dumps(pack), encoding="utf-8")
    with connect() as conn, conn.transaction(force_rollback=True):
        conn.execute("INSERT INTO sa_domains(domain_code,name,status) VALUES ('it_ops','IT 운영','pilot') "
                     "ON CONFLICT DO NOTHING")
        pack_id = load_pack(conn, path.parent)
        assert conn.execute("SELECT status FROM sa_pack_versions WHERE pack_version_id=%s", (pack_id,)).fetchone()[0] == "draft"
        assert conn.execute("SELECT count(*) FROM sa_tasks JOIN sa_templates USING(template_id) "
                            "WHERE pack_version_id=%s", (pack_id,)).fetchone()[0] == 47
        assert conn.execute("SELECT count(*) FROM sa_golden_trajectories JOIN sa_templates USING(template_id) "
                            "WHERE pack_version_id=%s", (pack_id,)).fetchone()[0] == 60
        from slotagent.packs.loader import lock_pack, pack_readiness
        from slotagent.packs.select import select_tasks

        readiness = pack_readiness(conn, pack_id)
        assert not readiness["ready"] and readiness["pack_fingerprint"].startswith("sha256:")
        with pytest.raises(ValueError, match="validation required"):
            lock_pack(conn, pack_id)
        with pytest.raises(ValueError, match="locked pack"):
            select_tasks(conn, pack_id, 1, split="dev")
        column_exists = conn.execute("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE "
                                     "table_schema='public' AND table_name='sa_tasks' AND column_name='confirmation')").fetchone()[0]
        if not column_exists:
            with pytest.raises(ValueError, match="migration first"):
                load_pack(conn, WRITE_PACK)
        else:
            write_id = load_pack(conn, WRITE_PACK)
            assert conn.execute("SELECT count(*) FROM sa_tasks JOIN sa_templates USING(template_id) "
                                "WHERE pack_version_id=%s AND confirmation IS NOT NULL", (write_id,)).fetchone()[0] == 6
    # 삽입한 모든 행은 위 트랜잭션에서 롤백한다.
