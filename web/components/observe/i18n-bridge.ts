"use client";

import { useT } from "@/lib/i18n/use-t";

/**
 * i18n 过渡桥：t(key) 命中字典则用译文；缺键时回退调用处的英文字面量。
 * 目的：dictionaries.ts 尚未收录的新键先用英文渲染，键补齐后自动切换为译文。
 */

type TParams = Record<string, string | number>;

export function useOt() {
  const t = useT();
  return (key: string, en: string, params?: TParams): string => {
    const resolved = t(key, params);
    if (resolved !== key) return resolved;
    let out = en;
    if (params) {
      for (const [k, v] of Object.entries(params)) {
        out = out.split(`{${k}}`).join(String(v));
      }
    }
    return out;
  };
}
