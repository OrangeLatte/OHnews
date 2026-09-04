"use client";

/**
 * COMPARE 模式：跨文档元素级 diff 表。
 * 选 ≥2 文档 → compare run → output {agreement, conflicts, gaps} 渲染：
 * 一致 = 绿✓（浅绿底）/ 冲突 = 红▲（浅红底，各文档值并排）/ 缺口 = 灰斜纹。
 * 顶部统计条 "+n −n 缺n" + 比例条；可切换基准文档（基线列居首）。
 */

import { useEffect, useMemo, useState } from "react";
import { Skeleton, toast } from "@/components/ui/toast";
import { objectApi, type ExtractionRow, type WorkflowOut } from "@/lib/object-api";
import { useT } from "@/lib/i18n/use-t";
import {
  ElementChip,
  MISSING_CELL_BG,
  ModeHeader,
  elementOrderIndex,
  type DocRow,
} from "@/components/case/case-shared";

type RowStatus = "agree" | "conflict" | "gap";

const domValue = (rows: ExtractionRow[] | undefined): string | null => {
  const list = rows ?? [];
  if (list.length === 0) return null;
  return list.reduce((a, b) => (b.confidence > a.confidence ? b : a)).normalized_value;
};

type Props = {
  caseId: string;
  docs: DocRow[];
  ex: Record<string, ExtractionRow[]>;
  ensureAllEx: (rids: string[]) => void;
  busy: boolean;
  setBusy: (v: boolean) => void;
  cmpOut: WorkflowOut | null;
  setCmpOut: (out: WorkflowOut | null) => void;
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
}: Props) {
  const t = useT();
  const [picked, setPicked] = useState<string[]>([]);
  const [baseline, setBaseline] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

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

  const cols = useMemo(() => {
    if (picked.length === 0) return [] as DocRow[];
    const base = docs.find((d) => d.document_revision_id === baseline);
    const rest = picked
      .filter((rid) => rid !== baseline)
      .map((rid) => docs.find((d) => d.document_revision_id === rid))
      .filter((d): d is DocRow => Boolean(d));
    return base ? [base, ...rest] : rest;
  }, [docs, picked, baseline]);

  const diffRows = useMemo(() => {
    if (!cmpOut) return [] as { element: string; status: RowStatus }[];
    const conflicts = cmpOut.conflicts ?? {};
    const agree = new Set(cmpOut.agreement ?? []);
    const gaps = new Set(cmpOut.gaps ?? []);
    const keys = new Set<string>([...agree, ...Object.keys(conflicts), ...gaps]);
    return [...keys]
      .map((element) => ({
        element,
        status: (conflicts[element] ? "conflict" : agree.has(element) ? "agree" : "gap") as RowStatus,
      }))
      .sort((a, b) => elementOrderIndex(a.element) - elementOrderIndex(b.element));
  }, [cmpOut]);

  const counts = useMemo(
    () => ({
      agree: diffRows.filter((r) => r.status === "agree").length,
      conflict: diffRows.filter((r) => r.status === "conflict").length,
      gap: diffRows.filter((r) => r.status === "gap").length,
    }),
    [diffRows],
  );

  const runCompare = () => {
    setBusy(true);
    setRunError(null);
    objectApi
      .compare(caseId, picked)
      .then((r) => {
        if (r.status === "failed") {
          setRunError(r.error || r.status);
          toast.error(r.error || t("case.loadFailed"));
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
      .finally(() => setBusy(false));
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
            {d.source_id}
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

      {runError ? (
        <p className="rounded-xl border border-red-500/40 bg-red-500/5 p-3 text-xs text-red-700 dark:text-red-300">
          {t("case.runError")}: {runError}
        </p>
      ) : null}

      {cmpOut && !busy ? (
        <>
          {/* 统计条：+一致 −冲突 缺缺口 + 比例条 */}
          <section className="rounded-xl border p-3" aria-label={t("case.statBar")}>
            <div className="flex flex-wrap items-center gap-3 text-xs font-medium">
              <span className="text-emerald-700 dark:text-emerald-300">+{counts.agree} {t("case.compareConsistent")}</span>
              <span className="text-red-700 dark:text-red-300">−{counts.conflict} {t("case.compareConflicts")}</span>
              <span className="text-zinc-500">缺{counts.gap} {t("case.compareGaps")}</span>
              {cmpOut.comparison_id ? (
                <span className="ml-auto font-mono text-[11px] text-muted-foreground">{cmpOut.comparison_id}</span>
              ) : null}
            </div>
            <div className="mt-2 flex h-1.5 overflow-hidden rounded bg-muted">
              <span className="h-full" style={{ width: `${pct(counts.agree)}%`, backgroundColor: "#16a34a" }} />
              <span className="h-full" style={{ width: `${pct(counts.conflict)}%`, backgroundColor: "#dc2626" }} />
              <span className="h-full" style={{ width: `${pct(counts.gap)}%`, backgroundColor: "#6b7280" }} />
            </div>
            {cmpOut.summary ? <p className="mt-2 text-xs text-muted-foreground">{cmpOut.summary}</p> : null}
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
                      {d.source_id}
                      {i === 0 && baseline ? (
                        <span className="ml-1 rounded bg-foreground/10 px-1 py-0.5 text-[10px]">{t("case.baselineTag")}</span>
                      ) : null}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {diffRows.map(({ element, status }) => (
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
                          ▲ {t("case.diffConflict")}
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

      {!cmpOut && !busy && !runError ? (
        <p className="rounded-xl border border-dashed p-4 text-sm text-muted-foreground">{t("case.compareNoResult")}</p>
      ) : null}
    </div>
  );
}
