# -*- coding: utf-8 -*-
"""离线规格测试：不依赖任何真实论文，全部现场构造。

覆盖两件事：
  1. **正例**：一份合成论文（源码 + 生成的 PDF + 压缩包）应通过全部可判定规则；
  2. **负例**：故意超页、故意写入身份元数据，必须被判 hard error。

这样 CI 里没有真实论文也能跑，且任何"只会说通过"的退化都会被立刻发现。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

REQUIREMENTS = """
第 1 条 论文用白色 A4 纸打印，上下左右各留出至少 2.5 厘米的页边距。
第 2 条 正文从第 1 页开始，正文不超过 6 页；正文之后是附录，页数不限。
第 3 条 论文首页为摘要专用页，摘要内容原则上不能超过一页。
第 4 条 正文不加目录。
第 5 条 图表必须在正文引用处予以标注。
第 6 条 电子版论文文件大小不超过 20 MB。
第 7 条 电子版论文不能有显示参赛者身份的信息。
第 8 条 电子版论文不要放承诺书和编号专用页。
第 9 条 支撑材料压缩为一个文件，大小不超过 20 MB。
第 10 条 支撑材料的文件列表应放入论文附录，且与压缩包内容相符。
第 11 条 附录内容应包括支撑材料的文件列表与全部完整、可运行的源程序。
"""

TEX = r"""
\documentclass[12pt,a4paper]{ctexart}
\usepackage[a4paper,top=2.5cm,bottom=2.5cm,left=2.5cm,right=2.5cm]{geometry}
\linespread{1.15}
\title{合成测试论文}
\begin{document}
\begin{abstract}
本文构造一份合成论文用于离线回归测试。摘要内容只有一句话，确保不跨页。
\par\noindent 关键词：离线测试；规格校验
\end{abstract}
\section{问题一}
正文引用图~\ref{fig:one} 与表~\ref{tab:one}。
\begin{equation} Z=\sum_t c_t G_t \end{equation}
\section{问题二}
补充说明。
\appendix
\section{附录 A\quad 支撑材料文件列表}
\begin{tabular}{ll}
1 & \texttt{result1.xlsx} \\
2 & \texttt{model.py} \\
3 & \texttt{notes.pdf} \\
\end{tabular}
\section{附录 B\quad 源程序}
\begin{lstlisting}
def solve(model):
    return model
\end{lstlisting}
\end{document}
"""

SOURCE_PY = "def solve(model):\n    return model\n"

MAIN_TEX_HEADING = "\\section{问题一}"


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run a checker, forcing UTF-8 on both sides of the pipe.

    The checker writes Chinese JSON; on a GBK console (Chinese Windows cmd) it would
    encode with GBK and this side would fail to decode as UTF-8. The checkers now
    self-force UTF-8, and the environment is pinned here too so the test does not
    depend on however it was launched.
    """
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", env=env)


CJK_FONT = "china-ss"


def _write_text(page, x: float, y: float, text: str) -> None:
    """Insert text with a CJK-capable font.

    pymupdf's default Base-14 font cannot render CJK: characters come out as
    replacement dots, which silently changes what the layout rules see (a page
    starting with "·" matched the numbered-heading pattern).
    """
    page.insert_text((x, y), text, fontname=CJK_FONT, fontsize=11)


def make_pdf(path: Path, pages: int, body_pages: int) -> None:
    """Write a PDF with a given body/appendix split using pymupdf."""
    import pymupdf

    doc = pymupdf.open()
    for index in range(pages):
        page = doc.new_page()
        if index == 0:
            _write_text(page, 72, 72, "ABSTRACT 摘要")
            _write_text(page, 72, 96, "Keywords 关键词: offline test")
        elif index < body_pages:
            # A numbered heading is what body pages start with; the abstract page must
            # not carry one, otherwise abstract_within_page correctly reports a span.
            _write_text(page, 72, 72, "%d. 问题%d" % (index, index))
            _write_text(page, 72, 96, "引用 图1 表1；本页为正文。")
        elif index == body_pages:
            _write_text(page, 72, 72, "附录A 支撑材料文件列表")
            _write_text(page, 72, 96, "1 result1.xlsx")
            _write_text(page, 72, 112, "2 model.py")
            _write_text(page, 72, 128, "3 notes.pdf")
        else:
            _write_text(page, 72, 72, "附录B 源程序")
    doc.save(str(path))
    doc.close()


