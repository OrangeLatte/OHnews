"use client";

/**
 * ARCHIVE 分类元数据：klass 图标码 + i18n 标签。
 */

import { MetaChip, type TFunc } from "@/components/monitors/bits";

export const KLASSES = [
  "element_map",
  "research_report",
  "cross_source_analysis",
  "monitor_review",
  "press_edition",
] as const;

export type Klass = (typeof KLASSES)[number];

export function klassCode(klass: string): string {
  const codes: Record<string, string> = {
    element_map: "EM",
    research_report: "RR",
    cross_source_analysis: "XC",
    monitor_review: "MR",
    press_edition: "PE",
  };
  return codes[klass] ?? klass.slice(0, 2).toUpperCase();
}

export function KlassChip({ klass }: { klass: string }) {
  return (
    <MetaChip title={klass}>
      <span className="font-mono text-[10px] font-semibold">{klassCode(klass)}</span>
      <span className="hidden sm:inline">{klass}</span>
    </MetaChip>
  );
}

export function klassLabel(klass: string, t: TFunc): string {
  return t(`archive.klass.${klass}`);
}
