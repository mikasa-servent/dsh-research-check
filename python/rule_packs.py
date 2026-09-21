# -*- coding: utf-8 -*-
"""规则库：把要求文本映射为可判定规则，并按交付物类型分组。

设计约定（改这个文件前请先读）：
  · 每条模板必须声明 `check`，且该 check 必须存在于 check_spec.py 的 KNOWN_CHECKS；
  · `profiles` 声明这条规则适用于哪些交付物类型，build 时按 profile 过滤；
  · 无法机器判定的要求用 check="manual"，并写清 how（进入人工清单，不假装可查）；
  · 宁缺勿滥：要求文本里没有明确出现的条款不要"猜"出来。

交付物类型（profile）：
  academic  学位/竞赛/期刊论文
  docs      技术文档、说明书、用户手册、白皮书
  software  软件交付、项目验收、发版说明、软著材料
  dataset   数据交付、数据集卡、元数据与数据字典
  tender    标书、申报书、投标响应文件
  generic   与类型无关的通用交付要求（体积、命名、身份信息、清单一致性）
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------
# 通用交付要求：任何交付物都适用
# --------------------------------------------------------------------------
GENERIC: list[dict] = [
    {
        "id": "gen.file_size",
        "title": "交付文件大小上限",
        "pattern": r"(?:大小|体积|文件)[^。；;\n]{0,16}?(?:不超过|不大于|上限)\s*(\d+(?:\.\d+)?)\s*(MB|GB|M|G)\b"
                   r"|(?:不超过|不大于)\s*(\d+(?:\.\d+)?)\s*(MB|GB)",
        "profiles": ["*"],
        "check": "file_size_max",
        "scope": "per-file",
        "severity": "hard",
        "params": lambda m: _size_params(m),
        "why": "超出平台或评审系统限制会直接提交失败。",
    },
    {
        "id": "gen.no_placeholder",
        "title": "不得残留占位符",
        # 语序两种都常见：“不得残留 TODO” / “不得残留待办标记”，故用非贪婪通配。
        "pattern": r"待填|待补|placeholder|(?:不得|不能|避免|禁止)[\s\S]{0,16}?(?:TODO|待办|FIXME|占位)"
                   r"|模板[^。；;\n]{0,8}(?:未改|待)|XXXX",
        "profiles": ["*"],
        "check": "placeholder_text",
        "scope": "document",
        "severity": "soft",
        "params": lambda m: {"words": ["待填", "待补", "TODO", "XXXX", "placeholder"]},
        "why": "占位符残留是最尴尬的一类失误，评委/甲方一眼可见。",
    },
    {
        "id": "gen.identity_metadata",
        "title": "交付文件属性不得含身份信息",
        "pattern": r"不能有显示[^。；;\n]{0,10}身份|不得出现[^。；;\n]{0,20}(?:学校|姓名|赛区|公司名)"
                   r"|所有文件中不能有",
        "profiles": ["*"],
        "check": "metadata_no_identity",
        "scope": "document",
        "severity": "hard",
        "params": lambda m: {"words": ["学校", "大学", "学院", "赛区", "指导教师", "姓名", "学号", "公司"]},
        "why": "匿名评审或对外交付要求；文档属性字段是最直接的泄露源。",
    },
    {
        "id": "gen.office_identity",
        "title": "随附 Office 文档属性不得含身份信息",
        # 与 gen.identity_metadata 用同一触发条件：匿名/身份要求通常同时覆盖论文 PDF
        # 与随附的 docx/xlsx，只生成其中一条会留下漏检（这里曾真的漏过一次）。
        # 判定器在未提供 Office 文件时报 skipped，不会假装通过。
        "pattern": r"不能有显示[^。；;\n]{0,10}身份|不得出现[^。；;\n]{0,20}(?:学校|姓名|赛区|公司名)"
                   r"|所有文件中不能有|匿名|脱敏",
        "profiles": ["*"],
        "check": "office_metadata_no_identity",
        "scope": "per-file",
        "severity": "hard",
        "params": lambda m: {"words": ["学校", "大学", "学院", "赛区", "指导教师", "姓名", "学号", "公司"]},
        "why": "Word/Excel 的 creator、lastModifiedBy、Company 字段肉眼不可见，是最常见的泄露源。",
    },
    {
        "id": "gen.archive_manifest",
        "title": "归档内容与清单一致",
        "pattern": r"文件列表[^。；;\n]{0,24}附录|清单[^。；;\n]{0,16}一致|与.{0,8}内容相符|压缩包内文件",
        "profiles": ["*"],
        "check": "manifest_matches_archive",
        "scope": "bundle",
        "severity": "hard",
        "params": lambda m: {"manifest": []},
        "why": "清单与实际内容不符通常被直接判为材料造假，是风险最高的条款之一。",
    },
    {
        "id": "gen.archive_size",
        "title": "归档文件大小上限",
        "pattern": r"(?:支撑材料|压缩包|归档|附件包)[^。；;\n]{0,40}?(\d+(?:\.\d+)?)\s*(MB|GB|M|G)",
        "profiles": ["*"],
        "check": "archive_size_max",
        "scope": "bundle",
        "severity": "hard",
        "params": lambda m: {"limit": _to_bytes(m.group(1), m.group(2))},
        "why": "归档包同样受体积限制。",
    },
    {
        "id": "gen.archive_forbidden",
        "title": "归档不得含承诺书/编号页等非交付件",
        "pattern": r"承诺书[^。；;\n]{0,40}(?:不要|不得|不放)|编号专用页[^。；;\n]{0,30}(?:不要|不得|不放)",
        "profiles": ["*"],
        "check": "bundle_no_forbidden_files",
        "scope": "bundle",
        "severity": "hard",
        "params": lambda m: {"forbidden": ["承诺书", "编号专用页"]},
        "why": "这类页面由组织方另行处理，放进归档会被判违规。",
    },
    {
        "id": "gen.file_naming",
        "title": "文件命名规范",
        "pattern": r"命名[^。；;\n]{0,20}(?:规范|格式)|命名方式|文件名[^。；;\n]{0,12}(?:统一|规范)",
        "profiles": ["*"],
        "check": "file_naming",
        "scope": "per-file",
        "severity": "soft",
        "params": lambda m: {"pattern": r"^[A-Za-z0-9._\-\u4e00-\u9fa5 ()（）]+$"},
        "why": "命名混乱会拖慢评审与自动核验，也是打包脚本最容易出错的地方。",
    },
    {
        "id": "gen.required_files",
        "title": "必须提交的文件齐备",
        "pattern": r"(?:必须|应|须)[^。；;\n]{0,20}(?:提交|提供)[^。；;\n]{0,24}(?:文件|材料|文档)",
        "profiles": ["*"],
        "check": "required_files_present",
        "scope": "per-file",
        "severity": "hard",
        "params": lambda m: {"required": []},
        "why": "缺件是最高频的退回原因；把要求里点名的文件列进 params.required 即可自动核对。",
    },
]

# --------------------------------------------------------------------------
# 学术论文
# --------------------------------------------------------------------------
ACADEMIC: list[dict] = [
    {
        "id": "doc.body_pages",
        "title": "正文页数上限",
        "pattern": r"正文[^。；;\n]{0,20}(?:不超过|最多|限)\s*(\d+)\s*页",
        "profiles": ["academic"],
        "check": "max_pages",
        "scope": "body",
        "severity": "hard",
        "params": lambda m: {"limit": int(m.group(1)), "appendix_marker": ["附录", "Appendix"]},
        "why": "页数是最先被感知的硬约束，超一页即违规。",
    },
    {
        "id": "doc.total_pages",
        "title": "全文档页数上限",
        "pattern": r"(?:全文|论文|总页数|说明书)[^。；;\n]{0,14}(?:不超过|最多)\s*(\d+)\s*页",
        "profiles": ["academic", "docs", "tender"],
        "check": "max_pages",
        "scope": "document",
        "severity": "hard",
        "params": lambda m: {"limit": int(m.group(1))},
        "why": "整份文档（含附录/附件）的页数上限。",
    },
    {
        "id": "doc.abstract_first_page",
        "title": "首页必须为摘要专用页",
        "pattern": r"(?:第一页|首页)[^。；;\n]{0,30}摘要",
        "profiles": ["academic"],
        "check": "abstract_first_page",
        "scope": "document",
        "severity": "hard",
        "params": lambda m: {"keywords": ["摘要", "Abstract"]},
        "why": "电子版论文首页必须是摘要页；承诺书与编号页不得出现在电子版中。",
    },
    {
        "id": "doc.abstract_within_page",
        "title": "摘要不超过一页",
        "pattern": r"摘要[^。；;\n]{0,24}(?:不超过|不能超过|限)\s*一页|摘要[^。；;\n]{0,10}一页以内",
        "profiles": ["academic"],
        "check": "abstract_within_page",
        "scope": "document",
        "severity": "hard",
        "params": lambda m: {"keywords": ["关键词", "Keywords", "关键字"],
                             "body_heading_pattern": r"^\s*[0-9]{1,2}\s*[.、．]"},
        "why": "摘要专用页只有一页，溢出会把正文挤到下一页并改变后续页码基准。",
    },
    {
        "id": "doc.no_toc",
        "title": "正文前不加目录",
        "pattern": r"不要目录|不加目录|无需目录",
        "profiles": ["academic", "tender"],
        "check": "no_toc",
        "scope": "document",
        "severity": "soft",
        "params": lambda m: {},
        "why": "目录会挤占正文页数且在评阅时无价值。",
    },
    {
        "id": "doc.no_blank_page",
        "title": "不得出现空白页",
        "pattern": r"空白页|不得留空|不能有空白",
        "profiles": ["academic", "docs", "tender"],
        "check": "no_blank_page",
        "scope": "body",
        "severity": "soft",
        "params": lambda m: {"min_chars": 20, "appendix_marker": ["附录", "Appendix"]},
        "why": "浮动体排版容易挤出空白页，属常见低级失误。",
    },
    {
        "id": "doc.figures_referenced",
        "title": "图必须被正文引用",
        "pattern": r"图表?[^。；;\n]{0,16}(?:引用|标注|说明)|引用处予以标注",
        "profiles": ["academic", "docs", "tender"],
        "check": "all_figures_referenced",
        "scope": "body",
        "severity": "soft",
        "params": lambda m: {},
        "why": "未被引用的图表等于没有信息。",
    },
    {
        "id": "doc.tables_referenced",
        "title": "表必须被正文引用",
        "pattern": r"图表?[^。；;\n]{0,16}(?:引用|标注|说明)|引用处予以标注",
        "profiles": ["academic", "docs", "tender"],
        "check": "all_tables_referenced",
        "scope": "body",
        "severity": "soft",
        "params": lambda m: {},
        "why": "同图：表也必须在正文中被引用。",
    },
    {
        "id": "doc.pdf_size",
        "title": "PDF 文件大小上限",
        "pattern": r"大小不超过\s*(\d+)\s*MB|不超过\s*(\d+)\s*MB",
        "profiles": ["academic", "docs", "tender"],
        "check": "max_pdf_bytes",
        "scope": "document",
        "severity": "hard",
        "params": lambda m: {"limit": int(m.group(1) or m.group(2)) * 1024 * 1024},
        "why": "超出平台限制会直接上传失败。",
    },
    {
        "id": "doc.forbidden_pages",
        "title": "电子版不含承诺书与编号专用页",
        "pattern": r"承诺书[^。；;\n]{0,40}(?:不要|不得|不放)|编号专用页[^。；;\n]{0,30}(?:不要|不得|不放)",
        "profiles": ["academic", "tender"],
        "check": "forbidden_text",
        "scope": "document",
        "severity": "hard",
        "params": lambda m: {"words": ["承诺书", "编号专用页", "赛区评阅编号"]},
        "why": "这两页由组织方另行处理，放进电子版会被判违规。",
    },
    {
        "id": "doc.margins",
        "title": "页边距下限",
        "pattern": r"(?:上下左右|四边|各)[^。；;\n]{0,16}(?:至少|不小于|不少于)\s*(\d+(?:\.\d+)?)\s*(?:厘米|cm)",
        "profiles": ["academic", "docs", "tender"],
        "check": "margins_min",
        "scope": "document",
        "severity": "hard",
        "params": lambda m: {"min_cm": float(m.group(1))},
        "why": "纸质装订与裁切需要留白；未显式声明时应确认默认值是否达标。",
    },
    {
        "id": "doc.paper_a4",
        "title": "纸张规格",
        "pattern": r"白色?A4纸|A4纸打印|A4\b",
        "profiles": ["academic", "tender"],
        "check": "page_geometry",
        "scope": "document",
        "severity": "soft",
        "params": lambda m: {"paper": "a4paper"},
        "why": "A4 是版心与页数换算的前提。",
    },
    {
        "id": "src.linespread",
        "title": "行距下限",
        "pattern": r"行距[^。；;\n]{0,20}?(\d+(?:\.\d+)?)\s*倍|1\.5\s*倍行距",
        "profiles": ["academic", "docs", "tender"],
        "check": "linespread_min",
        "scope": "document",
        "severity": "soft",
        "params": lambda m: {"min": float(m.group(1)) if m.group(1) else 1.5},
        "why": "PDF 交付时行距已固化，只能从源码判定。",
    },
    {
        "id": "src.font_size",
        "title": "正文字号下限",
        "pattern": r"(?:字号|字体大小)[^。；;\n]{0,16}?(\d+(?:\.\d+)?)\s*(?:pt|磅|号)",
        "profiles": ["academic", "docs", "tender"],
        "check": "fontsize_min",
        "scope": "document",
        "severity": "soft",
        "params": lambda m: {"min_pt": int(float(m.group(1)))},
        "why": "字号过小会被判为不可读。",
    },
    {
        "id": "src.max_sections",
        "title": "章节数上限",
        "pattern": r"不超过\s*(\d+)\s*(?:个)?(?:章节|部分|章)",
        "profiles": ["academic", "docs", "tender"],
        "check": "max_sections",
        "scope": "body",
        "severity": "soft",
        "params": lambda m: {"limit": int(m.group(1))},
        "why": "章节过碎会削弱论证的连贯性。",
    },
    {
        "id": "src.abstract_no_math",
        "title": "摘要内不出现独立公式",
        "pattern": r"摘要[^。；;\n]{0,30}(?:不要公式|不得含公式|不使用公式)|禁止公式",
        "profiles": ["academic"],
        "check": "math_in_abstract",
        "scope": "document",
        "severity": "soft",
        "params": lambda m: {"allow": False},
        "why": "公式排版在摘要区容易破坏单页版式。",
    },
    {
        "id": "asset.format",
        "title": "图片格式限制",
        "pattern": r"图片[^。；;\n]{0,24}(?:格式|为)\s*((?:[A-Za-z]{3,4}[、,，/]\s*)+[A-Za-z]{3,4})",
        "profiles": ["academic", "docs", "tender"],
        "check": "asset_format",
        "scope": "per-file",
        "severity": "soft",
        "params": lambda m: {"allowed": re.findall(r"[A-Za-z]{3,4}", m.group(1))},
        "why": "格式不统一会让排版出现字体/颜色偏差。",
    },
    {
        "id": "asset.dpi",
        "title": "位图分辨率下限",
        "pattern": r"(\d{2,4})\s*dpi|分辨率[^。；;\n]{0,12}(\d{3,4})",
        "profiles": ["academic", "docs", "tender"],
        "check": "asset_min_dpi",
        "scope": "per-file",
        "severity": "soft",
        "params": lambda m: {"min": float(m.group(1) or m.group(2))},
        "why": "低分辨率截图在打印稿上会糊成一片。",
    },
    {
        "id": "deliverable.source_code",
        "title": "附录须含支撑材料清单与全部源程序",
        "pattern": r"附录内容应包括支撑材料的文件列表|全部完整、可运行的源程序",
        "profiles": ["academic"],
        "check": "manual",
        "scope": "document",
        "severity": "hard",
        "params": lambda m: {},
        "why": "机器只能核对清单一致性，无法判断代码是否完整可运行。",
        "how": "人工确认：附录列出全部支撑文件；附录含完整可运行源程序；程序运行结果与交付结果一致。",
    },
    {
        "id": "deliverable.originality",
        "title": "原创性与引用规范",
        "pattern": r"参考文献|引用他人|抄袭|原创",
        "profiles": ["academic", "tender"],
        "check": "manual",
        "scope": "document",
        "severity": "hard",
        "params": lambda m: {},
        "why": "引用是否规范需要人读，工具只能提示。",
        "how": "人工确认：所有引用他人成果均列出参考文献并在正文标注；无抄袭。",
    },
]

# --------------------------------------------------------------------------
# 技术文档 / 说明书 / 手册
# --------------------------------------------------------------------------
DOCS: list[dict] = [
    {
        "id": "docs.paragraph_limit",
        "title": "单段落字数上限（可读性）",
        # 常见写法差异很大：每段/每个段落/单段 + 不超过/最多/限 + 字数。刻意放宽。
        "pattern": r"(?:每|单|一个)?(?:个)?段(?:落)?[^。；;\n]{0,20}?(?:不超过|最多|限|控制在)\s*(\d+)\s*字"
                   r"|(?:每|单|一个)?(?:个)?段(?:落)?[^。；;\n]{0,12}?(\d+)\s*字以内",
        "profiles": ["docs", "tender"],
        "check": "max_paragraph_chars",
        "scope": "document",
        "severity": "soft",
        "params": lambda m: {"limit": int(m.group(1) or m.group(2)), "source": "office"},
        "why": "长段落是文档可读性的主要杀手，尤其是转换自 Word 的稿件。",
    },
    {
        "id": "docs.version_string",
        "title": "必须出现版本号",
        # 语序两种都常见：“必须出现版本号” / “版本号必须…” / “文档版本”——都要能命中。
        "pattern": r"(?:必须|应|需|须)[^。；;\n]{0,16}?(?:出现|包含|标注|注明|给出)[^。；;\n]{0,8}?版本"
                   r"|版本(?:号|标识)[^。；;\n]{0,16}?(?:必须|应|需|须)"
                   r"|文档版本",
        "profiles": ["docs", "software"],
        "check": "version_string_present",
        "scope": "document",
        "severity": "soft",
        "params": lambda m: {"pattern": r"[Vv]?\d+\.\d+(?:\.\d+)?", "label": "版本号"},
        "why": "无版本号的文档在多方交付中无法定位是哪一版。",
    },
    {
        "id": "docs.contact_info",
        "title": "须含联系方式（支持/责任方）",
        "pattern": r"(?:联系方式|联系电话|客服|support@|邮箱)[^。；;\n]{0,16}(?:必须|应|需|须)|须(?:给出|提供)联系方式",
        "profiles": ["docs"],
        "check": "required_text_pattern",
        "scope": "document",
        "severity": "soft",
        "params": lambda m: {"pattern": r"(\+?\d[\d\s\-]{6,}|[\w.+-]+@[\w-]+\.[\w.]+)",
                             "label": "联系方式（电话或邮箱）"},
        "why": "面向用户的文档缺联系方式，等于没有支持入口。",
    },
    {
        "id": "docs.todo_markers",
        "title": "不得残留待办标记",
        "pattern": r"(?:不得|不能|避免)[^。；;\n]{0,12}(?:TODO|待办|FIXME)|(?:删除|清理)[^。；;\n]{0,10}(?:TODO|待办)",
        "profiles": ["docs", "software"],
        "check": "forbidden_text",
        "scope": "document",
        "severity": "hard",
        "params": lambda m: {"words": ["TODO", "FIXME", "待办", "待补充", "待完善"]},
        "why": "对外文档残留待办标记会严重损害专业度。",
    },
]

# --------------------------------------------------------------------------
# 软件交付 / 项目验收 / 发版
# --------------------------------------------------------------------------
SOFTWARE: list[dict] = [
    {
        "id": "sw.required_files",
        "title": "源码包必备文件",
        "pattern": r"(?:必须|应|须)[^。；;\n]{0,20}(?:提交|提供|包含)[^。；;\n]{0,24}(?:源码|源代码|README|说明文件|许可|LICENSE)",
        "profiles": ["software"],
        "check": "required_files_present",
        "scope": "per-file",
        "severity": "hard",
        "params": lambda m: {"required": ["README.md", "LICENSE"], "case_insensitive": True},
        "why": "缺 README 或缺许可的交付包无法被验收方直接使用；required 列表按项目实际情况调整。",
    },
    {
        "id": "sw.changelog",
        "title": "必须有变更记录（CHANGELOG）",
        # 常见写法：“提供变更记录 CHANGELOG.md”“必须有变更记录”“更新日志”。
        "pattern": r"(?:变更记录|更新日志|修改记录|CHANGELOG)[^。；;\n]{0,16}?(?:必须|应|需|须|提供|提交)"
                   r"|(?:必须|应|需|须|提供|提交)[^。；;\n]{0,16}?(?:变更记录|更新日志|CHANGELOG)",
        "profiles": ["software"],
        "check": "required_files_present",
        "scope": "per-file",
        "severity": "soft",
        "params": lambda m: {"required": ["CHANGELOG.md"], "case_insensitive": True},
        "why": "验收与运维都依赖变更记录定位引入问题的版本。",
    },
    {
        "id": "sw.license_present",
        "title": "必须有许可证文件",
        "pattern": r"许可(?:证)?(?:文件)?[^。；;\n]{0,16}?(?:必须|应|需|须|提供)"
                   r"|(?:必须|应|需|须|提供)[^。；;\n]{0,12}?LICENSE|开源许可",
        "profiles": ["software"],
        "check": "required_files_present",
        "scope": "per-file",
        "severity": "hard",
        "params": lambda m: {"required": ["LICENSE"], "case_insensitive": True},
        "why": "无许可声明意味着接收方无权使用，法务上不可交付。",
    },
    {
        "id": "sw.no_error_markers",
        "title": "交付代码不得含报错标记",
        # 语序与列举方式差异大，且要求常用“；”分号分隔多条，因此用非贪婪通配而非
        # 严格相邻。命中任一表述即视为该条要求存在，随后由 forbidden_text 判定。
        "pattern": r"(?:不得|不能|避免|禁止)[\s\S]{0,60}?(?:Traceback|报错|异常|ERROR|错误标记)"
                   r"|(?:全部|所有)[\s\S]{0,12}?测试[\s\S]{0,12}?通过"
                   r"|无(?:任何)?报错",
        "profiles": ["software"],
        "check": "forbidden_text",
        "scope": "per-file",
        "severity": "hard",
        "params": lambda m: {"words": ["Traceback (most recent call last)", "ERROR:", "Exception in thread",
                                       "FATAL ERROR", "FAILED |"]},
        "why": "把带报错的运行日志当作交付证据，是最容易被验收方直接退回的问题。",
    },
    {
        "id": "sw.test_evidence",
        "title": "须提供测试或验证记录",
        "pattern": r"(?:测试|验证|验收)[^。；;\n]{0,16}(?:记录|报告|结果)[^。；;\n]{0,12}(?:必须|应|需|须)"
                   r"|须(?:提供|提交)[^。；;\n]{0,12}(?:测试|验证)记录",
        "profiles": ["software"],
        "check": "manual",
        "scope": "document",
        "severity": "hard",
        "params": lambda m: {},
        "why": "测试结论是否真实覆盖需求，必须人看，工具只能核对文件是否存在。",
        "how": "人工确认：测试/验证记录覆盖了要求中的功能点与边界条件，且结果与交付版本一致。",
    },
    {
        "id": "sw.traceability",
        "title": "需求—实现—测试三方可追溯",
        "pattern": r"可追溯|追溯矩阵|需求覆盖|对应关系",
        "profiles": ["software", "tender"],
        "check": "manual",
        "scope": "document",
        "severity": "hard",
        "params": lambda m: {},
        "why": "追溯性依赖语义判断，工具无法代替评审人逐条核对。",
        "how": "人工确认：每条需求都能指到实现位置与测试用例，无遗漏、无多余承诺。",
    },
]

# --------------------------------------------------------------------------
# 数据交付 / 数据集 / 元数据
# --------------------------------------------------------------------------
DATASET: list[dict] = [
    {
        "id": "data.required_columns",
        "title": "数据表必须包含规定字段",
        "pattern": r"(?:必须|应|须)[^。；;\n]{0,16}(?:包含|提供|含)[^。；;\n]{0,16}(?:字段|列|属性)"
                   r"|字段[^。；;\n]{0,10}(?:必须|须|应)|数据字典",
        "profiles": ["dataset"],
        "check": "dataset_columns_present",
        "scope": "per-file",
        "severity": "hard",
        "params": lambda m: {"required": [], "files": []},
        "why": "缺字段的数据无法被下游直接使用；required 列表从数据字典填入即可自动核对。",
    },
    {
        "id": "data.row_min",
        "title": "样本量下限",
        "pattern": r"(?:不少于|至少)\s*(\d+)\s*(?:条|行|个样本|条记录)",
        "profiles": ["dataset"],
        "check": "dataset_row_count",
        "scope": "per-file",
        "severity": "hard",
        "params": lambda m: {"min_rows": int(m.group(1)), "files": []},
        "why": "样本量不足会直接影响可用性结论。",
    },
    {
        "id": "data.identity_columns",
        "title": "数据中不得含身份/隐私字段",
        "pattern": r"(?:不得|不能|禁止)[^。；;\n]{0,16}(?:个人信息|隐私|身份)|脱敏|匿名化",
        "profiles": ["dataset"],
        "check": "dataset_no_sensitive_columns",
        "scope": "per-file",
        "severity": "hard",
        "params": lambda m: {"words": ["姓名", "身份证", "手机", "电话", "住址", "邮箱", "学校", "学号", "name",
                                       "email", "phone", "id_card", "address"]},
        "why": "交付含个人标识的数据通常直接违反合规要求。",
    },
    {
        "id": "data.data_dictionary",
        "title": "必须提供数据字典",
        "pattern": r"数据字典|字段说明|元数据[^。；;\n]{0,12}(?:必须|应|需|须)",
        "profiles": ["dataset"],
        "check": "required_files_present",
        "scope": "per-file",
        "severity": "soft",
        "params": lambda m: {"required": ["数据字典", "dictionary", "metadata"], "substring": True},
        "why": "没有数据字典的交付，接收方无法自解释字段含义。",
    },
    {
        "id": "data.provenance",
        "title": "须说明数据来源与采集方式",
        "pattern": r"(?:数据|样本)[^。；;\n]{0,12}(?:来源|出处|采集)[^。；;\n]{0,12}(?:必须|应|需|须|说明)",
        "profiles": ["dataset"],
        "check": "manual",
        "scope": "document",
        "severity": "hard",
        "params": lambda m: {},
        "why": "来源合法性需要人判断（授权链、伦理审查），工具无法替代。",
        "how": "人工确认：数据来源、授权范围、采集与脱敏流程均已说明，可对外交付。",
    },
]

# --------------------------------------------------------------------------
# 标书 / 申报书
# --------------------------------------------------------------------------
TENDER: list[dict] = [
    {
        "id": "tender.evaluation_items",
        "title": "逐条响应评审要点",
        "pattern": r"逐条响应|点对点响应|响应表|对照表",
        "profiles": ["tender"],
        "check": "manual",
        "scope": "document",
        "severity": "hard",
        "params": lambda m: {},
        "why": "是否逐条响应、有无负偏离，属于评审人判断，工具只能核对格式。",
        "how": "人工确认：招标/申报要点的每一条都有明确响应位置，无负偏离或已说明。",
    },
    {
        "id": "tender.forbidden_claims",
        "title": "不得出现排他性或违规承诺",
        "pattern": r"(?:不得|禁止)[^。；;\n]{0,20}(?:承诺|保证)[^。；;\n]{0,16}(?:必须|应)?|不得承诺",
        "profiles": ["tender"],
        "check": "manual",
        "scope": "document",
        "severity": "hard",
        "params": lambda m: {},
        "why": "违规承诺的法律后果需要人审，工具无法判定条款边界。",
        "how": "人工确认：无违规承诺、无排他性技术指标、商务条款与招标文件一致。",
    },
    {
        "id": "tender.required_sections",
        "title": "必须包含规定章节",
        "pattern": r"(?:必须|应|须)包含[^。；;\n]{0,24}(?:章节|部分|内容)",
        "profiles": ["tender"],
        "check": "required_text_pattern",
        "scope": "document",
        "severity": "soft",
        "params": lambda m: {"pattern": r"技术方案|商务|报价|资格|业绩", "label": "标书规定章节"},
        "why": "缺章节会被判为不响应；pattern 按招标文件实际章节名调整。",
    },
]

PROFILE_PACKS: dict[str, list[dict]] = {
    "academic": ACADEMIC,
    "docs": DOCS,
    "software": SOFTWARE,
    "dataset": DATASET,
    "tender": TENDER,
}

TEMPLATES: list[dict] = GENERIC + ACADEMIC + DOCS + SOFTWARE + DATASET + TENDER

PROFILE_NAMES = ["academic", "docs", "software", "dataset", "tender", "generic"]


def _to_bytes(value: str, unit: str) -> int:
    number = float(value)
    unit = (unit or "MB").upper()
    factor = 1024 ** 3 if unit.startswith("G") else 1024 ** 2
    return int(number * factor)


def _size_params(match) -> dict:
    if match.group(1) is not None:
        return {"limit": _to_bytes(match.group(1), match.group(2))}
    return {"limit": _to_bytes(match.group(3), match.group(4))}


def templates_for(profile: str) -> list[dict]:
    """Return the templates applying to one deliverable profile.

    `generic` keeps only the domain-neutral pack; any other profile gets the
    generic pack plus its own.
    """
    if profile == "generic":
        return list(GENERIC)
    pack = PROFILE_PACKS.get(profile, [])
    return list(GENERIC) + list(pack)
