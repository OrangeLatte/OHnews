"use client";

/**
 * 运行中心：采集计划卡片化（mode 徽标 / schedule / 源数 / enabled 开关 + runs 折叠），
 * runs 带进度条；enable/disable 均走 window.confirm（HITL）；
 * 新建计划 = PlanWizard 三步 stepper。
 */

import { useEffect, useState } from "react";
import { HelpIcon } from "@/components/help/help-icon";
import { useLocale } from "@/lib/i18n/use-t";
import {
  enableCollectionPlan,
  fetchCollectionPlans,
  fetchCollectionRuns,
  type CollectionPlanRow,
  type CollectionRunRow,
  type SourceRow,
} from "@/lib/landscape-api";
import { Skeleton } from "@/components/ui/toast";
import { PlanWizard } from "./plan-wizard";
import {
  RUN_BADGE,
  RUN_EN,
  RUN_ZH,
  relTime,
  useTr,
  type Tr,
} from "./sources-ui";

const MODE_EN: Record<string, string> = {
  realtime: "Realtime",
  scheduled: "Scheduled",
  backfill: "Backfill",
};

const MODE_ZH: Record<string, string> = {
  realtime: "实时",
  scheduled: "定时",
  backfill: "回补",
};

function runBadge(status: string): string {
  return RUN_BADGE[status] ?? "bg-zinc-100 text-[#6b7280]";
}

