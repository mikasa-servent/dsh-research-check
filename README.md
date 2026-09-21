# dsh-research-check

**交付物证据链与合规校验插件** —— 把"要求"变成可执行规格，把"数字"绑回程序输出，交接前一次性查出机械性错误。

> 面向 DeepSeek Harness（DSH）插件；同时提供 **MCP 服务器**与**独立 agent skill**，
> 因此 Claude Code / Codex / Cursor 等任何支持 MCP 的 harness 也能直接用同一套能力。

```bash
dsh plugin --profile web add dsh-research-check
```

---

## 它解决什么问题

评审、验收、甲方退回一份交付物，绝大多数理由**不是学术或技术问题，而是机械性错误**——下面每一条都是本插件在真实项目中实际抓到过的：

| 真实缺陷 | 表现 | 谁抓到的 |
|---|---|---|
| 图注改了、正文没改 | 图注写 4883 kWh，程序输出是 4760.98 | 台账核对（`research_numbers` + `ledger`） |
| 两个口径混用 | 正文月度合计 1885.1 万，表里是 1863.5 万 | 规格页面规则（`spec_check`） |
| 比率表述不严谨 | 写"两个口径的 1/565"，实测只有一个是 565，另一个 583 | 人工复核触发（工具报出比对结果） |
| 改稿残留旧值 | 摘要写 1536.4，正文定稿是 1521.6 | 台账 `verify` 的锚点探针 |
| **身份信息泄露** | xlsx 属性里存着 `xueyi`、`企业用户_505363329`；docx 里存着账号名 | `office_metadata_no_identity` |
| 页数超限 | 正文 31 页，上限 30 | `max_pages`（自动识别附录起始页） |
| 清单与实物不符 | 论文附录列 11 项，压缩包里实际 12 项 | `manifest_matches_archive` |
| 交付包里带报错日志 | `run.log` 里满是 Traceback 仍当成交付证据 | `forbidden_text`（会扫交付文件，不只看正文） |
| 数据不合规 | 交付数据里混入手机号字段 | `dataset_no_sensitive_columns` |
| 占位符没删 | 对外文档里留着 `TODO`、`待补充` | `placeholder_text` |

**它不做什么**（写进设计与文档，避免误解）：
- ❌ 不生成论文/文档内容——它是校对器，不是生成器
- ❌ 不判断两个冲突数字谁对——报告位置与两个候选值，由作者定夺
- ❌ 不重算公式——数字是**匹配**而非**重新推导**；若程序算错而正文照抄，两边一致仍会通过，结论关键值仍需独立复算
- ❌ 不评方法、不评文风、不做法律意见

---

## 四个工具

| 工具 | 作用 | 写入 |
|---|---|---|
| **`research_spec`** | **要求 → 可执行规格 → 逐条判定**。把赛会规范/期刊须知/验收标准/招标文件解析成规格 JSON（每条规则带判定器、严重度、作用域、**出处引用**），再对交付物判级 | `build` |
| **`research_audit`** | 一次性体检：页数上限、摘要单页、空白页、图表是否被引用、PDF 体积、PDF 与 OOXML 元数据身份信息、压缩包清单一致性 | 只读 |
| **`research_numbers`** | 数字一致性：同句式异值检测；给台账时逐条核对"台账值是否还在文中" | 只读 |
| **`research_ledger`** | 证据链台账：`teach` 从文稿自动登记候选、`add` 登记带出处的值、`verify` 核对、`list` 查看 | `teach`/`add` |

外部 harness 通过 **MCP** 获得等价能力（工具名 `spec_build` / `spec_check` / `audit` / `numbers` / `ledger` / `list_rules`）：

```json
{ "transport": "stdio", "serverName": "research-check",
  "command": "node", "args": ["<plugin>/mcp/server.mjs"] }
```

---

## 要求 → 规格：六类交付物规则包

`research_spec(action="build", profile=…)` 选择规则包；`profile` 决定"哪些要求会被翻译成可判定规则"。

