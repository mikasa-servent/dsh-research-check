# dsh-research-check

DeepSeek Harness 插件：给"数据 → 图表 → 结论"型论文做**证据链校验**。

它不是论文生成器，而是**校对器**：让每个数字、每张图、每句结论都能回指到底层程序输出，
并在投稿前把硬约束与卫生问题一次性查完。

## 安装

```bash
# 1) 链接 DSH 的 peer 包（链接安装的插件必须做这一步，否则加载时报
#    ERR_MODULE_NOT_FOUND: @deepseek-ai/dsh-tools）
node tests/link-peers.mjs

# 2) 装进某个 profile（web / tui / headless）
dsh plugin --profile web add link:C:\path\to\research-plugin
#    该命令会自动把 "dsh-research-check" 追加进 profile package.json 的
#    dsh.profile.bundles

# 3) 重启该 profile（工具在启动时注册，重启后模型即可调用）
```

校验核心需要 Python 3.10+，其中 PDF 解析需要 `pymupdf`、表格解析需要 `openpyxl`：

```bash
pip install pymupdf openpyxl
```

未检测到 Python 时，工具会返回 `NO_PYTHON`；可用环境变量 `DSH_RESEARCH_PYTHON` 指定解释器。

### 开发自检

```bash
npm run check        # 五个 JS 文件语法检查
npm run contract     # 契约测试：Config 是 Standard Schema、section order 是有限数字、
                     #   inject 只列真实服务、三个工具都具备 output.render、peer 与 order 表
npm run e2e          # 用真实论文文件跑通三个工具的 execute
npm run boot         # 真启动一个临时实例（随机端口），确认 profile 能起来后自动关闭
npm run test:hygiene # 负例回归：故意写入身份元数据，必须被判 fail
npm run test         # check + contract + e2e
```

`contract` / `smoke` / `e2e` / `boot` 需在 profile 目录下执行（例如 `cd ~/.dsh/profiles/web`），
这样 Node 才能从 profile 的 node_modules 解析 DSH peer 包。

### ⚠️ 三类"只在真启动时才炸"的坑（本插件踩过，已固化为回归项）

链接型插件最容易出问题的不是业务逻辑，而是 **cordis / harness 的运行期约定**。
本插件曾因此把整个 profile 启崩一次，下面每一条都对应 `contract` / `boot` 里的一个断言：

| 症状 | 根因 | 正确写法 |
|---|---|---|
| 启动即报 `Cannot read properties of undefined (reading 'validate')` | `export const Config` 写成普通对象 `{ guidance: {...} }`；cordis v4 要求它是 **Standard Schema** | `import z from "@deepseek-ai/schemastery"; export const Config = z.object({ guidance: z.string().default("") })` |
| 启动即报 `order must be a finite number` | 调用了不存在的 `ctx.systemPrompt.getSectionOrder("TOOL_GENERAL")`；order 由 `dsh-system-prompt` 内部表决定且**未导出** | 用显式数字：`TOOL_REPORT = 2900`、`TOOLS_SDK = 5000`，插件取 2950（`contract` 会校验落点） |
| 启动即报 `ERR_MODULE_NOT_FOUND: @deepseek-ai/dsh-tools` | 链接安装时 Node 从插件**真实路径**解析依赖，profile 的 node_modules 不在查找链上 | `node tests/link-peers.mjs` 建立 peer junction（`dsh-tools` / `cordis` / `schemastery`） |

另有一条**运行期**（不影响启动）的坑：该 build 的 `defineTool` 强制读取 `options.output.render`，
所以每个工具都必须给 `output`；本插件统一用 `openOutput()`（开放 schema + JSON 文本渲染）。

**结论：装完插件、升级 dsh 之后，都必须跑 `npm run boot`。**
任何"只在 mock 上下文里通过"的验证都不足以证明 profile 起得来——这是本次事故的直接教训。

## 三个工具

