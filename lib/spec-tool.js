/**
 * Spec-conformance tool: turn a requirements document into an executable
 * contract, then grade a deliverable against it.
 *
 * Three actions:
 *   build  — read a requirements text (.doc/.docx/.md/.txt) and emit a spec JSON
 *            whose rules each carry a `check`, a severity, and a citation.
 *   check  — evaluate a spec against a manuscript (LaTeX source + PDF), the
 *            files being submitted, an optional support archive.
 *   list   — print the rule vocabulary the checker understands.
 *
 * The heavy lifting is in `python/spec_build.py` and `python/check_spec.py`.
 * @module dsh-research-check/spec-tool
 */
import { isAbsolute, resolve } from "node:path";
import { runChecker } from "./util.js";

/** Rule vocabulary, mirrored from check_spec.py's KNOWN_CHECKS. */
export const RULE_VOCABULARY = [
	// 版面
	"max_pages", "min_pages", "abstract_first_page", "abstract_within_page", "no_blank_page",
	"all_figures_referenced", "all_tables_referenced", "max_pdf_bytes", "metadata_no_identity",
	// 结构
	"max_sections", "max_subsections_per_section", "no_toc", "forbidden_text",
	// 源码级排版
	"linespread_min", "fontsize_min", "page_geometry", "margins_min", "bibliography_placeholders",
	"math_in_abstract",
	// 素材
	"asset_format", "asset_naming", "asset_min_dpi", "no_asset_duplicates",
	// 交付物（与领域无关）
	"file_size_max", "office_metadata_no_identity", "file_naming", "manifest_matches_archive",
	"archive_size_max", "bundle_no_forbidden_files", "required_files_present", "placeholder_text",
	"max_paragraph_chars", "required_text_pattern", "version_string_present",
	// 数据交付
	"dataset_columns_present", "dataset_row_count", "dataset_no_sensitive_columns",
	// 人工
	"manual"
];

/** Deliverable profiles, mirroring rule_packs.py. */
export const PROFILES = {
	academic: "学位/竞赛/期刊论文：页数、摘要单页、图表引用、页边距、行距字号",
	docs: "技术文档/说明书/手册：段落长度、版本号、联系方式、待办残留",
	software: "软件交付/项目验收/发版：必备文件、许可、变更记录、报错标记残留",
	dataset: "数据交付/数据集：字段齐备、样本量、隐私字段、数据字典",
	tender: "标书/申报书：章节齐备、逐条响应、违规承诺",
	generic: "与类型无关：体积、命名、身份信息、清单一致性、占位符"
};

export const SPEC_DESCRIPTION =
	"Turn a requirements document (competition rules, journal guidelines, acceptance criteria, tender "
	+ "documents) into an executable spec JSON, then grade a deliverable against it. Rules are "
	+ "template-matched from the requirements text with a citation each, so every finding traces back to a "
	+ "clause. action=build creates the spec (pick a profile: academic / docs / software / dataset / "
	+ "tender / generic), action=check evaluates it, action=list prints the rule vocabulary and profiles. "
	+ "Requirements that no machine can verify are recorded as manual checklist items instead of being "
	+ "guessed at, and a rule that cannot run reports skipped — never a silent pass.";

/** Resolve a path against the session workspace. */
function resolvePath(path, ctx) {
	if (isAbsolute(path)) return path;
	const base = ctx?.workspace?.cwd ?? process.cwd();
	return resolve(base, path);
}

/**
 * Build the tool definition.
 * @param defineTool - `defineTool` from @deepseek-ai/dsh-tools.
 * @param openOutput - shared output contract factory.
 */
