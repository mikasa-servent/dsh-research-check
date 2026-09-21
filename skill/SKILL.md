---
name: research-evidence-check
description: Verify that a deliverable's claims, numbers, figures and files are mutually consistent and traceable to their sources; turn a requirements document (competition rules, journal guidelines, acceptance criteria, tender documents) into an executable specification and grade the deliverable against it; audit the files for hand-over hygiene. Works for papers, technical documentation, software hand-overs, datasets and bid responses — only the rule set changes. Use when numbers were edited in prose, when figures were regenerated, when a rule set must be applied before submission, when a package or archive is being assembled, or when someone questions where a number or a file came from.
whenToUse: The deliverable, its figures, or its result files have changed; a rule set (competition format, journal guidelines, acceptance criteria, tender requirements) must be applied; a submission or hand-over package is being assembled; or a specific number's or file's origin must be established.
---

# Deliverable evidence check

Deliverables are rejected for mechanical reasons, not scientific ones: a number updated
in a figure caption but not in the prose, a total that disagrees with the sum of its
parts, a stale value left behind after a revision, an author name leaking through
document metadata, a page limit exceeded by one page, a required file missing from the
package, an archive whose contents no longer match the manifest. This skill is the
procedure for catching those before a reviewer, an acceptance committee or a client does.

The procedure is identical whatever is being delivered — a paper, a manual, a software
package, a dataset, a bid. Only the rule set changes.

## Core principles

**Every number in the final text must resolve to exactly one of three sources:**

