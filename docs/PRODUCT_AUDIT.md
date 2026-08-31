# OH!News 产品体验审计（阶段 0 基线）

> 日期：2026-09-01 · 方法：真实浏览器走查（Playwright，桌面 1440 + 移动 390）+ 代码审查（web/ + packages/ 全量）+ API 实测。
> 纪律：审计 ≤15% 工作量，本文档是唯一审计产物；完成即进入阶段 1 纵向实现。

## 0. 一句话产品决策

OH!News 为**持续跟踪宏观/市场信息的个人研究者**服务：把「今天世界发生了什么变化」转成「可验证证据 → 用户自己的判断 → 长期追踪记忆」的闭环；不做预测器，不做 Dashboard 堆砌。

## 1. 数据新鲜度基线（硬验收 1/8 根源）

| 项 | 实测值 | 问题 |
|---|---|---|
| bronze 最新 published_at | 2026-08-30 08:15 UTC | 滞后 now ~40h |
| /api/today?top=3 | total=**1**（date=2026-08-31） | 窗口锚=now，真实数据下几乎恒空 |
| /api/events?days=7 | 63 条 | 单实体日桶噪音（见 §3.4） |
| /api/status | 76 events / 1573 stances / 12873 bronze / 68 NDI 点 | — |
| data_as_of 展示 | **所有页面均无** | 「数据截至何时」三问之三不成立 |

**结论**：新鲜度语义必须从「now-窗口」改为「数据实际覆盖（max published_at / ingest time）」，并在 UI 顶层展示 `data_as_of`。

## 2. 黄金路径走查实锤（2026-08-31 真实数据）

### 2.1 首页（三问检验）
- Q1 今天有什么变化：H1「系统发现 1 个值得关注的变化」✓（能答，但只有 1 个）
- Q2 为什么值得看：卡片裸露「JSD 0.43 / conf 0.33 / 强度 56/100」✗（硬验收 2：用户无需理解 NDI/JSD/stance/engine）
- Q3 数据截至何时：无任何展示 ✗（硬验收 8）

### 2.2 变化卡下钻（断裂实锤）
- 首页 today 卡未修 evidence_kind 双语义（R0 只修了 /today 页）：item_key 被当 event_id 拼进链接 → `/events/wallstreetcn:https://...:2026-08-29T01:45:22+00:00` → **HTTP 404 + 8 console errors + 错误文案暴露 URL 编码内部 ID**（硬验收 2/9 违规）。
- /today 页 item_key 语义卡无事件锚：只有引文 + Ask Analyst（href 塞 signal_id 内部值）。
- 事件详情 ev-fed-20260829：Evidence 引文**纯文本无原文外链**（/api/events/{id}/evidence 不含 url 字段）→ 黄金路径「Briefing→Change→Evidence→**原文**」最后一公里断裂（硬验收 3）。

### 2.3 移动 390px
- body scrollW=674 > viewport 375：nav 6+6 两行链接不折叠 → 横向溢出（硬验收 13 违规）。

### 2.4 单实体日桶噪音（M3-S2 已建簇但未消费）
- ev-fed-20260829 塞 63 篇：华见早报把英伟达财报/房贷政策混入 fed 事件。cluster_key 已迁移（76 行/58 簇/11 多实体）但 API/前端未消费。

### 2.5 好的部分（KEEP 依据）
- /today 卡 R0 修复生效：item_key 反查证据，中文引文正常显示。
- 事件详情评估卡（R1）：已证实·confirmed 徽章 + 14 信源 + 技术指标折叠展开——术语按需展开的方向正确。
- 弃权语义贯穿：NDI abstain / 样本门 / insufficient 在后端一致。
- ChartBase/FilterContext/tokens（R5）：地基可复用。

## 3. 四张清单与 KCD 决策

### 3.1 Route（收敛后 11 主/工具）
| Route | 决策 | 理由 |
|---|---|---|
| / | CHANGE | 阶段1 重做为 Briefing 页（3-5 变化卡 + data_as_of + 三问布局） |
| /today | DELETE（阶段1 后 redirect /） | 与首页同义入口（硬验收 9） |
| /events | KEEP | 事件列表；接入 cluster 消费 |
| /events/[id] | CHANGE | Dossier 化：Evidence Drawer（三桶+Gap）+ 原文外链 |
| /analyze /analyze/[id] | DEFER→DELETE | 功能并入 events/[id]（R7 后删，redirect） |
| /intel | KEEP | 情报巡逻工具页 |
| /brief | CHANGE | 与 /api/briefing 对齐，阶段1 Briefing 复用 |
| /timeline | KEEP | 实体叙事时间轴 |
| /watch | CHANGE | 阶段3 WatchUpdate 语义重做 |
| /alerts | CHANGE | 阶段3 触发条件与 Watch 融合 |
| /decisions | CHANGE | 阶段2 BeliefSnapshot 落点 |
| /library /research /dev/monitor | KEEP | — |
| /chat | DELETE→redirect /research | 同义入口（research 已含 ChatPanel） |
| /command /agent | DELETE（已完成） | 1c13f4e + redirects |

