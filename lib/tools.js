/**
 * Tool registration for the research-check plugin.
 *
 * Four model-facing tools, all read-mostly and workspace-scoped:
 *  - `research_audit`  : submission/layout hygiene report for a manuscript
 *  - `research_numbers`: number-consistency report (ledger-aware)
 *  - `research_ledger` : provenance ledger maintenance (teach/add/verify/list)
 *  - `research_spec`   : requirements document -> executable spec -> conformance grade
 *
 * The heavy parsing lives in the packaged Python checkers so that the plugin
 * stays dependency-free and works on any machine with Python 3.
 * @module dsh-research-check/tools
 */
import { dirname, isAbsolute, join, resolve } from "node:path";
import { runChecker, summarize } from "./util.js";
import { addEntry, ledgerStats, loadLedger, probeNearby, saveLedger, verifyEntries } from "./ledger.js";
import { defineSpecTool } from "./spec-tool.js";

const AUDIT_DESCRIPTION =
	"Audit a manuscript for submission hygiene: body/page limits, abstract placement, blank pages, "
	+ "unreferenced figures, PDF size and metadata identity leaks, plus OOXML (docx/xlsx) author metadata "
	+ "and support-archive manifest consistency. Read-only; returns a structured verdict with findings.";

const NUMBERS_DESCRIPTION =
	"Check that the numbers written in a paper are internally consistent and — when a provenance ledger is "
	+ "given — traceable to program output. Detects same-shaped sentences carrying conflicting values, and "
	+ "reports ledger entries that no longer appear in the manuscript. Read-only.";

const LEDGER_DESCRIPTION =
	"Maintain a provenance ledger that binds paper numbers to the program output they came from. "
	+ "action=teach scans a manuscript and registers candidate numbers with their context; "
	+ "action=add records one keyed value; action=verify checks every entry against the manuscript; "
	+ "action=list prints entries and statistics. Only 'add' and 'teach' write to the ledger file.";

/** Resolve a path argument against the session workspace. */
function resolvePath(path, ctx) {
	if (isAbsolute(path)) return path;
	const base = ctx?.workspace?.cwd ?? process.cwd();
	return resolve(base, path);
}

/**
 * Output contract shared by all three tools.
 *
 * Reports are inherently open-ended (counts, verdicts, finding lists), so the
 * schema is a permissive object: some harness builds reject a missing
 * `output.render`, and an open schema keeps every checker field visible to the
 * model instead of silently dropping unknown keys.
 */
function openOutput() {
	return {
		schema: { type: "object", additionalProperties: true },
		render: (_args, value) => [{ type: "text", text: JSON.stringify(value, null, 2) }]
	};
}

/**
 * Register the plugin's tools.
 * @param ctx - Cordis context carrying the tool registry.
 * @param defineTool - `defineTool` from @deepseek-ai/dsh-tools.
 */
