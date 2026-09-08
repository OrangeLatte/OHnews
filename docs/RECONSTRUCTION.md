# OH!News 产品重构计划 v4 — 从数据监测到情报解释

> **当前状态（2026-09-09，M6 收官）**：v4 计划已全部实施完成并多轮演化。产品现为「OH!News 认知闭环情报终端」——报纸风浅色 UI，主路径 = 发现变化 → 检验证据 → 形成判断 → 持续追踪（NOW → INVESTIGATE/observe → WATCH → MEMORY/archive）。工程里程碑 M1（契约层）→ M2（情报管道）→ M3（语义栈）→ M5（Agent 工程：langgraph 四图 + 18 元素拆解 + 六型报告 + 跟踪预警统一 + 三档案库 + 跨语言整合 + parent 总控）→ M6（收官 demo）均落库。历史过程文档（BLUEPRINT/REDESIGN/REFACTOR_V2/PRODUCT_AUDIT/FEATURE_PLAN_M5/HANDOVER_M2）已迁出至 `../OHnews_backup_20260909/docs_migrated/`（备注见该目录 MIGRATION_NOTES.md）。本文件保留作架构与数据模型真源；运行与演示说明见 README.md / README.zh.md。

> 真源链：BLUEPRINT.md（v2 架构裁决）→ REDESIGN.md/REDESIGN_AGENT.md（v3 产品与 Agent）→ **本文件（v4 情报本体重构）**。
> 执行约束：Ontology → Data model → Evidence model → Pipeline → IA → Interaction → UI。禁止为美学改 UI；每个组件必须回答「回答什么问题/代表什么情报对象/数据从哪来/证据是什么/下一步动作」。

---

## 0. 现状审计（Current System Audit）

### 0.1 已有资产（保留）

| 层 | 资产 | 位置 |
|---|---|---|
| 采集 | 61 源 SourceAdapter（L1×17/L2×13/L3×27/L4×4，5 语言） | oh-sources |
| 存储 | Bronze parquet / Silver sqlite WAL / NDI series | oh-storage |
| 事件 | EventBuilder（实体×日窗，≥3 篇×≥2 源门） | oh-pipeline events |
| 信号 | detect 四类：attention_spike / narrative_shift / ndi_alert / expectation_gap | oh-pipeline detect |
| 统计 | Dirichlet JSD / NDI / 温差 ΔT / 弃权语义 | oh-pipeline divergence |
| 分歧解剖 | 簇×簇 JSD / 主体对立表 / 词级 SVO 光谱 | oh-pipeline anatomy+svo |
| LLM | ModelRouter 三级路由 / committee 双标注员 | oh-llm |
| Agent | analysis_graph / chat_graph / research_graph / intel 四节点 / orchestrator Intent | oh-agents |
| 交互 | 六页 IA / watch 三类订阅 / library 档案 / decisions 决策日志 | web |
| 纪律 | NDI=EPU 式条件变量 / PIT / ρ≥0.8 前禁对外数字 / 非 AI 剧场 | 全局 |

### 0.2 概念不一致（必须消除）

