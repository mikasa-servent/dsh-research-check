/**
 * MCP protocol smoke test — no harness and no dependencies required.
 *
 * Spawns `mcp/server.mjs`, performs the initialize handshake, lists tools, calls a
 * real one (list_rules, which needs no input), and asserts the wire shapes a host
 * depends on. This is what makes "works in other harnesses" testable in CI.
 *
 * Usage: node tests/mcp-smoke.mjs
 */
import { spawn } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SERVER = join(ROOT, "mcp", "server.mjs");

const failures = [];
const passes = [];
function check(label, condition, detail) {
	if (condition) passes.push(label);
	else failures.push(detail === undefined ? label : `${label} — ${detail}`);
}

const child = spawn(process.execPath, [SERVER], { stdio: ["pipe", "pipe", "pipe"] });
let buffer = "";
const frames = [];
child.stdout.setEncoding("utf8");
child.stdout.on("data", (chunk) => {
	buffer += chunk;
	let index = buffer.indexOf("\n");
	while (index >= 0) {
		const line = buffer.slice(0, index).trim();
		buffer = buffer.slice(index + 1);
		if (line !== "") {
			try {
				frames.push(JSON.parse(line));
			} catch {
				failures.push(`无法解析响应帧：${line.slice(0, 120)}`);
			}
		}
		index = buffer.indexOf("\n");
	}
});
let stderr = "";
child.stderr.setEncoding("utf8");
child.stderr.on("data", (chunk) => { stderr += chunk; });

/** Send one request and wait until its id appears in the response stream. */
function request(id, method, params) {
	return new Promise((settle, reject) => {
		child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
		const deadline = Date.now() + 30000;
		const poll = () => {
			const found = frames.find((frame) => frame.id === id);
			if (found !== undefined) {
				settle(found);
				return;
			}
			if (Date.now() > deadline) {
				reject(new Error(`等待 ${method} 响应超时（stderr: ${stderr.slice(0, 200)}）`));
				return;
			}
			setTimeout(poll, 50);
		};
		poll();
	});
}

try {
	const init = await request(1, "initialize", { protocolVersion: "2025-06-18", capabilities: {} });
	check("initialize 返回 result", init.result !== undefined, JSON.stringify(init).slice(0, 160));
	check("serverInfo.name 正确", init.result?.serverInfo?.name === "research-check",
		JSON.stringify(init.result?.serverInfo));
	check("声明 tools capability", init.result?.capabilities?.tools !== undefined);
	check("返回 instructions（告知先建规格）",
		typeof init.result?.instructions === "string" && init.result.instructions.includes("spec_build"));

	const list = await request(2, "tools/list", {});
	const names = (list.result?.tools ?? []).map((tool) => tool.name);
	check("tools/list 至少 6 个工具", names.length >= 6, names.join(", "));
	for (const expected of ["spec_build", "spec_check", "audit", "numbers", "ledger", "list_rules"]) {
		check(`工具 ${expected} 已暴露`, names.includes(expected), names.join(", "));
	}
	const invalid = (list.result?.tools ?? []).filter((tool) => !/^[A-Za-z0-9_-]{1,64}$/u.test(tool.name));
	check("工具名满足宿主命名约束（≤64 且仅字母数字下划线连字符）", invalid.length === 0,
		invalid.map((tool) => tool.name).join(", "));
	const missingSchema = (list.result?.tools ?? []).filter((tool) => tool.inputSchema?.type !== "object");
	check("每个工具都有 object 类型的 inputSchema", missingSchema.length === 0,
		missingSchema.map((tool) => tool.name).join(", "));

	const call = await request(3, "tools/call", { name: "list_rules", arguments: {} });
	check("tools/call 返回 content 数组", Array.isArray(call.result?.content));
	check("content[0] 是 text 块", call.result?.content?.[0]?.type === "text");
	check("isError 为假", call.result?.isError !== true);
	let payload;
	try {
		payload = JSON.parse(call.result.content[0].text);
	} catch (error) {
		failures.push(`content 不是合法 JSON：${String(error?.message ?? error)}`);
	}
	check("payload 含 profiles", payload?.profiles !== undefined && Object.keys(payload.profiles).length >= 6);
	check("payload 含 checks", Array.isArray(payload?.checks) && payload.checks.length >= 30,
		String(payload?.checks?.length));

	const bad = await request(4, "tools/call", { name: "no_such_tool", arguments: {} });
	check("未知工具返回 JSON-RPC 错误", bad.error !== undefined && bad.error.code === -32602,
		JSON.stringify(bad).slice(0, 120));

	const unknown = await request(5, "not/a/method", {});
	check("未知方法返回 -32601", unknown.error?.code === -32601, JSON.stringify(unknown).slice(0, 120));
} catch (error) {
	failures.push(`协议交互失败：${String(error?.message ?? error)}`);
} finally {
	child.stdin.end();
	child.kill();
}

console.log(`${passes.length} passed, ${failures.length} failed`);
for (const label of failures) console.log(`  FAIL ${label}`);
process.exitCode = failures.length === 0 ? 0 : 1;
