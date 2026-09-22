# -*- coding: utf-8 -*-
"""规格符合性校验（deliverable conformance check）。

把"要求"变成可执行的合同：读一份 spec JSON，对着论文（LaTeX 源码 / PDF /
OOXML 文档）逐条判定，输出带出处引用的结构化报告。

核心原则：
  · 每条规则必须声明一种已知的 check，否则视为无效规则（拒绝执行）；
  · 无法机器判定的要求放人工清单（manual），绝不假装能查；
  · 每条判定都带 source 引用，便于向评委/编辑解释依据；
  · 报告区分 hard / soft / info，并给出 measured 与 expected，便于复现。

用法：
  python check_spec.py --spec submissions/2026-cumcm.json --root . \
      --doc paper/main.tex --pdf 论文初稿.pdf \
      [--files result1.xlsx "AI 工具使用详情.docx"] [--archive support.zip] \
      [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from encoding_guard import force_utf8_output

# --------------------------------------------------------------------------
# 判定器注册表：check 名 -> 需要的输入源
# --------------------------------------------------------------------------
# 源标记：src = 源码文本，pdf = PDF 文件，docx = OOXML 文件，sizes = 文件大小，
#         assets = 素材目录清单，bundle = 压缩包
KNOWN_CHECKS: dict[str, set[str]] = {
    # 版面（PDF）
    "max_pages": {"pdf", "sections"},
    "min_pages": {"pdf"},
    "abstract_first_page": {"pdf"},
    "abstract_within_page": {"pdf"},
    "no_blank_page": {"pdf"},
    "all_figures_referenced": {"pdf"},
    "all_tables_referenced": {"pdf"},
    "max_pdf_bytes": {"pdf"},
    "metadata_no_identity": {"pdf"},
    # 结构（源码/文本）
    "max_sections": {"src"},
    "max_subsections_per_section": {"src"},
    "no_toc": {"src"},
    "forbidden_text": {"src", "pdf"},
    # 源码级排版
    "linespread_min": {"src", "srcfile"},
    "fontsize_min": {"src"},
    "page_geometry": {"src"},
    "margins_min": {"src"},
    "bibliography_placeholders": {"src"},
    "math_in_abstract": {"src"},
    # 素材
    "asset_format": {"assets"},
    "asset_naming": {"assets"},
    "asset_min_dpi": {"assets"},
    "no_asset_duplicates": {"assets"},
    # 交付物（与领域无关）
    "file_size_max": {"sizes"},
    "office_metadata_no_identity": {"docx", "sizes"},
    "file_naming": {"sizes"},
    "manifest_matches_archive": {"bundle"},
    "archive_size_max": {"bundle"},
    "bundle_no_forbidden_files": {"bundle"},
    "required_files_present": {"sizes"},
    "placeholder_text": {"src", "docx"},
    "max_paragraph_chars": {"docx", "src"},
    "required_text_pattern": {"src", "docx"},
    "version_string_present": {"src", "docx"},
    # 数据交付
    "dataset_columns_present": {"docx", "sizes"},
    "dataset_row_count": {"docx", "sizes"},
    "dataset_no_sensitive_columns": {"docx", "sizes"},
}

MANUAL_ALLOWED = {"manual"}


def is_valid_rule(rule: dict) -> tuple[bool, str]:
    """A rule is only executable when it names a known check or is manual."""
    check = rule.get("check")
    if check is None:
        return False, "规则缺少 check 字段"
    if check in MANUAL_ALLOWED:
        return True, ""
    if check not in KNOWN_CHECKS:
        return False, f"未知 check：{check}（可查 check_spec.py 的 KNOWN_CHECKS）"
    return True, ""


# --------------------------------------------------------------------------
# 输入采集
# --------------------------------------------------------------------------
class Sources:
    """Lazily-loaded inputs shared by every rule."""

    def __init__(self, root: Path, doc: Path | None, pdf: Path | None,
                 files: list[Path], archive: Path | None, assets: list[Path]):
        self.root = root
        self.doc = doc
        self.pdf_path = pdf
        self.files = files
        self.archive = archive
        self.asset_roots = assets
        self._doc = doc.read_text(encoding="utf-8", errors="ignore") if doc and doc.exists() else ""
        self._pages: list[str] | None = None
        self._asset_list: list[Path] | None = None

    # -- 文本（含去注释的纯文本版本，用于结构/排版判定） --
    @property
    def doc_text(self) -> str:
        return self._doc

    @property
    def doc_clean(self) -> str:
        return strip_latex_comments(self._doc)

    @property
    def body_text(self) -> str:
        """Source text before the appendix (used by source-scope rules)."""
        text = self.doc_clean
        marker = re.search(r"\\appendix|\\section\{附录", text)
        return text[: marker.start()] if marker else text

    # -- PDF --
    def pages(self) -> list[str]:
        if self._pages is None:
            try:
                import pymupdf  # type: ignore
            except ImportError as error:  # pragma: no cover - environment dependent
                raise RuntimeError("需要 pymupdf 才能读取 PDF：pip install pymupdf") from error
            doc = pymupdf.open(self.pdf_path)
            self._pages = [page.get_text() for page in doc]
            self._meta = {k: v for k, v in (doc.metadata or {}).items() if v}
            doc.close()
        return self._pages

    def pdf_meta(self) -> dict:
        self.pages()
        return getattr(self, "_meta", {})

    # -- 素材 --
    def assets(self) -> list[Path]:
        if self._asset_list is None:
            found: list[Path] = []
            for root in self.asset_roots:
                base = root if root.is_absolute() else self.root / root
                if base.is_file():
                    found.append(base)
                elif base.is_dir():
                    found.extend(p for p in base.rglob("*") if p.is_file())
            self._asset_list = found
        return self._asset_list


def strip_latex_comments(text: str) -> str:
    return re.sub(r"(?<!\\)%.*", "", text)


def find_appendix_page(pages: list[str], markers: tuple[str, ...]) -> int | None:
    """Appendix heading must start a page; body prose often says “见附录”."""
    accepted = tuple(markers) + ("附录", "Appendix", "APPENDIX")
    for index, text in enumerate(pages, start=1):
        head = re.sub(r"\s+", " ", text[:30]).strip()
        if head == "":
            continue
        prefix = re.match(r"^[A-Za-z]\s+", head)
        tail = head[prefix.end():] if prefix else head
        if any(tail.startswith(marker) for marker in accepted):
            return index
    return None


def parse_length(value, base: int = 0) -> int:
    """Accept an int, a digit string, or a simple arithmetic expression."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"[-+*/(). 0-9]+", text):
            try:
                return int(eval(text, {"__builtins__": {}}, {}))  # noqa: S307 - sandboxed arithmetic
            except Exception:  # noqa: BLE001 - fall back to the literal below
                pass
        digits = re.findall(r"\d+", text)
        if digits:
            return int(digits[0])
    return base


