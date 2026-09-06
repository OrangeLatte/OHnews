"use client";

/**
 * 信源结果表：列头可点击排序（升/降切换）、行展开显示近期产出明细与
 * 「立即采集」按钮（POST /api/sources/{id}/refresh，HITL confirm）。
 */

import { useState } from "react";
import type { SourceRow } from "@/lib/landscape-api";
import { useT } from "@/lib/i18n/use-t";
import { ConfirmButton } from "@/components/ui/confirm-button";
import { TIER_HINT_KEYS, kindLabel } from "@/lib/sources-meta";
import { HEALTH_BADGE, HEALTH_DOT, healthOf, type Health, type Tr } from "./sources-ui";

export type SortKey =
  | "source_id"
  | "tier"
  | "kind"
  | "language"
  | "n_7d"
  | "n_30d"
  | "last_seen";
export type SortDir = "asc" | "desc";

const COLUMNS: { key: SortKey | "health"; labelKey: string; en: string; sortable: boolean }[] = [
  { key: "source_id", labelKey: "sources.id", en: "Source", sortable: true },
  { key: "tier", labelKey: "sources.tier", en: "Tier", sortable: true },
  { key: "kind", labelKey: "sources.kind", en: "Kind", sortable: true },
  { key: "language", labelKey: "sources.language", en: "Language", sortable: true },
  { key: "n_7d", labelKey: "sources.n7d", en: "7d output", sortable: true },
  { key: "n_30d", labelKey: "sources.n30d", en: "30d output", sortable: true },
  { key: "last_seen", labelKey: "sources.lastSeen", en: "Last seen", sortable: true },
  { key: "health", labelKey: "sources.health", en: "Health", sortable: false },
];

const HEALTH_EN: Record<Health, string> = { green: "Healthy", yellow: "Degraded", red: "Stale" };
const HEALTH_ZH: Record<Health, string> = { green: "健康", yellow: "降级", red: "停滞" };

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`size-3.5 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-90" : ""}`}
      aria-hidden="true"
    >
      <path d="m9 6 6 6-6 6" />
    </svg>
  );
}

function SortArrow({ dir }: { dir: SortDir | null }) {
  if (!dir) return null;
  return (
    <span aria-hidden="true" className="text-[10px]">
      {dir === "asc" ? "▲" : "▼"}
    </span>
  );
}

export function SourceTable({
  rows,
  tr,
  zh,
  sortKey,
  sortDir,
  onSort,
  refreshingId,
  onRefresh,
}: {
  rows: SourceRow[];
  tr: Tr;
  zh: boolean;
  sortKey: SortKey;
  sortDir: SortDir;
  onSort: (key: SortKey) => void;
  refreshingId: string;
  onRefresh: (s: SourceRow) => void;
}) {
  const [expanded, setExpanded] = useState("");

  return (
    <div className="overflow-x-auto rounded-xl border">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b bg-muted/40 text-left text-[11px] uppercase tracking-wider text-muted-foreground">
            <th className="w-8 py-2 pl-3" aria-hidden="true" />
            {COLUMNS.map((col) => (
              <th key={col.key} className="px-2 py-2 font-semibold">
                {col.sortable ? (
                  <button
                    type="button"
                    onClick={() => onSort(col.key as SortKey)}
                    className="inline-flex items-center gap-0.5 hover:text-foreground"
                  >
                    {tr(col.labelKey, col.en)}
                    <SortArrow dir={sortKey === col.key ? sortDir : null} />
                  </button>
                ) : (
                  tr(col.labelKey, col.en)
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => {
            const h = healthOf(s);
            const open = expanded === s.source_id;
            return (
              <SourceRowFragment
                key={s.source_id}
                s={s}
                health={h}
                zh={zh}
                open={open}
                onToggle={() => setExpanded(open ? "" : s.source_id)}
                refreshing={refreshingId === s.source_id}
                tr={tr}
                onRefresh={onRefresh}
              />
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SourceRowFragment({
  s,
  health,
  zh,
  open,
  onToggle,
  refreshing,
  tr,
  onRefresh,
}: {
  s: SourceRow;
  health: Health;
  zh: boolean;
  open: boolean;
  onToggle: () => void;
  refreshing: boolean;
  tr: Tr;
  onRefresh: (s: SourceRow) => void;
}) {
  const t = useT();
  const tierHintKey = TIER_HINT_KEYS[s.tier];
  return (
    <>
      <tr
        onClick={onToggle}
        className={`cursor-pointer border-b transition-colors last:border-b-0 ${
          open ? "bg-[#2563eb]/5" : "hover:bg-muted/50"
        }`}
      >
        <td className="py-2.5 pl-3">
          <Chevron open={open} />
        </td>
        <td className="px-2 py-2.5 font-mono text-xs font-medium">{s.source_id}</td>
        <td className="px-2 py-2.5">
          <span
            className="cursor-help rounded-md bg-muted px-1.5 py-0.5 text-[11px] font-medium"
            title={tierHintKey ? t(tierHintKey) : undefined}
          >
            {s.tier}
          </span>
        </td>
        <td className="px-2 py-2.5 text-xs">{kindLabel(s.kind, t)}</td>
        <td className="px-2 py-2.5 text-xs uppercase">{s.language}</td>
        <td className="px-2 py-2.5 tabular-nums">{s.n_7d}</td>
        <td className="px-2 py-2.5 tabular-nums text-muted-foreground">{s.n_30d}</td>
        <td className="px-2 py-2.5 text-xs text-muted-foreground">
          {s.last_seen ? s.last_seen.slice(0, 10) : "—"}
        </td>
        <td className="px-2 py-2.5">
          <span
            className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] ${HEALTH_BADGE[health]}`}
            title={zh ? HEALTH_ZH[health] : HEALTH_EN[health]}
          >
            <span className={`size-1.5 rounded-full ${HEALTH_DOT[health]}`} aria-hidden="true" />
            {zh ? HEALTH_ZH[health] : HEALTH_EN[health]}
          </span>
        </td>
      </tr>
      {open ? (
        <tr className="border-b bg-muted/30 last:border-b-0">
          <td colSpan={9} className="px-6 py-3">
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs">
              <span>{tr("sources.recent7", "{n} articles in last 7 days", { n: s.n_7d })}</span>
              <span>{tr("sources.recent30", "{n} articles in last 30 days", { n: s.n_30d })}</span>
              <span>
                {tr("sources.lastSeenFull", "Last item: {t}", {
                  t: s.last_seen ? s.last_seen.slice(0, 19).replace("T", " ") : "—",
                })}
              </span>
              <span className={s.enabled ? "text-[#16a34a]" : "text-[#6b7280]"}>
                {s.enabled ? tr("sources.enabledOn", "Enabled") : tr("sources.enabledOff", "Disabled")}
              </span>
              <span
                onClick={(e) => {
                  e.stopPropagation();
                }}
              >
                  <ConfirmButton
                    onConfirm={() => onRefresh(s)}
                    confirmLabel={tr("sources.refreshConfirm", "Trigger collection for {id} now?", { id: s.source_id })}
                    disabled={refreshing}
                    className="rounded-md border px-2 py-1 text-[11px] hover:bg-muted disabled:opacity-50"
                    armedClassName="border-amber-500 bg-amber-50 text-amber-800"
                  >
                    {refreshing
                      ? tr("sources.refreshing", "Triggering…")
                      : tr("sources.refresh", "Refresh now")}
                  </ConfirmButton>
                </span>
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}
