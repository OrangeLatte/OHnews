"use client";

/**
 * R5c 全局过滤器（REFACTOR_V2.md §5.2）：React Context + URL query 持久化。
 *
 * - 八个过滤维度，全部可选（未设置 = 页面用各自默认值）
 * - URL 即唯一真相（external store 模式）：useSyncExternalStore 订阅
 *   popstate + 内部 emit；setFilter 写 URL（history.replaceState，可分享、
 *   不污染浏览历史）后手动 emit 触发订阅者重读
 * - 刻意不用 useSearchParams：客户端组件读它会让页面在 next build 时
 *   要求 Suspense 边界（R0 在 events 页踩过），window.location 轻实现无此约束
 * - 快照缓存：getSnapshot 必须返回稳定引用（query 串不变即复用同一对象），
 *   否则 useSyncExternalStore 会无限重渲染
 *
 * 服务端过滤优先（API 加 filter 参数）是 R6+ 的接入方式；
 * 本层只提供状态与 URL 绑定，不做数据获取。
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";

export const FILTER_KEYS = [
  "timeRange",
  "entity",
  "entityType",
  "source",
  "frame",
  "emotion",
  "signalKind",
  "language",
] as const;

export type FilterKey = (typeof FILTER_KEYS)[number];

export type FilterState = Partial<Record<FilterKey, string>>;

type FilterContextValue = {
  filters: FilterState;
  setFilter: (key: FilterKey, value: string | null) => void;
  clearFilters: () => void;
  /** 便捷判定：无任何过滤条件生效 */
  isDefault: boolean;
};

const FilterContext = createContext<FilterContextValue | null>(null);

/* ---------- URL external store ---------- */

const listeners = new Set<() => void>();
const cache: { query: string; state: FilterState } = { query: "", state: {} };

function parseState(query: string): FilterState {
  const params = new URLSearchParams(query);
  const state: FilterState = {};
  for (const key of FILTER_KEYS) {
    const value = params.get(key);
    if (value) state[key] = value;
  }
  return state;
}

/** getSnapshot：query 不变时返回同一引用（稳定快照约束）。 */
function getSnapshot(): FilterState {
  const query = window.location.search;
  if (query !== cache.query) {
    cache.query = query;
    cache.state = parseState(query);
  }
  return cache.state;
}

const EMPTY_STATE: FilterState = {};

function getServerSnapshot(): FilterState {
  return EMPTY_STATE;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  window.addEventListener("popstate", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("popstate", listener);
  };
}

function emit(): void {
  for (const listener of listeners) listener();
}

function writeToUrl(state: FilterState): void {
  const params = new URLSearchParams(window.location.search);
  for (const key of FILTER_KEYS) {
    const value = state[key];
    if (value) params.set(key, value);
    else params.delete(key);
  }
  const query = params.toString();
  const next = `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`;
  window.history.replaceState(window.history.state, "", next);
}

/* ---------- context ---------- */

export function FilterProvider({ children }: { children: ReactNode }) {
  const filters = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const setFilter = useCallback((key: FilterKey, value: string | null) => {
    const next = { ...getSnapshot() };
    if (value) next[key] = value;
    else delete next[key];
    writeToUrl(next);
    emit();
  }, []);

  const clearFilters = useCallback(() => {
    writeToUrl({});
    emit();
  }, []);

  const value = useMemo<FilterContextValue>(
    () => ({
      filters,
      setFilter,
      clearFilters,
      isDefault: Object.keys(filters).length === 0,
    }),
    [filters, setFilter, clearFilters],
  );

  return <FilterContext.Provider value={value}>{children}</FilterContext.Provider>;
}

export function useFilters(): FilterContextValue {
  const ctx = useContext(FilterContext);
  if (!ctx) throw new Error("useFilters must be used within FilterProvider");
  return ctx;
}
