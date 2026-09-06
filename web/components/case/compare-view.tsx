"use client";

/**
 * COMPARE 模式：跨文档元素级 diff 表。
 * 选 ≥2 文档 → compare run → output {agreement, conflicts, missing} 渲染：
 * 一致 = 绿✓（浅绿底）/ 冲突 = 红▲（浅红底，各文档值并排）/ 缺口 = 灰斜纹。
 * 顶部统计条 "+n −n 缺n" + 比例条；可切换基准文档（基线列居首）。
 * 刷新恢复（R5）：会话内结果优先，否则从最近一次 compare run（succeeded →
 * diff 表 / abstained+blocked → 拦截卡）恢复 output；blocked 拦截卡带五因子
 * 评分分解（为什么被拦）；下方列最近 3 次 compare run 可点击回看。
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Skeleton, toast } from "@/components/ui/toast";
import { objectApi, type ExtractionRow, type WorkflowOut } from "@/lib/object-api";
import { useT } from "@/lib/i18n/use-t";
import { runStatusLabel } from "@/lib/i18n/labels";
import {
  ElementChip,
  FriendlyErrorBox,
  MISSING_CELL_BG,
  ModeHeader,
  StatusPill,
  elementOrderIndex,
  type DocRow,
  docLabel,
} from "@/components/case/case-shared";

type RowStatus = "agree" | "conflict" | "missing";

/** detail.analysis_runs 行的结构子集（刷新恢复 + 历史回看）。 */
type HistoryRunRow = {
  run_id?: string;
  kind: string;
  status: string;
  started_at?: string;
  input_refs?: string[];
  output?: unknown;
};

const domValue = (rows: ExtractionRow[] | undefined): string | null => {
  const list = rows ?? [];
  if (list.length === 0) return null;
  return list.reduce((a, b) => (b.confidence > a.confidence ? b : a)).normalized_value;
};

const isRestorableCompareRun = (r: HistoryRunRow): boolean =>
  r.kind === "compare" &&
  (r.status === "succeeded" || r.status === "abstained") &&
  !!r.output;

type Props = {
  caseId: string;
  docs: DocRow[];
  ex: Record<string, ExtractionRow[]>;
  ensureAllEx: (rids: string[]) => void;
  busy: boolean;
  setBusy: (v: boolean) => void;
  cmpOut: WorkflowOut | null;
  setCmpOut: (out: WorkflowOut | null) => void;
  /** detail.analysis_runs：刷新后从最近 compare run 恢复结果（诚实 blocked 卡 / diff 表） */
  historyRuns?: HistoryRunRow[];
  /** run 结束后刷新 detail（MAP 四视图分类真源与历史列表保持新鲜） */
  refreshDetail?: () => void;
};

