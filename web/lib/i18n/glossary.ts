/**
 * 术语字典（A2 tooltip）：全站「?」解释的单一真源。
 * 结构与 dictionaries.ts 同模式：en/zh 全量，其余语言骨架（fallback en）。
 * 纪律：解释必须人话 + 诚实边界（如 NDI 非预测器），禁止暴露内部实现细节。
 */

export const GLOSSARY_KEYS = [
  "ndi",
  "jsd",
  "frame",
  "stance",
  "engine",
  "bucket_supporting",
  "bucket_contradicting",
  "bucket_context",
  "cohort",
  "primary_source",
  "independent_source",
  "freshness",
  "strength_word",
  "change",
] as const;

export type GlossaryKey = (typeof GLOSSARY_KEYS)[number];

type GlossaryDict = Record<GlossaryKey, string>;

const EN: GlossaryDict = {
  ndi: "Narrative Divergence Index: how much official and market coverage disagree on an event. It is a descriptive measure, not a predictor — high NDI means contested narratives, nothing more.",
  jsd: "Jensen-Shannon Divergence: a statistical distance between two sets of framing. Higher values mean the two camps describe the same event in measurably different ways.",
  frame: "The angle a story takes: loss, gain, responsibility, conflict, human interest, or other. Same facts can be framed differently by different outlets.",
  stance: "How a source positions itself toward the subject: supportive, critical, neutral, or abstaining (no readable stance).",
  engine: "How the annotation was produced: lexicon (deterministic dictionary rules) or llm (model-assigned). Deterministic measures are never overwritten by models.",
  bucket_supporting: "Evidence that supports the claim being examined. Each independent source contributes one best item by default.",
  bucket_contradicting: "Evidence that weakens or contradicts the claim. Requesting this bucket is tracked so missing counter-evidence stays visible.",
  bucket_context: "Background material: relevant to the subject but neither supporting nor contradicting the claim.",
  cohort: "Sources that appear in both comparison windows. Shares computed over this common set remove distortion from source-mix changes.",
  primary_source: "First-hand, official material (tier L1): statements, filings, data releases from the institutions themselves.",
  independent_source: "A distinct media organization. Multiple articles from the same outlet count as one independent source — volume is not corroboration.",
  freshness: "How current the data behind this page is. Aging means coverage has not updated recently; stale means the window may misrepresent the present.",
  strength_word: "Plain-language grade of how well the change is covered: strong, notable, minor, or insufficient evidence.",
  change: "A qualified shift detected in coverage (attention, framing, divergence, or expectation gap), gated by coverage quality before it reaches you.",
};

const ZH: GlossaryDict = {
  ndi: "叙事分歧指数：官方报道与市场报道在同一事件上的分歧程度。它是描述性指标，不是预测器——高分歧只说明叙事存在争议，不预示任何方向。",
  jsd: "Jensen-Shannon 散度：两组叙事框架之间的统计距离。数值越高，说明两方对同一事件的描述方式差异越大。",
  frame: "报道采用的叙事角度：损失、收益、责任、冲突、人物故事或其他。同一事实可以被不同媒体框定为不同故事。",
  stance: "信源对主体的立场：支持、质疑、中性或弃权（无可读立场）。",
  engine: "标注的产出方式：lexicon（确定性词典规则）或 llm（模型辅助）。确定性测量永不被模型改写。",
  bucket_supporting: "支持当前主张的证据。默认每个独立来源只展示一条最佳条目。",
  bucket_contradicting: "削弱或反驳当前主张的证据。系统会记录你查看了此桶——缺失的反证应保持可见。",
  bucket_context: "背景材料：与主体相关，但既不支持也不反驳当前主张。",
  cohort: "同时出现在两个对比窗口中的信源。基于共同来源集计算的份额可剔除来源构成变化的干扰。",
  primary_source: "一手官方材料（L1 级）：机构自身的声明、文件、数据发布。",
  independent_source: "一家独立的媒体机构。同一媒体的多篇文章只算一个独立来源——数量不等于佐证。",
  freshness: "页面数据的新鲜程度。「数据开始变旧」表示覆盖近期未更新；「数据已过期」表示窗口可能无法代表当前。",
  strength_word: "变化被覆盖程度的白话分级：证据充分 / 值得关注 / 轻微迹象 / 证据不足。",
  change: "经覆盖质量门把关后呈现给你的合格变化（注意力聚集、叙事转变、分歧升高或预期错位）。",
};

/** 其余 19 语言骨架：缺键 fallback en（与 dictionaries.ts 同策略）。 */
const SKELETONS: Partial<Record<string, Partial<GlossaryDict>>> = {
  fr: {}, es: {}, ar: {}, ru: {}, de: {}, ja: {}, pt: {}, hi: {}, ko: {},
  it: {}, tr: {}, nl: {}, pl: {}, sv: {}, fa: {}, id: {}, vi: {}, bn: {}, yue: {},
};

export const GLOSSARY: Record<string, GlossaryDict> = { en: EN, zh: ZH, ...SKELETONS };

export function glossaryFor(locale: string): GlossaryDict {
  return GLOSSARY[locale] ?? EN;
}

export function glossaryText(locale: string, key: GlossaryKey): string {
  const dict = glossaryFor(locale);
  return dict[key] ?? EN[key];
}
