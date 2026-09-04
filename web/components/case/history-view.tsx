"use client";

/**
 * HISTORY 模式：GitHub/Vercel 式时间线（虚线 + 状态色节点 + 相对时间戳）。
 * 节点点击展开运行详情（input_refs/output/error/token；failed 默认展开），
 * 顶部状态 chips 过滤；queued/running 可取消。
 * 下方保留：Claims 卡（challenge + 追问/反证回显）、claim 表单、monitor_decisions 虚线卡。
 */

import { useMemo, useState } from "react";
import { HelpIcon } from "@/components/help/help-icon";
import { Skeleton, toast } from "@/components/ui/toast";
import { objectApi, type CaseDetail, type WorkflowOut } from "@/lib/object-api";
import { useT } from "@/lib/i18n/use-t";
import {
  ModeHeader,
  StatusPill,
  runMeta,
  secondsSince,
} from "@/components/case/case-shared";

type RunDetail = {
  run_id: string;
  kind: string;
  status: string;
  engine?: string;
  model?: string;
  prompt_version?: string;
  error?: string | null;
  input_refs?: string[];
  output_artifact_id?: string | null;
  token_in?: number;
  token_out?: number;
  started_at?: string;
  finished_at?: string;
  output?: WorkflowOut | null;
};

type RunRow = CaseDetail["analysis_runs"][number];
type ClaimRow = CaseDetail["claims"][number];
type FilterKey = "all" | "running" | "succeeded" | "abstained" | "failed";

type Props = {
  caseId: string;
  detail: CaseDetail | null;
  busy: boolean;
  setBusy: (v: boolean) => void;
  refreshDetail: () => void;
};

const matchFilter = (status: string, f: FilterKey): boolean => {
  if (f === "all") return true;
  if (f === "running") return status === "running" || status === "queued";
  return status === f;
};

