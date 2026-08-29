# REDESIGN AGENT — Agent 交互架构（v3 下篇）

> 真源链：`BLUEPRINT.md`（v2 裁决）→ `REDESIGN.md`（v3 产品方向）→ 本文件（v3 Agent 交互层，REDESIGN §4/§5 的完整展开）。
> 核心原则：**Agent 不是 Pipeline 的控制器，也不再是产品的主角**——它是运行在用户认知过程中的交互层：Signal Interpreter / Evidence Navigator / Research Companion。

## 1. 定位与认知链路

Agent 不负责：数据采集、ETL、定时任务、指标/NDI 计算、事件构建、数据库写入、系统监控（全部保持确定性 Pipeline）。

```text
WORLD → SOURCES → PIPELINE(OBSERVE/PROCESS/MEASURE) → EVENTS
→ NARRATIVE DYNAMICS → SIGNALS                       【L1-L3 确定性】
→ AGENT SYSTEM（Understand） → USER（Decide）
→ RESEARCH MEMORY → FUTURE OBSERVATION（WATCH 闭环）
```

## 2. 结构：一编排 + 三原语 + N 模式（Persona 废除）

```text
USER ── GUI Action ──▶ Interaction Layer ──▶ Agent Orchestrator
                                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
          EXPLORER        ANALYST        INVESTIGATOR
       Evidence          Meaning         Research
       Discovery         Analysis        Process
              └───────────────┼───────────────┘
                              ▼
                        Tool Gateway（结构化工具，不碰 SQL）
                              ▼
                     SIGNALS / EVIDENCE / MEMORY
```

v2 Persona → v3 归宿映射：

| v2 资产 | v3 归宿 |
|---|---|
| Scout（量级/新实体/CUSUM） | 保留为**纯统计函数**（并入 detect 层，非 Agent） |
| Cartographer / ACH RedTeam / Chief Analyst | 降为 **Analyst 的 Reasoning Modes**（COMPARE / CHALLENGE / SYNTHESIZE），无常驻实体 |
| analysis_graph（tagger→divergence→calibration→hypothesis→interpret） | **Analyst 原语**的实现基座 |
| research_graph（gather→synthesize） | **Explorer+Investigator** 的实现基座 |
| chat_graph（agent⇄tools 循环） | 改造为 **Orchestrator 入口**（Intent Resolver + Context Builder 前置） |
| intel_cycle 四节点 | 降为后台分析模式（Scout 统计入 L3，其余入 Analyst Modes） |

## 3. Action-driven，不是 Prompt-driven

用户通过 GUI 表达意图，Orchestrator 不反问。Suggested Actions 与 Intent 一一对应：

| 按钮 | Intent | Mode | 原语 |
|---|---|---|---|
| What changed? | EXPLAIN_SIGNAL | EXPLAIN | Analyst |
| Why did this change? | EXPLAIN_CAUSE | EXPLAIN | Explorer+Analyst |
| Who disagrees? | COMPARE_NARRATIVES | COMPARE | Explorer+Analyst+Divergence Engine |
| Show evidence | SHOW_EVIDENCE | EXPLORE | Explorer |
| Investigate | START_INVESTIGATION | INVESTIGATE | 三原语全链 |

API 形态：`POST /api/agent/act {"action": "EXPLAIN_SIGNAL", "signal_id": "..."} `——前端传结构化 Action 而非自由文本；Chat 保留为 Optional Chat（自由问句 → Intent Resolver 归类到同一 Intent 集）。

## 4. ResearchState（核心状态，不是 messages）

```python
class ResearchState(TypedDict):
    session_id: str
    current_intent: str            # EXPLAIN_SIGNAL / COMPARE_NARRATIVES / ...
    current_mode: str              # EXPLAIN / COMPARE / INVESTIGATE / CHALLENGE
    current_signal_id: str | None
    current_event_id: str | None
    current_question: str | None
    selected_entities: list[str]
    selected_time_range: tuple[str, str] | None
    evidence_ids: list[str]
    hypotheses: list[Hypothesis]   # 含 supporting/contradicting evidence_ids
    findings: list[Finding]
    uncertainty: list[str]
    research_stage: str            # RESOLVE/EXPLORE/ANALYZE/CHALLENGE/BUILD/REVIEW
    pending_action: str | None     # HITL 挂起点（复用 langgraph interrupt）
    memory_context: list[str]      # Library 相关摘要引用
```

交互单位：**User Action → State Change → Agent Reasoning → Artifact Generation → State Update**（不是 Message→LLM→Message）。

## 5. Artifact 契约（Agent 输出结构化语义，UI 负责呈现）

五类 Artifact（全部入 oh-contracts，Pydantic _Strict）：

- **AnalysisArtifact**：headline / observation / interpretation / causes[] / alternative_explanations[] / key_differences[] / evidence_ids / confidence / uncertainty / suggested_actions[]（Next Actions 递进）
- **EvidenceArtifact**：EvidenceSet 四分桶——supporting / contradicting / new / missing（Explorer 必须回答"我们缺什么证据"，不是返回 10 篇文章）
- **ComparisonArtifact**：groups[]（各簇框架分布+立场+样本量）/ divergence_metrics / interpretation
- **HypothesisArtifact**：hypotheses[] + 状态（initial/revised）+ challenge 历史
- **ChallengeArtifact**：strongest_alternative / counter_evidence_ids / impact（confidence 变化 High→Medium）

