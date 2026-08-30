# REFACTOR_V2 — Intelligence Platform 系统性重构规划 v1

> 状态：PROPOSAL（待确认后实施）
> 真源链：BLUEPRINT.md（架构）→ RECONSTRUCTION.md v4（数据模型/管道）→ 本文（产品重构）
> 审查基线：commit cab1a49（M2 完成）· 数据实测 2026-08-31
> 定位：**Agent-Native Intelligence OS** — Research Terminal × Editorial Intelligence × AI Agent

---

## §0 Current Architecture Audit（Phase 1）

### 0.1 后端资产（强项：纪律与契约）

| 层 | 现状 | 评估 |
|---|---|---|
| oh-contracts | M1 五对象（Signal/EventAssessment/NarrativeStatement/Insight/EvidenceItem）+ Intent/Artifact/IntelReport/ICD203 | **完整且 purity 强制**；缺 Emotion/Claim 生产/SRL 论元/KG 边类型/Embedding 契约 |
| oh-pipeline | svo（6 域×13 方向动作词典）、spectra（句级框架）、divergence（NDI+CI+温度差）、detect（四检测器+IS）、anatomy、events（实体×UTC日）、evidence/event_status（M2） | 统计层扎实；**SRL 仅主语+动作两类论元**；事件=实体×日桶（无语义聚类） |
| oh-agents | M2 intel_pipeline 四层（评估/信号/叙事/洞察）+ orchestrator/research/chat/intel 六角色/watch/library/alerts | **M2 对象可离线产出但零 API 暴露** |
| oh-api | 40 端点 + SSE 总线 | 覆盖全；缺 intel/daily、entity profile、KG 查询 |
| oh-storage | silver（4 表）+ bronze parquet（12879 行/50 源）+ intel/watch/library/alerts/chat/decisions | intel.sqlite **network 恒空**（事件单实体，共现不成立） |
| oh-llm | 三 Tier 路由（io/execute/strategic）+ json_mode 策略 + 委员会 | 可用；deepseek 固定 json_mode |

### 0.2 数据现实（决定重构节奏的硬约束）

- bronze **12,879 行**（gdelt 占 79%）；stance **1,573 行**；事件 **61 个**（全部单实体×日窗）
- stance 分布：neutral 83% 主导；frame=conflict/gain/loss
- NDI 弃权率 **64%**（官方簇样本门 N_s≥10 难满足）
- library/decisions/alerts 均空库；intel 报告 4 份全 offline、图为空

**推论**：任何依赖大语料 LLM 标注的能力（Emotion 双层、SRL 论元、Embedding）必须**分两步**——先离线词典层（确定性、PIT 安全、可测试），后 LLM 增强层（增量、可断点续跑）。否则 12k 文档 × LLM 在当前管道下不可持续。

### 0.3 前端现状（19 路由 / 6 导航）

- Next 16 + React 19 + Tailwind 4 + ECharts 6，全客户端组件、无全局状态库
- lib/api.ts 390 行：37 方法 + 20+ 手写类型（无 zod 运行时校验）
- 三套 ECharts 封装并存；FRAME 色板/词表 3-4 处重复定义
- eslint 24 问题（15 error：13 处 set-state-in-effect 反模式）；前端零测试
- `/command` 硬编码 GitHub-Dark 暗色，与报纸风全站割裂

### 0.4 十大断点（Trust-Breaking 清单，按严重度）

| # | 断点 | 位置 | 影响 |
|---|---|---|---|
| 1 | **Signal.evidence_ids 双语义**（item_key vs event_id），前端一律当 event_id 调 evidence 接口 | detect.py:177 / today:70 | narrative_shift 证据预览必然 404 |
| 2 | 首页 markLine「点击下钻」`silent:true` 假交互 | page.tsx:308 | 用户信任损害 |
| 3 | 事件详情 NDI 混语言（all+en 交错无标识） | events/[id]:82 | 数值口径漂移 |
| 4 | M2 四层对象零 API 暴露 | — | 前端只能消费统计层，语义层闲置 |
| 5 | KG 恒空（事件单实体建模） | events.py:51 | intel 页力导向图从不出现 |
| 6 | window.location.href 整页刷新 ×4 处 | page/timeline | SPA 体验断裂 |
| 7 | 事件详情拉全量 60 天列表 .find(id) | events/[id]:55 | O(n) 请求无单事件端点 |
| 8 | detail 页语言优先级覆盖用户选择 | app.py:317 | timeline 断点 |
| 9 | research confidence 类型漂移（string vs float） | api.ts:336 | 契约不符 |
| 10 | 13 处 set-state-in-effect + 无竞态处理 | 多页 | React 19 性能/一致性 |

