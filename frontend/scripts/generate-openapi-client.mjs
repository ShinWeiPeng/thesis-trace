import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { generateClient } from "./openapi-generator.mjs";

const root = resolve(import.meta.dirname, ".."); const projectRoot = resolve(root, ".."); const target = resolve(root, "src/generated/api.ts");
const python = process.platform === "win32" ? resolve(projectRoot, "backend/.venv/Scripts/python.exe") : resolve(projectRoot, "backend/.venv/bin/python");
let exported;
try { exported = execFileSync(python, ["-m", "thesis_trace.entrypoints.export_openapi"], { cwd: projectRoot, env: { ...process.env, PYTHONPATH: resolve(projectRoot, "backend/src") }, encoding: "utf8" }); }
catch (error) { if (!error.stdout) throw error; exported = String(error.stdout); }
const document = JSON.parse(exported); const canonical = JSON.stringify(document); const hash = createHash("sha256").update(canonical).digest("hex");
const generated = generateClient(document, hash);
if (process.argv.includes("--check")) { if (await readFile(target, "utf8") !== generated) throw new Error(`generated client is stale (backend OpenAPI sha256 ${hash})`); }
else await writeFile(target, generated);
