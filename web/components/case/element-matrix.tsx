"use client";

/**
 * MAP 模式：质性编码矩阵（NVivo/Atlas.ti 式）。
 * 行 = 案内出现过的元素，列 = 案内文档；单元格 = 主导值摘要 + 元素色点 + 计数，
 * hover tooltip 全值，点击展开底部详情面板（值/来源等级/语言/证据数/锚点深链/
 * 复核状态）。行/列 header 点击排序；上方每元素文档覆盖率统计条；空格灰斜纹。
 * 四视图 chips（全部/共识/分歧/缺失）：分类真源 = 最近一次 compare run 的
 * output；无 compare 结果时后三视图诚实禁用（不造分类）。
 */

import { useEffect, useMemo, useState } from "react";
import { HelpIcon } from "@/components/help/help-icon";
import { Skeleton } from "@/components/ui/toast";
import { objectApi, type ExtractionRow } from "@/lib/object-api";
import { useT } from "@/lib/i18n/use-t";
import {
  ElementChip,
  MISSING_CELL_BG,
  EmptyHint,
  ModeHeader,
  elementColor,
  elementOrderIndex,
  reviewPillClass,
  type DocRow,
  docLabel,
} from "@/components/case/case-shared";
import { elementEdge } from "@/lib/element-tokens";

type CellSelection = { element: string; rid: string } | null;
type ElemSort = "default" | "az";
type DocSort = "default" | "az";
type MatrixView = "all" | "consensus" | "conflict" | "missing";

/** MAP 四视图分类真源：compare run output 的四分结果（结构兼容 WorkflowOut 子集）。 */
export type MatrixCompareOut = {
  agreement?: string[];
  conflicts?: Record<string, Record<string, string>>;
  missing?: string[];
} | null;

const dominant = (rows: ExtractionRow[]): ExtractionRow | null =>
  rows.length === 0 ? null : rows.reduce((a, b) => (b.confidence > a.confidence ? b : a));

type Props = {
  caseId: string;
  docs: DocRow[];
  busy: boolean;
  dissecting: string | null;
  onDissect: (rid: string) => void;
  /** source_id → tier（来源等级），workspace 从 /api/sources 建 map 传入 */
  sourceTier: Record<string, string>;
  /** 最近一次 compare run 的四分结果；null = 无 compare 结果（后三视图禁用） */
  compareOut: MatrixCompareOut;
};

