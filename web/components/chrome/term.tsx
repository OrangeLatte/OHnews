"use client";

/**
 * Term（A2）：全站指标/标题旁的「?」解释组件。
 * hover / 键盘 focus 显示当前语言解释（缺键 fallback en）；报纸风浅色气泡。
 */

import { glossaryText, type GlossaryKey } from "@/lib/i18n/glossary";
import { useLocale } from "@/lib/i18n/use-t";

export function Term({ k, label }: { k: GlossaryKey; label?: string }) {
  const { locale } = useLocale();
  const text = glossaryText(locale, k);
  return (
    <span className="term-tip">
      <button
        type="button"
        className="term-mark"
        aria-label={label ?? k}
        aria-describedby={`term-${k}`}
      >
        ?
      </button>
      <span role="tooltip" id={`term-${k}`} className="term-bubble">
        {text}
      </span>
    </span>
  );
}
