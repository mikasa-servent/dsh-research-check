# -*- coding: utf-8 -*-
"""文档卫生专项检查（可独立调用）：只查 OOXML 属性与压缩包内容。

适用场景：一批提交文件（docx/xlsx/pptx + 支撑材料压缩包）在投稿前统一体检，
最常见的问题是文档属性里残留作者名、单位名或机器账号（实测踩到过
xlsx 的 lastModifiedBy 为内部账号、docx 的 lastModifiedBy 为"企业用户_####"）。

用法：
  python check_hygiene.py --files a.xlsx b.docx --archives support.zip [--manifest m1 m2 ...]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

IDENTITY_WORDS = ("学校", "大学", "学院", "校区", "赛区", "参赛队", "指导教师", "姓名",
                  "学号", "队号", "企业用户", "university", "school", "@")
PROMISE_WORDS = ("承诺书", "编号专用页", "赛区评阅编号")
META_TAGS = {
    "docProps/core.xml": ("dc:creator", "cp:lastModifiedBy", "dc:title", "dc:subject"),
    "docProps/app.xml": ("Company", "Manager"),
}


def office_metadata(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        with zipfile.ZipFile(path) as archive:
            for part, tags in META_TAGS.items():
                if part not in archive.namelist():
                    continue
                text = archive.read(part).decode("utf-8", "ignore")
                for tag in tags:
                    found = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.S)
                    if found and found.group(1).strip():
                        out[tag.split(":")[-1].lower()] = found.group(1).strip()
    except (zipfile.BadZipFile, OSError):
        return {}
    return out


def check_files(paths: list[Path]) -> list[dict]:
    findings = []
    for path in paths:
        if not path.exists():
            findings.append({"level": "error", "file": path.name, "message": "文件不存在"})
            continue
        if path.suffix.lower() not in {".xlsx", ".xlsm", ".docx", ".pptx"}:
            findings.append({"level": "info", "file": path.name, "message": "非 OOXML 文件，跳过元数据检查"})
            continue
        meta = office_metadata(path)
        leaks = {k: v for k, v in meta.items()
                 if k in {"creator", "lastmodifiedby", "author", "company", "manager"}
                 and any(word in v for word in IDENTITY_WORDS)}
        if leaks:
            findings.append({
                "level": "error", "file": path.name, "meta": meta,
                "message": f"属性含疑似身份字段：{leaks}",
                "fix": "把 creator / lastModifiedBy / Company 等清空后再提交",
            })
        elif meta:
            findings.append({"level": "info", "file": path.name, "meta": meta,
                             "message": "属性存在但未见身份词"})
        else:
            findings.append({"level": "info", "file": path.name, "message": "属性为空或无属性部件"})
    return findings


def check_archives(paths: list[Path], manifest: list[str]) -> list[dict]:
    findings = []
    for path in paths:
        if not path.exists():
            findings.append({"level": "error", "file": path.name, "message": "压缩包不存在"})
            continue
        try:
            with zipfile.ZipFile(path) as archive:
                names = [n.replace("\\", "/") for n in archive.namelist()]
        except (zipfile.BadZipFile, OSError) as error:
            findings.append({"level": "error", "file": path.name,
                             "message": f"无法读取（非 zip 或已损坏）：{error}"})
            continue
        size_mb = path.stat().st_size / 1024 / 1024
        forbidden = [n for n in names if any(word in n for word in PROMISE_WORDS)]
        if forbidden:
            findings.append({"level": "error", "file": path.name,
                             "message": f"含承诺书/编号页：{forbidden}"})
        if size_mb > 20:
            findings.append({"level": "error", "file": path.name,
                             "message": f"大小 {size_mb:.2f} MB 超过 20 MB"})
        if manifest:
            missing = [m for m in manifest if not any(n.endswith(m) for n in names)]
            extra = [n for n in names if not any(n.endswith(m) for m in manifest)]
            if missing or extra:
                findings.append({"level": "error", "file": path.name,
                                 "message": f"与清单不一致：缺 {missing or '无'}；多 {extra or '无'}"})
            else:
                findings.append({"level": "info", "file": path.name,
                                 "message": f"与清单逐条一致（{len(manifest)} 项，{size_mb:.2f} MB）"})
        else:
            findings.append({"level": "info", "file": path.name,
                             "message": f"{len(names)} 个条目，{size_mb:.2f} MB"})
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="文档卫生检查")
    parser.add_argument("--files", nargs="*", default=[])
    parser.add_argument("--archives", nargs="*", default=[])
    parser.add_argument("--manifest", nargs="*", default=[])
    args = parser.parse_args(argv)

    findings = check_files([Path(p) for p in args.files])
    findings += check_archives([Path(p) for p in args.archives], list(args.manifest))
    counts = {"error": 0, "warning": 0, "info": 0}
    for finding in findings:
        counts[finding["level"]] = counts.get(finding["level"], 0) + 1
    report = {
        "ok": True,
        "verdict": "fail" if counts["error"] else ("warn" if counts["warning"] else "pass"),
        "counts": counts,
        "findings": findings,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
