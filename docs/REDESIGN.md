# REDESIGN — OH!News 蓝图 v3：从 Technology-driven 到 Problem-driven

> 真源链：`BLUEPRINT.md`（v2 架构与裁决 A-H）→ 本文件（v3 产品重构）。
> v3 不推翻 v2 的任何裁决；它回答 v2 没有回答的问题——**用户为什么每天打开 OH!News**。

## 1. 定位转变

**旧定位（v2 隐含）**：拥有大量数据源、复杂 Agent 与图表的 AI Dashboard / Intelligence Platform。
**新定位（v3）**：**Continuous Research Workspace / Narrative & Information Observatory**——一个持续观察世界变化、发现重要信号、解释不同叙事、验证证据，并帮助用户逐步建立和更新自身认知体系的信息研究系统。

根本问题：技术架构复杂度超过了产品价值清晰度（"先建能力、再找展示"）。v3 从用户任务反推系统能力。

**最终检验标准（唯一）**：OH!News 能否比用户自己更早发现 *Something Meaningful Changed*。

## 2. 体验循环（产品的存在理由）

```text
WATCH 持续观察 → DETECT 发现变化 → UNDERSTAND 理解变化
→ INVESTIGATE 深入研究 → REMEMBER 沉淀研究记忆 → WATCH …
```

用户问题链：What changed? → Why? → Who sees it differently? → What evidence supports/contradicts? → Does this change what I previously believed?

## 3. 信息架构：四页（替代 Monitor/Analyze/Research 系统能力视角）

| 页 | 用户任务 | 核心回答 | 形态 |
|---|---|---|---|
| **Today** | 每天打开看一眼 | What changed? | Daily Intelligence Briefing：信息→过滤→变化检测→重要性排序→**每天 5-10 个 Signal**（不是数据展示中心，是变化发现系统） |
| **Watch** | 长期委托追踪 | 我关注的领域有什么新信号？ | 关注 **Entity / Topic / Theme / Question**（不是订阅媒体源）；重点 **Question Watch**：系统持续追踪一个问题的新证据+反向证据+叙事变化+注意力变化 |
| **Investigate** | 点开一个 Signal/Event/Question 后 | 为什么？各方怎么说？我该信什么？ | 结构化研究空间：Research Question → Current Understanding → Evidence → Different Narratives → AI Analysis → Counter Evidence → Challenge → Updated Understanding |
| **Library** | 沉淀 | 我过去研究过什么、判断过什么？ | Research Memory：Questions/Events/Evidence/Hypotheses/Conclusions/Decision Logs/Timeline → Personal Research Archive |

信息展示层级（Progressive Disclosure）：**Conclusion → Signal → Visualization → Evidence → Methodology**。

## 4. 系统边界（Detect / Understand / Decide）

```text
Sources → Collection → Normalization → Storage → Statistical Processing
→ Event Construction → Signal Detection      【Deterministic：Scheduled/Observable/Retryable/Testable，不 Agent 化】
        ↓ Something changed
   Agent                                      【Understand：组织证据/发现矛盾/提反向假设】
        ↓
   User                                       【Decide：What do I believe?】
```

v2 现状已符合此边界（采集纯 Python、langgraph 只在 analysis/research/chat）；v3 强化它并**停止把 Agent 当产品主角**。

## 5. Agent 压缩：N 个 Persona → 三个核心能力

| v3 能力 | 职责 | 承接的 v2 资产 |
|---|---|---|
| **Explorer** | Find Evidence | chat_graph 工具集、research_graph gather、Scout |
| **Analyst** | Compare & Explain | analysis_graph（tagger→divergence→calibration→hypothesis→interpret）、RedTeam ACH、Chief Analyst |
| **Investigator** | 围绕一个问题持续研究 | research_graph + Question Watch（新建）+ Research Memory |

Agent 不替用户思考、不给最终结论；参与**长期连续**的研究过程。intel 六角色降级为 Analyst 的内部方法（Scout 纯统计保留，Cartographer/ACH/Chief 成为 Analyst 的可选深度模式）。

## 6. Narrative Dynamics Framework（指标按用户问题组织）

NDI 保留（最有原创性资产），重定位：**NDI = Narrative Difference（叙事差异），≠ Conflict（冲突/撕裂）**。高 NDI 也可能只是关注点、解释框架、问题定义不同。

产品层六指标（每个回答一个用户问题）：

| 指标 | 回答 |
|---|---|
| **NDI**（Divergence） | 不同信息源如何讲述同一事件？ |
| **Expectation Gap / ΔT** | 官方与市场之间是否出现认知/预期错位？ |
| **Topic Divergence** | 不同群体是否在讨论完全不同的问题？ |
| **Narrative Shift** | 叙事与过去相比变了多少？ |
| **Attention Velocity** | 某主题正以多快速度获得关注？ |
| **Change Point** | 叙事/信息结构何时发生结构性变化？ |

