"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type EventRow } from "@/lib/api";

export default function AnalyzeIndexPage() {
  const [events, setEvents] = useState<EventRow[]>([]);
  const [filter, setFilter] = useState<string>("");

  useEffect(() => {
    api
      .events(30)
      .then(setEvents)
      .catch(() => setEvents([]));
  }, []);

  const f = filter.toLowerCase();
  const shown = events.filter((e) => !f || e.event_id.includes(f) || e.title.includes(f) || e.entities.some((x) => x.includes(f)));

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold">分析工作台</h1>
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="按实体筛选…"
          className="w-48 rounded-md border border-border bg-background px-3 py-1.5 text-sm outline-none focus:ring-1 focus:ring-ring"
        />
        <span className="text-xs text-muted-foreground">
          选择事件进入解剖视图：结论 → 分歧构成 → 光谱 → 证据
        </span>
      </div>
      <Card>
        <CardContent className="pt-4">
          {shown.length === 0 ? (
            <p className="text-sm text-muted-foreground">暂无事件</p>
          ) : (
            <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
              {shown.map((e) => (
                <Link
                  key={e.event_id}
                  href={`/analyze/${e.event_id}`}
                  className="group flex items-center gap-3 rounded-md border border-border/60 px-3 py-2 transition-colors hover:border-ring hover:bg-muted/40"
                >
                  <span className="font-mono text-xs text-muted-foreground">
                    {e.as_of.slice(0, 10)}
                  </span>
                  <span className="flex-1 truncate text-sm group-hover:text-foreground">
                    {e.title || e.event_id}
                  </span>
                  {e.entities.slice(0, 2).map((x) => (
                    <Badge key={x} variant="outline" className="text-[10px]">
                      {x}
                    </Badge>
                  ))}
                  {e.ndi != null ? (
                    <span className="font-mono text-xs text-emerald-400">
                      NDI {e.ndi.toFixed(3)}
                    </span>
                  ) : (
                    <span className="text-xs text-muted-foreground">abstain</span>
                  )}
                </Link>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle className="text-sm text-muted-foreground">递进路径</CardTitle>
        </CardHeader>
        <CardContent className="text-xs leading-6 text-muted-foreground">
          ① <b className="text-foreground">结论</b>：NDI 水平 + 分歧簇对（谁和谁分歧）
          → ② <b className="text-foreground">主体对立</b>：分歧落在哪个主体（官方 vs 市场谁挺谁批）
          → ③ <b className="text-foreground">光谱</b>：点主体过滤，逐句看主体-动作-方向结构
          → ④ <b className="text-foreground">证据</b>：一键引用回溯原文。
        </CardContent>
      </Card>
    </div>
  );
}