| # | 问题 | 现状证据 | 根因 |
|---|---|---|---|
| P1 | **内部标识符直出 UI** | "OPENAI Narrative Shift" / "US_TREASURY Attention Spike" / "XI_JINPING" 标题 | Signal.title 由 `{entity_id} {kind}` 模板拼接，EntityRegistry.canonical_name 未进入展示层 |
| P2 | **指标当结论** | "叙事框架分布发生迁移（JSD 0.53）"作为 what_changed 正文；conf 0.40/0.93 裸露 | Signal 卡文案是检测器模板句，无解释层；confidence 未分档 |
| P3 | **Signal/Event 混淆** | Attention Spike 是统计量却被当作"变化"与事件并列；narrative_shift 直接指向事件列表 | 无 subject_type 语义层（signal 的主体可以是 entity/event/topic） |
| P4 | **无 Narrative 对象** | 五框架（gain/loss/…）只是标注维度；"收益 26→457 篇"是计数不是叙事 | 缺语义层：没人回答"人们开始相信什么" |
| P5 | **无 Insight 对象** | what_changed/why_it_matters 是模板句非智能陈述；无 what_to_watch_next | 缺最高层综合：observation→interpretation→alternative→watch next |
| P6 | **Event 无状态语义** | 所有事件平等罗列，无 confirmed/contested/developing/unverified | 事件=文章聚类，无 primary source 佐证推导 |
| P7 | **证据无强度分档** | evidence_ids 是裸列表；n=1 与 n=15 展示相同 | 无 Evidence Strength（Strong/Moderate/Limited/Insufficient）评级 |
| P8 | **证据重复映射** | narrative_shift 信号的 evidence 挂 58 个事件（全部实体的事件集合） | detect_narrative_shifts 把实体全部事件塞进 evidence_ids，无 provenance 追溯 |
| P9 | **排名只看统计量级** | strength=z*18/JSD*130 线性映射 | 无 Intelligence Score（Importance×Novelty×Evidence×Persistence×Impact） |
| P10 | **时间轴不可解释** | 看板 §2 柱+线+markLine 无 hover 语义 | 图表缺情报注释层 |

### 0.3 不变的边界

- 措辞纪律：NDI 仍是内部指标，升格条件不变；对外语言 = 分歧分档（divergenceLevel 已实现，保留）。
- 弃权语义：样本门/证据不足时 abstain，不硬凑——升级为「Insufficient Evidence」一等公民状态。
- 单进程 + SQLite WAL + 无 Redis：不变。
- 离线降级：无 keys 时全部新管道走确定性模板（与现有 offline artifact 同构）。

---

## A. 产品架构（Conceptual Model）

```
┌────────────────────────────────────────────────────────────┐
│                    RESEARCH MEMORY (Archive)                │
│        library / decisions / watch 快照 / 研究报告           │
└──────────────────────────▲─────────────────────────────────┘
                           │ investigates
┌──────────────────────────┴─────────────────────────────────┐
│              INSIGHT — 「这对用户意味着什么」                  │
│   observation → interpretation → evidence_strength →        │
│   alternative → what_to_watch_next                          │
└──────────────────────────▲─────────────────────────────────┘
                           │ synthesizes
┌──────────────────────────┴─────────────────────────────────┐
│              NARRATIVE — 「人们开始相信什么」                  │
│   statement / momentum / supporting vs opposing evidence /  │
│   source_clusters / divergence                              │
└──────────────────────────▲─────────────────────────────────┘
                           │ interprets
┌──────────────────────────┴─────────────────────────────────┐
│              SIGNAL — 「什么变了（统计可检）」                 │
│   四类检测器 + subject_type + magnitude/confidence/          │
│   novelty/persistence + Intelligence Score 排名             │
└──────────────────────────▲─────────────────────────────────┘
                           │ triggered_by
┌──────────────────────────┴─────────────────────────────────┐
│              EVENT — 「发生了什么」                           │
│   status: confirmed/contested/developing/unverified         │
│   primary vs secondary sources / timeline / confidence      │
└──────────────────────────▲─────────────────────────────────┘
                           │ supports
┌──────────────────────────┴─────────────────────────────────┐
│        EVIDENCE / INFORMATION — 「原始信息即证据」             │
│   InformationItem（Bronze）+ provenance 追溯 + 强度分档       │
└──────────────────────────▲─────────────────────────────────┘
                           │ publishes / mentions
┌──────────────────────────┴─────────────────────────────────┐
│        SOURCE + ENTITY — 「谁在说 / 说的是谁」                │
│   61 源 metadata / 18 实体 canonical_name（永不泄漏 ID）      │
└────────────────────────────────────────────────────────────┘
```

**各层职责一句话**：
- Source：信息从哪来（含可信度画像，绝不平等对待）。
- InformationItem：原子证据（用户只在核查时接触）。
- Entity：世界中的持久对象（canonical_name 显示，ID 永不出现在 UI）。
- Event：发生了什么（带验证状态与时间线）。
- Signal：什么变了（统计可检的变化，≠事件）。
- Narrative：人们开始相信什么（语义陈述，非框架计数）。
- Insight：这对用户意味着什么（观察→解释→备择→下一步）。
- Research Memory：研究与判断的沉淀（可回溯可引用）。

