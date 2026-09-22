# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.5.0] - 2026-09-22

### Added

- **Beginner-facing documentation.** The README now leads with what the plugin actually catches
  (ten real defects, each with its consequence) instead of installation instructions, and two
  step-by-step tutorials ship with it:
  - [docs/TUTORIAL.zh.md](docs/TUTORIAL.zh.md) — 中文，三个场景（论文 / 软件交付 / 数字核对），
    每步都有命令与预期输出；
  - [docs/TUTORIAL.md](docs/TUTORIAL.md) — the same three scenarios in English.
- **`tests/verify_tutorial.py`** — executes every command the tutorials tell a reader to run,
  against a generated example project, and compares the output with what the tutorial claims.
  A tutorial that does not work is worse than no tutorial, so it is now a tested artifact.
- `check_hygiene.py` distinguishes two levels where it previously reported one: an identity
  *keyword* hit remains a hard error, while a property holding a bare person name — which the
  keyword list cannot recognise — now raises a warning that prints the values so a human decides.
  Reporting "no identity words found" for a field that plainly holds an author name was
  technically true and practically misleading.

### Notes

- Verified: 26 assertions in `tests/verify_tutorial.py` pass, covering the spec build, the
  conformance check, the hygiene check (all three outcomes), the ledger flow, and the
  `software` profile.

## [1.4.1] - 2026-09-22

### Fixed

- **The published tarball contained Python bytecode caches and the test suite.** 1.4.0
  shipped 30 files / 149 kB including `python/__pycache__/*.pyc` and `tests/`; it is now
  23 files / 73 kB. Root cause: `.gitignore` has no effect on npm packing, and a directory
  named in `package.json`'s `files` allow-list cannot exclude a subdirectory of itself —
  `.npmignore` removed `tests/` but not `__pycache__`. The allow-list now names files.
- **The checkers crashed on a GBK console.** Chinese Windows defaults to code page 936;
  the checkers printed Chinese JSON encoded as GBK while the reader decoded UTF-8, raising
  `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xc0`. It broke `npm publish`
  through the `prepublishOnly` hook, and CI could not see it because GitHub runners are
  UTF-8 by default. `python/encoding_guard.py` now forces UTF-8 on stdout/stderr
  (`errors="replace"`, so one bad character cannot fail a whole compliance report), and
  every checker calls it first thing in `main()`.
- **Peer ranges silently excluded harness prereleases.** `>=0.1.2-rc.1` matches
  `0.1.2-rc.1` but not `0.1.3-rc.1`; `>=0.1.0-rc.1 <0.2.0-0` matches `0.1.0-rc.1` but not
  `0.1.2-rc.1`. node-semver only admits a prerelease when a comparator on the *same*
  `major.minor.patch` tuple carries a prerelease tag, so the ranges are now
  `^0.1.2 || >=0.1.2-rc.1` (and equivalents for cordis and schemastery), verified with
  semver against the installed harness.
- Tests no longer depend on the author's machine: the hygiene test builds its own OOXML
  fixture instead of copying a local file, and both e2e tests take the workspace from
  `DSH_RESEARCH_WORKSPACE` and skip cleanly when it is absent.

### Added

- **`tests/pack-inventory.mjs`** — asserts what `npm pack` actually ships: no bytecode
  caches, no tests, every Python module and host adapter present, size budget enforced.
  It runs the real packer rather than reading configuration, so a future re-inclusion
  fails the build.

## [1.4.0] - 2026-09-21

### Added

- **MCP server** (`mcp/server.mjs`): a dependency-free JSON-RPC 2.0 stdio server that
  exposes the same operations to any MCP-capable host (Claude Code, Codex, Cursor, or
  DSH through its own mcp-client plugin). Tools: `spec_build`, `spec_check`, `audit`,
  `numbers`, `ledger`, `list_rules`.
- **Host-agnostic engine** (`lib/core.js`): every operation now has exactly one
  implementation (`specBuild`, `specCheck`, `audit`, `numbers`, `ledger`). The DSH
  plugin and the MCP server are thin adapters over it, so the two surfaces cannot
  drift apart; `lib/tools.js` holds no business logic as a result.
- **`tests/mcp-smoke.mjs`**: drives the real MCP wire protocol over stdio — initialize
  handshake, tool listing, one real call, unknown-tool and unknown-method errors — and
  asserts the host-visible constraints (name shape, object input schemas, JSON payload).

### Notes

- Verified after the refactor: 20 modules parse, marketplace readiness 35, dependency-free
  contract 33, MCP protocol 20, harness contract 38, tool e2e 4/4 calls.

## [1.3.0] - 2026-09-21

