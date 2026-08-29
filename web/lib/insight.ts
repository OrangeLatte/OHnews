// 用户语言映射层（重构指令 §三/§六）：工程指标降为解释层，默认界面只说人话。

export type DivergenceLevel = {
  label: string;
  zh: string;
  color: string;
  rank: number;
};

/** NDI → 四档语言（重构指令固定分档，解释层才展示数值）。 */
export function divergenceLevel(ndi: number | null | undefined): DivergenceLevel {
  if (ndi === null || ndi === undefined) {
    return { label: "Insufficient Data", zh: "证据不足（官方簇样本过少，系统弃权）", color: "#8a8378", rank: -1 };
  }
  if (ndi < 0.15) return { label: "Narrative Consensus", zh: "叙事共识", color: "#7d8a6a", rank: 0 };
  if (ndi < 0.35) return { label: "Emerging Differences", zh: "分歧初现", color: "#b08d3f", rank: 1 };
  if (ndi < 0.6) return { label: "Clear Divergence", zh: "明显分歧", color: "#a34a2a", rank: 2 };
  return { label: "Narrative Conflict", zh: "叙事冲突", color: "#8b2635", rank: 3 };
}

/** 趋势词（delta=较前值变化）。 */
export function divergenceTrend(delta: number | null | undefined): string {
  if (delta === null || delta === undefined) return "";
  if (delta >= 0.05) return "↑ 分歧正在扩大";
  if (delta <= -0.05) return "↓ 分歧正在收敛";
  return "→ 基本持平";
}

export type SignalKindMeta = { label: string; zh: string; color: string };

/** Signal 类型 → 用户语言（指令五类示例中，系统当前真实产出四类；Source Anomaly 暂无检测器，不虚构）。 */
export function signalKindMeta(kind: string): SignalKindMeta {
  switch (kind) {
    case "attention_spike":
      return { label: "Attention Surge", zh: "关注度骤增", color: "#b08d3f" };
    case "ndi_alert":
      return { label: "Narrative Divergence", zh: "叙事分歧", color: "#8b2635" };
    case "expectation_gap":
      return { label: "Expectation Shift", zh: "预期落差", color: "#a34a2a" };
    case "narrative_shift":
      return { label: "Narrative Shift", zh: "叙事迁移", color: "#6b5b95" };
    default:
      return { label: kind, zh: kind, color: "#8a8378" };
  }
}

/** 强度 → 语言。 */
export function strengthWord(strength: number): string {
  if (strength >= 80) return "显著";
  if (strength >= 50) return "明显";
  return "轻微";
}

/** z-score → 变化描述（解释层保留技术锚点）。 */
export function attentionPhrase(z: number): string {
  const pct = Math.round((Math.exp(Math.abs(z)) - 1) * 100);
  return `较基线上升约 ${pct > 999 ? "10 倍以上" : `${pct}%`}（${z.toFixed(1)}σ）`;
}

/** Watch 快照 → 状态徽章（指令 §十：Quiet/Developing/Attention Spike/Narrative Divergence）。 */
export type WatchStatus = { label: string; zh: string; color: string };

export function watchStatus(summary: Record<string, unknown> | null): WatchStatus {
  if (!summary) return { label: "Quiet", zh: "平静", color: "#8a8378" };
  const signals = (summary.signals as { kind: string }[] | undefined) ?? [];
  const kinds = new Set(signals.map((s) => s.kind));
  if (kinds.has("ndi_alert"))
    return { label: "Narrative Divergence", zh: "叙事分歧", color: "#8b2635" };
  if (kinds.has("attention_spike"))
    return { label: "Attention Spike", zh: "关注度骤增", color: "#b08d3f" };
  if (kinds.has("expectation_gap") || kinds.has("narrative_shift"))
    return { label: "Developing", zh: "发展中", color: "#a34a2a" };
  const nEvents = (summary.n_events as number | undefined) ?? 0;
  if (nEvents > 0) return { label: "Developing", zh: "发展中", color: "#a34a2a" };
  return { label: "Quiet", zh: "平静", color: "#8a8378" };
}

export const FRAME_ZH: Record<string, string> = {
  loss: "损失",
  gain: "收益",
  responsibility: "责任",
  conflict: "冲突",
  human_interest: "人情味",
  other: "其他",
};
