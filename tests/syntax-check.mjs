#!/usr/bin/env node
/**
 * Syntax-check every JavaScript module in the package.
 *
 * Replaces a hand-maintained file list, which had silently stopped covering new
 * modules: a syntax error in `lib/index.js` reached the contract test because
 * `npm run check` enumerated stale file names. Enumeration is now dynamic.
 *
 * Usage: node tests/syntax-check.mjs
 */
import { spawnSync } from "node:child_process";
import { readdirSync, statSync } from "node:fs";
import { dirname, extname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SKIP = new Set(["node_modules", ".git", ".obsolete"]);
const ROOTS = ["lib", "tests"];

/** Recursively collect .js/.mjs files under a directory. */
function collect(dir, found = []) {
	let entries;
	try {
		entries = readdirSync(dir);
	} catch {
		return found;
	}
	for (const entry of entries) {
		if (SKIP.has(entry)) continue;
		const path = join(dir, entry);
		if (statSync(path).isDirectory()) collect(path, found);
		else if ([".js", ".mjs"].includes(extname(entry))) found.push(path);
	}
	return found;
}

const files = ROOTS.flatMap((root) => collect(join(ROOT, root))).sort();
const failures = [];

for (const file of files) {
	const result = spawnSync(process.execPath, ["--check", file], { encoding: "utf8" });
	if (result.status !== 0) {
		const line = (result.stderr ?? "").split("\n").find((text) => text.includes("SyntaxError")) ?? "syntax error";
		failures.push(`${relative(ROOT, file)}: ${line.trim()}`);
	}
}

console.log(`${files.length} modules checked, ${failures.length} failed`);
for (const failure of failures) console.log(`  FAIL ${failure}`);
process.exitCode = failures.length === 0 ? 0 : 1;
