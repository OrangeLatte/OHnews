"use client";

/**
 * Change Detail（阶段 1-d 黄金路径第二跳）：ChangeDossier + Evidence Drawer。
 *
 * 硬验收映射：#3 三次操作到原文（卡→本页→引文外链）；#4 支持/反对/缺失三桶+Gap；
 * #7 五状态可区分（加载/无证据/证据不足/过期/错误）；#2 术语仅按需展开（TechnicalAnnex）。
 */

import Link from "next/link";
import { use, useEffect, useRef, useState } from "react";

import {
  api,
  type BeliefSnapshot,
  type ChangeDossier,
  type CoverageSummary,
  type DataFreshness,
  type EvidenceBucket,
  type EvidenceCitation,
  type EvidenceGap,
} from "@/lib/api";
import { SIGNAL } from "@/lib/tokens";
import { track } from "@/lib/track";

const KIND_ZH: Record<string, string> = {
  attention_spike: "关注升温",
  narrative_shift: "叙事转变",
  divergence_rise: "分歧扩大",
  expectation_gap: "预期错位",
};

const STATUS_ZH: Record<string, { zh: string; color: string }> = {
  confirmed: { zh: "已证实", color: SIGNAL.confirmed },
  contested: { zh: "存争议", color: SIGNAL.divergence },
  developing: { zh: "进展中", color: SIGNAL.attention },
  unverified: { zh: "未证实", color: SIGNAL.muted },
};

const STALENESS_ZH: Record<string, string> = {
  fresh: "数据新鲜",
  aging: "数据开始变旧",
  stale: "数据已过期",
};

const GAP_REASON_ZH: Record<string, string> = {
  no_primary_source: "暂无官方一手来源",
  single_cluster: "来源集中于单一阵营",
  time_gap: "关键时段缺少报道",
  source_silent: "相关方保持沉默",
};

const BUCKETS: { key: EvidenceBucket; zh: string }[] = [
  { key: "supporting", zh: "支持" },
  { key: "contradicting", zh: "反对" },
  { key: "context", zh: "上下文" },
];

function fmtOpt(x: number | null | undefined): string {
  return x === null || x === undefined ? "不可测" : x.toFixed(2);
}

function FreshnessLine({ f }: { f: DataFreshness }) {
  const stale = f.staleness === "stale";
  return (
    <span
      className="paper-kicker"
      style={{ color: stale ? SIGNAL.warning : SIGNAL.muted }}
      title={`覆盖 ${f.coverage_start ?? "?"} 至 ${f.as_of}`}
    >
      数据截至 {f.as_of.slice(0, 16).replace("T", " ")} UTC ·{" "}
      {STALENESS_ZH[f.staleness] ?? f.staleness}
    </span>
  );
}

function CoverageLine({ c }: { c: CoverageSummary }) {
  return (
    <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">
      {c.note}（独立来源 {c.n_independent_sources} 个，官方一手 {c.n_primary_sources} 个
      {c.time_span_days > 0 ? `，跨度 ${c.time_span_days} 天` : ""}
      {(c.languages ?? []).length ? `，${(c.languages ?? []).join(" + ")} 语料` : ""}）。
    </p>
  );
}

function CitationCard({ c }: { c: EvidenceCitation }) {
  const when = c.published_at ? c.published_at.slice(0, 10) : null;
  const REL_ZH: Record<string, string> = {
    supports: "支持",
    weakens: "削弱",
    context: "背景",
  };
  return (
    <li className="border-b border-foreground/10 py-3">
      {c.claim && (
        <p className="paper-kicker mb-1 text-[11px] text-muted-foreground">
          验证的主张：{c.claim}
        </p>
      )}
      <p className="text-[14px] leading-relaxed">{c.quote}</p>
      {(c.reason || c.relation) && (
        <p className="mt-1 text-[12px] text-muted-foreground">
          {c.relation && <span>归桶：{REL_ZH[c.relation] ?? c.relation}</span>}
          {c.reason && <span> · {c.reason}</span>}
        </p>
      )}
      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-muted-foreground">
        <span className="font-paper">{c.source_id}</span>
        <span>{c.source_tier}</span>
        {c.primary_status && (
          <span
            className="border px-1 py-px text-[10px]"
            style={{ borderColor: SIGNAL.confirmed, color: SIGNAL.confirmed }}
          >
            一手来源
          </span>
        )}
        {c.is_best_for_source && (
          <span className="border px-1 py-px text-[10px] text-muted-foreground">
            该来源最佳
          </span>
        )}
        {when && <span>{when}</span>}
        {c.url && (
          <a
            href={c.url}
            target="_blank"
            rel="noreferrer"
            onClick={() => track("source_opened", { objectId: c.item_key })}
            className="underline underline-offset-2 hover:text-foreground"
          >
            查看原文 ↗
          </a>
        )}
      </div>
    </li>
  );
}

