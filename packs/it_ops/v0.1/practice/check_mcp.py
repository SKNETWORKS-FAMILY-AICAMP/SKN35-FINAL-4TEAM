"""실제 stdio MCP 세션으로 서버·도구·버전·데이터·오류 동작을 확인한다."""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from server import PracticeData

HERE = Path(__file__).resolve().parent


async def check(command, args):
    manifest = json.loads((HERE / "servers.json").read_text(encoding="utf-8"))
    expected_data = PracticeData(HERE / "servers.json", HERE.parent / "data")
    async with stdio_client(StdioServerParameters(command=command, args=args)) as streams:
        async with ClientSession(*streams, read_timeout_seconds=15) as session:
            initialized = await session.initialize()
            listed = await session.list_tools()
            expected = {t["name"]: t for t in manifest["services"][0]["tools"]}
            assert {t.name for t in listed.tools} == set(expected)
            for tool in listed.tools:
                assert tool.input_schema == expected[tool.name]["input_schema"]
                assert tool.description == expected[tool.name]["semantics"]
            metadata_result = await session.read_resource("slotagent://practice/manifest")
            metadata = json.loads(metadata_result.contents[0].text)
            assert metadata["version"] == manifest["services"][0]["version"]
            assert metadata["data_version"] == manifest["services"][0]["data_version"]
            assert metadata["snapshot_hashes"] == {s["id"]: s["content_hash"] for s in manifest["snapshots"]}
            calls = 0
            for name, tool in expected.items():
                rows = expected_data.call(name, {})
                for arguments in ({}, *({"repo": repo} for repo in sorted({r["repo"] for r in rows})),
                                  {"repo": "acme/no-such-repository"}):
                    result = await session.call_tool(name, arguments)
                    assert not result.is_error
                    assert json.loads(result.content[0].text) == expected_data.call(name, arguments)
                    calls += 1
                result = await session.call_tool(name, {"unexpected": True})
                assert result.is_error
                calls += 1
    return {"checked_at": datetime.now(UTC).isoformat(), "transport": "stdio", "passed": True,
            "server_version": initialized.server_info.version, "tools": len(expected), "calls": calls,
            "data_version": metadata["data_version"], "snapshot_hashes": metadata["snapshot_hashes"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-image")
    parser.add_argument("--report", type=Path, default=Path("tmp/practice-mcp-check.json"))
    options = parser.parse_args()
    if options.docker_image:
        arguments = ["run", "--rm", "-i", "--network=none", "--read-only", "--cap-drop=ALL",
                     "--security-opt=no-new-privileges", "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m"]
        for name in ("deployments.json", "issues.json", "operations.json"):
            arguments += ["--mount", f"type=bind,source={(HERE.parent / 'data' / name).resolve()},target=/data/{name},readonly"]
        arguments.append(options.docker_image)
        result = asyncio.run(check("docker", arguments))
        result["image"] = options.docker_image
    else:
        result = asyncio.run(check(sys.executable, [str(HERE / "server.py")]))
    options.report.parent.mkdir(parents=True, exist_ok=True)
    options.report.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