| profile | 适用对象 | 规则数 | 典型规则 |
|---|---|---|---|
| `academic` | 学位/竞赛/期刊论文 | 29 | 正文页数、摘要单页、图表引用、页边距、行距字号、摘要内公式 |
| `software` | 软件交付、项目验收、发版 | 15 | 必备文件、LICENSE、CHANGELOG、报错标记残留、可追溯性（人工） |
| `dataset` | 数据交付、数据集 | 14 | 字段齐备、样本量下限、隐私字段、数据字典 |
| `docs` | 技术文档、说明书、手册 | 13 | 段落字数、版本号、联系方式、TODO 残留 |
| `tender` | 标书、申报书 | 12 | 章节齐备、逐条响应（人工）、违规承诺（人工） |
| `generic` | 任何交付物 | 9 | 体积、命名、身份元数据、清单一致性、占位符 |

**37 个判定器**，按用途分组：

| 组 | 数量 | 判定器 |
|---|---|---|
| 版面（PDF） | 9 | `max_pages` `min_pages` `abstract_first_page` `abstract_within_page` `no_blank_page` `all_figures_referenced` `all_tables_referenced` `max_pdf_bytes` `metadata_no_identity` |
| 结构（源码/文本） | 7 | `max_sections` `max_subsections_per_section` `no_toc` `forbidden_text` `placeholder_text` `required_text_pattern` `version_string_present` |
| 排版（源码级） | 6 | `linespread_min` `fontsize_min` `page_geometry` `margins_min` `bibliography_placeholders` `math_in_abstract` |
| 素材 | 4 | `asset_format` `asset_naming` `asset_min_dpi` `no_asset_duplicates` |
| 交付物通用 | 8 | `file_size_max` `office_metadata_no_identity` `file_naming` `manifest_matches_archive` `archive_size_max` `bundle_no_forbidden_files` `required_files_present` `max_paragraph_chars` |
| 数据交付 | 3 | `dataset_columns_present` `dataset_row_count` `dataset_no_sensitive_columns` |

### 三条设计纪律

1. **每条规则必须声明判定器**，否则规格加载即报错。无法机器判定的写成 `manual`，进人工清单——**绝不假装能查**。（例如"行距是否 1.5 倍"在 PDF 里已固化，只能判源码；"测试是否覆盖需求"只能人工。）
2. **`skipped` 不算通过**。缺输入、缺可选库、参数没填，都如实报 `skipped`；报告里绝不与 `pass` 混同。
3. **每条判定都带出处引用**（`source`），回复评审/甲方时可直接引用条款原文。

---

## 安装

### DSH 插件

```bash
# 1) 链接 DSH 的 peer 包（链接安装必须做，否则报 ERR_MODULE_NOT_FOUND: @deepseek-ai/dsh-tools）
node tests/link-peers.mjs

# 2) 装进某个 profile（会自动写进该 profile 的 dsh.profile.bundles）
dsh plugin --profile web add link:C:\path\to\dsh-research-check

# 3) 重启该 profile —— 工具在启动时注册，重启后模型即可调用
```

### 校验核心的运行依赖

```bash
pip install pymupdf openpyxl pillow python-docx
```

- `pymupdf`：所有版面规则（页数、摘要、空白页、图表引用、PDF 元数据）
- `openpyxl`：xlsx 数据交付与 Office 属性
- `pillow`：位图 DPI 规则；`python-docx`：段落长度与 docx 属性

未检测到 Python 时，工具返回 `NO_PYTHON`；可用 `DSH_RESEARCH_PYTHON` 指定解释器。

### 独立 agent skill（其他 harness）

```bash
cp skill/SKILL.md ~/.dsh/skills/research-evidence-check/        # DSH 用户级
cp skill/SKILL.md <project>/.dsh/skills/research-evidence-check/ # 项目级，随仓库共享
cp skill/SKILL.md ~/.agents/skills/research-evidence-check/      # .agents/skills 约定
```

---

## 快速上手

### 1. 先从要求文件生成规格

