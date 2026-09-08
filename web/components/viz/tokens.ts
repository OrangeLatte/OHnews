/**
 * OH Viz v1 设计令牌：序列色板（8 色循环）+ 语义色 + 轴规格常量。
 * 统一 viz/* 图表与 observe/* 图表的色彩语言；语义色与项目既有语义值逐一一致
 * （一致绿/冲突红/缺口灰/警示琥珀/信息蓝），保证跨 Lens 图例可读性。
 */

/** 序列色板（8 色循环：与 observe 情绪温度色板同源的低饱和报纸风配色）。 */
export const VIZ_SERIES_COLORS: readonly string[] = [
  "#b3543f", // 锈红
  "#5e83a8", // 灰蓝
  "#6f8f6a", // 橄榄绿
  "#b08d3f", // 琥珀沙
  "#a05a78", // 干玫瑰
  "#8a6fae", // 灰紫
  "#5e9c94", // 灰青
  "#c07a4a", // 陶土橙
];

/** 语义色（统一降饱和至情绪温度色板同档，保持语义辨识度）。 */
export const VIZ_SEMANTIC = {
  ok: "#6f8f6a",
  conflict: "#b3543f",
  gap: "#6b7280",
  warn: "#b08d3f",
  info: "#5e83a8",
} as const;

/** 序列第 i 项的颜色（负索引也安全循环）。 */
export function seriesColor(i: number): string {
  const n = VIZ_SERIES_COLORS.length;
  return VIZ_SERIES_COLORS[((i % n) + n) % n] as string;
}

/** 网格/轴线色：主题 token（经 style 生效——SVG 表现属性不支持 var()）。 */
export const GRID_STROKE = "var(--border)";

/** 轴与网格规格（TradingView 式克制：小字号 + 虚线网格）。 */
export const AXIS_FONT_SIZE = 10;
export const GRID_DASH = "3 3";
export const NEUTRAL_DASH = "1.5 1.5";