### Added

- **Cross-harness skill packaging**: `skill/SKILL.md` is the single source of truth for
  the procedure, loaded at runtime by `lib/skill.js` and also usable standalone from any
  skills directory (`~/.dsh/skills`, `~/.agents/skills`, `<project>/.dsh/skills`).
- Repository metadata for publishing: `marketplace-entry.json` (community registry
  entry), `LICENSE`, CI workflow, and a `prepublishOnly` hook that runs the test suite.

### Changed

- Skill renamed conceptually from a paper procedure to a **deliverable** procedure: five
  phases, six deliverable profiles, and an explicit rule that a rule which cannot run
  reports `skipped` rather than passing.

## [1.2.0] - 2026-09-21

### Added

- **Rule packs by deliverable type** (`python/rule_packs.py`). The capability was never
  paper-specific — only the rule library was. `spec_build.py --profile` now selects a
  pack, and `research_spec(action="list")` advertises the profiles:

  | profile | for | rules |
  |---|---|---|
  | `academic` | papers, theses, journal submissions | 29 |
  | `docs` | manuals, specs, white papers | 13 |
  | `software` | software hand-over, acceptance, releases | 15 |
  | `dataset` | data delivery, dataset cards | 14 |
  | `tender` | bids, grant applications | 12 |
  | `generic` | any deliverable | 9 |

- **Eleven new checks**, all domain-neutral: `required_files_present`,
  `placeholder_text`, `max_paragraph_chars`, `required_text_pattern`,
  `version_string_present`, `dataset_columns_present`, `dataset_row_count`,
  `dataset_no_sensitive_columns`.
- **`tests/test_generality.py`** — grades three non-paper deliverables (software package,
  dataset, technical document) with their own requirement documents, each in a clean and
  a defective variant. Clean must pass; every planted defect must be caught. A rule pack
  that can only say "pass" fails this test.
- CI gained the cross-domain step, so the rule packs cannot silently rot.

### Fixed

- `forbidden_text` only searched the manuscript source and PDF, so **a Traceback in a
  delivered `run.log` passed the rule**. Delivered files are now searched too.
- `collect_deliverable_text` did not recognise `.log` (nor `.out`, `.err`, source-code
  suffixes), which is why the above gap was invisible.
- `gen.office_identity` required a narrow phrasing ("所有文件中…"), so a requirement
  saying only "不能有显示参赛者身份的信息" produced a PDF-metadata rule but **no
  Office-metadata rule** — the exact leak class this plugin was written for. Both rules
  now share one trigger, and the Office rule reports `skipped` when no Office file is
  supplied rather than pretending to pass.
- Rule-pack patterns were too literal for real requirements prose: paragraph limits
  missed "每段不超过…", version rules missed "文档必须出现版本号", required-file rules
  missed "提供 README.md", error-marker rules missed "不得出现 Traceback 与 ERROR 标记".
  All were widened after the generality test failed on them.
- `tests/test_spec_offline.py` asserted on rule **ids** (`bundle.manifest`), which broke
  when the generic pack renamed ids to `gen.archive_manifest`; assertions now select
  findings by `check` name.

### Notes

- Verified: real CUMCM rule set still yields 19 rules with 0 errors on the 87-page
  manuscript; the three non-paper cases each pass clean and catch their planted defects.

## [1.1.0] - 2026-09-14

### Added

- **`research_spec` tool** — turn a requirements document into an executable
  specification and grade a deliverable against it:
  - `build` template-matches a requirements file (`.doc`/`.docx`/`.md`/`.txt`) into a
    spec JSON; each rule carries a `check`, a `severity`, a `scope` and a **citation**;
  - `check` evaluates the spec against LaTeX source, the built PDF, submitted files
    and an optional support archive;
  - `list` prints the rule vocabulary (30 checks).
- **Two new checkers**: `python/spec_build.py` (requirements → spec) and
  `python/check_spec.py` (spec → graded report), plus `tests/run_spec_check.py` for a
  formatted CLI run.
- **Archive-manifest recovery**: when a spec leaves `manifest` empty, the appendix's
  file list is recovered automatically — by following `\input` chains to the section
  holding the manifest table, falling back to appendix pages of the PDF with the
  source-code appendix excluded. Comparison is space- and script-insensitive, so
  "AI 工具使用详情.pdf" matches an archive entry stored without the space.
- **New checks worth calling out**: `abstract_within_page` (index-based, so a dense
  single-page abstract is not a false positive), `margins_min` (e.g. ≥2.5 cm),
  `office_metadata_no_identity` (DOCX/XLSX author fields), `bundle_no_forbidden_files`,
  `asset_min_dpi`.
