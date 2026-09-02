/**
 * 字典结构单一真源：zh 全量（键的定义处），en 全量对照；
 * 其余 19 语言骨架（键缺失时 fallback en，翻译学家工作流填充后自主校验）。
 * 键约定：点路径 "nav.now"；值模板 {n} 占位。
 */

export type Dict = Record<string, string>;

export const ZH: Dict = {
  "nav.now": "现在什么变了",
  "nav.investigate": "调查与验证",
  "nav.watch": "关注与追踪",
  "nav.memory": "认知档案",
  "nav.settings": "设置",
  "nav.disclaimer": "NDI = 叙事分歧指数，非预测器",
  "home.title": "OH!News",
  "home.briefing.latest": "最近一次有效简报：{t}",
  "home.briefing.changes": "最近一次简报：{n} 件值得注意的变化",
  "home.briefing.none": "本期简报没有值得看的变化",
  "home.briefing.more": "另有 {n} 件变化列于本期简报",
  "common.loading": "加载中…",
  "common.error": "加载失败，请稍后重试",
  "common.viewEvidence": "验证证据 →",
  "common.notImportant": "不重要",
};

export const EN: Dict = {
  "nav.now": "NOW",
  "nav.investigate": "INVESTIGATE",
  "nav.watch": "WATCH",
  "nav.memory": "MEMORY",
  "nav.settings": "Settings",
  "nav.disclaimer": "NDI = Narrative Divergence Index, not a predictor",
  "home.title": "OH!News",
  "home.briefing.latest": "Last valid briefing: {t}",
  "home.briefing.changes": "Latest briefing: {n} notable changes",
  "home.briefing.none": "Nothing worth your attention in this briefing",
  "home.briefing.more": "{n} more changes listed in this briefing",
  "common.loading": "Loading…",
  "common.error": "Failed to load, please retry",
  "common.viewEvidence": "Verify evidence →",
  "common.notImportant": "Not important",
};

/** 19 语言骨架：仅 key 占位（fallback en），由翻译学家工作流填充并自主校验。 */
function skeleton(): Dict {
  return Object.fromEntries(Object.keys(EN).map((k) => [k, ""]));
}

export const SKELETON_CODES = [
  "fr", "es", "ar", "ru", "de", "ja", "pt", "hi", "ko", "it",
  "tr", "nl", "pl", "sv", "fa", "id", "vi", "bn", "yue",
] as const;

export const DICTS: Record<string, Dict> = {
  zh: ZH,
  en: EN,
  ...Object.fromEntries(SKELETON_CODES.map((c) => [c, skeleton()])),
};
