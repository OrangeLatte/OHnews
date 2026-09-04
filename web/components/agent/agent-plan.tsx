"use client";

/**
 * AgentDock Plan 标签：当前 Case 的研究计划（Parent Agent 规划产物，规格 4.3）。
 * GET /api/agent/plans?case_id=…；POST /api/agent/plan 生成——
 * 后端未就绪时诚实报错（404/失败 toast + 内联错误），不假装成功。
 */

import { useCallback, useEffect, useState } from "react";
import { toast } from "@/components/ui/toast";
import { postJson } from "@/lib/landscape-api";
import { useT } from "@/lib/i18n/use-t";
import { useResearchState } from "@/lib/research-state";

interface PlanStep {
  step_id: string;
  kind: string;
  title: string;
  rationale: string;
}

interface PlanRow {
  plan_id: string;
  case_id: string;
  steps: PlanStep[];
  created_at: string;
}

export function AgentPlan() {
  const t = useT();
  const { caseId } = useResearchState();
  const [plans, setPlans] = useState<PlanRow[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [err, setErr] = useState("");
  const [generating, setGenerating] = useState(false);

  const load = useCallback((cid: string): Promise<void> => {
    return fetch(`/api/agent/plans?case_id=${encodeURIComponent(cid)}`, { cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error(`agent/plans: HTTP ${r.status}`);
        return r.json() as Promise<unknown>;
      })
      .then((data) => {
        const raw = Array.isArray(data)
          ? data
          : (data as { plans?: PlanRow[] } | null)?.plans ?? [];
        const rows = (Array.isArray(raw) ? raw : []).map((p: PlanRow) => ({
          ...p,
          steps: Array.isArray(p?.steps) ? p.steps : [],
        }));
        setPlans(rows);
        setErr("");
      });
  }, []);

  useEffect(() => {
    if (!caseId) return;
    let alive = true;
    load(caseId)
      .catch((e: unknown) => {
        if (alive) setErr(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (alive) setLoaded(true);
      });
    return () => {
      alive = false;
    };
  }, [caseId, load]);

  const generate = (): void => {
    if (!caseId || generating) return;
    setGenerating(true);
    postJson<unknown>("/api/agent/plan", { case_id: caseId })
      .then(() => load(caseId))
      .then(() => toast.success(t("agentPlan.generated")))
      .catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : String(e);
        setErr(msg);
        toast.error(`${t("agentPlan.failed")}: ${msg}`);
      })
      .finally(() => setGenerating(false));
  };

  return (
    <div className="space-y-2 text-xs">
      <div className="flex items-center justify-between gap-2">
        <p className="font-medium">{t("agentPlan.title")}</p>
        <button
          type="button"
          onClick={generate}
          disabled={!caseId || generating}
          className="rounded border px-1.5 py-0.5 disabled:opacity-40"
        >
          {generating ? t("agentPlan.generating") : t("agentPlan.generate")}
        </button>
      </div>

      {!caseId ? (
        <div className="rounded border border-dashed p-2">
          <p className="font-medium">{t("agentPlan.empty")}</p>
          <p className="mt-1 text-muted-foreground">{t("agentPlan.emptyHint")}</p>
        </div>
      ) : err ? (
        <p className="break-all text-red-600">
          {t("agentPlan.loadFailed")}: {err}
        </p>
      ) : plans.length === 0 ? (
        <p className="text-muted-foreground">{loaded ? t("agentPlan.empty") : t("common.loading")}</p>
      ) : (
        <ul className="space-y-2">
          {plans.map((p) => (
            <li key={p.plan_id} className="rounded border p-2">
              <p className="font-medium">
                {t("agentPlan.createdAt")} {p.created_at?.slice(0, 16).replace("T", " ")}
              </p>
              <p className="mt-1 text-muted-foreground">
                {t("agentPlan.steps")} ({p.steps.length})
              </p>
              <ol className="mt-1 space-y-1">
                {p.steps.map((s) => (
                  <li key={s.step_id} className="rounded border bg-muted/40 p-1.5">
                    <p className="flex items-center gap-1">
                      <span
                        className="rounded bg-foreground px-1 py-0.5 font-mono text-[10px] text-background"
                        title={t("agentPlan.stepKind")}
                      >
                        {s.kind}
                      </span>
                      <span className="font-medium">{s.title}</span>
                    </p>
                    {s.rationale ? (
                      <p className="mt-0.5 text-muted-foreground">
                        {t("agentPlan.rationale")}: {s.rationale}
                      </p>
                    ) : null}
                  </li>
                ))}
              </ol>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