export function defineSpecTool(defineTool, openOutput) {
	return defineTool({
		name: "research_spec",
		description: SPEC_DESCRIPTION,
		parameters: {
			action: {
				type: "string",
				required: true,
				enum: ["build", "check", "list"],
				description: "build | check | list"
			},
			requirements: {
				type: "string",
				description: "For build: the requirements document (.doc/.docx/.md/.txt)."
			},
			spec: {
				type: "string",
				description: "Spec JSON path: output for build, input for check."
			},
			name: {
				type: "string",
				description: "For build: spec display name (defaults to the file stem)."
			},
			profile: {
				type: "string",
				description: "For build: deliverable type — academic | docs | software | dataset | tender | generic (default academic)."
			},
			paper: {
				type: "string",
				description: "For check: LaTeX source file, used by source-level rules."
			},
			pdf: {
				type: "string",
				description: "For check: the built PDF, used by layout rules."
			},
			files: {
				type: "array",
				items: { type: "string" },
				description: "For check: submitted files to measure (size, OOXML metadata)."
			},
			archive: {
				type: "string",
				description: "For check: support-material archive (zip)."
			},
			assets: {
				type: "array",
				items: { type: "string" },
				description: "For check: asset directories for figure/table rules."
			},
			root: {
				type: "string",
				description: "For check: project root that relative paths resolve against (default workspace)."
			}
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
					note: "check=manual 的条目会进入人工清单；拿不到输入时判 skipped，绝不当作通过。"
				};
			}

			if (args.action === "build") {
				if (typeof args.requirements !== "string" || typeof args.spec !== "string") {
					return { ok: false, error: "MISSING_ARGS", message: "build 需要 requirements 与 spec 两个路径" };
				}
				const argv = [
					"--requirements", resolvePath(args.requirements, exec),
					"--out", resolvePath(args.spec, exec)
				];
				if (typeof args.name === "string" && args.name !== "") argv.push("--name", args.name);
				if (typeof args.profile === "string" && args.profile !== "") argv.push("--profile", args.profile);
				const report = await runChecker("spec_build.py", argv, { cwd });
				if (report?.ok === true) {
					return {
						...report,
						next: "请逐条复核规则：确认 limit 数值与 source 引用，再把 manifest 等留空参数补齐，然后 action=check。"
					};
				}
				return report;
			}

			if (args.action === "check") {
				if (typeof args.spec !== "string") {
					return { ok: false, error: "MISSING_SPEC", message: "check 需要 spec 路径" };
				}
				const argv = ["--spec", resolvePath(args.spec, exec),
					"--root", typeof args.root === "string" && args.root !== ""
						? resolvePath(args.root, exec)
						: cwd];
				if (typeof args.paper === "string" && args.paper !== "") {
					argv.push("--doc", resolvePath(args.paper, exec));
				}
				if (typeof args.pdf === "string" && args.pdf !== "") {
					argv.push("--pdf", resolvePath(args.pdf, exec));
				}
				if ((args.files ?? []).length > 0) {
					argv.push("--files", ...args.files.map((file) => resolvePath(file, exec)));
				}
				if (typeof args.archive === "string" && args.archive !== "") {
					argv.push("--archive", resolvePath(args.archive, exec));
				}
				if ((args.assets ?? []).length > 0) {
					argv.push("--assets", ...args.assets.map((dir) => resolvePath(dir, exec)));
				}
				const report = await runChecker("check_spec.py", argv, { cwd });
				if (report?.ok !== true) return report;
				const failed = (report.findings ?? []).filter((finding) => finding.level === "error");
				const warned = (report.findings ?? []).filter((finding) => finding.level === "warning");
				const skipped = (report.findings ?? []).filter((finding) => finding.level === "skipped");
				return {
					...report,
					summary: {
						rules: report.spec?.rules ?? 0,
						failed: failed.length,
						warned: warned.length,
						skipped: skipped.length,
						manual: (report.findings ?? []).filter((finding) => finding.check === "manual").length
					},
					blocking: failed.map((finding) => ({
						id: finding.id, title: finding.title, detail: finding.detail, source: finding.source
					})),
					unverifiable: skipped.map((finding) => ({ id: finding.id, detail: finding.detail }))
				};
			}

			return { ok: false, error: "UNKNOWN_ACTION", action: args.action };
		},
		presentCall: (args) => ({
			card: "generic",
			title: `Spec ${args.action ?? "?"}`,
			kind: args.action === "check" ? "read" : "other",
			rawInput: args.spec ?? args.requirements
		})
	});
}
