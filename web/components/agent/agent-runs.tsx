"use client";

/**
 * AgentDock Runs 标签：Agent 运行 + 工作流运行合并时间线（规格 4.3）。
 * GET /api/agent/runs?limit=12 + GET /api/analysis-runs?limit=12，按开始时间倒序。
 * 状态色徽标；Agent 运行可展开工具调用；ResearchState.activeRunId 高亮当前运行。
 */

import { useEffect, useState } from "react";
import { useT } from "@/lib/i18n/use-t";
import { useResearchState } from "@/lib/research-state";

interface AgentRunRow {
  run_id: string;
  workflow: string;
  status: string;
  model: string;
  error: string;
  started_at: string;
}

interface WorkflowRunRow {
  run_id: string;
  case_id: string;
  kind: string;
  engine: string;
  status: string;
  error: string;
  started_at: string;
}

interface ToolRow {
  call_id: string;
  tool: string;
  ok: boolean;
  latency_ms: number;
  error: string;
}

type MergedRow = {
  run_id: string;
  source: "agent" | "workflow";
  label: string;
  status: string;
  error: string;
  started_at: string;
  case_id: string;
};

const STATUS_CLS: Record<string, string> = {
  succeeded: "text-green-600",
  abstained: "text-amber-600",
  awaiting_hitl: "text-amber-600",
  failed: "text-red-600",
  running: "animate-pulse text-blue-600",
  queued: "text-muted-foreground",
  cancelled: "text-muted-foreground line-through",
};

export function AgentRuns() {
  const t = useT();
  const { activeRunId, caseId } = useResearchState();
  const [rows, setRows] = useState<MergedRow[]>([]);
  const [err, setErr] = useState("");
  const [tools, setTools] = useState<Record<string, ToolRow[]>>({});
  const [openRun, setOpenRun] = useState("");
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let alive = true;
    Promise.all([
      fetch("/api/agent/runs?limit=12", { cache: "no-store" }).then((r) => r.json()),
      fetch("/api/analysis-runs?limit=12", { cache: "no-store" }).then((r) => r.json()),
    ])
      .then(([ag, wf]) => {
        if (!alive) return;
        const a: AgentRunRow[] = Array.isArray(ag) ? ag : [];
        const w: WorkflowRunRow[] = Array.isArray(wf) ? wf : [];
        const merged: MergedRow[] = [
          ...a.map((r) => ({
            run_id: r.run_id,
            source: "agent" as const,
            label: r.workflow || r.run_id,
            status: r.status ?? "",
            error: r.error ?? "",
            started_at: r.started_at ?? "",
            case_id: "",
          })),
          ...w.map((r) => ({
            run_id: r.run_id,
            source: "workflow" as const,
            label: `${r.kind} · ${r.case_id || "—"}`,
            status: r.status ?? "",
            error: r.error ?? "",
            started_at: r.started_at ?? "",
            case_id: r.case_id ?? "",
          })),
        ].sort((x, y) => {
          // 当前 Case 的 run 置顶（不隐藏其他运行，诚实呈现全量时间线）
          const cx = x.case_id !== "" && x.case_id === caseId ? 0 : 1;
          const cy = y.case_id !== "" && y.case_id === caseId ? 0 : 1;
          if (cx !== cy) return cx - cy;
          return y.started_at > x.started_at ? 1 : y.started_at < x.started_at ? -1 : 0;
        });
        setRows(merged);
        setErr("");
      })
      .catch((e: unknown) => {
        if (alive) setErr(e instanceof Error ? e.message : String(e));
      });
    return () => {
      alive = false;
    };
  }, [tick, caseId]);

  const expandRun = (runId: string, source: MergedRow["source"]): void => {
    setOpenRun(runId === openRun ? "" : runId);
    if (source === "agent" && !(runId in tools)) {
      fetch(`/api/agent/runs/${encodeURIComponent(runId)}/tool-calls`)
        .then((r) => r.json())
        .then((list: ToolRow[]) => setTools((prev) => ({ ...prev, [runId]: list })))
        .catch(() => {
          /* 工具列表失败不打断时间线 */
        });
    }
  };

  return (
    <div className="space-y-2 text-xs">
      <div className="flex items-center justify-between gap-2">
        <p className="font-medium">{t("agentRuns.title")}</p>
        <button type="button" onClick={() => setTick((n) => n + 1)} className="rounded border px-1.5 py-0.5">
          {t("agentPanel.refresh")}
        </button>
      </div>

      {err ? <p className="break-all text-red-600">{err}</p> : null}

      {rows.length === 0 ? (
        <p className="text-muted-foreground">{t("agentRuns.empty")}</p>
      ) : (
        <ul className="space-y-1">
          {rows.map((r) => (
            <li
              key={`${r.source}-${r.run_id}`}
              className={`rounded border p-1.5 ${r.run_id === activeRunId ? "border-sky-500" : ""}`}
            >
              <p className="flex items-center justify-between gap-2">
                {r.source === "agent" ? (
                  <button
                    type="button"
                    onClick={() => expandRun(r.run_id, r.source)}
                    className="flex min-w-0 flex-1 items-center justify-between gap-2 text-left"
                    aria-expanded={openRun === r.run_id}
                  >
                    <span className="truncate">{r.label}</span>
                    <span className={STATUS_CLS[r.status] ?? "text-muted-foreground"}>{r.status}</span>
                  </button>
                ) : (
                  <>
                    <span className="truncate">{r.label}</span>
                    <span className={STATUS_CLS[r.status] ?? "text-muted-foreground"}>{r.status}</span>
                  </>
                )}
              </p>
              <p className="mt-0.5 flex items-center gap-1 text-[10px] text-muted-foreground">
                <span className="rounded bg-muted px-1">
                  {r.source === "agent" ? t("agentRuns.srcAgent") : t("agentRuns.srcWorkflow")}
                </span>
                {caseId && r.case_id === caseId ? (
                  <span className="rounded bg-sky-500/15 px-1 text-sky-700 dark:text-sky-300">
                    {t("agentRuns.currentCase")}
                  </span>
                ) : null}
                <span className="font-mono">{r.started_at.slice(0, 16).replace("T", " ")}</span>
                {r.run_id === activeRunId ? (
                  <span className="rounded bg-sky-500/15 px-1 text-sky-700 dark:text-sky-300">
                    {t("agentRuns.active")}
                  </span>
                ) : null}
              </p>
              {r.error ? (
                <p className="truncate text-red-600/80" title={r.error}>
                  {r.error}
                </p>
              ) : null}
              {r.source === "agent" && openRun === r.run_id ? (
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
    </div>
  );
}
