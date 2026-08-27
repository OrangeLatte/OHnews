"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, type AlertHit, type AlertRule } from "@/lib/api";

const PERCENTILES = [0.8, 0.9, 0.95];

export default function AlertsPage() {
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [hits, setHits] = useState<AlertHit[]>([]);
  const [entityId, setEntityId] = useState("fed");
  const [percentile, setPercentile] = useState(0.9);
  const [msg, setMsg] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  const query = useCallback(async () => {
    const [r, h] = await Promise.all([api.alertRules(), api.alertHits()]);
    setRules(r);
    setHits(h);
  }, []);

  useEffect(() => {
    void query().catch(() => setRules([]));
  }, [query]);

  async function add() {
    if (!entityId.trim()) return;
    await api.addAlertRule(entityId.trim(), percentile);
    await query();
  }

  async function remove(ruleId: string) {
    await api.deleteAlertRule(ruleId);
    await query();
  }

  async function check() {
    setChecking(true);
    setMsg(null);
    try {
      const r = await api.alertCheck();
      setMsg(r.triggered > 0 ? `触发 ${r.triggered} 条预警` : "本次检查无新触发");
      await query();
    } catch (err) {
      setMsg(String(err));
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold">预警订阅</h1>
        <Button size="sm" variant="outline" onClick={check} disabled={checking}>
          {checking ? "检查中…" : "运行检查"}
        </Button>
        {msg && <span className="text-sm text-muted-foreground">{msg}</span>}
      </div>
      <p className="text-xs text-muted-foreground">
        触发语义：实体相关事件 NDI ≥ 该实体历史分布 P{percentile * 100}（描述性提示
        "分歧进入历史高位区间"，非方向性判断）。同实体每日最多 1 次；历史点位不足 8 个自动弃权。
      </p>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">新建订阅</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-2">
          <Input
            className="max-w-[12rem]"
            value={entityId}
            onChange={(e) => setEntityId(e.target.value)}
            placeholder="实体（如 fed）"
          />
          {PERCENTILES.map((p) => (
            <Button
              key={p}
              size="sm"
              variant={percentile === p ? "default" : "outline"}
              onClick={() => setPercentile(p)}
            >
              P{p * 100}
            </Button>
          ))}
          <Button size="sm" onClick={add}>
            订阅
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">订阅规则（{rules.length}）</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>规则</TableHead>
                <TableHead>实体</TableHead>
                <TableHead>分位</TableHead>
                <TableHead>窗口</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rules.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-muted-foreground">
                    暂无订阅
                  </TableCell>
                </TableRow>
              ) : (
                rules.map((r) => (
                  <TableRow key={r.rule_id}>
                    <TableCell className="font-mono text-xs">{r.rule_id}</TableCell>
                    <TableCell>{r.entity_id}</TableCell>
                    <TableCell>
                      <Badge variant="outline">P{r.percentile * 100}</Badge>
                    </TableCell>
                    <TableCell>{r.window_days}d</TableCell>
                    <TableCell>
                      <Button size="sm" variant="outline" onClick={() => remove(r.rule_id)}>
                        删除
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">触发记录（{hits.length}）</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>时间</TableHead>
                <TableHead>实体</TableHead>
                <TableHead>事件</TableHead>
                <TableHead>NDI</TableHead>
                <TableHead>基线</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {hits.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-muted-foreground">
                    暂无触发
                  </TableCell>
                </TableRow>
              ) : (
                hits.map((h) => (
                  <TableRow key={`${h.rule_id}-${h.event_id}-${h.triggered_at}`}>
                    <TableCell className="font-mono text-xs">
                      {h.triggered_at.replace("T", " ").slice(0, 16)}
                    </TableCell>
                    <TableCell>{h.entity_id}</TableCell>
                    <TableCell>
                      <Link
                        href={`/events/${encodeURIComponent(h.event_id)}`}
                        className="max-w-[18rem] truncate text-primary underline-offset-4 hover:underline"
                      >
                        {h.event_title}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <Badge variant="ok">{h.ndi.toFixed(3)}</Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      P 基线 {h.baseline.toFixed(3)}
                    </TableCell>
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