function GapList({ gaps }: { gaps: EvidenceGap[] }) {
  if (!gaps.length) return null;
  return (
    <div
      className="mt-5 border border-dashed p-3"
      style={{ borderColor: SIGNAL.warning }}
    >
      <p className="paper-kicker" style={{ color: SIGNAL.warning }}>
        缺失的证据
      </p>
      <ul className="mt-2 space-y-1.5 text-[13px] leading-relaxed">
        {gaps.map((g) => (
          <li key={g.gap_id}>
            {g.expectation}
            {g.reason in GAP_REASON_ZH && (
              <span className="text-muted-foreground">
                （{GAP_REASON_ZH[g.reason]}）
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Drawer({ d, changeId }: { d: ChangeDossier; changeId: string }) {
  const [bucket, setBucket] = useState<EvidenceBucket>("supporting");
  const [showAll, setShowAll] = useState(false);
  const all = (d.evidence[bucket] as EvidenceCitation[] | undefined) ?? [];
  const best = all.filter((c) => c.is_best_for_source);
  const items = showAll || best.length === 0 ? all : best;
  const empty =
    (((d.evidence.supporting ?? []).length +
      (d.evidence.contradicting ?? []).length +
      (d.evidence.context ?? []).length) === 0);
  const pickBucket = (key: EvidenceBucket) => {
    setBucket(key);
    track("evidence_opened", { objectId: changeId, meta: { bucket: key } });
    if (key === "contradicting") {
      track("counter_evidence_requested", { objectId: changeId });
    }
  };
  const seenRef = useRef(false);
  useEffect(() => {
    if (empty && !seenRef.current) {
      seenRef.current = true;
      track("insufficient_evidence_seen", { objectId: changeId });
    }
  }, [empty, changeId]);
  return (
    <div>
      <div className="flex gap-4 border-b border-foreground/20 text-[13px]">
        {BUCKETS.map((b) => {
          const n = (d.evidence[b.key] as EvidenceCitation[]).length;
          const active = b.key === bucket;
          return (
            <button
              key={b.key}
              type="button"
              onClick={() => pickBucket(b.key)}
              className="pb-1.5"
              style={{
                borderBottom: active
                  ? `2px solid ${SIGNAL.divergence}`
                  : "2px solid transparent",
                color: active ? SIGNAL.divergence : undefined,
              }}
            >
              {b.zh}
              <span className="ml-1 text-muted-foreground">{n}</span>
            </button>
          );
        })}
      </div>
      {empty ? (
        <p className="py-6 text-[14px] text-muted-foreground">
          暂无可引用的证据条目（该变化可能来自少量报道，尚未形成可追溯的证据链）。
        </p>
      ) : items.length === 0 ? (
        <p className="py-6 text-[14px] text-muted-foreground">
          此桶暂无条目——不代表没有相反证据，只是现有语料中未观测到。
        </p>
      ) : (
        <ul>
          {items.map((c) => (
            <CitationCard key={c.item_key} c={c} />
          ))}
        </ul>
      )}
      {best.length > 0 && best.length < all.length && (
        <button
          type="button"
          className="mt-2 text-[12px] text-muted-foreground underline underline-offset-2"
          onClick={() => setShowAll(!showAll)}
        >
          {showAll ? "收起同源重复条目" : `展开同源其余 ${all.length - best.length} 条`}
        </button>
      )}
      <GapList gaps={d.evidence.gaps ?? []} />
    </div>
  );
}

function Coverage({ c }: { c: CoverageSummary }) {
  return (
    <section className="mt-8">
      <h2 className="font-paper text-base">证据覆盖情况</h2>
      <CoverageLine c={c} />
    </section>
  );
}

/** 阶段 2：stance 四值人话（展示与表单共用）。 */
const STANCE_OPTIONS: { key: BeliefSnapshot["stance"]; zh: string }[] = [
  { key: "maintain", zh: "维持原判" },
  { key: "adjust", zh: "调整看法" },
  { key: "reverse", zh: "反转看法" },
  { key: "uncertain", zh: "存疑待查" },
];

const STANCE_ZH_MAP = Object.fromEntries(
  STANCE_OPTIONS.map((o) => [o.key, o.zh])
) as Record<BeliefSnapshot["stance"], string>;

/** 与前一版本差异（系统计算仅供展示；判定规则与契约 diff_from 一致）。 */
function beliefDiff(prev: BeliefSnapshot, cur: BeliefSnapshot): string {
  const parts: string[] = [];
  if (prev.stance !== cur.stance) {
    parts.push(
      `立场由「${STANCE_ZH_MAP[prev.stance]}」变为「${STANCE_ZH_MAP[cur.stance]}」`
    );
  }
  const delta = cur.confidence - prev.confidence;
  if (Math.abs(delta) >= 0.05) {
    parts.push(
      `信心${delta > 0 ? "上升" : "下降"} ${Math.round(Math.abs(delta) * 100)}%`
    );
  }
  return parts.length ? parts.join("；") : "与前一版本一致";
}

function fmtTs(iso: string): string {
  return new Date(iso).toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** 我的判断（阶段 2 判断闭环）：仅用户主动确认写入；历史差异可见。 */
function MyJudgment({ changeId, dossier }: { changeId: string; dossier: ChangeDossier }) {
  const subject = (dossier.subjects ?? [])[0];
  const subjectId = subject?.id ?? "unknown";
  const subjectLabel = subject?.label ?? "";
  const [beliefs, setBeliefs] = useState<BeliefSnapshot[]>([]);
  const [stance, setStance] = useState<BeliefSnapshot["stance"] | null>(null);
  const [confidence, setConfidence] = useState(60);
  const [rationale, setRationale] = useState("");
  const [saving, setSaving] = useState(false);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);
  const investigatingRef = useRef(false);

  useEffect(() => {
    let alive = true;
    api
      .beliefsForChange(changeId)
      .then((rows) => {
        if (!alive) return;
        setBeliefs(rows);
        const last = rows[rows.length - 1];
        if (last) {
          setStance(last.stance);
          setConfidence(Math.round(last.confidence * 100));
        }
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [changeId]);

  function pickStance(v: BeliefSnapshot["stance"]) {
    setStance(v);
    if (!investigatingRef.current) {
      investigatingRef.current = true;
      track("investigation_started", { objectId: changeId });
    }
  }

  function submit() {
    if (!stance || saving) return;
    setSaving(true);
    api
      .saveBelief({
        change_id: changeId,
        subject_id: subjectId,
        subject_label: subjectLabel,
        stance,
        confidence: confidence / 100,
        rationale,
      })
      .then((snap) => {
        setSaving(false);
        setSavedMsg("已保存。你的判断只属于你——系统不会改写它。");
        setRationale("");
        track("judgment_saved", { objectId: changeId });
        track("judgment_change_type", {
          objectId: changeId,
          meta: { change_type: snap.change_type, stance: snap.stance },
        });
        return api.beliefsForChange(changeId).then(setBeliefs);
      })
      .catch(() => {
        setSaving(false);
        setSavedMsg("保存失败，请稍后重试。");
      });
  }

  const prev = beliefs.length >= 2 ? beliefs[beliefs.length - 2] : undefined;
  const last = beliefs[beliefs.length - 1];

  return (
    <section className="mt-8">
      <h2 className="font-paper text-base">我的判断</h2>
      <p className="mt-1 text-[13px] text-muted-foreground">
        看完证据后，你对这个变化的看法是什么？判断由你确认后才会记录。
      </p>

      {beliefs.length > 0 && (
        <div className="mt-3 border border-foreground/15 bg-foreground/[0.03] p-3 text-[13px]">
          <p className="paper-kicker">你的认知轨迹</p>
          <ul className="mt-2 space-y-1.5">
            {beliefs.map((b, i) => (
              <li key={b.snapshot_id}>
                <span className="text-muted-foreground">{fmtTs(b.believed_at)}</span>
                {" · "}
                {STANCE_ZH_MAP[b.stance]}
                {" · 信心 "}
                {Math.round(b.confidence * 100)}%
                {b.rationale && <span className="text-muted-foreground"> · {b.rationale}</span>}
                {i > 0 && (
                  <span style={{ color: SIGNAL.confirmed }}>
                    （{beliefDiff(beliefs[i - 1], b)}）
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-4 space-y-3">
        <div className="flex flex-wrap gap-2">
          {STANCE_OPTIONS.map((o) => (
            <button
              key={o.key}
              type="button"
              onClick={() => pickStance(o.key)}
              className={`border px-3 py-1.5 text-[13px] transition-colors ${
                stance === o.key
                  ? "border-foreground bg-foreground text-background"
                  : "border-foreground/25 hover:border-foreground/60"
              }`}
            >
              {o.zh}
            </button>
          ))}
        </div>

        <label className="block text-[13px]">
          <span className="text-muted-foreground">你的信心：{confidence}%</span>
          <input
            type="range"
            min={0}
            max={100}
            value={confidence}
            onChange={(e) => setConfidence(Number(e.target.value))}
            className="mt-1 w-full accent-foreground"
          />
        </label>

        <textarea
          value={rationale}
          onChange={(e) => setRationale(e.target.value)}
          placeholder="依据是什么？（可选，帮助未来的你回溯当时的理由）"
          rows={2}
          className="w-full border border-foreground/25 bg-transparent px-3 py-2 text-[14px] outline-none focus:border-foreground/60"
        />

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={submit}
            disabled={!stance || saving}
            className="border border-foreground bg-foreground px-4 py-1.5 text-[13px] text-background disabled:opacity-40"
          >
            {saving ? "保存中…" : last ? "更新判断" : "保存判断"}
          </button>
          {savedMsg && <span className="text-[12px]" style={{ color: SIGNAL.confirmed }}>{savedMsg}</span>}
        </div>
        {prev && last && (
          <p className="text-[12px] text-muted-foreground">
            保存后将与前一版本（{fmtTs(last.believed_at)}）对比展示差异。
          </p>
        )}
      </div>
    </section>
  );
}

export default function ChangeDetailPage({
  params,
}: PageProps<"/changes/[id]">) {
  const { id } = use(params);
  const [dossier, setDossier] = useState<ChangeDossier | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    api
      .changeDossier(id)
      .then((d) => {
        if (!alive) return;
        setDossier(d);
        setLoading(false);
        track("change_opened", {
          objectId: id,
          freshness: d.freshness.as_of,
        });
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setError(e instanceof Error ? e.message : "加载失败");
        setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [id]);

  if (loading) {
    return (
      <section className="mx-auto max-w-3xl px-4 py-16" aria-live="polite">
        <p className="text-muted-foreground">正在加载变化详情…</p>
      </section>
    );
  }
  if (error || !dossier) {
    return (
      <section className="mx-auto max-w-3xl px-4 py-16" role="alert">
        <p style={{ color: SIGNAL.warning }}>
          {error ?? "未找到该变化"}——
          <Link href="/" className="underline underline-offset-2">
            返回今日简报
          </Link>
        </p>
      </section>
    );
  }

  const status = STATUS_ZH[dossier.status] ?? STATUS_ZH.unverified;
  return (
    <article className="mx-auto max-w-3xl px-4 pb-20">
      <div className="border-b border-foreground/20 py-3">
        <Link href="/" className="paper-kicker hover:text-foreground">
          ← 返回今日简报
        </Link>
      </div>

      <header className="pt-6">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="paper-kicker">
            {KIND_ZH[dossier.kind] ?? dossier.kind}
          </span>
          <span
            className="inline-flex items-center gap-1.5 text-[13px]"
            style={{ color: status.color }}
          >
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ background: status.color }}
            />
            {status.zh}
          </span>
        </div>
        <h1 className="mt-2 font-paper text-3xl leading-tight">
          {dossier.headline}
        </h1>
        <div className="mt-2">
          <FreshnessLine f={dossier.freshness} />
        </div>
        {(dossier.subjects ?? []).length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {(dossier.subjects ?? []).map((s) => (
              <span
                key={`${s.kind}-${s.id}`}
                className="border border-foreground/20 px-2 py-0.5 text-[12px]"
              >
                {s.label}
              </span>
            ))}
          </div>
        )}
      </header>

      <section className="mt-6 space-y-3">
        <p className="text-[15px] leading-relaxed">{dossier.what}</p>
        <p className="text-[15px] leading-relaxed text-muted-foreground">
          {dossier.why_now}
        </p>
      </section>

      <Coverage c={dossier.coverage} />

      <section className="mt-8">
        <h2 className="font-paper text-base">证据</h2>
        <div className="mt-3">
          <Drawer d={dossier} changeId={id} />
        </div>
      </section>

      <MyJudgment changeId={id} dossier={dossier} />

      {dossier.technical && (
        <details className="mt-10 border-t border-foreground/20 pt-3">
          <summary className="paper-kicker cursor-pointer select-none">
            技术指标（面向进阶读者）
          </summary>
          <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1.5 text-[13px] sm:grid-cols-3">
            {[
              ["信号 ID", dossier.technical.signal_id],
              ["引擎", dossier.technical.engine],
              ["叙事分歧指数", fmtOpt(dossier.technical.ndi)],
              ["框架分布距离", fmtOpt(dossier.technical.jsd)],
              ["官方-市场温差", fmtOpt(dossier.technical.temperature_gap)],
              [
                "智能分",
                dossier.technical.intelligence_score == null
                  ? "不可测"
                  : String(dossier.technical.intelligence_score),
              ],
            ].map(([k, v]) => (
              <div key={k as string} className="flex justify-between gap-2">
                <dt className="text-muted-foreground">{k}</dt>
                <dd className="text-right">{v}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-2 text-[12px] text-muted-foreground">
            叙事分歧指数（NDI）为描述性监测指标，不构成方向性判断。
          </p>
        </details>
      )}
    </article>
  );
}
