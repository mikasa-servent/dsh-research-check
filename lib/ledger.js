/**
 * Provenance ledger: the durable record that binds every number in a paper to
 * the program output it came from.
 *
 * The ledger is a single JSON document next to the paper. Entries are keyed by
 * a stable name (`q3.total_cost`) rather than by value, so re-running a program
 * can refresh values without touching the manuscript text.
 * @module dsh-research-check/ledger
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

/** Current on-disk schema version. */
export const SCHEMA = 1;

/** Load a ledger, returning an empty skeleton when the file is absent. */
export function loadLedger(path) {
	const target = resolve(path);
	if (!existsSync(target)) {
		return {
			schema: SCHEMA,
			updated: new Date().toISOString(),
			entries: []
		};
	}
	const parsed = JSON.parse(readFileSync(target, "utf8"));
	return {
		schema: parsed.schema ?? SCHEMA,
		updated: parsed.updated,
		paper: parsed.paper,
		entries: Array.isArray(parsed.entries) ? parsed.entries : []
	};
}

/** Persist a ledger, creating parent directories on demand. */
export function saveLedger(path, ledger) {
	const target = resolve(path);
	mkdirSync(dirname(target), { recursive: true });
	const next = { ...ledger, schema: SCHEMA, updated: new Date().toISOString() };
	writeFileSync(target, `${JSON.stringify(next, null, 2)}\n`, "utf8");
	return target;
}

/**
 * Record (or update) one number with its provenance.
 * @returns The stored entry.
 */
export function addEntry(ledger, input) {
	if (typeof input.key !== "string" || input.key.trim() === "") {
		throw new TypeError("ledger entry requires a non-empty key");
	}
	if (typeof input.value !== "number" || !Number.isFinite(input.value)) {
		throw new TypeError(`ledger entry ${input.key} requires a finite numeric value`);
	}
	const entry = {
		key: input.key.trim(),
		value: input.value,
		unit: input.unit ?? null,
		source: input.source ?? null,
		anchor: input.anchor ?? null,
		note: input.note ?? null,
		revision: (findEntry(ledger, input.key.trim())?.revision ?? 0) + 1,
		updated: new Date().toISOString()
	};
	const index = ledger.entries.findIndex((item) => item.key === entry.key);
	if (index >= 0) ledger.entries[index] = entry;
	else ledger.entries.push(entry);
	return entry;
}

/** Look up one entry by key. */
export function findEntry(ledger, key) {
	return ledger.entries.find((entry) => entry.key === key);
}

/**
 * Verify that every ledger entry still appears in the extracted numbers.
 * @param ledger - Ledger document.
 * @param numbers - Flat list of `{value, unit, source, page, context}` hits.
 * @param options - Relative and absolute tolerances.
 * @returns Findings in the shared `{level, message, ...}` shape.
 */
