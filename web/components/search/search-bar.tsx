"use client";

/**
 * 顶栏全局搜索（R7）：300ms debounce 拉取 /api/search，下拉结果报纸风。
 *
 * - AbortController 防竞态：新请求发起前中断上一个（含 timer 清理）
 * - q trim 后 <2 字符不请求（对齐后端 search_bronze 最小长度语义）
 * - 点击结果项 window.open 原文（无 url 则禁用），并埋点 source_opened
 * - Esc / 外部点击关闭；空结果「无匹配文章」；加载中不阻塞既有列表
 */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { track } from "@/lib/track";

type SearchResult = {
  item_key: string;
  source_id: string;
  title: string;
  url: string;
  published_at: string | null;
  snippet: string;
};

const DEBOUNCE_MS = 300;
const FETCH_LIMIT = 8;
const MIN_QUERY_LEN = 2;

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleDateString("zh-CN", { year: "numeric", month: "short", day: "numeric" });
}

export function SearchBar() {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const term = q.trim();
  const active = open && term.length >= MIN_QUERY_LEN;

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      if (term.length < MIN_QUERY_LEN) {
        // 短词清态：下拉仅在 term>=2 时渲染，此延迟清除无可见副作用
        setResults([]);
        setLoading(false);
        return;
      }
      setLoading(true);
      fetch(`/api/search?q=${encodeURIComponent(term)}&limit=${FETCH_LIMIT}`, {
        cache: "no-store",
        signal: controller.signal,
      })
        .then((r) => (r.ok ? r.json() : []))
        .then((rows: SearchResult[]) => setResults(Array.isArray(rows) ? rows : []))
        .catch(() => undefined)
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [term]);

  useEffect(() => {
    if (!active) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [active]);

  function openResult(item: SearchResult) {
    if (!item.url) return;
    track("source_opened", { objectId: item.item_key, fromPage: "/search-bar" });
    window.open(item.url, "_blank", "noopener,noreferrer");
  }

  return (
    <div ref={rootRef} className="relative">
      <input
        type="search"
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
        }}
        placeholder="搜索文章…"
        aria-label="搜索文章"
        className="h-7 w-40 rounded-none border border-black/10 bg-card px-2 text-xs focus:border-foreground focus:outline-none md:w-56"
      />
      {active && (
        <div className="absolute right-0 top-full z-50 mt-1 w-80 border border-black/10 bg-card shadow-sm">
          {results.length === 0 && !loading ? (
            <p className="px-3 py-3 text-xs text-muted-foreground">无匹配文章</p>
          ) : (
            <ul className="max-h-96 overflow-y-auto">
              {results.map((item) => (
                <li key={item.item_key}>
                  <button
                    type="button"
                    onClick={() => openResult(item)}
                    disabled={!item.url}
                    className="block w-full px-3 py-2 text-left hover:bg-foreground/5 disabled:cursor-default"
                  >
                    <span className="font-paper block truncate text-sm">
                      {item.title || "（无标题）"}
                    </span>
                    <span className="mt-0.5 flex items-center gap-2 text-[11px] text-muted-foreground">
                      <span>{item.source_id}</span>
                      {item.published_at && <span>{fmtDate(item.published_at)}</span>}
                    </span>
                    <span className="mt-1 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                      {item.snippet}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <Link
            href={`/investigate?q=${encodeURIComponent(term)}`}
            onClick={() => setOpen(false)}
            className="block border-t border-black/10 px-3 py-2 text-xs hover:!text-primary"
          >
            在调查台搜索 &ldquo;{term}&rdquo; →
          </Link>
        </div>
      )}
    </div>
  );
}

export default SearchBar;