1. program output (a script, notebook, or result file that can be re-run),
2. a data file shipped with the work (or the task's attachments),
3. an explicit definition (a parameter, a conversion, a derived formula).

A number that resolves to none of the three is a defect even when it happens to be
correct, because nothing can check it later.

**Every requirement that will be graded must exist as a checkable rule.** A rule living
only in someone's memory ("正文不超过 30 页" / "交付包必须含 LICENSE") is not
enforceable; once it is in a spec file it can be re-verified after every edit.

**A rule that cannot run must report `skipped`, never a silent pass.** Missing input,
missing optional library, or an unfilled parameter all mean "not verified".

## Phase 0 — Encode the requirements before writing

Convert the rule set once per delivery:

```
research_spec(action="build", requirements="format2026.doc", spec="submissions/cumcm-2026.json",
              profile="academic", name="2026 全国大学生数学建模竞赛（论文格式规范）")

research_spec(action="build", requirements="验收标准.docx", spec="specs/acceptance.json",
              profile="software", name="软件交付验收标准")

research_spec(action="build", requirements="数据交付要求.md", spec="specs/data.json",
              profile="dataset", name="数据交付检查表")
```

Profiles pick the rule pack (`research_spec(action="list")` prints them):

| profile | for | typical rules |
|---|---|---|
| `academic` | papers, theses, journal submissions | page limits, one-page abstract, figure/table references, margins |
| `docs` | manuals, specs, white papers | paragraph length, version string, contact info, TODO residue |
| `software` | software hand-over, acceptance, releases | required files, LICENSE, CHANGELOG, error-marker residue |
| `dataset` | data delivery, dataset cards | required columns, row count, sensitive columns, data dictionary |
| `tender` | bids, grant applications | required sections, point-by-point response |
| `generic` | any deliverable | size, naming, identity metadata, manifest consistency, placeholders |

Then **read the generated spec and correct it** before trusting it:

- check each rule's `params` — page limits, size limits, `required` file/column lists,
  `manifest` entries. A rule with empty params reports `skipped`: honest, but useless;
- read each `source` citation: a rule whose citation does not say what the rule claims
  must be fixed or deleted;
- leave `check: "manual"` items alone — they are genuinely unverifiable by tool and
  belong on a human checklist. Never "upgrade" them to a fake automated check.

## Phase 1 — Establish the ledger before editing text

Record each number that will appear in the paper, keyed by meaning rather than by
value, together with the artifact that produced it:

```
research_ledger(action="add", key="q3.total_cost", value=1521.6, unit="万元",
                source="code/q3_rolling_mpc.py", anchor="全年费用")
```

- Key by **meaning** (`q3.total_cost`), never by value — re-running the program must
  not require editing the manuscript.
- `anchor` is a short fixed phrase near the number in the text; it is what makes
  stale-value detection possible later.
- Units go in `unit`, values stay numeric, so `1.5 万元` and `15000 元` are not two
  different facts.

If the paper already exists and no ledger does, bootstrap one and then curate it:

```
research_ledger(action="teach", ledger="paper-ledger.json", paper=["paper/main.tex"],
                unit_filter=["万元","kWh"], min_abs=100)
```

`teach` registers every magnitude-bearing number with the sentence it came from.
Rename the generated keys to semantic names and add the producing script; an
uncurated ledger still detects missing values but cannot tell you where they came from.

### 2. Re-run programs, then verify the paper

After any change to code or data, re-run the producing programs, refresh the ledger
values, and then check the manuscript:

```
research_numbers(paper=["paper/main.tex"], ledger="paper-ledger.json")
research_ledger(action="verify", ledger="paper-ledger.json", paper=["paper/main.pdf"])
```

Interpretation:

- **error** — the ledger value does not appear anywhere in the text (edited away, or
  the ledger was not refreshed), or a value of the same unit and comparable
  magnitude sits at the same anchor with a different number.
- **warning** — the same sentence shape carries two different values for the same
  unit. Often a legitimate contrast (two scenarios, before/after), so confirm by
  reading the sentence rather than "fixing" it.

Prefer `.tex`/`.md` sources for iteration (fast, unaffected by line breaking) and the
built PDF for the final pass (it is what the reviewer reads).

### 3. Grade against the spec

```
research_spec(action="check", spec="submissions/cumcm-2026.json",
              paper="paper/main.tex", pdf="论文初稿.pdf",
              files=["论文初稿.pdf", "support.zip"], archive="support.zip")
```

Reading the result:

- **error** (`severity: hard`) — blocking; fix before submitting, and quote the rule's
  `source` citation when explaining why the constraint exists.
- **warning** (`severity: soft`) — judgement call; may be acceptable with a reason.
- **skipped** — the rule could not be evaluated (missing input, missing optional
  library). Never report a skipped rule as passing; either supply the input or move it
  to the manual checklist.
- **manual** — genuinely unverifiable by tool. Walk the checklist by hand and say so.

Re-run this after every rebuild. Page-limit rules are the ones that silently flip
when a figure moves.

### 4. Audit the manuscript itself

```
research_audit(paper="论文初稿.pdf",
               files=["AI 工具使用详情.docx", "result1.xlsx"],
               archives=["support.zip"],
               manifest=["result1.xlsx", "q1_final_two_stage.py", "AI 工具使用详情.pdf"],
               max_body_pages=30)
```

Covers: body/page limits (appendix excluded via the heading marker), abstract on the
first page, blank pages, unreferenced figure/table numbers, PDF size, identity leaks
in PDF metadata, author/company fields inside DOCX/XLSX/ZIP payloads, and whether the
archive contents still match the manifest the appendix claims.

Use `research_spec` when a rule set exists (it carries severities and citations);
use `research_audit` for an ad-hoc pass when no spec has been written yet.

### 5. When a number legitimately changes

Treat a revision as a three-step transaction, never one:

1. update the producing program, re-run it, refresh the ledger value;
2. update the prose **and** the figure/table that carries the same number;
3. re-run `research_numbers` — a value that survives in prose after its caption was
   updated is exactly the defect this skill exists to catch.

## What this skill does not do

- It does not decide which of two conflicting numbers is correct; it reports the
  conflict and the location, and the author resolves it.
- It does not recompute formulas from raw data. Values are matched, not re-derived —
  so a wrong number recorded consistently in both program and text will pass. Re-derive
  independently when a number matters to the conclusion.
- It does not judge prose quality, novelty, or methodology.

## Reporting

State findings as: what was checked, what disagreed, where (file, page, sentence
fragment), and the two candidate values. Never silently "repair" a manuscript number:
report it and let the author choose, because only the author knows which side is stale.
