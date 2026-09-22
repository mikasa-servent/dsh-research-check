# -*- coding: utf-8 -*-
"""控制台输出编码的加固。

为什么需要它：这些脚本会把**带中文的 JSON** 打到 stdout，供宿主（DSH 插件、MCP 服务器）
或测试按 UTF-8 读取。中文 Windows 的 cmd / PowerShell 默认代码页是 GBK（936），
此时 Python 用 GBK 编码输出，读取方按 UTF-8 解码就会抛
``UnicodeDecodeError: 'utf-8' codec can't decode byte 0xc0``，
表现为"工具在 Linux/CI 上正常、在用户机器上崩溃"。

这个 bug 真实发生过一次：CI（Linux，默认 UTF-8）全绿，但用户在 cmd 里跑
``npm publish`` 时 prepublishOnly 崩掉。修法是在源头强制 UTF-8，而不是要求调用方
设好 ``PYTHONIOENCODING``——插件会以宿主自己的方式拉起这些脚本，宿主未必设过。

用法（放在每个 checker 的 import 之后、main 之前）：

    from encoding_guard import force_utf8_output
    force_utf8_output()

函数是幂等的，重复调用无副作用；在已经使用 UTF-8 的平台上不做任何事。
"""
from __future__ import annotations

import sys

#: 目标编码：JSON 与人类可读报告都用它。
TARGET_ENCODING = "utf-8"


def force_utf8_output() -> str:
    """把 stdout/stderr 切到 UTF-8，返回实际生效的编码名。

    仅在流支持 ``reconfigure`` 时动作（Python 3.7+ 的文本流都支持）；
    被重定向到管道、文件或 StringIO 时静默跳过，绝不因加固本身抛异常。
    """
    current = (getattr(sys.stdout, "encoding", None) or "").lower()
    if current.replace("_", "-") in {"utf-8", "utf8"}:
        return current

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            # errors="replace" 保证即使有无法编码的字符也不会让整个报告失败：
            # 宁可个别字符降级，也不能让一次合规校验因为一个字符而崩掉。
            reconfigure(encoding=TARGET_ENCODING, errors="replace")
        except (ValueError, OSError):
            # 流已被关闭或包装（例如某些测试夹具），跳过加固即可。
            continue
    return (getattr(sys.stdout, "encoding", None) or "").lower()