| 工具 | 作用 | 写入 |
|---|---|---|
| `research_audit` | 版面与投稿卫生：正文页数上限、摘要是否首页、空白页、图表是否被引用、PDF 属性身份信息、docx/xlsx 作者字段、压缩包与附录清单是否一致 | 只读 |
| `research_numbers` | 数字一致性：同句式异值检测；给台账时逐条核对"台账值是否还在文中" | 只读 |
| `research_ledger` | 证据链台账：`teach` 扫描文稿登记候选数值、`add` 登记一条带出处、`verify` 逐条核对、`list` 查看 | `teach`/`add` |
| `research_spec` | **规格符合性**：把要求文件变成可执行规格（`build`），再对着论文与交付物逐条判定（`check`），`list` 列出可判定的规则词汇 | `build` |

## 规格符合性（`research_spec`）

思路：**要求不该只存在于人的记忆里**。"正文不超过 30 页"写进规格文件后，才能每次改完自动复验。
这套能力**与学科无关**——它只关心"要求 → 可判定规则 → 逐条判定"，所以论文、技术文档、软件交付、
数据集、标书用的是同一套工具，只是规则包不同。

### 交付物类型（profile）

| profile | 适用对象 | 规则数 | 典型规则 |
|---|---|---|---|
| `academic` | 学位/竞赛/期刊论文 | 29 | 正文页数、摘要单页、图表引用、页边距、行距字号 |
| `docs` | 技术文档、说明书、手册 | 13 | 段落长度、版本号、联系方式、待办残留 |
| `software` | 软件交付、项目验收、发版 | 15 | 必备文件、LICENSE、CHANGELOG、报错标记残留 |
| `dataset` | 数据交付、数据集 | 14 | 字段齐备、样本量、隐私字段、数据字典 |
| `tender` | 标书、申报书 | 12 | 章节齐备、逐条响应、违规承诺 |
| `generic` | 任何交付物 | 9 | 体积、命名、身份元数据、清单一致性、占位符 |

```bash
# 论文
python python/spec_build.py --requirements format2026.doc --out specs/cumcm-2026.json \
    --profile academic --name "2026 全国大学生数学建模竞赛（论文格式规范）"
# 软件验收
python python/spec_build.py --requirements 验收标准.docx --out specs/acceptance.json \
    --profile software --name "软件交付验收标准"
# 数据交付
python python/spec_build.py --requirements 数据交付要求.md --out specs/data.json \
    --profile dataset --name "数据交付检查表"

python python/spec_build.py --list-profiles      # 查看可用类型与规则数

# 对着交付物判定
python python/check_spec.py --spec specs/acceptance.json --root . \
    --files README.md LICENSE CHANGELOG.md run.log
```

### 跨领域实测（`python tests/test_generality.py`）

三类非论文交付物，每类用**自己的要求文本**生成规格，各造一份干净件与一份缺陷件：

| 交付物 | 干净件 | 缺陷件中被拦截的问题 |
|---|---|---|
| 软件包 | 0 error | 缺 `README.md`；交付日志含 `Traceback` / `ERROR:` |
| 数据集 | 0 error | 缺字段；样本量不足；混入手机号字段 |
| 技术文档 | 0 error | 超长段落（warning）；`TODO` 残留；docx 作者身份（error） |

一个"永远通过"的规则包会让第 2 列全绿而第 3 列全空——这个测试就是防止规则包退化成装饰品。

规则长这样（每条都带判定器与出处）：

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

设计约束（决定了它不会变成花架子）：

1. **每条规则必须声明 `check`**，否则规格加载即报错；无法机器判定的写 `manual`，
   进人工清单，**绝不假装能查**。
2. **`severity` 三级**：`hard` 判 error、`soft` 判 warning、`info` 不改判。
3. **`scope` 精确**：`document` / `body`（附录前）/ `per-file` / `bundle`，
   所以"正文 ≤30 页、附录不限"能如实表达。
4. **`skipped` 不算通过**：缺输入或缺可选库时如实报 skipped，报告里绝不混同 pass。
5. **出处引用**：每条判定附 `source`，答辩/回复审稿意见时直接引用条款。

可用判定器（38 个）见 `research_spec(action="list")`，按用途分组：

