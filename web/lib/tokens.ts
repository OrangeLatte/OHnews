// Design tokens 单一来源（R5a 收敛）：色值只在这里定义一次。
// ECharts（canvas）无法读 CSS var，因此 TS 常量为运行时唯一真源；
// globals.css 的 --signal-* / --frame-* 用同值手工同步（改动时两处一起改）。
// 语义：颜色永不单独编码信息，一律配合形状/标签（§8 可访问性要求）。

/** 语义信号色（REFACTOR_V2 §8：attention amber / narrative purple / divergence rust / confirmed slate-green）。 */
export const SIGNAL = {
  attention: "#b08d3f",
  narrative: "#6b5b95",
  divergence: "#8b2635",
  confirmed: "#7d8a6a",
  warning: "#a34a2a",
  muted: "#8a8378",
} as const;

/** NDI 分档色（divergenceLevel 固定五档，与 SIGNAL 语义对齐）。 */
export const NDI_LEVELS = {
  abstain: SIGNAL.muted,
  consensus: SIGNAL.confirmed,
  emerging: SIGNAL.attention,
  clear: SIGNAL.warning,
  conflict: SIGNAL.divergence,
} as const;

/** 五框架色板（报纸风亮色基准；FRAME_BG 为 10% 透明背景变体）。 */
export const FRAME_COLORS: Record<string, string> = {
  loss: "#b3543f",
  gain: "#5e8a5e",
  responsibility: "#b08d3e",
  conflict: "#8a6fae",
  human_interest: "#5e83a8",
  other: "#9a948a",
};

export const FRAME_BG: Record<string, string> = {
  loss: "#b3543f1a",
  gain: "#5e8a5e1a",
  responsibility: "#b08d3e1a",
  conflict: "#8a6fae1a",
  human_interest: "#5e83a81a",
  other: "#9a948a1a",
};

export const FRAME_TEXT: Record<string, string> = { ...FRAME_COLORS };

export const FRAME_ZH: Record<string, string> = {
  loss: "损失",
  gain: "收益",
  responsibility: "责任",
  conflict: "冲突",
  human_interest: "人情味",
  other: "其他",
};

/** 事件评估四态色（M2 EventAssessment.status）。 */
export const ASSESS_STATUS: Record<string, string> = {
  confirmed: SIGNAL.confirmed,
  contested: SIGNAL.divergence,
  developing: SIGNAL.attention,
  unverified: SIGNAL.muted,
};

/** ECharts 报纸风主题基底（R5b chart-base 注入用）。 */
export const PAPER_THEME = {
  textStyle: { fontFamily: 'Georgia, "Times New Roman", "Songti SC", serif' },
  axis: {
    axisLine: { lineStyle: { color: "#c9c2b4" } },
    axisLabel: { color: "#8a8378" },
    splitLine: { lineStyle: { color: "#e5e0d3" } },
  },
} as const;