---

## B. 信息架构（IA）

### 主导航六页（保留路由，内容重构）

| 页 | 回答的问题 | 重构要点 |
|---|---|---|
| 01 INTELLIGENCE `/` | 今天世界有什么值得我注意的变化？ | 五段智能卡结构（见 E） |
| 02 SIGNALS `/today` + `/signals/[id]` | 具体什么变了？变化意味着什么？ | Signal 独立解释页（见 F） |
| 03 EVENTS `/events` + `/events/[id]` | 发生了什么？谁在怎么说？ | 八段式（见 F） |
| 04 WATCHLIST `/watch` | 我关心的对象最近有什么变化？ | Your World：对象级智能摘要（非"平静"二字） |
| 05 RESEARCH `/research` | 为什么？竞争解释是什么？ | 十步分析工作流 + 结构化报告（见 G） |
| 06 ARCHIVE `/library` | 我研究过什么？当时怎么判断的？ | 保留 + Insight/Narrative 存档类型 |

### 后台路由保留

/command（大屏）、/analyze（光谱工作台）、/intel（巡逻）、/timeline、/alerts、/decisions、/chat、/agent、/dev/monitor——全部保留，作为 Advanced Mode 入口。

---

## C. 核心数据模型（oh-contracts 新增）

```python
# —— 已存在并保留 ——
Source(SourceMeta)      # +display_name; source_type/institution/country/credibility_profile
InformationItem(BronzeRecord)  # 不变
Entity(EntityRegistry)  # +display_name 别名表（前端唯一合法名称来源）
Signal(contracts.signals.Signal)  # +subject_type(entity|event|topic|narrative)
                                  # +novelty_score/persistence_score/baseline/current_value

# —— 新增 ——
class EventStatus(StrEnum):
    confirmed = "confirmed"        # ≥1 L1 primary + ≥3 独立源
    contested = "contested"        # primary 之间立场冲突（官方簇 JSD 高）
    developing = "developing"      # 多源报道但无 primary 佐证
    unverified = "unverified"      # 样本不足（默认保守态）

class EvidenceStrength(StrEnum):
    strong = "strong"              # ≥2 L1 或 ≥5 独立源跨 ≥3 tier
    moderate = "moderate"          # ≥3 独立源跨 ≥2 tier
    limited = "limited"            # 2 源或单一 tier
    insufficient = "insufficient"  # <2 源（= 弃权语义）

class Evidence(BaseModel):
    item_key            # provenance 锚点（Bronze 幂等主键）
    source_id; tier; quote; published_at
    role: Literal["primary","secondary","commentary","social"]

class NarrativeStatement(BaseModel):     # 语义叙事对象
    id; statement            # "The Fed is approaching a rate-cutting cycle…"
    entity_ids; event_ids
    supporting_item_keys; opposing_item_keys
    source_cluster           # L1/L3/L4 等来源簇
    momentum: Literal["rising","steady","fading"]
    confidence; divergence   # 该叙事内部 vs 跨簇
    first_seen; window

class Insight(BaseModel):                # 最高层输出（五段强制）
    id; headline
    observation              # 什么变了（事实层）
    interpretation           # 这意味着什么（解释层）
    evidence_strength        # Strong/Moderate/Limited/Insufficient
    alternative_explanations # 备择解释（强制 ≥1，离线模板也给）
    what_changed; why_it_matters; what_to_watch_next
    related_signal_ids; related_event_ids; related_narrative_ids
    engine: Literal["llm","offline"]; generated_at
```

**Event 增强**：status / confidence / primary_sources / secondary_sources / timeline（按日文章重排）。
**Intelligence Score**（见 H）取代 strength 作为首页排名。

---

## D. 系统管道（新增环节加粗）

