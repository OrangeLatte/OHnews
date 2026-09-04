"use client";

/**
 * 数据说明卡：research.sqlite 三层架构一句话（bronze → silver → gold）+ 各表 counts。
 */

import { type TFunc } from "@/components/monitors/bits";
import { SectionCard } from "./section-card";
import type { UsageOut } from "./usage-card";

const KEY_COUNTS = [
  "cases",
  "artifacts",
  "artifact_revisions",
  "user_commits",
  "monitors",
  "monitor_updates",
] as const;

export function DataCard({
  usage,
  t,
}: {
  usage: UsageOut | null;
  t: TFunc;
}) {
  const counts = usage?.counts;
  const shown = counts
    ? KEY_COUNTS.filter((k) => k in counts).map((k) => [k, counts[k]] as const)
    : [];

  return (
    <SectionCard title={t("settings.data")} tone={counts ? "ok" : "warn"} helpKey="state.empty">
      <p className="max-w-3xl text-[13px] leading-relaxed">{t("settings.dataLine")}</p>
      {counts ? (
        <div className="mt-3 grid grid-cols-2 gap-1.5 sm:grid-cols-3 lg:grid-cols-6">
          {shown.map(([k, v]) => (
            <div key={k} className="rounded-md border bg-muted/30 px-2 py-1.5 text-xs" title={k}>
              <p className="truncate text-muted-foreground">{k}</p>
              <p className="font-mono text-sm font-semibold tabular-nums">{v}</p>
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-2 text-xs text-muted-foreground">{t("settings.loadFailed")}</p>
      )}
    </SectionCard>
  );
}
