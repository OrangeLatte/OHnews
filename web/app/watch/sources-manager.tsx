"use client";

import { useEffect, useMemo, useState } from "react";

import { FRAME_BG, FRAME_TEXT, FRAME_ZH, highlightFrames } from "@/lib/highlight";

type SourceRow = {
  source_id: string;
  kind: string;
  tier: string;
  language: string;
  enabled: boolean;
  n_7d: number;
  n_30d: number;
  last_seen: string | null;
};
type ArticleRow = {
  item_key: string;
  title: string;
  url: string;
  published_at: string;
  body: string;
};

const TIERS = ["L1", "L2", "L3", "L4"];

function ArticleCard({ a }: { a: ArticleRow }) {
  const segs = useMemo(() => highlightFrames(a.title + "\n" + a.body), [a]);
  return (
    <div className="border-t border-border/50 py-2 text-sm">
      <a
        href={a.url || "#"}
        target="_blank"
        rel="noreferrer"
        className="font-medium hover:text-primary"
      >
        {a.title || "(无标题)"}
      </a>
      <p className="mt-1 text-[13px] leading-6">
        {segs.map((s, i) =>
          s.frame ? (
            <span
              key={i}
              className="rounded-sm px-0.5"
              style={{ backgroundColor: FRAME_BG[s.frame], color: FRAME_TEXT[s.frame] }}
              title={FRAME_ZH[s.frame]}
            >
              {s.text}
            </span>
          ) : (
            <span key={i}>{s.text}</span>
          ),
        )}
      </p>
    </div>
  );
}

