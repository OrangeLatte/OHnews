/**
 * ExplanationRegistry（Clean-slate Phase 1）：
 * 与领域字段绑定的解释注册表，取代 JSX 旁手写 Tooltip。
 * 文本全部走消息键（help.*），21 语言机制复用 dictionaries fallback。
 * 覆盖对象：专业指标 / 质量门 / 状态 / 页面模式 / Lens / 十八元素 / Agent 动作。
 * 新闻标题、普通按钮、正文不加问号（避免视觉噪声）。
 */

export interface HelpDefinition {
  /** 注册键（全局唯一，供组件/自动化扫描引用） */
  key: string;
  /** 一行短解释（hover/focus 首屏） */
  short: string;
  /** 长解释（Popover 展开：计算/来源方法） */
  method: string;
  /** 局限与误读警告 */
  limit: string;
  /** 可选示例 */
  example?: string;
  /** 内容更新时间（ISO） */
  updatedAt: string;
}

const UPDATED = "2026-09-03";

export const HELP_REGISTRY: Record<string, HelpDefinition> = {
  "metric.ndi": {
    key: "metric.ndi",
    short: "help.ndi.short",
    method: "help.ndi.method",
    limit: "help.ndi.limit",
    example: "help.ndi.example",
    updatedAt: UPDATED,
  },
  "metric.abstain": {
    key: "metric.abstain",
    short: "help.abstain.short",
    method: "help.abstain.method",
    limit: "help.abstain.limit",
    updatedAt: UPDATED,
  },
  "state.loading": {
    key: "state.loading",
    short: "help.state.loading",
    method: "help.state.loading.method",
    limit: "help.state.generic.limit",
    updatedAt: UPDATED,
  },
  "state.empty": {
    key: "state.empty",
    short: "help.state.empty",
    method: "help.state.empty.method",
    limit: "help.state.generic.limit",
    updatedAt: UPDATED,
  },
  "state.abstained": {
    key: "state.abstained",
    short: "help.state.abstained",
    method: "help.state.abstained.method",
    limit: "help.state.generic.limit",
    updatedAt: UPDATED,
  },
  "state.stale": {
    key: "state.stale",
    short: "help.state.stale",
    method: "help.state.stale.method",
    limit: "help.state.generic.limit",
    updatedAt: UPDATED,
  },
  "state.error": {
    key: "state.error",
    short: "help.state.error",
    method: "help.state.error.method",
    limit: "help.state.generic.limit",
    updatedAt: UPDATED,
  },
  "state.needsReview": {
    key: "state.needsReview",
    short: "help.state.needsReview",
    method: "help.state.needsReview.method",
    limit: "help.state.generic.limit",
    updatedAt: UPDATED,
  },
  "state.needsConfirm": {
    key: "state.needsConfirm",
    short: "help.state.needsConfirm",
    method: "help.state.needsConfirm.method",
    limit: "help.state.generic.limit",
    updatedAt: UPDATED,
  },
  "state.notConfigured": {
    key: "state.notConfigured",
    short: "help.state.notConfigured",
    method: "help.state.notConfigured.method",
    limit: "help.state.generic.limit",
    updatedAt: UPDATED,
  },
  "mode.read": {
    key: "mode.read",
    short: "help.mode.read",
    method: "help.mode.read.method",
    limit: "help.mode.generic.limit",
    updatedAt: UPDATED,
  },
  "mode.map": {
    key: "mode.map",
    short: "help.mode.map",
    method: "help.mode.map.method",
    limit: "help.mode.generic.limit",
    updatedAt: UPDATED,
  },
  "mode.compare": {
    key: "mode.compare",
    short: "help.mode.compare",
    method: "help.mode.compare.method",
    limit: "help.mode.generic.limit",
    updatedAt: UPDATED,
  },
  "mode.report": {
    key: "mode.report",
    short: "help.mode.report",
    method: "help.mode.report.method",
    limit: "help.mode.generic.limit",
    updatedAt: UPDATED,
  },
  "mode.history": {
    key: "mode.history",
    short: "help.mode.history",
    method: "help.mode.history.method",
    limit: "help.mode.generic.limit",
    updatedAt: UPDATED,
  },
  "lens.flow": {
    key: "lens.flow",
    short: "help.lens.flow",
    method: "help.lens.flow.method",
    limit: "help.lens.generic.limit",
    updatedAt: UPDATED,
  },
  "lens.narrative": {
    key: "lens.narrative",
    short: "help.lens.narrative",
    method: "help.lens.narrative.method",
    limit: "help.lens.generic.limit",
    updatedAt: UPDATED,
  },
  "lens.divergence": {
    key: "lens.divergence",
    short: "help.lens.divergence",
    method: "help.lens.divergence.method",
    limit: "help.lens.generic.limit",
    updatedAt: UPDATED,
  },
  "lens.emotion": {
    key: "lens.emotion",
    short: "help.lens.emotion",
    method: "help.lens.emotion.method",
    limit: "help.lens.generic.limit",
    updatedAt: UPDATED,
  },
  "lens.entities": {
    key: "lens.entities",
    short: "help.lens.entities",
    method: "help.lens.entities.method",
    limit: "help.lens.generic.limit",
    updatedAt: UPDATED,
  },
  "agent.hitl": {
    key: "agent.hitl",
    short: "help.hitl.short",
    method: "help.hitl.method",
    limit: "help.hitl.limit",
    updatedAt: UPDATED,
  },
  "agent.evidenceSpan": {
    key: "agent.evidenceSpan",
    short: "help.evidenceSpan.short",
    method: "help.evidenceSpan.method",
    limit: "help.evidenceSpan.limit",
    updatedAt: UPDATED,
  },
};

/** 十八项拆解元素的注册键（与 dissection ELEMENT_KEYS 一一对应）。 */
export const ELEMENT_HELP_KEYS: string[] = [
  "element.actor",
  "element.target",
  "element.stakeholder",
  "element.hardFact",
  "element.quantData",
  "element.dataScope",
  "element.action",
  "element.causalLink",
  "element.timeline",
  "element.perspective",
  "element.explicitStance",
  "element.implicitBias",
  "element.tone",
  "element.diction",
  "element.sourceReliability",
  "element.argumentStructure",
  "element.intent",
  "element.context",
];

export function helpDefinition(key: string): HelpDefinition | undefined {
  // 调用方存在两种前缀习惯（"mode.read" 与 "help.mode.read"），兼容双格式查找，
  // 否则带前缀的 helpKey 落空 → 点击 ？ 无解释（第十一轮验收 P0-1）。
  return HELP_REGISTRY[key] ?? HELP_REGISTRY[key.replace(/^help\./, "")];
}

/** 自动化扫描用：全部注册键（覆盖率测试 = 页面引用键 ⊆ 注册表）。 */
export function allHelpKeys(): string[] {
  return [
    ...Object.keys(HELP_REGISTRY),
    ...ELEMENT_HELP_KEYS,
  ];
}