- **版面**：`max_pages`、`abstract_first_page`、`abstract_within_page`、`no_blank_page`、
  `all_figures_referenced`、`all_tables_referenced`、`max_pdf_bytes`、`metadata_no_identity`
- **结构**：`max_sections`、`no_toc`、`forbidden_text`
- **排版（源码级）**：`linespread_min`、`fontsize_min`、`page_geometry`、`margins_min`
- **素材**：`asset_format`、`asset_naming`、`asset_min_dpi`、`no_asset_duplicates`
- **交付物（与领域无关）**：`file_size_max`、`office_metadata_no_identity`、`file_naming`、
  `manifest_matches_archive`、`archive_size_max`、`bundle_no_forbidden_files`、
  `required_files_present`、`placeholder_text`、`max_paragraph_chars`、
  `required_text_pattern`、`version_string_present`
- **数据交付**：`dataset_columns_present`、`dataset_row_count`、`dataset_no_sensitive_columns`

### 典型用法

```
research_audit(paper="论文初稿.pdf", archives=["support.zip"],
               manifest=["result1.xlsx", "...", "AI 工具使用详情.pdf"])

research_numbers(paper=["paper/sections/*.tex"], ledger="paper-ledger.json")

research_ledger(action="add", key="q3.total_cost", value=1521.6,
                unit="万元", source="code/q3_rolling_mpc.py", anchor="全年费用")
research_ledger(action="verify", ledger="paper-ledger.json", paper=["论文初稿.pdf"])
```

命令行等价形式（不经 DSH 也能用）：

```bash
node lib/ledger-cli.js teach  --ledger L.json --paper paper.tex --unit-filter 万元 --min-abs 100
node lib/ledger-cli.js verify --ledger L.json --paper paper.pdf [--near]
python python/check_numbers.py --paper paper.pdf [--ledger L.json]
python python/audit_paper.py   --paper paper.pdf --archives support.zip --manifest a.xlsx b.py
```

## 台账格式

```json
{
  "schema": 1,
  "paper": "论文初稿.pdf",
  "entries": [
    {
      "key": "q3.total_cost",
      "value": 1521.6,
      "unit": "万元",
      "source": "code/q3_rolling_mpc.py",
      "anchor": "全年费用",
      "revision": 3,
      "updated": "2026-09-13T10:00:00.000Z"
    }
  ]
}
```

- `key` 用语义名（`q3.total_cost`），**不要用数值当键**——这样程序重跑后刷新数值不必改正文。
- `anchor` 是数值附近的固定短语，`verify` 用它定位并检查"同锚点处是否出现量级相近的异值"。
- `value` 一律是**数值**，单位单独放在 `unit`，避免把"1.5 万元"和"15000 元"判成两个值。

## 校验逻辑（为什么这样设计）

1. **先登记、后核对**：只有存在台账，工具才知道"这个数字本应是多少"，否则只能做同句异值检测。
2. **锚点 + 量级窗口**：同一锚点附近出现同单位、量级相近但数值不同的数，才判为冲突；
   否则会大量误报（实测把"35.1 万元"和"1521.6 万元"混在一句里就会误判）。
3. **PDF 与 tex 双入口**：`.tex` 快且不受排版断行影响，适合日常迭代；
   `.pdf` 是最终产物，适合投稿前复核（顺带能查版面）。
4. **阈值全部可调**：`--max-body-pages`、`--max-mb`、`--tol`、`--min-abs` 都有默认值，
   不同赛事/期刊的规矩只需换参数。

## 实测样例

在本插件自带的下游用例（2026 CUMCM C 题论文，87 页 / 正文 30 页）上：

```
research_audit  → 正文 30 页 / 上限 30 页（总 87 页）；PDF 属性未见身份信息；
                  压缩包与清单逐条一致（12 项，2.40 MB）→ pass
research_numbers（365 天全年 PDF，抽取 7941 个数字）→ 2 条同句异值提示（均为人工确认后属正常对照）
research_ledger verify（台账故意写入陈旧值 1536.4 万元）→ 能定位到与台账不一致的段落
```

## 已知边界