内部分析层保留（不进首页）：Shannon Entropy（Diversity）/ HHI（Concentration，二选一表达）/ Emotion Space（valence×arousal 二维）/ Relative Negative Bias（以事件整体基线比较，进 Source Lens）。**IQV 降为实验指标**；极化/模块度/同质性等网络指标**暂缓**——需真实 Social/Interaction Graph，当前主体是机构与媒体而非社群；未来引入 Reddit/X/知乎评论区互动网络后再建独立 Network Dynamics Layer。

## 7. SIGNAL：统一收敛对象

所有技术能力最终收敛为用户能理解的对象，而不是让用户面对底层结构：

```text
Articles → Entities/Topics/Frames → Events → Time Series
→ Change Detection → Signals → Explainable Evidence
→ User Investigation → Research Memory
```

```python
class SignalKind(StrEnum):
    ATTENTION_SPIKE = "attention_spike"      # Attention Velocity / Spike
    NARRATIVE_SHIFT = "narrative_shift"      # 与过去相比变了多少
    NDI_ALERT = "ndi_alert"                  # 分歧显著（高位/突变）
    EXPECTATION_GAP = "expectation_gap"      # ΔT 温差（官方 vs 市场）

class Signal(BaseModel):                      # oh-contracts
    signal_id: str; kind: SignalKind; entity_id: str
    title: str                                # 用户语言（"FED Narrative Shift"）
    what_changed: str; why_it_matters: str | None
    metrics: dict[str, float]                 # kind 相关数值（z/delta/ndi/gap…）
    strength: float                           # 0-100，重要性排序
    confidence: float
    evidence_ids: list[str]                   # event_ids（证据链入口）
    detected_at: datetime; as_of: datetime    # PIT：as_of 锚
```

事件级动态（Narrative Timeline / Event Lifecycle，v3 目标形态）：
Detection → Attention Spike → Narrative Formation → Divergence → Shift → Emotional Escalation → Consensus/Fragmentation。

## 8. 可视化体系（停止"有数据找炫酷图表"）

选择流程：用户问题 → 需要理解什么 → 信息结构 → 视觉编码。四层：

1. **Signal Layer**（What changed?）：Delta/Spike/Velocity/Timeline/Anomaly。
2. **Structure Layer**（What is happening?）：Distribution/Composition/Comparison/Cluster。
3. **Relationship Layer**（What is connected?）：**仅当关系复杂到文字无法表达才用** Entity/Event Graph——不默认展示 Network Graph。
4. **Evidence Layer**（Why believe?）：Claim → Evidence → Source → Original Context。

风格：**Financial Terminal + Editorial Research + AI Workspace**——高信息密度、强排版层级、Editorial Layout、Minimal DataViz、Progressive Disclosure。不再走 Cyberpunk Dashboard，也不做 Generic SaaS Admin。

**核心视觉对象 = Narrative Landscape（信息场）**，替代单点 NDI 数字：
- Diversity × Divergence 四象限：共识 / 阵营化 / 多元 / 复杂分化；
- NDI × Topic Divergence 四象限：Shared Focus / Different Priorities / **Same Event, Different Worlds**（最具辨识度的研究视角）/ Fragmented Reality。

## 9. 资产三清单

**保留（= OH! Information Intelligence Engine，不动）**：SourceAdapter+7 adapters+Registry+Runner+Health、Bronze/Silver/Parquet/SQLite WAL/Protocol、EntityRegistry、RuleTagger、EventBuilder、NDI+Divergence+Cross-lang Gate+Validation、ModelRouter+Fallback+Schema+Committee+Gold Set。

**重构（v3 主战场）**：Agent Architecture（→三能力）、Product API（→Today/Watch/Investigate/Library 语义）、Frontend IA（→四页）、Signal Object（新建）、Research Memory（新建，含决策日志整合）。

**降级为内部能力 / Progressive Disclosure 层**：intel 六角色 Persona 前端、默认 Network Graph（/command 源星系）、NDI 唯一核心视觉、词级 SVO 与句级光谱（降为 Investigate 内的证据检视工具）、独立指标卡堆叠。

## 10. 五阶段路线（新功能准入五问：为什么需要/什么场景/解决什么/删掉损失什么/有没有更简单方式）

1. **Phase R1 Today→Signal→Evidence**（当前）：Signal 契约+确定性变化检测+/api/today+/today 页。验收：每天打开能看 5-10 个值得注意的变化并能一键下钻证据。
2. **Phase R2 Watch**：Entity/Topic/**Question** 订阅+持续追踪（新证据/反向证据/叙事变化/注意力）。
3. **Phase R3 Narrative Timeline**：NDI/TopicDivergence/NarrativeShift/AttentionVelocity/ChangePoint/ΔT 形成事件生命周期视图。
4. **Phase R4 Investigate**：Explorer/Analyst/Investigator 三能力结构化研究流程（含 ACH/Counter-evidence 挑战环）。
5. **Phase R5 Library**：Questions/Evidence/Hypotheses/Conclusions/Timeline/Decision Log → Personal Research System。

措辞纪律延续：NDI=叙事分歧指数（描述性监测），ρ≥0.8 硬门禁未过禁对外数字。
