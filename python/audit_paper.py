# -*- coding: utf-8 -*-
"""投稿体检：版面硬约束 + 文档卫生（通用实现，随 dsh-research-check 分发）。

检查项：
  A. 版面：总页数、正文页数（首个附录之前）、首页是否为摘要页、空白页、
     图/表是否被正文引用、PDF 大小、文档属性是否含身份信息
  B. 卫生：xlsx/docx/pptx 元数据里的作者与单位字段（最常见的泄露源）、
     压缩包内是否含承诺书/编号页、清单与实际内容是否一致
所有阈值以参数给出，默认按“单文件 PDF、正文≤30 页、≤20MB”的常见投稿规范。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

META_KEYS = ("creator", "lastModifiedBy", "author", "company", "manager", "title", "subject")
IDENTITY_WORDS = ("学校", "大学", "学院", "校区", "赛区", "参赛队", "指导教师", "姓名",
                  "学号", "队号", "university", "school")
PROMISE_WORDS = ("承诺书", "编号专用页", "赛区评阅编号")


# --------------------------------------------------------------------------
# A. 版面
# --------------------------------------------------------------------------
def page_texts(pdf_path: Path) -> list[str]:
    import pymupdf  # type: ignore
    doc = pymupdf.open(pdf_path)
    texts = [page.get_text() for page in doc]
    doc.close()
    return texts


def pdf_metadata(pdf_path: Path) -> dict:
    import pymupdf  # type: ignore
    doc = pymupdf.open(pdf_path)
    meta = {k: v for k, v in (doc.metadata or {}).items() if v}
    doc.close()
    return meta


def find_appendix_start(pages: list[str], markers: tuple[str, ...]) -> int | None:
    """Locate the appendix start by matching a heading in the page header area.

    Two real-world shapes must both work: a plain ``附录 A`` heading and the
    LaTeX-generated ``A 附录A`` (running number, then title). Body prose often
    says “见附录” within its first lines, so matching is anchored to the page
    start instead of scanning the whole page (observed: a naive page-wide scan
    reported the body as 4 pages for an 87-page PDF).
    """
    accepted = tuple(markers) + ("附录", "Appendix", "APPENDIX")
    for index, text in enumerate(pages, start=1):
        head = re.sub(r"\s+", " ", text[:30]).strip()
        if head == "":
            continue
        # Strip a leading running number such as the "A" in "A 附录A".
        prefix = re.match(r"^[A-Za-z]\s+", head)
        tail = head[prefix.end():] if prefix is not None else head
        if any(tail.startswith(marker) for marker in accepted):
            return index
    return None


def audit_layout(pdf_path: Path, max_body_pages: int, max_mb: float,
                 appendix_markers: tuple[str, ...]) -> list[dict]:
    findings: list[dict] = []
    size_mb = pdf_path.stat().st_size / 1024 / 1024
    if size_mb > max_mb:
        findings.append({"level": "error", "check": "size",
                         "message": f"PDF 大小 {size_mb:.2f} MB 超过上限 {max_mb:g} MB"})
    pages = page_texts(pdf_path)
    total = len(pages)
    appendix = find_appendix_start(pages, appendix_markers)
    if appendix is None:
        appendix = total + 1
        findings.append({"level": "info", "check": "appendix",
                         "message": "未识别到附录起始页（可用 --appendix-marker 指定标题文字）"})
    body = appendix - 1
    if body > max_body_pages:
        findings.append({"level": "error", "check": "body-pages",
                         "message": f"正文 {body} 页超过上限 {max_body_pages} 页"})
    else:
        findings.append({"level": "info", "check": "body-pages",
                         "message": f"正文 {body} 页 / 上限 {max_body_pages} 页（总 {total} 页）"})

    first = re.sub(r"\s+", "", pages[0][:300]) if pages else ""
    if "摘要" not in first and "abstract" not in first.lower():
        findings.append({"level": "warning", "check": "abstract-first",
                         "message": "首页前 200 字内未见“摘要/Abstract”，请确认首页为摘要专用页"})
    for word in PROMISE_WORDS:
        hits = [i + 1 for i, text in enumerate(pages) if word in text]
        if hits:
            findings.append({"level": "error", "check": "forbidden-page",
                             "message": f"出现「{word}」于第 {hits[:5]} 页（电子版不得含承诺书与编号专用页）"})

    blanks = [i + 1 for i, text in enumerate(pages[:body]) if len(text.strip()) < 20]
    if blanks:
        findings.append({"level": "warning", "check": "blank-page",
                         "message": f"疑似空白页：第 {blanks[:8]} 页"})

    body_text = "\n".join(pages[:body])
    refs = set(re.findall(r"图\s*([0-9]+)", body_text)) | set(re.findall(r"表\s*([0-9]+)", body_text))
    captions = set(re.findall(r"^(图|表)\s*([0-9]+)", body_text, re.M))
    caption_ids = {num for _, num in captions}
    unreferenced = sorted(caption_ids - refs, key=lambda x: int(x))
    if unreferenced:
        findings.append({"level": "warning", "check": "figure-reference",
                         "message": f"存在未被正文引用的图表编号：{unreferenced[:10]}"})

    meta = pdf_metadata(pdf_path)
    leak = {k: v for k, v in meta.items()
            if k.lower() in {"author", "creator", "producer"} and any(w in str(v) for w in IDENTITY_WORDS)}
    if leak:
        findings.append({"level": "error", "check": "pdf-metadata",
                         "message": f"PDF 属性疑似含身份信息：{leak}"})
    else:
        findings.append({"level": "info", "check": "pdf-metadata",
                         "message": f"PDF 属性未见身份信息（{', '.join(f'{k}={v}' for k, v in meta.items()) or '空'}）"})
    return findings


# --------------------------------------------------------------------------
# B. 文档卫生
# --------------------------------------------------------------------------
def office_metadata(path: Path) -> dict:
    """Read OOXML core/app properties without third-party dependencies."""
    out: dict[str, str] = {}
    try:
        with zipfile.ZipFile(path) as archive:
            if "docProps/core.xml" in archive.namelist():
                core = archive.read("docProps/core.xml").decode("utf-8", "ignore")
                for tag in ("dc:creator", "cp:lastModifiedBy", "dc:title", "dc:subject"):
                    found = re.search(rf"<{tag}>(.*?)</{tag}>", core, re.S)
                    if found and found.group(1).strip():
                        out[tag.split(":")[-1]] = found.group(1).strip()
            if "docProps/app.xml" in archive.namelist():
                app = archive.read("docProps/app.xml").decode("utf-8", "ignore")
                for tag in ("Company", "Manager"):
                    found = re.search(rf"<{tag}>(.*?)</{tag}>", app, re.S)
                    if found and found.group(1).strip():
                        out[tag.lower()] = found.group(1).strip()
    except (zipfile.BadZipFile, OSError):
        return {}
    return out


def audit_hygiene(files: list[Path], archives: list[Path],
                  manifest: list[str]) -> list[dict]:
    findings: list[dict] = []
    for path in files:
        if path.suffix.lower() not in {".xlsx", ".xlsm", ".docx", ".pptx"}:
            continue
        meta = office_metadata(path)
        suspicious = {k: v for k, v in meta.items()
                      if k in {"creator", "lastModifiedBy", "author", "company", "manager"} and v}
        if suspicious:
            findings.append({
                "level": "error", "check": "office-metadata", "file": path.name,
                "message": f"文档属性含作者/单位字段：{suspicious}；"
                           "投稿规范通常要求所有文件不得含参赛者身份信息",
            })
        else:
            findings.append({"level": "info", "check": "office-metadata", "file": path.name,
                             "message": "文档属性无作者/单位字段"})

    for archive_path in archives:
        try:
            with zipfile.ZipFile(archive_path) as archive:
                names = [n.replace("\\", "/") for n in archive.namelist()]
        except (zipfile.BadZipFile, OSError) as error:
            findings.append({"level": "error", "check": "archive", "file": archive_path.name,
                             "message": f"无法读取压缩包：{error}"})
            continue
        size_mb = archive_path.stat().st_size / 1024 / 1024
        forbidden = [n for n in names if any(w in n for w in PROMISE_WORDS)]
        if forbidden:
            findings.append({"level": "error", "check": "archive-forbidden", "file": archive_path.name,
                             "message": f"压缩包含承诺书/编号页：{forbidden}"})
        if manifest:
            missing = [m for m in manifest if not any(n.endswith(m) for n in names)]
            extra = [n for n in names if not any(n.endswith(m) for m in manifest)]
            if missing or extra:
                findings.append({"level": "error", "check": "archive-manifest", "file": archive_path.name,
                                 "message": f"清单不一致：缺 {missing or '无'}；多 {extra or '无'}"})
            else:
                findings.append({"level": "info", "check": "archive-manifest", "file": archive_path.name,
                                 "message": f"与清单逐条一致（{len(manifest)} 项，{size_mb:.2f} MB）"})
        else:
            findings.append({"level": "info", "check": "archive", "file": archive_path.name,
                             "message": f"{len(names)} 个条目，{size_mb:.2f} MB"})
    return findings


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="投稿体检：版面硬约束 + 文档卫生")
    parser.add_argument("--paper", required=True, help="参赛论文 PDF")
    parser.add_argument("--files", nargs="*", default=[], help="随附的 docx/xlsx 等文件")
    parser.add_argument("--archives", nargs="*", default=[], help="支撑材料压缩包")
    parser.add_argument("--manifest", nargs="*", default=[], help="附录清单里的文件名（用于一致性核对）")
    parser.add_argument("--max-body-pages", type=int, default=30)
    parser.add_argument("--max-mb", type=float, default=20.0)
    parser.add_argument("--appendix-marker", nargs="*", default=["附录"],
                        help="判定附录起始页的标题文字，默认“附录”")
    args = parser.parse_args(argv)

    paper = Path(args.paper)
    if not paper.exists():
        print(json.dumps({"ok": False, "error": "MISSING_PAPER", "path": str(paper)}, ensure_ascii=False))
        return 2

    try:
        layout = audit_layout(paper, args.max_body_pages, args.max_mb, tuple(args.appendix_marker))
    except ImportError:
        print(json.dumps({"ok": False, "error": "NO_PYMUPDF",
                          "message": "版面检查需要 pymupdf：pip install pymupdf"}, ensure_ascii=False))
        return 2
    hygiene = audit_hygiene([Path(f) for f in args.files], [Path(a) for a in args.archives],
                            list(args.manifest))
    findings = layout + hygiene
    counts = {"error": 0, "warning": 0, "info": 0}
    for finding in findings:
        counts[finding["level"]] = counts.get(finding["level"], 0) + 1
    report = {
        "ok": True,
        "paper": paper.name,
        "verdict": "fail" if counts["error"] else ("warn" if counts["warning"] else "pass"),
        "counts": counts,
        "findings": findings,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
