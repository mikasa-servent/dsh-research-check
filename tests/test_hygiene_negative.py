# -*- coding: utf-8 -*-
"""负例回归：往一份 OOXML 文件里写入身份元数据，验证 check_hygiene.py 必须判 fail。

夹具是**现场生成的**，不依赖任何本机文件——早期版本从真实交付目录复制一份 xlsx，
在 CI（Linux runner）上直接 FileNotFoundError，把 Python job 挂掉了。自造夹具的另一个
好处是：测试只依赖被测代码，不依赖作者的目录布局。

用法：python tests/test_hygiene_negative.py
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
CHECKER = PLUGIN / "python" / "check_hygiene.py"

# 最小可用的 OOXML 包：一份 [Content_Types].xml + docProps/core.xml + docProps/app.xml。
# check_hygiene 只读属性部件，因此不需要完整的工作簿结构。
CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Override PartName="/docProps/core.xml" ContentType="application/vnd.'
    'openxmlformats-package.core-properties+xml"/>'
    '<Override PartName="/docProps/app.xml" ContentType="application/vnd.'
    'openxmlformats-officedocument.extended-properties+xml"/>'
    "</Types>"
)

CORE_TEMPLATE = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<cp:coreProperties '
    'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/">'
    "<dc:creator>{creator}</dc:creator>"
    "<cp:lastModifiedBy>{last_modified_by}</cp:lastModifiedBy>"
    "</cp:coreProperties>"
)

APP_TEMPLATE = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
    "<Company>{company}</Company>"
    "</Properties>"
)


def make_ooxml(path: Path, creator: str = "", last_modified_by: str = "", company: str = "") -> Path:
    """Write a minimal OOXML package carrying the requested metadata."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("docProps/core.xml",
                         CORE_TEMPLATE.format(creator=creator, last_modified_by=last_modified_by))
        archive.writestr("docProps/app.xml", APP_TEMPLATE.format(company=company))
    return path


def run_checker(target: Path) -> dict:
    result = subprocess.run(
        [sys.executable, str(CHECKER), "--files", str(target)],
        capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
    )
    if not result.stdout.strip():
        raise SystemExit("check_hygiene 未输出 JSON：%s" % result.stderr[-400:])
    return json.loads(result.stdout)


def check(label: str, condition: bool) -> int:
    print("  %s %s" % ("ok  " if condition else "FAIL", label))
    return 0 if condition else 1


def main() -> int:
    failures = 0
    with tempfile.TemporaryDirectory(prefix="hygiene-negative-") as tmp:
        root = Path(tmp)

        # 1) 负例：creator 与 lastModifiedBy 都含身份词 → 必须 fail
        dirty = make_ooxml(root / "dirty.xlsx", creator="张三", last_modified_by="某某大学数模队")
        report = run_checker(dirty)
        print("负例判定：%s %s" % (report["verdict"], report["counts"]))
        failures += check("含身份元数据判 fail", report["verdict"] == "fail")
        failures += check("报出具体命中的字段",
                          any("身份" in f.get("message", "") for f in report["findings"]))
        failures += check("给出修复建议",
                          any(f.get("fix") for f in report["findings"]))

        # 2) 负例：仅 Company 含单位名 → 同样必须 fail（属性来源不同，覆盖 app.xml 分支）
        company = make_ooxml(root / "company.docx", company="某某大学")
        company_report = run_checker(company)
        failures += check("Company 含单位名判 fail", company_report["verdict"] == "fail")

        # 3) 正例：同样的结构但属性干净 → 必须 pass（否则规则会误报）
        clean = make_ooxml(root / "clean.xlsx")
        clean_report = run_checker(clean)
        print("正例判定：%s %s" % (clean_report["verdict"], clean_report["counts"]))
        failures += check("干净属性判 pass", clean_report["verdict"] == "pass")

    print("\n%s" % ("全部通过" if failures == 0 else "%d 项失败" % failures))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
