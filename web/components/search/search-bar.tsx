"use client";

/**
 * 顶栏全局搜索（R7 + P1-A 五类型精确定位）：300ms debounce 拉取 /api/search，下拉结果报纸风。
 *
 * - AbortController 防竞态：新请求发起前中断上一个（含 timer 清理）
 * - q trim 后 <2 字符不请求（对齐后端 search_bronze 最小长度语义）
 * - P1-A 分流（结果必带 kind + 稳定 ID，禁止裸跳）：
 *   article → 研究此文流（取全文建 Case）；event → 有实体跳实体时间线，
 *   无实体诚实降级 inbox 预填标题前缀（q= 主路径）；entity → 实体时间线；
 *   case → 案例工作台；monitor → 监测台 open= 深链。任何路径先关浮层。
 * - 「原文」次链接仅文章有 url 时显示（window.open 外跳）
 * - Esc / 外部点击关闭；空结果「无匹配」；加载中不阻塞既有列表
 */

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { objectApi } from "@/lib/object-api";
import { track } from "@/lib/track";
import { useT } from "@/lib/i18n/use-t";
import { toast } from "@/components/ui/toast";

type SearchResultKind = "article" | "event" | "entity" | "case" | "monitor";

type SearchResult = {
  kind: SearchResultKind;
  item_key?: string;
  id?: string;
  source_id?: string;
  /** 事件主实体（P1-A 起后端回传；无实体为 null/缺省 → inbox 降级路径）。 */
  entity?: string | null;
  /** case/monitor 状态（后端 P1-A 起回传，可选）。 */
  status?: string;
  /** monitor 目标引用（entity:fed 等，可选）。 */
  target_ref?: string;
  title: string;
  url: string;
  published_at: string | null;
  snippet: string;
};

const DEBOUNCE_MS = 300;
const FETCH_LIMIT = 8;
const MIN_QUERY_LEN = 2;

const stampId = (prefix: string) =>
  `${prefix}-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleDateString("zh-CN", { year: "numeric", month: "short", day: "numeric" });
}

export function SearchBar() {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const t = useT();

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

  /** 文章点击 = 研究此文：取 bronze 全文 → 建 Research Case → 挂载文档 → 跳转工作台。 */
  async function research(item: SearchResult) {
    if (!item.source_id || !item.item_key || busyId) return;
    const key = item.item_key;
    setBusyId(key);
    try {
      const detail = await objectApi.articleDetail(item.source_id, key);
      const now = new Date().toISOString();
      const caseId = stampId("case");
      const docId = stampId(`doc-${item.source_id}`);
      await objectApi.createCase({
        case_id: caseId,
        question: detail.title || item.title || caseId,
        origin: "observe",
        created_at: now,
        updated_at: now,
      });
      await objectApi.attachDocument(caseId, {
        document_id: docId,
        document_revision_id: `rev-${docId}`,
        source_id: item.source_id,
        body: detail.body,
        language: detail.language,
        canonical_url: detail.url || item.url,
        title: detail.title || item.title || "",
      });
      track("case_created", { objectId: caseId, fromPage: "/search-bar" });
      toast.success(t("search.researchOk"));
      setOpen(false);
      setQ("");
      router.push(`/cases/${caseId}`);
    } catch {
      toast.error(t("search.researchFail"));
    } finally {
      setBusyId(null);
    }
  }

  /** P1-A 五类型分流：kind + 稳定 ID 驱动跳转；任何路径先关浮层，ID 缺失不动（禁止裸跳）。 */
  function onOpen(item: SearchResult) {
    setOpen(false);
    switch (item.kind) {
      case "event": {
        if (item.id) track("change_opened", { objectId: item.id, fromPage: "/search-bar" });
        if (item.entity) {
          router.push(
            `/observe?mode=entities&days=30&entity=${encodeURIComponent(item.entity)}`,
          );
        } else {
          // 诚实降级：事件无实体 → inbox 预填标题前缀（CJK 8 字 / 拉丁 12 字符），不裸跳
          const cjk = /[\u4e00-\u9fff]/.test(item.title);
          router.push(`/observe?mode=inbox&q=${encodeURIComponent(item.title.slice(0, cjk ? 8 : 12))}`);
        }
        return;
      }
      case "entity":
        if (item.id) {
          router.push(`/observe?mode=entities&days=30&entity=${encodeURIComponent(item.id)}`);
        }
        return;
      case "case":
        if (item.id) router.push(`/cases/${encodeURIComponent(item.id)}`);
        return;
      case "monitor":
        if (item.id) router.push(`/watch?tab=monitors&open=${encodeURIComponent(item.id)}`);
        return;
      default:
        void research(item);
    }
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
        placeholder={t("search.placeholder")}
        aria-label={t("search.placeholder")}
        className="h-7 w-40 rounded-none border border-black/10 bg-card px-2 text-xs focus:border-foreground focus:outline-none md:w-56"
      />
      {active && (
        <div className="absolute right-0 top-full z-50 mt-1 w-80 border border-black/10 bg-card shadow-sm">
          {results.length === 0 && !loading ? (
            <p className="px-3 py-3 text-xs text-muted-foreground">{t("search.noMatch")}</p>
          ) : (
            <ul className="max-h-96 overflow-y-auto">
              {results.map((item) => {
                const key = item.item_key ?? item.id ?? "";
                const busy = busyId === item.item_key;
                return (
                  <li key={key} className="border-b border-black/5 last:border-b-0">
                    <div
                      role="button"
                      tabIndex={0}
                      onClick={() => onOpen(item)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") onOpen(item);
                      }}
                      aria-busy={busy}
                      className="block w-full cursor-pointer px-3 py-2 text-left hover:bg-foreground/5"
                    >
                      <span className="font-paper flex items-center gap-1 truncate text-sm">
                        <span className="mr-1 shrink-0 border border-black/20 px-1 text-[10px] align-middle">
                          {t(`search.kind.${item.kind}`)}
                        </span>
                        {item.title || t("search.untitled")}
                      </span>
                      <span className="mt-0.5 flex items-center gap-2 text-[11px] text-muted-foreground">
                        {item.kind === "article" && <span>{item.source_id}</span>}
                        {item.kind === "event" && <span>{item.entity ?? t("search.eventTag")}</span>}
                        {item.kind === "entity" && <span className="font-mono">{item.id}</span>}
                        {item.status && <span>{item.status}</span>}
                        {item.kind === "monitor" && item.target_ref && (
                          <span className="font-mono">{item.target_ref}</span>
                        )}
                        {item.published_at && <span>{fmtDate(item.published_at)}</span>}
                      </span>
                      <span className="mt-1 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                        {item.snippet}
                      </span>
                    </div>
                    {item.kind === "article" && (
                      <div className="flex items-center gap-3 px-3 pb-2 text-[11px]">
                        <button
                          type="button"
                          onClick={() => research(item)}
                          disabled={busy}
                          className="border border-foreground/30 px-1.5 py-0.5 hover:!text-primary disabled:opacity-50"
                        >
                          {busy ? t("search.researching") : t("search.researchThis")}
                        </button>
                        {item.url && (
                          <a
                            href={item.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            className="text-muted-foreground hover:!text-primary"
                          >
                            {t("search.openOriginal")} ↗
                          </a>
                        )}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          <a
            href={`/cases?q=${encodeURIComponent(term)}`}
            onClick={() => setOpen(false)}
            className="block border-t border-black/10 px-3 py-2 text-xs hover:!text-primary"
          >
            {t("search.searchInCases", { q: term })} →
          </a>
        </div>
      )}
    </div>
  );
}

export default SearchBar;
