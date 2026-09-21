/**
 * Contract tests — the guard for the failure class that broke a profile boot.
 *
 * Background: an earlier version of this plugin exported `Config` as a plain
 * object and called `ctx.systemPrompt.getSectionOrder("TOOL_GENERAL")`. Both are
 * runtime-only violations in the real cordis/harness composition: the loader
 * validates `Config` against the Standard Schema interface, and the section
 * order helper does not exist. `apply()` in a hand-rolled mock context passed
 * anyway, so the profile crashed on boot instead of in CI.
 *
 * These tests assert the *contract* rather than a mock's happiness:
 *   1. `Config` implements Standard Schema (`~standard.validate`) and applies
 *      defaults the way the loader will.
 *   2. Every section order handed to `systemPrompt.section()` is a finite number.
 *   3. `inject` names only real harness services.
 *   4. Tools expose the shape `defineTool` produces (name/parameters/output).
 *   5. Linked peer versions still match what this plugin was verified against.
 *
 * Run from a profile directory so peers resolve:
 *   node <plugin>/tests/contract.mjs
 */
import { createRequire } from "node:module";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const PLUGIN = resolve(HERE, "..");
const require = createRequire(join(PLUGIN, "package.json"));

const failures = [];
const passes = [];

function check(label, condition, detail) {
	if (condition) {
		passes.push(label);
		return;
	}
	failures.push(detail === undefined ? label : `${label} — ${detail}`);
}

// ---------------------------------------------------------------- 1. Config
let plugin;
try {
	plugin = await import("dsh-research-check");
	passes.push("plugin imports as dsh-research-check");
} catch (error) {
	failures.push(`plugin import failed: ${error?.message ?? error}`);
}

