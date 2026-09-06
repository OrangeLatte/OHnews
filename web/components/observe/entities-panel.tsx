"use client";

/**
 * Entities Lens：实体关系图（parent 层级边 + NDI 语义色环；无跨实体关系边数据时
 * 诚实呈现层级图，不虚构关系）→ 实体 chips → 时间轴（MiniColumns + 逐日表）→ 事件卡。
 */

import { useState } from "react";
import { MiniColumns } from "@/components/observe/charts";
import { useOt } from "@/components/observe/i18n-bridge";
import { ndiTone, relParts } from "@/components/observe/rel-time";
import { StatusDot } from "@/components/observe/status-dots";
import { Skeleton } from "@/components/ui/toast";
import type {
  EntityGraphPayload,
  EntityRow,
  EntityTimeline,
  NdiRankRow,
} from "@/lib/landscape-api";
import { useT } from "@/lib/i18n/use-t";

const TONE_TEXT_KEY: Record<string, [string, string]> = {
  ok: ["observe.timeline.tone.low", "divergence low"],
  warn: ["observe.timeline.tone.mid", "divergence moderate"],
  conflict: ["observe.timeline.tone.high", "divergence high"],
  gap: ["observe.timeline.tone.null", "no reading"],
};

const TONE_HEX: Record<string, string> = {
  ok: "#16a34a",
  warn: "#d97706",
  conflict: "#dc2626",
  gap: "#6b7280",
};

/** 实体关系图：自适应单环布局，边=parent 层级弦线，环色=NDI 语义，标签上下交替防重叠。节点点击开统一 Drawer。 */
function EntityGraph({
  entities,
  ndiMap,
  selEntity,
  kg,
  onOpenDrawer,
}: {
  entities: EntityRow[];
  ndiMap: Map<string, number>;
  selEntity: string;
  kg?: EntityGraphPayload | null;
  onOpenDrawer: (id: string, label?: string, ndi?: number | null) => void;
}) {
  const W = 640;
  const H = 360;
  const cx = W / 2;
  const cy = H / 2;
  const n = entities.length;
  const r = Math.min(160, Math.max(100, (n * 42) / (2 * Math.PI)));
  const pos = new Map(
    entities.map((e, i) => {
      const a = (i / Math.max(n, 1)) * Math.PI * 2 - Math.PI / 2;
      return [e.entity_id, { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a), i }] as const;
    }),
  );
  const idOf = (id: string): string => TONE_HEX[ndiTone(ndiMap.get(id) ?? null)];

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="entity graph">
      {/* KG 真实关系边（silver entity_edges：co_occurs / acts_on 等） */}
      {(kg?.edges ?? []).map((e, i) => {
        const a = pos.get(e.src);
        const b = pos.get(e.dst);
        if (!a || !b) return null;
        return (
          <line
            key={`kg-${i}`}
            x1={a.x}
            y1={a.y}
            x2={b.x}
            y2={b.y}
            stroke="#2563eb"
            strokeOpacity={0.5}
            strokeWidth={Math.min(3.2, 0.8 + e.weight * 0.5)}
          >
            <title>
              {`${e.src} —${e.kind}→ ${e.dst} · w ${e.weight}${e.n_evidence ? ` · evidence ${e.n_evidence}` : ""}`}
            </title>
          </line>
        );
      })}
      {/* parent → child 层级弦线 */}
      {entities.map((e) => {
        const a = pos.get(e.entity_id);
        const b = e.parent_id ? pos.get(e.parent_id) : undefined;
        if (!a || !b) return null;
        return (
          <line
            key={`edge-${e.entity_id}`}
            x1={a.x}
            y1={a.y}
            x2={b.x}
            y2={b.y}
            className="stroke-muted-foreground/40"
            strokeWidth="1.5"
            strokeDasharray="3 3"
          />
        );
      })}
      {entities.map((e) => {
        const p = pos.get(e.entity_id);
        if (!p) return null;
        const ndi = ndiMap.get(e.entity_id) ?? null;
        const selected = selEntity === e.entity_id;
        const labelAbove = p.i % 2 === 1;
        return (
          <g
            key={e.entity_id}
            className="cursor-pointer"
            onClick={() => onOpenDrawer(e.entity_id, e.aliases[0], ndi)}
          >
            <title>
              {`${e.entity_id}${e.aliases.length > 0 ? ` · ${e.aliases.slice(0, 3).join(" / ")}` : ""} · NDI ${ndi === null ? "—" : ndi.toFixed(2)}`}
            </title>
            {selected ? (
              <circle cx={p.x} cy={p.y} r="20" fill="none" className="stroke-foreground" strokeWidth="1.5" />
            ) : null}
            <circle
              cx={p.x}
              cy={p.y}
              r="13"
              className="fill-card"
              stroke={idOf(e.entity_id)}
              strokeWidth="3.5"
            />
            <text
              x={p.x}
              y={labelAbove ? p.y - 20 : p.y + 27}
              textAnchor="middle"
              fontSize="10"
              className="fill-foreground"
            >
              {e.entity_id.length > 12 ? `${e.entity_id.slice(0, 11)}…` : e.entity_id}
            </text>
          </g>
        );
      })}
      <text x={cx} y={cy + 3} textAnchor="middle" fontSize="9" className="fill-muted-foreground">
        {n}
      </text>
    </svg>
  );
}

