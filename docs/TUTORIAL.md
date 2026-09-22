# Step-by-step tutorial: check your work before you hand it in

This assumes you have never used the plugin before. Following it once takes about 15 minutes.
Every step shows the command **and what you should see**, so you always know whether it worked.

Three scenarios — read the one you need:

| Scenario | Who it is for |
|---|---|
| [**A. Checking a paper**](#scenario-a-checking-a-paper) | competitions, journal submissions, theses |
| [**B. Checking a software hand-over**](#scenario-b-checking-a-software-hand-over) | delivering code, acceptance reviews |
| [**C. Only checking whether numbers went stale**](#scenario-c-only-checking-whether-numbers-went-stale) | you already have a draft and only want the numbers verified |

---

# Setup (about 5 minutes)

## 1. Make sure Python is installed

Open a terminal (`Win + R` → `cmd` on Windows) and run:

```
python --version
```

**Expect** something like `Python 3.13.x` — it must be **3.10 or newer**.
If it is missing, install it from https://www.python.org/downloads/ and tick **Add Python to PATH**.

## 2. Install the libraries the checks need

```
pip install pymupdf openpyxl pillow python-docx
```

They read PDFs, spreadsheets, image resolution, and Word documents respectively. Nothing else to configure.

## 3. Get the plugin

**Option 1 — inside DeepSeek Harness (recommended)**

```
dsh plugin --profile web add dsh-research-check
```

Restart DSH afterwards; then you can simply tell the AI "check my paper against the format rules".

**Option 2 — command line only** (no DSH needed)

```
git clone https://github.com/mikasa-servent/dsh-research-check.git
cd dsh-research-check
```

Both options give you the same command-line tools. This tutorial uses the command line because it is
the most explicit; with Option 1, replace each command with one sentence to your AI.

---

# Scenario A: checking a paper

Suppose your project folder looks like this (use your own file names):

```
my-paper/
├── format-rules.doc     ← the requirements document you were given
├── paper.tex            ← your source (or a Word file)
├── paper.pdf            ← the built PDF
├── results.xlsx         ← a file you must submit alongside
├── support.zip          ← the archive you must submit
└── figures/             ← your images
```

## Step 1 — turn the requirements into a checklist (once per project)

```
cd /d "C:\my-paper"
python "<plugin>\python\spec_build.py" ^
    --requirements format-rules.doc ^
    --out specs\my-rules.json ^
    --profile academic ^
    --name "Paper format rules"
```

**Expect** something like:

```json
{
  "ok": true,
  "out": "specs\\my-rules.json",
  "profile": "academic",
  "rules": 19,
  "bySeverity": { "hard": 15, "soft": 4, "info": 0 },
  "needsReview": [
    "Line spacing: the rule was derived for source files; if you deliver Word, verify paragraph spacing by hand."
  ]
}
```

How to read it:

- `rules: 19` — 19 requirements were found that a machine **can** check
- `hard: 15` — 15 of them are "violating this is a hard failure"
- `needsReview` — things no machine can decide (line spacing in a Word file, for example)

## Step 2 — review the checklist by hand (do not skip this)

Open `specs\my-rules.json` in a text editor and check three things:

1. **the numbers** — is `"limit": 30` really "body ≤ 30 pages"? Is `"limit": 20971520` really 20 MB?
2. **each rule's `source`** — it quotes the requirements document verbatim; confirm it was understood correctly;
3. **empty parameters** — for example:

```json
{
  "id": "gen.required_files",
  "params": { "required": [] }     ← empty, so this rule will report "not checked"
}
```

Fill those in. If the requirements say "you must submit paper.pdf, results.xlsx and code.zip":

```json
{ "required": ["paper.pdf", "results.xlsx", "code.zip"] }
```

> You cannot break anything by leaving a parameter empty: the rule reports `skipped` ("not checked")
> rather than pretending to pass.

## Step 3 — run the check

```
python "<plugin>\python\check_spec.py" ^
    --spec specs\my-rules.json ^
    --root . ^
    --doc paper.tex ^
    --pdf paper.pdf ^
    --files results.xlsx ^
    --archive support.zip ^
    --assets figures
```

Each input is optional; whatever you leave out is simply not checked:

| Argument | What to pass | Which rules use it |
|---|---|---|
| `--doc` | your LaTeX/Markdown source | line spacing, font size, table of contents, section count |
| `--pdf` | the built PDF | page counts, abstract page, blank pages, figure references |
| `--files` | loose files you must submit | file size, identity leaks in Word/Excel properties |
| `--archive` | your support archive | archive size, manifest consistency |
| `--assets` | image directory | image format, resolution, naming |

For a readable table instead of raw JSON:

```
python "<plugin>\tests\run_spec_check.py" --spec specs\my-rules.json
```

```
Spec: Paper format rules v1.0.0 (19 rules)
Verdict: fail   {'error': 1, 'warning': 0, 'info': 2, 'pass': 15, 'skipped': 1}
-----------------------------------------------------------------
[ok  ] hard  body page limit        body 30 pages / limit 30
[ok  ] hard  abstract fits one page  abstract (with keywords) fits on one page
[FAIL] hard  no identity in metadata  metadata hit: {'creator': 'Zhang San'}
[ok  ] soft  figures referenced      all referenced
[skip] hard  required files present   rule lists no required files (params.required)
```

## Step 4 — read the result and work through it

| Marker | Meaning | What to do |
|---|---|---|
| `pass` | satisfied | nothing |
| `error` | **a hard requirement is violated** | **must fix**, then re-run |
| `warning` | advisory | decide for yourself |
| `skipped` | **not checked** | supply the missing input or move it to the manual list — **do not read it as passing** |
| `info` | manual checklist | confirm by hand |

Every failure carries the `source` citation, i.e. the original wording of the requirement:

```
1 item to fix:
  · no identity in metadata — …no file may display the contestant's identity, school or region…
```

## Step 5 — the usual fixes

**① Identity information in document properties** (the most common violation)

Author names hide inside Excel/Word metadata where you cannot see them:

```
python "<plugin>\python\check_hygiene.py" --files results.xlsx notes.docx
```

**Know the limits of this check** — it reports two different levels:

| What the property contains | Result | Meaning |
|---|---|---|
| an identity keyword (school, university, region, supervisor, name, student ID, email, account-ish words) | **error** | a definite leak, must be cleared |
| a bare person name (e.g. "Zhang San") | **warning** | the keyword list cannot recognise names, so **look at it yourself** |

So when a `warning` prints the property values, open the file and confirm: if it is personal
information, clear it.

To clear: Excel/WPS → File → Info → Check for Issues → Inspect Document → Remove Personal
Information → Save. Or clear the `creator` / `lastModifiedBy` / `Company` fields in a script,
which is the practical route for a batch of files.

**② Too many pages**

Trim or re-layout. Note the **appendix does not count as body text** — the checker finds the
appendix heading and excludes everything after it automatically.

**③ Archive does not match the manifest**

Every file listed in your appendix must exist in the archive, one for one.

**④ A figure is never referenced**

Mention it in the text ("as shown in Figure 3"). Unreferenced figures are dead weight.

## Step 6 — re-run until clean

```
python "<plugin>\tests\run_spec_check.py" --spec specs\my-rules.json
```

**Goal**: `error: 0`. Then confirm the remaining `skipped` and `info` items by hand and submit.

---

# Scenario B: checking a software hand-over

Your client hands you an "acceptance criteria.docx".

```
cd /d "D:\my-project"
python "<plugin>\python\spec_build.py" ^
    --requirements acceptance-criteria.docx ^
    --out specs\acceptance.json ^
    --profile software ^
    --name "Delivery acceptance criteria"

python "<plugin>\python\check_spec.py" ^
    --spec specs\acceptance.json ^
    --root . ^
    --files README.md LICENSE CHANGELOG.md run.log ^
    --archive delivery.zip
```

What this catches for software specifically — all frequent return-to-sender reasons:

| Check | Why it matters |
|---|---|
| required files present | no `README.md` / `LICENSE` means the client cannot use it, and legally may not |
| changelog present | without `CHANGELOG.md` nobody can tell which version introduced a problem |
| error markers in logs | leaving `Traceback` / `ERROR:` in delivered logs proves nothing was tested |
| archive vs manifest | a mismatch reads as a false statement about what you delivered |

```
[ok  ] hard  source package required files   all present
[FAIL] hard  no error markers in delivered code  hit: ['Traceback (most recent call last)', 'ERROR:']
[ok  ] soft  changelog required              present
```

---

# Scenario C: only checking whether numbers went stale

This is the highest-value scenario, because the defect it catches is the hardest to spot by eye:
you updated a figure and forgot the prose.

## Step 1 — build a ledger of the key numbers and where they come from

```
cd /d "C:\my-paper"
node "<plugin>\lib\ledger-cli.js" teach ^
    --ledger ledger.json ^
    --paper paper.tex ^
    --unit-filter 万元 ^
    --min-abs 100
```

```
{ "ok": true, "candidates": 130, "added": 6,
  "note": "candidates registered; rename the keys and add the producing script, then verify." }
```

Open `ledger.json`:

```json
{
  "key": "auto.paper.tex.p0.3",
  "value": 1521.6,
  "unit": "万元",
  "anchor": "total annual cost fell from 1536.4 to 1521.6"
}
```

The value of this step: it captures **both the before and after values in one sentence**
(1536.4 and 1521.6) — exactly where a stale number survives a revision.

## Step 2 — curate the ledger

Rename `auto.paper.tex.p0.3` to something meaningful (`q3.total_cost`) and record the program
that produced it:

```json
{ "key": "q3.total_cost", "value": 1521.6, "unit": "万元",
  "source": "code/q3.py", "anchor": "total annual cost" }
```

## Step 3 — verify

```
node "<plugin>\lib\ledger-cli.js" verify ^
    --ledger ledger.json ^
    --paper paper.pdf ^
    --near
```

```
# everything fine
{ "verdict": "pass", "checked": 6, "missing": 0 }

# a real example of a defect
{
  "verdict": "fail", "missing": 1,
  "findings": [{
    "key": "q3.total_cost", "expected": 1521.6,
    "message": "ledger value 1521.6万元 not found in the document: either the text was edited without updating the ledger, or the ledger is out of date."
  }]
}
```

## Step 4 — act on it

- `missing` — the ledger value is nowhere in the document: you probably changed one side only;
- `--near` — a similar value sits at the same anchor (ledger says 1521.6, the text says 1536.4):
  **that is the stale value**.

---

# Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `NO_PYTHON` | Python missing or not on PATH | install 3.10+ and tick Add to PATH |
| garbled Chinese output | old version | upgrade to 1.4.1+ |
| many `skipped` rules | the inputs they need were not supplied | pass `--pdf` / `--files` / `--archive` |
| rules seem incomplete | unusual wording in the requirements file | open the generated spec and add rules by hand, copying the existing shape |
| a result looks wrong | a rule parameter is wrong | check `params` in the spec (page limit, size limit) |

---

# Three things to remember

1. **Requirements → spec**: feed the requirements document to `spec_build.py` once per project;
2. **Before submitting**: run `check_spec.py`, clear every `error`, confirm `skipped` and `info` by hand;
3. **After changing a number**: run `ledger verify` — it catches the "figure updated, prose not" class
   of defect that nothing else does.
