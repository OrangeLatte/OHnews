/**
 * 运行错误友好化（P2 打磨）：匹配原始 error 文本特征 → i18n 标题键 + 完整原文。
 * 诚实纪律：只美化标题，根因原文始终保留在 detail（调用方以 details/summary 折叠展示）。
 */

/** 特征匹配表：顺序即优先级（余额 402 先于通用 ValidationError 等）。 */
const PATTERNS: { key: string; test: RegExp }[] = [
  { key: "case.errBalance", test: /\b402\b|insufficient balance/i },
  { key: "case.errValidation", test: /ValidationError|validation error/i },
  { key: "case.errTimeout", test: /TimeoutError|timed out/i },
  { key: "case.errNetwork", test: /Connection error/i },
  { key: "case.errFiltered", test: /contentFilter|\b1301\b/ },
];

const TITLE_MAX = 120;

export type FriendlyError = {
  /** 匹配成功时的 i18n 键（case.errBalance 等）；未匹配为空串 */
  titleKey: string;
  /** 未匹配时的降级标题（原文首行截断 120 字符） */
  fallbackTitle: string;
  /** 完整原文（折叠详情，根因不丢） */
  detail: string;
};

/** 模块级纯函数：raw 为空时按未知错误降级处理。 */
export function friendlyError(raw: string): FriendlyError {
  const text = raw ?? "";
  for (const p of PATTERNS) {
    if (p.test.test(text)) {
      return { titleKey: p.key, fallbackTitle: "", detail: text };
    }
  }
  const firstLine = (text.split("\n")[0] ?? text).trim();
  const fallbackTitle =
    firstLine.length > TITLE_MAX ? `${firstLine.slice(0, TITLE_MAX)}…` : firstLine;
  return { titleKey: "", fallbackTitle, detail: text };
}

/** 便捷取标题：命中走 i18n，未匹配走截断首行（原文为空时返回空串）。 */
export function friendlyErrorTitle(raw: string, t: (key: string) => string): string {
  const fe = friendlyError(raw);
  return fe.titleKey ? t(fe.titleKey) : fe.fallbackTitle;
}
