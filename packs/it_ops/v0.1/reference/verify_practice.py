"""P-03 명세의 고정 데이터 해시·도구 스키마·capability 포괄 여부를 검증한다."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "backend/src"))

from deployment_answer import PACK_DIR
from jsonschema import Draft202012Validator
from slotagent.common.hashing import canonical_hash


def verify_practice(pack_dir=PACK_DIR, require_launchable=False):
    pack_dir = Path(pack_dir).resolve()
    manifest = json.loads((pack_dir / "practice/servers.json").read_text(encoding="utf-8"))
    pack = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
    if (manifest["pack_code"], manifest["pack_version"]) != (
        pack["pack_version"]["pack_code"], pack["pack_version"]["version"]
    ):
        raise ValueError("Practice manifest belongs to another pack version")
    datasets = {}
    if len({s["id"] for s in manifest["snapshots"]}) != len(manifest["snapshots"]):
        raise ValueError("Duplicate snapshot ID")
    for snapshot in manifest["snapshots"]:
        path = (pack_dir / snapshot["path"]).resolve()
        if not path.is_relative_to(pack_dir / "data"):
            raise ValueError("Only data directory may be mounted")
        if snapshot["container_path"] != "/data/" + path.name or not snapshot["read_only"]:
            raise ValueError("Data must be mounted read-only at its allowlisted path")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["snapshot_version"] != snapshot["version"] or canonical_hash(data) != snapshot["content_hash"]:
            raise ValueError(f"Frozen data mismatch: {snapshot['id']}")
        datasets[snapshot["id"]] = data
    capabilities = set()
    launchable = True
    tool_count = 0
    for server in manifest["services"]:
        ready = (server["status"] == "ready" and isinstance(server["image"], str)
                 and ("@sha256:" in server["image"] or server["image"].startswith("sha256:")) and bool(server["command"]))
        launchable = launchable and ready
        if server["transport"] != "stdio" or server["lifecycle"]["container_scope"] != "trial_attempt":
            raise ValueError("P-03 requires a fresh stdio container per trial attempt")
        names = set()
        for tool in server["tools"]:
            if tool["name"] in names:
                raise ValueError("Duplicate tool name")
            names.add(tool["name"])
            if tool["source_snapshot"] not in server["snapshots"]:
                raise ValueError("Tool uses an undeclared snapshot")
            for key in ("input_schema", "output_schema"):
                Draft202012Validator.check_schema(tool[key])
            Draft202012Validator(tool["input_schema"]).validate({})
            Draft202012Validator(tool["input_schema"]).validate({"repo": "acme/ops-service"})
            rows = datasets[tool["source_snapshot"]][tool["source_key"]]
            Draft202012Validator(tool["output_schema"]).validate(rows)
            capabilities.update(tool["capabilities"])
            tool_count += 1
    required = {c for template in pack["templates"] for c in template["required_capabilities"]}
    if not required <= capabilities:
        raise ValueError(f"Missing capabilities: {required - capabilities}")
    if require_launchable and not launchable:
        raise ValueError("Practice server image/command is not built or pinned yet")
    return {"spec_checks_passed": True, "launchable": bool(launchable), "snapshots": len(datasets),
            "tools": tool_count, "templates_covered_by_capability": len(pack["templates"]),
            "actual_mcp_verified": False}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-launchable", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify_practice(require_launchable=args.require_launchable), ensure_ascii=False, indent=2))
