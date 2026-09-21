/**
 * End-to-end execution test: call each registered tool's `execute` the way the
 * registry does, against a real deliverable workspace.
 *
 * The workspace is configurable, because the files this needs (a built PDF, a
 * support archive, manuscript sources) belong to the user's project, not to the
 * plugin. Resolution order:
 *   1. `DSH_RESEARCH_WORKSPACE` environment variable
 *   2. first CLI argument
 *   3. the current working directory
 * When the expected files are absent the test reports SKIPPED and exits 0, so it
 * never fails on a machine that simply has no manuscript to point it at.
 *
 * Run from a profile directory so DSH peers resolve:
 *   DSH_RESEARCH_WORKSPACE=/path/to/project node ./node_modules/dsh-research-check/tests/e2e.mjs
 */
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { defineTool } from "@deepseek-ai/dsh-tools";

const workspace = resolve(
	process.env.DSH_RESEARCH_WORKSPACE ?? process.argv[2] ?? process.cwd()
);

const REQUIRED = ["论文初稿.pdf", "paper/sections/06_q3_model_and_solving.tex"];
const missing = REQUIRED.filter((relative) => !existsSync(resolve(workspace, relative)));
if (missing.length > 0) {
	console.log(JSON.stringify({
		status: "skipped",
		reason: "workspace does not contain the files this test exercises",
		workspace,
		missing,
		hint: "set DSH_RESEARCH_WORKSPACE=<project root> to run it against a real deliverable"
	}, null, 2));
	process.exit(0);
}

const registered = new Map();
const ctx = {
	tools: { register: (tool) => registered.set(tool.name, tool) },
	systemPrompt: { getSectionOrder: () => 100, section: () => {} }
};
const plugin = await import("dsh-research-check");
plugin.apply(ctx, {});

const exec = { workspace: { cwd: workspace } };
const out = { workspace };

out.audit = await call("research_audit", {
	paper: "论文初稿.pdf",
	archives: ["support.zip"],
	files: ["AI 工具使用详情.pdf"],
	max_body_pages: 30
});

out.numbers = await call("research_numbers", {
	paper: ["paper/sections/06_q3_model_and_solving.tex"],
	tolerance: 0.01
});

out.ledgerTeach = await call("research_ledger", {
	action: "teach",
	ledger: "_e2e-ledger.json",
	paper: ["paper/sections/06_q3_model_and_solving.tex"],
	unit_filter: ["万元"],
	min_abs: 100
});

out.ledgerList = await call("research_ledger", {
	action: "list",
	ledger: "_e2e-ledger.json"
});

async function call(name, args) {
	const tool = registered.get(name);
	if (tool === undefined) throw new Error(`tool not registered: ${name}`);
	const started = Date.now();
	const value = await tool.execute(args, exec);
	return {
		ms: Date.now() - started,
		verdict: value?.verdict ?? value?.ledgerVerdict,
		counts: value?.counts,
		keys: Object.keys(value ?? {}).slice(0, 14),
		sample: summarise(value)
	};
}

function summarise(value) {
	if (value === null || typeof value !== "object") return value;
	if (Array.isArray(value.findings) && value.findings.length > 0) {
		return value.findings.slice(0, 2).map((finding) => finding.message ?? finding.check);
	}
	return undefined;
}

console.log(JSON.stringify(out, null, 2));
const failed = Object.entries(out)
	.filter(([key, result]) => key !== "workspace" && result.verdict === "fail");
console.log(`\n[RESULT] ${Object.keys(out).length - 1} tool calls, ${failed.length} returned verdict=fail`);
process.exitCode = failed.length === 0 ? 0 : 1;
