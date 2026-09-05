"use client";

/**
 * OBSERVE 页 URL 状态（?mode=&days=&entity=）：history.replaceState 同步 + useSyncExternalStore 订阅。
 * getServerSnapshot 返回默认值，规避 SSR hydration mismatch；仅 replaceState 不触发 popstate。
 * entity 来自搜索跳转（/observe?mode=entities&days=30&entity=x）等入口，页面层消费后可清除。
 */

export const OBSERVE_MODES = [
  "signal",
  "flow",
  "narrative",
  "divergence",
  "emotion",
  "entities",
  "inbox",
] as const;

export type ObserveMode = (typeof OBSERVE_MODES)[number];

/** days=0 表示 All 窗口（后端请求时按 3650 展开 / inbox 省略 days）。 */
export type ObserveUrlState = { mode: ObserveMode; days: number; entity: string };

const DEFAULTS: ObserveUrlState = { mode: "signal", days: 7, entity: "" };

const DAY_VALUES = new Set(["0", "1", "7", "30"]);

let cacheRaw: string | null = null;
let cacheVal: ObserveUrlState = DEFAULTS;
const subs = new Set<() => void>();

function parse(raw: string): ObserveUrlState {
  const p = new URLSearchParams(raw);
  const m = p.get("mode");
  const d = p.get("days");
  const e = p.get("entity");
  return {
    mode: (OBSERVE_MODES as readonly string[]).includes(m ?? "") ? (m as ObserveMode) : DEFAULTS.mode,
    days: d !== null && DAY_VALUES.has(d) ? Number(d) : DEFAULTS.days,
    entity: e ?? DEFAULTS.entity,
  };
}

function notify(): void {
  for (const cb of subs) cb();
}

export function subscribeUrl(cb: () => void): () => void {
  subs.add(cb);
  window.addEventListener("popstate", notify);
  return () => {
    subs.delete(cb);
    window.removeEventListener("popstate", notify);
  };
}

export function getUrlSnapshot(): ObserveUrlState {
  const raw = typeof window === "undefined" ? "" : window.location.search;
  if (cacheRaw !== raw) {
    cacheRaw = raw;
    cacheVal = parse(raw);
  }
  return cacheVal;
}

export function getUrlServerSnapshot(): ObserveUrlState {
  return DEFAULTS;
}

export function setUrlState(next: Partial<ObserveUrlState>): void {
  const merged = { ...getUrlSnapshot(), ...next };
  const p = new URLSearchParams();
  if (merged.mode !== DEFAULTS.mode) p.set("mode", merged.mode);
  if (merged.days !== DEFAULTS.days) p.set("days", String(merged.days));
  if (merged.entity) p.set("entity", merged.entity);
  const qs = p.toString();
  const base = window.location.pathname;
  window.history.replaceState(null, "", qs ? `${base}?${qs}` : base);
  cacheRaw = null;
  notify();
}