function PlanCard({
  plan,
  tr,
  zh,
  runsOpen,
  runs,
  runsLoading,
  onToggleRuns,
  onFlipEnabled,
}: {
  plan: CollectionPlanRow;
  tr: Tr;
  zh: boolean;
  runsOpen: boolean;
  runs: CollectionRunRow[];
  runsLoading: boolean;
  onToggleRuns: () => void;
  onFlipEnabled: () => void;
}) {
  return (
    <div
      className={`rounded-xl border p-3 transition-colors ${
        plan.enabled ? "" : "opacity-75"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onToggleRuns}
          aria-expanded={runsOpen}
          className="flex min-w-0 items-center gap-1.5 text-left"
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            className={`size-3.5 shrink-0 text-muted-foreground transition-transform ${runsOpen ? "rotate-90" : ""}`}
            aria-hidden="true"
          >
            <path d="m9 6 6 6-6 6" />
          </svg>
          <span className="truncate font-mono text-xs font-semibold">{plan.plan_id}</span>
        </button>
        <span className="rounded-md bg-[#dbeafe] px-1.5 py-0.5 text-[10px] font-medium text-[#2563eb]">
          {zh ? (MODE_ZH[plan.mode] ?? plan.mode) : (MODE_EN[plan.mode] ?? plan.mode)}
        </span>
        {plan.schedule ? (
          <span className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-[10px]">
            {plan.schedule}
          </span>
        ) : null}
        <span className="text-xs text-muted-foreground">
          {tr("sources.sources", "Sources")} {plan.source_ids.length}
        </span>
        <span className="ml-auto flex items-center gap-2">
          <span
            className={`text-xs ${plan.enabled ? "text-[#16a34a]" : "text-[#6b7280]"}`}
          >
            {plan.enabled ? tr("sources.enabled", "Enabled") : tr("sources.disabled", "Disabled")}
          </span>
          <button
            type="button"
            onClick={onFlipEnabled}
            className="rounded-md border px-1.5 py-0.5 text-[11px] hover:bg-muted"
          >
            {plan.enabled ? tr("sources.disable", "Disable") : tr("sources.enable", "Enable")}
          </button>
        </span>
      </div>
      <p className="mt-1 pl-5 text-[11px] text-muted-foreground">
        {tr("sources.planCreatedAt", "Created {t}", { t: relTime(plan.created_at, zh) })}
      </p>

      {runsOpen ? (
        <div className="mt-2 space-y-1.5 border-t pt-2 pl-5">
          {runsLoading ? (
            <Skeleton className="h-8 w-full rounded-md" />
          ) : runs.length === 0 ? (
            <p className="text-xs text-muted-foreground">{tr("sources.noRuns", "No runs yet.")}</p>
          ) : (
            runs.map((r) => {
              const pct = Math.max(0, Math.min(100, Math.round(r.progress ?? 0)));
              return (
                <div key={r.run_id} className="text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-[11px]">{r.run_id}</span>
                    <span className={`rounded-md px-1.5 py-0.5 text-[10px] font-medium ${runBadge(r.status)}`}>
                      {zh ? (RUN_ZH[r.status] ?? r.status) : (RUN_EN[r.status] ?? r.status)}
                    </span>
                    <span className="text-muted-foreground">
                      {tr("sources.progress", "Output")} {r.items_collected}
                    </span>
                    <span className="ml-auto text-[10px] text-muted-foreground" title={r.started_at}>
                      {relTime(r.started_at, zh)}
                    </span>
                  </div>
                  <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-muted">
                    <div
                      className={`h-full rounded-full ${
                        r.status === "failed"
                          ? "bg-[#dc2626]"
                          : r.status === "succeeded"
                            ? "bg-[#16a34a]"
                            : "bg-[#2563eb]"
                      }`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  {r.last_error ? (
                    <p className="mt-0.5 truncate text-[11px] text-[#dc2626]" title={r.last_error}>
                      {r.last_error}
                    </p>
                  ) : null}
                </div>
              );
            })
          )}
        </div>
      ) : null}
    </div>
  );
}

export function RunCenter({ sources, reloadToken }: { sources: SourceRow[]; reloadToken: number }) {
  const tr = useTr();
  const { locale } = useLocale();
  const zh = locale.startsWith("zh");
  const [plans, setPlans] = useState<CollectionPlanRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [wizardOpen, setWizardOpen] = useState(false);
  const [runsOpenId, setRunsOpenId] = useState("");
  const [runs, setRuns] = useState<CollectionRunRow[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);

  useEffect(() => {
    let alive = true;
    fetchCollectionPlans()
      .then((p) => {
        if (alive) {
          setPlans(p);
          setErr("");
        }
      })
      .catch((e: unknown) => {
        if (alive) setErr(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [reloadToken]);

  useEffect(() => {
    if (!runsOpenId) return;
    let alive = true;
    fetchCollectionRuns(runsOpenId)
      .then((r) => {
        if (alive) setRuns(r);
      })
      .catch(() => {
        if (alive) setRuns([]);
      })
      .finally(() => {
        if (alive) setRunsLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [runsOpenId]);

  const toggleRuns = (planId: string): void => {
    setRuns([]);
    setRunsLoading(true);
    setRunsOpenId((prev) => (prev === planId ? "" : planId));
  };

  const flipEnabled = (p: CollectionPlanRow): void => {
    const msg = p.enabled ? tr("sources.confirmDisable", "Disable this plan?") : tr("sources.confirmEnable", "Enable this plan?");
    if (!window.confirm(`${msg} (${p.plan_id})`)) return;
    enableCollectionPlan(p.plan_id, !p.enabled)
      .then(() => {
        setPlans((prev) =>
          prev.map((x) => (x.plan_id === p.plan_id ? { ...x, enabled: !p.enabled } : x)),
        );
        setErr("");
      })
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : String(e)));
  };

  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2">
        <h2 className="text-base font-semibold">{tr("sources.runCenter", "Run center (collection plans)")}</h2>
        <HelpIcon helpKey="agent.hitl" />
        <button
          type="button"
          onClick={() => setWizardOpen((v) => !v)}
          className="ml-auto rounded-lg border px-3 py-1.5 text-sm hover:bg-muted"
        >
          {wizardOpen ? tr("sources.closeWizard", "Close") : tr("sources.newPlan", "+ New plan")}
        </button>
      </div>

      {err ? <p className="text-sm text-[#dc2626]">{err}</p> : null}

      {wizardOpen ? (
        <PlanWizard
          sources={sources}
          tr={tr}
          zh={zh}
          onCreated={(p) => {
            setPlans((prev) => [p, ...prev]);
            setWizardOpen(false);
          }}
          onCancel={() => setWizardOpen(false)}
        />
      ) : null}

      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 2 }, (_, i) => (
            <Skeleton key={i} className="h-16 w-full rounded-xl" />
          ))}
        </div>
      ) : plans.length === 0 ? (
        <div className="rounded-xl border border-dashed p-6 text-center">
          <p className="text-sm text-muted-foreground">{tr("sources.noPlans", "No collection plans yet.")}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {tr("sources.noPlansHint", "Create a plan to schedule deterministic ETL collection (no LLM in the loop).")}
          </p>
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {plans.map((p) => (
            <PlanCard
              key={p.plan_id}
              plan={p}
              tr={tr}
              zh={zh}
              runsOpen={runsOpenId === p.plan_id}
              runs={runs}
              runsLoading={runsLoading && runsOpenId === p.plan_id}
              onToggleRuns={() => toggleRuns(p.plan_id)}
              onFlipEnabled={() => flipEnabled(p)}
            />
          ))}
        </div>
      )}
    </section>
  );
}
