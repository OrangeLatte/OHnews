/** 相对时间拆解：调用方用 i18n 模板渲染（observe.rel.* 键）。 */
export type RelPart = { value: number; unit: "s" | "m" | "h" | "d" | "mo" };

export function relParts(iso: string, now = Date.now()): RelPart | null {
  const ts = Date.parse(iso);
  if (!Number.isFinite(ts)) return null;
  const s = Math.max(1, Math.round((now - ts) / 1000));
  if (s < 60) return { value: s, unit: "s" };
  const m = Math.round(s / 60);
  if (m < 60) return { value: m, unit: "m" };
  const h = Math.round(m / 60);
  if (h < 48) return { value: h, unit: "h" };
  const d = Math.round(h / 24);
  if (d < 60) return { value: d, unit: "d" };
  return { value: Math.round(d / 30), unit: "mo" };
}

/** NDI/分歧强度 → 状态色语义：null=缺口灰，低=绿，中=琥珀，高=冲突红。 */
export function ndiTone(ndi: number | null | undefined): "ok" | "warn" | "conflict" | "gap" {
  if (ndi === null || ndi === undefined) return "gap";
  if (ndi >= 0.66) return "conflict";
  if (ndi >= 0.33) return "warn";
  return "ok";
}
