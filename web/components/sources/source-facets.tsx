"use client";

/**
 * 信源目录 facet 树：tier / kind / language / 健康度 / 启用状态，全量计数徽标。
 * 计数口径 = 除本组外的其余筛选 + 搜索（组内互斥，组间叠加）。
 */

import type { ReactNode } from "react";
import type { SourceRow } from "@/lib/landscape-api";
import { useT } from "@/lib/i18n/use-t";
import { kindLabel } from "@/lib/sources-meta";
import { healthOf, type Health, type Tr } from "./sources-ui";

export type Facets = {
  tier: string;
  kind: string;
  language: string;
  health: "" | Health;
  enabled: "" | "on" | "off";
};

export const EMPTY_FACETS: Facets = { tier: "", kind: "", language: "", health: "", enabled: "" };

export type FacetGroup = "tier" | "kind" | "language" | "health" | "enabled";

export function sourceMatches(
  s: SourceRow,
  f: Facets,
  q: string,
  skip?: FacetGroup,
): boolean {
  if (skip !== "tier" && f.tier && s.tier !== f.tier) return false;
  if (skip !== "kind" && f.kind && s.kind !== f.kind) return false;
  if (skip !== "language" && f.language && s.language !== f.language) return false;
  if (skip !== "health" && f.health && healthOf(s) !== f.health) return false;
  if (skip !== "enabled" && f.enabled && (f.enabled === "on") !== s.enabled) return false;
  if (q) {
    const needle = q.trim().toLowerCase();
    if (needle && !`${s.source_id} ${s.kind} ${s.tier} ${s.language}`.toLowerCase().includes(needle)) {
      return false;
    }
  }
  return true;
}

function uniqueValues(rows: SourceRow[], pick: (s: SourceRow) => string): string[] {
  const seen = new Set<string>();
  for (const r of rows) seen.add(pick(r));
  return [...seen].filter(Boolean).sort((a, b) => a.localeCompare(b));
}

function ValueRow({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`flex w-full items-center justify-between gap-2 rounded-md px-2 py-1 text-left text-xs transition-colors ${
        active ? "bg-[#2563eb]/10 font-medium text-[#2563eb]" : "hover:bg-muted"
      }`}
    >
      <span className="truncate">{label}</span>
      <span
        className={`shrink-0 rounded-full px-1.5 text-[10px] ${
          active ? "bg-[#2563eb] text-white" : "bg-muted text-muted-foreground"
        }`}
      >
        {count}
      </span>
    </button>
  );
}

function Group({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div>
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </p>
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

export function SourceFacets({
  rows,
  facets,
  q,
  tr,
  zh,
  onFacet,
  onClear,
}: {
  rows: SourceRow[];
  facets: Facets;
  q: string;
  tr: Tr;
  zh: boolean;
  onFacet: (group: FacetGroup, value: string) => void;
  onClear: () => void;
}) {
  const t = useT();
  const tiers = [
    ...["L1", "L2", "L3", "L4"].filter((t) => rows.some((r) => r.tier === t)),
    ...uniqueValues(rows, (r) => r.tier).filter((t) => !["L1", "L2", "L3", "L4"].includes(t)),
  ];
  const kinds = uniqueValues(rows, (r) => r.kind);
  const languages = uniqueValues(rows, (r) => r.language);
  const healths: Health[] = ["green", "yellow", "red"];
  const healthEn: Record<Health, string> = { green: "Healthy", yellow: "Degraded", red: "Stale" };
  const healthZh: Record<Health, string> = { green: "健康", yellow: "降级", red: "停滞" };

  const countFor = (group: FacetGroup, value: string): number =>
    rows.filter((r) => sourceMatches(r, facets, q, group) && matchesValue(r, group, value)).length;

  const anyActive =
    facets.tier !== "" || facets.kind !== "" || facets.language !== "" || facets.health !== "" || facets.enabled !== "";

  return (
    <aside className="space-y-4" aria-label={tr("sources.facets", "Filters")}>
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold">{tr("sources.facets", "Filters")}</p>
        {anyActive ? (
          <button type="button" onClick={onClear} className="text-xs text-[#2563eb] hover:underline">
            {tr("sources.clearFacets", "Clear")}
          </button>
        ) : null}
      </div>

      <Group title={tr("sources.facetTier", "Tier")}>
        <ValueRow
          label={tr("sources.healthAll", "Any")}
          count={rows.filter((r) => sourceMatches(r, facets, q, "tier")).length}
          active={facets.tier === ""}
          onClick={() => onFacet("tier", "")}
        />
        {tiers.map((tier) => (
          <ValueRow
            key={tier}
            label={tier}
            count={countFor("tier", tier)}
            active={facets.tier === tier}
            onClick={() => onFacet("tier", tier)}
          />
        ))}
      </Group>

      <Group title={tr("sources.facetKind", "Kind")}>
        <ValueRow
          label={tr("sources.healthAll", "Any")}
          count={rows.filter((r) => sourceMatches(r, facets, q, "kind")).length}
          active={facets.kind === ""}
          onClick={() => onFacet("kind", "")}
        />
        {kinds.map((kind) => (
          <ValueRow
            key={kind}
            label={kindLabel(kind, t)}
            count={countFor("kind", kind)}
            active={facets.kind === kind}
            onClick={() => onFacet("kind", kind)}
          />
        ))}
      </Group>

      <Group title={tr("sources.facetLanguage", "Language")}>
        <ValueRow
          label={tr("sources.healthAll", "Any")}
          count={rows.filter((r) => sourceMatches(r, facets, q, "language")).length}
          active={facets.language === ""}
          onClick={() => onFacet("language", "")}
        />
        {languages.map((lang) => (
          <ValueRow
            key={lang}
            label={lang.toUpperCase()}
            count={countFor("language", lang)}
            active={facets.language === lang}
            onClick={() => onFacet("language", lang)}
          />
        ))}
      </Group>

      <Group title={tr("sources.facetHealth", "Health")}>
        <ValueRow
          label={tr("sources.healthAll", "Any")}
          count={rows.filter((r) => sourceMatches(r, facets, q, "health")).length}
          active={facets.health === ""}
          onClick={() => onFacet("health", "")}
        />
        {healths.map((h) => (
          <ValueRow
            key={h}
            label={zh ? healthZh[h] : healthEn[h]}
            count={countFor("health", h)}
            active={facets.health === h}
            onClick={() => onFacet("health", h)}
          />
        ))}
      </Group>

      <Group title={tr("sources.facetEnabled", "Enabled")}>
        <ValueRow
          label={tr("sources.healthAll", "Any")}
          count={rows.filter((r) => sourceMatches(r, facets, q, "enabled")).length}
          active={facets.enabled === ""}
          onClick={() => onFacet("enabled", "")}
        />
        <ValueRow
          label={tr("sources.enabledOn", "Enabled")}
          count={countFor("enabled", "on")}
          active={facets.enabled === "on"}
          onClick={() => onFacet("enabled", "on")}
        />
        <ValueRow
          label={tr("sources.enabledOff", "Disabled")}
          count={countFor("enabled", "off")}
          active={facets.enabled === "off"}
          onClick={() => onFacet("enabled", "off")}
        />
      </Group>
    </aside>
  );
}

function matchesValue(s: SourceRow, group: FacetGroup, value: string): boolean {
  switch (group) {
    case "tier":
      return s.tier === value;
    case "kind":
      return s.kind === value;
    case "language":
      return s.language === value;
    case "health":
      return healthOf(s) === value;
    case "enabled":
      return (value === "on") === s.enabled;
    default:
      return true;
  }
}
