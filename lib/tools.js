/**
 * Tool registration for the research-check plugin.
 *
 * Four model-facing tools, all read-mostly and workspace-scoped:
 *  - `research_audit`   hand-over hygiene report for a deliverable
 *  - `research_numbers` number-consistency report (ledger-aware)
 *  - `research_ledger`  provenance ledger maintenance (teach/add/verify/list)
 *  - `research_spec`    requirements document -> executable spec -> conformance grade
 *
 * Every operation delegates to `lib/core.js`, the host-agnostic engine that
 * `mcp/server.mjs` also uses. This file therefore holds no business logic — only
 * path resolution and the harness tool contract, so the DSH plugin and the MCP
 * server cannot drift apart.
 * @module dsh-research-check/tools
 */
import { isAbsolute, join, resolve } from "node:path";
import { audit, ledger, numbers, specBuild, specCheck } from "./core.js";
import { PROFILES, RULE_VOCABULARY } from "./spec-tool.js";

const AUDIT_DESCRIPTION =
	"Audit a deliverable for hand-over hygiene: body/page limits, abstract placement, blank pages, "
	+ "unreferenced figures, PDF size and metadata identity leaks, plus OOXML (docx/xlsx) author metadata "
	+ "and archive manifest consistency. Read-only; returns a structured verdict with findings.";

const NUMBERS_DESCRIPTION =
	"Check that the numbers written in a deliverable are internally consistent and — when a provenance "
	+ "ledger is given — traceable to the program that produced them. Detects same-shaped sentences "
	+ "carrying conflicting values, and reports ledger entries that no longer appear. Read-only.";

const LEDGER_DESCRIPTION =
	"Maintain a provenance ledger that binds reported numbers to the program output they came from. "
	+ "action=teach scans a document and registers candidate numbers with their context; "
	+ "action=add records one keyed value; action=verify checks every entry against the document; "
	+ "action=list prints entries and statistics. Only 'add' and 'teach' write to the ledger file.";

const SPEC_DESCRIPTION =
	"Turn a requirements document (competition rules, journal guidelines, acceptance criteria, tender "
	+ "documents) into an executable spec JSON, then grade a deliverable against it. Rules are "
	+ "template-matched from the requirements text with a citation each, so every finding traces back to a "
	+ "clause. action=build creates the spec (pick a profile: academic / docs / software / dataset / "
	+ "tender / generic), action=check evaluates it, action=list prints the rule vocabulary and profiles. "
	+ "Requirements that no machine can verify become manual checklist items instead of being guessed at, "
	+ "and a rule that cannot run reports skipped — never a silent pass.";

/** Resolve a path argument against the session workspace. */
function resolvePath(path, ctx) {
	if (isAbsolute(path)) return path;
	const base = ctx?.workspace?.cwd ?? process.cwd();
	return resolve(base, path);
}