```
Ingestion (SourceAdapter, 不变)
→ Normalization (Bronze, 不变)
→ Entity Resolution (EntityRegistry, 不变)
→ Event Detection (EventBuilder, 不变) → **Event Status 推导**（新增，纯规则）
→ Signal Detection (detect.py, 不变) → **Signal 增强**（subject_type/novelty/persistence，纯规则）
→ **Narrative Modeling**（新增：LLM 从 stance+原文抽 NarrativeStatement；离线=从主导框架+源簇生成模板叙事）
→ **Insight Generation**（新增：LLM/模板合成五段；输入=Signal+Event+Narrative+evidence）
→ Research Agent (chat_graph+orchestrator, 保留) → **十步工作流编排**（prompt 结构升级）
→ Archive (library+decisions, 不变)
```

**Narrative Builder 设计**（关键新增）：
- 输入：某实体近窗 stance 行 + 高置信句级光谱 + 源簇划分。
- LLM 路径（strategic tier）：抽取 1-3 条叙事陈述（statement/momentum/evidence 挂 item_key）。
- 离线路径：`{主导框架迁移方向} + {源簇} + {ΔNDI}` 的确定性模板句，诚实标注 engine=offline。
- 幂等：narrative_id = `nar-{entity}-{window}`。
- 弃权：stance 行 < 样本门 → 不产 Narrative（不硬凑）。

**Insight Generator 设计**：
- 输入：Intelligence Score Top-N 的 Signal + 其关联 Event/Narrative。
- 输出：五段 Insight（LLM strategic / 离线模板）。
- 复用 AnalysisArtifact 五层契约（Observation→Interpretation→Evidence→Alternative→Uncertainty），Insight 是其 UI 化升级。
- 每日批量生成一次（run_daily 末尾）+ 惰性按需（首页请求时 missing 则现场生成并缓存）。

---

## E. 首页线框（Homepage Wireframe）

```
┌──────────────────────────────────────────────────────────────┐
│ MASTHEAD: Non-commercial research edition | OH!News | NAV 六页 │
│ NDI = EPU 式条件变量，非收益预测器（保留）                       │
├──────────────────────────────────────────────────────────────┤
│ Today's Intelligence · 2026-08-30                             │
│ 系统从 N 个变化中识别出 3 项值得注意的动态                       │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ 01  Narrative Shift · OpenAI                              │ │
│ │ 围绕 OpenAI 的报道正从扩张叙事转向竞争压力                   │ │
│ │                                                          │ │
│ │ Why this matters: 转移主要发生在二手财媒集群，              │ │
│ │ 尚未出现在官方沟通中——官方沉默本身是信息。                   │ │
│ │                                                          │ │
│ │ Evidence: Moderate  ▮▮▮▯                                │ │
│ │ What changed: 叙事框架显著迁移（内部 JSD 0.53，折叠）       │ │
│ │ Watch next: 官方声明或一手证据是否确认竞争担忧              │ │
│ │                                                          │ │
│ │ [ Explore Intelligence → ]  [ 存入档案 ]                  │ │
│ └──────────────────────────────────────────────────────────┘ │
│ （×3–5 张：Intelligence Score 排名；无 LLM 时离线五段照样完整）  │
├──────────────────────────────────────────────────────────────┤
│ §2 What is changing? — 可解释时间轴                           │
│ [ECharts: 柱=注意力 | 线=分歧 | 事件标记]                       │
│ hover → 「8/27 注意力↑ 3.2σ。分歧同步上升。                    │
│          主要驱动：二手财媒集群。关联事件：美加贸易谈判。」        │
│ （悬停注释由后端生成，非前端拼字符串）                           │
├──────────────────────────────────────────────────────────────┤
│ §3 Emerging Narratives — 人们开始相信什么                      │
│ ┌ 「降息预期正在聚集」  momentum ↑                            │ │
│ │   来源：市场评论 + 财媒   Evidence: Moderate               │ │
│ ├ 「通胀粘性制约宽松空间」 momentum →                         │ │
│ │   来源：官方机构沟通     Evidence: Strong                 │ │
│ └ （每条可展开 supporting/opposing evidence 抽样）             │
├──────────────────────────────────────────────────────────────┤
│ §4 Developing Events                                         │
│ ● Developing  美加贸易紧张升级                                 │
│   What happened: 新关税措施引发加方强烈回应。                   │
│   Narrative state: 分歧初现。 Evidence: 5 独立源/2 primary。   │
│   [ Explore Event → ]                                        │
├───────────────────────────────┬──────────────────────────────┤
│ §5 Your World（左 8 栏延伸）    │ §6 Research Questions        │
│ Federal Reserve               │ 「为什么市场预期降息而官方     │
│  无结构性变化；但降息预期的      │  沟通保持谨慎？」              │
│  关注度在上升。                 │ [ 开始研究 → ]                │
│ AI Industry                   │ 预设三问（保留现有）           │
│  叙事分歧上升：                │                              │
│  「AI 投资热潮」vs「变现压力」   │                              │
└───────────────────────────────┴──────────────────────────────┘
```

