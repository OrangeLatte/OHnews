/**
 * 十八元素视觉 Token（单一真源）。
 *
 * 规格要求（OHNEWS_RESEARCH_OS_SPEC_V5 二.3）：每类元素拥有独立颜色、简称与
 * 图形编码；颜色不得作为唯一辨识手段（同时显示短码/名称）；满足 WCAG AA 对比度。
 *
 * 三层辨识 = 独立色（bg/edge 同色相明度分离）+ 短码（short）+ 图形族（shape）。
 * 消费方：annotated-text（mark/图例）、case-shared（Dot/Chip）、element-matrix、read-mode。
 */

export type ElementShape = "underline" | "leftbar" | "outline" | "plain";

export type ElementToken = {
  /** 浅底色（mark 背景 / Dot 背景），文字用深色，对比度 ≥ 7:1。 */
  bg: string;
  /** 同色相深色（边框 / 短码文字），保证与浅底的边界辨识。 */
  edge: string;
  /** 2-6 字母短码（图例/矩阵/卡片显示；颜色之外的辨识手段）。 */
  short: string;
  /** 图形编码族：事实类下划线 / 论证类左侧竖线 / 立场态度类双边框 / 其余纯底。 */
  shape: ElementShape;
};

export const ELEMENT_TOKENS: Record<string, ElementToken> = {
  actor: { bg: "#fef3c7", edge: "#b45309", short: "AC", shape: "outline" },
  target: { bg: "#fee2e2", edge: "#b91c1c", short: "TG", shape: "outline" },
  stakeholder: { bg: "#ffedd5", edge: "#c2410c", short: "ST", shape: "outline" },
  hard_fact: { bg: "#dcfce7", edge: "#15803d", short: "FACT", shape: "underline" },
  quant_data: { bg: "#ccfbf1", edge: "#0f766e", short: "QNT", shape: "underline" },
  data_scope: { bg: "#cffafe", edge: "#0e7490", short: "SCOPE", shape: "underline" },
  action: { bg: "#dbeafe", edge: "#1d4ed8", short: "ACT", shape: "outline" },
  causal_link: { bg: "#e0e7ff", edge: "#4338ca", short: "CAUSE", shape: "leftbar" },
  timeline: { bg: "#ede9fe", edge: "#6d28d9", short: "TIME", shape: "underline" },
  perspective: { bg: "#f5f3ff", edge: "#7c3aed", short: "PERSP", shape: "leftbar" },
  explicit_stance: { bg: "#ffe4e6", edge: "#be123c", short: "STANCE", shape: "leftbar" },
  implicit_bias: { bg: "#fce7f3", edge: "#be185d", short: "BIAS", shape: "leftbar" },
  tone: { bg: "#fff1f2", edge: "#9f1239", short: "TONE", shape: "leftbar" },
  diction: { bg: "#fef9c3", edge: "#a16207", short: "DICT", shape: "plain" },
  source_reliability: { bg: "#e0f2fe", edge: "#0369a1", short: "SRC", shape: "outline" },
  argument_structure: { bg: "#ecfccb", edge: "#4d7c0f", short: "ARG", shape: "leftbar" },
  intent: { bg: "#fae8ff", edge: "#a21caf", short: "INT", shape: "leftbar" },
  context: { bg: "#f1f5f9", edge: "#475569", short: "CTX", shape: "plain" },
};

export const ELEMENT_BG: Record<string, string> = Object.fromEntries(
  Object.entries(ELEMENT_TOKENS).map(([k, t]) => [k, t.bg]),
);

export const ELEMENT_EDGE: Record<string, string> = Object.fromEntries(
  Object.entries(ELEMENT_TOKENS).map(([k, t]) => [k, t.edge]),
);

export function elementBg(key: string): string {
  return ELEMENT_BG[key] ?? "#e2e8f0";
}

export function elementEdge(key: string): string {
  return ELEMENT_EDGE[key] ?? "#64748b";
}

export function elementShort(key: string): string {
  return ELEMENT_TOKENS[key]?.short ?? key.slice(0, 3).toUpperCase();
}

export function elementShape(key: string): ElementShape {
  return ELEMENT_TOKENS[key]?.shape ?? "plain";
}

/** 图例图形符号（shape 族的文本表示，颜色之外的辨识手段）。 */
export const SHAPE_GLYPH: Record<ElementShape, string> = {
  underline: "▁",
  leftbar: "▎",
  outline: "◇",
  plain: "●",
};