- 数值抽取基于正则与单位表，**不解析语义**：同一数字在不同语境重复出现时不会报错，
  这是刻意的（否则误报无法收敛）。
- 中文单位表是白名单（`万元/kWh/MW/%` 等），需要新单位时在 `python/check_numbers.py`
  的 `NUM_UNITS` 里加一项即可。
- 压缩包只读 zip；`.rar` 需要外部解包工具。
- 表格数据（csv/xlsx）目前只用于抽取候选值，尚未做"公式级"重算核对（规划中：
  让用户在台账里写 `expr` 表达式，工具直接重算）。

## 目录结构

```
lib/index.js       插件入口（apply / inject / Config / systemPrompt / skills）
lib/tools.js       三个工具的注册与参数解析
lib/ledger.js      台账读写、核对、锚点探针
lib/ledger-cli.js  命令行入口（不依赖 DSH）
lib/skill.js       读取并注册内嵌 skill
lib/util.js        Python 解析、进程执行、结果汇总
skill/SKILL.md     独立 skill（research-evidence-check），可单独复制给别人用
python/check_numbers.py  数值抽取与一致性检查
python/audit_paper.py    版面与卫生体检
python/check_hygiene.py  文档元数据专项（可独立调用）
tests/                   回归脚本（含"故意写错值"的负例）
```

## Skill（给其他智能体 / harness 用）

本插件自带 `research-evidence-check` skill，**两条路径都可用**：

1. **随插件自动启用**：插件启动时通过 `ctx.skills.register(...)` 注册，装上即有。
   可用 Config 关闭或改路径：

   ```yaml
   - name: dsh-research-check
     config:
       registerSkill: false          # 不注册内嵌 skill
       # skillPath: "D:/my/skills/research-evidence-check/SKILL.md"
   ```

2. **独立目录形式**（Claude Code、DSH、任何扫描 skills 目录的 harness）：

   ```bash
   # DSH 用户级
   mkdir -p ~/.dsh/skills/research-evidence-check && cp skill/SKILL.md "$_/"
   # 或项目级（随仓库提交，团队共享）
   mkdir -p .dsh/skills/research-evidence-check && cp skill/SKILL.md "$_/"
   # Claude Code 等使用 .agents/skills 约定
   mkdir -p ~/.agents/skills/research-evidence-check && cp skill/SKILL.md "$_/"
   ```

   frontmatter 用规范字段：`name`（kebab-case）、`description`、`whenToUse`；
   调用面由 `disable-model-invocation` / `user-invocable` 控制（旧键 `modelInvocable`
   等会被 provider 拒绝，`tests/registry-manifest.mjs` 会拦住）。

## 上架到插件市场

社区注册表是 [awesome-dsh-plugin](https://awesome-dsh-plugin.com)（源仓库
`github.com/awesome-dsh-plugin/awesome-dsh-plugin`，条目按 **npm 包名** 分发）。

**发布前**（本仓库已全部满足，`npm run registry` 逐条断言）：

```bash
npm run test          # 语法 + 上架清单 + 契约 + 端到端
npm run boot          # 真启动一次，确认不会把 profile 启崩
npm pack --dry-run    # 检查将被打包的 16 个文件
```

**发布步骤**：

```bash
# 1) 发布到 npm（publishConfig 已设 public）
npm publish                  # 首次需先 npm login

# 2) 用户侧安装（市场页显示的就是这条命令）
dsh plugin --profile web add dsh-research-check

# 3) 提交到社区注册表：向 awesome-dsh-plugin 仓库提 PR，条目形如
#    { "name": "dsh-research-check", "owner": "<你的 GitHub 名>",
#      "url": "https://github.com/<你>/dsh-research-check",
#      "category": "tools",           # 备选：docs / skill / workflow
#      "description": { "en": "<package.json 的英文描述>",
#                       "zh": "<package.json 的中文描述>" },
#      "npm": "dsh-research-check" }
```

发布后每次改版本号：更新 `CHANGELOG.md` → `npm version patch|minor|major` →
`npm publish` → `npm run test` 全绿。

## License

MIT