### 0.5 现有信息架构 vs 目标

当前 6 导航页基本对应 prompt 的 01-06（INTELLIGENCE/SIGNALS/EVENTS/WATCHLIST/RESEARCH/ARCHIVE），**IA 骨架成立**；问题在深度而非广度：图不联动、语义层缺位、Agent 无 Research Pipeline 可视化、无 Entity Profile、无 Raw Data Explorer。

---

## §1 Product Refactoring Plan（Phase 2 总览）

### 1.1 重构原则（承 prompt，落地为可验证规则）

1. **Signal over Noise**：主对象=Signal/Event/Narrative/Entity/Change；新闻只是 Evidence。→ 首页禁止原始新闻列表，一切展示经检测器/IS 排序。
2. **Progressive Disclosure 五层**：Overview → Anomaly → Relation → Evidence → Research。→ 每个视图标注层级，下钻路径显式可追踪。
3. **Everything Explorable**：Entity/Event/Narrative/Source/Emotion/Metric 全部可点击 → side panel 或 filter。→ 验收：首页任一视觉元素 3 次点击内到达 Raw Evidence。
4. **每图必答一问**：图表标题=问题，副标题=指标定义，交互=钻取动作。→ 组件 API 强制 `question` prop。
5. **诚实弃权**：数据不足显示 Insufficient Evidence 及原因（源数/多样性/确认度），不制造假信号。→ 承现有 abstain 纪律，前端统一 `<InsufficientEvidence reason/>` 组件。

### 1.2 不做什么（边界声明）

- 不引入向量数据库（数据规模 12k 文档不需要；Embedding 用按需 API/local 方案）
- 不做实时流处理（现有 T+1 PIT 批管道是产品语义的一部分——「情报」不是「快讯」）
- 不推翻 Next 16/React 19/Tailwind 4/ECharts 栈，不引入重状态库（FilterContext 用 React Context + URL state 足够）
- 不做登录/多租户（单用户研究终端）

---

## §2 Information Architecture

### 2.1 导航收敛：6 主导航 + 3 工具页

```
01 INTELLIGENCE  /        全局势能层（8 层 Dashboard，见 §5）
02 SIGNALS       /signals 检测工作台（原 /today，增强过滤/排序/降钻）
03 EVENTS        /events  事件情报系统（列表 → [id] 七段式 v2）
04 ENTITIES      /entities 实体档案（新增；替代散落的 timeline 入口）
   └ /entities/[id]        Entity Profile
05 RESEARCH      /research Agent 研究工作台（三栏 Canvas）
06 ARCHIVE       /library 研究知识库（原 /library 增强）

工具页（导航不放主栏，顶部 utility 区）：
/watch（订阅管理）· /alerts（预警）· /decisions（决策日志）· /command（暗色指挥舱，保留但 token 化）
/intel（情报巡逻）并入 INTELLIGENCE 的 System Alerts 层 · /brief 并入 INTELLIGENCE
/agent 并入 /research（双入口合一）· /analyze 并入 /events/[id]（七段式已覆盖解剖视图）
/timeline 并入 /entities/[id]（实体档案含时间轴）
```

**路由收敛：19 → 6 主 + 6 工具**，消除 agent/research、analyze/events、intel/intelligence 三组功能重叠。

### 2.2 钻取链（Global → Raw Evidence）

