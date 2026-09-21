/**
 * Shared helpers for the research-check plugin: Python resolution, bounded
 * process execution, JSON reading, and result shaping.
 * @module dsh-research-check/util
 */
import { spawn, spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
/** Directory holding the Python checkers shipped with this plugin. */
export const PYTHON_DIR = resolve(HERE, "..", "python");

/** Environment variable that overrides Python interpreter discovery. */
export const PYTHON_ENV = "DSH_RESEARCH_PYTHON";

/**
 * Resolve a Python 3 interpreter. Tries the explicit override first, then the
 * common Windows and POSIX launchers.
 * @returns The interpreter command name, or `undefined` when none is found.
 */
export function resolvePython() {
	const override = process.env[PYTHON_ENV];
	if (override !== undefined && override.trim() !== "") return override.trim();
	const candidates = process.platform === "win32"
		? [["python", []], ["py", ["-3"]], ["python3", []]]
		: [["python3", []], ["python", []]];
	for (const [command, prefix] of candidates) {
		const probe = spawnSync(command, [...prefix, "--version"], {
			stdio: "ignore",
			timeout: 4000,
			windowsHide: true
		});
		if (probe.status === 0) return prefix.length > 0 ? `${command} ${prefix.join(" ")}` : command;
	}
	return undefined;
}

/** Split a resolved interpreter string into command plus leading arguments. */
export function interpreterArgv(resolved) {
	const parts = resolved.split(" ").filter((part) => part !== "");
	return { command: parts[0], prefix: parts.slice(1) };
}

/**
 * Run one of the packaged Python checkers and parse its JSON report.
 * @param script - Checker file name inside `python/`.
 * @param args - Arguments passed to the checker.
 * @param options - `cwd` for relative input paths and an overall timeout.
 * @returns The parsed report, or a structured failure object.
 */
export function runChecker(script, args, options = {}) {
	const python = resolvePython();
	if (python === undefined) return Promise.resolve({
		ok: false,
		error: "NO_PYTHON",
		message: `No Python 3 interpreter found. Install Python 3.10+ or set ${PYTHON_ENV} to an interpreter path.`
	});
	const scriptPath = join(PYTHON_DIR, script);
	if (!existsSync(scriptPath)) return Promise.resolve({
		ok: false,
		error: "MISSING_CHECKER",
		message: `Checker not found: ${scriptPath}`
	});
	const timeoutMs = options.timeoutMs ?? 180000;
	return new Promise((settle) => {
		const { command, prefix } = interpreterArgv(python);
		const child = spawn(command, [...prefix, scriptPath, ...args], {
			cwd: options.cwd ?? process.cwd(),
			env: { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1" },
			stdio: ["ignore", "pipe", "pipe"]
		});
		let stdout = "";
		let stderr = "";
		let settled = false;
		const timer = setTimeout(() => {
			if (settled) return;
			settled = true;
			child.kill();
			settle({
				ok: false,
				error: "TIMEOUT",
				message: `Checker exceeded ${timeoutMs} ms: ${script}`
			});
		}, timeoutMs);
		child.stdout.setEncoding("utf8");
		child.stderr.setEncoding("utf8");
		child.stdout.on("data", (chunk) => { stdout += chunk; });
		child.stderr.on("data", (chunk) => { stderr += chunk; });
		child.on("error", (error) => {
			if (settled) return;
			settled = true;
			clearTimeout(timer);
			settle({ ok: false, error: "SPAWN_FAILED", message: String(error?.message ?? error) });
		});
		child.on("close", (code) => {
			if (settled) return;
			settled = true;
			clearTimeout(timer);
			const parsed = parseJson(stdout);
			if (parsed === undefined) {
				settle({
					ok: false,
					error: "BAD_OUTPUT",
					message: `Checker did not emit JSON (exit ${code}).`,
					stderr: stderr.slice(-4000),
					stdout: stdout.slice(-2000)
				});
				return;
			}
			settle(parsed);
		});
	});
}

/** Parse the last JSON object printed by a checker (leading logs tolerated). */
export function parseJson(text) {
	const trimmed = text.trim();
	if (trimmed === "") return undefined;
	try {
		return JSON.parse(trimmed);
	} catch {
		const start = trimmed.indexOf("{");
		const end = trimmed.lastIndexOf("}");
		if (start === -1 || end <= start) return undefined;
		try {
			return JSON.parse(trimmed.slice(start, end + 1));
		} catch {
			return undefined;
		}
	}
}

/** Read a JSON file, returning `undefined` when it is absent or malformed. */
export function readJson(path) {
	try {
		return JSON.parse(readFileSync(path, "utf8"));
	} catch {
		return undefined;
	}
}

/** Resolve a user-supplied path against the plugin working directory. */
export function resolveInput(path, cwd) {
	if (isAbsolute(path)) return path;
	return resolve(cwd ?? process.cwd(), path);
}

/**
 * Aggregate findings into a headline verdict shared by every checker tool.
 * @param findings - Individual check results carrying `level`.
 * @returns Counts plus the worst level seen.
 */
export function summarize(findings) {
	const counts = { error: 0, warning: 0, info: 0 };
	for (const finding of findings) {
		const level = finding?.level ?? "info";
		if (level in counts) counts[level] += 1;
	}
	const verdict = counts.error > 0 ? "fail" : counts.warning > 0 ? "warn" : "pass";
	return { verdict, counts, total: findings.length };
}
