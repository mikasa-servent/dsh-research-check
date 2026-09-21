# -*- coding: utf-8 -*-
"""负例回归：往副本里写入身份元数据，验证 check_hygiene.py 能抓到。"""
from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(r"C:\Users\asus\Desktop\数学建模")
PLUGIN = ROOT / "research-plugin"
DEMO = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "AppData/Local/Temp/research-plugin-demo.xlsx"

CORE = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<cp:coreProperties '
    'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/">'
    "<dc:creator>张三</dc:creator>"
    "<cp:lastModifiedBy>某某大学数模队</cp:lastModifiedBy>"
    "</cp:coreProperties>"
)

DEMO.parent.mkdir(parents=True, exist_ok=True)
shutil.copy(ROOT / "result1.xlsx", DEMO)
tmp = DEMO.with_suffix(".tmp")
with zipfile.ZipFile(DEMO) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
    for item in zin.infolist():
        data = zin.read(item.filename)
        if item.filename.replace("\\", "/") == "docProps/core.xml":
            data = CORE.encode("utf-8")
        zout.writestr(item, data)
shutil.move(str(tmp), str(DEMO))
print("[构造] 已写入身份元数据的负例：%s" % DEMO)

result = subprocess.run(
    [sys.executable, str(PLUGIN / "python" / "check_hygiene.py"), "--files", str(DEMO)],
    capture_output=True, text=True, encoding="utf-8",
    env={"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PATH": __import__("os").environ.get("PATH", "")},
)
print(result.stdout)
expected_fail = '"verdict": "fail"' in result.stdout
print("[结论] 负例是否被正确判为 fail：%s" % ("是 ✅" if expected_fail else "否 ❌"))
DEMO.unlink(missing_ok=True)
sys.exit(0 if expected_fail else 1)
