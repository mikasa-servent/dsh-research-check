#!/usr/bin/env node
/**
 * MCP server for dsh-research-check — the cross-harness adapter.
 *
 * Any host that speaks MCP (Claude Code, Codex, Cursor, DSH via its mcp-client
 * plugin, …) can spawn this file and get the same operations the DSH plugin
 * exposes. The engine lives in `lib/core.js`; this file is only the wire protocol,
 * so there is no second implementation to drift.
 *
 * Transport: JSON-RPC 2.0 over stdio, newline-delimited. No dependencies.
 *
 * Usage (host config):
 *   { "transport": "stdio", "serverName": "research-check",
 *     "command": "node", "args": ["<plugin>/mcp/server.mjs"] }
 *
 * Manual smoke test:
 *   echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | node mcp/server.mjs
 */
import { createInterface } from "node:readline";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { audit, ledger, numbers, specBuild, specCheck } from "../lib/core.js";
import { PROFILES, RULE_VOCABULARY } from "../lib/spec-tool.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const PLUGIN_ROOT = resolve(HERE, "..");
const SERVER_NAME = "research-check";
const SERVER_VERSION = "1.4.0";
const PROTOCOL_VERSION = "2025-06-18";

/** Tool catalogue: name, description, JSON Schema, and the engine call. */
const TOOLS = [
	{
		name: "spec_build",
		description:
			"Build an executable spec JSON from a requirements document (competition rules, journal "
			+ "guidelines, acceptance criteria, tender documents). Rules are template-matched with a citation "
			+ "each; requirements no machine can verify become manual checklist items.",
		inputSchema: {
			type: "object",
			properties: {
				requirements: { type: "string", description: "Requirements document (.doc/.docx/.md/.txt)." },
				spec: { type: "string", description: "Output spec JSON path." },
				name: { type: "string", description: "Spec display name (defaults to the file stem)." },
				profile: {
					type: "string",
					enum: Object.keys(PROFILES),
					description: "Deliverable type; picks the rule pack. Default academic."
				}
			},
			required: ["requirements", "spec"]
		},
		run: (args, cwd) => specBuild({ ...args, cwd })
	},
	{
		name: "spec_check",
		description:
			"Grade a deliverable against a spec: page/layout rules from the PDF, source-level rules from the "
			+ "manuscript source, file rules from the delivered files, archive rules from the package. Returns "
			+ "a verdict with blocking findings, warnings and skipped (unverifiable) rules.",
		inputSchema: {
			type: "object",
			properties: {
				spec: { type: "string", description: "Spec JSON path." },
				document: { type: "string", description: "Manuscript/source file (LaTeX, Markdown, text)." },
				pdf: { type: "string", description: "Built PDF, used by layout rules." },
				files: { type: "array", items: { type: "string" }, description: "Delivered files to measure." },
				archive: { type: "string", description: "Support/archive zip." },
				assets: { type: "array", items: { type: "string" }, description: "Asset directories." },
				root: { type: "string", description: "Project root for relative paths." }
			},
			required: ["spec"]
		},
		run: (args, cwd) => specCheck({ ...args, cwd })
	},
	{
		name: "audit",
		description:
			"Audit a deliverable's files: body page limits, abstract placement, blank pages, unreferenced "
			+ "figures, PDF size, identity leaks in PDF metadata, author fields in DOCX/XLSX, and archive "
			+ "manifest consistency. Read-only.",
		inputSchema: {
			type: "object",
			properties: {
				paper: { type: "string", description: "Built PDF (or composite document)." },
				files: { type: "array", items: { type: "string" }, description: "Companion docx/xlsx files." },
				archives: { type: "array", items: { type: "string" }, description: "Archives to inspect." },
				manifest: { type: "array", items: { type: "string" }, description: "Expected archive contents." },
				maxBodyPages: { type: "number", description: "Body page limit (default 30)." },
				maxMb: { type: "number", description: "Size limit in MB (default 20)." },
				appendixMarker: { type: "array", items: { type: "string" }, description: "Appendix heading text." }
			},
			required: ["paper"]
		},
		run: (args, cwd) => audit({ ...args, cwd })
	},
	{
		name: "numbers",
		description:
			"Check number consistency across a document: same-sentence conflicting values, and — when a ledger "
			+ "is given — whether every ledger value still appears. Catches the classic defect where a figure "
			+ "caption was updated but the prose was not. Read-only.",
		inputSchema: {
			type: "object",
			properties: {
				documents: {
					type: "array", items: { type: "string" },
					description: "Document sources (tex/md/txt/pdf)."
				},
				evidence: { type: "array", items: { type: "string" }, description: "Data files (csv/xlsx)." },
				ledger: { type: "string", description: "Ledger JSON to verify against." },
				tolerance: { type: "number", description: "Relative tolerance (default 0.01)." }
			},
			required: ["documents"]
		},
		run: (args, cwd) => numbers({
			cwd,
			documents: args.documents,
			evidence: args.evidence,
			ledger: args.ledger,
			tolerance: args.tolerance
		})
	},
	{
		name: "ledger",
		description:
			"Maintain the provenance ledger that binds numbers to the programs that produced them. "
			+ "action=teach scans a document and registers candidates; action=add records one keyed value; "
			+ "action=verify checks every entry against the document; action=list prints entries.",
		inputSchema: {
			type: "object",
			properties: {
				action: { type: "string", enum: ["teach", "add", "verify", "list"], description: "Operation." },
				ledger: { type: "string", description: "Ledger JSON path (default paper-ledger.json)." },
				documents: { type: "array", items: { type: "string" }, description: "Sources for teach/verify." },
				key: { type: "string", description: "Entry key for add, e.g. q3.total_cost." },
				value: { type: "number", description: "Entry value for add." },
				unit: { type: "string", description: "Unit label, e.g. 万元." },
				source: { type: "string", description: "Producing program or output file." },
				anchor: { type: "string", description: "Nearby phrase used to locate the value." },
				unitFilter: { type: "array", items: { type: "string" }, description: "For teach: units to keep." },
				minAbs: { type: "number", description: "For teach: ignore values below this magnitude." },
				verbose: { type: "boolean", description: "For verify: include per-entry matches." }
			},
			required: ["action"]
		},
		run: (args, cwd) => ledger({ ...args, cwd, unitFilter: args.unitFilter, minAbs: args.minAbs })
	},
	{
		name: "list_rules",
		description:
			"List the rule vocabulary (checks the engine can evaluate) and the deliverable profiles with "
			+ "their descriptions, so a requirement can be matched to a check.",
		inputSchema: { type: "object", properties: {} },
		run: () => Promise.resolve({
			ok: true,
			profiles: PROFILES,
			checks: RULE_VOCABULARY,
			note: "check=manual 的条目进入人工清单；拿不到输入时判 skipped，绝不当作通过。"
		})
	}
];