export default function ElementMatrix({
  caseId,
  docs,
  busy,
  dissecting,
  onDissect,
  sourceTier,
  compareOut,
}: Props) {
  const t = useT();
  const [exMap, setExMap] = useState<Record<string, ExtractionRow[]>>({});
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<CellSelection>(null);
  const [elemSort, setElemSort] = useState<ElemSort>("default");
  const [docSort, setDocSort] = useState<DocSort>("default");
  const [reloadKey, setReloadKey] = useState(0);
  const [view, setView] = useState<MatrixView>("all");

  // 全文档并行拉取 extractions（Promise.all）；dissect 完成后 bump reloadKey 重取
  useEffect(() => {
    if (docs.length === 0) return;
    let alive = true;
    Promise.all(
      docs.map((d) =>
        objectApi
          .extractions(d.document_revision_id)
          .then((rows) => [d.document_revision_id, rows] as const)
          .catch(() => [d.document_revision_id, [] as ExtractionRow[]] as const),
      ),
    ).then((pairs) => {
      if (!alive) return;
      setExMap(Object.fromEntries(pairs));
      setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, [docs, reloadKey]);

  // dissect 完成信号（渲染期状态调整，React 官方模式）：dissecting 非空 → null 时重取
  const [prevDissecting, setPrevDissecting] = useState<string | null>(null);
  if (prevDissecting !== dissecting) {
    setPrevDissecting(dissecting);
    if (prevDissecting !== null && dissecting === null) setReloadKey((k) => k + 1);
  }

  const cols = useMemo(() => {
    const list = [...docs];
    return docSort === "az" ? list.sort((a, b) => a.source_id.localeCompare(b.source_id)) : list;
  }, [docs, docSort]);

  const byCell = useMemo(() => {
    const m = new Map<string, ExtractionRow[]>();
    for (const [rid, list] of Object.entries(exMap)) {
      for (const e of list) {
        const key = `${e.element_key}\u0000${rid}`;
        const arr = m.get(key) ?? [];
        arr.push(e);
        m.set(key, arr);
      }
    }
    return m;
  }, [exMap]);

  const cellRows = (element: string, rid: string): ExtractionRow[] =>
    byCell.get(`${element}\u0000${rid}`) ?? [];

  const rows = useMemo(() => {
    const present = new Set<string>();
    for (const list of byCell.values()) for (const e of list) present.add(e.element_key);
    const list = [...present];
    return elemSort === "az"
      ? list.sort((a, b) => a.localeCompare(b))
      : list.sort((a, b) => elementOrderIndex(a) - elementOrderIndex(b));
  }, [byCell, elemSort]);

  // 四视图分类集合（真源 = compare run output；null → 后三视图禁用）
  const viewSets = useMemo(
    () => ({
      agree: new Set(compareOut?.agreement ?? []),
      conflict: new Set(Object.keys(compareOut?.conflicts ?? {})),
      missing: new Set(compareOut?.missing ?? []),
      hasResult: compareOut !== null,
    }),
    [compareOut],
  );

  const shownRows = useMemo(() => {
    if (view === "all") return rows;
    const set = view === "consensus" ? viewSets.agree : view === "conflict" ? viewSets.conflict : viewSets.missing;
    return rows.filter((r) => set.has(r));
  }, [rows, view, viewSets]);

  const selectView = (v: MatrixView) => {
    setView(v);
    setSelected(null);
  };

  const coverage = useMemo(
    () =>
      rows.map((element) => ({
        element,
        covered: docs.filter(
          (d) => (byCell.get(`${element}\u0000${d.document_revision_id}`) ?? []).length > 0,
        ).length,
      })),
    [rows, docs, byCell],
  );

  const selectedDetail =
    selected !== null
      ? {
          doc: docs.find((d) => d.document_revision_id === selected.rid) ?? null,
          rows: cellRows(selected.element, selected.rid),
        }
      : null;
  const selTier = selectedDetail?.doc
    ? (sourceTier[selectedDetail.doc.source_id] ?? "—")
    : "—";
  const selLanguage = selectedDetail?.doc?.language || "—";

  if (docs.length === 0) {
    return (
      <div className="space-y-3">
        <ModeHeader title={t("case.modeTitle.map")} helpKey="help.mode.map" />
        <EmptyHint text={t("case.gotoObserve")} action={t("case.gotoObserveAction")} href="/observe" />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <ModeHeader title={t("case.modeTitle.map")} helpKey="help.mode.map">
        <span className="text-xs text-muted-foreground">
          {rows.length} × {docs.length}
        </span>
      </ModeHeader>

      {/* 覆盖率统计条：每元素 N/M 文档 + 绿色比例条 */}
      <section className="rounded-xl border p-2" aria-label={t("case.matrixCoverage")}>
        <p className="mb-1.5 flex items-center gap-1 text-xs font-medium text-muted-foreground">
          {t("case.matrixCoverage")}
          <HelpIcon helpKey="help.mode.map" />
        </p>
        <div className="grid grid-cols-2 gap-x-3 gap-y-1 sm:grid-cols-3 xl:grid-cols-5">
          {coverage.map(({ element, covered }) => (
            <div key={element} className="flex items-center gap-1.5 text-[11px]">
              <ElementChip elementKey={element} />
              <span className="w-9 shrink-0 tabular-nums text-muted-foreground">
                {covered}/{docs.length}
              </span>
              <span className="h-1 min-w-6 flex-1 overflow-hidden rounded bg-muted">
                <span
                  className="block h-full rounded"
                  style={{ width: `${docs.length === 0 ? 0 : Math.round((covered / docs.length) * 100)}%`, backgroundColor: "#16a34a" }}
                />
              </span>
            </div>
          ))}
          {coverage.length === 0 && !loading ? (
            <p className="col-span-full text-xs text-muted-foreground">{t("case.notDissected")}</p>
          ) : null}
        </div>
      </section>

      {/* 四视图切换 chips：分类真源 = 最近一次 compare run output */}
      <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={t("case.modeTitle.map")}>
        {(
          [
            ["all", "case.matrixView.all"],
            ["consensus", "case.matrixView.consensus"],
            ["conflict", "case.matrixView.conflict"],
            ["missing", "case.matrixView.missing"],
          ] as const
        ).map(([v, key]) => {
          const disabled = v !== "all" && !viewSets.hasResult;
          return (
            <button
              key={v}
              type="button"
              disabled={disabled}
              onClick={() => selectView(v)}
              aria-pressed={view === v}
              title={disabled ? t("case.matrixViewNeedCompare") : undefined}
              className={`rounded-md border px-2 py-1 text-xs ${view === v ? "border-sky-500 bg-sky-500/5 font-medium" : ""} ${disabled ? "cursor-not-allowed text-muted-foreground/50" : "hover:bg-muted"}`}
            >
              {t(key)}
            </button>
          );
        })}
      </div>

      {/* 元素 × 文档矩阵 */}
      <section className="overflow-x-auto rounded-xl border" aria-label={t("case.modeTitle.map")}>
        {loading ? (
          <div className="space-y-2 p-3">
            {["a", "b", "c", "d", "e"].map((k, i) => (
              <Skeleton key={k} className={`h-8 ${i % 2 ? "w-11/12" : "w-full"}`} />
            ))}
          </div>
        ) : (
          <table className="w-full min-w-max border-collapse text-xs">
            <thead>
              <tr className="border-b">
                <th className="sticky left-0 z-10 bg-background p-2 text-left align-bottom">
                  <button
                    type="button"
                    onClick={() => setElemSort((p) => (p === "default" ? "az" : "default"))}
                    className="rounded-md border px-1.5 py-0.5 font-medium hover:bg-muted"
                    title={t("case.sortRows")}
                  >
                    {t("case.elementCol")}
                    {elemSort === "az" ? " ▲" : " ↕"}
                  </button>
                </th>
                {cols.map((d) => (
                  <th key={d.document_revision_id} className="p-1.5 text-left align-bottom">
                    <button
                      type="button"
                      onClick={() => setDocSort((p) => (p === "default" ? "az" : "default"))}
                      className="rounded-md px-1 py-0.5 font-medium hover:bg-muted"
                      title={t("case.sortCols")}
                    >
                      {docLabel(d)}
                      <span className="ml-1 opacity-60">{d.language}</span>
                      {docSort === "az" ? " ▲" : ""}
                    </button>
                    <button
                      type="button"
                      disabled={busy || dissecting !== null}
                      onClick={() => onDissect(d.document_revision_id)}
                      className="ml-1 rounded-md border px-1 py-0.5 text-[10px] font-normal hover:bg-muted disabled:opacity-50"
                    >
                      {dissecting === d.document_revision_id ? t("case.dissecting") : t("case.dissect")}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shownRows.map((element) => (
                <tr key={element} className="border-b last:border-b-0">
                  <th className="sticky left-0 z-10 bg-background p-2 text-left font-medium">
                    <ElementChip elementKey={element} />
                  </th>
                  {cols.map((d) => {
                    const list = cellRows(element, d.document_revision_id);
                    const dom = dominant(list);
                    const isSel =
                      selected !== null && selected.element === element && selected.rid === d.document_revision_id;
                    if (!dom) {
                      return (
                        <td key={d.document_revision_id} className="p-1">
                          <div
                            className={`flex h-9 items-center justify-center rounded-md px-2 text-[11px] text-zinc-400 ${MISSING_CELL_BG}`}
                            title={t("case.cellMissing")}
                          >
                            {t("case.missingShort")}
                          </div>
                        </td>
                      );
                    }
                    const tooltip = list.map((e) => `• ${e.normalized_value}`).join("\n");
                    return (
                      <td key={d.document_revision_id} className="p-1">
                        <button
                          type="button"
                          onClick={() => setSelected(isSel ? null : { element, rid: d.document_revision_id })}
                          aria-expanded={isSel}
                          title={tooltip}
                          className={`h-9 w-full rounded-md border px-2 text-left text-[11px] leading-tight hover:border-muted-foreground/50 ${isSel ? "border-sky-500 ring-1 ring-sky-500" : ""}`}
                        >
                          <span className="flex items-center gap-1.5">
                            <span
                              aria-hidden
                              className="h-2 w-2 shrink-0 rounded-sm"
                              style={{
                                backgroundColor: elementColor(element),
                                border: `1px solid ${elementEdge(element)}`,
                              }}
                            />
                            <span className="min-w-0 flex-1 truncate">{dom.normalized_value}</span>
                            {list.length > 1 ? <span className="shrink-0 opacity-60">×{list.length}</span> : null}
                          </span>
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
              {shownRows.length === 0 ? (
                <tr>
                  <td colSpan={cols.length + 1} className="p-6 text-center text-muted-foreground">
                    {view === "all" ? t("case.notDissected") : t("case.noMatch")}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        )}
      </section>

      {/* 底部详情面板 */}
      {selectedDetail && selected !== null ? (
        <section className="rounded-xl border p-3" aria-label={t("case.matrixDetail")}>
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <p className="text-[13px] font-semibold">
              <span className="font-mono text-xs text-muted-foreground">{t("case.matrixDetail")}:</span>{" "}
              {selected.element}
            </p>
            <span className="text-xs text-muted-foreground">
              @ {selectedDetail.doc?.source_id ?? selected.rid}
            </span>
            <span className="text-xs text-muted-foreground">
              {t("case.matrixSourceTier")}: <span className="font-mono">{selTier}</span>
            </span>
            <span className="text-xs text-muted-foreground">
              {t("case.matrixLanguage")}: <span className="font-mono">{selLanguage}</span>
            </span>
            <button
              type="button"
              onClick={() => setSelected(null)}
              className="ml-auto rounded-md border px-2 py-0.5 text-xs hover:bg-muted"
            >
              ×
            </button>
          </div>
          {selectedDetail.rows.length === 0 ? (
            <p className="text-xs text-muted-foreground">{t("case.cellMissing")}</p>
          ) : (
            <ul className="space-y-2">
              {selectedDetail.rows.map((e) => {
                const span0 = e.spans?.[0] ?? null;
                const anchorHref = span0
                  ? `/cases/${encodeURIComponent(caseId)}?mode=read&doc=${encodeURIComponent(e.document_revision_id)}`
                  : null;
                return (
                  <li key={e.extraction_id} className="rounded-lg border p-2 text-xs">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="min-w-0 flex-1">{e.normalized_value}</span>
                      <span className="text-muted-foreground">
                        {t("case.confidence")} {(e.confidence * 100).toFixed(0)}%
                      </span>
                      <span className={`rounded px-1 py-0.5 ${reviewPillClass(e.human_status)}`}>
                        {e.human_status}
                      </span>
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                      <span>
                        {t("case.matrixEvidenceCount")}:{" "}
                        <span className="font-mono">{(e.spans ?? []).length}</span>
                      </span>
                      {anchorHref ? (
                        <a
                          href={anchorHref}
                          title={t("case.matrixAnchorLink")}
                          className="font-mono underline decoration-dotted underline-offset-2 hover:text-foreground"
                        >
                          {t("case.matrixAnchorLink")} ↗ {span0?.span_id}
                        </a>
                      ) : (
                        <span className="rounded bg-muted px-1 py-0.5 italic">{t("case.inferredBadge")}</span>
                      )}
                    </div>
                    {e.uncertainty_reason ? (
                      <p className="mt-1 italic text-muted-foreground">
                        {t("case.uncertainty")}: {e.uncertainty_reason}
                      </p>
                    ) : null}
                    {(e.spans ?? []).length > 0 ? (
                      <ul className="mt-1 space-y-0.5">
                        {(e.spans ?? []).map((s) => (
                          <li
                            key={`${e.extraction_id}-${s.span_id}`}
                            className="border-l-2 border-muted-foreground/40 pl-2 text-muted-foreground"
                          >
                            “{s.quote}”
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      ) : null}
    </div>
  );
}
