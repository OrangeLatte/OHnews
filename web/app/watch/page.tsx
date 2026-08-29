"use client";

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api, type SignalRow, type WatchRow } from "@/lib/api";

const TYPE_META: Record<string, { label: string; hint: string; color: string }> = {
  entity: { label: "实体", hint: "实体 id（如 fed / ecb / trump）", color: "#58a6ff" },
  topic: { label: "主题", hint: "关键词，逗号分隔（如 衰退,关税）", color: "#d29922" },
  question: { label: "问题", hint: "研究问题句（Agent 回答在 R4 接入）", color: "#bc8cff" },
};

function summaryLines(w: WatchRow): string[] {
  const s = w.last_summary as Record<string, unknown> | null;
  if (!s) return ["尚未刷新"];
  const lines: string[] = [];
  if (s.kind === "entity") {
    lines.push(`${s.n_signals} 个相关 Signal · ${s.n_events} 个关联事件`);
    const sigs = (s.signals as SignalRow[]) ?? [];
    for (const g of sigs.slice(0, 3))
      lines.push(`· [${g.kind}] ${g.title}（strength ${Math.round(g.strength)}）`);
    const evs = (s.events as { event_id: string; title: string }[]) ?? [];
    for (const e of evs.slice(0, 3)) lines.push(`· 事件 ${e.event_id}：${e.title}`);
  } else if (s.kind === "topic") {
    lines.push(`近 7 日 ${s.n_articles} 篇文章命中「${(s.terms as string[]).join(" / ")}」`);
    const tops = (s.top_sources as { source_id: string; n: number }[]) ?? [];
    if (tops.length)
      lines.push(`主要来源：${tops.map((t) => `${t.source_id}(${t.n})`).join("、")}`);
    lines.push(`${s.n_events} 个关联事件`);
  } else {
    lines.push(`问题已记录 · 匹配 ${s.n_matched_events} 个事件 · Agent 深度回答即将接入`);
    const evs = (s.events as { event_id: string; title: string }[]) ?? [];
    for (const e of evs.slice(0, 3)) lines.push(`· 事件 ${e.event_id}：${e.title}`);
  }
  return lines;
}

export default function WatchPage() {
  const [watches, setWatches] = useState<WatchRow[]>([]);
  const [type, setType] = useState("entity");
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    api.watches().then((r) => setWatches(r.watches)).catch((e) => setError(String(e)));
  }, []);
  useEffect(load, [load]);

  async function add() {
    if (!query.trim()) return;
    setBusy("add");
    try {
      await api.watchAdd(type, query);
      setQuery("");
      load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  async function refresh(id: string) {
    setBusy(id);
    try {
      await api.watchRefresh(id);
      load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <div>
        <h1 className="font-serif text-2xl tracking-tight">Watch</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          订阅实体、主题与研究问题——系统在你关心的方向上持续监测变化。
        </p>
      </div>

      <Card>
        <CardContent className="flex flex-col gap-3 pt-4">
          <div className="flex gap-2">
            {(Object.keys(TYPE_META) as string[]).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setType(t)}
                className={`rounded-md border px-3 py-1.5 text-sm transition-colors ${
                  type === t
                    ? "border-transparent text-white"
                    : "border-border text-muted-foreground hover:text-foreground"
                }`}
                style={type === t ? { backgroundColor: TYPE_META[t].color } : undefined}
              >
                {TYPE_META[t].label}
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={TYPE_META[type].hint}
              onKeyDown={(e) => e.key === "Enter" && add()}
            />
            <Button onClick={add} disabled={busy === "add"}>
              {busy === "add" ? "添加中…" : "订阅"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {error && <p className="text-destructive">{error}</p>}

      <div className="flex flex-col gap-3">
        {watches.length === 0 ? (
          <p className="text-sm text-muted-foreground">暂无订阅——从上方添加第一个 Watch。</p>
        ) : (
          watches.map((w) => {
            const meta = TYPE_META[w.type] ?? TYPE_META.entity;
            return (
              <Card key={w.watch_id}>
                <CardHeader className="pb-2">
                  <div className="flex items-center gap-2">
                    <Badge
                      variant="outline"
                      className="text-[10px]"
                      style={{ borderColor: meta.color, color: meta.color }}
                    >
                      {meta.label}
                    </Badge>
                    <CardTitle className="flex-1 font-mono text-sm">{w.query}</CardTitle>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy === w.watch_id}
                      onClick={() => refresh(w.watch_id)}
                    >
                      {busy === w.watch_id ? "…" : "刷新"}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-muted-foreground"
                      onClick={() => api.watchRemove(w.watch_id).then(load)}
                    >
                      删除
                    </Button>
                  </div>
                  {w.last_checked_at && (
                    <p className="text-xs text-muted-foreground">
                      最近刷新 {w.last_checked_at.replace("T", " ").slice(0, 16)}
                    </p>
                  )}
                </CardHeader>
                <CardContent className="pt-0">
                  <ul className="space-y-1 text-sm">
                    {summaryLines(w).map((line, i) => (
                      <li key={i} className={i === 0 ? "text-foreground" : "text-muted-foreground"}>
                        {line}
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            );
          })
        )}
      </div>
    </div>
  );
}