const byName = new Map(TOOLS.map((tool) => [tool.name, tool]));

/** One JSON-RPC response frame. */
function send(payload) {
	process.stdout.write(`${JSON.stringify(payload)}\n`);
}

function result(id, value) {
	return { jsonrpc: "2.0", id, result: value };
}

function failure(id, code, message) {
	return { jsonrpc: "2.0", id, error: { code, message } };
}

/** Dispatch one request; unknown methods and tool errors are reported, never thrown. */
async function handle(request) {
	const { id, method, params } = request ?? {};
	if (typeof method !== "string") return failure(id ?? null, -32600, "invalid request");

	if (method === "initialize") {
		return result(id, {
			protocolVersion: (params?.protocolVersion) ?? PROTOCOL_VERSION,
			capabilities: { tools: { listChanged: false } },
			serverInfo: {
				name: SERVER_NAME,
				version: SERVER_VERSION,
				title: "Deliverable evidence & conformance checks"
			},
			instructions:
				"Build a spec from the requirements document first (spec_build), correct its params, then grade "
				+ "with spec_check. Use numbers + ledger to prove every reported number traces to a program. "
				+ "A rule that cannot run reports skipped: treat it as unverified, not as passing."
		});
	}

	if (method === "notifications/initialized" || method === "initialized") return undefined;

	if (method === "tools/list") {
		return result(id, {
			tools: TOOLS.map((tool) => ({
				name: tool.name,
				description: tool.description,
				inputSchema: tool.inputSchema
			}))
		});
	}

	if (method === "tools/call") {
		const tool = byName.get(params?.name);
		if (tool === undefined) return failure(id, -32602, `unknown tool: ${String(params?.name)}`);
		const cwd = process.env.DSH_RESEARCH_CWD ?? process.cwd();
		try {
			const value = await tool.run(params?.arguments ?? {}, cwd);
			const text = JSON.stringify(value ?? { ok: false, error: "EMPTY_RESULT" }, null, 2);
			return result(id, {
				content: [{ type: "text", text }],
				isError: value?.ok === false
			});
		} catch (error) {
			return result(id, {
				content: [{ type: "text", text: `工具执行异常：${String(error?.message ?? error)}` }],
				isError: true
			});
		}
	}

	if (method === "ping") return result(id, {});

	return failure(id, -32601, `method not found: ${method}`);
}

/** Read newline-delimited JSON-RPC from stdin and answer in order. */
async function main() {
	const rl = createInterface({ input: process.stdin, crlfDelay: Number.POSITIVE_INFINITY });
	let queue = Promise.resolve();
	rl.on("line", (line) => {
		const trimmed = line.trim();
		if (trimmed === "") return;
		queue = queue.then(async () => {
			let request;
			try {
				request = JSON.parse(trimmed);
			} catch (error) {
				send(failure(null, -32700, `parse error: ${String(error?.message ?? error)}`));
				return;
			}
			const response = await handle(request);
			if (response !== undefined) send(response);
		});
	});
	await new Promise((settle) => rl.on("close", settle));
	await queue;
}

main().catch((error) => {
	process.stderr.write(`[${SERVER_NAME}] fatal: ${String(error?.stack ?? error)}\n`);
	process.exitCode = 1;
});

export { TOOLS, PLUGIN_ROOT };
