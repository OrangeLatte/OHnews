"use client";

/**
 * i18n 运行时（M5 A1，自建轻量方案）：
 * LanguageProvider 持久化 localStorage；html.lang/dir 同步（RTL：ar/fa）；
 * useT() 返回 t(key, params)——缺键 fallback en，再缺返回 key 本身。
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { DICTS } from "./dictionaries";
import { DEFAULT_LOCALE, dirOf, isLocale, localeMeta } from "./locales";

type LangContextValue = {
  locale: string;
  dir: "ltr" | "rtl";
  setLocale: (code: string) => void;
};

const LangContext = createContext<LangContextValue | null>(null);
const STORAGE_KEY = "oh-locale";

/* localStorage external store（同 R5c FilterContext 模式：SSR 安全/无 set-state-in-effect） */
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
function getSnapshot(): string {
  const v = window.localStorage.getItem(STORAGE_KEY);
  return v && isLocale(v) ? v : DEFAULT_LOCALE;
}
function getServerSnapshot(): string {
  return DEFAULT_LOCALE;
}

function interpolate(template: string, params?: Record<string, string | number>): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (_, k: string) =>
    k in params ? String(params[k]) : `{${k}}`,
  );
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const locale = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const setLocale = useCallback((code: string) => {
    if (!isLocale(code)) return;
    window.localStorage.setItem(STORAGE_KEY, code);
    notify();
  }, []);

  useEffect(() => {
    const html = document.documentElement;
    html.lang = locale;
    html.dir = dirOf(locale);
  }, [locale]);

  const value = useMemo<LangContextValue>(
    () => ({ locale, dir: dirOf(locale), setLocale }),
    [locale, setLocale],
  );

  return <LangContext.Provider value={value}>{children}</LangContext.Provider>;
}

export function useLocale(): LangContextValue {
  const ctx = useContext(LangContext);
  if (!ctx) {
    // 未包裹 Provider 时退化为默认语言（不抛错，渐进接入）
    return { locale: DEFAULT_LOCALE, dir: dirOf(DEFAULT_LOCALE), setLocale: () => undefined };
  }
  return ctx;
}

export function useT() {
  const { locale } = useLocale();
  return useCallback(
    (key: string, params?: Record<string, string | number>): string => {
      const dict = DICTS[locale] ?? {};
      const raw = dict[key] || DICTS[DEFAULT_LOCALE]?.[key] || key;
      return interpolate(raw, params);
    },
    [locale],
  );
}

export { localeMeta };
