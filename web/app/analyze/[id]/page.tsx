"use client";

import { use, useEffect, useMemo, useState } from "react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  api,
  type AnatomyData,
  type EvidenceRow,
  type SpectrumDoc,
  type SpectrumSentence,
  type SpectrumSpan,
} from "@/lib/api";

// —— 词级结构配色：主体按实体确定性取色，动作按方向语义 ——
const ENTITY_PALETTE = [
  "#f0b429", "#58a6ff", "#3fb950", "#bc8cff", "#39c5cf",
  "#ff7b72", "#d2a8ff", "#7ee787", "#ffa657", "#79c0ff",
];
export function entityColor(entityId: string): string {
  let h = 0;
  for (const c of entityId) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return ENTITY_PALETTE[h % ENTITY_PALETTE.length];
}

const DIRECTION_META: Record<string, { icon: string; color: string; label: string }> = {
  easing: { icon: "↓", color: "#3fb950", label: "宽松" },
  tightening: { icon: "↑", color: "#f85149", label: "紧缩" },
  hold: { icon: "→", color: "#8b949e", label: "按兵不动" },
  escalate: { icon: "⚔", color: "#f85149", label: "升级" },
  deescalate: { icon: "🕊", color: "#3fb950", label: "缓和" },
  beat: { icon: "↗", color: "#3fb950", label: "超预期" },
  miss: { icon: "↘", color: "#f85149", label: "不及预期" },
  exit: { icon: "⇤", color: "#d29922", label: "离任" },
  enter: { icon: "⇥", color: "#3fb950", label: "履新" },
  rally: { icon: "▲", color: "#3fb950", label: "上行" },
  plunge: { icon: "▼", color: "#f85149", label: "下行" },
  expand: { icon: "⊕", color: "#3fb950", label: "扩张" },
  restrict: { icon: "⊖", color: "#d29922", label: "收缩" },
};

const TIER_LABEL: Record<string, string> = {
  L1: "官方",
  L2: "通讯社",
  L3: "财经媒体",
  L4: "社媒",
};

const STANCE_CN: Record<string, string> = {
  supportive: "挺",
  critical: "批",
  neutral: "中性",
};

// —— 词级渲染：spans 切分句子，实体/动作可点击 ——
function SentenceView({
  s,
  activeEntity,
  onEntityClick,
}: {
  s: SpectrumSentence;
  activeEntity: string | null;
  onEntityClick: (eid: string) => void;
}) {
  const spans = useMemo(
    () => [...(s.spans ?? [])].sort((a, b) => a.start - b.start),
    [s.spans],
  );
  const parts: React.ReactNode[] = [];
  let cur = 0;
  let key = 0;
  for (const sp of spans) {
    if (sp.start > cur)
      parts.push(<span key={key++}>{s.text.slice(cur, sp.start)}</span>);
    const seg = s.text.slice(sp.start, sp.end);
    if (sp.entity_id) {
      const c = entityColor(sp.entity_id);
      const active = activeEntity === sp.entity_id;
      parts.push(
        <button
          key={key++}
          type="button"
          onClick={() => onEntityClick(sp.entity_id!)}
          className={`mx-0.5 rounded px-1 font-medium transition-all hover:brightness-125 ${active ? "ring-1" : ""}`}
          style={{
            color: c,
            backgroundColor: `${c}22`,
            textDecoration: `underline ${c}66`,
            ...(active ? { outline: `1px solid ${c}` } : {}),
          }}
          title={`主体：${sp.entity_id}`}
        >
          {seg}
        </button>,
      );
    } else if (sp.direction) {
      const m = DIRECTION_META[sp.direction] ?? DIRECTION_META.hold;
      parts.push(
        <span
          key={key++}
          className="mx-0.5 rounded px-1 font-medium"
          style={{ color: m.color, backgroundColor: `${m.color}1f` }}
          title={`动作：${m.label}（${sp.domain}）`}
        >
          {m.icon} {seg}
        </span>,
      );
    }
    cur = sp.end;
  }
  if (cur < s.text.length) parts.push(<span key={key++}>{s.text.slice(cur)}</span>);
  return <>{parts}</>;
}

// —— 分歧构成：簇对条 + 簇分布堆叠条（纯 CSS，紧凑交互）——
const FRAME_KEYS = ["loss", "gain", "responsibility", "conflict", "human_interest", "other"] as const;
const FRAME_COLORS: Record<string, string> = {
  loss: "#e5534b",
  gain: "#3fb950",
  responsibility: "#d29922",
  conflict: "#bc8cff",
  human_interest: "#58a6ff",
  other: "#8b949e",
};

function FrameBar({ dist }: { dist: Record<string, number> }) {
  const total = FRAME_KEYS.reduce((s, k) => s + (dist[k] ?? 0), 0) || 1;
  return (
    <div className="flex h-3 w-full overflow-hidden rounded-sm">
      {FRAME_KEYS.map((k) => {
        const v = dist[k] ?? 0;
        if (v / total < 0.01) return null;
        return (
          <div
            key={k}
            style={{ width: `${(v / total) * 100}%`, backgroundColor: FRAME_COLORS[k] }}
            title={`${k}: ${(v / total).toFixed(2)}`}
          />
        );
      })}
    </div>
  );
}

