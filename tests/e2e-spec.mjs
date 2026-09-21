/**
 * End-to-end test for the spec-conformance tool, including a negative case.
 *
 * Positive: build a spec from a requirements document, then check a real
 * deliverable against it.
 * Negative: tighten the page limit and plant a sentinel identity word; both must
 * come back as hard failures, otherwise the grader is decorative.
 *
 * Inputs are configurable and the test skips (exit 0) when they are absent, so it
 * never fails on a machine that has no project to point it at:
 *   DSH_RESEARCH_WORKSPACE=<project root>           workspace
 *   DSH_RESEARCH_REQUIREMENTS=<path|.doc|.docx>     requirements document
 *   (CLI args 2/3 override the two above)
 *
 * Run from a profile directory so DSH peers resolve:
 *   node ./node_modules/dsh-research-check/tests/e2e-spec.mjs
 */
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { defineTool } from "@deepseek-ai/dsh-tools";

const workspace = resolve(
	process.env.DSH_RESEARCH_WORKSPACE ?? process.argv[2] ?? process.cwd()
);
// A requirements document in any supported format is enough; the PDF is optional
// because only layout rules need it.
const requirements = resolve(
	process.env.DSH_RESEARCH_REQUIREMENTS ?? process.argv[3] ?? join(workspace, "format2026.doc")
);
const pdf = process.argv[4] ?? "论文初稿.pdf";

if (!existsSync(requirements)) {
	console.log(JSON.stringify({
		status: "skipped",
		reason: "no requirements document to build a spec from",
		looked_for: requirements,
		hint: "set DSH_RESEARCH_REQUIREMENTS=<requirements file> to run it"
	}, null, 2));
	process.exit(0);
}

const registered = new Map();
const ctx = {
	tools: { register: (tool) => registered.set(tool.name, tool) },
	skills: { register: () => {} },
	systemPrompt: { getSectionOrder: () => 100, section: () => {} }
};
const plugin = await import("dsh-research-check");
plugin.apply(ctx, {});

const exec = { workspace: { cwd: workspace } };
const tool = registered.get("research_spec");
if (tool === undefined) throw new Error("research_spec not registered");

const dir = mkdtempSync(join(tmpdir(), "spec-e2e-"));
const specPath = join(dir, "spec.json");
const negativePath = join(dir, "spec-negative.json");

const results = {};

results.list = await tool.execute({ action: "list" }, exec);
results.build = await tool.execute({
	action: "build", requirements, spec: specPath, name: "e2e 规格", profile: "academic"
}, exec);
if (results.build?.ok !== true) {
	console.error("build 失败：", JSON.stringify(results.build, null, 2));
	process.exit(2);
}

results.checkClean = await tool.execute({
	action: "check", spec: specPath, pdf, files: [pdf]
}, exec);

// Negative control: tighten the page ceiling and add a sentinel word that the PDF
// metadata provably contains ("LaTeX"), so both rules must fail. Rules are located
// by `check`, not by id, so a pack renaming ids cannot silently disable the control.
const spec = JSON.parse(readFileSync(specPath, "utf8"));
for (const rule of spec.rules) {
	if (rule.check === "max_pages" && rule.scope === "body") rule.params.limit = 5;
	if (rule.check === "metadata_no_identity") rule.params.words.push("LaTeX");
}
writeFileSync(negativePath, JSON.stringify(spec, null, 2), "utf8");
results.checkNegative = await tool.execute({
	action: "check", spec: negativePath, pdf, files: [pdf]
}, exec);

const compact = (report) => ({
	ok: report.ok,
	verdict: report.verdict,
	summary: report.summary ?? report.counts,
	blocking: (report.blocking ?? []).map((item) => `${item.id}: ${item.detail}`)
});
console.log(JSON.stringify({
	list: { ok: results.list.ok, checks: results.list.checks?.length },
	build: { ok: results.build.ok, rules: results.build.rules, hard: results.build.bySeverity?.hard },
	checkClean: compact(results.checkClean),
	checkNegative: compact(results.checkNegative),
	specDir: dir
}, null, 2));

const negativesCaught = (results.checkNegative.blocking ?? []).length >= 2;
const cleanPasses = results.checkClean.verdict !== "fail";
console.log(`\n[RESULT] 干净稿 ${cleanPasses ? "通过" : "误报"}；负例拦截 ${negativesCaught ? "成功" : "失败"}`);
process.exitCode = negativesCaught && cleanPasses ? 0 : 1;
