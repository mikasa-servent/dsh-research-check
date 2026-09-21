/**
 * Host-agnostic conformance engine.
 *
 * Both consumers call this module and only differ in how they expose results:
 *   - the DSH plugin (`lib/tools.js`, `lib/spec-tool.js`) wraps it as harness tools;
 *   - the MCP server (`mcp/server.mjs`) wraps it as MCP tools for any other host.
 *
 * Keeping the engine free of host APIs is what makes "works in other harnesses" a
 * structural property rather than a promise: there is exactly one implementation of
 * each operation, and every host is a thin adapter over it.
 * @module dsh-research-check/core
 */
import { existsSync } from "node:fs";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { addEntry, ledgerStats, loadLedger, probeNearby, saveLedger, verifyEntries } from "./ledger.js";
import { runChecker, summarize } from "./util.js";

/**
 * Build a spec from a requirements document.
 * @param options - Paths plus the deliverable profile.
 * @returns The checker report, augmented with a next-step hint.
 */
export async function specBuild(options) {
	if (!options.requirements || !options.spec) {
		return { ok: false, error: "MISSING_ARGS", message: "specBuild 需要 requirements 与 spec 两个路径" };
	}
	const argv = ["--requirements", options.requirements, "--out", options.spec];
	if (options.name) argv.push("--name", options.name);
	if (options.profile) argv.push("--profile", options.profile);
	const report = await runChecker("spec_build.py", argv, { cwd: options.cwd });
	if (report?.ok !== true) return report;
	return {
		...report,
		next: "逐条复核：确认 params（页数/体积/required/manifest 等）与 source 引用，"
			+ "补齐留空参数，再执行 check。"
	};
}

/**
 * Grade a deliverable against a spec.
 * @param options - Spec path plus whichever sources exist.
 * @returns The report with a compact summary, blocking list and unverifiable list.
 */
export async function specCheck(options) {
	if (!options.spec) return { ok: false, error: "MISSING_SPEC", message: "specCheck 需要 spec 路径" };
	const argv = ["--spec", options.spec, "--root", options.root ?? options.cwd ?? process.cwd()];
	if (options.document) argv.push("--doc", options.document);
	if (options.pdf) argv.push("--pdf", options.pdf);
	if ((options.files ?? []).length > 0) argv.push("--files", ...options.files);
	if (options.archive) argv.push("--archive", options.archive);
	if ((options.assets ?? []).length > 0) argv.push("--assets", ...options.assets);
	const report = await runChecker("check_spec.py", argv, { cwd: options.cwd });
	if (report?.ok !== true) return report;
	const findings = report.findings ?? [];
	const failed = findings.filter((finding) => finding.level === "error");
	const warned = findings.filter((finding) => finding.level === "warning");
	const skipped = findings.filter((finding) => finding.level === "skipped");
	return {
		...report,
		summary: {
			rules: report.spec?.rules ?? 0,
			failed: failed.length,
			warned: warned.length,
			skipped: skipped.length,
			manual: findings.filter((finding) => finding.check === "manual").length
		},
		blocking: failed.map((finding) => ({
			id: finding.id, title: finding.title, detail: finding.detail, source: finding.source
		})),
		unverifiable: skipped.map((finding) => ({ id: finding.id, detail: finding.detail }))
	};
}

/**
 * Audit a deliverable's files (page limits, metadata leaks, archive manifest).
 * @param options - Paper/composite paths plus companion files.
 * @returns The checker report.
 */
export async function audit(options) {
	if (!options.paper) return { ok: false, error: "MISSING_PAPER", message: "audit 需要 paper（成稿 PDF）路径" };
	const argv = ["--paper", options.paper];
	for (const file of options.files ?? []) argv.push(...["--files", file]);
	for (const archive of options.archives ?? []) argv.push(...["--archives", archive]);
	if ((options.manifest ?? []).length > 0) argv.push("--manifest", ...options.manifest);
	if (typeof options.maxBodyPages === "number") argv.push("--max-body-pages", String(options.maxBodyPages));
	if (typeof options.maxMb === "number") argv.push("--max-mb", String(options.maxMb));
	if ((options.appendixMarker ?? []).length > 0) argv.push("--appendix-marker", ...options.appendixMarker);
	return runChecker("audit_paper.py", argv, { cwd: options.cwd });
}

/**
 * Check number consistency, optionally against a ledger.
 * @param options - Document sources, evidence files, optional ledger.
 * @returns The checker report; ledger findings are merged when a ledger is given.
 */
