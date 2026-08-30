# OH!News M2 情报管道 — 会话交接（2026-08-30）

> 用途：旧会话因 glm-5.3-flash 空响应死循环作废，本文件用 deepseek 汇总旧上下文，供新会话（glm-5.3-flash）无缝续接 M2 实现。

## 0. 会话背景

- 称呼用户为 **Latte**。
- 任务起源：`新任务目标文件.md`（OrangeC_OH!News 目录）——在**忽略** `narrativeradar-plan/` 与 `narrativeradar-demo/` 两个旧文件夹的基础上，基于 git_proj 下其他项目（量化交易 / AI agent 框架）重新构思的项目蓝图。
- 技术栈以 langchain/langGraph/deepagent 为核心（agent 为主），模块化 + git 规范提交（conventional commits，scope=包名），跨平台兼容，低成本 + 免费信息源 + 规避反爬。
- 模型分工（用户要求）：低级=deepseek-v4-flash（基础 I/O/批量读/确定性输出）；中级=GLM-5.3-Flash（项目架构执行与编码）；高级=GLM-5.3 zhipuai（战略构思/最高复杂度）。

## 1. 项目现状（git 已确认）

- 仓库：`/Users/orangec/Desktop/AI/git_proj/OrangeC_OH!News/OHnews`，**工作区干净**（无未提交改动）。
- 已提交：
  - `ae0f421` docs(plan): v4 情报本体重构计划（Signal/Event/Narrative/Insight 四层本体 + M1-M5 迁移计划 + Intelligence Score）→ 即 `docs/RECONSTRUCTION.md`，**M2 设计真源**。
  - `3b94740` feat(contracts): **M1 本体契约层已完成**——oh-contracts 新增 `narrative.py`（NarrativeStatement/EventStatus/EvidenceStrength/Evidence/Insight）+ `signals.py` 扩展（subject_type/novelty/persistence/baseline/current_value）+ `ranking.py`（IntelligenceScore 纯函数，加权线和+证据门禁封顶 40）+ purity 测试。
- 架构真源：`docs/BLUEPRINT.md`；产品重构计划：`docs/RECONSTRUCTION.md`。

## 2. 本任务：M2 情报管道（oh-pipeline + oh-agents）

旧会话崩溃前（2026-08-30 18:24:14）的任务快照（in_progress 状态保留）：

1. **M2a** oh-pipeline `event_status.py`：EventStatus 推导 + EventAssessment（confirmed/contested/developing/unverified）— `in_progress`
2. **M2b** oh-pipeline `evidence.py`：EvidenceItem provenance + EvidenceStrength 分档（L1→primary/strong … L4→social/limited）
3. **M2c** oh-pipeline ranking 接线：IS 计算进 detect_signals + **P8 evidence_ids provenance 修复**
4. **M2d** oh-agents `narrative_builder`（statement/momentum/supporting-opposing，LLM+离线双路径）
5. **M2e** oh-agents `insight_generator`（五段强制 + alternative≥1）
6. **M2f** run_daily/run_pipeline 编排接线 + 测试 + QA + commit

### 设计要点（RECONSTRUCTION.md §C/D/H 摘要，实现前先读原文）

- **EventStatus**（默认保守态）：
  - `confirmed` = ≥1 L1 primary + ≥3 独立源
  - `contested` = primary 之间立场冲突（官方簇 JSD 高）
  - `developing` = 多源报道但无 primary 佐证
  - `unverified` = 样本不足
- **EvidenceStrength**：
  - `strong` = ≥2 L1 或 ≥5 独立源跨 ≥3 tier
  - `moderate` = ≥3 独立源跨 ≥2 tier
  - `limited` = 2 源或单一 tier
  - `insufficient` = <2 源（=弃权语义）
