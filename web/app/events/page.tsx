"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { api } from "@/lib/api";
import { divergenceLevel } from "@/lib/insight";

type EventRow = {
  event_id: string;
  title: string;
  entities: string[];
  as_of: string;
  ndi: number | null;
  ndi_status: string;
  n_sources: number;
};

export default function EventsPage() {
  const [events, setEvents] = useState<EventRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    const qs = new URLSearchParams(window.location.search).get("q");
    api
      .events(30)
      .then((evts) => {
        setEvents(evts);
        if (qs) setQ(qs);
      })
      .catch((err) => setError(String(err)));
  }, []);

  if (error) return <p className="text-destructive">加载失败：{error}</p>;
  if (!events) return <p className="text-sm text-muted-foreground">加载事件中…</p>;

  const ql = q.trim().toLowerCase();
  const filtered = ql
    ? events.filter(
        (e) =>
          e.title.toLowerCase().includes(ql) ||
          e.entities.some((x) => x.toLowerCase().includes(ql)),
      )
    : events;

  return (
    <div className="flex flex-col gap-6">
      <header>
        <p className="paper-kicker">03 / EVENTS</p>
        <h1 className="font-paper mt-1 text-3xl tracking-tight">事件与叙事</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          每个事件 = 一组被不同来源共同报道的变化。点击进入七段式解读：
          发生了什么 → 为什么重要 → 谁在分歧 → 证据在哪。
        </p>
      </header>

      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="按实体或标题筛选（如 fed / tariff）"
        className="w-full max-w-md border border-border bg-card px-3 py-2 text-sm outline-none focus:border-primary"
      />

      {filtered.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {ql ? `没有匹配「${q}」的事件。` : "近 30 天无事件（信息量不足时系统选择弃权而非硬凑）。"}
        </p>
      ) : (
        <div className="flex flex-col">
          {filtered.map((e) => {
            const lv = divergenceLevel(e.ndi);
            return (
              <Link
                key={e.event_id}
                href={`/events/${e.event_id}`}
                className="flex items-baseline gap-4 border-b border-border/60 py-3 hover:bg-muted/30"
              >
                <span className="font-mono text-xs text-muted-foreground">
                  {e.as_of.slice(0, 10)}
                </span>
                <span className="flex-1 truncate font-paper text-base">{e.title}</span>
                <span className="font-mono text-[11px] text-muted-foreground">
                  {e.n_sources} 源
                </span>
                <span
                  className="w-36 text-right text-xs font-medium"
                  style={{ color: lv.color }}
                >
                  {lv.zh}
                </span>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
