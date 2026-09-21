/**
 * Standalone contract test — runs with no DSH checkout and no dependencies.
 *
 * `tests/contract.mjs` verifies the same contract against the real harness, but it
 * needs a profile directory and installed peers. CI has neither, so this variant
 * imports the plugin through a stub `defineTool` that enforces the two rules that
 * actually broke a profile boot before:
 *
 *   1. `Config` must implement the Standard Schema interface;
 *   2. every tool must supply `output.render`.
 *
 * It also checks the surface a marketplace listing depends on: four tools, one
 * embedded skill, finite section orders, and a rule vocabulary that matches the
 * Python checker's registry.
 *
 * Usage: node tests/contract-standalone.mjs
 */
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineTool } from "./stub-tools.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..");
const failures = [];
const passes = [];

function check(label, condition, detail) {
	if (condition) passes.push(label);
	else failures.push(detail === undefined ? label : `${label} — ${detail}`);
}

// ---------------------------------------------------------------- schema types
// The stub must accept the same parameter shapes the real tools declare, otherwise
// it would reject valid definitions and hide real problems.

// Import the plugin. It imports @deepseek-ai/* at module scope, so rewrite those two
// imports to the local stubs instead of requiring a DSH install. The shim lives in
// tests/, so the plugin's own relative imports must be rebased onto ../lib/.
const pluginSource = readFileSync(join(ROOT, "lib", "index.js"), "utf8")
	.replace('import z from "@deepseek-ai/schemastery";', 'import z from "./stub-schemastery.js";')
	.replace('import { defineTool } from "@deepseek-ai/dsh-tools";', 'import { defineTool } from "./stub-tools.js";')
	.replace(/from "\.\/(?!stub-)/gu, 'from "../lib/');

const shimPath = join(ROOT, "tests", ".index.shim.mjs");
const { writeFileSync, unlinkSync } = await import("node:fs");
writeFileSync(shimPath, pluginSource, "utf8");
let plugin;
try {
	plugin = await import(`${new URL(`file://${shimPath.replace(/\\/gu, "/")}`).href}?t=${Date.now()}`);
} finally {
	unlinkSync(shimPath);
}

check("plugin exposes apply()", typeof plugin.apply === "function");
check("plugin exposes inject[]", Array.isArray(plugin.inject));

// ---------------------------------------------------------------- config schema
const standard = plugin.Config?.["~standard"];
check("Config implements Standard Schema", standard !== undefined);
check("Config.validate applies defaults",
	typeof standard?.validate === "function" && standard.validate({})?.value?.guidance === "");
check("Config rejects a wrong type",
	Array.isArray(standard?.validate({ guidance: 1 })?.issues));

// ---------------------------------------------------------------- registration
const registered = [];
const skills = [];
const orders = [];
const ctx = {
	tools: { register: (tool) => registered.push(tool) },
	skills: { register: (skill) => skills.push(skill) },
	systemPrompt: { section: (entry) => orders.push(entry.order) }
};
try {
	plugin.apply(ctx, {});
	passes.push("apply() completes with the stub context");
} catch (error) {
	failures.push(`apply() threw: ${error?.message ?? error}`);
}

check("section orders are finite numbers",
	orders.length > 0 && orders.every((order) => Number.isFinite(order)), JSON.stringify(orders));
check("four tools registered", registered.length === 4, `got ${registered.length}`);
for (const name of ["research_audit", "research_numbers", "research_ledger", "research_spec"]) {
	const tool = registered.find((item) => item.name === name);
	check(`tool ${name} registered`, tool !== undefined);
	if (tool === undefined) continue;
	check(`${name} has an object parameter schema`, tool.parameters?.type === "object");
	check(`${name} exposes output.render`, typeof tool.output?.render === "function");
	check(`${name} renders JSON text`, tool.output.render({}, { ok: true })?.[0]?.type === "text");
}
check("embedded skill registered", skills.length === 1, `got ${skills.length}`);
check("skill name is kebab-case",
	/^[a-z0-9]+(-[a-z0-9]+)*$/u.test(skills[0]?.name ?? ""), skills[0]?.name);

// ---------------------------------------------------------------- vocabulary sync
const checkerSource = readFileSync(join(ROOT, "python", "check_spec.py"), "utf8");
const block = /KNOWN_CHECKS[^{]*\{([\s\S]*?)\n\}/u.exec(checkerSource);
const pythonChecks = new Set(
	[...(block?.[1] ?? "").matchAll(/"([a-z_]+)":/gu)].map((match) => match[1]));
const specToolPath = join(ROOT, "lib", "spec-tool.js");
const vocabularySource = readFileSync(specToolPath, "utf8");
const vocabBlock = /RULE_VOCABULARY = \[([\s\S]*?)\];/u.exec(vocabularySource);
const jsChecks = new Set([...(vocabBlock?.[1] ?? "").matchAll(/"([a-z_]+)"/gu)].map((m) => m[1]));
const missingInJs = [...pythonChecks].filter((name) => !jsChecks.has(name));
const missingInPy = [...jsChecks].filter((name) => !pythonChecks.has(name) && name !== "manual");
check("rule vocabulary matches the Python checker",
	missingInJs.length === 0 && missingInPy.length === 0,
	`只在 Python 有：${missingInJs.join(",") || "无"}；只在 JS 有：${missingInPy.join(",") || "无"}`);

// The profiles the tool advertises must match the packs the builder actually loads.
const packsSource = readFileSync(join(ROOT, "python", "rule_packs.py"), "utf8");
const packsBlock = /PROFILE_PACKS[^{]*\{([\s\S]*?)\n\}/u.exec(packsSource);
const pythonProfiles = new Set([...(packsBlock?.[1] ?? "").matchAll(/"([a-z]+)":/gu)].map((m) => m[1]));
const profileBlock = /export const PROFILES = \{([\s\S]*?)\n\};/u.exec(vocabularySource);
const jsProfiles = new Set([...(profileBlock?.[1] ?? "").matchAll(/^\s*([a-z]+):/gmu)].map((m) => m[1]));
const profileGap = [...pythonProfiles].filter((name) => !jsProfiles.has(name));
check("advertised profiles match the rule packs",
	profileGap.length === 0,
	`Python 有而 JS 未声明：${profileGap.join(",") || "无"}（JS: ${[...jsProfiles].join(",")}）`);

// ---------------------------------------------------------------- manifest sync
const manifest = JSON.parse(readFileSync(join(ROOT, "package.json"), "utf8"));
for (const relative of ["lib/spec-tool.js", "python/check_spec.py", "python/spec_build.py", "skill/SKILL.md"]) {
	check(`packaged file: ${relative}`, readFileSync(join(ROOT, relative), "utf8").length > 200);
}
check("version matches CHANGELOG",
	readFileSync(join(ROOT, "CHANGELOG.md"), "utf8").includes(`## [${manifest.version}]`),
	`package.json ${manifest.version}`);

console.log(`${passes.length} passed, ${failures.length} failed`);
for (const label of failures) console.log(`  FAIL ${label}`);
process.exitCode = failures.length === 0 ? 0 : 1;