export default function SourcesManager() {
  const [sources, setSources] = useState<SourceRow[]>([]);
  const [q, setQ] = useState("");
  const [tier, setTier] = useState<string | null>(null);
  const [lang, setLang] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [articles, setArticles] = useState<ArticleRow[]>([]);
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null);
  const [backfillDays, setBackfillDays] = useState(1);
  const [addUrl, setAddUrl] = useState("");
  const [suggestion, setSuggestion] = useState<Record<string, unknown> | null>(null);
  const [suggestNote, setSuggestNote] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    fetch("/api/sources")
      .then((r) => r.json())
      .then((d) => setSources(d.sources ?? []))
      .catch(() => undefined);
  }, []);

  const languages = useMemo(
    () => [...new Set(sources.map((s) => s.language))].sort(),
    [sources],
  );

  const filtered = sources.filter(
    (s) =>
      (tier === null || s.tier === tier) &&
      (lang === null || s.language === lang) &&
      (q === "" || s.source_id.toLowerCase().includes(q.toLowerCase())),
  );

  function toggle(sid: string) {
    if (openId === sid) {
      setOpenId(null);
      return;
    }
    setOpenId(sid);
    setArticles([]);
    setLoadingId(sid);
    fetch(`/api/sources/${sid}/articles?limit=5`)
      .then((r) => r.json())
      .then(setArticles)
      .catch(() => undefined)
      .finally(() => setLoadingId(null));
  }

  function refresh(sid: string, days: number) {
    setRefreshMsg(`采集中 ${sid}（近 ${days} 天，回溯）…`);
    fetch(`/api/sources/${sid}/refresh?days=${days}`, { method: "POST" })
      .then((r) => r.json())
      .then((d) => {
        setRefreshMsg(
          d.ok
            ? `${sid}：拉取 ${d.n_items} 条，新写入 ${d.n_written} 条`
            : `${sid} 采集失败：${d.error ?? "未知错误"}`,
        );
        return fetch("/api/sources").then((r) => r.json());
      })
      .then((d) => setSources(d.sources ?? []))
      .catch((e) => setRefreshMsg(`失败：${String(e)}`));
  }

  function suggest() {
    setSuggestion(null);
    setSuggestNote("识别中…");
    fetch("/api/sources/suggest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: addUrl.trim() }),
    })
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json()).detail ?? "建议失败");
        return r.json();
      })
      .then((d) => {
        setSuggestion(d.suggestion);
        setSuggestNote(null);
      })
      .catch((e) => setSuggestNote(`识别失败：${String(e.message ?? e)}`));
  }

  function registerSuggested() {
    if (!suggestion || adding) return;
    setAdding(true);
    fetch("/api/sources", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(suggestion),
    })
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json()).detail ?? "注册失败");
        return r.json();
      })
      .then(() => {
        setSuggestNote(`已注册 ${String(suggestion.source_id)}——可在列表中启用采集`);
        setSuggestion(null);
        setAddUrl("");
        return fetch("/api/sources").then((r) => r.json());
      })
      .then((d) => setSources(d.sources ?? []))
      .catch((e) => setSuggestNote(`注册失败：${String(e.message ?? e)}`))
      .finally(() => setAdding(false));
  }

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <h2 className="font-paper text-xl">信息源</h2>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="搜索信息源…"
          className="w-44 border border-input bg-card px-2.5 py-1.5 text-sm outline-none focus:ring-1 focus:ring-ring"
        />
        <div className="flex gap-1">
          <button
            type="button"
            onClick={() => setTier(null)}
            className={`px-2 py-1 text-xs ${tier === null ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground"}`}
          >
            全部
          </button>
          {TIERS.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTier(t === tier ? null : t)}
              className={`px-2 py-1 text-xs ${tier === t ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground"}`}
            >
              {t}
            </button>
          ))}
        </div>
        <select
          aria-label="语言筛选"
          value={lang ?? ""}
          onChange={(e) => setLang(e.target.value || null)}
          className="border border-input bg-card px-2 py-1 text-xs"
        >
          <option value="">全部语言</option>
          {languages.map((l) => (
            <option key={l} value={l}>
              {l}
            </option>
          ))}
        </select>
        <span className="ml-auto text-xs text-muted-foreground">
          {filtered.length} / {sources.length} 源 · 点行展开内容与标注
        </span>
      </div>
      <details className="mb-3 border border-border px-3 py-2 text-sm">
        <summary className="cursor-pointer text-xs text-muted-foreground">＋ 添加信源（输入网址识别）</summary>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input
            value={addUrl}
            onChange={(e) => setAddUrl(e.target.value)}
            placeholder="https://example.com/rss.xml"
            className="min-w-0 flex-1 border border-input bg-card px-2.5 py-1.5 text-sm"
          />
          <button
            type="button"
            onClick={suggest}
            disabled={!addUrl.trim()}
            className="border border-border px-2 py-1 text-xs hover:bg-muted disabled:opacity-50"
          >
            识别
          </button>
        </div>
        {suggestNote && <p className="mt-2 text-xs text-muted-foreground">{suggestNote}</p>}
        {suggestion && (
          <div className="mt-2 border border-border/60 p-2 text-xs">
            <p className="font-mono">
              {String(suggestion.source_id)} · {String(suggestion.adapter)} ·{" "}
              {String(suggestion.tier)} · {String(suggestion.language)}
            </p>
            <p className="mt-1 text-muted-foreground">
              启发式建议（主机名/路径/域名推断），确认前请人工核对等级与语言。
            </p>
            <button
              type="button"
              onClick={registerSuggested}
              disabled={adding}
              className="mt-2 border border-border px-2 py-1 hover:bg-muted disabled:opacity-50"
            >
              {adding ? "注册中…" : "确认注册"}
            </button>
          </div>
        )}
      </details>
      {refreshMsg && <p className="mb-2 text-xs text-primary">{refreshMsg}</p>}
      <div className="border-t border-foreground/20">
        {filtered.map((s) => (
          <div key={s.source_id} className="border-b border-border/50">
            <button
              type="button"
              onClick={() => toggle(s.source_id)}
              className="flex w-full items-baseline gap-3 px-1 py-2 text-left text-sm hover:bg-muted/40"
            >
              <span className="w-8 font-mono text-[11px] text-muted-foreground">{s.tier}</span>
              <span className="w-36 truncate font-mono text-[13px]">{s.source_id}</span>
              <span className="w-8 text-[11px] text-muted-foreground">{s.language}</span>
              <span className="flex-1 font-mono text-xs text-muted-foreground">
                7d {s.n_7d} · 30d {s.n_30d}
              </span>
              {!s.enabled && <span className="text-[11px] text-muted-foreground">已停用</span>}
              <span
                className={`h-1.5 w-1.5 rounded-full ${s.n_7d > 0 ? "bg-[var(--color-ok)]" : "bg-border"}`}
                title={s.n_7d > 0 ? "近7日有产出" : "近7日无产出"}
              />
              <span className="text-xs text-muted-foreground">{openId === s.source_id ? "收起" : "展开"}</span>
            </button>
            {openId === s.source_id && (
              <div className="px-6 pb-4">
                <div className="mb-1 flex items-center justify-end gap-3">
                  <select
                    aria-label={`回溯天数 ${s.source_id}`}
                    value={backfillDays}
                    onChange={(e) => setBackfillDays(Number(e.target.value))}
                    className="border border-input bg-card px-1.5 py-1 text-[11px]"
                  >
                    {[1, 7, 30, 90].map((d) => (
                      <option key={d} value={d}>
                        近 {d} 天
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() => refresh(s.source_id, backfillDays)}
                    className="border border-border px-2 py-1 text-[11px] hover:bg-muted"
                  >
                    {loadingId === s.source_id ? "采集中…" : "立即采集"}
                  </button>
                </div>
                {loadingId === s.source_id && (
                  <p className="py-2 text-xs text-muted-foreground">加载文章…</p>
                )}
                {articles.map((a) => (
                  <ArticleCard key={a.item_key} a={a} />
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
