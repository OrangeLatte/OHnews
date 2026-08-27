"use client";

import { useCallback, useEffect, useState } from "react";

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
import { Textarea } from "@/components/ui/textarea";
import { api, type DecisionRow } from "@/lib/api";

export default function DecisionsPage() {
  const [entityId, setEntityId] = useState("fed");
  const [decision, setDecision] = useState("");
  const [eventId, setEventId] = useState("");
  const [rows, setRows] = useState<DecisionRow[]>([]);
  const [resolveId, setResolveId] = useState("");
  const [outcome, setOutcome] = useState("");

  const query = useCallback(async () => {
    try {
      setRows(await api.decisions(entityId || "fed"));
    } catch {
      setRows([]);
    }
  }, [entityId]);

  useEffect(() => {
    void query();
  }, [query]);

  async function add() {
    if (!decision.trim()) return;
    await api.addDecision(entityId || "fed", decision, eventId || undefined);
    setDecision("");
    await query();
  }

  async function resolve() {
    if (!resolveId.trim() || !outcome.trim()) return;
    await api.resolveDecision(resolveId, outcome);
    setResolveId("");
    setOutcome("");
    await query();
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">
        决策日志（记录判断 → 回填结果 = 个人资产 + 校准数据）
      </h1>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">记录新决策</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex gap-2">
            <Input
              className="max-w-[12rem]"
              value={entityId}
              onChange={(e) => setEntityId(e.target.value)}
              placeholder="实体（如 fed）"
            />
            <Input
              className="max-w-[16rem]"
              value={eventId}
              onChange={(e) => setEventId(e.target.value)}
              placeholder="关联事件 ID（可选）"
            />
          </div>
          <Textarea
            rows={2}
            value={decision}
            onChange={(e) => setDecision(e.target.value)}
            placeholder="据此判断…"
          />
          <Button className="w-fit" onClick={add}>
            记录
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">回填结果</CardTitle>
        </CardHeader>
        <CardContent className="flex gap-2">
          <Input
            className="max-w-[14rem]"
            value={resolveId}
            onChange={(e) => setResolveId(e.target.value)}
            placeholder="decision_id"
          />
          <Input
            className="max-w-[24rem]"
            value={outcome}
            onChange={(e) => setOutcome(e.target.value)}
            placeholder="结果（事后回填）"
          />
          <Button variant="outline" onClick={resolve}>
            回填
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">决策列表（实体：{entityId || "fed"}）</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>时间</TableHead>
                <TableHead>事件</TableHead>
                <TableHead>NDI</TableHead>
                <TableHead>判断</TableHead>
                <TableHead>结果</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-muted-foreground">
                    暂无记录
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((d) => (
                  <TableRow key={d.decision_id}>
                    <TableCell className="font-mono text-xs">{d.decision_id}</TableCell>
                    <TableCell className="font-mono text-xs">
                      {d.created_at.replace("T", " ").slice(0, 16)}
                    </TableCell>
                    <TableCell className="text-xs">{d.event_id ?? "—"}</TableCell>
                    <TableCell>
                      {d.ndi_at_decision === null ? "—" : d.ndi_at_decision.toFixed(3)}
                    </TableCell>
                    <TableCell className="max-w-[20rem] truncate">{d.decision}</TableCell>
                    <TableCell>
                      {d.outcome ? (
                        <Badge variant="ok">{d.outcome}</Badge>
                      ) : (
                        <Badge variant="abstain">待回填</Badge>
                      )}
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
