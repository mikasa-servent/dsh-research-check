# -*- coding: utf-8 -*-
"""从要求文本生成规格文件（spec）——现已支持按交付物类型分规则包。

输入：要求文本（.doc/.docx/.md/.txt，如赛会格式规范、期刊须知、验收标准、招标文件）
输出：spec JSON —— 规则逐条带出处引用，可直接喂给 check_spec.py 自查。

设计要点（改这个文件前请先读）：
  · 规则来自 rule_packs.py 的模板库，按 --profile 过滤；文本没写到的条款不会被"猜"出来。
  · 每条规则必须能判定：库里的模板都带 check 名；无法判定的写 manual 进人工清单。
  · 出处引用：把命中的原句截下来放进 source，便于答辩/回复评审时指认依据。
  · 解析不出、或文本本身含糊的地方写进 needsReview，不静默丢弃。

用法：
  python spec_build.py --requirements format2026.doc --out specs/cumcm-2026.json \
      [--name "2026 全国大学生数学建模竞赛"] [--profile academic|docs|software|dataset|tender|generic]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rule_packs import PROFILE_NAMES, templates_for  # noqa: E402
from encoding_guard import force_utf8_output

# 需要人工确认的解析缺口：文本里出现过、但无法机器判定的表述
REVIEW_HINTS = [
    ("行距", "行距要求已尝试从源码判定；若以 Word 交付，需人工核对段落行距设置。"),
    ("字号", "字号要求已尝试从源码判定；Word 交付时请人工核对样式字号。"),
    ("页边距", "页边距建议在 geometry 或页面设置中显式声明，便于自动核对。"),
    ("字体", "字体族要求（如宋体/黑体）目前不参与自动判定，需人工确认。"),
    ("颜色", "颜色要求（如不得使用彩色）需人工确认图表与文字用色。"),
    ("目录", "目录要求已按是否生成目录判定。"),
    ("命名", "文件命名规则已按字符集判定；更细的命名约定（如“学号_姓名”）需人工补充 pattern。"),
    ("字段", "字段要求需在规格 params.required 里列出字段名后才会自动核对。"),
    ("样本量", "样本量已按行数判定；有效样本的判定口径需人工确认。"),
    ("加解密", "加密/权限要求需人工确认（工具不校验加密状态）。"),
    ("法律", "法律与合规条款需人工确认（工具不提供法律意见）。"),
]


def read_requirements(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".docx":
        import docx  # type: ignore
        doc = docx.Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs) + "\n" + "\n".join(
            c.text for t in doc.tables for r in t.rows for c in r.cells)
    if suffix == ".doc":
        import os
        import win32com.client as com  # type: ignore
        app = com.Dispatch("Word.Application")
        app.Visible = False
        app.DisplayAlerts = 0
        try:
            document = app.Documents.Open(os.path.abspath(path), ReadOnly=True)
            text = document.Content.Text
            document.Close(0)
        finally:
            app.Quit()
        return text
    raise SystemExit(f"不支持的要求文本格式：{suffix}")


def citation(text: str, match: re.Match, width: int = 60) -> str:
    start = max(0, match.start() - width)
    end = min(len(text), match.end() + width)
    return re.sub(r"\s+", "", text[start:end])


def build(text: str, name: str, profile: str) -> dict:
    flat = re.sub(r"\s+", "", text)
    rules: list[dict] = []
    seen: set[str] = set()
    for template in templates_for(profile):
        match = re.search(template["pattern"], flat)
        if match is None or template["id"] in seen:
            continue
        seen.add(template["id"])
        entry = {
            "id": template["id"],
            "title": template["title"],
            "check": template["check"],
            "scope": template["scope"],
            "severity": template["severity"],
            "params": template["params"](match),
            "why": template["why"],
            "source": f"{name}：…{citation(flat, match)}…",
        }
        if template["check"] == "manual":
            entry["how"] = template.get("how", "需人工确认")
        rules.append(entry)

    needs_review = [f"{keyword}：{hint}" for keyword, hint in REVIEW_HINTS if keyword in flat]
    # 参数留空的规则必须由人补齐，否则判定会如实报 skipped —— 这里显式提示
    for rule in rules:
        params = rule.get("params") or {}
        if rule["check"] == "manifest_matches_archive" and not params.get("manifest"):
            needs_review.append(f"{rule['id']}：manifest 为空，判定时会尝试从附录自动识别；"
                                "建议人工确认后写回规格。")
        if rule["check"] in {"required_files_present", "dataset_columns_present", "dataset_row_count"} \
                and not params.get("required") and not params.get("files"):
            needs_review.append(f"{rule['id']}：需要人工填写 params（required/files/行数下限）后才能生效。")

    return {
        "name": name,
        "version": "1.0.0",
        "profile": profile,
        "source": {
            "requirements": name,
            "profile": profile,
            "generatedBy": "spec_build.py（模板匹配，非自由生成）",
            "note": "仅收录要求文本中明确出现、且可机器判定的条款；未收录部分见 needsReview。",
        },
        "rules": rules,
        "needsReview": needs_review,
    }


def main(argv: list[str] | None = None) -> int:
    force_utf8_output()
    parser = argparse.ArgumentParser(description="从要求文本生成规格文件")
    parser.add_argument("--requirements", help="要求文本（.doc/.docx/.md/.txt）")
    parser.add_argument("--out", help="输出 spec JSON")
    parser.add_argument("--name", default="", help="规格名称（默认用文件名）")
    parser.add_argument("--profile", default="academic",
                        help="交付物类型：" + " / ".join(PROFILE_NAMES))
    parser.add_argument("--list-profiles", action="store_true", help="列出可用类型与其规则数")
    args = parser.parse_args(argv)

    if args.list_profiles:
        print(json.dumps({p: len(templates_for(p)) for p in PROFILE_NAMES}, ensure_ascii=False, indent=2))
        return 0
    if not args.requirements or not args.out:
        parser.error("--requirements 与 --out 为必填（--list-profiles 除外）")
    if args.profile not in PROFILE_NAMES:
        print(json.dumps({"ok": False, "error": "UNKNOWN_PROFILE", "profile": args.profile,
                          "known": PROFILE_NAMES}, ensure_ascii=False, indent=2))
        return 2

    path = Path(args.requirements)
    if not path.exists():
        print(json.dumps({"ok": False, "error": "MISSING_REQUIREMENTS", "path": str(path)},
                         ensure_ascii=False))
        return 2
    text = read_requirements(path)
    name = args.name or path.stem
    spec = build(text, name, args.profile)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "out": str(out),
        "name": spec["name"],
        "profile": spec["profile"],
        "rules": len(spec["rules"]),
        "bySeverity": {s: sum(1 for r in spec["rules"] if r["severity"] == s) for s in ("hard", "soft", "info")},
        "checks": sorted({r["check"] for r in spec["rules"]}),
        "needsReview": spec["needsReview"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