def as_number(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        if match:
            return float(match.group(0))
    return None


# --------------------------------------------------------------------------
# 判定器
# --------------------------------------------------------------------------
def judge(rule: dict, src: Sources) -> dict:
    """Evaluate one rule and return a finding without the rule metadata."""
    check = rule["check"]
    params = rule.get("params") or {}
    scope = rule.get("scope", "document")

    # ---------------- 版面 ----------------
    if check in {"max_pages", "min_pages"}:
        pages = src.pages()
        total = len(pages)
        appendix = find_appendix_page(pages, tuple(params.get("appendix_marker", ["附录"])))
        if scope == "body" and appendix is not None:
            measured = appendix - 1
            span = f"正文（附录自第 {appendix} 页起）"
        else:
            measured = total
            span = "整份"
        limit = parse_length(params.get("limit"))
        if check == "max_pages":
            ok = measured <= limit
            detail = f"{span} {measured} 页 / 上限 {limit} 页"
        else:
            ok = measured >= limit
            detail = f"{span} {measured} 页 / 下限 {limit} 页"
        return {"level": "pass" if ok else rule["_severity"], "measured": measured,
                "expected": {"limit": limit, "scope": scope}, "detail": detail}

    if check == "abstract_first_page":
        page = re.sub(r"\s+", "", src.pages()[0][:300]) if src.pages() else ""
        words = params.get("keywords", ["摘要", "abstract"])
        ok = any(word.lower() in page.lower() for word in words)
        return {"level": "pass" if ok else rule["_severity"], "measured": page[:40],
                "expected": words, "detail": "首页含摘要" if ok else "首页前 300 字未出现摘要标识"}

    if check == "abstract_within_page":
        # Index-based decision: the abstract starts on some page, so the first numbered
        # body heading must not share that page. The pattern requires a separator
        # (period or CJK enumeration mark) after the number: a bare "1 result1.xlsx"
        # inside an appendix file list is not a heading and must not end the search.
        # A geometry heuristic was tried first and reported a false positive on a dense
        # but legitimately single-page abstract.
        try:
            import pymupdf  # type: ignore
        except ImportError:
            return {"level": "skipped", "measured": None, "expected": "摘要不跨页",
                    "detail": "需要 pymupdf 才能逐页判定"}
        heading = params.get("body_heading_pattern", r"^\s*[0-9]{1,2}\s*[.、．]")
        # Backwards compatibility: an earlier spec revision carried a geometry
        # threshold instead; when only that is present, fall back to a line-geometry
        # decision so old spec files keep working.
        legacy_fraction = params.get("body_below_fraction")
        marker_words = params.get("keywords", ["摘要", "Abstract"])
        doc = pymupdf.open(src.pdf_path)
        try:
            pages = [page.get_text() for page in doc]
        finally:
            doc.close()
        if legacy_fraction is not None and "body_heading_pattern" not in params:
            document = pymupdf.open(src.pdf_path)
            try:
                page = document[0]
                lines = [line for block in page.get_text("dict")["blocks"]
                         if block.get("type") == 0 for line in block.get("lines", [])]
                if not lines:
                    return {"level": "skipped", "measured": None, "expected": "摘要不跨页",
                            "detail": "首页无可解析文本行"}
                threshold = float(legacy_fraction)
                body_start = max(line["bbox"][3] for line in lines)
                fits = body_start <= page.rect.height * threshold
                return {"level": "pass" if fits else rule["_severity"],
                        "measured": {"last_line_y": round(body_start, 1),
                                     "page_height": round(page.rect.height, 1)},
                        "expected": {"摘要主体结束于首页 %.0f%% 高度以内" % (threshold * 100)},
                        "detail": "摘要主体在首页内" if fits else "摘要主体延伸到首页底部，疑似跨页"}
            finally:
                document.close()

        start = next((i for i, text in enumerate(pages[:4])
                      if any(word in text for word in marker_words)), None)
        if start is None:
            return {"level": "skipped", "measured": None, "expected": "摘要不跨页",
                    "detail": "前 4 页未找到摘要标识，无法定位摘要页"}
        end = None
        for index in range(start, min(start + 3, len(pages))):
            if re.search(heading, pages[index], re.M):
                end = index
                break
        span = None if end is None else end - start + 1
        # `end` is the first page carrying a numbered body heading. The abstract fits
        # when that heading is on the abstract's page or the very next one; only two or
        # more pages of separation mean the abstract itself spilled (`start` is the page
        # holding the 关键词/Keywords marker).
        fits = end is None or end <= start + 1
        return {
            "level": "pass" if fits else rule["_severity"],
            "measured": {"abstract_page": start + 1, "first_heading_page": None if end is None else end + 1,
                         "span_pages": span},
            "expected": "摘要占用 1 页",
            "detail": ("摘要（含关键词）在 1 页内" if fits
                       else f"摘要跨 {span} 页：第 {start + 1}～{end + 1} 页（正文标题已挤入摘要页）"),
        }

    if check == "no_blank_page":
        pages = src.pages()
        appendix = find_appendix_page(pages, tuple(params.get("appendix_marker", ["附录"])))
        span = pages[: appendix - 1] if (scope == "body" and appendix) else pages
        blanks = [i + 1 for i, text in enumerate(span) if len(text.strip()) < int(params.get("min_chars", 20))]
        return {"level": "pass" if not blanks else rule["_severity"], "measured": blanks,
                "expected": "无空白页", "detail": "无空白页" if not blanks else f"疑似空白页：{blanks[:8]}"}

    if check in {"all_figures_referenced", "all_tables_referenced"}:
        word = "图" if check.startswith("all_figures") else "表"
        text = "\n".join(src.pages())
        captions = {m.group(1) for m in re.finditer(rf"^{word}\s*([0-9]+)", text, re.M)}
        refs = set(re.findall(rf"{word}\s*([0-9]+)\s*(?:[（(]|和|、|,|，|\s)", text)) | set(
            re.findall(rf"(?:见|如|由|按)\s*{word}\s*([0-9]+)", text))
        unreferenced = sorted(captions - refs, key=lambda x: int(x))
        return {"level": "pass" if not unreferenced else rule["_severity"], "measured": unreferenced,
                "expected": f"每张{word}都被正文引用",
                "detail": "全部被引用" if not unreferenced else f"未被引用：{word}{unreferenced[:10]}"}

    if check == "max_pdf_bytes":
        size = src.pdf_path.stat().st_size
        limit = parse_length(params.get("limit"))
        ok = size <= limit
        return {"level": "pass" if ok else rule["_severity"], "measured": size,
                "expected": {"max_bytes": limit},
                "detail": f"{size / 1024 / 1024:.2f} MB" + ("" if ok else f" 超过上限 {limit / 1024 / 1024:g} MB")}

    if check == "metadata_no_identity":
        words = params.get("words", ["学校", "大学", "学院", "赛区", "指导教师", "姓名", "学号"])
        meta = src.pdf_meta()
        hits = {k: v for k, v in meta.items()
                if k.lower() in {"author", "creator", "title", "subject", "keywords"}
                and any(w in str(v) for w in words)}
        return {"level": "pass" if not hits else rule["_severity"], "measured": hits,
                "expected": f"属性不含 {words}",
                "detail": "属性未见身份信息" if not hits else f"属性命中：{hits}"}

    # ---------------- 结构（源码） ----------------
    if check == "max_sections":
        text = src.body_text if scope == "body" else src.doc_clean
        # Count first occurrences: appendix sections restart numbering (A, B, C),
        # so a plain regex count would double-count a body section's first mention.
        hard = len(re.findall(r"\\section\{", text))
        soft = len(re.findall(r"\\section\*\{", text))
        if hard >= 3:
            count = hard
        else:
            numbered = {v for v in re.findall(r"\\section\{([0-9]+)", text)}
            count = len(numbered) or (hard + soft)
        limit = parse_length(params.get("limit"))
        return {"level": "pass" if count <= limit else rule["_severity"], "measured": count,
                "expected": {"limit": limit},
                "detail": f"{count} 个章节（\\section {hard} 个、\\section* {soft} 个）/ 上限 {limit}"}

    if check == "max_subsections_per_section":
        text = src.body_text if scope == "body" else src.doc_clean
        chunks = re.split(r"\\section\{", text)[1:]
        worst = max((len(re.findall(r"\\subsection\{", chunk)) for chunk in chunks), default=0)
        limit = parse_length(params.get("limit"))
        return {"level": "pass" if worst <= limit else rule["_severity"], "measured": worst,
                "expected": {"limit": limit}, "detail": f"单个 section 最多 {worst} 个 subsection"}

    if check == "no_toc":
        text = src.doc_clean
        found = bool(re.search(r"\\tableofcontents|\\contentsname", text))
        return {"level": "pass" if not found else rule["_severity"], "measured": found,
                "expected": False, "detail": "未生成目录" if not found else "检测到 \\tableofcontents"}

    if check == "forbidden_text":
        words = params.get("words", [])
        text = src.doc_clean if src.doc_text else ""
        pdf_text = "\n".join(src.pages()) if src.pdf_path else ""
        # Delivered files matter too: a software hand-over is judged on its run logs
        # and generated reports, not only on the source manuscript (this was a real
        # coverage gap — a Traceback in run.log passed the rule).
        file_text = collect_deliverable_text(
            Sources(root=src.root, doc=None, pdf=None, files=src.files, archive=None, assets=[]),
            use_pdf=False)
        haystack = re.sub(r"\s+", "", text + "\n" + pdf_text + "\n" + file_text)
        hits = [w for w in words if re.sub(r"\s+", "", w) in haystack]
        return {"level": "pass" if not hits else rule["_severity"], "measured": hits,
                "expected": f"不出现 {words}",
                "detail": ("未出现禁用文本" if not hits
                           else f"命中：{hits}（已检查源码/PDF/交付文件）")}

    # ---------------- 源码级排版 ----------------
    if check == "linespread_min":
        text = src.doc_clean
        values = [float(v) for v in re.findall(r"\\linespread\{([0-9.]+)\}", text)]
        baselines = [float(v) for v in re.findall(r"\\baselineskip\s*=?\s*([0-9.]+)\\baselineskip", text)]
        effective = min(values) if values else None
        limit = float(params.get("min", 1.0))
        ok = effective is not None and effective >= limit
        return {"level": "pass" if ok else rule["_severity"], "measured": {"linespread": values, "baselineskip": baselines},
                "expected": {"min": limit},
                "detail": f"\\linespread={values or '未设置'}" + (f"，\\baselineskip={baselines}" if baselines else "")}

    if check == "fontsize_min":
        text = src.doc_clean
        sizes = [int(v) for v in re.findall(r"\\fontsize\{(\d+)", text)] + \
                [int(v) for v in re.findall(r"z\.font\.size\s*=\s*Pt\((\d+)", "")]
        docclass = re.findall(r"\\documentclass\[([^\]]*)\]", text)
        odd = [v for v in sizes if v < int(params.get("min_pt", 10))]
        ok = not odd
        return {"level": "pass" if ok else rule["_severity"], "measured": {"fontsize": sizes, "documentclass": docclass},
                "expected": {"min_pt": params.get("min_pt", 10)},
                "detail": f"显式字号 {sizes or '未设置'}；documentclass {docclass or '未设置'}"}

    if check == "page_geometry":
        text = src.doc_clean
        geometry = re.findall(r"\\geometry\{([^}]*)\}", text)
        paper = params.get("paper")
        ok = True
        detail = f"\\geometry{{{'; '.join(geometry)}}}" if geometry else "未显式设置 geometry（使用文档类默认）"
        if paper:
            ok = any(paper in g for g in geometry) if geometry else True
        return {"level": "pass" if ok else rule["_severity"], "measured": geometry,
                "expected": {"paper": paper}, "detail": detail}

    if check == "margins_min":
        text = src.doc_clean
        limit = float(params.get("min_cm", 2.0))
        found: dict[str, float] = {}
        for key in ("top", "bottom", "left", "right"):
            match = re.search(rf"{key}\s*=\s*([0-9.]+)\s*(cm|mm|in)", text)
            if match:
                value = float(match.group(1))
                found[key] = value if match.group(2) == "cm" else (value / 10 if match.group(2) == "mm" else value * 2.54)
        bad = {k: v for k, v in found.items() if v < limit}
        return {"level": "pass" if not bad else rule["_severity"], "measured": found,
                "expected": {"min_cm": limit}, "detail": f"页边距 {found or '未显式设置'}" + (f"；小于下限：{bad}" if bad else "")}

    if check == "bibliography_placeholders":
        text = src.doc_clean
        hits = re.findall(r"待填|TODO|XXXX|（待|\(待", text)
        return {"level": "pass" if not hits else rule["_severity"], "measured": len(hits),
                "expected": "无占位符", "detail": f"发现 {len(hits)} 处占位符" if hits else "无占位符"}

    if check == "math_in_abstract":
        text = src.doc_clean
        start = text.find("\\begin{abstract}")
        end = text.find("\\end{abstract}")
        if start < 0 or end < 0:
            return {"level": "info", "measured": None, "expected": "摘要环境内无公式",
                    "detail": "未找到 abstract 环境，跳过"}
        abstract = text[start:end]
        formulas = len(re.findall(r"\\begin\{equation\}|\\\[|\$\$", abstract))
        allow = bool(params.get("allow", False))
        ok = formulas == 0 or allow
        return {"level": "pass" if ok else rule["_severity"], "measured": formulas,
                "expected": "摘要内不出现独立公式", "detail": f"摘要内公式环境 {formulas} 处"}

    # ---------------- 素材 ----------------
    if check in {"asset_format", "asset_naming", "asset_min_dpi", "no_asset_duplicates"}:
        files = src.assets()
        if check == "asset_format":
            allowed = {e.lower().lstrip(".") for e in params.get("allowed", ["pdf", "png", "jpg", "jpeg", "svg"])}
            bad = [str(p.relative_to(src.root)) for p in files if p.suffix.lower().lstrip(".") not in allowed]
            return {"level": "pass" if not bad else rule["_severity"], "measured": bad[:20],
                    "expected": sorted(allowed), "detail": "格式全部合规" if not bad else f"不合规 {len(bad)} 个：{bad[:5]}"}
        if check == "asset_naming":
            pattern = params.get("pattern", r"^[A-Za-z0-9._-]+$")
            bad = [p.name for p in files if not re.fullmatch(pattern, p.stem)]
            return {"level": "pass" if not bad else rule["_severity"], "measured": bad[:20],
                    "expected": pattern, "detail": "命名合规" if not bad else f"命名不合规 {len(bad)} 个：{bad[:5]}"}
        if check == "no_asset_duplicates":
            seen: dict[str, list[str]] = {}
            for p in files:
                key = f"{p.stem.lower()}{p.suffix.lower()}"
                seen.setdefault(key, []).append(str(p.relative_to(src.root)))
            dupes = {k: v for k, v in seen.items() if len(v) > 1}
            return {"level": "pass" if not dupes else rule["_severity"], "measured": list(dupes)[:10],
                    "expected": "同名同扩展名唯一", "detail": "无重复" if not dupes else f"重复 {len(dupes)} 组"}
        if check == "asset_min_dpi":
            limit = float(params.get("min", 300))
            low: list[str] = []
            try:
                from PIL import Image  # type: ignore
            except ImportError:
                return {"level": "info", "measured": None, "expected": {"min_dpi": limit},
                        "detail": "需要 Pillow 才能读位图 DPI"}
            for p in files:
                if p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
                    continue
                with Image.open(p) as image:
                    dpi = image.info.get("dpi", (0, 0))
                    if dpi and min(dpi) < limit:
                        low.append(f"{p.name}({min(dpi):.0f}dpi)")
            return {"level": "pass" if not low else rule["_severity"], "measured": low[:10],
                    "expected": {"min_dpi": limit}, "detail": "位图分辨率达标" if not low else f"低于 {limit:.0f} dpi：{low[:5]}"}

    # ---------------- 交付物 ----------------
    if check == "file_size_max":
        limit = parse_length(params.get("limit"))
        named = params.get("files")
        targets = [src.root / n for n in named] if named else list(src.files)
        big = []
        for path in targets:
            if path.exists() and path.stat().st_size > limit:
                big.append({"file": path.name, "mb": round(path.stat().st_size / 1024 / 1024, 2)})
        return {"level": "pass" if not big else rule["_severity"], "measured": big,
                "expected": {"max_bytes": limit}, "detail": "大小合规" if not big else f"超限：{big}"}

    if check == "office_metadata_no_identity":
        words = params.get("words", ["学校", "大学", "学院", "赛区", "企业用户", "指导教师"])
        hits: dict[str, dict[str, str]] = {}
        inspected = 0
        for path in src.files:
            if path.suffix.lower() not in {".docx", ".xlsx", ".pptx"}:
                continue
            inspected += 1
            meta = read_office_metadata(path)
            if not meta:
                continue
            suspicious = {k: v for k, v in meta.items()
                          if k in {"creator", "lastmodifiedby", "author", "company", "manager"}
                          and any(w in v for w in words)}
            if suspicious:
                hits[path.name] = suspicious
        if inspected == 0:
            return {"level": "skipped", "measured": None, "expected": "OOXML 属性无身份字段",
                    "detail": "未提供 docx/xlsx/pptx 文件（用 --files 传入交付文件）"}
        return {"level": "pass" if not hits else rule["_severity"], "measured": hits,
                "expected": "OOXML 属性无身份字段",
                "detail": (f"已检查 {inspected} 个文档，属性干净" if not hits
                           else f"命中：{hits}")}

    if check == "file_naming":
        pattern = params.get("pattern", r"^[A-Za-z0-9._-]+$")
        bad = [p.name for p in src.files if not re.fullmatch(pattern, p.name)]
        return {"level": "pass" if not bad else rule["_severity"], "measured": bad[:20],
                "expected": pattern, "detail": "命名合规" if not bad else f"命名不合规：{bad[:5]}"}

    # ---------------- 交付物（与领域无关） ----------------
    if check == "required_files_present":
        return judge_required_files(rule, src, params)

    if check == "placeholder_text":
        words = params.get("words", ["待填", "待补", "TODO", "XXXX"])
        haystack = collect_deliverable_text(src, use_pdf=bool(src.pdf_path))
        hits = [w for w in words if w.lower() in haystack.lower()]
        return {"level": "pass" if not hits else rule["_severity"], "measured": hits,
                "expected": f"不出现 {words}",
                "detail": "未发现占位符" if not hits else f"命中占位符：{hits}"}

    if check == "max_paragraph_chars":
        return judge_paragraph_length(rule, src, params)

    if check in {"required_text_pattern", "version_string_present"}:
        pattern = params.get("pattern", r"[Vv]?\d+\.\d+")
        label = params.get("label", "必需文本模式")
        haystack = collect_deliverable_text(src, use_pdf=bool(src.pdf_path))
        found = re.search(pattern, haystack)
        return {"level": "pass" if found else rule["_severity"],
                "measured": found.group(0) if found else None,
                "expected": {"pattern": pattern, "label": label},
                "detail": (f"命中“{label}”：{found.group(0)}" if found
                           else f"未找到{label}（pattern={pattern}）")}

    # ---------------- 数据交付 ----------------
    if check in {"dataset_columns_present", "dataset_row_count", "dataset_no_sensitive_columns"}:
        return judge_dataset(rule, src, params, check)

    if check in {"manifest_matches_archive", "archive_size_max", "bundle_no_forbidden_files"}:
        if src.archive is None or not src.archive.exists():
            return {"level": "skipped", "measured": None, "expected": None,
                    "detail": "未提供压缩包，跳过"}
        import zipfile
        with zipfile.ZipFile(src.archive) as archive:
            names = [n.replace("\\", "/") for n in archive.namelist()]
        if check == "manifest_matches_archive":
            manifest = [m for m in (params.get("manifest") or [])]
            origin = "规格显式提供"
            if not manifest:
                # Auto-recover the appendix list instead of giving up: an empty
                # manifest otherwise makes the most dangerous rule unverifiable.
                manifest, note = extract_manifest(
                    src.root, src.doc, src.pdf_path,
                    tuple(params.get("extensions", [".xlsx", ".py", ".pdf", ".docx", ".csv", ".m", ".ipynb"])))
                if not manifest:
                    return {"level": "skipped", "measured": None, "expected": None,
                            "detail": f"规格未提供 manifest，且附录自动识别失败（{note}）"}
                origin = note
            missing = [m for m in manifest if not any(matches_entry(n, m) for n in names)]
            extra = [n for n in names if not any(matches_entry(n, m) for m in manifest)]
            ok = not missing and not extra
            detail = ("与清单逐条一致" if ok else f"缺 {missing}；多 {extra}") + f"（清单 {origin}）"
            return {"level": "pass" if ok else rule["_severity"],
                    "measured": {"missing": missing, "extra": extra, "manifest": manifest},
                    "expected": len(manifest), "detail": detail}
        if check == "archive_size_max":
            limit = parse_length(params.get("limit"))
            size = src.archive.stat().st_size
            ok = size <= limit
            return {"level": "pass" if ok else rule["_severity"], "measured": size,
                    "expected": {"max_bytes": limit}, "detail": f"{size / 1024 / 1024:.2f} MB"}
        words = params.get("forbidden", ["承诺书", "编号专用页"])
        hits = [n for n in names if any(w in n for w in words)]
        return {"level": "pass" if not hits else rule["_severity"], "measured": hits,
                "expected": f"不含 {words}", "detail": "未含禁用文件" if not hits else f"命中：{hits}"}

    return {"level": "skipped", "measured": None, "expected": None, "detail": f"暂未实现的 check：{check}"}


def matches_entry(archive_name: str, manifest_entry: str) -> bool:
    """Compare an archive path with a manifest entry, ignoring spacing differences.

    Typeset lists often carry a space inside a CJK filename ("AI 工具使用详情.pdf")
    while the archive stores it without ("AI工具使用详情.pdf"), and a greedy match can
    still carry a prose prefix ("工具使用详情.pdf"), so a suffix test is used after
    normalising whitespace.
    """
    left = re.sub(r"\s+", "", archive_name.replace("\\", "/").lower())
    right = re.sub(r"\s+", "", manifest_entry.replace("\\", "/").strip().lower())
    if left.endswith(right) or right.endswith(left):
        return True
    # Try trimming a leading CJK run from the archive name so "工具使用详情.pdf"
    # still matches "AI工具使用详情.pdf".
    trimmed = re.sub(r"^[\u4e00-\u9fa5]+", "", left)
    return trimmed != left and (trimmed.endswith(right) or right.endswith(trimmed))


def expand_latex_sources(doc: Path, limit: int = 40) -> list[Path]:
    """Resolve ``\\input``/``\\include`` recursively so manifest tables in section
    files are read (the root document usually contains no filenames itself)."""
    seen: set[Path] = set()
    order: list[Path] = []
    queue = [doc]
    while queue and len(order) < limit:
        current = queue.pop(0)
        if current in seen or not current.exists():
            continue
        seen.add(current)
        order.append(current)
        try:
            text = current.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for value in re.findall(r"\\(?:input|include)\{([^}]*)\}", text):
            candidate = Path(value.strip())
            if candidate.suffix == "":
                candidate = candidate.with_suffix(".tex")
            resolved = candidate if candidate.is_absolute() else current.parent / candidate
            if resolved.exists() and resolved not in seen:
                queue.append(resolved)
    return order


def extract_manifest(root: Path, doc: Path | None, pdf: Path | None,
                     patterns: tuple[str, ...]) -> tuple[list[str], str]:
    """Recover the deliverable's file list so the archive rule can run.

    LaTeX first: follow ``\\input`` chains and collect filename-shaped tokens from
    ``\\texttt{}`` entries, which is the curated list. PDF appendix pages are the
    fallback, with code-listing pages skipped. Returns the candidates plus a note
    describing their origin, so the report never implies a curated list when the
    list was auto-detected.
    """
    found: list[str] = []
    seen: set[str] = set()
    votes: dict[str, int] = {}
    allow = tuple(patterns)
    # PDF text uses typographic hyphens (U+2010/2011/2013) where the source has "-".
    hyphen_map = {0x2010: "-", 0x2011: "-", 0x2012: "-", 0x2013: "-", 0x2014: "-"}
    extensions = "|".join(p.lstrip(".") for p in allow)
    token_re = re.compile(r"[A-Za-z0-9_.\-]+\.(?:%s)" % extensions, re.I)
    # LaTeX escapes underscores inside \texttt (q1\_final\_two\_stage.py); without
    # unescaping, the token regex stops at the backslash and yields "_stage.py".
    latex_escape_re = re.compile(r"\\([_&%#{}])")

    def remember(name: str) -> None:
        clean = name.translate(hyphen_map).strip().strip("`'\",.;：:")
        if clean == "":
            return
        if not clean.lower().endswith(allow):
            return
        # Prose contamination ("结构同result4-2.xlsx") is tolerated here and resolved at
        # comparison time: matches_entry() accepts a suffix relationship, so such a
        # candidate still matches its archive entry, while a genuinely mixed name
        # ("AI 工具使用详情.pdf") is preserved.
        votes[clean] = votes.get(clean, 0) + 1
        if clean in seen:
            return
        seen.add(clean)
        found.append(clean)

    def harvest(text: str, latex: bool = False) -> None:
        """Pull filename-shaped tokens out of prose, not whole sentences."""
        prepared = latex_escape_re.sub(r"\1", text) if latex else text
        for match in token_re.finditer(prepared.translate(hyphen_map)):
            remember(match.group(0))
        # CJK filenames legitimately contain a space ("AI 工具使用详情.pdf"), which the
        # ASCII token regex above cannot span. Matching is space-insensitive later,
        # so a spaced candidate still matches the archive's unspaced entry.
        if re.search(r"[\u4e00-\u9fa5]", prepared):
            for match in re.finditer(r"[\u4e00-\u9fa5][\u4e00-\u9fa5A-Za-z0-9 _.\-]*\.(?:%s)"
                                     % extensions, prepared):
                remember(re.sub(r"\s+", "", match.group(0)))

    if doc is not None and doc.exists():
        for source in expand_latex_sources(doc):
            text = source.read_text(encoding="utf-8", errors="ignore")
            # Skip the source-code appendix: its identifiers look like filenames.
            if re.search(r"\\lstinputlisting|\\begin\{lstlisting\}", text) and "文件清单" not in text:
                continue
            for value in re.findall(r"\\texttt\{([^}]*)\}", text):
                harvest(value, latex=True)
            # A manifest table may also name files without \texttt (plain prose).
            if "文件清单" in text:
                harvest(text, latex=True)
        if found:
            # No frequency filter here: each curated entry appears exactly once in
            # a manifest table, so repetition would be the wrong signal.
            return found, (f"自动识别 {len(found)} 项（取自 LaTeX 附录的文件清单表）"
                           "，建议人工确认后写回规格")

    if not found and pdf is not None and pdf.exists():
        try:
            import pymupdf  # type: ignore
        except ImportError:
            return [], "需要 pymupdf 才能从 PDF 附录提取清单"
        try:
            document = pymupdf.open(pdf)
        except Exception as error:  # noqa: BLE001 - unreadable PDF degrades to skipped
            return [], f"PDF 无法读取：{type(error).__name__}"
        try:
            pages = [page.get_text() for page in document]
        finally:
            document.close()
        start = find_appendix_page(pages, ("附录", "Appendix"))
        for text in pages[(start - 1) if start else 0:]:
            if re.search(r"def [a-z_]+\(|import (numpy|pandas|pulp)|if __name__", text):
                continue
            harvest(text)

    if not found:
        return [], "未能从附录提取到文件清单"

    # Frequency filter: a listed deliverable is mentioned repeatedly (manifest row,
    # then again in prose); stray mentions inside the source-code appendix
    # ("args.out.parent.m", "np.m") appear once. Keep the frequent ones, and fall
    # back to everything when nothing repeats.
    repeated = [name for name in found if votes.get(name, 0) >= 2]
    dropped = len(found) - len(repeated)
    chosen = repeated or found
    source = ("取自 LaTeX 附录的 \\texttt 条目"
              if doc is not None and doc.exists() else "取自 PDF 附录页")
    note = f"自动识别 {len(chosen)} 项（{source}）"
    if repeated:
        note += f"，已按出现频次过滤掉 {dropped} 个疑似源码片段"
    note += "，建议人工确认后写回规格"
    return chosen, note


def read_office_metadata(path: Path) -> dict[str, str]:
    import zipfile
    out: dict[str, str] = {}
    try:
        with zipfile.ZipFile(path) as archive:
            if "docProps/core.xml" in archive.namelist():
                core = archive.read("docProps/core.xml").decode("utf-8", "ignore")
                for tag in ("dc:creator", "cp:lastModifiedBy", "dc:title", "dc:subject"):
                    found = re.search(rf"<{tag}>(.*?)</{tag}>", core, re.S)
                    if found and found.group(1).strip():
                        out[tag.split(":")[-1].lower()] = found.group(1).strip()
            if "docProps/app.xml" in archive.namelist():
                app = archive.read("docProps/app.xml").decode("utf-8", "ignore")
                for tag in ("Company", "Manager"):
                    found = re.search(rf"<{tag}>(.*?)</{tag}>", app, re.S)
                    if found and found.group(1).strip():
                        out[tag.lower()] = found.group(1).strip()
    except (zipfile.BadZipFile, OSError):
        return {}
    return out


# --------------------------------------------------------------------------
# 与领域无关的交付物判定器
# --------------------------------------------------------------------------
# Suffixes treated as readable text when scanning delivered files. Run logs belong
# here: a software hand-over is judged on them, and an earlier version omitted
# ".log", which made the error-marker rule pass on a log full of Tracebacks.
TEXT_SUFFIXES = {
    ".md", ".txt", ".tex", ".rst", ".log", ".out", ".err", ".json", ".yaml", ".yml",
    ".csv", ".tsv", ".ini", ".cfg", ".conf", ".toml", ".sql", ".py", ".js", ".ts",
    ".java", ".c", ".cpp", ".h", ".sh", ".ps1", ".bat", ".r", ".m",
}


def collect_deliverable_text(src: Sources, use_pdf: bool = False) -> str:
    """Gather searchable text from every supplied source.

    Domain-neutral rules must work whether the deliverable is LaTeX, Markdown, a
    PDF or a set of Office files, so this concatenates whatever is available
    instead of assuming one format.
    """
    chunks: list[str] = []
    if src.doc_text:
        chunks.append(src.doc_text)
    if use_pdf and src.pdf_path is not None and src.pdf_path.exists():
        try:
            chunks.append("\n".join(src.pages()))
        except Exception:  # noqa: BLE001 - a PDF-less run must still work
            pass
    for path in src.files:
        suffix = path.suffix.lower()
        try:
            if suffix in TEXT_SUFFIXES:
                chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
            elif suffix == ".docx":
                import docx  # type: ignore
                document = docx.Document(str(path))
                chunks.append("\n".join(p.text for p in document.paragraphs))
                chunks.append("\n".join(c.text for t in document.tables for r in t.rows for c in r.cells))
        except Exception:  # noqa: BLE001 - an unreadable file must not abort the rule
            continue
    return "\n".join(chunks)


def judge_required_files(rule: dict, src: Sources, params: dict) -> dict:
    """Check that the deliverable ships the files the requirements demand."""
    required = [str(item) for item in (params.get("required") or [])]
    if not required:
        return {"level": "skipped", "measured": None, "expected": "required 列表为空",
                "detail": "规则未列出必须提交的文件（params.required），无法核对"}
    case_insensitive = bool(params.get("case_insensitive"))
    substring = bool(params.get("substring"))
    targets: list[str] = []
    for path in src.files:
        if path.is_dir():
            targets.extend(entry.name for entry in path.rglob("*") if entry.is_file())
        else:
            targets.append(path.name)
    pool = [t.lower() for t in targets] if case_insensitive else list(targets)

    missing: list[str] = []
    for item in required:
        needle = item.lower() if case_insensitive else item
        hit = (any(needle in candidate for candidate in pool) if substring
               else any(candidate == needle or candidate.endswith(needle) for candidate in pool))
        if not hit:
            missing.append(item)
    return {
        "level": "pass" if not missing else rule["_severity"],
        "measured": {"required": required, "missing": missing, "inspected": len(targets)},
        "expected": f"齐备：{required}",
        "detail": ("必需文件齐备" if not missing
                   else f"缺少 {len(missing)} 项：{missing}（已检查 {len(targets)} 个文件）"),
    }


def judge_paragraph_length(rule: dict, src: Sources, params: dict) -> dict:
    """Flag over-long paragraphs using Word XML, which preserves paragraph breaks.

    PDF text extraction loses paragraph boundaries, so this rule reads OOXML and
    reports skipped — rather than guessing — when no .docx is supplied.
    """
    limit = int(params.get("limit", 500))
    docs = [p for p in src.files if p.suffix.lower() == ".docx"]
    if not docs:
        return {"level": "skipped", "measured": None, "expected": {"limit": limit},
                "detail": "该规则按段落判定，需要传入 .docx 文件（PDF 无段落边界）"}
    offenders: list[dict] = []
    counted = 0
    for path in docs:
        try:
            import docx  # type: ignore
            document = docx.Document(str(path))
        except Exception as error:  # noqa: BLE001 - unreadable file
            return {"level": "skipped", "measured": None, "expected": {"limit": limit},
                    "detail": f"无法读取 {path.name}：{type(error).__name__}"}
        for index, paragraph in enumerate(document.paragraphs, 1):
            text = paragraph.text.strip()
            if text == "":
                continue
            counted += 1
            if len(text) > limit:
                offenders.append({"file": path.name, "paragraph": index, "chars": len(text),
                                  "preview": text[:40]})
    return {
        "level": "pass" if not offenders else rule["_severity"],
        "measured": {"paragraphs": counted, "over_limit": len(offenders), "samples": offenders[:5]},
        "expected": {"limit": limit},
        "detail": (f"{counted} 段均在 {limit} 字以内" if not offenders
                   else f"{len(offenders)} 段超过 {limit} 字（最长 {max(o['chars'] for o in offenders)} 字）"),
    }


def read_table_frame(path: Path) -> tuple[list[str], int]:
    """Return (column names, row count) for a csv/xlsx data deliverable."""
    if path.suffix.lower() == ".csv":
        import csv
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
            reader = csv.reader(handle)
            try:
                header = next(reader)
            except StopIteration:
                return [], 0
            rows = sum(1 for _ in reader)
        return [str(h).strip() for h in header], rows
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        import openpyxl  # type: ignore
        workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
        try:
            sheet = workbook[workbook.sheetnames[0]]
            header: list[str] = []
            rows = 0
            for index, row in enumerate(sheet.iter_rows(values_only=True)):
                if index == 0:
                    header = [str(cell).strip() for cell in row if cell is not None]
                    continue
                if any(cell is not None for cell in row):
                    rows += 1
            return header, rows
        finally:
            workbook.close()
    return [], 0


def judge_dataset(rule: dict, src: Sources, params: dict, check: str) -> dict:
    """Domain-neutral dataset checks over csv/xlsx deliverables."""
    files = [Path(item) for item in (params.get("files") or []) if item]
    if not files:
        files = [p for p in src.files if p.suffix.lower() in {".csv", ".xlsx", ".xlsm"}]
    if not files:
        return {"level": "skipped", "measured": None, "expected": None,
                "detail": "未提供 csv/xlsx 数据文件（可用 params.files 指定）"}

    if check == "dataset_columns_present":
        required = [str(c) for c in (params.get("required") or [])]
        if not required:
            return {"level": "skipped", "measured": None, "expected": None,
                    "detail": "规则未列出必需字段（params.required）"}
        case_insensitive = bool(params.get("case_insensitive", True))
        missing: dict[str, list[str]] = {}
        for path in files:
            header, _ = read_table_frame(path)
            pool = [h.lower() for h in header] if case_insensitive else header
            absent = [c for c in required
                      if (c.lower() if case_insensitive else c) not in pool]
            if absent:
                missing[path.name] = absent
        return {"level": "pass" if not missing else rule["_severity"], "measured": missing,
                "expected": f"每个数据文件都含字段：{required}",
                "detail": ("字段齐备" if not missing else f"缺字段：{missing}")}

    if check == "dataset_row_count":
        minimum = int(params.get("min_rows", 1))
        counts = {path.name: read_table_frame(path)[1] for path in files}
        short = {name: count for name, count in counts.items() if count < minimum}
        return {"level": "pass" if not short else rule["_severity"], "measured": counts,
                "expected": {"min_rows": minimum},
                "detail": (f"样本量达标（最少 {min(counts.values())} 行）" if not short
                           else f"样本量不足：{short}（下限 {minimum}）")}

    words = [w.lower() for w in (params.get("words") or [])]
    allow = {w.lower() for w in (params.get("allow") or [])}
    hits: dict[str, list[str]] = {}
    for path in files:
        header, _ = read_table_frame(path)
        found = [h for h in header if any(w in h.lower() for w in words) and h.lower() not in allow]
        if found:
            hits[path.name] = found
    return {"level": "pass" if not hits else rule["_severity"], "measured": hits,
            "expected": f"字段名不含敏感词：{words}",
            "detail": ("未发现敏感字段" if not hits else f"疑似隐私/身份字段：{hits}")}


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
SEVERITY_LEVEL = {"hard": "error", "soft": "warning", "info": "info"}


def load_spec(path: Path) -> dict:
    spec = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or "rules" not in spec:
        raise SystemExit("规格文件必须包含 rules 数组")
    for rule in spec["rules"]:
        if "id" not in rule:
            raise SystemExit(f"规则缺少 id：{rule}")
        ok, why = is_valid_rule(rule)
        if not ok:
            raise SystemExit(f"规则 {rule.get('id')} 无效：{why}")
        rule["_severity"] = SEVERITY_LEVEL.get(rule.get("severity", "hard"), "error")
    return spec


def evaluate(spec: dict, src: Sources) -> dict:
    findings = []
    for rule in spec["rules"]:
        base = {
            "id": rule["id"],
            "title": rule.get("title", ""),
            "check": rule["check"],
            "severity": rule.get("severity", "hard"),
            "scope": rule.get("scope", "document"),
            "source": rule.get("source", ""),
        }
        if rule["check"] == "manual":
            findings.append({**base, "level": "info", "measured": None, "expected": None,
                             "detail": rule.get("how", "需人工确认")})
            continue
        try:
            result = judge(rule, src)
        except Exception as error:  # noqa: BLE001 - a failing check must not hide the rest
            result = {"level": "skipped", "measured": None, "expected": None,
                      "detail": f"判定异常：{type(error).__name__}: {error}"}
        findings.append({**base, **result})

    counts = {"error": 0, "warning": 0, "info": 0, "pass": 0, "skipped": 0}
    for finding in findings:
        counts[finding["level"]] = counts.get(finding["level"], 0) + 1
    verdict = "fail" if counts["error"] else ("warn" if (counts["warning"] or counts["skipped"]) else "pass")
    return {
        "ok": True,
        "spec": {"name": spec.get("name"), "version": spec.get("version"),
                 "source": spec.get("source", {}), "rules": len(spec["rules"])},
        "verdict": verdict,
        "counts": counts,
        "findings": findings,
    }


def json_default(value):
    """Serialise the few non-JSON types a finding may carry (sets, Paths)."""
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=str)
    if isinstance(value, Path):
        return str(value)
    return str(value)


def main(argv: list[str] | None = None) -> int:
    force_utf8_output()
    parser = argparse.ArgumentParser(description="交付物规格符合性校验")
    parser.add_argument("--spec", required=True, help="规格 JSON")
    parser.add_argument("--root", default=".", help="工程根目录（相对路径的基准）")
    parser.add_argument("--doc", help="LaTeX 源码（源码级规则用）")
    parser.add_argument("--pdf", help="成稿 PDF（版面规则用）")
    parser.add_argument("--files", nargs="*", default=[], help="交付文件（大小/元数据规则用）")
    parser.add_argument("--archive", help="支撑材料压缩包")
    parser.add_argument("--assets", nargs="*", default=[], help="素材目录（图表规则用）")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    spec = load_spec(Path(args.spec))
    src = Sources(
        root=root,
        doc=(root / args.doc) if args.doc else None,
        pdf=(root / args.pdf) if args.pdf else None,
        files=[Path(f) if Path(f).is_absolute() else root / f for f in args.files],
        archive=(root / args.archive) if args.archive else None,
        assets=[Path(a) if Path(a).is_absolute() else root / a for a in args.assets],
    )
    report = evaluate(spec, src)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=json_default))
    return 1 if report["counts"]["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
