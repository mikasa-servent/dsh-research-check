# -*- coding: utf-8 -*-
"""规格符合性自查的运行封装（避免 PowerShell 引号/编码问题）。

用法：
  python tests/run_spec_check.py                     # 用默认规格与默认路径
  python tests/run_spec_check.py --spec X.json --pdf Y.pdf
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
CHECKER = HERE / "python" / "check_spec.py"

ICON = {"pass": "[ok  ]", "error": "[FAIL]", "warning": "[warn]", "skipped": "[skip]", "info": "[info]"}


def main() -> int:
    parser = argparse.ArgumentParser(description="运行规格符合性自查并格式化输出")
    parser.add_argument("--spec", default="submissions/cumcm-2026.json")
    parser.add_argument("--root", default=".")
    parser.add_argument("--doc", default="paper/main.tex",
                        help="LaTeX 源码；带源码时压缩包清单规则可从附录精确提取")
    parser.add_argument("--pdf", default="论文初稿.pdf")
    parser.add_argument("--files", nargs="*", default=["论文初稿.pdf", "support.zip"])
    parser.add_argument("--archive", default="support.zip")
    parser.add_argument("--json", action="store_true", help="输出原始 JSON")
    args = parser.parse_args()

    command = [sys.executable, str(CHECKER), "--spec", args.spec, "--root", args.root,
               "--doc", args.doc, "--pdf", args.pdf, "--archive", args.archive]
    if args.files:
        command += ["--files", *args.files]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    if result.returncode > 1 or not result.stdout.strip():
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        return 2
    report = json.loads(result.stdout)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["counts"]["error"] == 0 else 1

    print("规格：%s v%s（%d 条规则，出处：%s）"
          % (report["spec"]["name"], report["spec"]["version"], report["spec"]["rules"],
             (report["spec"].get("source") or {}).get("requirements", "-")))
    print("判定：%s   %s" % (report["verdict"], report["counts"]))
    print("-" * 96)
    for finding in report["findings"]:
        print("%s %-6s %-30s %s" % (ICON[finding["level"]], finding["severity"],
                                    finding["id"], finding["detail"][:88]))
    print("-" * 96)
    failed = [f for f in report["findings"] if f["level"] == "error"]
    if failed:
        print("需修正 %d 条：" % len(failed))
        for finding in failed:
            print("  · %s —— %s" % (finding["title"] or finding["id"], finding["source"][:80]))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
