"use client";

import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type AgentInvokeResponse } from "@/lib/api";

const INTENTS: { value: string; label: string }[] = [
  { value: "explain_signal", label: "Explain Signal · 解读信号" },
  { value: "explain_cause", label: "Explain Cause · 解释成因" },
  { value: "compare_narratives", label: "Compare Narratives · 比较叙事" },
  { value: "show_evidence", label: "Show Evidence · 出示证据" },
  { value: "start_investigation", label: "Start Investigation · 立案调查" },
];

const TARGET_KINDS: { value: string; label: string }[] = [
  { value: "signal", label: "Signal 信号" },
  { value: "event", label: "Event 事件" },
  { value: "entity", label: "Entity 实体" },
  { value: "topic", label: "Topic 主题" },
];

const INTENT_LABELS: Record<string, string> = Object.fromEntries(
  INTENTS.map((i) => [i.value, i.label]),
);

const LAYER_META: { key: string; label: string; color: string }[] = [
  { key: "observation", label: "OBSERVATION · 观察到什么", color: "#58a6ff" },
  { key: "interpretation", label: "INTERPRETATION · 如何解读", color: "#3fb950" },
  { key: "evidence", label: "EVIDENCE · 证据", color: "#d29922" },
  { key: "alternative", label: "ALTERNATIVE · 替代解释", color: "#bc8cff" },
  { key: "uncertainty", label: "UNCERTAINTY · 不确定性", color: "#8b949e" },
];