```bash
# 论文
python python/spec_build.py --requirements format2026.doc --out specs/cumcm-2026.json \
    --profile academic --name "2026 全国大学生数学建模竞赛（论文格式规范）"
# 软件验收
python python/spec_build.py --requirements 验收标准.docx --out specs/acceptance.json \
    --profile software --name "软件交付验收标准"

python python/spec_build.py --list-profiles     # 查看可用类型与规则数
```

生成后**逐条复核**：确认 `params`（页数/体积/required/manifest）、读一遍 `source` 引用，
补齐留空参数。留空的规则会在判定时如实报 `skipped`——那是诚实的失败，不是通过。

### 2. 对着交付物判定

```bash
# 论文：源码 + 成稿 + 交付文件 + 压缩包
python python/check_spec.py --spec specs/cumcm-2026.json --root . \
    --doc paper/main.tex --pdf 论文初稿.pdf \
    --files 论文初稿.pdf support.zip --archive support.zip

# 软件交付：只看文件类规则
python python/check_spec.py --spec specs/acceptance.json --root . \
    --files README.md LICENSE CHANGELOG.md run.log

# 格式化输出（中文表格）
python tests/run_spec_check.py --spec specs/cumcm-2026.json
```

### 3. 在会话里用（DSH）

```
research_audit(paper="论文初稿.pdf", archives=["support.zip"], manifest=["result1.xlsx", "..."])
research_numbers(paper=["paper/main.tex"], ledger="paper-ledger.json")
research_ledger(action="add", key="q3.total_cost", value=1521.6, unit="万元",
                source="code/q3_rolling_mpc.py", anchor="全年费用")
research_spec(action="check", spec="specs/cumcm-2026.json", pdf="论文初稿.pdf")
```

---

## 规格（spec）与台账（ledger）格式

### 规格：每条规则都是一份可复现的判定依据

```json
{
  "id": "doc.body_pages",
  "title": "正文页数上限",
  "check": "max_pages",
  "scope": "body",
  "severity": "hard",
  "params": { "limit": 30, "appendix_marker": ["附录"] },
  "why": "页数是评委翻页时最先感知的硬约束，超一页即违规。",
  "source": "…第四条论文从第四页开始是正文内容（不要目录，不超过30页）…"
}
```

- `severity`：`hard` → error、`soft` → warning、`info` → 不改判
- `scope`：`document` / `body`（附录前）/ `per-file` / `bundle`
- `check`：必须是 37 个判定器之一，或 `manual`

### 台账：数字与出处的绑定

```json
{
  "schema": 1,
  "entries": [
    {
      "key": "q3.total_cost",
      "value": 1521.6,
      "unit": "万元",
      "source": "code/q3_rolling_mpc.py",
      "anchor": "全年费用",
      "revision": 3
    }
  ]
}
```

- `key` 用**语义名**而不是数值 —— 程序重跑后刷新数值不必改正文
- `anchor` 是数值附近的固定短语，`verify` 用它定位并检查"同锚点处是否出现量级相近的异值"
- `value` 一律数值，单位单独放 `unit`，避免把「1.5 万元」和「15000 元」判成两个事实

---

## 实测样例

**真实论文**（2026 CUMCM C 题，87 页 / 正文 30 页，规格 19 条规则）：

```
[ok  ] hard  gen.archive_manifest   与清单逐条一致（清单 自动识别 13 项）
[ok  ] hard  doc.body_pages         正文（附录自第 31 页起）30 页 / 上限 30 页
[ok  ] hard  doc.abstract_within_page 摘要（含关键词）在 1 页内
[ok  ] hard  doc.margins            页边距 {top:2.5, bottom:2.5, left:2.5, right:2.5}
[ok  ] hard  doc.metadata_identity  属性未见身份信息
[skip] hard  gen.office_identity    未提供 docx/xlsx 文件（需 --files 传入）
→ 15 通过 / 0 错误 / 2 跳过
```

**跨领域**（`python tests/test_generality.py`，三类非论文交付物，各含干净件与缺陷件）：

