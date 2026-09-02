# OH!News 功能修改需求存档（M5 阶段提案）

> 存档日期：2026-09-02。本文档为用户修改需求全文存档 + 技术顺序建议，**实施前需用户审核**。
> 前置状态：T1-T9 手术 17 commits + U 系列 4 commits + V 系列（V2-V7 12 文件未 commit）已落库/待落库。

---

## 一、用户需求原文存档（7 项）

### 1. 网页语言可选（21 语言）
用户选择后网页显示统一为所选语言；信源原文及关键术语保留源语言。
支持：English / Mandarin Chinese / French / Spanish / Arabic / Russian / German / Japanese / Portuguese / Hindi / Korean / Italian / Turkish / Dutch / Polish / Swedish / Persian (Farsi) / Indonesian / Vietnamese / Bengali / Cantonese。

### 2. 全站「?」tooltip
所有页面各层级指标、标题需在文本块旁添加交互「圆圈？」icon，hover 显示解释（按用户所选语言展示）。目的：降低阅读难度、便于理解功能与交互逻辑。

### 3. 首页 NOW 数据可视化丰富
围绕「现在变了什么」，按窗口粒度语义 1d / 7d / 30d / 全量自适应，从五个数据维度展示：
- 文章量/来源/语言（bronze 12.9k）
- 框架/立场（stances 1,573）
- NDI（68 点，弃权 64%）
- 情绪/SRL/动作（annotations 12.9k）
- Signal 历史
维度覆盖：信息流、叙事、分歧、情绪/行动、实体/网络。
排版尽量通过跳转展现完整内容，避免竖直长滚动。

### 4. 02 INVESTIGATE：文章拆解 + AI 报告
- 各媒体收集量图表移至首页；02 侧重单篇信源具体分析。
- 文章点击进入后核心功能=**文章拆解**（接入 AI API + agent 聊天框），拆解元素（颜色区分标注，hash(article id) 主键入库，agent 基于拆解内容生成研究报告）：
  主体(Actor/Subject)、客体(Object/Target)、利益相关方(Stakeholders)、核心事实(Hard Facts)、硬核数据(Quantitative Data)、数据定义域(Data Scope)、核心动作(Action/Verb)、因果链条(Causal Link)、时间线(Timeline/Stage)、叙事视角(Perspective/Framing)、显性立场(Explicit Stance)、隐性倾向(Implicit Bias)、情绪基调(Tone/Sentiment)、修辞与用词(Diction)、信源属性(Source Reliability)、论证逻辑(Argument Structure)、发布动机(Intent)、时代/行业背景(Context)。
- **研究报告 6+1 类**：真实性与可信度核查 / 意图与动机判定 / 归因与因果推演 / 叙事与框架分析 / 动态趋势与时序分析 / 综合结构化摘要 + 汇总报告（结合经济、金融专业整合）。agent 需以 system prompt + ai message 约束专业度。
- 报告可在 agent 聊天框中选存为档案 → 存入 04 MEMORY（**用户确认才存，不自动储存**，支持版本迭代后选择性保存）。
- 拆解元素作为可视化图表组放页面最上方（无数据显示「未配置分析」）。
- 现有 01 What happened ~ 06 Evidence 合并为「信源交叉分析」（每板块内容保留、合并收缩、可折叠）；agent 可基于交叉分析输出信源交叉分析报告。
- 07 Ask the analyst 改为按本信源生成的建议问题，可采纳并在 agent 中交互；agent 可解答问题并接入交叉分析数据。
- EVENT SUMMARY 同步改造。
- 页面窄栏一侧 agent 聊天框统一处理，可折叠并调整位置（左/右/下）。

### 5. 03 WATCH 重构：信源订阅 + 跟踪预警
- 缺失功能补齐：
  - **信源订阅**：按官方/非官方、国家地区、信源属性分类或自定义筛选选择信源。
  - **信源爬取**：手动启动实时收集 / cron 定时收集 / 回溯收集。
  - **信源扩展**：AI agent 聊天框——用户输入网址，agent 识别信源主体与爬取方式，确认后添加至信源数据库。
- **「我的订阅」+「预警订阅」合并为「跟踪预警」**：跟踪单元扩展为 实体 / 主题 / 问题 / 文章元素（立场、情绪、动作等，来源于 02 拆解）；每个跟踪/预警任务可点入获取单元级分析报告（AI）；联动首页可视化图表/状态栏。
- 页面窄栏一侧 agent 聊天框（同 4 的折叠/位置要求）。

### 5b.（原文编号重复，实为 04）04 MEMORY 重构：三档案库
- **元素档案库**（02 拆解结果）/ **研究档案库**（02 研究报告）/ **信源交叉分析档案库**（交叉分析报告）。
- 存储前提：在 02 与 agent 沟通中确认储存，否则不自动储存（保护用户不同意报告时的迭代空间，可选择性保存不同版本）。
- 04 设一个 agent（窄栏聊天框，同上折叠/位置要求）：可将用户搜索筛选后的报告组合为「档案报纸」，用户可在沟通中调整报纸内容。