function ClusterMatrix({ data }: { data: AnatomyData }) {
  return (
    <div className="flex flex-col gap-1.5">
      {data.cluster_pairs.map((p) => (
        <div key={`${p.a}-${p.b}`} className="flex items-center gap-2 text-xs">
          <span className="w-28 shrink-0 font-mono">
            {TIER_LABEL[p.a] ?? p.a} ↔ {TIER_LABEL[p.b] ?? p.b}
          </span>
          <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full transition-all"
              style={{
                width: `${p.jsd * 100}%`,
                backgroundColor: p.official_vs_market ? "#f0b429" : "#58a6ff",
              }}
            />
          </div>
          <span className="w-10 text-right font-mono">{p.jsd.toFixed(3)}</span>
          <span className="w-16 text-right text-muted-foreground">
            n={p.n_a}/{p.n_b}
          </span>
        </div>
      ))}
    </div>
  );
}

function EntityOpposition({
  data,
  activeEntity,
  onEntityClick,
}: {
  data: AnatomyData;
  activeEntity: string | null;
  onEntityClick: (eid: string) => void;
}) {
  if (data.entity_opposition.length === 0)
    return <p className="text-xs text-muted-foreground">无双侧对立主体（官方簇样本不足）</p>;
  return (
    <div className="flex flex-col gap-1.5">
      {data.entity_opposition.map((o) => {
        const c = entityColor(o.entity_id);
        const offS = o.official.supportive ?? 0;
        const offC = o.official.critical ?? 0;
        const mktS = o.market.supportive ?? 0;
        const mktC = o.market.critical ?? 0;
        return (
          <button
            key={o.entity_id}
            type="button"
            onClick={() => onEntityClick(o.entity_id)}
            className={`flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors hover:bg-muted/40 ${activeEntity === o.entity_id ? "bg-muted/60 ring-1 ring-ring" : ""}`}
          >
            <span className="w-24 shrink-0 font-medium" style={{ color: c }}>
              {o.entity_id}
            </span>
            <span className="text-muted-foreground">
              官方{" "}
              <b className="text-emerald-400">挺{(offS * 100).toFixed(0)}%</b>{" "}
              <b className="text-red-400">批{(offC * 100).toFixed(0)}%</b>
            </span>
            <span className="text-muted-foreground">vs</span>
            <span className="text-muted-foreground">
              市场{" "}
              <b className="text-emerald-400">挺{(mktS * 100).toFixed(0)}%</b>{" "}
              <b className="text-red-400">批{(mktC * 100).toFixed(0)}%</b>
            </span>
            <span className="ml-auto w-12 text-right font-mono">Δ{o.gap.toFixed(2)}</span>
            <span className="text-muted-foreground">
              n={o.n_official}/{o.n_market}
            </span>
          </button>
        );
      })}
    </div>
  );
}

