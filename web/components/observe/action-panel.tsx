"use client";

import { useOt } from "@/components/observe/i18n-bridge";

import { useEffect, useState } from "react";

type Pulse = { daily: { date: string; count: number }[]; top_actions: { action: string; count: number }[] };

export function ActionPanel({ days }: { days: number }) {
  const [data, setData] = useState<Pulse | null>(null);
  useEffect(() => { fetch(`/api/annotations/actions?days=${days}`).then((r) => r.json()).then(setData).catch(() => setData({ daily: [], top_actions: [] })); }, [days]);
  const ot = useOt();
  if (!data) return <p className="text-xs text-muted-foreground">{ot("observe.loading", "Loading…")}</p>;
  const max = Math.max(1, ...data.daily.map((x) => x.count));
  return <section className="mt-6 border-t pt-4"><h3 className="text-sm font-semibold">{ot("observe.action.title", "Action pulse")}</h3><p className="mb-3 text-xs text-muted-foreground">{ot("observe.action.desc", "SRL action mentions by article publication date · not sentiment")}</p>{data.daily.length ? <div className="flex items-stretch gap-2"><div aria-hidden className="flex w-8 flex-col justify-between py-0.5 text-right text-[9px] text-muted-foreground"><span>{max}</span><span>{Math.round(max / 2)}</span><span>0</span></div><div className="min-w-0 flex-1"><div className="flex h-24 items-end gap-1" aria-label="Daily action volume">{data.daily.map((x) => <div key={x.date} tabIndex={0} role="img" aria-label={`${x.date}: ${x.count}`} title={`${x.date}: ${x.count}`} className="group relative flex-1 cursor-default outline-none focus-visible:ring-1 focus-visible:ring-[#5e83a8]" ><span aria-hidden className="pointer-events-none absolute -top-4 left-1/2 -translate-x-1/2 rounded-[3px] border bg-card px-1 text-[9px] font-semibold tabular-nums opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">{x.count}</span><div className="w-full bg-[#5e83a8]/70 transition-colors group-hover:bg-[#5e83a8]" style={{ height: `${Math.max(4, x.count / max * 100)}%` }} /></div>)}</div><div aria-hidden className="mt-0.5 flex gap-1 text-[9px] text-muted-foreground">{data.daily.map((x) => <span key={x.date} className="min-w-0 flex-1 truncate text-center">{x.date.slice(5)}</span>)}</div></div></div> : <p className="text-xs text-muted-foreground">{ot("observe.action.empty", "No SRL action coverage in this window.")}</p>}<div className="mt-3 flex flex-wrap gap-2">{data.top_actions.map((x) => <span key={x.action} className="rounded border px-2 py-1 text-xs">{x.action} <b>{x.count}</b></span>)}</div></section>;
}