```
INTELLIGENCE（局能）
  → 任一对象点击 = 设为全局 Filter
  → SIGNALS（异常检测）→ Signal Breakdown（五因子）
  → EVENT（七段式：发生了什么→谁异议→证据→原始文）
  → ENTITY（档案：关注度/叙事/情绪/关系时间轴）
  → RELATION（KG 边详情：共现/施动/反对，时间对比）
  → EVIDENCE（句级光谱 + 语义标注高亮）
  → RAW DOCUMENT（原文 + Annotation Layer Toggle）
```

### 2.3 三种页面模板

- **Dashboard 模板**（INTELLIGENCE/SIGNALS）：Grid 12 栏 + 全局 Filter Bar + 层叠 section
- **Detail 模板**（EVENTS/ENTITIES）：主栏叙事流 + 右侧 side panel（相关对象/证据/Agent）
- **Workspace 模板**（RESEARCH）：三栏 Canvas（历史 | 对话+结构化输出 | 上下文）

---

## §3 Unified Data Model（Phase 3）

### 3.1 契约新增（oh-contracts，保持零依赖零 IO）

```python
# semantics.py（新增）
class EmotionLabel(StrEnum):  # 8 类，词典 v1 + LLM v2 共用
    fear anger optimism uncertainty confidence urgency concern relief

class EmotionVector(_Strict):          # 双层情绪（prompt §10）
    expressed: dict[EmotionLabel, float]   # 文本表达
    audience: dict[EmotionLabel, float]    # 预期读者效应
    intensity: float                       # [0,1]
    confidence: float
    engine: Literal["lexicon", "llm", "offline"]

class SemanticRole(_Strict):           # SRL 论元（扩展 svo 现状）
    subject: str | None
    action: str | None                     # taxonomy 词
    object: str | None                     # v1: 宾语 NP 启发式
    target: str | None                     # 间接受事（实体命中）
    time: str | None                       # 时间表达式
    location: str | None
    causality: str | None                  # v2 LLM
    engine: Literal["lexicon", "llm", "offline"]

class SemanticAnnotation(_Strict):     # 文档级标注容器（Raw Data Explorer 的数据面）
    item_key: str
    roles: list[SemanticRole]
    actions: list[ActionMention]           # {verb, direction, strength, certainty}
    emotions: EmotionVector | None
    claims: list[Claim]                    # 复用 schemas.Claim，开始生产
    frame_dist: dict[FrameLabel, float]
    event_candidates: list[str]
    embedding: list[float] | None          # 可空，见 §4.5

class EntityEdge(_Strict):             # KG 边类型化（cartographer v2）
    src: str; dst: str
    kind: Literal["co_occurs","acts_on","opposes","supports","regulates",
                  "responds_to","mentions","competes_with","parent_of"]
    weight: float
    first_seen: datetime; last_seen: datetime
    evidence_item_keys: list[str]          # 边可溯源
```

### 3.2 存储扩展（oh-storage）

- silver 新表 `annotations(item_key PK, payload JSON, engine, annotated_at)`（幂等 upsert）
- silver 新表 `entity_edges(edge_key PK, src, dst, kind, weight, first_seen, last_seen, evidence JSON)`
- 事件聚类 v2：`events` 增 `cluster_key` 列（多实体事件合并），保留 `ev-{entity}-{date}` 为成员 id，簇 id=`evt-{hash8}`；**破坏性变更**——需要一次性迁移脚本 + 测试夹具同步
- bronze 不动（immutable 分区原则）

### 3.3 数据流全景

```
Bronze → Clean/Normalize → SemanticAnnotation(词典 v1 → LLM v2 增量)
      → Event Cluster v2（实体×日 → 语义簇）
      → Stance/Silver → NDI/Divergence → Detect+IS（现有）
      → EventAssessment/Narrative/Insight（现有 M2）
      → EntityEdge（KG v2）→ Signal/Alert → API → Visualization
```

---

## §4 Semantic Intelligence Pipeline（Phase 3 实施）

分四级，每级独立可测、可降级、PIT 安全（标注只用 t-1 信息；LLM 标注附 `annotated_at` 供审计）。