def make_pdf_with_identity(path: Path) -> None:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "ABSTRACT")
    doc.set_metadata({"author": "某某大学 张三", "creator": "测试"})
    doc.save(str(path))
    doc.close()


def build_fixture(root: Path, pages: int, body_pages: int, xlsx_creator: str = "") -> None:
    (root / "paper").mkdir(parents=True, exist_ok=True)
    (root / "paper" / "main.tex").write_text(TEX, encoding="utf-8")
    (root / "model.py").write_text(SOURCE_PY, encoding="utf-8")
    (root / "result1.xlsx").write_bytes(_minimal_xlsx(xlsx_creator))
    (root / "notes.pdf").write_bytes(_minimal_pdf_bytes())
    make_pdf(root / "paper.pdf", pages, body_pages)
    with zipfile.ZipFile(root / "support.zip", "w") as archive:
        for name in ("result1.xlsx", "model.py", "notes.pdf"):
            archive.write(root / name, name)


def _minimal_xlsx(creator: str = "") -> bytes:
    """A tiny but valid xlsx (one sheet, one cell) with optional author metadata.

    Default is clean: the positive fixture must have nothing to report, and the
    negative case plants an author explicitly.
    """
    import io
    import zipfile as zf

    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:creator>{creator}</dc:creator></cp:coreProperties>"
    )
    buffer = io.BytesIO()
    with zf.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml",
                         '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr("docProps/core.xml", core)
        archive.writestr("xl/workbook.xml", '<?xml version="1.0"?><workbook/>')
    return buffer.getvalue()


def _minimal_pdf_bytes() -> bytes:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "notes")
    data = doc.tobytes()
    doc.close()
    return data


def check(label: str, condition: bool) -> bool:
    print("  %s %s" % ("ok  " if condition else "FAIL", label))
    return condition


def findings_by_check(report: dict, check_name: str) -> list[dict]:
    """Select findings by `check` rather than by rule id.

    Rule ids are versioned labels (`bundle.manifest` became `gen.archive_manifest`
    when the generic pack was introduced); asserting on them makes the test brittle
    for no benefit.
    """
    return [f for f in report["findings"] if f.get("check") == check_name]


def levels_of(report: dict, check_name: str) -> set[str]:
    return {f["level"] for f in findings_by_check(report, check_name)}