// —— 光谱：文章折叠 + 实体过滤 ——
function SpectrumPanel({
  docs,
  activeEntity,
  onEntityClick,
}: {
  docs: SpectrumDoc[];
  activeEntity: string | null;
  onEntityClick: (eid: string) => void;
}) {
  const [openKey, setOpenKey] = useState<string | null>(null);
  const filtered = useMemo(
    () =>
      activeEntity
        ? docs.filter((d) => d.sentences.some((s) => (s.spans ?? []).some((p) => p.entity_id === activeEntity)))
        : docs,
    [docs, activeEntity],
  );
  if (docs.length === 0) return <p className="text-sm text-muted-foreground">暂无关联文章</p>;
  return (
    <div className="flex flex-col gap-2">
      {activeEntity && (
        <p className="text-xs text-muted-foreground">
          已过滤主体 <b style={{ color: entityColor(activeEntity) }}>{activeEntity}</b>（
          {filtered.length}/{docs.length} 篇）·
          <button type="button" className="underline" onClick={() => onEntityClick(activeEntity)}>
            取消
          </button>
        </p>
      )}
      {filtered.map((d) => {
        const open = openKey === d.item_key;
        const hit = d.sentences.filter((s) => (s.spans ?? []).length > 0).length;
        return (
          <div key={d.item_key} className="rounded-md border border-border/60">
            <button
              type="button"
              onClick={() => setOpenKey(open ? null : d.item_key)}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted/40"
            >
              <span className="text-xs">{open ? "▼" : "▶"}</span>
              <span className="font-mono text-xs text-muted-foreground">{d.source_id}</span>
              <span className="flex-1 truncate">{d.title || "(无标题)"}</span>
              <Badge variant="outline" className="text-[10px]">
                {hit} 句含结构
              </Badge>
            </button>
            {open && (
              <p className="border-t border-border/60 px-3 py-2 text-sm leading-8">
                {d.sentences.map((s) => (
                  <span key={s.i} className="mr-1">
                    <SentenceView s={s} activeEntity={activeEntity} onEntityClick={onEntityClick} />
                    {s.stance && (
                      <sup
                        className="ml-0.5 text-[10px]"
                        style={{ color: s.stance === "critical" ? "#e5534b" : "#3fb950" }}
                      >
                        {STANCE_CN[s.stance]}
                      </sup>
                    )}
                  </span>
                ))}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default function WorkbenchPage({ params }: PageProps<"/analyze/[id]">) {
  const { id } = use(params);
  const [anatomy, setAnatomy] = useState<AnatomyData | null>(null);
  const [spectrum, setSpectrum] = useState<SpectrumDoc[]>([]);
  const [evidence, setEvidence] = useState<EvidenceRow[]>([]);
  const [activeEntity, setActiveEntity] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setActiveEntity(null);
    Promise.all([api.eventAnatomy(id), api.eventSpectrum(id), api.eventEvidence(id)])
      .then(([a, sp, ev]) => {
        setAnatomy(a);
        setSpectrum(sp);
        setEvidence(ev);
      })
      .catch((err) => setError(String(err)));
  }, [id]);

  if (error)
    return (
      <div className="flex flex-col gap-3">
        <p className="text-destructive">加载失败：{error}</p>
        <Link href="/analyze" className="text-sm text-muted-foreground underline">
          ← 返回工作台
        </Link>
      </div>
    );

  return (
    <div className="flex flex-col gap-5">
      {/* 递进①：结论 */}
      <div className="flex items-center gap-3">
        <Link href="/analyze" className="text-sm text-muted-foreground hover:text-foreground">
          ← 工作台
        </Link>
        <h1 className="font-mono text-lg">{id}</h1>
        {anatomy?.ndi && (
          <Badge variant="outline" className="font-mono">
            NDI {anatomy.ndi.ndi?.toFixed(3) ?? "abstain"} · n={anatomy.ndi.n_sources}
          </Badge>
        )}
      </div>

      {/* 递进②：分歧构成（簇对 + 簇分布） */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">分歧构成 · 信源簇对（谁和谁分歧）</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {anatomy ? <ClusterMatrix data={anatomy} /> : <p className="text-sm text-muted-foreground">加载中…</p>}
          {anatomy && Object.keys(anatomy.clusters).length > 0 && (
            <div className="grid grid-cols-1 gap-2 pt-2 md:grid-cols-2">
              {Object.entries(anatomy.clusters).map(([tier, dist]) => (
                <div key={tier} className="flex items-center gap-2 text-xs">
                  <span className="w-16 shrink-0 text-muted-foreground">{TIER_LABEL[tier] ?? tier}</span>
                  <FrameBar dist={dist} />
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* 递进③：主体对立（分歧落在哪个主体）→ 点击联动过滤光谱 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            主体对立 · 官方 vs 市场（点击主体，光谱联动过滤）
          </CardTitle>
        </CardHeader>
        <CardContent>
          {anatomy ? (
            <EntityOpposition data={anatomy} activeEntity={activeEntity} onEntityClick={(e) => setActiveEntity((cur) => (cur === e ? null : e))} />
          ) : (
            <p className="text-sm text-muted-foreground">加载中…</p>
          )}
        </CardContent>
      </Card>

      {/* 递进④：光谱（词级主体-动作-方向结构） */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">叙事光谱 · 词级结构（主体色块 + 动作域/方向）</CardTitle>
          <p className="text-xs text-muted-foreground">
            主体（实体）按色区分可点击过滤；动作按域/方向着色（↓宽松 ↑紧缩 ⚔升级 ↗超预期 ↘不及 ▲上行 ▼下行）；句尾「批/挺」= 立场线索。
          </p>
        </CardHeader>
        <CardContent>
          <SpectrumPanel
            docs={spectrum}
            activeEntity={activeEntity}
            onEntityClick={(e) => setActiveEntity((cur) => (cur === e ? null : e))}
          />
        </CardContent>
      </Card>

      {/* 递进⑤：证据链一键引用 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">证据链（一键引用回溯原文）</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-1.5">
            {evidence.slice(0, 12).map((r) => (
              <div key={r.item_key + r.frame} className="flex items-center gap-2 text-xs">
                <span className="w-24 shrink-0 font-mono text-muted-foreground">{r.source_id}</span>
                <span className="flex-1 truncate text-muted-foreground" title={r.quote}>
                  {r.quote}
                </span>
                <Badge variant="outline" className="text-[10px]">
                  {r.frame}
                </Badge>
                <EvidenceCopy r={r} />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function EvidenceCopy({ r }: { r: EvidenceRow }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      size="sm"
      variant="outline"
      className="h-6 px-2 text-[10px]"
      onClick={async () => {
        await navigator.clipboard.writeText(
          [
            `【摘录】${r.quote}`,
            `来源：${r.source_id}`,
            `PIT 时间：${r.ts}`,
            `框架：${r.frame} / 立场：${r.stance} / 置信度：${r.confidence.toFixed(2)}`,
            `item_key：${r.item_key}`,
          ].join("\n"),
        );
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
    >
      {copied ? "已复制" : "引用"}
    </Button>
  );
}
