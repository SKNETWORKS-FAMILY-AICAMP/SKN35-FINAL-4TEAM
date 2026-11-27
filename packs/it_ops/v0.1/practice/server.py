"""P-03 read-only MCP practice server. No pack answers or user credentials are loaded."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

if len(Path(__file__).resolve().parents) > 4:
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "backend/src"))

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from slotagent.common.hashing import canonical_hash

VERSION = "0.1.1"
RESOURCE = "slotagent://practice/manifest"


class PracticeData:
    def __init__(self, manifest_path, data_dir):
        self.manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        self.server = self.manifest["services"][0]
        if self.server["service"] != "github":
            raise ValueError("This implementation only serves github")
        self.data_dir = Path(data_dir).resolve()
        self.tools = {t["name"]: t for t in self.server["tools"]}
        if self.server["version"] != VERSION:
            raise ValueError("Practice server version mismatch")
        self.data = {}
        self.hashes = {}
        for snapshot in self.manifest["snapshots"]:
            path = (self.data_dir / Path(snapshot["path"]).name).resolve()
            if not path.is_relative_to(self.data_dir):
                raise ValueError("Snapshot escapes data directory")
            data = json.loads(path.read_text(encoding="utf-8"))
            digest = canonical_hash(data)
            if digest != snapshot["content_hash"] or data["snapshot_version"] != snapshot["version"]:
                raise ValueError(f"Frozen snapshot mismatch: {snapshot['id']}")
            self.data[snapshot["id"]] = data
            self.hashes[snapshot["id"]] = digest
        self.rows = {}
        for name, tool in self.tools.items():
            Draft202012Validator.check_schema(tool["input_schema"])
            Draft202012Validator.check_schema(tool["output_schema"])
            Draft202012Validator(tool["output_schema"]).validate(
                self.data[tool["source_snapshot"]][tool["source_key"]])
            self.rows[name] = self.data[tool["source_snapshot"]][tool["source_key"]]
        for family in ((("list_deployments", "run_id", int), ("list_operation_runs", "id", str)),
                       (("list_issues", "number", str), ("list_operation_issues", "id", str))):
            sources = [(name, key, cast, self.rows[name]) for name, key, cast in family]
            identities = set()
            for _, key, _, rows in sources:
                for row in rows:
                    identity = (row["repo"], str(row[key]))
                    if identity in identities:
                        raise ValueError("Conflicting practice record identity")
                    identities.add(identity)
            for name, key, cast, native in sources:
                combined = list(native)
                for other, other_key, _, rows in sources:
                    if other != name:
                        combined.extend({**{k: v for k, v in row.items() if k != other_key},
                                         key: cast(row[other_key])} for row in rows)
                Draft202012Validator(self.tools[name]["output_schema"]).validate(combined)
                self.rows[name] = combined

    def call(self, name, arguments):
        if name not in self.tools:
            raise ValueError("Unknown tool")
        tool = self.tools[name]
        Draft202012Validator(tool["input_schema"]).validate(arguments)
        rows = self.rows[name]
        result = [r for r in rows if "repo" not in arguments or r["repo"] == arguments["repo"]]
        Draft202012Validator(tool["output_schema"]).validate(result)
        return result

    def metadata(self):
        return {"server_id": self.server["server_id"], "version": VERSION,
                "data_version": self.server["data_version"], "snapshot_hashes": self.hashes,
                "tools": [{"name": t["name"], "input_schema": t["input_schema"],
                           "decoded_output_schema": t["output_schema"], "capabilities": t["capabilities"]}
                          for t in self.tools.values()]}


async def serve(data):
    async def list_tools(context, params):
        return types.ListToolsResult(tools=[types.Tool(
            name=t["name"], description=t["semantics"], inputSchema=t["input_schema"],
            annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
        ) for t in data.tools.values()])

    async def call_tool(context, params):
        try:
            result = data.call(params.name, params.arguments or {})
            return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))])
        except (ValueError, KeyError, TypeError, ValidationError) as exc:
            return types.CallToolResult(isError=True, content=[types.TextContent(type="text", text=str(exc))])

    async def list_resources(context, params):
        return types.ListResourcesResult(resources=[types.Resource(
            uri=RESOURCE, name="practice_manifest", mimeType="application/json")])

    async def read_resource(context, params):
        if str(params.uri) != RESOURCE:
            raise ValueError("Unknown resource")
        return types.ReadResourceResult(contents=[types.TextResourceContents(
            uri=RESOURCE, mimeType="application/json", text=json.dumps(data.metadata(), ensure_ascii=False))])

    server = Server("slotagent-github-practice", version=VERSION, on_list_tools=list_tools,
                    on_call_tool=call_tool, on_list_resources=list_resources, on_read_resource=read_resource)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("servers.json"))
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    args = parser.parse_args()
    asyncio.run(serve(PracticeData(args.manifest, args.data_dir)))