| 交付物 | 干净件 | 缺陷件被拦截 |
|---|---|---|
| 软件包 | 0 error | 缺 `README.md`；日志含 `Traceback`/`ERROR:` |
| 数据集 | 0 error | 缺字段；样本量不足；混入手机号字段 |
| 技术文档 | 0 error | 超长段落（warning）；`TODO` 残留；docx 作者身份（error） |

---

## 验证

九段验证，全部可在本地复现：

```bash
npm test                 # 语法 + 上架清单 + 依赖无关契约 + 规格 e2e + 离线回归 + 跨领域
npm run test:generality  # 只跑跨领域（软件/数据/文档，含负例）
npm run mcp:smoke        # MCP 协议层（stdio 真实报文）
npm run boot             # 真启动一个临时 profile，确认不会把 profile 启崩
npm run test:hygiene     # 负例：故意写入身份元数据，必须判 fail
```

在 CI 里（`.github/workflows/verify.yml`）跑 Node 22/24 + Python 3.13：

| 阶段 | 结果 |
|---|---|
| 语法（20 模块，动态枚举） | 0 失败 |
| 上架清单（registry 字段、文件、skill frontmatter） | 35 通过 |
| 依赖无关运行期契约（用 stub 替身，CI 无需 harness） | 33 通过 |
| MCP 协议（initialize / tools/list / tools/call / 错误码） | 20 通过 |
| 离线规格回归（合成论文 + 3 个负例） | 全部通过 |
| 跨领域回归（software / dataset / docs） | 全部通过 |
| DSH 运行期契约 + 工具 e2e + 规格 e2e | 38 通过 / 4 次调用 / 负例拦截 |
| 真启动 profile | pass |

---

## 已知边界

- **数字是匹配不是重算**：程序算错而正文照抄，两边一致仍会通过。结论关键值请独立复算。
- **单位表是白名单**（`万元/kWh/MW/%` 等），新领域需在 `python/check_numbers.py` 的 `NUM_UNITS` 增补。
- **压缩包只读 zip**；`.rar` 需外部解包。
- **段落长度只认 `.docx`**：PDF 无段落边界，该规则会报 `skipped` 而不是猜。
- **人工清单无法自动化**：`manual` 条目（原创性、可追溯性、测试覆盖）需要人逐条确认。

---

## 目录结构

```
lib/index.js        插件入口（apply / inject / Config / systemPrompt / skills）
lib/core.js         宿主无关执行核心 —— 插件与 MCP 服务器共用，避免两套逻辑漂移
lib/tools.js        四个 DSH 工具的注册与路径解析（不含业务逻辑）
lib/spec-tool.js    规则词汇表与交付物 profile 定义
lib/ledger.js       台账读写、逐条核对、锚点探针
lib/ledger-cli.js   命令行入口（不依赖 DSH）
lib/skill.js        读取并注册内嵌 skill
lib/util.js         Python 解释器发现、进程执行、结果汇总
mcp/server.mjs      零依赖 MCP 服务器（stdio JSON-RPC 2.0）
skill/SKILL.md      独立 agent skill（五阶段流程）
python/rule_packs.py   六类交付物规则包（模板 + 判定器 + 出处）
python/spec_build.py   要求文本 → 规格 JSON
python/check_spec.py   规格 → 判定报告（37 个判定器）
python/check_numbers.py 数字抽取与一致性
python/audit_paper.py   版面与文档卫生体检
python/check_hygiene.py 文档元数据专项
tests/                  九段验证（含负例与跨领域）
```

---

## License

MIT

---

## 由来

本插件从一条真实的论文生产线里抽出来：先是给单篇论文写检查脚本，后来发现**每一个检查都对应一个真实发生过的缺陷**，而这类缺陷与学科无关——凡是"数据 → 图表 → 结论"的交付物都会犯。于是把"要求"抽象成规格、把"数字"绑回台账、把判定器做成词汇表，让它能用在论文、文档、软件、数据、标书五类交付上。