- **Evidence**：item_key（Bronze 幂等主键 provenance 锚点）/ source_id / tier / quote / published_at / role∈{primary,secondary,commentary,social}。
- **Intelligence Score**：`IS = 100 × (0.30·Imp + 0.20·Nov + 0.25·Ev + 0.15·Per + 0.10·Impact) × G(Ev)`；`G(Ev)=Insufficient?0.4(封顶40):1.0`；首页只展示 IS≥40 的 Top 3-5。已实现于 oh-contracts `ranking.py`（M2c 是接线消费）。
- **Narrative Builder**：输入=实体近窗 stance 行 + 高置信句级光谱 + 源簇。LLM 路径（strategic tier）抽 1-3 条；离线路径=`{主导框架迁移方向}+{源簇}+{ΔNDI}` 模板句，**engine=offline 诚实标注**。幂等：`nar-{entity}-{window}`；stance 行 < 样本门 → 弃权不硬凑。
- **Insight Generator**：输入=IS Top-N Signal + 关联 Event/Narrative；输出五段（observation/interpretation/evidence_strength/alternative_explanations/what_changed…，**alternative ≥1 强制，离线模板也给**）；engine∈{llm,offline}；run_daily 每日批量 + 首页惰性补洞（双写路径，M2 统一 run_daily 优先）。
- **管道顺序**：Ingestion→Bronze→Entity→Event Detection→**Event Status（纯规则）**→Signal Detection→**Signal 增强（subject_type/novelty/persistence 纯规则）**→**Narrative Modeling**→**Insight Generation**→Research Agent→Archive。

### 需要新建/接线的文件（当前不存在）

- `packages/oh-pipeline/src/oh_pipeline/event_status.py`（新建，纯规则，读 stance+bronze）
- `packages/oh-pipeline/src/oh_pipeline/evidence.py`（新建）
- `packages/oh-pipeline/src/oh_pipeline/ranking.py`（新建，消费 detect 输出）
- `packages/oh-agents/src/oh_agents/narrative_builder.py`、`insight_generator.py`（新建）
- `scripts/dev/run_daily.py` + `packages/oh-pipeline/src/oh_pipeline/run.py` 编排接线

### 旧会话崩溃前最后动作

- 已读完：`entities.py`（DEFAULT_ENTITIES 全量清单）、`run.py`、`run_daily.py`、`signals.py`（subject_type/novelty/persistence/baseline/current_value）、`ranking.py`，正准备开始写 `event_status.py`（M2a）。

### 技术债提醒（RECONSTRUCTION.md §I 技术债登记）

- **P8**：`detect_narrative_shifts` 的 evidence_ids 是全事件集合问题 → M2c 修为 provenance item_key。
- P1：Signal.title 模板拼接 → M4 输出层重写，检测器内部 id 保留（M2 不动）。

## 3. 工程守则（项目 AGENTS.md，必须遵守）

- 工具链：**uv workspace**（本仓库唯一 Python 工具链，不用 conda）。
- QA Gate：`uv run ruff check packages && uv run ruff format packages && uv run pytest -v`；`sensitive` marker 默认跳过；`sanity` = Phase 0 门禁。
- 结构：`packages/*` 单向依赖；oh-contracts 零内部依赖零 IO（purity 测试强制）。
- PIT 纪律：一切指标只用 t-1 及更早信息。
- 措辞：NDI = 叙事分歧指数（描述性监测）；禁用"预测器/择时"。
- 提交：conventional commits，scope = 包名，模块单独 commit（git commit/push 需用户确认）。
- 日志镜像：`uv run python scripts/dev/collect_logs.py` → `.opencode/logs/`（gitignored）。

## 4. 新会话开始方式

用 **glm-5.3-flash**（zhipuai/glm-5.3-flash，已验证可用）开新 session，起始输入建议：

> Latte。继续 OHNews M2 实现。先读 `docs/HANDOVER_M2.md`（旧会话交接）与 `docs/RECONSTRUCTION.md` §I-M2，从 M2a `oh-pipeline/src/oh_pipeline/event_status.py` 开始（旧会话已就绪，worktree 干净，M1 契约已 commit）。
