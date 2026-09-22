# -*- coding: utf-8 -*-
"""跨交付物演示：同一套插件与判定器，判四类完全不同的交付物。

目的不是"跑通"，而是证明泛化是真的：
  1. 每类交付物用**自己的**要求文本生成规格（不同 profile、不同规则集）；
  2. 每类都造一份**干净**交付物 → 必须 0 error；
  3. 每类都造一份**有缺陷**的交付物 → 对应规则必须判 error。

若某个 profile 的规则集是"装饰性"的（永远通过），第 3 步会失败。
"""
from __future__ import annotations

import importlib.util
import json
import re
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
CHECK = PLUGIN / "python" / "check_spec.py"
BUILD = PLUGIN / "python" / "spec_build.py"


def run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})


def load_checker():
    loader = importlib.util.spec_from_file_location("cs", CHECK)
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    return module


def write_docx(path: Path, paragraphs: list[str], creator: str = "") -> None:
    """Create a minimal .docx with given paragraphs and an optional author.

    java/python-docx always writes a core.xml; the creator is injected by rewriting
    that part. The injection is verified by the caller, because a silently failed
    plant would make the identity rule look broken when it is actually fine.
    """
    import docx
    import zipfile as zf

    document = docx.Document()
    for text in paragraphs:
        document.add_paragraph(text)
    document.save(str(path))
    if not creator:
        return
    buffer = path.with_suffix(".tmp")
    with zf.ZipFile(path) as zin, zf.ZipFile(buffer, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.replace("\\", "/") == "docProps/core.xml":
                core = data.decode("utf-8", "ignore")
                if "<dc:creator>" in core:
                    core = re.sub(r"<dc:creator>.*?</dc:creator>",
                                  f"<dc:creator>{creator}</dc:creator>", core, flags=re.S)
                else:
                    core = core.replace("</cp:coreProperties>",
                                        f"<dc:creator>{creator}</dc:creator></cp:coreProperties>")
                data = core.encode("utf-8")
            zout.writestr(item, data)
    buffer.replace(path)


def docx_creator(path: Path) -> str:
    """Read back the planted author so the fixture itself is verifiable."""
    import zipfile as zf

    with zf.ZipFile(path) as archive:
        core = archive.read("docProps/core.xml").decode("utf-8", "ignore")
    found = re.search(r"<dc:creator>(.*?)</dc:creator>", core, re.S)
    return (found.group(1) if found else "").strip()


def severities(report: dict, needle: str) -> set[str]:
    """Levels reported for rule ids containing `needle` (soft rules warn, not error)."""
    return {f["level"] for f in report["findings"] if needle in f["id"]}


def check(name: str, condition: bool, detail: str = "") -> int:
    print("  %s %s%s" % ("ok  " if condition else "FAIL", name, ("  — " + detail) if detail and not condition else ""))
    return 0 if condition else 1


def spec_for(cwd: Path, requirements: str, profile: str, name: str) -> dict:
    (cwd / "requirements.txt").write_text(requirements, encoding="utf-8")
    result = run([PYTHON, str(BUILD), "--requirements", "requirements.txt",
                  "--out", "spec.json", "--name", name, "--profile", profile], cwd)
    if result.returncode != 0:
        raise SystemExit("[%s] 规格生成失败：%s" % (profile, result.stderr[-400:]))
    return json.loads((cwd / "spec.json").read_text(encoding="utf-8"))


def run_check(cwd: Path, spec_name: str, extra: list[str]) -> dict:
    result = run([PYTHON, str(CHECK), "--spec", spec_name, "--root", ".", *extra], cwd)
    if not result.stdout.strip():
        raise SystemExit("检查未输出 JSON：%s" % result.stderr[-500:])
    return json.loads(result.stdout)


def errors_of(report: dict) -> list[str]:
    return [f["id"] for f in report["findings"] if f["level"] == "error"]


# --------------------------------------------------------------------------
# 1) software：软件交付包
# --------------------------------------------------------------------------
def case_software(root: Path) -> int:
    print("\n[1/3] software — 软件交付包（源码 + README + LICENSE + CHANGELOG）")
    failures = 0
    requirements = """交付说明
1. 交付包必须提交完整源码，并提供 README.md 与 LICENSE 文件。
2. 交付包必须提供变更记录 CHANGELOG.md。
3. 交付代码不得出现 Traceback 与 ERROR 标记，须保证全部测试通过。
4. 源码包大小不超过 20 MB。
"""
    spec = spec_for(root, requirements, "software", "软件交付验收标准")
    checks = {r["check"] for r in spec["rules"]}
    failures += check("规则集含必备文件判定", "required_files_present" in checks, str(checks))
    failures += check("规则集含报错标记判定", "forbidden_text" in checks, str(checks))

    # 干净包
    for name in ("README.md", "LICENSE", "CHANGELOG.md"):
        (root / name).write_text("# %s\n内容\n" % name, encoding="utf-8")
    (root / "main.py").write_text("def run():\n    return 0\n", encoding="utf-8")
    (root / "run.log").write_text("All tests passed\n", encoding="utf-8")
    clean = run_check(root, "spec.json", ["--files", "README.md", "LICENSE", "CHANGELOG.md",
                                          "main.py", "run.log"])
    failures += check("干净交付包无 error", not errors_of(clean), str(errors_of(clean)))

    # 缺陷包：删 README + 日志里留 Traceback
    # 日志必须含真正的报错标记：单独一行 "Traceback (most recent call last):" 只是
    # 调用栈表头，规则按设计匹配的是完整标记（表头、ERROR:、FATAL ERROR 等）。
    (root / "README.md").unlink()
    (root / "run.log").write_text(
        "Traceback (most recent call last):\n"
        '  File "main.py", line 3, in <module>\n'
        "ValueError: boom\n"
        "ERROR: 1 test failed\n",
        encoding="utf-8")
    dirty = run_check(root, "spec.json", ["--files", "LICENSE", "CHANGELOG.md", "main.py", "run.log"])
    caught = set(errors_of(dirty))
    failures += check("缺 README 被拦截", any("required" in e for e in caught), str(caught))
    failures += check("交付日志含报错标记被拦截",
                      any("marker" in e for e in caught), str(caught))
    return failures


# --------------------------------------------------------------------------
# 2) dataset：数据交付
# --------------------------------------------------------------------------
def case_dataset(root: Path) -> int:
    print("\n[2/3] dataset — 数据交付（字段齐全 + 样本量 + 隐私字段）")
    failures = 0
    requirements = """数据交付要求
1. 交付数据必须包含字段：user_id、amount、date。
2. 样本量至少 10 条记录。
3. 数据中不得包含个人信息与隐私字段。
"""
    spec = spec_for(root, requirements, "dataset", "数据交付检查表")
    checks = {r["check"] for r in spec["rules"]}
    failures += check("规则集含字段/样本量/隐私三类判定",
                      {"dataset_columns_present", "dataset_row_count",
                       "dataset_no_sensitive_columns"} <= checks, str(checks))

    # 规则参数需人工补：字段名与文件（模拟填好后的规格）
    for rule in spec["rules"]:
        if rule["check"] == "dataset_columns_present":
            rule["params"]["required"] = ["user_id", "amount", "date"]
            rule["params"]["files"] = ["data.csv"]
        if rule["check"] == "dataset_row_count":
            rule["params"]["min_rows"] = 10
            rule["params"]["files"] = ["data.csv"]
        if rule["check"] == "dataset_no_sensitive_columns":
            rule["params"]["files"] = ["data.csv"]
    (root / "spec-filled.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    # 干净数据
    rows = ["user_id,amount,date"] + ["%d,%d,2026-01-%02d" % (i, i * 10, i) for i in range(1, 13)]
    (root / "data.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    clean = run_check(root, "spec-filled.json", ["--files", "data.csv"])
    failures += check("干净数据无 error", not errors_of(clean), str(errors_of(clean)))

    # 缺陷数据：缺 date 字段、只剩 5 行、混入手机号列
    bad = ["user_id,amount,phone"] + ["%d,%d,13800000000" % (i, i * 10) for i in range(1, 6)]
    (root / "data.csv").write_text("\n".join(bad) + "\n", encoding="utf-8")
    dirty = run_check(root, "spec-filled.json", ["--files", "data.csv"])
    caught = set(errors_of(dirty))
    failures += check("缺字段被拦截", any("columns" in e for e in caught), str(caught))
    failures += check("样本量不足被拦截", any("row" in e for e in caught), str(caught))
    failures += check("隐私字段被拦截", any("identity" in e for e in caught), str(caught))
    return failures


# --------------------------------------------------------------------------
# 3) docs：技术文档
# --------------------------------------------------------------------------
def case_docs(root: Path) -> int:
    print("\n[3/3] docs — 技术文档（段落长度 + 版本号 + TODO 标记 + 身份元数据）")
    failures = 0
    requirements = """文档交付规范
1. 每段不超过 200 字，超长段落须拆分。
2. 文档必须出现版本号。
3. 不得残留 TODO 与待办标记。
4. 所有文件中不能有显示作者身份的信息。
"""
    spec = spec_for(root, requirements, "docs", "产品文档交付规范")
    checks = {r["check"] for r in spec["rules"]}
    failures += check("规则集含段落长度判定", "max_paragraph_chars" in checks, str(checks))
    failures += check("规则集含版本号判定", "version_string_present" in checks, str(checks))
    failures += check("规则集含占位符判定", "placeholder_text" in checks, str(checks))

    for rule in spec["rules"]:
        if rule["check"] == "max_paragraph_chars":
            rule["params"]["limit"] = 200
    (root / "spec-filled.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    # 干净文档
    write_docx(root / "manual.docx", ["版本 V1.2.0", "本文档说明产品的安装与使用步骤。"] * 3)
    clean = run_check(root, "spec-filled.json", ["--files", "manual.docx"])
    failures += check("干净文档无 error", not errors_of(clean), str(errors_of(clean)))

    # 缺陷文档：超长段落（soft）+ TODO（soft）+ 作者身份（hard）
    long_paragraph = "说明" * 150
    write_docx(root / "manual.docx",
               ["版本 V1.2.0", long_paragraph, "待补充：安装步骤 TODO"],
               creator="某某大学 张三")
    planted = docx_creator(root / "manual.docx")
    failures += check("夹具已种入作者身份", planted == "某某大学 张三", repr(planted))

    dirty = run_check(root, "spec-filled.json", ["--files", "manual.docx"])
    caught = set(errors_of(dirty))
    failures += check("超长段落被报出（soft → warning）",
                      any(level in {"error", "warning"} for level in severities(dirty, "paragraph")),
                      str(severities(dirty, "paragraph")))
    failures += check("TODO 占位符被报出",
                      bool(severities(dirty, "placeholder")) | bool(severities(dirty, "todo")),
                      str({f["id"]: f["level"] for f in dirty["findings"]}))
    failures += check("docx 作者身份被拦截（hard → error）",
                      any("office" in e for e in caught), str(caught))
    return failures


def main() -> int:
    failures = 0
    with tempfile.TemporaryDirectory(prefix="generality-") as tmp:
        base = Path(tmp)
        for name, case in (("software", case_software), ("dataset", case_dataset), ("docs", case_docs)):
            workdir = base / name
            workdir.mkdir()
            failures += case(workdir)
    print("\n%s" % ("全部通过：三类非论文交付物均被正确判定" if failures == 0 else "%d 项失败" % failures))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
