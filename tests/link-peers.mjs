/**
 * Link the DSH peer packages into this plugin's own node_modules.
 *
 * Why this is needed: `dsh plugin add link:<path>` installs the plugin as a
 * junction. Node resolves a package's imports from its **real** path, so when
 * the loader imports the linked plugin, `@deepseek-ai/dsh-tools` cannot be found
 * by walking up from the plugin directory (it lives in the DSH install).
 * Creating junctions for the peers keeps a linked checkout loadable.
 *
 * Usage:  node tests/link-peers.mjs [--unlink]
 */
import { existsSync, mkdirSync, readdirSync, rmSync, symlinkSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const PLUGIN = resolve(HERE, "..");
const PEERS = ["dsh-tools", "cordis", "schemastery"];

/** Candidate locations of the DSH-installed peer packages, in priority order. */
function candidateRoots() {
	const roots = [];
	const dshHome = process.env.DSH_HOME ?? join(homedir(), ".dsh");
	roots.push(join(dshHome, "profiles", "node_modules", "@deepseek-ai"));
	roots.push(join(dshHome, "profiles", "web", "node_modules", "@deepseek-ai"));
	// Global npm install of the harness itself.
	if (process.env.APPDATA) {
		roots.push(join(process.env.APPDATA, "npm", "node_modules", "@deepseek-ai",
			"dsh", "node_modules", "@deepseek-ai"));
	}
	return roots;
}

const unlink = process.argv.includes("--unlink");
const target = join(PLUGIN, "node_modules", "@deepseek-ai");

if (unlink) {
	for (const peer of PEERS) {
		const link = join(target, peer);
		if (existsSync(link)) rmSync(link, { recursive: true, force: true });
	}
	console.log(`[unlink] removed peer links under ${target}`);
	process.exit(0);
}

const roots = candidateRoots();
mkdirSync(target, { recursive: true });

let linked = 0;
for (const peer of PEERS) {
	const link = join(target, peer);
	if (existsSync(link)) {
		console.log(`[skip] ${peer} already present`);
		linked += 1;
		continue;
	}
	const source = roots.map((root) => join(root, peer)).find((path) => existsSync(path));
	if (source === undefined) {
		console.warn(`[warn] ${peer} not found in any of:\n  ${roots.join("\n  ")}`);
		continue;
	}
	symlinkSync(source, link, process.platform === "win32" ? "junction" : "dir");
	console.log(`[link] ${peer} -> ${source}`);
	linked += 1;
}

const available = existsSync(target) ? readdirSync(target) : [];
console.log(`\npeers linked: ${linked}/${PEERS.length} (now present: ${available.join(", ") || "none"})`);
console.log("Next: dsh plugin --profile <name> add link:" + PLUGIN);
process.exit(linked === PEERS.length ? 0 : 1);