| 级 | 能力 | 方法 | 产出 | 落点 |
|---|---|---|---|---|
| **S1 词典层** | Action 提及+方向+强度；8 类情绪双层近似（表达=情绪词密度，读者效应=风险/不确定性触发词）；SRL 论元启发式（宾语=动词后 NP 命中实体/金融词表；时间=日期正则+介词模式；地点=城市/国家别名表） | 扩展 svo.py 词典 → 新 `semantics.py` | SemanticAnnotation(engine=lexicon) | annotations 表；Raw Data Explorer v1 |
| **S2 事件聚类 v2** | 同日跨实体合并：标题+首段 shingle(5) Jaccard ≥ τ + 时间近邻 + 实体重叠 | events.py v2 | 多实体 Event → KG 共现不再恒空 | events 表 cluster_key |
| **S3 KG v2** | 边类型化：SRO 主谓宾 → acts_on/opposes（stance 极性）/co_occurs；父子边；边证据链 | cartographer v2 + annotations | entity_edges 表；/api/graph | INTELLIGENCE Entity Network 层 |
| **S4 LLM 增强层** | 增量标注（只标 S1 低置信 + 新文档）：Emotion 精标、claim 抽取、causality、embedding（bge-small local ONNX 或 API，见开放问题） | oh-llm Tier=execute，json_mode，Semaphore(3)，断点续跑（annotated_at 水位） | engine=llm 标注 | Raw Explorer v2、Claim 面板 |

**成本核算（S4）**：新增文档 ~200-400/日 × 单标 <2k tok；deepseek-v4-flash 单文档成本可忽略；全量回填 12.8k 文档一次性可接受。S1 词典层先行保证 S4 故障时系统不空转。

---

## §5 Visualization Architecture（Phase 4）

### 5.1 八层 Dashboard（/，自上而下）

| Layer | 组件 | 回答的问题 | 数据源（现有/新增） | 交互 |
|---|---|---|---|---|
| L1 Situation Overview | StatusBand + KeyMetrics 行 | 信息环境今天什么状态？ | /api/intel/daily（新增，M2 四层聚合） | 指标点击=设 Filter |
| L2 Intelligence Radar | 雷达/多维矩阵 | 哪些维度异常？ | 四检测器计数 + IS 分布 | 维度点击过滤全页 |
| L3 Attention Heatmap | Entity×Day 热力 | 谁在异常升温？ | stances 按日聚合 | hover=基线对比人话；click=实体 Filter |
| L4 Narrative Shift Flow | Alluvial（前后窗框架迁移） | 叙事如何迁移？ | flow.frames（现有） | 流带点击=框架 Filter |
| L5 Event Momentum Timeline | 时间轴+事件标记+NDI 叠加 | 什么导致了变化？ | ndi_series+events | brush 选时段全局联动；点=Event Panel |
| L6 Entity Network | 力导图（KG v2） | 谁与谁相关？什么关系新出现？ | entity_edges（新增） | 时段对比高亮新增/消失边 |
| L7 Divergence Matrix | Source×Frame 热力 | 谁和谁分歧？ | anatomy cluster_pairs | 行点击=Source Intelligence |
| L8 Emotion Landscape | Stacked Area/Streamgraph | 信息环境情绪如何演化？ | annotations 聚合（新增） | expressed/audience 切换 |

右侧栏：Active Events / Watchlist 状态 / Ask the Analyst（常驻）。

### 5.2 全局联动（Chart Linking）

- `FilterContext`（React Context）：`{timeRange, entity, entityType, source, frame, emotion, signalKind, language}`，全部持久化到 URL query（可分享、可后退）
- 所有图表组件消费同一 context；点击任何图元 = setFilter；brush = setTimeRange
- 服务端过滤优先（API 加 filter 参数），前端只做高亮态

### 5.3 组件工程

- **唯一 ECharts 封装** `components/visualizations/chart-base.tsx`：统一主题注入（token→echarts theme）、ResizeObserver、空/加载/弃权三态、`question` prop 强制
- 每图必带：`question`（标题）、`metric`（副标题指标定义）、`onDrill`（钻取回调）、`insufficient`（弃权态渲染）

---

## §6 Interaction Architecture