- **CI** (`.github/workflows/verify.yml`): a Node 22/24 job for syntax + marketplace
  readiness + a **dependency-free** runtime contract test, and a Python job that
  compiles the checkers and runs the offline regression suite.
- `tests/stub-tools.js` and `tests/stub-schemastery.js`: minimal stand-ins for the DSH
  peers, so the runtime contract is testable without a harness checkout.
- `tests/test_spec_offline.py`: synthesises a whole submission (source, PDF, archive)
  and asserts **three negative controls** — page-limit breach, archive missing a
  manifest entry, planted identity metadata in a spreadsheet — each of which must fail.

### Changed

- Skill `research-evidence-check` gained a Phase 0 (encode requirements before writing)
  and a Phase 3 (grade against the spec), including how to read `error` / `warning` /
  `skipped` / `manual` so a skipped rule is never reported as passing.
- `tests/syntax-check.mjs` now enumerates modules dynamically; the previous
  hand-maintained list had silently stopped covering new files.
- `npm test` runs five stages: syntax → marketplace readiness → dependency-free
  contract → harness e2e → offline spec regression.

### Fixed

- `office_metadata_no_identity` was implemented in the checker but **no rule template
  ever produced it**, so DOCX/XLSX identity leaks could not be caught through a
  generated spec. A template (plus an explicit skip when no Office file is supplied)
  now exists.
- The abstract-span rule used a geometry threshold, which misreported a densely filled
  but legitimately single-page abstract; it is now index-based, with the legacy
  parameter still honoured for older spec files.
- Manifest recovery produced prose fragments ("结构同result4-2.xlsx") and split filenames
  at LaTeX-escaped underscores ("\_stage.py"); both are fixed by harvesting filename
  tokens after unescaping and deciding matches at comparison time.

### Notes

- Verified against a real rule set (2026 CUMCM format specification, **18 rules
  extracted, 13 of them `hard`**) and a real 87-page manuscript: 15 pass, 0 errors,
  0 warnings, 1 skipped (a rule whose inputs were not supplied).

## [1.0.0] - 2026-09-14

First public release. Marketplace-ready package with tools, an embedded skill, and
a verification suite that covers the failure modes found while using it on a real
87-page manuscript.

### Added

- **Tools** (host side, model-facing):
  - `research_audit` — submission hygiene: body/page limits, abstract on the first
    page, blank pages, unreferenced figure/table numbers, PDF size, identity leaks in
    PDF metadata, author/company fields inside DOCX/XLSX payloads, and consistency
    between a support archive and the manifest the appendix claims.
  - `research_numbers` — number consistency: same-sentence conflicting values, plus
    per-entry ledger verification when a ledger is supplied.
  - `research_ledger` — provenance ledger with `teach` (bootstrap from a manuscript),
    `add` (record key + value + unit + source + anchor), `verify`, `list`.
- **Skill**: `research-evidence-check` (`skill/SKILL.md`), also registered at runtime
  through `ctx.skills.register`, so installing the plugin makes the procedure
  available without copying files.
- **Checkers** (Python 3, dependency-free for text; `pymupdf`/`openpyxl` for PDF and
  spreadsheet input): `check_numbers.py`, `audit_paper.py`, `check_hygiene.py`.
- **Ledger CLI** (`lib/ledger-cli.js`) usable without DSH.
- **Verification suite**: `tests/registry-manifest.mjs` (packaging and marketplace
  readiness), `tests/contract.mjs` (cordis/harness runtime contracts),
  `tests/e2e.mjs` (real tool execution), `tests/boot-check.mjs` (real profile boot),
  `tests/test_hygiene_negative.py` (planted identity metadata must be reported).

### Fixed

While hardening the plugin before release, four defects were found and fixed; each
now has a regression test, because each one had shipped at least once:

- `Config` was a plain object, which cordis v4 rejects (it must implement the
  Standard Schema interface) — this crashed the whole profile on boot.
- The guidance section called a non-existent `ctx.systemPrompt.getSectionOrder`,
  producing `order must be a finite number` at boot. Section orders are numeric and
  internal, so the value is now written literally and asserted against the prompt
  package's own table.
- A linked install could not resolve `@deepseek-ai/dsh-tools`/`schemastery` because
  Node resolves from the package's real path; `tests/link-peers.mjs` now creates the
  junctions.
- Tools were registered without the `output.render` contract that this harness build
  requires at call time.

### Notes

- Known limitation: values are matched, not re-derived, so a number that is wrong but
  recorded consistently in both program and manuscript will pass. Independent
  re-derivation is still the author's responsibility for conclusion-critical numbers.