export default function CompareView({
  caseId,
  docs,
  ex,
  ensureAllEx,
  busy,
  setBusy,
  cmpOut,
  setCmpOut,
  historyRuns,
  refreshDetail,
}: Props) {
  const t = useT();
  const [picked, setPicked] = useState<string[]>([]);
  const [baseline, setBaseline] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [blockedOut, setBlockedOut] = useState<WorkflowOut | null>(null);
  const [histSel, setHistSel] = useState<string | null>(null);

  // 选中文档的 extractions 惰性并行加载（值列展示用）
  useEffect(() => {
    if (picked.length === 0) return;
    ensureAllEx(picked);
  }, [picked, ensureAllEx]);

  const togglePick = (rid: string) => {
    const next = picked.includes(rid) ? picked.filter((x) => x !== rid) : [...picked, rid];
    setPicked(next);
    setBaseline((b) => (b !== null && next.includes(b) ? b : (next[0] ?? null)));
  };

  // 最近 3 次 compare run（succeeded / abstained，output 非空）；analysis_runs 新→旧
  const histRuns = useMemo<HistoryRunRow[]>(
    () => (historyRuns ?? []).filter(isRestorableCompareRun).slice(0, 3),
    [historyRuns],
  );
  // R6 类型化深链：?run=<run_id> 指定恢复该次 compare 结果（cmp- 证据 chip 回跳）。
  // 仅首命中应用一次（applied ref 防重复）；无参数 / run 不在历史 / 会话内已有结果
  // → 行为与旧版完全一致（恢复最新一次）。
  const [urlRun, setUrlRun] = useState("");
  const urlRunApplied = useRef(false);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setUrlRun(new URLSearchParams(window.location.search).get("run") ?? "");
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);
  useEffect(() => {
    if (urlRunApplied.current || !urlRun) return;
    if (cmpOut || blockedOut) return;
    if (!histRuns.some((r) => r.run_id === urlRun)) return;
    const timer = window.setTimeout(() => {
      urlRunApplied.current = true;
      setHistSel(urlRun);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [urlRun, histRuns, cmpOut, blockedOut]);
  const histSelected = useMemo<HistoryRunRow | null>(
    () => (histSel ? (histRuns.find((r) => r.run_id === histSel) ?? null) : null),
    [histSel, histRuns],
  );
  // 会话内无结果时恢复最近一次 compare run（刷新后不丢结果）
  const restoredRun = useMemo<HistoryRunRow | null>(() => {
    if (cmpOut || blockedOut) return null;
    return histRuns[0] ?? null;
  }, [cmpOut, blockedOut, histRuns]);

  // 当前展示对象（历史回看 > 会话内结果 > 历史恢复）；rids = 该 run 的输入版本
  const active = useMemo<{
    runId: string | null;
    out: WorkflowOut | null;
    blocked: WorkflowOut | null;
    rids: string[];
    fromHistory: boolean;
  } | null>(() => {
    const asOut = (r: HistoryRunRow): WorkflowOut | null => (r.output ?? null) as WorkflowOut | null;
    if (histSelected) {
      const out = asOut(histSelected);
      return {
        runId: histSelected.run_id ?? null,
        out: out && !out.blocked ? out : null,
        blocked: out?.blocked ? out : null,
        rids: histSelected.input_refs ?? [],
        fromHistory: true,
      };
    }
    if (cmpOut) {
      return { runId: cmpOut.run_id ?? null, out: cmpOut, blocked: null, rids: picked, fromHistory: false };
    }
    if (blockedOut) {
      return { runId: blockedOut.run_id ?? null, out: null, blocked: blockedOut, rids: picked, fromHistory: false };
    }
    if (restoredRun) {
      const out = asOut(restoredRun);
      return {
        runId: restoredRun.run_id ?? null,
        out: out && !out.blocked ? out : null,
        blocked: out?.blocked ? out : null,
        rids: restoredRun.input_refs ?? [],
        fromHistory: true,
      };
    }
    return null;
  }, [histSelected, cmpOut, blockedOut, restoredRun, picked]);

  const activeOut = active?.out ?? null;
  const activeBlocked = active?.blocked ?? null;
  const fromHistory = active?.fromHistory ?? false;

  // 历史回看：输入版本列（基线 = input_refs[0]）+ 惰性取 extractions
  const cols = useMemo(() => {
    const rids = fromHistory ? (active?.rids ?? []) : picked;
    if (rids.length === 0) return [] as DocRow[];
    const baseRid = fromHistory ? rids[0] : baseline;
    const base = docs.find((d) => d.document_revision_id === baseRid);
    const rest = rids
      .filter((rid, i) => (fromHistory ? i !== 0 : rid !== baseline))
      .map((rid) => docs.find((d) => d.document_revision_id === rid))
      .filter((d): d is DocRow => Boolean(d));
    return base ? [base, ...rest] : rest;
  }, [active, docs, picked, baseline, fromHistory]);

  useEffect(() => {
    if (fromHistory && (active?.rids.length ?? 0) > 0) ensureAllEx(active!.rids);
  }, [fromHistory, active, ensureAllEx]);

  const diffRows = useMemo(() => {
    if (!activeOut) return [] as { element: string; status: RowStatus; classification?: string }[];
    const conflicts = activeOut.conflicts ?? {};
    const agree = new Set(activeOut.agreement ?? []);
    const missing = new Set([...(activeOut.missing ?? []), ...(activeOut.gaps ?? [])]);
    const keys = new Set<string>([...agree, ...Object.keys(conflicts), ...missing]);
    return [...keys]
      .map((element) => ({
        element,
        status: (conflicts[element] ? "conflict" : agree.has(element) ? "agree" : "missing") as RowStatus,
        classification:
          typeof conflicts[element]?.classification === "string" ? conflicts[element].classification : undefined,
      }))
      .sort((a, b) => elementOrderIndex(a.element) - elementOrderIndex(b.element));
  }, [activeOut]);

  const counts = useMemo(
    () => ({
      agree: diffRows.filter((r) => r.status === "agree").length,
      conflict: diffRows.filter((r) => r.status === "conflict").length,
      gap: diffRows.filter((r) => r.status === "missing").length,
    }),
    [diffRows],
  );

  const runCompare = () => {
    setBusy(true);
    setRunError(null);
    setBlockedOut(null);
    setHistSel(null);
    objectApi
      .compare(caseId, picked)
      .then((r) => {
        if (r.status === "failed") {
          setRunError(r.error || r.status);
          toast.error(r.error || t("case.loadFailed"));
        } else if (r.output?.blocked) {
          // 相关性门槛拦截：不渲染 diff 表，诚实呈现拦截原因（P0-2）
          setBlockedOut(r.output);
          setCmpOut(null);
          toast.info(r.output.summary || t("case.compareBlocked"));
        } else if (!r.output) {
          setRunError(r.status);
          toast.info(`${t("case.status")}: ${r.status}`);
        } else {
          setCmpOut(r.output);
          toast.success(t("case.compareDone"));
        }
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : t("case.loadFailed");
        setRunError(msg);
        toast.error(msg);
      })
      .finally(() => {
        setBusy(false);
        refreshDetail?.();
      });
  };

  if (docs.length < 2) {
    return (
      <div className="space-y-3">
        <ModeHeader title={t("case.modeTitle.compare")} helpKey="help.mode.compare" />
        <p className="rounded-xl border border-dashed p-4 text-sm text-muted-foreground">{t("case.compareNeedTwo")}</p>
      </div>
    );
  }

  const total = counts.agree + counts.conflict + counts.gap;
  const pct = (n: number) => (total === 0 ? 0 : Math.round((n / total) * 100));
  // 五因子数值格式化：缺失/不可解析 → "—"（诚实，不编造）
  const fmtNum = (v: number | null | undefined, digits = 2): string =>
    typeof v === "number" && Number.isFinite(v) ? v.toFixed(digits) : "—";
  const breakdown = activeBlocked?.eligibility ?? null;
  const breakdownCells: { label: string; value: string }[] = breakdown
    ? [
        { label: t("case.factorEntityOverlap"), value: fmtNum(breakdown.entity_overlap) },
        { label: t("case.factorTopicOverlap"), value: fmtNum(breakdown.topic_similarity) },
        { label: t("case.factorTimeDistance"), value: fmtNum(breakdown.time_distance_hours, 1) },
        { label: t("case.factorSameEventScore"), value: fmtNum(breakdown.same_event_score) },
        { label: t("case.factorComparisonMode"), value: breakdown.comparison_mode ?? "—" },
      ]
    : [];

  return (
    <div className="space-y-3">
      <ModeHeader title={t("case.modeTitle.compare")} helpKey="help.mode.compare">
        <span className="text-xs text-muted-foreground">{t("case.comparePickHint")}</span>
      </ModeHeader>

      <div className="flex flex-wrap gap-1.5">
        {docs.map((d) => (
          <button
            key={d.document_revision_id}
            type="button"
            onClick={() => togglePick(d.document_revision_id)}
            aria-pressed={picked.includes(d.document_revision_id)}
            className={`rounded-md border px-2 py-1 text-xs ${picked.includes(d.document_revision_id) ? "border-sky-500 bg-sky-500/5 font-medium" : "text-muted-foreground hover:text-foreground"}`}
          >
            {docLabel(d)}
            <span className="ml-1 opacity-60">{d.language}</span>
          </button>
        ))}
      </div>

      {picked.length >= 2 ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">{t("case.compareBaseline")}:</span>
          {picked.map((rid) => (
            <button
              key={rid}
              type="button"
              onClick={() => setBaseline(rid)}
              aria-pressed={baseline === rid}
              className={`rounded-md border px-1.5 py-0.5 text-xs ${baseline === rid ? "border-foreground font-medium" : "text-muted-foreground hover:text-foreground"}`}
            >
              {docs.find((d) => d.document_revision_id === rid)?.source_id ?? rid}
            </button>
          ))}
          <button
            type="button"
            disabled={busy}
            onClick={runCompare}
            className="ml-auto rounded-md border px-3 py-1.5 text-xs font-medium hover:bg-muted disabled:opacity-50"
          >
            {t("case.compare")}
          </button>
        </div>
      ) : null}

      {busy ? <Skeleton className="h-10 w-full" /> : null}

      {runError ? <FriendlyErrorBox raw={runError} className="rounded-xl border border-red-500/40 bg-red-500/5 p-3 text-xs text-red-700 dark:text-red-300" /> : null}

      {activeBlocked && !busy ? (
        <section className="rounded-xl border border-amber-500/40 bg-amber-500/5 p-4" aria-live="polite">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded bg-[#fef3c7] px-1.5 py-0.5 text-[11px] font-medium text-[#b45309] dark:bg-amber-500/15 dark:text-amber-300">
              {breakdown?.comparison_mode === "cross_event_analogy"
                ? t("case.crossEventMode")
                : t("case.compareBlocked")}
            </span>
            {fromHistory ? (
              <span className="font-mono text-[11px] text-muted-foreground">{active?.runId}</span>
            ) : null}
          </div>
          <p className="mt-2 text-sm">{activeBlocked.summary}</p>
          {breakdown ? (
            <div className="mt-3" aria-label={t("case.compareBreakdown")}>
              <p className="text-[11px] font-medium text-muted-foreground">{t("case.compareBreakdown")}</p>
              <div className="mt-1 grid grid-cols-2 gap-1.5 sm:grid-cols-3 lg:grid-cols-5">
                {breakdownCells.map((c) => (
                  <div key={c.label} className="rounded-md border bg-background/60 px-2 py-1.5">
                    <p className="text-[10px] text-muted-foreground">{c.label}</p>
                    <p className="font-mono text-xs">{c.value}</p>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </section>
      ) : null}

      {activeOut && !busy ? (
        <>
          {/* 统计条：+一致 −冲突 缺缺口 + 比例条 */}
          <section className="rounded-xl border p-3" aria-label={t("case.statBar")}>
            <div className="flex flex-wrap items-center gap-3 text-xs font-medium">
              <span className="text-emerald-700 dark:text-emerald-300">+{counts.agree} {t("case.compareConsistent")}</span>
              <span className="text-red-700 dark:text-red-300">−{counts.conflict} {t("case.compareConflicts")}</span>
              <span className="text-zinc-500">缺{counts.gap} {t("case.compareGaps")}</span>
              {fromHistory ? (
                <span className="font-mono text-[11px] text-muted-foreground">{active?.runId}</span>
              ) : activeOut.comparison_id ? (
                <span className="ml-auto font-mono text-[11px] text-muted-foreground">{activeOut.comparison_id}</span>
              ) : null}
            </div>
            <div className="mt-2 flex h-1.5 overflow-hidden rounded bg-muted">
              <span className="h-full" style={{ width: `${pct(counts.agree)}%`, backgroundColor: "#16a34a" }} />
              <span className="h-full" style={{ width: `${pct(counts.conflict)}%`, backgroundColor: "#dc2626" }} />
              <span className="h-full" style={{ width: `${pct(counts.gap)}%`, backgroundColor: "#6b7280" }} />
            </div>
            {activeOut.summary ? <p className="mt-2 text-xs text-muted-foreground">{activeOut.summary}</p> : null}
          </section>

          {/* 元素级 diff 表 */}
          <section className="overflow-x-auto rounded-xl border">
            <table className="w-full min-w-max border-collapse text-xs">
              <thead>
                <tr className="border-b bg-muted/40">
                  <th className="p-2 text-left font-medium">{t("case.elementCol")}</th>
                  <th className="p-2 text-left font-medium">{t("case.diffStatus")}</th>
                  {cols.map((d, i) => (
                    <th key={d.document_revision_id} className="p-2 text-left font-medium">
                      {docLabel(d)}
                      {i === 0 && (fromHistory ? active!.rids[0] : baseline) === d.document_revision_id ? (
                        <span className="ml-1 rounded bg-foreground/10 px-1 py-0.5 text-[10px]">{t("case.baselineTag")}</span>
                      ) : null}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {diffRows.map(({ element, status, classification }) => (
                  <tr key={element} className="border-b last:border-b-0">
                    <td className="p-2">
                      <ElementChip elementKey={element} />
                    </td>
                    <td className="p-2">
                      {status === "agree" ? (
                        <span className="rounded bg-[#dcfce7] px-1.5 py-0.5 font-medium text-[#15803d] dark:bg-emerald-500/15 dark:text-emerald-300">
                          ✓ {t("case.diffAgree")}
                        </span>
                      ) : status === "conflict" ? (
                        <span className="rounded bg-[#fee2e2] px-1.5 py-0.5 font-medium text-[#b91c1c] dark:bg-red-500/15 dark:text-red-300">
                          ▲ {classification === "narrative_difference" ? t("case.diffNarrative") : t("case.diffFact")}
                        </span>
                      ) : (
                        <span className="rounded bg-zinc-500/10 px-1.5 py-0.5 text-zinc-500">{t("case.missingShort")}</span>
                      )}
                    </td>
                    {cols.map((d) => {
                      const v = domValue(ex[d.document_revision_id]?.filter((e) => e.element_key === element));
                      if (v === null) {
                        return (
                          <td key={d.document_revision_id} className="p-1.5">
                            <span
                              className={`flex h-8 items-center justify-center rounded-md px-2 text-[11px] text-zinc-400 ${MISSING_CELL_BG}`}
                            >
                              {t("case.missingShort")}
                            </span>
                          </td>
                        );
                      }
                      const tint =
                        status === "conflict"
                          ? "bg-[#fee2e2] text-[#7f1d1d] dark:bg-red-500/10 dark:text-red-200"
                          : status === "agree"
                            ? "bg-[#dcfce7] text-[#14532d] dark:bg-emerald-500/10 dark:text-emerald-200"
                            : "";
                      return (
                        <td key={d.document_revision_id} className="p-1.5">
                          <span className={`block h-8 rounded-md px-2 leading-8 ${tint}`} title={v}>
                            <span className="line-clamp-1">{v}</span>
                          </span>
                        </td>
                      );
                    })}
                  </tr>
                ))}
                {diffRows.length === 0 ? (
                  <tr>
                    <td colSpan={cols.length + 2} className="p-6 text-center text-muted-foreground">
                      {t("case.compareNoDiff")}
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </section>
        </>
      ) : null}

      {!active && !busy && !runError ? (
        <p className="rounded-xl border border-dashed p-4 text-sm text-muted-foreground">{t("case.compareNoResult")}</p>
      ) : null}

      {/* 历史版本：最近 3 次 compare run，点击回看该次 output */}
      {histRuns.length > 0 && !busy ? (
        <section className="rounded-xl border p-3" aria-label={t("case.compareHistory")}>
          <p className="mb-1.5 text-[13px] font-semibold">{t("case.compareHistory")}</p>
          <ul className="space-y-1">
            {histRuns.map((r) => {
              const out = (r.output ?? null) as WorkflowOut | null;
              const rid = r.run_id ?? "";
              const isSel = histSel !== null && histSel === rid;
              return (
                <li key={rid || r.started_at || out?.summary}>
                  <button
                    type="button"
                    onClick={() => setHistSel(isSel ? null : rid || null)}
                    aria-pressed={isSel}
                    className={`flex w-full flex-wrap items-center gap-2 rounded-md border px-2 py-1.5 text-xs ${isSel ? "border-sky-500 bg-sky-500/5" : "hover:bg-muted"}`}
                  >
                    <StatusPill status={r.status} label={runStatusLabel(t, r.status)} />
                    <span className="font-mono text-[11px]">{rid || "—"}</span>
                    <span className="text-[11px] text-muted-foreground">
                      {(r.started_at ?? "").slice(0, 19).replace("T", " ")}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-muted-foreground" title={out?.summary ?? ""}>
                      {out?.summary ?? ""}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
