# -*- coding: utf-8 -*-
"""验证教程（TUTORIAL）里的每条命令与预期输出是否真实可复现。

做法：造一个最小的示例项目（要求文件 + 源码 + PDF + 数据 + 压缩包），
按教程的顺序执行每个命令，把真实输出与教程里写的内容比对。
任何不一致都报出来——教程写错比代码写错更坑人，因为用户照着做会卡住。

用法：python tests/verify_tutorial.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
PY = sys.executable
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

REQUIREMENTS = """论文格式要求（示例）
第一条 论文用 A4 纸打印，上下左右各留出至少 2.5 厘米的页边距。
第二条 正文不超过 3 页；正文之后是附录，页数不限。
第三条 论文第一页为摘要专用页，摘要内容原则上不能超过一页。
第四条 正文不要目录。
第五条 图表必须在正文引用处予以标注。
第六条 电子版论文大小不超过 20 MB。
第七条 电子版论文不能有显示参赛者身份的信息。
第八条 电子版论文不要放承诺书和编号专用页。
第九条 支撑材料压缩为一个文件，大小不超过 20 MB。
第十条 支撑材料的文件列表应放入论文附录，且与压缩包内容相符。
"""

TEX = r"""
\documentclass[12pt,a4paper]{ctexart}
\usepackage[a4paper,top=2.5cm,bottom=2.5cm,left=2.5cm,right=2.5cm]{geometry}
\begin{document}
\begin{abstract}
这是一份用于验证教程的示例摘要，只有一句话。
\par\noindent 关键词：教程验证
\end{abstract}
\section{问题一}
正文引用图~\ref{fig:one} 与表~\ref{tab:one}。
\appendix
\section{附录 A\quad 支撑材料文件列表}
\begin{tabular}{ll}
1 & \texttt{result1.xlsx} \\
2 & \texttt{model.py} \\
\end{tabular}
\end{document}
"""


def make_pdf(path: Path, pages: int, body_pages: int) -> None:
    import pymupdf

    doc = pymupdf.open()
    for index in range(pages):
        page = doc.new_page()
        if index == 0:
            page.insert_text((72, 72), "ABSTRACT", fontname="china-ss", fontsize=11)
            page.insert_text((72, 96), "Keywords", fontname="china-ss", fontsize=11)
        elif index < body_pages:
            page.insert_text((72, 72), "%d. Section" % index, fontname="china-ss", fontsize=11)
        elif index == body_pages:
            page.insert_text((72, 72), "Appendix A file list", fontname="china-ss", fontsize=11)
            page.insert_text((72, 96), "1 result1.xlsx", fontname="china-ss", fontsize=11)
            page.insert_text((72, 112), "2 model.py", fontname="china-ss", fontsize=11)
        else:
            page.insert_text((72, 72), "Appendix B source", fontname="china-ss", fontsize=11)
    doc.save(str(path))
    doc.close()


def make_xlsx(path: Path, creator: str = "") -> None:
    """Minimal xlsx carrying core properties."""
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.'
        'openxmlformats-package.core-properties+xml"/></Types>'
    )
    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties '
        'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:creator>{creator}</dc:creator></cp:coreProperties>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("docProps/core.xml", core)


def build_project(root: Path) -> None:
    (root / "格式规范.txt").write_text(REQUIREMENTS, encoding="utf-8")
    (root / "论文.tex").write_text(TEX, encoding="utf-8")
    (root / "model.py").write_text("def solve(m):\n    return m\n", encoding="utf-8")
    make_xlsx(root / "数据.xlsx")
    make_pdf(root / "论文.pdf", pages=4, body_pages=2)
    with zipfile.ZipFile(root / "支撑材料.zip", "w") as archive:
        archive.write(root / "数据.xlsx", "数据.xlsx")
        archive.write(root / "model.py", "model.py")


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", env=ENV)


results: list[tuple[bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    results.append((ok, label if ok else "%s — %s" % (label, detail)))
    print("  %s %s%s" % ("ok  " if ok else "FAIL", label, "" if ok else "  ← " + detail))


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="tutorial-"))
    try:
        build_project(root)

        print("[教程 场景A 第1步] spec_build")
        build = run([PY, str(PLUGIN / "python" / "spec_build.py"),
                     "--requirements", "格式规范.txt", "--out", "specs/我的要求.json",
                     "--profile", "academic", "--name", "示例论文格式要求"], root)
        check("命令执行成功", build.returncode == 0, build.stderr[-200:])
        summary = json.loads(build.stdout)
        check("输出含 rules 计数", isinstance(summary.get("rules"), int) and summary["rules"] > 0)
        check("输出含 bySeverity", set(summary.get("bySeverity", {})) >= {"hard", "soft", "info"})
        check("输出含 checks 列表", isinstance(summary.get("checks"), list) and summary["checks"])
        check("输出含 needsReview", isinstance(summary.get("needsReview"), list))
        print("      实际: rules=%d hard=%d soft=%d" % (
            summary["rules"], summary["bySeverity"]["hard"], summary["bySeverity"]["soft"]))
        spec_path = root / "specs" / "我的要求.json"
        check("规格文件已生成", spec_path.exists())
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        check("每条规则都有 source 出处",
              all(r.get("source") for r in spec["rules"]))
        check("每条规则都有 check",
              all(r.get("check") for r in spec["rules"]))
        has_required = any(r["check"] == "required_files_present" for r in spec["rules"])
        print("      （示例要求里没有'必须提交某文件'的表述，required_files 规则是否生成: %s）" % has_required)

        print("[教程 场景A 第3步] check_spec / run_spec_check")
        check_run = run([PY, str(PLUGIN / "python" / "check_spec.py"),
                         "--spec", "specs/我的要求.json", "--root", ".",
                         "--doc", "论文.tex", "--pdf", "论文.pdf",
                         "--files", "数据.xlsx", "--archive", "支撑材料.zip"], root)
        check("检查命令执行成功", check_run.returncode in (0, 1), check_run.stderr[-200:])
        report = json.loads(check_run.stdout)
        check("报告含 verdict 与 counts", "verdict" in report and "counts" in report)
        found = {f["check"]: f["level"] for f in report["findings"]}
        check("页数规则确实生效（不是 skipped）", found.get("max_pages") in {"pass", "error"},
              str(found.get("max_pages")))
        check("压缩包清单规则生效", found.get("manifest_matches_archive") in {"pass", "error"},
              str(found.get("manifest_matches_archive")))
        check("身份元数据规则生效", found.get("office_metadata_no_identity") in {"pass", "error"},
              str(found.get("office_metadata_no_identity")))
        print("      实际判定: %s %s" % (report["verdict"], report["counts"]))

        pretty = run([PY, str(PLUGIN / "tests" / "run_spec_check.py"), "--spec", "specs/我的要求.json"], root)
        check("run_spec_check 可运行", pretty.returncode in (0, 1), pretty.stderr[-200:])
        check("输出含中文表头「判定」", "判定" in pretty.stdout)
        check("输出含 [ok  ] 或 [FAIL] 标记",
              ("[ok  ]" in pretty.stdout) or ("[FAIL]" in pretty.stdout))

        print("[教程 场景A 第5步] check_hygiene")
        # Two cases, because the checker's reach differs: a keyword-matching leak is a
        # hard error, while a bare person name only raises a warning (the keyword list
        # cannot recognise names — the tutorial says so explicitly).
        make_xlsx(root / "数据_脏.xlsx", creator="某某大学 张三")
        make_xlsx(root / "数据_半脏.xlsx", creator="张三")
        hygiene = run([PY, str(PLUGIN / "python" / "check_hygiene.py"), "--files", "数据.xlsx"], root)
        check("check_hygiene 可运行", hygiene.returncode in (0, 1), hygiene.stderr[-200:])
        clean_report = json.loads(hygiene.stdout)
        check("干净文件判 pass", clean_report["verdict"] == "pass", clean_report["verdict"])
        hygiene2 = run([PY, str(PLUGIN / "python" / "check_hygiene.py"), "--files", "数据_脏.xlsx"], root)
        dirty_report = json.loads(hygiene2.stdout)
        check("含学校名的文件判 fail", dirty_report["verdict"] == "fail", dirty_report["verdict"])
        hygiene3 = run([PY, str(PLUGIN / "python" / "check_hygiene.py"), "--files", "数据_半脏.xlsx"], root)
        half_report = json.loads(hygiene3.stdout)
        check("裸人名给出 warning 并提示人工确认",
              half_report["verdict"] == "warn"
              and any("人工确认" in f.get("message", "") for f in half_report["findings"]),
              json.dumps(half_report["counts"], ensure_ascii=False))

        print("[教程 场景C] teach → add → verify（台账流程）")
        teach = run(["node", str(PLUGIN / "lib" / "ledger-cli.js"), "teach",
                     "--ledger", "台账.json", "--paper", "论文.tex",
                     "--unit-filter", "页", "--min-abs", "1"], root)
        if teach.returncode != 0:
            # 示例文本里可能没有带单位的数字，那正好用来验证"如实报 0"
            check("teach 在无候选时也不崩", teach.returncode == 0, teach.stderr[-300:])
        else:
            teach_out = json.loads(teach.stdout)
            check("teach 输出含 candidates/added/note",
                  {"candidates", "added", "note"} <= set(teach_out))
            print("      实际: candidates=%s added=%s" % (teach_out["candidates"], teach_out["added"]))

        add = run(["node", str(PLUGIN / "lib" / "ledger-cli.js"), "add",
                   "--ledger", "台账.json", "--key", "demo.value",
                   "--value", "1521.6", "--unit", "万元",
                   "--source", "model.py", "--anchor", "全年费用"], root)
        check("add 成功", json.loads(add.stdout).get("ok") is True, add.stdout[-200:])

        # 负例：台账值不在文档里 → verify 必须报 fail（教程里承诺了这个行为）
        verify = run(["node", str(PLUGIN / "lib" / "ledger-cli.js"), "verify",
                      "--ledger", "台账.json", "--paper", "论文.pdf"], root)
        verify_out = json.loads(verify.stdout)
        check("verify 报出'台账值不在文档中'",
              verify_out.get("verdict") == "fail" and verify_out.get("missing", 0) >= 1,
              json.dumps(verify_out, ensure_ascii=False)[:200])

        print("[教程 场景B] software profile")
        (root / "验收标准.txt").write_text(
            "交付要求\n1. 交付包必须提交完整源码，并提供 README.md 与 LICENSE 文件。\n"
            "2. 交付代码不得出现 Traceback 与 ERROR 标记。\n", encoding="utf-8")
        build_sw = run([PY, str(PLUGIN / "python" / "spec_build.py"),
                        "--requirements", "验收标准.txt", "--out", "specs/验收.json",
                        "--profile", "software", "--name", "示例验收标准"], root)
        check("software profile 可生成", build_sw.returncode == 0, build_sw.stderr[-200:])
        sw = json.loads(build_sw.stdout)
        check("生成必备文件规则", "required_files_present" in sw["checks"], str(sw["checks"]))
        check("生成报错标记规则", "forbidden_text" in sw["checks"], str(sw["checks"]))

        print()
        failed = [item for ok, item in results if not ok]
        print("%d 项通过，%d 项失败" % (len(results) - len(failed), len(failed)))
        for item in failed:
            print("  FAIL %s" % item)
        return 0 if not failed else 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
