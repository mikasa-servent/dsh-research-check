/**
 * Minimal stand-in for `@deepseek-ai/schemastery`, for dependency-free tests.
 *
 * Implements just enough of the Standard Schema interface for the plugin's
 * `Config` export to be validated the way cordis validates it:
 * `{ "~standard": { vendor, version, validate(value) } }`.
 *
 * The real bug this guards against: exporting `Config` as a plain object made
 * cordis read `config["~standard"].validate` off `undefined` and crash the whole
 * profile on boot.
 * @module dsh-research-check/tests/stub-schemastery
 */

class Schema {
	constructor(description) {
		this.description = description;
		this["~standard"] = {
			vendor: "dsh-research-check-stub",
			version: 1,
			validate: (value) => this.validate(value)
		};
	}

	/** Validate and apply defaults, mirroring schemastery's object behaviour. */
	validate(value) {
		const input = value === undefined || value === null ? {} : value;
		if (typeof input !== "object" || Array.isArray(input)) {
			return { issues: [{ message: "expected an object" }] };
		}
		const out = {};
		const issues = [];
		for (const [key, field] of Object.entries(this.description.fields ?? {})) {
			const provided = input[key];
			if (provided === undefined) {
				if (field.hasDefault) out[key] = field.defaultValue;
				continue;
			}
			if (typeof provided !== field.type) {
				issues.push({ message: `${key} must be ${field.type}`, path: [key] });
				continue;
			}
			out[key] = provided;
		}
		return issues.length > 0 ? { issues } : { value: out };
	}
}

/** Schema for a string field. */
function string() {
	const field = { type: "string", hasDefault: false, defaultValue: undefined };
	return {
		...field,
		default(value) {
			return { type: "string", hasDefault: true, defaultValue: value };
		},
		_meta: field
	};
}

/** Schema for a boolean field. */
function boolean() {
	return {
		type: "boolean",
		default(value) {
			return { type: "boolean", hasDefault: true, defaultValue: value };
		}
	};
}

/** Build an object schema from a map of field schemas. */
function object(fields) {
	const normalised = {};
	for (const [key, field] of Object.entries(fields)) {
		const meta = field?._meta ?? field;
		normalised[key] = {
			type: meta.type,
			hasDefault: meta.hasDefault === true,
			defaultValue: meta.defaultValue
		};
	}
	return new Schema({ fields: normalised });
}

export default { object, string, boolean };
export { boolean, object, string };