### 06. 跨语言信源整合（02 内，可作独立工作流/工具/中间件）
以交叉分析为基础：保留原生语言 + 生成英文副本，统一以英文对比；需 AI 校验各语言专有名词、语法语序、情感等。

### 07. 首页 parent agent
- a. 新手教程 demo 填入；
- b. 控制模型供应商配置，显示在线状态、模型用量；
- c. 汇总 02/03/04 agent 的会话记录、状态、缓存、工具、skill、中间件、system prompts、HITL、ai message 等；包含 02/03/04 的功能，掌控除信源收集外的所有功能。
- d. **信源文章筛选与拆解队列管理**：主 agent 可推荐并配置筛选要分析的信源文章（按信源可靠性、主题相关性、时效性等打分排序），用户确认后进入拆解队列——避免对全量文章盲目跑 LLM 拆解浪费 token（成本闸门前置）。

---

## 二、数据/能力现状对照（诚实边界）

| 需求 | 现状 | 缺口 |
|---|---|---|
| 21 语言 UI | 全站中文硬编码；NDI 语料仅 zh/en | i18n 框架 + 21 字典 + RTL（阿/波）；信源数据非 21 语 |
| tooltip | 无 | 术语字典（21 语）+ Term 组件 |
| 首页图表组 | flow/框架哑铃/叙事场已有雏形 | 窗口聚合端点 + 五维度图表组 |
| 文章拆解 | 词典层（SVO 六域/情绪八类/SRL）已有，engine=lexicon | 15-18 元素 LLM 拆解 + 存储 + 渲染 |
| 6+1 报告 | research.py 两节点图 + chat.py 六工具 | 报告模板 + 专业度 prompt + 版本化存储 |
| 信源管理 | oh-sources 7 适配器 + SourcesManager（开发者页） | 分类筛选/手动/cron/回溯 + URL 扩展 agent |
| 跟踪预警 | Watch（3 类）+ Alerts（分位数）分离 | 统一任务模型 + 元素级单元 |
| 档案库 | library.sqlite（3 类）+ belief.sqlite | 三档案库 + 版本化 + 报纸组合 |
| 跨语言 | crosslang.py Phase 7 门禁（全部 locked） | LLM 翻译副本 + 校验流 |
| parent agent | 无 | 编排层 + 供应商面板 + 会话汇总 |

## 三、技术顺序建议（待审核）

**Phase A 地基**（1.5-2 周）
- A1 i18n 地基：自建轻量 dict（避免 next-intl 重依赖）+ 21 语言骨架文件 + RTL 切换；全站文案分批抽取
- A2 「?」tooltip：`<Term term="ndi"/>` 组件 + 术语字典（复用 A1 文件结构）
- A3 拆解契约与存储：`article_dissections` 新表（hash 主键，engine=llm，与词典层 annotations 分离）+ 18 元素 Pydantic 契约
- A4 AgentDock 通用侧栏组件（可折叠 + 左/右/下）：02/03/04 共用，提前做

**Phase B 02 核心**
- B0 信源筛选器（parent agent 职责前置）：按信源可靠性/主题相关性/时效打分 → 推荐拆解队列 → 用户确认后入库（article_dissection_queue 表；token 成本闸门）
- B1 拆解 agent（LLM 增强，仅消费 B0 队列 + 用户主动触发，缓存复用——非全量回填）
- B2 6+1 报告生成（system prompt 专业度约束 + 版本化）
- B3 02 页面重构（拆解可视化顶部 + 交叉分析折叠区 + 建议问题）

**Phase C 03**
- C1 信源管理增强（筛选/手动/cron/回溯）
- C2 信源扩展 agent（URL→主体+爬取方式识别）
- C3 跟踪预警统一任务模型（实体/主题/问题/元素四类单元）
- C4 任务级分析报告 agent

**Phase D 04**
- D1 三档案库 + 确认式版本化存储
- D2 档案报纸 agent

**Phase E 集成**
- E1 跨语言整合 agent（英文副本 + 术语表锁定 + 回译校验）
- E2 parent agent（教程 demo / 供应商面板 / 会话与配置汇总）
- F 首页图表组（窗口×五维度）可与 B 并行

## 四、待用户裁决的关键点

1. **i18n 方案**：自建 dict vs next-intl；21 语言翻译初稿由 AI 生成后人工抽检？
2. **拆解成本**：两级闸门——B0 parent agent 筛选队列（推荐+用户确认）→ B1 按需拆解+缓存；全量回填 12.9k 仅在用户明确要求时执行；建议默认前者。
3. **agent 框架**：延续现有顺序编排（graph.py 风格）vs 引入 langgraph；会话存储扩展 chat.sqlite vs 每子 agent 独立库。
4. **跟踪预警合并**：旧 alerts.sqlite/watch.sqlite 数据迁移策略（保留历史 or 清零重建）。
5. **跨语言副本存储**：bronze 加 translated 列 vs 副本独立表（建议独立表，原文不可变原则）。
6. **信源爬取合规**：用户自定义 URL 爬取需遵守 robots/ToS + 限速（工程守则既定）。
7. **V 系列未 commit 12 文件**：新阶段开工前先验收 commit，避免 diff 混杂。
8. **Signal 历史落库**（首页图表组依赖）：新表 signal_snapshots 每日快照。