| Pattern | 用途 | 落点 |
|---|---|---|
| Side Panel | 对象点击右展：摘要/指标/时间轴/相关/证据 | 全局 `<DetailPanel>`（路由感知） |
| Hover Intelligence | 数字+人话解释（「较基线上升 447%」） | insight.ts 扩展 |
| Brush Selection | 时间刷选全局过滤 | L5 时间轴 |
| Compare Mode | A vs B 实体/前后 7d | ENTITIES + L4/L8 |
| Focus Mode | 点击实体弱化其他 | L6 网络图 |
| Investigation Canvas | 多对象加入对比共同事件/分歧 | RESEARCH 上下文栏 |
| Insufficient Evidence | 弃权原因四类（源少/多样性低/未确认/语义置信低） | 全局组件 |

**断点修复（§0.4 #1-#10 全部纳入 R0/R1）**：markLine 可点、evidence_ids 语义统一（detect.py 统一为 item_key + 附 `evidence_kind` 字段，前端按 kind 路由）、NDI 语言标识、单事件端点 `GET /api/events/{id}` 等。

---

## §7 Agent Research Workspace（Phase 8）

### 7.1 Research Pipeline 可视化（真实步骤非 "Thinking..."）

`POST /api/agent/invoke` 增强：返回 `steps: [{phase, action, detail, duration_ms, status}]`，前端逐步渲染（SSE 推送，复用现有总线）：

```
✓ Identifying entities (fed, fomc, usd)
✓ Retrieving 23 related events (7d)
✓ Comparing official vs market narratives (JSD 0.61)
✓ Detecting contradictions (2 official cluster conflicts)
✓ Building event timeline (2026-08-02 → 08-29)
✓ Measuring narrative shift (loss→gain, ΔNDI +0.18)
✓ Evaluating evidence confidence (MODERATE, 5 sources, 2 primary)
```

### 7.2 Component-aware Output

Artifact 增 `ui_spec: [{component: "NarrativeFlow", data_ref, question}]`——后端按 Intent 决定组件序列，前端 `ComponentRegistry` 动态渲染。映射表（Intent → 组件链）在 orchestrator 维护，例：

- 时变类问题 → IntelligenceSummary + EventTimeline + TimeSeriesChart
- 关系类 → EntityGraph + RelationshipMap
- 分歧类 → DivergenceMatrix + SourceComparison + ContradictionPanel
- 比较类 → ComparisonTable + 双 MetricCard

### 7.3 三栏 Canvas

左：Research History（chat threads + saved questions）；中：对话 + 结构化输出（组件流渲染）；右：Research Context（可拖入 Entity/Event/Watch 对象 → 注入 ContextPacket）。

### 7.4 Evidence/Confidence 体系（Phase 9）

- 每个结论挂 Evidence Links（supporting/opposing 分组）；Fact/Inference/Hypothesis 三态视觉标识
- Confidence Breakdown：source_reliability/diversity/consistency/confirmation/semantic 五因子分解（复用 IS 因子与 EventAssessment 置信式）
- Signal Breakdown：Attention×Change×Novelty×Confidence×Persistence 条形分解（metrics 已有五因子）

---

## §8 Component Architecture（Phase 5-7 落点）

```
web/components/
  /intelligence    status-band, key-metrics, intelligence-radar, alert-strip
  /visualizations  chart-base, attention-heatmap, narrative-flow(alluvial),
                   event-timeline, entity-network, divergence-matrix,
                   emotion-landscape, signal-radar
  /signals         signal-card, signal-breakdown, signal-filters
  /events          event-summary, event-timeline-section, actor-map,
                   narrative-evolution, source-distribution
  /entities        entity-profile, entity-header, attention-trend,
                   narrative-trend, related-entities
  /research        research-canvas, pipeline-steps, component-registry,
                   context-panel
  /evidence        evidence-card, evidence-table, claim-card,
                   contradiction-panel, confidence-indicator, insufficient
  /raw-data        raw-explorer, annotation-toggle, annotated-text
  /ui              (shadcn 现有 + 补 dialog/dropdown/tabs/sheet/skeleton)
```