export async function numbers(options) {
	const papers = options.paper ?? options.documents ?? [];
	if (papers.length === 0) return { ok: false, error: "MISSING_INPUT", message: "numbers 需要至少一个文稿源" };
	const argv = ["--paper", ...papers];
	if ((options.data ?? options.evidence ?? []).length > 0) {
		argv.push("--data", ...(options.data ?? options.evidence));
	}
	if (options.ledger) argv.push("--ledger", options.ledger, "--emit-hits");
	if (typeof options.tolerance === "number") argv.push("--tol", String(options.tolerance));
	const report = await runChecker("check_numbers.py", argv, { cwd: options.cwd });
	if (report?.ok !== true || !options.ledger) return report;

	const ledger = loadLedger(options.ledger);
	const hits = report.numbers ?? [];
	const findings = verifyEntries(ledger, hits);
	const near = probeNearby(ledger, hits);
	return {
		...report,
		ledger: { path: options.ledger, ...ledgerStats(ledger) },
		ledgerVerdict: summarize(findings).verdict,
		ledgerFindings: [...findings.filter((f) => f.level === "error"), ...near]
	};
}

/**
 * Maintain the provenance ledger.
 * @param options - `action` plus action-specific arguments.
 * @returns A structured result; only `teach` and `add` write.
 */
export async function ledger(options) {
	const path = options.ledger ?? "paper-ledger.json";
	const action = options.action;

	if (action === "list") {
		const current = loadLedger(path);
		return { ok: true, action, ledger: path, stats: ledgerStats(current), entries: current.entries };
	}

	if (action === "add") {
		const current = loadLedger(path);
		let entry;
		try {
			entry = addEntry(current, {
				key: options.key ?? "",
				value: Number(options.value),
				unit: options.unit ?? null,
				source: options.source ?? null,
				anchor: options.anchor ?? null
			});
		} catch (error) {
			return { ok: false, action, error: "INVALID_ENTRY", message: String(error?.message ?? error) };
		}
		saveLedger(path, current);
		return { ok: true, action, ledger: path, entry, stats: ledgerStats(current) };
	}

	const papers = options.paper ?? options.documents ?? [];
	if (papers.length === 0) {
		return { ok: false, action, error: "MISSING_PAPER", message: "teach/verify 需要至少一个文稿源" };
	}
	const check = await runChecker("check_numbers.py", ["--paper", ...papers, "--emit-hits"],
		{ cwd: options.cwd });
	if (check?.ok !== true) return { ok: false, action, error: check };
	const hits = check.numbers ?? [];

	if (action === "teach") {
		const current = loadLedger(path);
		const units = options.unitFilter ?? options.unit_filter ?? [];
		const minAbs = typeof options.minAbs === "number" ? options.minAbs : 1;
		let added = 0;
		let candidates = 0;
		for (const hit of hits) {
			if (!hit.unit) continue;
			candidates += 1;
			if (units.length > 0 && !units.includes(hit.unit)) continue;
			if (Math.abs(hit.value) < minAbs) continue;
			added += 1;
			addEntry(current, {
				key: `auto.${hit.source ?? "document"}.p${hit.page ?? 0}.${added}`,
				value: hit.value,
				unit: hit.unit,
				source: `${hit.source ?? "document"}${hit.page ? ` 第 ${hit.page} 页` : ""}`,
				anchor: hit.context
			});
		}
		saveLedger(path, current);
		return {
			ok: true, action, ledger: path, candidates, added,
			stats: ledgerStats(current),
			note: "候选条目已登记；请把 key 改成语义名并补上 source 程序路径，再用于 verify。"
		};
	}

	if (action === "verify") {
		const current = loadLedger(path);
		if (current.entries.length === 0) {
			return { ok: false, action, error: "LEDGER_EMPTY", ledger: path };
		}
		const findings = verifyEntries(current, hits);
		const near = probeNearby(current, hits);
		const problems = findings.filter((finding) => finding.level === "error");
		return {
			ok: true, action, ledger: path,
			verdict: problems.length > 0 ? "fail" : (near.length > 0 ? "warn" : "pass"),
			checked: current.entries.length,
			missing: problems.length,
			nearby: near.length,
			scanned: hits.length,
			findings: [...problems, ...near,
				...(options.verbose === true ? findings.filter((f) => f.level === "info") : [])]
		};
	}

	return { ok: false, error: "UNKNOWN_ACTION", action };
}

/** Copy an example spec into the workspace so a user can start from a known shape. */
export function writeSpecTemplate(path, template) {
	const target = resolve(path);
	mkdirSync(dirname(target), { recursive: true });
	writeFileSync(target, `${JSON.stringify(template, null, 2)}\n`, "utf8");
	return { ok: true, path: target, exists: existsSync(target) };
}

export { RULE_VOCABULARY, PROFILES } from "./spec-tool.js";