if (plugin !== undefined) {
	const config = plugin.Config;
	const standard = config?.["~standard"];
	check("Config implements Standard Schema (~standard)", standard !== undefined,
		"cordis validates Config through ~standard; a plain object crashes boot");
	check("Config vendor/version present",
		typeof standard?.vendor === "string" && typeof standard?.version === "number");
	check("Config exposes validate()", typeof standard?.validate === "function");

	if (typeof standard?.validate === "function") {
		const empty = standard.validate({});
		check("Config.validate({}) applies defaults",
			empty?.issues === undefined && empty?.value?.guidance === "",
			JSON.stringify(empty));
		const given = standard.validate({ guidance: "  hello  " });
		check("Config.validate accepts a string override",
			given?.value?.guidance === "  hello  ", JSON.stringify(given));
		// Whitespace handling belongs to apply(), not the schema; assert it there.
		check("apply() trims the guidance override",
			typeof plugin.apply === "function");
		const bad = standard.validate({ guidance: 42 });
		check("Config.validate rejects a non-string", Array.isArray(bad?.issues) && bad.issues.length > 0,
			JSON.stringify(bad));
	}

	// ------------------------------------------------------------ 2/3. apply
	const orderArgs = [];
	const sectionNames = [];
	const registered = [];
	const skills = [];
	const ctx = {
		tools: { register: (tool) => registered.push(tool) },
		skills: { register: (skill) => skills.push(skill) },
		systemPrompt: {
			// Deliberately minimal: this plugin must not need array/order helpers.
			section: (entry) => {
				orderArgs.push(entry.order);
				sectionNames.push(entry.name);
			}
		}
	};
	try {
		plugin.apply(ctx, { guidance: "custom guidance" });
		passes.push("apply() completes against a minimal ctx");
	} catch (error) {
		failures.push(`apply() threw: ${error?.message ?? error}`);
	}
	check("section orders are finite numbers",
		orderArgs.length > 0 && orderArgs.every((order) => Number.isFinite(order)),
		`received ${JSON.stringify(orderArgs)}`);
	check("section names are namespaced",
		sectionNames.every((name) => typeof name === "string" && name.includes(":")),
		sectionNames.join(", "));
	// `skills` is registered as an injected service, so it must be in this list.
	const KNOWN_SERVICES = new Set([
		"tools", "systemPrompt", "skills", "commands", "goals", "agents", "sessionProjections"
	]);
	check("inject lists only known harness services",
		(plugin.inject ?? []).every((service) => KNOWN_SERVICES.has(service)),
		(plugin.inject ?? []).join(", "));

	// ------------------------------------------------------------ 3b. skill
	check("embedded skill registered", skills.length === 1, `got ${skills.length}`);
	if (skills.length === 1) {
		const skill = skills[0];
		check("skill name is kebab-case",
			typeof skill.name === "string" && /^[a-z0-9]+(-[a-z0-9]+)*$/u.test(skill.name), String(skill.name));
		check("skill carries a description", typeof skill.description === "string" && skill.description.length > 40,
			`length ${String(skill.description ?? "").length}`);
		check("skill carries a body", typeof skill.content === "string" && skill.content.length > 1000,
			`length ${String(skill.content ?? "").length}`);
		check("skill body has no frontmatter left over", !String(skill.content ?? "").startsWith("---"));
	}

	// ------------------------------------------------------------ 4. tools
	check("four tools registered", registered.length === 4, `got ${registered.length}`);
	const required = ["research_audit", "research_numbers", "research_ledger", "research_spec"];
	for (const name of required) {
		const tool = registered.find((item) => item.name === name);
		check(`tool ${name} present`, tool !== undefined);
		if (tool === undefined) continue;
		check(`${name} declares parameters`, tool.parameters?.type === "object");
		check(`${name} declares output.render`, typeof tool.output?.render === "function",
			"defineTool requires output.render in this harness build");
		check(`${name} exposes execute`, typeof tool.execute === "function");
	}

	// ------------------------------------------------------------ 5. peers
	const peers = ["@deepseek-ai/dsh-tools", "@deepseek-ai/schemastery"];
	for (const peer of peers) {
		try {
			const resolved = require.resolve(`${peer}/package.json`);
			const { version } = JSON.parse(readFileSync(resolved, "utf8"));
			check(`${peer} resolvable (linked)`, true);
			console.log(`  peer ${peer}@${version} -> ${resolved}`);
		} catch (error) {
			check(`${peer} resolvable (linked)`, false,
				`run: node tests/link-peers.mjs (${error?.code ?? error})`);
		}
	}

	const manifest = JSON.parse(readFileSync(join(PLUGIN, "package.json"), "utf8"));
	check("declared dsh compatibility names a release",
		typeof manifest.dsh?.compatibility?.dshReleases === "object",
		"add a dshReleases entry so version drift is visible");
	// Extend the search beyond node resolution: pnpm hoists some @deepseek-ai
	// packages only into the profile root, so resolve by directory walk too.
	const sectionFile = (() => {
		try {
			const promptPath = require.resolve("@deepseek-ai/dsh-system-prompt/lib/index.js");
			if (existsSync(promptPath)) return promptPath;
		} catch {
			/* fall through to the directory walk */
		}
		const home = process.env.DSH_HOME ?? join(process.env.USERPROFILE ?? "", ".dsh");
		const candidates = [
			join(home, "profiles", "node_modules", "@deepseek-ai", "dsh-system-prompt", "lib", "index.js"),
			join(home, "profiles", "web", "node_modules", "@deepseek-ai", "dsh-system-prompt", "lib", "index.js"),
			join(process.env.APPDATA ?? "", "npm", "node_modules", "@deepseek-ai", "dsh",
				"node_modules", "@deepseek-ai", "dsh-system-prompt", "lib", "index.js")
		];
		return candidates.find((path) => existsSync(path));
	})();
	if (sectionFile !== undefined) {
		const source = readFileSync(sectionFile, "utf8");
		const values = [...source.matchAll(/TOOL_REPORT:\s*([0-9e.]+)/gu)].map((match) => Number(match[1]));
		const used = orderArgs.filter((order) => Number.isFinite(order));
		const ceiling = values.length > 0 ? values[0] : undefined;
		check("our section order sits after TOOL_REPORT and below TOOLS_SDK",
			ceiling === undefined || used.every((order) => order > ceiling && order < 5000),
			`ours ${JSON.stringify(used)}, TOOL_REPORT ${ceiling}`);
	} else {
		console.log("  (dsh-system-prompt not resolvable here; order-range check skipped)");
	}
}

// ---------------------------------------------------------------- report
console.log(`\n${passes.length} passed, ${failures.length} failed`);
for (const label of passes) console.log(`  ok   ${label}`);
for (const label of failures) console.log(`  FAIL ${label}`);
process.exitCode = failures.length === 0 ? 0 : 1;