export function EntitiesPanel({
  entities,
  entityErr,
  selEntity,
  timeline,
  days,
  ndi,
  kg,
  onOpen,
  onOpenDrawer,
}: {
  entities: EntityRow[] | null;
  entityErr: string;
  selEntity: string;
  timeline: EntityTimeline | null;
  days: number;
  ndi: NdiRankRow[];
  kg?: EntityGraphPayload | null;
  onOpen: (entityId: string) => void;
  /** 星座节点点击 → 统一 Change Drawer（P1 图表联动）；chips 仍走 onOpen 选中。 */
  onOpenDrawer: (entityId: string, label?: string, ndi?: number | null) => void;
}) {
  const t = useT();
  const ot = useOt();
  const [expanded, setExpanded] = useState<string | null>(null);

  const ndiMap = new Map(ndi.map((r) => [r.entity, r.ndi]));
  const timelineStale = timeline !== null && timeline.days !== days;
  const points = timeline ? timeline.points.slice(-30) : [];

  return (
    <div className="space-y-4">
      {entityErr ? <p className="text-[13px] text-red-600">{entityErr}</p> : null}

      {entities !== null && entities.length > 0 ? (
        <div className="space-y-1">
          <EntityGraph entities={entities} ndiMap={ndiMap} selEntity={selEntity} kg={kg} onOpenDrawer={onOpenDrawer} />
          <p className="flex flex-wrap items-center gap-3 text-[10px] text-muted-foreground">
            <span>
              {ot(
                "observe.entities.edgeNote",
                "Blue solid edges = typed co-occurrence/action relations from the knowledge graph (hover for kind/weight); gray dashed = entity hierarchy (parent_id).",
              )}
            </span>
            {(["ok", "warn", "conflict", "gap"] as const).map((tone) => (
              <span key={tone} className="flex items-center gap-1">
                <span aria-hidden className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: TONE_HEX[tone] }} />
                {ot(TONE_TEXT_KEY[tone][0], TONE_TEXT_KEY[tone][1])}
              </span>
            ))}
          </p>
        </div>
      ) : null}

      <div className="flex flex-wrap gap-1" role="group" aria-label={t("entity.pick")}>
        {entities === null ? (
          <>
            <Skeleton className="h-6 w-20 rounded-[6px]" />
            <Skeleton className="h-6 w-24 rounded-[6px]" />
            <Skeleton className="h-6 w-16 rounded-[6px]" />
          </>
        ) : (
          entities.map((e) => (
            <button
              key={e.entity_id}
              type="button"
              onClick={() => onOpen(e.entity_id)}
              aria-pressed={selEntity === e.entity_id}
              className={`rounded-[6px] border px-2 py-0.5 text-xs transition-colors hover:bg-muted/60 ${
                selEntity === e.entity_id ? "bg-foreground text-background" : ""
              }`}
            >
              {e.entity_id}
            </button>
          ))
        )}
        {entities !== null && entities.length === 0 && !entityErr ? (
          <p className="text-[13px] text-muted-foreground">{t("entity.pick")}</p>
        ) : null}
      </div>

      {!selEntity ? (
        <p className="rounded-[12px] border border-dashed p-3 text-[13px] text-muted-foreground">
          {t("entity.pick")}
        </p>
      ) : timeline === null ? (
        <div className="space-y-2" aria-busy="true">
          <Skeleton className="h-12 rounded-[12px]" />
          <Skeleton className="h-24 rounded-[12px]" />
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-xs text-muted-foreground">
            {timelineStale ? <span className="text-amber-600">⟳ {ot("observe.refreshing", "refreshing…")} · </span> : null}
            {t("entity.totalArticles", {
              n: timeline.points.reduce((s, p) => s + p.articles, 0),
            })}{" "}
            · {t("entity.totalEvents", { n: timeline.events.length })}
          </p>

          {points.length > 1 ? <MiniColumns values={points.map((p) => p.articles)} /> : null}

          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-left text-xs text-muted-foreground">
                  <th className="py-1 pr-3">{t("observe.date")}</th>
                  <th className="pr-3">{t("entity.articlesCol")}</th>
                  <th className="pr-3">{t("entity.nEventsCol")}</th>
                  <th>NDI</th>
                </tr>
              </thead>
              <tbody>
                {timeline.points.slice(-14).map((p) => (
                  <tr key={p.date} className="border-t">
                    <td className="py-1 pr-3 tabular-nums">{p.date}</td>
                    <td className="pr-3 tabular-nums">{p.articles}</td>
                    <td className="pr-3 tabular-nums">{p.n_events}</td>
                    <td className="tabular-nums">{p.ndi === null ? "—" : p.ndi.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {timeline.events.length > 0 ? (
            <ul className="space-y-0">
              {timeline.events.map((ev, i) => {
                const tone = ndiTone(ev.ndi);
                const rel = relParts(ev.as_of);
                const isLast = i === timeline.events.length - 1;
                const open = expanded === ev.event_id;
                return (
                  <li
                    key={ev.event_id}
                    className={`relative border-l border-dashed border-muted-foreground/40 pl-4 ${isLast ? "" : "pb-3"}`}
                  >
                    <span className="absolute -left-[5px] top-1.5" aria-hidden>
                      <StatusDot tone={tone} className="h-2.5 w-2.5" />
                    </span>
                    <button
                      type="button"
                      onClick={() => setExpanded(open ? null : ev.event_id)}
                      aria-expanded={open}
                      className="w-full text-left"
                      title={ot("observe.timeline.expandHint", "click to expand event detail")}
                    >
                      <span className="flex items-baseline justify-between gap-2">
                        <span className="text-sm font-semibold">{ev.title}</span>
                        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                          {rel
                            ? ot(`observe.rel.${rel.unit}`, `{v}${rel.unit}`, { v: rel.value })
                            : ev.as_of.slice(0, 10)}
                        </span>
                      </span>
                      <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                        <StatusDot tone={tone} />
                        NDI {ev.ndi === null ? "—" : ev.ndi.toFixed(2)}
                        <span aria-hidden>·</span>
                        {ot(TONE_TEXT_KEY[tone][0], TONE_TEXT_KEY[tone][1])}
                        <span aria-hidden>·</span>
                        {open ? "▲" : "▼"}
                      </span>
                    </button>
                    {open ? (
                      <div className="mt-1.5 space-y-0.5 rounded-[6px] border bg-muted/40 p-2 text-xs text-muted-foreground">
                        <p>
                          {t("observe.date")}: {ev.as_of.slice(0, 16).replace("T", " ")} UTC
                        </p>
                        {ev.dominant_frame ? (
                          <p>
                            {t("entity.frame")}: {ev.dominant_frame}
                          </p>
                        ) : (
                          <p>{t("entity.frame")}: —</p>
                        )}
                        <p>event_id: {ev.event_id}</p>
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="rounded-[12px] border border-dashed p-3 text-[13px] text-muted-foreground">
              {t("entity.noEvents")}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
