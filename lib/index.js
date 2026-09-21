/**
 * dsh-research-check — evidence-chain checks for data-driven papers.
 *
 * Registers three tools and one skill:
 *   research_audit    submission/layout hygiene report for a manuscript
 *   research_numbers  number-consistency report (ledger-aware)
 *   research_ledger   provenance ledger maintenance (teach/add/verify/list)
 *   skill             research-evidence-check (the procedure behind the above)
 *
 * Design notes:
 *  - Zero runtime dependencies: the plugin spawns a local Python 3 checker and
 *    reads/writes one JSON ledger, so it installs into any profile.
 *  - Every check is read-only except the two ledger write actions, and all paths
 *    resolve against the session workspace rather than the plugin directory.
 *  - Each host service is used defensively, so a composition without `skills`
 *    still gets the tools and one without `tools` still gets the skill.
 * @module dsh-research-check
 */
import z from "@deepseek-ai/schemastery";
import { defineTool } from "@deepseek-ai/dsh-tools";
import { registerSkill } from "./skill.js";
import { registerTools } from "./tools.js";
import { resolvePython } from "./util.js";

/** Plugin name shown in loader patches and diagnostics. */
export const name = "research-check";

/** Cordis services this plugin needs before `apply` runs. */
export const inject = ["tools", "systemPrompt", "skills"];

/**
 * Optional configuration; every field has a working default. Cordis v4 requires
 * the Config export to implement the Standard Schema interface, so this is a
 * schemastery schema (linked as a peer alongside cordis/dsh-tools) rather than a
 * plain object — the latter crashes profile boot.
 */
export const Config = z.object({
	/** Extra lines appended to the tool policy section of the system prompt. */
	guidance: z.string().default(""),
	/** Register the embedded `research-evidence-check` skill (default on). */
	registerSkill: z.boolean().default(true),
	/** Override the skill document path; defaults to the packaged SKILL.md. */
	skillPath: z.string().default("")
});

const GUIDANCE = [
	"## Research evidence-chain checks",
	"Before a manuscript is declared ready, run `research_audit` on the built PDF to verify page limits,",
	"abstract placement, blank pages, unreferenced figures, metadata identity leaks, and whether the",
	"support archive still matches the appendix manifest.",
	"Whenever numbers change in a paper, run `research_numbers` (and `research_ledger` with",
	"action=verify when a ledger exists): a number that survives in prose while its figure caption was",
	"updated is a silent defect that reviewers read as carelessness.",
	"Numbers produced by programs should first be recorded with `research_ledger` action=add",
	"(key + value + source + anchor) so later revisions can be checked automatically.",
	"The `research-evidence-check` skill holds the full procedure; load it before a revision pass."
].join("\n");

/** Register the plugin. */
export function apply(ctx, config = {}) {
	const extra = typeof config.guidance === "string" ? config.guidance.trim() : "";
	const python = resolvePython();
	// dsh-system-prompt owns placement via numeric orders: TOOL_REPORT sits at
	// 2900 and TOOLS_SDK at 5000. There is no exported constant or lookup helper
	// for these values, so the numbers are written literally here (and asserted by
	// tests/contract.mjs against the prompt package's own table).
	ctx.systemPrompt.section({
		name: "tool:research-check",
		order: 2950,
		text: python === undefined
			? `${GUIDANCE}\n\n(Note: no Python 3 interpreter was detected, so the checkers will report NO_PYTHON.`
				+ " Install Python 3.10+ or set DSH_RESEARCH_PYTHON to an interpreter path.)"
			: GUIDANCE
	});
	if (extra !== "") {
		ctx.systemPrompt.section({
			name: "tool:research-check:custom",
			order: 2951,
			text: extra
		});
	}
	if (typeof ctx.tools?.register === "function") registerTools(ctx, defineTool);
	registerSkill(ctx, {
		register: config.registerSkill !== false,
		...(typeof config.skillPath === "string" && config.skillPath !== ""
			? { path: config.skillPath }
			: {})
	});
}

export { registerSkill, registerTools };
