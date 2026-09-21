/**
 * Marketplace/manifest readiness checks.
 *
 * Verified against the community registry (`awesome-dsh-plugin`) entry shape and
 * the DSH loader's own expectations: a plugin is distributed as a normal npm
 * package that declares a `dsh.bundle.patch`, so the machine-checkable parts of
 * "ready to list" are: valid manifest, every declared field present, every file
 * referenced by `files`/`exports` actually existing, a packaged skill, a README
 * with install instructions, and a licence.
 *
 * Run from anywhere: it reads only the package directory.
 *   node tests/registry-manifest.mjs
 */
import { existsSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..");
const failures = [];
const passes = [];

function check(label, condition, detail) {
	if (condition) passes.push(label);
	else failures.push(detail === undefined ? label : `${label} — ${detail}`);
}

const manifest = JSON.parse(readFileSync(join(ROOT, "package.json"), "utf8"));

// ---------------------------------------------------------------- identity
check("name is lowercase and npm-safe", /^[a-z0-9][a-z0-9._-]*$/u.test(manifest.name), manifest.name);
check("version is semver", /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/u.test(manifest.version), manifest.version);
check("description present and substantial",
	typeof manifest.description === "string" && manifest.description.length >= 120,
	`length ${String(manifest.description ?? "").length}; registry listings show this text verbatim`);
check("description carries both English and Chinese",
	(manifest.description ?? "").replace(/[^A-Za-z]/gu, "").length >= 80
	&& /[\u4e00-\u9fa5]{6}/u.test(manifest.description ?? ""),
	"community registry stores {en, zh}; a bilingual description maps onto it directly");
check("license declared", typeof manifest.license === "string" && manifest.license !== "");
check("keywords include marketplace discovery terms",
	Array.isArray(manifest.keywords)
	&& ["dsh", "dsh-plugin", "deepseek"].every((word) => manifest.keywords.includes(word)),
	JSON.stringify(manifest.keywords));

// ---------------------------------------------------------------- DSH wiring
const bundle = manifest.dsh?.bundle;
check("dsh.bundle.patch declared", typeof bundle?.patch === "string", "the loader mounts bundles through this patch");
if (typeof bundle?.patch === "string") {
	const patchPath = join(ROOT, bundle.patch);
	check("patch file exists", existsSync(patchPath), bundle.patch);
	if (existsSync(patchPath)) {
		const patch = readFileSync(patchPath, "utf8");
		check("patch inserts this package by name", patch.includes(`name: ${manifest.name}`), bundle.patch);
	}
}
check("dsh.compatibility lists at least one release",
	Object.keys(manifest.dsh?.compatibility?.dshReleases ?? {}).length > 0,
	"the market surfaces compatibility; silent drift is the failure mode");
check("entry point exports the plugin surface",
	manifest.main === "lib/index.js" || existsSync(join(ROOT, manifest.main ?? "")),
	String(manifest.main));

// ---------------------------------------------------------------- packaging
const required = ["README.md", "CHANGELOG.md", "LICENSE", "lib/index.js", "skill/SKILL.md", "python/check_numbers.py"];
for (const relative of required) {
	check(`packaged file present: ${relative}`, existsSync(join(ROOT, relative)));
}
for (const pattern of manifest.files ?? []) {
	const clean = pattern.replace(/\/$/u, "");
	check(`files[] entry exists: ${pattern}`, existsSync(join(ROOT, clean)));
}

const skillPath = join(ROOT, "skill/SKILL.md");
if (existsSync(skillPath)) {
	const skill = readFileSync(skillPath, "utf8");
	const front = /^---\r?\n([\s\S]*?)\r?\n---/u.exec(skill);
	check("SKILL.md has YAML frontmatter", front !== null);
	if (front !== null) {
		const body = front[1];
		const nameMatch = /^name:\s*(\S+)/mu.exec(body);
		check("skill name present and kebab-case",
			nameMatch !== null && /^[a-z0-9]+(-[a-z0-9]+)*$/u.test(nameMatch[1]),
			nameMatch?.[1] ?? "missing");
		check("skill description present", /^description:\s*\S/mu.test(body));
		check("skill uses canonical invocation keys only",
			!/(?:^|\n)(modelInvocable|userInvocable|disableModelInvocation):/mu.test(body),
			"filesystem provider rejects the legacy keys; use disable-model-invocation / user-invocable");
	}
	check("skill body is substantive", skill.split("\n").length >= 40, `${skill.split("\n").length} lines`);
}

const readmePath = join(ROOT, "README.md");
if (existsSync(readmePath)) {
	const readme = readFileSync(readmePath, "utf8");
	check("README documents installation", /dsh plugin --profile/iu.test(readme));
	check("README documents the install command for the market", /add\s+dsh-research-check|add link:/u.test(readme));
	check("README names the three tools",
		["research_audit", "research_numbers", "research_ledger"].every((tool) => readme.includes(tool)));
}

const licensePath = join(ROOT, "LICENSE");
if (existsSync(licensePath)) {
	const license = readFileSync(licensePath, "utf8");
	check("LICENSE is a real licence text", /MIT License/u.test(license) && statSync(licensePath).size > 500);
}

// ---------------------------------------------------------------- runtime
const runtimeDeps = Object.keys(manifest.dependencies ?? {});
check("no runtime dependencies", runtimeDeps.length === 0,
	`keeps the plugin installable into any profile; found ${runtimeDeps.join(", ")}`);
check("DSH peers declared as optional peerDependencies",
	["@deepseek-ai/dsh-tools", "@deepseek-ai/schemastery"].every((peer) => manifest.peerDependencies?.[peer] !== undefined));

console.log(`${passes.length} passed, ${failures.length} failed`);
for (const label of passes) console.log(`  ok   ${label}`);
for (const label of failures) console.log(`  FAIL ${label}`);
process.exitCode = failures.length === 0 ? 0 : 1;