export function verifyEntries(ledger, numbers, options = {}) {
	const rel = options.rel ?? 0.01;
	const absTol = options.absTol ?? 0.005;
	const findings = [];
	for (const entry of ledger.entries) {
		const hits = numbers.filter((hit) => close(hit.value, entry.value, rel, absTol));
		if (hits.length === 0) {
			findings.push({
				level: "error",
				key: entry.key,
				expected: entry.value,
				unit: entry.unit,
				message:
					`台账值 ${format(entry.value)}${entry.unit ?? ""} 在文档中未找到：` +
					"可能是改写文字时漏改，或台账未随稿更新（先跑源程序刷新台账，再核对正文）。",
				where: entry.source ?? entry.note ?? ""
			});
			continue;
		}
		// Same-anchor probe: a stale value often survives elsewhere in the text,
		// so also look for a *plausibly conflicting* number inside the entry's own
		// anchor. Plausible means same unit and within one order of magnitude —
		// otherwise unrelated nearby figures (e.g. 35.1 万元 inside a sentence about
		// 1521.6 万元) would be reported as conflicts.
		if (entry.anchor) {
			const anchors = String(entry.anchor)
				.split(/[|｜,，、;；\s]+/u)
				.filter((part) => part.length >= 2);
			const magnitude = Math.abs(entry.value);
			const suspects = numbers.filter((hit) => {
				if (hit.unit !== entry.unit) return false;
				if (close(hit.value, entry.value, rel, absTol)) return false;
				const size = Math.abs(hit.value);
				if (size < 10) return false;
				if (size < magnitude / 10 || size > magnitude * 10) return false;
				if (anchors.length === 0) return false;
				return anchors.some((anchor) => (hit.context ?? "").includes(anchor));
			});
			for (const suspect of suspects.slice(0, 3)) {
				findings.push({
					level: "error",
					key: entry.key,
					expected: entry.value,
					found: suspect.value,
					unit: entry.unit,
					message:
						`同一锚点（${anchors.join("/")}）处出现的 ${format(suspect.value)}${entry.unit} ` +
						`与台账值 ${format(entry.value)}${entry.unit} 不一致。`,
					where: `${suspect.source}${suspect.page ? ` 第 ${suspect.page} 页` : ""}｜${(suspect.context ?? "").slice(0, 70)}`
				});
			}
			if (suspects.length > 0) continue;
		}
		findings.push({
			level: "info",
			key: entry.key,
			expected: entry.value,
			unit: entry.unit,
			message: `台账值 ${format(entry.value)}${entry.unit ?? ""} 已在文档中命中 ${hits.length} 处`,
			where: `${hits[0].source}${hits[0].page ? ` 第 ${hits[0].page} 页` : ""}`
		});
	}
	return findings;
}

/**
 * Aggressive stale-value probe: same unit, within one order of magnitude, and
 * near the entry's own anchor, but not equal to the ledger value. Opt-in
 * because it can surface unrelated neighbouring figures; useful when a value
 * was revised and the old number may still survive somewhere in the text.
 */
export function probeNearby(ledger, numbers, options = {}) {
	const rel = options.rel ?? 0.01;
	const absTol = options.absTol ?? 0.005;
	const findings = [];
	for (const entry of ledger.entries) {
		if (typeof entry.value !== "number" || !entry.anchor) continue;
		const anchors = String(entry.anchor)
			.split(/[|｜,，、;；\s]+/u)
			.filter((part) => part.length >= 2);
		if (anchors.length === 0) continue;
		const magnitude = Math.abs(entry.value);
		for (const hit of numbers) {
			if (hit.unit !== entry.unit) continue;
			if (close(hit.value, entry.value, rel, absTol)) continue;
			const size = Math.abs(hit.value);
			if (size < magnitude / 10 || size > magnitude * 10) continue;
			if (!anchors.some((anchor) => (hit.context ?? "").includes(anchor))) continue;
			findings.push({
				level: "warning",
				key: entry.key,
				expected: entry.value,
				found: hit.value,
				unit: entry.unit,
				message:
					`锚点“${anchors.join("/")}”附近出现量级相近的 ${format(hit.value)}${entry.unit}，` +
					`与台账值 ${format(entry.value)}${entry.unit} 不同；请人工确认是否陈旧数据。`,
				where: `${hit.source}${hit.page ? ` 第 ${hit.page} 页` : ""}｜${(hit.context ?? "").slice(0, 70)}`
			});
		}
	}
	return findings;
}

/** Numeric closeness with a relative floor so small values are not over-matched. */
function close(a, b, rel, absTol) {
	const scale = Math.max(Math.abs(a), Math.abs(b), 1e-12);
	return Math.abs(a - b) <= Math.max(absTol, rel * scale);
}

/** Human-facing number formatting shared by reports. */
export function format(value) {
	if (Number.isInteger(value)) return String(value);
	return String(Number(value.toFixed(6)));
}

/** Compact statistics for reports and tool output. */
export function ledgerStats(ledger) {
	const withSource = ledger.entries.filter((entry) => entry.source).length;
	return {
		entries: ledger.entries.length,
		withSource,
		withoutSource: ledger.entries.length - withSource,
		units: [...new Set(ledger.entries.map((entry) => entry.unit).filter(Boolean))].sort()
	};
}
