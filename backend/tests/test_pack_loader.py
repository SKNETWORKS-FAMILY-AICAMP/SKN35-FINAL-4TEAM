"""loader 사전 검증, 정책 저장 전제 및 실제 DB 롤백 테스트."""

import importlib.util
import json
import os
import shutil
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from slotagent.common import contracts
from slotagent.packs.groups import load_group, read_group
from slotagent.packs.loader import load_pack, lock_pack, pack_content_hash, read_pack, store_pack_content_hash

ROOT = Path(__file__).resolve().parents[2]
READ_PACK = ROOT / "packs/it_ops/v0.1"
WRITE_PACK = ROOT / "packs/it_ops/v0.1"


@pytest.mark.parametrize("present", [False, True])
def test_pack_hash_storage_after_column_migration(present):
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = (present,)
    conn.execute.return_value.rowcount = 1
    pack = {"tasks": [{"code": "test"}]}
    assert store_pack_content_hash(conn, 7, pack) == present
    if present:
        assert conn.execute.call_args.args[1] == (pack_content_hash(pack), 7)
    else:
        assert conn.execute.call_count == 1


def test_pack_lock_sets_timeout_before_locks_and_restores(monkeypatch):
    conn = MagicMock()
    conn.execute.return_value.fetchone.side_effect = [("3s",), ("draft",)]
    monkeypatch.setattr("slotagent.packs.loader.pack_readiness", lambda *args: {"blockers": []})
    lock_pack(conn, 7, lock_timeout_ms=250)
    calls = [c.args for c in conn.execute.call_args_list]
    assert calls[1] == ("SELECT set_config('lock_timeout',%s,true)", ("250ms",))
    assert "FOR UPDATE" in calls[2][0]
    assert calls[-1] == ("SELECT set_config('lock_timeout',%s,true)", ("3s",))


@pytest.mark.parametrize("timeout", [0, -1, True, "5s", 2147483648])
def test_pack_lock_rejects_invalid_timeout_before_database(timeout):
    with pytest.raises(ValueError, match="lock_timeout_ms"):
        lock_pack(None, 7, lock_timeout_ms=timeout)


def test_read_and_write_pack_validation():
    pack, snapshots, golden = read_pack(READ_PACK)
    assert len(pack["tasks"]) == 128 and len(snapshots) == 11 and len(golden) == 168
    pack, snapshots, golden = read_group(WRITE_PACK, "writes")
    assert len(pack["templates"]) == 6 and len(pack["tasks"]) == 18
    assert len(snapshots) == 2 and len(golden) == 24
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
    spec = importlib.util.spec_from_file_location("write_smoke", WRITE_PACK / "reference/evaluators/writes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.run(tmp_path)
    assert result["runs"] == 100 and result["all_matched"]
    for item in result["results"]:
        if item["scenario"] == "omit_write":
            assert not item["forbidden_action"] and not item["conditions"]["2"]
        if item["scenario"] in {"without_confirmation", "changed_after_approval"}:
            assert item["forbidden_action"]
    pack = load_group(WRITE_PACK, "writes")
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
    pack = load_group(READ_PACK, "lookup")
    version = "loader-test-" + uuid4().hex
    pack["pack_version"]["version"] = version
    path.write_text(json.dumps(pack), encoding="utf-8")
    with connect() as conn, conn.transaction(force_rollback=True):
        conn.execute("INSERT INTO sa_domains(domain_code,name,status) VALUES ('it_ops','IT 운영','pilot') "
                     "ON CONFLICT DO NOTHING")
        pack_id = load_pack(conn, path.parent)
        assert conn.execute("SELECT status FROM sa_pack_versions WHERE pack_version_id=%s", (pack_id,)).fetchone()[0] == "draft"
        assert conn.execute("SELECT count(*) FROM sa_tasks JOIN sa_templates USING(template_id) "
                            "WHERE pack_version_id=%s", (pack_id,)).fetchone()[0] == 26
        assert conn.execute("SELECT count(*) FROM sa_golden_trajectories JOIN sa_templates USING(template_id) "
                            "WHERE pack_version_id=%s", (pack_id,)).fetchone()[0] == 32
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
                                "WHERE pack_version_id=%s AND confirmation IS NOT NULL", (write_id,)).fetchone()[0] == 27
    # 삽입한 모든 행은 위 트랜잭션에서 롤백한다.
