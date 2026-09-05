/**
 * SOURCES 目录元数据映射（P2 打磨）：kind / tier 的展示标签与解释。
 * 事实口径：后端 /api/sources 当前对 kind 未填充（现网 61/61 全为字面 "?"），
 * 值域参照 config/sources.yaml 的 adapter 分类 + 任务预设的通用别名；
 * 未命中映射的值原样直显（含 "?" → 未标注兜底，不再裸显问号）。
 */

/** kind 值 → i18n 键（sources.kind.*）。 */
export const KIND_LABEL_KEYS: Record<string, string> = {
  rss: "sources.kind.rss",
  web: "sources.kind.web",
  api: "sources.kind.api",
  json_api: "sources.kind.jsonApi",
  gdelt: "sources.kind.gdelt",
  fred: "sources.kind.fred",
  browser: "sources.kind.browser",
  reddit_cdp: "sources.kind.redditCdp",
  telegram: "sources.kind.telegram",
  youtube: "sources.kind.youtube",
};

/** 后端未标注 kind（现网为 "?"）时的 i18n 键。 */
export const KIND_UNKNOWN_KEY = "sources.kindUnknown";

/** tier → i18n 解释键（sources.tierHint.*）。 */
export const TIER_HINT_KEYS: Record<string, string> = {
  L1: "sources.tierHint.L1",
  L2: "sources.tierHint.L2",
  L3: "sources.tierHint.L3",
  L4: "sources.tierHint.L4",
};

/** tier 图例色点（与信源表徽标一致的轻量色板）。 */
export const TIER_LEGEND: { tier: string; dot: string }[] = [
  { tier: "L1", dot: "bg-emerald-500" },
  { tier: "L2", dot: "bg-sky-500" },
  { tier: "L3", dot: "bg-amber-500" },
  { tier: "L4", dot: "bg-zinc-500" },
];

/**
 * kind 展示标签：命中映射走 i18n，"?" 走「未标注」，其余原值直显。
 */
export function kindLabel(kind: string, t: (key: string) => string): string {
  if (kind === "?" || kind === "") return t(KIND_UNKNOWN_KEY);
  const key = KIND_LABEL_KEYS[kind];
  return key ? t(key) : kind;
}
