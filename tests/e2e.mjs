/**
 * End-to-end execution test: call each registered tool's `execute` the way the
 * registry does, against real files. Run from the profile directory so peers
 * resolve:
 *   node ./node_modules/dsh-research-check/tests/e2e.mjs
 */
import { defineTool } from "@deepseek-ai/dsh-tools";

const registered = new Map();
const ctx = {
	tools: { register: (tool) => registered.set(tool.name, tool) },
	systemPrompt: { getSectionOrder: () => 100, section: () => {} }
};
const plugin = await import("dsh-research-check");
plugin.apply(ctx, {});

const workspace = "C:\\Users\\asus\\Desktop\\数学建模";
const exec = { workspace: { cwd: workspace } };
const out = {};

out.audit = await call("research_audit", {
	paper: "论文初稿.pdf",
	archives: ["support.zip"],
	manifest: [
		"result1.xlsx", "result2.xlsx", "result3.xlsx", "result4-2.xlsx", "result4-3.xlsx",
		"q1_final_two_stage.py", "q2_roll_v3.py", "q3_rolling_mpc.py",
		"q4_microgrid_dispatch.py", "check_data.py", "test_epsilon.py", "AI 工具使用详情.pdf"
	],
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
const failed = Object.entries(out).filter(([, result]) => result.verdict === "fail");
console.log(`\n[RESULT] ${Object.keys(out).length} tool calls, ${failed.length} returned verdict=fail`);
