#!/usr/bin/env node
/**
 * Boot verification: start a throwaway instance of a DSH profile on a spare
 * port, confirm it actually serves, then shut it down (process tree included).
 *
 * Why this exists: a plugin can pass every in-process mock and still break the
 * real boot (Config validated against Standard Schema, section orders resolved by
 * the prompt registry, bundles composed in order). Only a real boot proves the
 * profile still comes up. This never touches an already-running instance.
 *
 * Hard guarantees:
 *   - every stage logs to stderr, so a hang is visible instead of silent;
 *   - the whole run is bounded by --timeout, and the child is killed with its
 *     tree (taskkill /T on Windows) so no stray server is left listening.
 *
 * Usage:
 *   node tests/boot-check.mjs [--profile web] [--port 0] [--timeout 60000]
 */
import { spawn, spawnSync } from "node:child_process";
import { createConnection } from "node:net";
import { argv, platform } from "node:process";

function flag(name, fallback) {
	const index = argv.indexOf(`--${name}`);
	return index >= 0 && argv[index + 1] !== undefined ? argv[index + 1] : fallback;
}

const profile = flag("profile", "web");
const requestedPort = Number(flag("port", "0"));
const timeoutMs = Number(flag("timeout", "60000"));
const started = Date.now();
const log = (message) => process.stderr.write(`[boot-check +${Date.now() - started}ms] ${message}\n`);

const command = platform === "win32" ? "dsh.cmd" : "dsh";
const args = ["--profile", profile, "--port", String(requestedPort), "--no-open"];
const spawnTarget = platform === "win32"
	? { file: process.env.COMSPEC ?? "cmd.exe", args: ["/d", "/s", "/c", command, ...args] }
	: { file: command, args };
log(`spawning: ${spawnTarget.file} ${spawnTarget.args.join(" ")}`);

const child = spawn(spawnTarget.file, spawnTarget.args, {
	stdio: ["ignore", "pipe", "pipe"],
	windowsHide: true
});

let output = "";
child.stdout.setEncoding("utf8");
child.stderr.setEncoding("utf8");
child.stdout.on("data", (chunk) => { output += chunk; });
child.stderr.on("data", (chunk) => { output += chunk; });
child.on("error", (error) => log(`spawn error: ${error.message}`));

/** Kill the child and its descendants; Windows needs taskkill /T. */
function killTree() {
	if (child.exitCode !== null || child.pid === undefined) return;
	if (platform === "win32") {
		spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore" });
		return;
	}
	child.kill("SIGTERM");
}

/** Parse the first listen-port line the app prints, when it reports one. */
function discoveredPort() {
	const match = output.match(/https?:\/\/[^\s]*?:(\d{2,5})\b/u);
	if (match === null) return undefined;
	const port = Number(match[1]);
	return Number.isFinite(port) ? port : undefined;
}

/** Resolve once some port accepts a TCP connection, else at the deadline. */
function waitForPort() {
	return new Promise((settle) => {
		const deadline = Date.now() + timeoutMs;
		const attempt = () => {
			if (child.exitCode !== null) {
				settle({ ok: false, reason: `process exited early (code ${child.exitCode})` });
				return;
			}
			const port = requestedPort !== 0 ? requestedPort : discoveredPort();
			if (port === undefined) {
				if (Date.now() > deadline) settle({ ok: false, reason: "no port reported" });
				else setTimeout(attempt, 400);
				return;
			}
			const socket = createConnection({ host: "127.0.0.1", port }, () => {
				socket.destroy();
				settle({ ok: true, port });
			});
			socket.on("error", () => {
				socket.destroy();
				if (Date.now() > deadline) settle({ ok: false, reason: "timeout waiting for port" });
				else setTimeout(attempt, 400);
			});
		};
		attempt();
	});
}

let result;
try {
	const portResult = await waitForPort();
	log(portResult.ok ? `port ${portResult.port} is accepting connections` : `port wait failed: ${portResult.reason}`);
	let httpStatus = null;
	if (portResult.ok) {
		try {
			const response = await fetch(`http://127.0.0.1:${portResult.port}/`);
			httpStatus = response.status;
		} catch (error) {
			log(`http probe failed: ${error?.message ?? error}`);
		}
	}
	result = { portResult, httpStatus };
} catch (error) {
	log(`unexpected failure: ${error?.message ?? error}`);
	result = { portResult: { ok: false, reason: "exception" }, httpStatus: null };
} finally {
	killTree();
}

const pluginErrors = output
	.split(/\r?\n/u)
	.filter((line) => /error|cannot read|undefined|failed to load/iu.test(line))
	.filter((line) => !/401|unauthor/i.test(line));

const ok = result.portResult.ok && result.httpStatus !== null && pluginErrors.length === 0;
console.log(JSON.stringify({
	profile,
	port: result.portResult.port ?? null,
	elapsedMs: Date.now() - started,
	served: result.portResult.ok,
	httpStatus: result.httpStatus,
	pluginErrors,
	verdict: ok ? "pass" : "fail"
}, null, 2));
if (pluginErrors.length > 0) console.log(`\n--- boot output (tail) ---\n${output.slice(-2500)}`);
process.exit(ok ? 0 : 1);
