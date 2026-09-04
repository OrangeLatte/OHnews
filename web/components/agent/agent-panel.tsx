"use client";

/**
 * AgentPanel（Parent Agent 控制面板）：模型状态 / 用量 / 运行 / 工具 / HITL / 会话。
 * 数据全部来自 research.sqlite 只读端点；HITL 决策是面板内唯一写操作（显式按钮）。
 */

import { useCallback, useEffect, useState } from "react";
import { postJson } from "@/lib/landscape-api";
import { useT } from "@/lib/i18n/use-t";

interface UsageOut {
  summary: { calls: number; token_in: number; token_out: number; cost_usd: number };
  counts: Record<string, number>;
}

interface RunRow {
  run_id: string;
  workflow: string;
  status: string;
  model: string;
  error: string;
  started_at: string;
}

interface BizRunRow {
  run_id: string;
  case_id: string;
  kind: string;
  engine: string;
  status: string;
  error: string;
  started_at: string;
}

interface MonPendingRow {
  update_id: string;
  monitor_id: string;
  summary: string;
  suggested_case_action: string;
  reviewed: boolean;
}

interface ToolRow {
  call_id: string;
  tool: string;
  ok: boolean;
  latency_ms: number;
  error: string;
}

interface HitlRow {
  hitl_id: string;
  action: string;
  payload: Record<string, unknown>;
  status: string;
}

interface ThreadRow {
  thread_id: string;
  title: string;
  created_at: string;
}

const STATUS_CLS: Record<string, string> = {
  succeeded: "text-green-600",
  failed: "text-red-600",
  running: "text-blue-600",
  queued: "text-muted-foreground",
  awaiting_hitl: "text-amber-600",
  cancelled: "text-muted-foreground",
};

