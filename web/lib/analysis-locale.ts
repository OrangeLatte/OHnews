"use client";

/**
 * 分析输出语言偏好（analysis_locale）：独立于 UI 语言（ui_locale）的
 * 三独立字段之一。存 localStorage "oh-analysis-locale"，仅支持 zh/en；
 * 未设置时 readAnalysisLocale 返回 ""（请求不透传，后端维持默认行为）。
 * useSyncExternalStore 模式同 use-t.tsx（SSR 安全 / 无 set-state-in-effect）。
 */

import { useCallback, useSyncExternalStore } from "react";

const STORAGE_KEY = "oh-analysis-locale";
const DEFAULT_LOCALE = "en";

const listeners = new Set<() => void>();
function notify(): void {
  for (const cb of listeners) cb();
}
function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  window.addEventListener("storage", cb);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", cb);
  };
}

/** 显式设置值（未设置/非法 → 默认 en），设置面板展示用。 */
function getSnapshot(): "zh" | "en" {
  const v = window.localStorage.getItem(STORAGE_KEY);
  return v === "zh" || v === "en" ? v : DEFAULT_LOCALE;
}

/** 请求透传值：仅当用户显式设置过才返回，否则 ""（不透传）。 */
export function readAnalysisLocale(): "zh" | "en" | "" {
  const v = window.localStorage.getItem(STORAGE_KEY);
  return v === "zh" || v === "en" ? v : "";
}

export function useAnalysisLocale(): ["zh" | "en", (v: "zh" | "en") => void] {
  const value = useSyncExternalStore<"zh" | "en">(
    subscribe,
    getSnapshot,
    () => DEFAULT_LOCALE,
  );
  const setValue = useCallback((v: "zh" | "en") => {
    window.localStorage.setItem(STORAGE_KEY, v);
    notify();
  }, []);
  return [value, setValue];
}
