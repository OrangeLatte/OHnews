"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, type EventRow, type StatusInfo } from "@/lib/api";

function fmtNdi(ndi: number | null) {
  return ndi === null ? "—" : ndi.toFixed(3);
}

export default function DashboardPage() {
  const [status, setStatus] = useState<StatusInfo | null>(null);
  const [events, setEvents] = useState<EventRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.status(), api.events(30)])
      .then(([s, e]) => {
        setStatus(s);
        setEvents(e);
      })
      .catch((err) => setError(String(err)));
  }, []);

  if (error) return <p className="text-destructive">API 不可达：{error}</p>;

  const stats = [
    { label: "事件数", value: status?.events ?? "…" },
    { label: "Stance 行", value: status?.stances ?? "…" },
    { label: "NDI 点位", value: status?.ndi_points ?? "…" },
    { label: "有效 / 弃权", value: status ? `${status.ndi_ok} / ${status.ndi_abstain}` : "…" },
    { label: "Bronze 记录", value: status?.bronze_records ?? "…" },
  ];

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">叙事分歧概览</h1>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
        {stats.map((s) => (
          <Card key={s.label}>
            <CardHeader className="pb-0">
              <CardTitle className="text-2xl">{s.value}</CardTitle>
            </CardHeader>
            <CardContent className="text-xs text-muted-foreground">{s.label}</CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">事件（近 30 天，点击下钻证据链）</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>事件</TableHead>
                <TableHead>标题</TableHead>
                <TableHead>实体</TableHead>
                <TableHead>NDI</TableHead>
                <TableHead>源数</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {events.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-muted-foreground">
                    暂无数据——先运行 backfill + run_daily
                  </TableCell>
                </TableRow>
              ) : (
                events.map((e) => (
                  <TableRow key={e.event_id}>
                    <TableCell>
                      <Link
                        href={`/events/${encodeURIComponent(e.event_id)}`}
                        className="font-mono text-xs text-primary underline-offset-4 hover:underline"
                      >
                        {e.event_id}
                      </Link>
                    </TableCell>
                    <TableCell className="max-w-[22rem] truncate" title={e.title}>
                      {e.title}
                    </TableCell>
                    <TableCell className="text-xs">{e.entities.join(", ")}</TableCell>
                    <TableCell>
                      <Badge variant={e.ndi_status === "ok" ? "ok" : "abstain"}>
                        {fmtNdi(e.ndi)}（{e.ndi_status}）
                      </Badge>
                    </TableCell>
                    <TableCell>{e.n_sources}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