export default function HistoryView({ caseId, detail, busy, setBusy, refreshDetail }: Props) {
  const t = useT();
  const [filter, setFilter] = useState<FilterKey>("all");
  const [openIds, setOpenIds] = useState<Record<string, boolean>>({});
  const [details, setDetails] = useState<Record<string, RunDetail>>({});
  const [loadingRun, setLoadingRun] = useState<string | null>(null);
  const [claimText, setClaimText] = useState("");
  const [claimKind, setClaimKind] = useState("factual");
  const [challengeRes, setChallengeRes] = useState<Record<string, WorkflowOut | null>>({});

  const runs = useMemo(
    () => [...(detail?.analysis_runs ?? [])].sort((a, b) => (b.started_at ?? "").localeCompare(a.started_at ?? "")),
    [detail],
  );

  const counts = useMemo(() => {
    const c: Record<FilterKey, number> = { all: runs.length, running: 0, succeeded: 0, abstained: 0, failed: 0 };
    for (const r of runs) {
      if (matchFilter(r.status, "running")) c.running += 1;
      else if (matchFilter(r.status, "succeeded")) c.succeeded += 1;
      else if (matchFilter(r.status, "abstained")) c.abstained += 1;
      else if (matchFilter(r.status, "failed")) c.failed += 1;
    }
    return c;
  }, [runs]);

  const visibleRuns = useMemo(() => runs.filter((r) => matchFilter(r.status, filter)), [runs, filter]);

  const relLabel = (iso?: string | null): string => {
    const s = secondsSince(iso);
    if (!Number.isFinite(s)) return "—";
    if (s < 60) return t("case.relJustNow");
    if (s < 3600) return t("case.relMin", { n: Math.floor(s / 60) });
    if (s < 86400) return t("case.relHour", { n: Math.floor(s / 3600) });
    return t("case.relDay", { n: Math.floor(s / 86400) });
  };

  const isOpen = (r: RunRow): boolean =>
    openIds[r.run_id] !== undefined ? openIds[r.run_id] : r.status === "failed";

  const toggleRun = (r: RunRow) => {
    const next = !isOpen(r);
    setOpenIds((p) => ({ ...p, [r.run_id]: next }));
    if (next && details[r.run_id] === undefined && loadingRun !== r.run_id) {
      setLoadingRun(r.run_id);
      fetch(`/api/analysis-runs/${encodeURIComponent(r.run_id)}`)
        .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
        .then((d: RunDetail) => setDetails((p) => ({ ...p, [r.run_id]: d })))
        .catch(() =>
          setDetails((p) => ({
            ...p,
            [r.run_id]: {
              run_id: r.run_id,
              kind: r.kind,
              status: r.status,
              engine: r.engine,
              error: r.error,
              started_at: r.started_at,
              finished_at: r.finished_at,
            },
          })),
        )
        .finally(() => setLoadingRun(null));
    }
  };

  const cancelRun = (runId: string) => {
    setBusy(true);
    fetch(`/api/analysis-runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" })
      .then((r) => {
        if (r.ok) {
          toast.success(t("case.runCancelledDone"));
          refreshDetail();
        } else {
          toast.error(`${t("case.loadFailed")} HTTP ${r.status}`);
        }
      })
      .catch((err: unknown) =>
        toast.error(err instanceof Error ? err.message : t("case.loadFailed")),
      )
      .finally(() => setBusy(false));
  };

  const runChallenge = (claimId: string) => {
    setBusy(true);
    objectApi
      .challenge(caseId, claimId)
      .then((out) => {
        setChallengeRes((p) => ({ ...p, [claimId]: out.output }));
        refreshDetail();
        const qs = out.output?.questions ?? [];
        toast.success(`${t("case.challenged")}${qs.length > 0 ? ` · ${qs.slice(0, 2).join(" / ")}` : ""}`);
      })
      .catch((err: unknown) =>
        toast.error(err instanceof Error ? err.message : t("case.loadFailed")),
      )
      .finally(() => setBusy(false));
  };

  const addClaim = () => {
    if (!claimText.trim()) return;
    setBusy(true);
    objectApi
      .createClaim(caseId, { statement: claimText, kind: claimKind, span_ids: [] })
      .then(() => {
        setClaimText("");
        refreshDetail();
        toast.success(t("case.claimAdded"));
      })
      .catch((err: unknown) =>
        toast.error(err instanceof Error ? err.message : t("case.loadFailed")),
      )
      .finally(() => setBusy(false));
  };

  const outputSummary = (d: RunDetail): { label: string; value: string }[] => {
    const o = d.output;
    if (!o || typeof o !== "object") return [];
    const out: { label: string; value: string }[] = [];
    if (o.n_elements !== undefined) out.push({ label: t("case.outElements"), value: String(o.n_elements) });
    if (o.summary) out.push({ label: t("case.outSummary"), value: o.summary });
    if (o.agreement) out.push({ label: t("case.compareConsistent"), value: o.agreement.join(", ") || "—" });
    if (o.conflicts) out.push({ label: t("case.compareConflicts"), value: Object.keys(o.conflicts).join(", ") || "—" });
    if (o.gaps) out.push({ label: t("case.compareGaps"), value: o.gaps.join(", ") || "—" });
    if (o.artifact_id) out.push({ label: "artifact", value: o.artifact_id });
    if (o.questions) out.push({ label: t("case.questions"), value: o.questions.join(" / ") || "—" });
    if (o.engine) out.push({ label: "engine", value: o.engine });
    return out;
  };

  const claims = detail?.claims ?? [];
  const decisions = detail?.monitor_decisions ?? [];
  const nothing = runs.length === 0 && claims.length === 0 && decisions.length === 0;

  return (
    <div className="space-y-4">
      <ModeHeader title={t("case.modeTitle.history")} helpKey="help.mode.history" />

      {/* 模式说明：HISTORY 是什么 + 与 REPORT 的联动流程 */}
      <div className="rounded-xl border bg-muted/30 px-4 py-3 text-xs text-muted-foreground">
        <p className="mb-0.5 font-medium text-foreground">{t("case.historyWhat")}</p>
        <p className="mb-1">{t("case.historyDesc")}</p>
        <p className="font-medium text-foreground">{t("case.historyFlow")}</p>
      </div>

      {/* 状态 chips 过滤 */}
      {runs.length > 0 ? (
        <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
          {(
            [
              ["all", t("case.filterAll")],
              ["running", t("case.runRunning")],
              ["succeeded", t("case.runSucceeded")],
              ["abstained", t("case.runAbstained")],
              ["failed", t("case.runFailed")],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setFilter(key)}
              aria-pressed={filter === key}
              className={`rounded-md border px-1.5 py-0.5 ${filter === key ? "border-foreground font-medium" : "text-muted-foreground hover:text-foreground"}`}
            >
              {label} <span className="opacity-60">{counts[key]}</span>
            </button>
          ))}
        </div>
      ) : null}

      {/* 时间线 */}
      <section aria-label={t("case.timelineTitle")} className="space-y-0 border-l-2 border-dashed pl-4">
        {visibleRuns.map((r) => {
          const meta = runMeta(r.status);
          const open = isOpen(r);
          const d = details[r.run_id];
          const isActive = r.status === "running" || r.status === "queued";
          return (
            <div key={r.run_id} className="relative pb-2">
              <span
                aria-hidden
                className={`absolute -left-[22px] top-3.5 h-2.5 w-2.5 rounded-full ${meta.dot} ${r.status === "running" ? "animate-spin border-2 border-amber-400 border-t-transparent" : ""}`}
              />
              <div className="flex min-h-[44px] items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs">
                <button
                  type="button"
                  onClick={() => toggleRun(r)}
                  aria-expanded={open}
                  className="flex min-w-0 flex-1 flex-wrap items-center gap-2 text-left"
                >
                  <span className="w-16 shrink-0 text-[11px] text-muted-foreground" title={r.started_at?.slice(0, 19)}>
                    {relLabel(r.started_at)}
                  </span>
                  <span className="rounded bg-muted px-1.5 py-0.5 font-mono">{r.kind}</span>
                  <StatusPill status={r.status} label={r.status} />
                  {r.engine ? <span className="text-muted-foreground">{r.engine}</span> : null}
                  {r.error ? (
                    <span className="min-w-0 flex-1 truncate text-red-700 dark:text-red-300" title={r.error}>
                      {r.error}
                    </span>
                  ) : null}
                </button>
                {isActive ? (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => cancelRun(r.run_id)}
                    className="shrink-0 rounded border px-1.5 py-0.5 text-[11px] hover:bg-red-500/10 disabled:opacity-50"
                  >
                    {t("case.cancelRun")}
                  </button>
                ) : (
                  <span aria-hidden className="shrink-0 text-muted-foreground">{open ? "▾" : "▸"}</span>
                )}
              </div>
              {open ? (
                <div className="mt-1 mb-1 rounded-lg border bg-muted/20 p-2.5 text-xs">
                  {loadingRun === r.run_id && !d ? (
                    <Skeleton className="h-10 w-full" />
                  ) : d ? (
                    <div className="space-y-1.5">
                      <p className="flex flex-wrap gap-1.5">
                        {(d.input_refs ?? []).length > 0 ? (
                          <>
                            <span className="text-muted-foreground">{t("case.inputRefs")}:</span>
                            {(d.input_refs ?? []).map((ref) => (
                              <span key={ref} className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">
                                {ref}
                              </span>
                            ))}
                          </>
                        ) : (
                          <span className="text-muted-foreground">{t("case.inputRefs")}: —</span>
                        )}
                      </p>
                      {outputSummary(d).map(({ label, value }) => (
                        <p key={label} className="flex flex-wrap gap-1.5">
                          <span className="text-muted-foreground">{label}:</span>
                          <span className="min-w-0 flex-1">{value}</span>
                        </p>
                      ))}
                      {(d.token_in ?? 0) > 0 || (d.token_out ?? 0) > 0 ? (
                        <p className="text-muted-foreground">
                          {t("case.tokens")}: in {d.token_in ?? 0} / out {d.token_out ?? 0}
                          {d.model ? ` · ${d.model}` : ""}
                          {d.prompt_version ? ` · prompt ${d.prompt_version}` : ""}
                        </p>
                      ) : null}
                      {d.output_artifact_id ? (
                        <p className="text-muted-foreground">artifact: {d.output_artifact_id}</p>
                      ) : null}
                      {d.error ? (
                        <p className="rounded-md border border-red-500/40 bg-red-500/5 p-1.5 text-red-700 dark:text-red-300">
                          {t("case.errorRoot")}: {d.error}
                        </p>
                      ) : null}
                      <p className="text-[11px] text-muted-foreground">
                        {d.started_at?.slice(0, 19).replace("T", " ") ?? "—"} →{" "}
                        {d.finished_at?.slice(0, 19).replace("T", " ") ?? "—"}
                      </p>
                    </div>
                  ) : (
                    <p className="text-muted-foreground">{t("case.loading")}</p>
                  )}
                </div>
              ) : null}
            </div>
          );
        })}
        {visibleRuns.length === 0 ? (
          <p className="pb-1 text-xs text-muted-foreground">{t("case.noRuns")}</p>
        ) : null}
      </section>

      {/* Claims */}
      <section className="space-y-2" aria-label={t("case.claimsTitle")}>
        <p className="text-[13px] font-semibold">{t("case.claimsTitle")}</p>
        {claims.map((c: ClaimRow) => {
          const res = challengeRes[c.claim_id];
          return (
            <div key={c.claim_id} className="rounded-xl border p-2.5 text-xs">
              <p className="flex min-h-[36px] flex-wrap items-center gap-2">
                <span className="rounded bg-muted px-1.5 py-0.5 font-mono">{c.kind}</span>
                <span className="min-w-0 flex-1">{c.statement}</span>
                <span className="text-muted-foreground">({c.status})</span>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => runChallenge(c.claim_id)}
                  className="rounded-md border px-2 py-1 hover:bg-muted disabled:opacity-50"
                >
                  {t("case.challenge")}
                </button>
                <HelpIcon helpKey="agent.hitl" />
              </p>
              {c.spans.map((s) => (
                <p key={s.span_id} className="mt-1 border-l-2 border-muted-foreground/40 pl-2 text-muted-foreground">
                  “{s.quote}” ({s.polarity} · {s.document_revision_id})
                </p>
              ))}
              {res ? (
                <div className="mt-2 rounded-lg border bg-muted/20 p-2">
                  <p className="font-medium text-muted-foreground">{t("case.challengeResult")}</p>
                  {(res.questions ?? []).length > 0 ? (
                    <ul className="mt-1 list-disc pl-4">
                      {res.questions!.map((q, i) => (
                        <li key={`q-${i}`}>{q}</li>
                      ))}
                    </ul>
                  ) : null}
                  {(res.counter_evidence ?? []).length > 0 ? (
                    <div className="mt-1">
                      <p className="text-muted-foreground">{t("case.counterEvidence")}:</p>
                      <ul className="mt-0.5 space-y-0.5">
                        {res.counter_evidence!.map((ce) => (
                          <li key={ce.span_id} className="border-l-2 border-amber-500/60 pl-2">
                            “{ce.quote}”
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {(res.questions ?? []).length === 0 && (res.counter_evidence ?? []).length === 0 ? (
                    <p className="mt-1 text-muted-foreground">—</p>
                  ) : null}
                </div>
              ) : null}
            </div>
          );
        })}
        {claims.length === 0 ? <p className="text-xs text-muted-foreground">{t("case.noClaims")}</p> : null}

        <form
          onSubmit={(e) => {
            e.preventDefault();
            addClaim();
          }}
          className="flex flex-wrap items-center gap-2 rounded-xl border p-2.5"
        >
          <input
            value={claimText}
            onChange={(e) => setClaimText(e.target.value)}
            placeholder={t("case.claimStatement")}
            aria-label={t("case.claimStatement")}
            className="min-w-40 flex-1 rounded-md border bg-transparent px-2 py-1 text-xs"
          />
          <select
            value={claimKind}
            onChange={(e) => setClaimKind(e.target.value)}
            aria-label={t("case.claimKind")}
            className="rounded-md border bg-transparent px-1 py-1 text-xs"
          >
            <option value="factual">factual</option>
            <option value="opinion">opinion</option>
          </select>
          <button
            type="submit"
            disabled={busy || !claimText.trim()}
            className="rounded-md border px-2 py-1 text-xs hover:bg-muted disabled:opacity-50"
          >
            {t("case.addClaim")}
          </button>
        </form>
      </section>

      {/* monitor_decisions */}
      {decisions.length > 0 ? (
        <section className="space-y-1.5" aria-label={t("case.decisionsTitle")}>
          <p className="text-[13px] font-semibold">{t("case.decisionsTitle")}</p>
          {decisions.map((d) => (
            <p key={d.update_id} className="rounded-xl border border-dashed px-2.5 py-1.5 text-xs text-muted-foreground">
              {d.created_at?.slice(0, 19).replace("T", " ")} · {t("case.monitorDecision")} ·{" "}
              <span className="font-medium text-foreground">{d.decision}</span> · {d.summary}
            </p>
          ))}
        </section>
      ) : null}

      {nothing ? <p className="text-sm text-muted-foreground">{t("case.emptyHistory")}</p> : null}
    </div>
  );
}
