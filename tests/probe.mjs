/**
 * Load-and-register smoke test for dsh-research-check, run from the profile
 * directory so Node resolves @deepseek-ai/* peers from the profile's own
 * node_modules (a linked plugin's real path is outside the profile tree).
 *
 * Usage (from ~/.dsh/profiles/<name>):
 *   node ./node_modules/dsh-research-check/tests/probe.mjs
 */
import { defineTool } from "@deepseek-ai/dsh-tools";

const registered = [];
const sections = [];
const ctx = {
	tools: { register: (tool) => registered.push(tool) },
	systemPrompt: {
		getSectionOrder: (key) => {
			void key;
			return 100;
		},
		section: (entry) => sections.push(entry)
	}
};

const plugin = await import("dsh-research-check");
if (typeof plugin.apply !== "function") throw new Error("plugin does not export apply()");
if (!Array.isArray(plugin.inject)) throw new Error("plugin does not export inject[]");
if (typeof defineTool !== "function") throw new Error("defineTool unavailable — peer not resolvable");

plugin.apply(ctx, {});

const report = {
	name: plugin.name,
	inject: plugin.inject,
	configKeys: Object.keys(plugin.Config ?? {}),
	promptSections: sections.map((section) => section.name),
	tools: registered.map((tool) => ({
		name: tool.name,
		parameters: Object.keys(tool.parameters ?? {}),
		hasExecute: typeof tool.execute === "function"
	}))
};
console.log(JSON.stringify(report, null, 2));
if (registered.length === 0) throw new Error("no tools registered");
console.log(`\n[OK] ${registered.length} tools registered by dsh-research-check`);