**Design Tokens（globals.css 扩展）**：Paper/Ink 基底保留报纸风；新增语义信号色 token：`--signal-attention`(amber)/`--signal-narrative`(purple)/`--signal-divergence`(rust)/`--signal-confirmed`(slate-green)/`--signal-warning`；Display=衬线（现有 Georgia/Songti 栈）、Data=mono、Body=sans；`.dark` 变体补全并支持切换（/command 归入 dark token，消除硬编码）。颜色永不单独编码信息（配形状/标签/图案）。

---

## §9 Implementation Roadmap

| Phase | 内容 | 交付物 | 验收 |
|---|---|---|---|
| **R0 信任修复**（1 天） | 断点 #1#2#3#6#7#9 + eslint error 清零 | detect.py evidence_kind、/api/events/{id}、前端修 | today 页证据预览全通；首页可点下钻 |
| **R1 语义层上 API**（1 天） | GET /api/intel/daily（M2 四层）、EventAssessment 接入事件详情 07 段 | intel_pipeline 接 app.py | 首页消费 NarrativeStatement/Insight |
| **M3-S1 词典语义层**（2 天） | semantics.py：Action/Emotion 双层/SRL 论元 v1 + annotations 表 + 管道接线 | SemanticAnnotation(lexicon) | 全量 12.8k 标注跑通，pytest 覆盖 |
| **M3-S2 事件聚类 v2**（1 天） | cluster_key 合并 + 迁移脚本 | 多实体事件 | KG 共现图非空 |
| **M3-S3 KG v2**（1-2 天） | entity_edges 表 + cartographer v2 + /api/graph | 类型化边 + 证据链 | intel 页网络图出现新边高亮 |
| **R5 前端地基**（2-3 天） | FilterContext + chart-base + tokens + /ui 补齐 + 路由收敛 19→12 + 组件迁移 | 重构骨架 | eslint 0；tsc 0；导航 6+6 |
| **R6 Dashboard v2**（3 天） | 八层 + 全局联动 | / 页 | 任一图元 3 击到 Raw Evidence |
| **R7 Event/Entity v2**（2 天） | 事件七段增强（Assessment/情绪/Actor Map）+ Entity Profile | /events/[id]、/entities/[id] | 详情含语义标注高亮 |
| **R8 Agent Canvas**（2-3 天） | steps 可视化 + ui_spec + 三栏 + SSE | /research | 组件流输出非长文 |
| **M3-S4 LLM 增强层**（2 天） | 增量标注水位线 + claim 生产 + embedding 决策落地 | engine=llm 标注 | 断点续跑验证 |
| **R9 Evidence/Confidence**（1-2 天） | 三态结论标识 + Confidence/Signal Breakdown | 全局 | 每结论可点开证据链 |
| **R10 打磨**（1-2 天） | Raw Explorer v2、Source Intelligence、响应式、可访问性、性能（虚拟化按需） | — | 10 秒五问（§40 标准） |

**顺序依据**：信任修复 → 数据真实化（语义层）→ 地基 → 展示 → 智能 → 打磨；每 Phase 独立可交付、测试先行、conventional commits（scope=包名/模块单独 commit）。

---

## §10 开放问题（需用户裁决）

1. **事件聚类破坏性变更**：event_id 语义从 `ev-{entity}-{date}` 变为簇 id，历史 silver 数据需迁移（脚本 + 测试夹具）。接受？
2. **Embedding 方案**：a) 本地 bge-small ONNX（离线、无 API 成本、需装依赖）b) zhipu embedding API（简单、外部依赖）c) 推迟到 S4 后。建议 a。
3. **Emotion 双层词典 v1 的精度预期**：词典法 audience_emotion 是粗近似（承 NDI 地板效应教训），UI 需标注 engine=lexicon 置信说明。接受？
4. **/command 去留**：保留为独立暗色指挥舱（token 化）还是并入 INTELLIGENCE？建议保留（大屏场景独立价值）。
5. **主题默认**：亮（报纸）为默认、暗色可切？还是暗色为终端感默认？建议亮默认（编辑风定位）。
6. **R0-R2 是否先行 commit**：R0 修复独立于重构主线，建议先行小步 commit。