---

## F. Event 页八段 + Signal 解释页线框

### Event 页（/events/[id]）

```
标题（canonical 实体名）  ● Developing   Confidence: Moderate
Last updated: 2 小时前   [3 独立源 · 1 primary]

01 What happened — 简洁事实陈述，无推测
02 Timeline — 时序重构（按日文章聚合）：
   8/23 初步报道 → 8/24 官方回应 → 8/26 政策反应 → 8/28 分歧显现
03 What people are saying — 叙事簇：
   叙事 A「结构性恶化」(市场评论, momentum ↑, 3 证据)
   叙事 B「暂时性调整」(官方沟通, momentum →, 2 证据)
04 Where they disagree — 分歧性质区分：事实 / 解释 / 预测 / 归因
   （现状只有立场对立表 → 升级为四类分歧标签）
05 Evidence — Primary / Secondary / Commentary / Social 四层（保留现有，加 role 标注）
06 Narrative Map — 簇距离（保留，收进 Advanced 折叠）
07 Intelligence Assessment — 系统综合：
   Observation → Interpretation → Confidence → Alternative → What to watch next
   （= Insight 对象的 Event 视图，与首页卡片同源）
08 Ask the analyst — 预设问题（保留）
```

### Signal 解释页（/signals/[id] 新增）

```
Attention Surge — Federal Reserve（显示名）
Detected: 8/28   Evidence Strength: Moderate

What changed?  报道量为基线 4.1 倍（4.1σ）。
Why?           增量集中于：降息猜测 / 通胀数据 / 央行沟通。
Is it meaningful?  Persistence: Moderate（连续 3 天）  Novelty: High
Related Events:  ev-fed-20260827 →（显示标题非 ID）
Related Narratives: 「降息预期聚集」/「通胀粘性」
Advanced 折叠：baseline 23 篇/日 → current 94；z=4.1；JSD …
```

---

## G. Research Agent 十步工作流

```
1 Parse Question → 2 Identify Entities → 3 Retrieve Events
→ 4 Retrieve Signals → 5 Retrieve Narratives → 6 Generate Hypotheses
→ 7 Search Evidence → 8 Evaluate Evidence Quality → 9 Compare Explanations
→ 10 Produce Assessment
```

**报告结构（升级现有 StructuredResearch 九段）**：
Executive Answer / What changed / Competing explanations（Hypo A/B/C 各带 Evidence）/ Most likely explanation + reasoning / Confidence（Strong/Moderate/Limited）/ **What would change our mind（可证伪条件，强制字段）** / What to watch next / Sources & Evidence（全部可回溯 item_key）。

实现：orchestrator.run_intent 已有 ContextPacket+五层 Artifact；新增 chat_graph 工具 `get_narratives`/`get_insights`；prompt 模板按十步重排；LLM 缺席时离线路径生成确定性报告（每步标注 engine）。

---

## H. Intelligence Score 排名算法

**不盲乘的理由**：五因子中 Evidence=0 的语义是「弃权」而非「0 分」；线性乘法会让单零因子湮灭其他维度的信号，且量纲不可比。