export function AgentPanel() {
  const t = useT();
  const [llmReady, setLlmReady] = useState<boolean | null>(null);
  const [usage, setUsage] = useState<UsageOut | null>(null);
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [threads, setThreads] = useState<ThreadRow[]>([]);
  const [hitl, setHitl] = useState<HitlRow[]>([]);
  const [bizRuns, setBizRuns] = useState<BizRunRow[]>([]);
  const [monPending, setMonPending] = useState<MonPendingRow[]>([]);
  const [tools, setTools] = useState<Record<string, ToolRow[]>>({});
  const [openRun, setOpenRun] = useState("");
  const [err, setErr] = useState("");

  const monitorPending = (): Promise<MonPendingRow[]> =>
    fetch("/api/monitors")
      .then((r) => r.json() as Promise<{ monitor_id: string }[]>)
      .then((ms) =>
        Promise.all(
          ms.map((m) =>
            fetch(`/api/monitors/${encodeURIComponent(m.monitor_id)}/updates`).then(
              (r) => r.json() as Promise<MonPendingRow[]>,
            ),
          ),
        ),
      )
      .then((lists) => lists.flat().filter((u) => !u.reviewed));

  const refresh = useCallback(() => {
    Promise.all([
      fetch("/api/llm/health").then((r) => r.json()),
      fetch("/api/usage").then((r) => r.json()),
      fetch("/api/agent/runs?limit=12").then((r) => r.json()),
      fetch("/api/agent/threads?limit=8").then((r) => r.json()),
      fetch("/api/hitl/pending").then((r) => r.json()),
      fetch("/api/analysis-runs?limit=12").then((r) => r.json()),
      monitorPending(),
    ])
      .then(([hlth, u, r, th, h, br, mp]) => {
        setLlmReady(Boolean(hlth?.ready));
        setUsage(u as UsageOut);
        setRuns(r as RunRow[]);
        setThreads(th as ThreadRow[]);
        setHitl(h as HitlRow[]);
        setBizRuns(br as BizRunRow[]);
        setMonPending(mp);
        setErr("");
      })
      .catch((e: unknown) => {
        setErr(e instanceof Error ? e.message : String(e));
      });
  }, []);

  useEffect(() => {
    let alive = true;
    Promise.all([
      fetch("/api/llm/health").then((r) => r.json()),
      fetch("/api/usage").then((r) => r.json()),
      fetch("/api/agent/runs?limit=12").then((r) => r.json()),
      fetch("/api/agent/threads?limit=8").then((r) => r.json()),
      fetch("/api/hitl/pending").then((r) => r.json()),
      fetch("/api/analysis-runs?limit=12").then((r) => r.json()),
      monitorPending(),
    ])
      .then(([hlth, u, r, th, h, br, mp]) => {
        if (!alive) return;
        setLlmReady(Boolean(hlth?.ready));
        setUsage(u as UsageOut);
        setRuns(r as RunRow[]);
        setThreads(th as ThreadRow[]);
        setHitl(h as HitlRow[]);
        setBizRuns(br as BizRunRow[]);
        setMonPending(mp);
      })
      .catch((e: unknown) => {
        if (alive) setErr(e instanceof Error ? e.message : String(e));
      });
    return () => {
      alive = false;
    };
  }, []);

  const expandRun = (runId: string): void => {
    setOpenRun(runId === openRun ? "" : runId);
    if (!(runId in tools)) {
      fetch(`/api/agent/runs/${runId}/tool-calls`)
        .then((r) => r.json())
        .then((list: ToolRow[]) => setTools((prev) => ({ ...prev, [runId]: list })))
        .catch(() => {
          /* 工具列表失败不打断面板 */
        });
    }
  };

  const decide = (hitlId: string, status: "approved" | "rejected"): void => {
    postJson(`/api/hitl/${hitlId}/decide`, { status, decided_by: "user" })
      .then(() => refresh())
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : String(e)));
  };

  const reviewMon = (updateId: string, decision: "new_case" | "ignore"): void => {
    postJson(`/api/monitors/updates/${encodeURIComponent(updateId)}/review`, { decision })
      .then(() => refresh())
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : String(e)));
  };

  const s = usage?.summary;

  return (
    <div className="ag-panel space-y-3 text-xs">
      {err ? <p className="text-red-600">{err}</p> : null}

      <section className="flex items-center justify-between gap-2">
        <span>{t("agentPanel.model")}</span>
        <button type="button" onClick={refresh} className="rounded border px-1.5 py-0.5">
          {t("agentPanel.refresh")}
        </button>
      </section>
      <p>
        <span
          className={`mr-1 inline-block h-2 w-2 rounded-full ${
            llmReady === null ? "bg-muted" : llmReady ? "bg-green-500" : "bg-red-400"
          }`}
          aria-hidden
        />
        {llmReady === null ? "…" : llmReady ? t("agentPanel.llmReady") : t("agentPanel.llmOff")}
      </p>

      <section className="rounded border p-2">
        <p className="mb-1 font-medium">{t("agentPanel.usage")}</p>
        {s ? (
          <p className="text-muted-foreground">
            {t("agentPanel.calls")}: {s.calls} · {t("agentPanel.tokens")}: {s.token_in}/
            {s.token_out} · {t("agentPanel.cost")}: ${s.cost_usd.toFixed(4)}
          </p>
        ) : (
          <p className="text-muted-foreground">…</p>
        )}
      </section>

      <section className="rounded border p-2">
        <p className="mb-1 font-medium">
          {t("agentPanel.hitl")} ({hitl.length + monPending.length})
        </p>
        {monPending.length > 0 ? (
          <div className="mb-2">
            <p className="mb-1 text-muted-foreground">{t("agentPanel.monitorPending")}</p>
            <ul className="space-y-1">
              {monPending.map((m) => (
                <li key={m.update_id} className="rounded border bg-amber-50 p-1.5 dark:bg-amber-950">
                  <p className="break-all">{m.summary}</p>
                  <span className="flex gap-1 pt-1">
                    <button
                      type="button"
                      onClick={() => reviewMon(m.update_id, "new_case")}
                      className="rounded border px-1.5 py-0.5"
                    >
                      {t("monitors.acceptNew")}
                    </button>
                    <button
                      type="button"
                      onClick={() => reviewMon(m.update_id, "ignore")}
                      className="rounded border px-1.5 py-0.5"
                    >
                      {t("agentPanel.dismiss")}
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {hitl.length === 0 ? (
          <p className="text-muted-foreground">{t("agentPanel.noHitl")}</p>
        ) : (
          <ul className="space-y-1">
            {hitl.map((h) => (
              <li key={h.hitl_id} className="rounded border bg-amber-50 p-1.5 dark:bg-amber-950">
                <p className="font-medium">{h.action}</p>
                <p className="mb-1 break-all text-muted-foreground">
                  {JSON.stringify(h.payload).slice(0, 120)}
                </p>
                <span className="flex gap-1">
                  <button
                    type="button"
                    onClick={() => decide(h.hitl_id, "approved")}
                    className="rounded border px-1.5 py-0.5"
                  >
                    {t("agentPanel.approve")}
                  </button>
                  <button
                    type="button"
                    onClick={() => decide(h.hitl_id, "rejected")}
                    className="rounded border px-1.5 py-0.5"
                  >
                    {t("agentPanel.reject")}
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="rounded border p-2">
        <p className="mb-1 font-medium">{t("agentPanel.workflowRuns")}</p>
        {bizRuns.length === 0 ? (
          <p className="text-muted-foreground">{t("agentPanel.noBizRuns")}</p>
        ) : (
          <ul className="space-y-1">
            {bizRuns.map((r) => (
              <li key={r.run_id}>
                <p className="flex items-center justify-between gap-2">
                  <span className="truncate">
                    {r.kind} · {r.case_id || "—"}
                  </span>
                  <span className={STATUS_CLS[r.status] ?? ""}>{r.status}</span>
                </p>
                {r.error ? (
                  <p className="truncate text-red-600/80" title={r.error}>
                    {r.error}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="rounded border p-2">
        <p className="mb-1 font-medium">{t("agentPanel.runs")}</p>
        {runs.length === 0 ? (
          <p className="text-muted-foreground">{t("agentPanel.noRuns")}</p>
        ) : (
          <ul className="space-y-1">
            {runs.map((r) => (
              <li key={r.run_id}>
                <button
                  type="button"
                  onClick={() => expandRun(r.run_id)}
                  className="flex w-full items-center justify-between gap-2 text-left"
                  aria-expanded={openRun === r.run_id}
                >
                  <span className="truncate">{r.workflow}</span>
                  <span className={STATUS_CLS[r.status] ?? ""}>{r.status}</span>
                </button>
                {r.error ? (
                  <p className="truncate text-red-600/80" title={r.error}>
                    {r.error}
                  </p>
                ) : null}
                {openRun === r.run_id ? (
                  <ul className="mb-1 ml-3 space-y-0.5 text-muted-foreground">
                    {(tools[r.run_id] ?? []).length === 0 ? (
                      <li>{t("agentPanel.noTools")}</li>
                    ) : (
                      tools[r.run_id].map((c) => (
                        <li key={c.call_id}>
                          {c.ok ? "✓" : "✗"} {c.tool} · {c.latency_ms}ms
                          {c.error ? ` · ${c.error}` : ""}
                        </li>
                      ))
                    )}
                  </ul>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="rounded border p-2">
        <p className="mb-1 font-medium">{t("agentPanel.threads")}</p>
        {threads.length === 0 ? (
          <p className="text-muted-foreground">{t("agentPanel.noThreads")}</p>
        ) : (
          <ul className="space-y-0.5 text-muted-foreground">
            {threads.map((th) => (
              <li key={th.thread_id} className="truncate">
                {th.title || th.thread_id} · {th.created_at.slice(0, 16).replace("T", " ")}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