/**
 * Output contract shared by all four tools.
 *
 * Reports are inherently open-ended (counts, verdicts, finding lists), so the schema
 * is a permissive object: some harness builds reject a missing `output.render`, and an
 * open schema keeps every checker field visible instead of silently dropping unknowns.
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
				type: "string", required: true,
				description: "Path to the built PDF (or the composite document being delivered)."
			},
			files: {
				type: "array", items: { type: "string" },
				description: "Companion docx/xlsx files to scan for author metadata."
			},
			archives: {
				type: "array", items: { type: "string" },
				description: "Support archives (zip) to inspect."
			},
			manifest: {
				type: "array", items: { type: "string" },
				description: "File names the document claims the archive contains."
			},
			max_body_pages: { type: "number", description: "Body page limit (default 30)." },
			max_mb: { type: "number", description: "Size limit in MB (default 20)." },
			appendix_marker: {
				type: "array", items: { type: "string" },
				description: "Heading text that starts the appendix (default 附录)."
			}
		},
		output: openOutput(),
		async execute(args, exec) {
			const cwd = exec?.workspace?.cwd ?? process.cwd();
			return audit({
				cwd,
				paper: resolvePath(args.paper, exec),
				files: (args.files ?? []).map((path) => resolvePath(path, exec)),
				archives: (args.archives ?? []).map((path) => resolvePath(path, exec)),
				manifest: args.manifest ?? [],
				maxBodyPages: args.max_body_pages,
				maxMb: args.max_mb,
				appendixMarker: args.appendix_marker ?? []
			});
		},
		presentCall: (args) => ({ card: "generic", title: "Audit deliverable", kind: "read", rawInput: args.paper })
	}));

	ctx.tools.register(defineTool({
		name: "research_numbers",
		description: NUMBERS_DESCRIPTION,
		parameters: {
			paper: {
				type: "array", items: { type: "string" }, required: true,
				description: "Document sources: PDF, or LaTeX/Markdown/text (faster and exact)."
			},
			data: {
				type: "array", items: { type: "string" },
				description: "Data files (csv/xlsx) forming the evidence side."
			},
			ledger: { type: "string", description: "Optional provenance ledger JSON to verify entries against." },
			tolerance: { type: "number", description: "Relative tolerance for value matching (default 0.01)." }
		},
		output: openOutput(),
		async execute(args, exec) {
			const cwd = exec?.workspace?.cwd ?? process.cwd();
			const papers = Array.isArray(args.paper) ? args.paper : [args.paper];
			return numbers({
				cwd,
				documents: papers.map((path) => resolvePath(path, exec)),
				evidence: (args.data ?? []).map((path) => resolvePath(path, exec)),
				ledger: typeof args.ledger === "string" ? resolvePath(args.ledger, exec) : undefined,
				tolerance: args.tolerance
			});
		},
		presentCall: (args) => ({
			card: "generic", title: "Check numbers", kind: "read",
			rawInput: Array.isArray(args.paper) ? args.paper.join(", ") : args.paper
		})
	}));

	ctx.tools.register(defineTool({
		name: "research_ledger",
		description: LEDGER_DESCRIPTION,
		parameters: {
			action: {
				type: "string", required: true, enum: ["teach", "add", "verify", "list"],
				description: "teach | add | verify | list"
			},
			ledger: { type: "string", description: "Ledger JSON path (default paper-ledger.json in the workspace)." },
			paper: {
				type: "array", items: { type: "string" },
				description: "Document sources for teach/verify (tex is exact; pdf also works)."
			},
			key: { type: "string", description: "Stable entry key for action=add, e.g. q3.total_cost." },
			value: { type: "number", description: "Numeric value for action=add." },
			unit: { type: "string", description: "Unit label, e.g. 万元." },
			source: { type: "string", description: "Program or output file that produced the value." },
			anchor: { type: "string", description: "Nearby phrase used to locate the value during verify." },
			unit_filter: {
				type: "array", items: { type: "string" },
				description: "For teach: only register these units."
			},
			min_abs: { type: "number", description: "For teach: ignore values smaller than this magnitude (default 1)." },
			verbose: { type: "boolean", description: "For verify: include per-entry matches." }
		},
		output: openOutput(),
		async execute(args, exec) {
			const cwd = exec?.workspace?.cwd ?? process.cwd();
			return ledger({
				cwd,
				action: args.action,
				ledger: resolvePath(args.ledger ?? "paper-ledger.json", exec),
				documents: (args.paper ?? []).map((path) => resolvePath(path, exec)),
				key: args.key,
				value: args.value,
				unit: args.unit,
				source: args.source,
				anchor: args.anchor,
				unitFilter: args.unit_filter ?? [],
				minAbs: args.min_abs,
				verbose: args.verbose
			});
		},
		presentCall: (args) => ({
			card: "generic", title: `Ledger ${args.action ?? "?"}`, kind: "other", rawInput: args.key ?? args.ledger
		})
	}));

	ctx.tools.register(defineTool({
		name: "research_spec",
		description: SPEC_DESCRIPTION,
		parameters: {
			action: {
				type: "string", required: true, enum: ["build", "check", "list"],
				description: "build | check | list"
			},
			requirements: { type: "string", description: "For build: the requirements document (.doc/.docx/.md/.txt)." },
			spec: { type: "string", description: "Spec JSON path: output for build, input for check." },
			name: { type: "string", description: "For build: spec display name (defaults to the file stem)." },
			profile: {
				type: "string",
				description: "For build: deliverable type — academic | docs | software | dataset | tender | generic (default academic)."
			},
			paper: { type: "string", description: "For check: source document, used by source-level rules." },
			pdf: { type: "string", description: "For check: the built PDF, used by layout rules." },
			files: { type: "array", items: { type: "string" }, description: "For check: delivered files to measure." },
			archive: { type: "string", description: "For check: support-material archive (zip)." },
			assets: { type: "array", items: { type: "string" }, description: "For check: asset directories." },
			root: { type: "string", description: "For check: project root for relative paths (default workspace)." }
		},
		output: openOutput(),
		async execute(args, exec) {
			const cwd = exec?.workspace?.cwd ?? process.cwd();
			if (args.action === "list") {
				return {
					ok: true,
					action: "list",
					profiles: PROFILES,
					checks: RULE_VOCABULARY,
					severities: { hard: "违反即判错（error）", soft: "提示（warning）", info: "不改判" },
					scopes: ["document", "body", "appendix", "per-file", "bundle"],
					note: "check=manual 的条目进入人工清单；拿不到输入时判 skipped，绝不当作通过。"
				};
			}
			if (args.action === "build") {
				return specBuild({
					cwd,
					requirements: resolvePath(args.requirements ?? "", exec),
					spec: resolvePath(args.spec ?? "", exec),
					name: args.name,
					profile: args.profile
				});
			}
			if (args.action === "check") {
				return specCheck({
					cwd,
					spec: resolvePath(args.spec ?? "", exec),
					root: typeof args.root === "string" && args.root !== "" ? resolvePath(args.root, exec) : cwd,
					document: typeof args.paper === "string" ? resolvePath(args.paper, exec) : undefined,
					pdf: typeof args.pdf === "string" ? resolvePath(args.pdf, exec) : undefined,
					files: (args.files ?? []).map((file) => resolvePath(file, exec)),
					archive: typeof args.archive === "string" ? resolvePath(args.archive, exec) : undefined,
					assets: (args.assets ?? []).map((dir) => resolvePath(dir, exec))
				});
			}
			return { ok: false, error: "UNKNOWN_ACTION", action: args.action };
		},
		presentCall: (args) => ({
			card: "generic",
			title: `Spec ${args.action ?? "?"}`,
			kind: args.action === "check" ? "read" : "other",
			rawInput: args.spec ?? args.requirements
		})
	}));
}

/** Absolute path helper exported for tests. */
export function ledgerPathFor(base, name) {
	return join(resolve(base), name);
}
