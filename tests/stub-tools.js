/**
 * Minimal stand-in for `@deepseek-ai/dsh-tools`' `defineTool`, used by tests that
 * run without a DSH checkout (CI, a bare clone).
 *
 * It reproduces the contract this plugin actually depends on:
 *   - arguments are validated against the implicit property map, so a tool with a
 *     malformed schema fails the same way it would in the harness;
 *   - `output.render` is mandatory (the real harness reads `options.output.render`
 *     unconditionally, which is what once broke tool registration at call time);
 *   - the returned object carries name/parameters/output/execute.
 *
 * It deliberately does NOT re-implement execution policy, presentation or
 * concurrency; those are covered by the harness-backed contract test instead.
 * @module dsh-research-check/tests/stub-tools
 */

const TYPES = new Set(["string", "number", "boolean", "object", "array"]);

/** Compile the implicit parameter map into a JSON-schema-like object. */
function parameterSchema(spec = {}) {
	const properties = {};
	const required = [];
	for (const [key, definition] of Object.entries(spec)) {
		const type = definition?.type;
		if (!TYPES.has(type)) throw new TypeError(`parameter ${key}: unsupported type ${String(type)}`);
		properties[key] = {
			type,
			...(definition.items === undefined ? {} : { items: definition.items }),
			...(definition.enum === undefined ? {} : { enum: definition.enum }),
			...(definition.description === undefined ? {} : { description: definition.description })
		};
		if (definition.required === true) required.push(key);
	}
	return { type: "object", properties, ...(required.length > 0 ? { required } : {}) };
}

/** Validate arguments against the compiled schema; returns violation strings. */
function validate(schema, args) {
	const violations = [];
	if (args === null || typeof args !== "object") return ["arguments must be an object"];
	for (const key of schema.required ?? []) {
		if (args[key] === undefined) violations.push(`${key} is required`);
	}
	for (const [key, value] of Object.entries(args)) {
		const property = schema.properties[key];
		if (property === undefined) continue;
		if (value === undefined || value === null) continue;
		const actual = Array.isArray(value) ? "array" : typeof value;
		if (actual !== property.type && !(property.type === "number" && actual === "number")) {
			violations.push(`${key} must be ${property.type}, got ${actual}`);
		}
		if (property.enum !== undefined && !property.enum.includes(value)) {
			violations.push(`${key} must be one of ${property.enum.join(" | ")}`);
		}
	}
	return violations;
}

/**
 * Drop-in replacement for the harness `defineTool`.
 * @param options - `{name, description, parameters, output, execute, presentCall}`.
 */
export function defineTool(options) {
	if (typeof options?.name !== "string" || options.name === "") {
		throw new TypeError("defineTool requires a non-empty name");
	}
	if (options.output === undefined || typeof options.output.render !== "function") {
		throw new TypeError(`defineTool(${options.name}): output.render is required by this harness build`);
	}
	const schema = parameterSchema(options.parameters);
	return {
		name: options.name,
		description: options.description,
		parameters: schema,
		output: {
			schema: options.output.schema,
			render: (args, value) => options.output.render(args, value)
		},
		async execute(args, exec) {
			const violations = validate(schema, args);
			if (violations.length > 0) {
				throw new TypeError(`invalid arguments for ${options.name}: ${violations.join("; ")}`);
			}
			return options.execute(args, exec);
		},
		...(typeof options.presentCall === "function"
			? { presentCall: (args) => options.presentCall(args) }
			: {})
	};
}
