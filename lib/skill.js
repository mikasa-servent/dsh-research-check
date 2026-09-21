/**
 * Embedded copy of the `research-evidence-check` skill.
 *
 * The standalone `skill/SKILL.md` is the source of truth for agent-harness users
 * (Claude Code, DSH, anything that scans a skills directory). This module loads
 * the same file at runtime and registers it with `ctx.skills`, so installing the
 * plugin makes the skill available without copying files around.
 * @module dsh-research-check/skill
 */
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
/** Absolute path of the standalone skill document. */
export const SKILL_PATH = resolve(HERE, "..", "skill", "SKILL.md");

/** Fallback metadata used when the document cannot be read. */
const FALLBACK = {
	name: "research-evidence-check",
	description:
		"Verify that a data-driven paper's numbers, figures and claims are mutually consistent and "
		+ "traceable to program output, and audit the submission package for hygiene before publishing."
};

/**
 * Parse the YAML frontmatter of a SKILL.md document.
 *
 * Deliberately minimal: the frontmatter uses flat `key: value` scalars, so a
 * dependency-free parse is enough and keeps the plugin installable anywhere.
 * @param raw - Full document text.
 * @returns Frontmatter fields plus the trimmed body.
 */
export function parseSkillDocument(raw) {
	const match = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/u.exec(raw);
	if (match === null) return { data: {}, body: raw.trim() };
	const data = {};
	for (const line of match[1].split(/\r?\n/u)) {
		const separator = line.indexOf(":");
		if (separator <= 0) continue;
		const key = line.slice(0, separator).trim();
		const value = line.slice(separator + 1).trim().replace(/^["']|["']$/gu, "");
		if (key !== "" && value !== "") data[key] = value;
	}
	return { data, body: match[2].trim() };
}

/**
 * Read and register the skill.
 * @param ctx - Cordis context exposing `skills` and `logger`.
 * @param config - `register` toggles registration; `path` overrides the document.
 * @returns The registered skill summary, or `undefined` when registration is off.
 */
export function registerSkill(ctx, config = {}) {
	if (config.register === false) return undefined;
	if (typeof ctx?.skills?.register !== "function") {
		ctx?.logger?.warn?.("dsh-research-check: ctx.skills unavailable; embedded skill not registered");
		return undefined;
	}
	let parsed = { data: {}, body: "" };
	try {
		parsed = parseSkillDocument(readFileSync(config.path ?? SKILL_PATH, "utf8"));
	} catch (error) {
		ctx?.logger?.warn?.(`dsh-research-check: cannot read skill document: ${error?.message ?? error}`);
	}
	const name = typeof parsed.data.name === "string" && parsed.data.name !== ""
		? parsed.data.name
		: FALLBACK.name;
	const description = typeof parsed.data.description === "string" && parsed.data.description !== ""
		? parsed.data.description
		: FALLBACK.description;
	const body = parsed.body === "" ? description : parsed.body;
	const skill = {
		name,
		description,
		...(typeof parsed.data.whenToUse === "string" ? { whenToUse: parsed.data.whenToUse } : {}),
		content: body
	};
	ctx.skills.register(skill);
	ctx?.logger?.info?.(`dsh-research-check: registered skill ${name}`);
	return skill;
}

/** Summary used by tests without touching a real registry. */
export function readSkillSummary(path) {
	const parsed = parseSkillDocument(readFileSync(path ?? SKILL_PATH, "utf8"));
	return {
		name: parsed.data.name,
		description: parsed.data.description,
		whenToUse: parsed.data.whenToUse,
		bodyLength: parsed.body.length
	};
}

export { join };