export function registerTools(ctx, defineTool) {
	ctx.tools.register(defineTool({
		name: "research_audit",
		description: AUDIT_DESCRIPTION,
		parameters: {
			paper: {
				type: "string",
				required: true,
				description: "Path to the manuscript PDF."
			},
			files: {
				type: "array",
				items: { type: "string" },
				description: "Companion docx/xlsx files to scan for author metadata."
			},
			archives: {
				type: "array",
				items: { type: "string" },
				description: "Support-material archives (zip/rar) to inspect."
			},
			manifest: {
				type: "array",
				items: { type: "string" },
				description: "File names the manuscript appendix claims the archive contains."
			},
			max_body_pages: {
				type: "number",
				description: "Body page limit (default 30)."
			},
			max_mb: {
				type: "number",
				description: "PDF size limit in MB (default 20)."
			},
			appendix_marker: {
				type: "array",
				items: { type: "string" },
				description: "Heading text that starts the appendix (default 附录)."
			}
		},
		output: openOutput(),
		async execute(args, exec) {
			const cwd = exec?.workspace?.cwd ?? process.cwd();
			const argv = ["--paper", resolvePath(args.paper, exec)];
			for (const file of args.files ?? []) argv.push(...["--files", resolvePath(file, exec)]);
			for (const archive of args.archives ?? []) argv.push(...["--archives", resolvePath(archive, exec)]);
			if ((args.manifest ?? []).length > 0) argv.push("--manifest", ...args.manifest);
			if (typeof args.max_body_pages === "number") argv.push("--max-body-pages", String(args.max_body_pages));
			if (typeof args.max_mb === "number") argv.push("--max-mb", String(args.max_mb));
			if ((args.appendix_marker ?? []).length > 0) argv.push("--appendix-marker", ...args.appendix_marker);
			const report = await runChecker("audit_paper.py", argv, { cwd });
			return report;
		},
		presentCall: (args) => ({ card: "generic", title: "Audit manuscript", kind: "read", rawInput: args.paper })
	}));

	ctx.tools.register(defineTool({
		name: "research_numbers",
		description: NUMBERS_DESCRIPTION,
		parameters: {
			paper: {
				type: "array",
				items: { type: "string" },
				required: true,
				description: "Manuscript sources: PDF, or LaTeX/Markdown text files (faster and exact)."
			},
			data: {
				type: "array",
				items: { type: "string" },
				description: "Data files (csv/xlsx) representing the evidence side."
			},
			ledger: {
				type: "string",
				description: "Optional provenance ledger JSON to verify entries against."
			},
			tolerance: {
				type: "number",
				description: "Relative tolerance for value matching (default 0.01 = 1%)."
			}
		},
		output: openOutput(),
		async execute(args, exec) {
			const cwd = exec?.workspace?.cwd ?? process.cwd();
			const papers = Array.isArray(args.paper) ? args.paper : [args.paper];
			const argv = ["--paper", ...papers.map((path) => resolvePath(path, exec))];
			if ((args.data ?? []).length > 0) argv.push("--data", ...args.data.map((path) => resolvePath(path, exec)));
			if (typeof args.ledger === "string") {
				argv.push("--ledger", resolvePath(args.ledger, exec), "--emit-hits");
			}
			if (typeof args.tolerance === "number") argv.push("--tol", String(args.tolerance));
			const report = await runChecker("check_numbers.py", argv, { cwd });
			if (report?.ok === true && typeof args.ledger === "string") {
				const ledger = loadLedger(resolvePath(args.ledger, exec));
				const hits = report.numbers ?? [];
				const findings = verifyEntries(ledger, hits);
				const near = probeNearby(ledger, hits);
				const summary = summarize(findings);
				return {
					...report,
					ledger: { path: args.ledger, ...ledgerStats(ledger) },
					ledgerVerdict: summary.verdict,
					ledgerFindings: [...findings.filter((f) => f.level === "error"), ...near]
				};
			}
			return report;
		},
		presentCall: (args) => ({
			card: "generic", title: "Check paper numbers", kind: "read",
			rawInput: Array.isArray(args.paper) ? args.paper.join(", ") : args.paper
		})
	}));

	ctx.tools.register(defineTool({
		name: "research_ledger",
		description: LEDGER_DESCRIPTION,
		parameters: {
			action: {
				type: "string",
				required: true,
				enum: ["teach", "add", "verify", "list"],
				description: "teach | add | verify | list"
			},
			ledger: {
				type: "string",
				description: "Ledger JSON path (default paper-ledger.json in the workspace)."
			},
			paper: {
				type: "array",
				items: { type: "string" },
				description: "Manuscript sources for teach/verify (tex is faster and exact; pdf also works)."
			},
			key: {
				type: "string",
				description: "Stable entry key for action=add, e.g. q3.total_cost."
			},
			value: {
				type: "number",
				description: "Numeric value for action=add."
			},
			unit: {
				type: "string",
				description: "Unit label for the entry, e.g. 万元."
			},
			source: {
				type: "string",
				description: "Program or output file that produced the value."
			},
			anchor: {
				type: "string",
				description: "Nearby phrase used to match the entry's location during verify."
			},
			unit_filter: {
				type: "array",
				items: { type: "string" },
				description: "For teach: only register these units."
			},
			min_abs: {
				type: "number",
				description: "For teach: ignore values smaller than this magnitude (default 1)."
			},
			verbose: {
				type: "boolean",
				description: "For verify: include per-entry matches in the output."
			}
		},
		output: openOutput(),
		async execute(args, exec) {
			const cwd = exec?.workspace?.cwd ?? process.cwd();
			const ledgerPath = resolvePath(args.ledger ?? "paper-ledger.json", exec);
			const papers = (args.paper ?? []).map((path) => resolvePath(path, exec));

			if (args.action === "list") {
				const ledger = loadLedger(ledgerPath);
				return { ok: true, action: "list", ledger: ledgerPath, stats: ledgerStats(ledger), entries: ledger.entries };
			}

			if (args.action === "add") {
				const ledger = loadLedger(ledgerPath);
				const entry = addEntry(ledger, {
					key: args.key ?? "",
					value: Number(args.value),
					unit: args.unit ?? null,
					source: args.source ?? null,
					anchor: args.anchor ?? null
				});
				saveLedger(ledgerPath, ledger);
				return { ok: true, action: "add", ledger: ledgerPath, entry, stats: ledgerStats(ledger) };
			}

			if (papers.length === 0) {
				return { ok: false, error: "MISSING_PAPER", message: "teach/verify need at least one paper source." };
			}
			const check = await runChecker("check_numbers.py", ["--paper", ...papers, "--emit-hits"], { cwd });
			if (check?.ok !== true) return { ok: false, action: args.action, error: check };
			const hits = check.numbers ?? [];

			if (args.action === "teach") {
				const ledger = loadLedger(ledgerPath);
				const units = args.unit_filter ?? [];
				const minAbs = typeof args.min_abs === "number" ? args.min_abs : 1;
				let added = 0;
				let candidates = 0;
				for (const hit of hits) {
					if (!hit.unit) continue;
					candidates += 1;
					if (units.length > 0 && !units.includes(hit.unit)) continue;
					if (Math.abs(hit.value) < minAbs) continue;
					added += 1;
					addEntry(ledger, {
						key: `auto.${hit.source ?? "paper"}.p${hit.page ?? 0}.${added}`,
						value: hit.value,
						unit: hit.unit,
						source: `${hit.source ?? "paper"}${hit.page ? ` 第 ${hit.page} 页` : ""}`,
						anchor: hit.context
					});
				}
				saveLedger(ledgerPath, ledger);
				return {
					ok: true, action: "teach", ledger: ledgerPath, candidates, added,
					stats: ledgerStats(ledger),
					note: "候选条目已登记；请把 key 改成语义名并补上 source 程序路径，再用于 verify。"
				};
			}

			const ledger = loadLedger(ledgerPath);
			if (ledger.entries.length === 0) {
				return { ok: false, action: "verify", error: "LEDGER_EMPTY", ledger: ledgerPath };
			}
			const findings = verifyEntries(ledger, hits);
			const near = probeNearby(ledger, hits);
			const problems = findings.filter((finding) => finding.level === "error");
			return {
				ok: true,
				action: "verify",
				ledger: ledgerPath,
				verdict: problems.length > 0 ? "fail" : (near.length > 0 ? "warn" : "pass"),
				checked: ledger.entries.length,
				missing: problems.length,
				nearby: near.length,
				scanned: hits.length,
				findings: [
					...problems,
					...near,
					...(args.verbose === true ? findings.filter((f) => f.level === "info") : [])
				]
			};
		},
		presentCall: (args) => ({
			card: "generic", title: `Ledger ${args.action ?? "?"}`, kind: "other", rawInput: args.key ?? args.ledger
		})
	}));

	ctx.tools.register(defineSpecTool(defineTool, openOutput));
}

/** Absolute path helper exported for tests. */
export function ledgerPathFor(base, name) {
	return join(dirname(base), name);
}
