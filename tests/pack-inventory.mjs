#!/usr/bin/env node
/**
 * Packed-inventory test: assert what `npm pack` would actually ship.
 *
 * Motivated by a real defect: the plugin was published with Python bytecode caches
 * inside it (30 files / 149 kB instead of 25 / 125 kB), because `.gitignore` has no
 * effect on npm packing, and `package.json`'s `files` allow-list cannot exclude a
 * subdirectory of a listed directory. Nothing in the suite noticed, because the
 * tarball worked — it was merely wrong for users.
 *
 * The check is deliberately behavioural: it runs the real packer rather than reading
 * configuration, so any future re-inclusion (a new directory in `files`, a stray
 * artifact) fails here.
 *
 * Usage: node tests/pack-inventory.mjs
 */
import { execFileSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const failures = [];
const passes = [];
function check(label, condition, detail) {
	if (condition) passes.push(label);
	else failures.push(detail === undefined ? label : `${label} — ${detail}`);
}

/** Ask npm what it would pack (no tarball is written). */
function dryRun() {
	// Windows cannot exec the npm shim directly and `shell: true` triggers Node's
	// argument-concatenation warning, so route through cmd.exe like the boot check does.
	const target = process.platform === "win32"
		? { file: process.env.COMSPEC ?? "cmd.exe", args: ["/d", "/s", "/c", "npm pack --dry-run --json"] }
		: { file: "npm", args: ["pack", "--dry-run", "--json"] };
	const output = execFileSync(target.file, target.args, { cwd: ROOT, encoding: "utf8" });
	const parsed = JSON.parse(output);
	return parsed[0];
}

let report;
try {
	report = dryRun();
} catch (error) {
	console.log(`无法执行 npm pack：${String(error?.message ?? error)}`);
	process.exit(2);
}

const files = report.files.map((entry) => entry.path.replace(/\\/gu, "/"));
const names = new Set(files);

// ---------------------------------------------------------------- exclusions
const cacheEntries = files.filter((path) => path.includes("__pycache__") || path.endsWith(".pyc"));
check("no Python bytecode caches are packed", cacheEntries.length === 0,
	cacheEntries.slice(0, 4).join(", "));

const testEntries = files.filter((path) => path.startsWith("tests/"));
check("development tests are not packed", testEntries.length === 0,
	`${testEntries.length} test files (${testEntries.slice(0, 3).join(", ")})`);

check("no editor or OS metadata is packed",
	!files.some((path) => /(^|\/)(\.vscode|\.idea|\.DS_Store|Thumbs\.db)/u.test(path)));

check("no local ledger or scratch files are packed",
	!files.some((path) => /(ledger\.json|\.tgz$|\.tmp$|\.bak$)/u.test(path)));

// ---------------------------------------------------------------- presence
// Everything needed at install time: the plugin entry, the shared engine, both
// host adapters, the Python checkers with their rule packs, and the skill.
const required = [
	"package.json",
	"lib/index.js",
	"lib/core.js",
	"mcp/server.mjs",
	"cordis.patch.yml",
	"skill/SKILL.md",
	"python/rule_packs.py",
	"python/spec_build.py",
	"python/check_spec.py",
	"python/check_numbers.py",
	"python/audit_paper.py",
	"python/check_hygiene.py",
	"python/encoding_guard.py",
	"README.md",
	"LICENSE"
];
for (const path of required) {
	check(`packed: ${path}`, names.has(path));
}

// Every Python module that ships must be listed by name, or the plugin breaks at runtime
// on a machine that installed from npm — the repository would still work, which is the
// worst kind of divergence: only users hit it.
const PYTHON_MODULES = [
	"python/audit_paper.py",
	"python/check_hygiene.py",
	"python/check_numbers.py",
	"python/check_spec.py",
	"python/encoding_guard.py",
	"python/rule_packs.py",
	"python/spec_build.py"
];
const shippedPython = files.filter((path) => path.startsWith("python/") && path.endsWith(".py"));
for (const module of PYTHON_MODULES) {
	check(`packed python module: ${module.replace("python/", "")}`, names.has(module));
}
check("no unexpected python module ships",
	shippedPython.length === PYTHON_MODULES.length,
	`packed ${shippedPython.length}: ${shippedPython.join(", ")}`);

// ---------------------------------------------------------------- sanity budget
check("total packed files stay lean (<= 30)", report.entryCount <= 30, String(report.entryCount));
check("tarball stays under 150 kB", report.size <= 150 * 1024, `${report.size} bytes`);
check("unpacked size stays under 400 kB", report.unpackedSize <= 400 * 1024, `${report.unpackedSize} bytes`);

console.log(`${passes.length} passed, ${failures.length} failed`);
console.log(`  packed: ${report.entryCount} files, ${(report.size / 1024).toFixed(1)} kB ` +
	`(unpacked ${(report.unpackedSize / 1024).toFixed(1)} kB)`);
for (const label of failures) console.log(`  FAIL ${label}`);
process.exitCode = failures.length === 0 ? 0 : 1;