Analyst 强制五层分离输出（禁止 LLM 混写）：**Observation → Interpretation → Evidence → Alternative Interpretation → Uncertainty**。

## 6. Tool Gateway（结构化工具面）

Agent 只见工具不见库。清单（现有→新建）：

| 类 | 工具 | 现状 |
|---|---|---|
| Signal | get_signal / get_signal_timeline / list_signals（今日 Top-N） | R1 新建 /api/today 复用 |
| Event | get_related_events(entity, range) | chat.query_events 改造 |
| Narrative | get_narrative_distribution(event_id) / compare_narratives(event_id, groups) | divergence/anatomy 复用 |
| Evidence | retrieve_evidence(query) / retrieve_counter_evidence(claim) / get_source_context | evidence 端点+spectrum 复用；counter-evidence 新建（stance 对立检索） |
| Memory | get/create_question / create/update_hypothesis / save_finding / save_conclusion / get_research_memory | R5 新建（Library） |
| Metric | get_metric_history(metric, entity) / detect_change(entity, metric) | ndi_all/detect 复用 |

## 7. ContextPacket（Context Builder，取代 messages 堆历史）

```python
class ContextPacket(BaseModel):
    user_intent: str; current_signal: dict | None; current_event: dict | None
    selected_entities: list[str]; selected_time_range: tuple[str, str] | None
    metrics: dict[str, float]; narrative_summary: str | None
    key_evidence: list[dict]; contradictory_evidence: list[dict]
    current_hypothesis: dict | None; previous_findings: list[dict]
    uncertainty: list[str]; relevant_memory: list[dict]
```

每次 Invocation：USER ACTION → CONTEXT BUILDER → CONTEXT PACKET → MODEL。会话压缩 = Raw Conversation → 结构化抽取（Claim/Evidence/Hypothesis/Finding/Decision/Open Question）→ Research Artifacts（不读 10 万 token 历史）。

## 8. Challenge Mode（替代常驻 RedTeam）

触发条件：hypothesis confidence 超阈 / 证据失衡检出 / 用户请求 / 结论生成前（强制）。流程：Current Claim → 最强反方论证 → counter evidence 检索 → 替代假设生成 → 证据质量核查 → 更新 uncertainty。输出 ChallengeArtifact（含 confidence 影响）。

## 9. Streaming = Execution Events（不是 token 流）

```text
event: state    data: RETRIEVING_EVIDENCE
event: progress data: 12 evidence sources found
event: state    data: ANALYZING_DIVERGENCE
event: artifact data: {AnalysisArtifact…}
```

前端呈现"系统正在研究"（● 检索证据 → ✓ 12 源命中 → ● 比较叙事 → …），复用现有 SSE 总线（publish_sse 扩 event 类型）。

## 10. LangGraph 状态机：Graph = Research Process

```text
IDLE → RESOLVE_INTENT → [EXPLAIN | EXPLORE | INVESTIGATE]
  EXPLAIN:   CONTEXT→ANALYZE→ARTIFACT
  EXPLORE:   RETRIEVE→CLUSTER/RANK→EVIDENCE SET
  INVESTIGATE: HYPOTHESIZE→EVIDENCE→(SUPPORT|CONTRADICTION)
                     →CHALLENGE→REVISE→CONCLUSION→OPEN QUESTIONS
→ CHALLENGE（触发式）→ QUALITY CHECK → BUILD ARTIFACT
→ USER REVIEW ── CONTINUE（state update）/ SAVE（memory update）→ NEXT ACTION
```

HITL 复用 interrupt/Command(resume)（v2 已验证）；checkpoint 仍 SqliteSaver 单写者（裁决 D）。

## 11. Memory 四层（R5 Library 的地基）

Session（当前研究状态）/ Episodic（研究过程史）/ Semantic（长期结论）/ Watch（entities/topics/questions）。现有 decision_log 并入 Episodic→Semantic；Question Watch（R2）产 Watch 层。

## 12. 分层总览与实施顺序

```text
L0 WORLD / L1 DATA PIPELINE / L2 INTELLIGENCE ENGINE
→ L3 SIGNAL LAYER（R1：detect+Signal+Today）   ← 当前
→ L4 AGENT INTERACTION LAYER（Orchestrator/三原语/Modes/Tool Gateway/ContextPacket）
→ L5 RESEARCH MEMORY（R5） / L6 EXPERIENCE（Today/Watch/Investigate/Library）
```

实施顺序：**R1 Signal 层（进行中）→ R2 Watch（Question Watch 优先）→ R3 Narrative Timeline → R4 Agent 交互层改造（chat_graph→Orchestrator、research_graph→Investigator 状态机）→ R5 Library**。L4 改造前不新增任何 Agent Persona；新功能过 REDESIGN §10 五问。

最终形态（衡量标准）：Better Context / Better State / Better Tools / Better Artifacts / Better Interaction / Better Memory——而非 More Agents / More Personas / More Autonomous Loops。