设计：**加权线和 + 证据门禁（乘性封顶）**：

```
IS = 100 × ( 0.30·Imp + 0.20·Nov + 0.25·Ev + 0.15·Per + 0.10·Imp ) × G(Ev)

Imp(ortance)  = 实体 importance（央行 1.0 / 政府 0.9 / 系统性公司 0.7 / 其他 0.5）
                × 事件源覆盖（min(n_sources/8, 1)）
Nov(elty)     = 首次检出=1.0；重复检出按窗口衰减 exp(-Δdays/7)
Ev(idence)    = Strong 1.0 / Moderate 0.7 / Limited 0.4 / Insufficient 0.0
Per(sistence) = min(连续检出天数/5, 1)
Impact        = 0.5 + 0.5·ΔT_norm（温差代表官方-市场认知差，影响潜力代理）

G(Ev) = Ev==Insufficient ? 0.4（封顶 40 分） : 1.0   # 弃权不消失，降权不湮灭
```

权重总和=1，各因子∈[0,1]，IS∈[0,40]∪(40,100] 两段语义清晰：40 以下是「有变化但证据不足」区。首页只展示 IS≥40 的 Top 3-5；全部不足时首页诚实显示「今日无高置信变化」（这是产品承诺的一部分）。

---

## I. 迁移计划（增量，不重写）

### M1 本体契约层（oh-contracts）
`narrative.py`（NarrativeStatement/EventStatus/EvidenceStrength/Evidence/Insight）+ signals.py 扩展（subject_type/novelty/persistence/baseline/current_value）+ ranking.py（IntelligenceScore 纯函数）+ purity 测试。

### M2 情报管道（oh-pipeline + oh-agents）
- `pipeline/event_status.py`：confirmed/contested/developing/unverified 推导（纯规则，读 stance+bronze）。
- `pipeline/evidence.py`：EvidenceStrength 评级 + role 标注（primary=L1 tier 等）。
- `pipeline/ranking.py`：IS 计算（消费 detect 输出）。
- `agents/narrative_builder.py`：LLM+离线双路径 NarrativeStatement。
- `agents/insight_generator.py`：五段 Insight（复用 orchestrator offline 模板 + LLM 路径）。
- run_daily 编排：事件→信号→**叙事→洞察→落库**。

### M3 存储（oh-storage）
sqlite 新表 `narratives` / `insights`（单库单写者模式照旧）；events 查询输出补 status/confidence；EntityRegistry display_name 暴露。

### M4 API（oh-api）
`GET /api/graph?subject={entity}` 图遍历（entity→events→signals→narratives→insights→sources）；`GET /api/narratives?days=`；`GET /api/insights?date=`；`GET /api/signals/{id}`（解释层数据）；events/today 输出加 IS/status/evidence_strength；**全部文本字段输出 display_name**。

### M5 前端（web）
- 首页五段重构（Intelligence 卡/可解释时间轴/Emerging Narratives/Developing Events/Your World+Research Questions）。
- Event 页八段（+Timeline/Intelligence Assessment/分歧性质四类）。
- Signal 解释页 /signals/[id]。
- Evidence Strength 徽章组件（替换裸 conf；Advanced 折叠保留数值）。
- **内部 ID 消灭**：所有 entity 显示走 display_name。
- Your World：watch 快照渲染升级为对象级智能摘要。

### M6（可选 P2）信息图谱可视化
/api/graph 已就绪后，/graph 页 ECharts graph 视图（复用 /command force 组件）。

### 保留不动的
路由结构 / ECharts 基建 / watch 三类订阅 / library / decisions / chat / intel / alerts / timeline / analyze 光谱 / command 大屏（数据源切换后自动受益）。

### 技术债登记
1. detect_narrative_shifts 的 evidence_ids 全事件集合问题（P8）——M2 修为 provenance item_key。
2. Signal.title 模板拼接（P1）——M4 输出层重写，检测器内部 id 保留。
3. insight 惰性生成与 run_daily 批量的双写路径——M2 统一由 run_daily 优先，惰性只补洞。