def main() -> int:
    failures = 0
    with tempfile.TemporaryDirectory(prefix="spec-offline-") as tmp:
        root = Path(tmp)
        (root / "requirements.txt").write_text(REQUIREMENTS, encoding="utf-8")
        build_fixture(root, pages=4, body_pages=2)

        build = run([PYTHON, str(PLUGIN / "python" / "spec_build.py"),
                     "--requirements", "requirements.txt", "--out", "spec.json",
                     "--name", "离线规格"], root)
        if build.returncode != 0:
            print(build.stdout, build.stderr)
            return 1
        summary = json.loads(build.stdout)
        print("规格生成：%d 条规则（hard %d / soft %d）"
              % (summary["rules"], summary["bySeverity"]["hard"], summary["bySeverity"]["soft"]))
        generated = json.loads((root / "spec.json").read_text(encoding="utf-8"))
        abstract_rule = next((r for r in generated["rules"] if r["id"] == "doc.abstract_within_page"), None)
        if abstract_rule is not None:
            print("  摘要规则参数：%s" % json.dumps(abstract_rule["params"], ensure_ascii=False))
        failures += 0 if check("从要求文本提取到规则", summary["rules"] >= 8) else 1
        failures += 0 if check("包含 manifest 一致性规则",
                               "manifest_matches_archive" in summary["checks"]) else 1

        spec_path = root / "spec.json"
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        for rule in spec["rules"]:
            if rule["id"] == "doc.body_pages":
                rule["params"]["limit"] = 6
            if rule["id"] == "doc.metadata_identity":
                rule["params"]["words"].append("某某大学")
        spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

        base = [PYTHON, str(PLUGIN / "python" / "check_spec.py"), "--spec", "spec.json",
                "--root", ".", "--doc", "paper/main.tex", "--pdf", "paper.pdf",
                "--files", "result1.xlsx", "--archive", "support.zip", "--assets", "."]

        def with_spec(spec_name: str) -> list[str]:
            """Rebuild the command with a different --spec value (index-safe)."""
            rebuilt = list(base)
            rebuilt[rebuilt.index("--spec") + 1] = spec_name
            return rebuilt

        def with_archive(archive_name: str) -> list[str]:
            rebuilt = list(base)
            rebuilt[rebuilt.index("--archive") + 1] = archive_name
            return rebuilt

        clean = run(base, root)
        report = json.loads(clean.stdout)
        print("正例判定：%s %s" % (report["verdict"], report["counts"]))
        if report["counts"]["error"]:
            # Always show what failed: a bare "无 hard 错误" assertion is unactionable.
            for finding in report["findings"]:
                if finding["level"] in {"error", "warning"}:
                    print("    [%s] %-34s %s" % (finding["level"], finding["id"], finding["detail"][:130]))
        failures += 0 if check("合成论文无 hard 错误", report["counts"]["error"] == 0) else 1
        failures += 0 if check("正文页数规则生效",
                               "pass" in levels_of(report, "max_pages")) else 1
        failures += 0 if check("压缩包清单规则生效且非跳过",
                               levels_of(report, "manifest_matches_archive") <= {"pass", "error"}
                               and levels_of(report, "manifest_matches_archive") != set()) else 1

        # Negative 1: exceed the page limit. The fixture is built so the abstract sits
        # alone on page 1 and body pages carry the numbered headings (the convention the
        # rule assumes), so a page-limit failure here can only come from the limit.
        for rule in spec["rules"]:
            if rule["id"] == "doc.body_pages":
                rule["params"]["limit"] = 1
        (root / "spec-tight.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        tight = json.loads(run(with_spec("spec-tight.json"), root).stdout)
        failures += 0 if check("超页被拦截", "error" in levels_of(tight, "max_pages")) else 1

        # Negative 2: archive missing a manifest entry.
        with zipfile.ZipFile(root / "broken.zip", "w") as archive:
            archive.write(root / "model.py", "model.py")
        broken = json.loads(run(with_archive("broken.zip"), root).stdout)
        failures += 0 if check("压缩包缺文件被拦截",
                               "error" in levels_of(broken, "manifest_matches_archive")) else 1

        # Negative 3: identity metadata planted inside the submitted xlsx. Only the
        # spreadsheet rules are loaded, so an unrelated PDF-level finding cannot mask it.
        build_fixture(root, pages=4, body_pages=2, xlsx_creator="某某大学 张三")
        with zipfile.ZipFile(root / "support.zip", "w") as archive:
            for name in ("result1.xlsx", "model.py", "notes.pdf"):
                archive.write(root / name, name)
        office_spec = {
            "name": "office-only", "version": "1.0.0",
            "source": {"requirements": "synthetic", "generatedBy": "test"},
            "rules": [rule for rule in spec["rules"]
                      if rule["check"] in {"office_metadata_no_identity", "metadata_no_identity"}],
            "needsReview": []
        }
        (root / "spec-office.json").write_text(json.dumps(office_spec, ensure_ascii=False, indent=2),
                                               encoding="utf-8")
        identity = json.loads(run(with_spec("spec-office.json"), root).stdout)
        failures += 0 if check("xlsx 身份元数据被拦截",
                               "error" in levels_of(identity, "office_metadata_no_identity")) else 1

    print("\n%s" % ("全部通过" if failures == 0 else "%d 项失败" % failures))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
