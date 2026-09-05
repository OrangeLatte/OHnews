"use client";

/**
 * Monitor 卡片（列表项）：target_type 语义徽标 + question + trigger chips +
 * window/schedule 元数据 + last_snapshot 相对时间 + 待复核琥珀徽标（●）。
 */

import type { MonitorRow } from "@/lib/object-api";
import { relTime } from "./format";
import { MetaChip, StatusDot, type TFunc, type Tone } from "./bits";

function targetTypeCode(targetType: string): string {
  // oh-contracts MonitorTarget 闭集（monitoring.py）
  const known: Record<string, string> = {
    case: "CASE",
    entity: "ENT",
    topic: "TOP",
    question: "QST",
    article: "ART",
    claim: "CLM",
    stance: "STA",
    sentiment: "SEN",
    action: "ACT",
    element: "ELE",
  };
  if (known[targetType]) return known[targetType];
  return targetType.slice(0, 3).toUpperCase() || "REF";
}

/** Monitor 配置状态三色：active=绿 / paused=灰 / error=红（预留）；其余视为口径外。 */
export function statusTone(status: string): Tone {
  if (status === "active") return "ok";
  if (status === "paused") return "idle";
  if (status === "error") return "bad";
  return "info";
}

export function MonitorCard({
  m,
  pending,
  selected,
  onSelect,
  t,
  lang,
}: {
  m: MonitorRow;
  pending: number;
  selected: boolean;
  onSelect: (id: string) => void;
  t: TFunc;
  lang: "en" | "zh";
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(m.monitor_id)}
      aria-current={selected ? "true" : undefined}
      className={`block w-full rounded-xl border bg-card p-3 text-left transition-colors ${
        selected ? "border-ring ring-ring/40 ring-2" : "hover:bg-accent/50"
      }`}
    >
      <div className="flex items-start gap-2">
        <span
          className="mt-0.5 inline-flex h-6 shrink-0 items-center rounded-md bg-secondary px-1.5 font-mono text-[10px] font-semibold text-secondary-foreground"
          title={m.target_type}
        >
          {targetTypeCode(m.target_type)}
        </span>
        <div className="min-w-0 flex-1">
          <p className="line-clamp-2 text-[13px] font-semibold leading-snug">{m.question}</p>
          <p className="mt-0.5 truncate font-mono text-xs text-muted-foreground" title={m.target_ref}>
            {m.target_ref}
          </p>
        </div>
        {pending > 0 && (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-[#fef3c7] px-1.5 py-0.5 text-xs font-medium text-[#b45309] dark:bg-[#d97706]/20 dark:text-[#fbbf24]">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-[#d97706]" aria-hidden="true" />
            {t("monitors.pendingBadge", { n: pending })}
          </span>
        )}
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        {m.trigger_conditions.map((tc) => (
          <MetaChip key={tc}>{tc}</MetaChip>
        ))}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1">
          <StatusDot tone={statusTone(m.status)} /> {m.status}
        </span>
        <span title={t("monitors.window")}>
          ⏱ {m.window} · {m.schedule}
        </span>
        <span>
          {t("monitors.lastSnapshot")}: {relTime(m.last_confirmed_snapshot_at, lang)}
        </span>
      </div>
    </button>
  );
}