function ArtifactView({ res }: { res: AgentInvokeResponse }) {
  const a = res.artifact;
  if (!a) return null;
  const evidence = Array.isArray(a.evidence) ? a.evidence : [];
  const packet = res.packet;
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <CardTitle className="text-base">
            {INTENT_LABELS[a.intent] ?? a.intent}
          </CardTitle>
          <Badge variant="outline" className="font-mono text-[10px]">
            {a.engine}
          </Badge>
          {res.offline && (
            <span className="text-[10px] text-muted-foreground">
              离线模式（未配置 LLM keys，确定性模板输出）
            </span>
          )}
        </div>
        <p className="font-mono text-xs text-muted-foreground">target: {a.target_id}</p>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {LAYER_META.map((m) => {
          if (m.key === "evidence") {
            return (
              <div key={m.key}>
                <h3
                  className="mb-1 text-[11px] font-semibold uppercase tracking-wider"
                  style={{ color: m.color }}
                >
                  {m.label}
                </h3>
                {evidence.length === 0 ? (
                  <p className="text-sm text-muted-foreground">（无独立佐证）</p>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {evidence.map((e, i) => (
                      <span
                        key={`${e}-${i}`}
                        className="rounded border border-border/70 bg-muted/40 px-2 py-0.5 font-mono text-xs"
                      >
                        {e}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
          }
          const val = (a as unknown as Record<string, string | null>)[m.key];
          return (
            <div key={m.key}>
              <h3
                className="mb-1 text-[11px] font-semibold uppercase tracking-wider"
                style={{ color: m.color }}
              >
                {m.label}
              </h3>
              <p className="whitespace-pre-wrap text-sm leading-6">
                {val && val.trim() ? val : "（本层暂无内容）"}
              </p>
            </div>
          );
        })}
        <details className="rounded border border-border/60 px-3 py-2">
          <summary className="cursor-pointer text-xs text-muted-foreground">
            ContextPacket（NDI 点位 {packet.ndi_points.length} · stance{" "}
            {packet.stances.length} 行 · 证据事件 {packet.evidence_ids.length}）
          </summary>
          <pre className="mt-2 overflow-x-auto text-[11px] leading-5 text-muted-foreground">
            {JSON.stringify(
              {
                target_kind: packet.target_kind,
                entity_id: packet.entity_id,
                ndi_points: packet.ndi_points.slice(-5),
                stances: packet.stances.slice(0, 8),
                notes: packet.notes,
              },
              null,
              2,
            )}
          </pre>
        </details>
      </CardContent>
    </Card>
  );
}

function ChatReplyView({ res }: { res: AgentInvokeResponse }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <CardTitle className="text-base">
            {INTENT_LABELS[res.packet.intent] ?? res.packet.intent}
          </CardTitle>
          <Badge variant="outline" className="font-mono text-[10px]">
            rounds {res.rounds ?? 0}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p className="whitespace-pre-wrap text-sm leading-7">{res.reply}</p>
        {(res.tools_used?.length ?? 0) > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {res.tools_used!.map((t, i) => (
              <span
                key={`${t}-${i}`}
                className="rounded border border-border/70 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground"
              >
                {t}
              </span>
            ))}
          </div>
        )}
        {(res.citations?.length ?? 0) > 0 && (
          <div>
            <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Citations
            </h3>
            <div className="flex flex-wrap gap-1.5">
              {res.citations!.map((c, i) => (
                <span
                  key={`${c}-${i}`}
                  className="rounded border border-border/70 bg-muted/40 px-2 py-0.5 font-mono text-xs"
                >
                  {c}
                </span>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function IntentPanel() {
  const [intent, setIntent] = useState("explain_signal");
  const [targetKind, setTargetKind] = useState("signal");
  const [targetId, setTargetId] = useState("");
  const [message, setMessage] = useState("");
  const [res, setRes] = useState<AgentInvokeResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const autoFired = useRef(false);

  useEffect(() => {
    const sp = new URLSearchParams(window.location.search);
    const it = sp.get("intent");
    const tk = sp.get("target_kind");
    const tid = sp.get("target_id");
    if (it) setIntent(it);
    if (tk) setTargetKind(tk);
    if (tid) setTargetId(tid);
    if (it && tk && tid && !autoFired.current) {
      autoFired.current = true;
      setBusy(true);
      api
        .agentInvoke({ intent: it, target_kind: tk, target_id: tid })
        .then(setRes)
        .catch((err) => setError(String(err)))
        .finally(() => setBusy(false));
    }
  }, []);

  async function invoke() {
    if (!targetId.trim()) {
      setError("target_id 不能为空");
      return;
    }
    setBusy(true);
    setError(null);
    setRes(null);
    try {
      const r = await api.agentInvoke({
        intent,
        target_kind: targetKind,
        target_id: targetId.trim(),
        message: message.trim() || undefined,
      });
      setRes(r);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">意图驱动的分析师（Action → Intent → Artifact）</CardTitle>
          <p className="text-xs text-muted-foreground">
            从 Today 页 Signal 卡「Ask Analyst」会自动带入意图与目标；也可在此手动发起。缺 LLM
            keys 时输出确定性五层 Artifact。
          </p>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-xs text-muted-foreground">
              Intent
              <select
                value={intent}
                onChange={(e) => setIntent(e.target.value)}
                className="rounded-md border border-border bg-background px-2 py-2 text-sm text-foreground"
              >
                {INTENTS.map((i) => (
                  <option key={i.value} value={i.value}>
                    {i.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted-foreground">
              Target kind
              <select
                value={targetKind}
                onChange={(e) => setTargetKind(e.target.value)}
                className="rounded-md border border-border bg-background px-2 py-2 text-sm text-foreground"
              >
                {TARGET_KINDS.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            Target id（signal_id / event_id / entity_id）
            <input
              value={targetId}
              onChange={(e) => setTargetId(e.target.value)}
              placeholder="如 sig-attention_spike-fed-20260828 或 ev-fed-20260827"
              className="rounded-md border border-border bg-background px-2 py-2 font-mono text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            附加问题（可选）
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              rows={2}
              className="rounded-md border border-border bg-background px-2 py-2 text-sm"
            />
          </label>
          <div className="flex items-center gap-3">
            <Button size="sm" onClick={invoke} disabled={busy}>
              {busy ? "Analyst 运行中…" : "调用分析师"}
            </Button>
            {error && <span className="text-xs text-destructive">{error}</span>}
          </div>
        </CardContent>
      </Card>

      {res &&
        (res.artifact ? <ArtifactView res={res} /> : <ChatReplyView res={res} />)}
    </div>
  );
}
