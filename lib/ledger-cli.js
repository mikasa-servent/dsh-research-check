#!/usr/bin/env node
/**
 * Standalone ledger CLI for the research-check plugin.
 *
 * Usage:
 *   node lib/ledger-cli.js add    --ledger L.json --key q3.total_cost --value 1521.6 --unit 万元 --source code/q3.py
 *   node lib/ledger-cli.js verify --ledger L.json --paper paper.pdf paper.tex [--tol 0.01]
 *   node lib/ledger-cli.js teach  --ledger L.json --paper paper.tex [--unit-filter 万元,kWh]
 *   node lib/ledger-cli.js list   --ledger L.json
 *
 * Number extraction is delegated to the packaged Python checker so that the
 * plugin's text parsing stays in one place.
 */
import { runChecker } from "./util.js";
import {
	addEntry, format, ledgerStats, loadLedger, probeNearby, saveLedger, verifyEntries
} from "./ledger.js";

function parseArgv(argv) {
	const [command, ...rest] = argv;
	const flags = { _: [] };
	for (let index = 0; index < rest.length; index += 1) {
		const token = rest[index];
		if (!token.startsWith("--")) {
			flags._.push(token);
			continue;
		}
		const name = token.slice(2);
		const next = rest[index + 1];
		if (next === undefined || next.startsWith("--")) {
			flags[name] = true;
			continue;
		}
		if (flags[name] === undefined) flags[name] = [];
		if (Array.isArray(flags[name])) flags[name].push(next);
		else flags[name] = [flags[name], next];
		index += 1;
	}
	return { command, flags };
}

function asList(value) {
	if (value === undefined || value === true) return [];
	return Array.isArray(value) ? value : [value];
}

function asString(value) {
	if (value === undefined || value === true) return undefined;
	return Array.isArray(value) ? value[0] : value;
}

async function extractNumbers(paths, cwd) {
	if (paths.length === 0) return { hits: [], error: undefined };
	const report = await runChecker("check_numbers.py", ["--paper", ...paths, "--emit-hits"], { cwd });
	if (report?.ok !== true) return { hits: [], error: report };
	return { hits: report.numbers ?? [], error: undefined, report };
}

function emit(payload) {
	process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
}

async function main() {
	const { command, flags } = parseArgv(process.argv.slice(2));
	const ledgerPath = asString(flags.ledger) ?? "paper-ledger.json";
	const cwd = process.cwd();

	if (command === "add") {
		const ledger = loadLedger(ledgerPath);
		const entry = addEntry(ledger, {
			key: asString(flags.key) ?? "",
			value: Number(asString(flags.value)),
			unit: asString(flags.unit) ?? null,
			source: asString(flags.source) ?? null,
			anchor: asString(flags.anchor) ?? null,
			note: asString(flags.note) ?? null
		});
		saveLedger(ledgerPath, ledger);
		emit({ ok: true, op: "add", entry, ledger: ledgerPath, stats: ledgerStats(ledger) });
		return 0;
	}

	if (command === "list") {
		const ledger = loadLedger(ledgerPath);
		emit({ ok: true, op: "list", ledger: ledgerPath, stats: ledgerStats(ledger), entries: ledger.entries });
		return 0;
	}

	if (command === "teach") {
		const papers = asList(flags.paper);
		const { hits, error } = await extractNumbers(papers, cwd);
		if (error) {
			emit({ ok: false, op: "teach", error });
			return 2;
		}
		const units = asList(flags["unit-filter"]);
		const minAbs = Number(asString(flags["min-abs"]) ?? 1);
		const ledger = loadLedger(ledgerPath);
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
		emit({
			ok: true,
			op: "teach",
			ledger: ledgerPath,
			candidates,
			added,
			stats: ledgerStats(ledger),
			note: "候选条目已登记，请把 key 改成便于引用的语义名（如 q3.total_cost），并补上 source 程序路径。"
		});
		return 0;
	}

	if (command === "verify") {
		const ledger = loadLedger(ledgerPath);
		if (ledger.entries.length === 0) {
			emit({ ok: false, op: "verify", error: "LEDGER_EMPTY", ledger: ledgerPath });
			return 2;
		}
		const papers = asList(flags.paper);
		const { hits, error } = await extractNumbers(papers, cwd);
		if (error) {
			emit({ ok: false, op: "verify", error });
			return 2;
		}
		const findings = verifyEntries(ledger, hits, {
			rel: Number(asString(flags.tol) ?? 0.01)
		});
		const near = flags.near === true
			? probeNearby(ledger, hits, { rel: Number(asString(flags.tol) ?? 0.01) })
			: [];
		const problems = findings.filter((finding) => finding.level === "error");
		emit({
			ok: true,
			op: "verify",
			ledger: ledgerPath,
			verdict: problems.length > 0 ? "fail" : (near.length > 0 ? "warn" : "pass"),
			checked: ledger.entries.length,
			missing: problems.length,
			nearby: near.length,
			scanned: hits.length,
			findings: [...problems, ...near, ...(flags.verbose
				? findings.filter((finding) => finding.level === "info")
				: [])]
		});
		return problems.length > 0 ? 1 : 0;
	}

	emit({
		ok: false,
		error: "UNKNOWN_COMMAND",
		usage: [
			"add    --ledger L.json --key K --value V [--unit U] [--source S] [--anchor A]",
			"verify --ledger L.json --paper P [--tol 0.01] [--verbose]",
			"teach  --ledger L.json --paper P [--unit-filter 万元] [--min-abs 1]",
			"list   --ledger L.json"
		]
	});
	return 2;
}

/** Add an entry into a freshly loaded ledger (helper for the teach loop). */

main().then((code) => {
	process.exitCode = code;
}).catch((error) => {
	emit({ ok: false, error: "UNCAUGHT", message: String(error?.stack ?? error) });
	process.exitCode = 2;
});