### 3.2 Component
| 组件 | 决策 |
|---|---|
| visualizations/chart-base.tsx | KEEP（唯一封装，R5） |
| filters/filter-context.tsx + filter-bar.tsx | KEEP（阶段1 时间/实体过滤复用） |
| lib/tokens.ts | KEEP（单一真源） |
| echart.tsx | DELETE（已删） |
| ChatPanel（chat/page.tsx 内） | CHANGE：抽到 components/（阶段4 消费） |
| IntentPanel / key-setup | DEFER（阶段4） |
| 首页私有 Chart/Panel 等 | DELETE（随 Briefing 重做） |

### 3.3 API
| 端点 | 决策 |
|---|---|
| GET /api/briefing（新） | NEW：有限 ChangeBrief 队列（data_as_of/新鲜度语义） |
| GET /api/changes/{id}（新） | NEW：ChangeDossier（含 EvidenceSet 三桶+EvidenceGap） |
| GET /api/changes/{id}/evidence?bucket=（新） | NEW：分桶证据（supporting/contradicting/context） |
| /api/today | CHANGE→DELETE：被 /api/briefing 替代 |
| /api/brief | KEEP（晨报文本，阶段1 复用） |
| /api/events | CHANGE：+url 字段（原文外链）+ cluster_key 消费 |
| /api/events/{id}/evidence | CHANGE：+url +bucket 分桶 |
| /api/evidence/by_keys | KEEP |
| /api/intel/* /api/graph | KEEP（M3 产出消费面） |
| /api/watches /api/library /api/decisions /api/alerts/* | KEEP（阶段2/3 扩展） |
| /api/chat /api/research /api/agent/invoke /api/keys /api/stream | KEEP（阶段4 嵌入） |

### 3.4 Contract（oh-contracts 新增/变更）
| 契约 | 阶段 | 语义 |
|---|---|---|
| DataFreshness | 1 | data_as_of + coverage（数据实际覆盖窗）+ staleness 分级 |
| ChangeBrief | 1 | 面向用户的「变化卡」：what/why_now/强度（人话）/锚定实体 |
| ChangeDossier | 1 | 变化详情包：headline/summary/status(人话)/EvidenceSet/CoverageSummary/SubjectRef[] |
| EvidenceItem(产品语义) | 1 | +url/title/source_tier（原文外链最后一公里） |
| EvidenceSet | 1 | supporting/contradicting/context 三桶 + EvidenceGap[] |
| CoverageSummary | 1 | 样本覆盖人话：n_sources/n_primary/时间跨度/缺口 |
| EvidenceGap | 1 | **缺失证据一等公民**（期望但未观测的来源/方向/时间），不得伪装为 EvidenceItem |
| SubjectRef | 1 | 实体/事件/簇的稳定引用（隐藏内部 ID） |
| BeliefSnapshot / WatchUpdate | 2/3 | 仅用户确认写入；「自上次快照以来」增量 |
| M3 S1-S3（semantics/cluster/KG） | KEEP | 停止扩建，仅消费 |

## 4. 基线行为快照（回归锚）

- /api/today 真实数据 total=1（narrative_shift，JSD 0.43）
- ev-fed-20260829：confirmed/strong，14 信源，NDI 中文语料可测
- bronze 12,873 标注 100% 覆盖（actions 8.2%）
- 图 28 边（co_occurs 22/acts_on 5/parent_of 1）
- eslint 0/0，tsc 0，后端 pytest 339 passed

## 5. 决策日志（防回潮）

1. **Dashboard 八层 = DELETE**（用户裁决）：违反「链路优先」原则，图表堆砌不缩短认知闭环。M3 基础设施保留为数据面。
2. **Research Canvas = CHANGE+DEFER**：Agent 增强排在阶段 4，且必须嵌入已成立的闭环。
3. **Entity Profile / Embedding = DEFER**：bge-small ONNX 推迟，当前词典层够用。
4. **M3 S1-S3 = KEEP 停扩建**：语义/聚类/KG 是资产，但消费面（API/前端）按阶段 1 需求暴露。
5. **前端类型真源 = FastAPI OpenAPI 生成 TS**：Pydantic 唯一契约真源，Zod 仅运行时边界校验。
6. **evidence_kind 双语义**：R0 已在契约显式化（item_key/event_id），阶段 1 的 EvidenceItem 产品语义消除该泄漏。
7. **新鲜度语义重构**：now-窗口 → 数据覆盖窗（DataFreshness），阶段 1 落地。
8. **R5 保留**：tokens/ChartBase/FilterContext 是阶段 1 的施工面。

## 6. 阶段 1 验收映射（硬验收 → 动作）

| 硬验收 | 阶段 1 动作 |
|---|---|
| 1 十秒三问 | Briefing 页 + data_as_of 顶层展示 |
| 2 无需内部术语 | ChangeBrief 人话字段（JSD/conf 不出契约） |
| 3 三次操作到原文 | 卡→Dossier→Evidence→url 外链（≤3 步） |
| 4 支持/反对/缺失 | EvidenceSet 三桶 + EvidenceGap |
| 7 五状态可区分 | no change/empty/insufficient/stale/error 状态机（ChartBase 四态延伸） |
| 8 日期一致 | DataFreshness 贯穿 API→UI |
| 9 无同义入口 | /today /chat redirect 清理 |
| 11 降级可用 | API 失败/LLM 未配/大量 abstain 的真实条件（本环境即真实条件） |
| 13 390px | nav 折叠 + Briefing 单列（走查已复现溢出） |
| 14 埋点 | 7 主路径事件（§阶段 1-e） |
