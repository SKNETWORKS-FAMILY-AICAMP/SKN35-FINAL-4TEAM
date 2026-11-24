import { readFile, writeFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { compile } from "json-schema-to-typescript";

const here = path.dirname(fileURLToPath(import.meta.url));
const schemaDir = path.resolve(here, "../../contracts/schemas");
const schema = JSON.parse(await readFile(path.join(schemaDir, "api.schema.json"), "utf8"));
// The source API schema has only $defs. Export each definition through a root
// property so the generator preserves all request/response types and resolves
// relative references from the actual contracts directory.
const root = { ...schema, title: "ApiContracts", type: "object", additionalProperties: false,
  properties: Object.fromEntries(Object.keys(schema.$defs).map((key) => [key, { $ref: `#/$defs/${key}` }])) };
const result = await compile(root, "ApiContracts", { cwd: schemaDir, declareExternallyReferenced: true, bannerComment: "/* Generated from contracts/schemas/api.schema.json. Run npm run generate:types; do not edit. */" });
await mkdir(path.resolve(here, "../src/types"), { recursive: true });
await writeFile(path.resolve(here, "../src/types/contracts.ts"), result);
console.log("Generated src/types/contracts.ts from repository contracts.");
