"use client";

import { useEffect, useRef, useState } from "react";
import { api, type HourglassScene } from "@/lib/api";
import { track } from "@/lib/track";

/**
 * Orange Hourglass Hero（阶段 1.5-e）
 *
 * 上层=过去窗口（baseline），下层=当前窗口，腰部=过质量门的变化点。
 * 流带宽度=覆盖量，颜色=叙事框架，纹理簇=来源簇。
 * 深墨色舞台+暖橙流光，与全站报纸风形成反差排版。
 * 桌面 SVG 渲染（DOM 无障碍覆盖层）；移动端简化脉冲对比+纵向变化卡。
 * prefers-reduced-motion 时禁用过渡动画。
 */

const PAPER = "#f5efe2";
const ORANGE = "#ff9a4d";
const ORANGE_DIM = "#e2762d";
const MUTED_INK = "#8a919e";

// 深墨舞台上的框架色（亮化变体，保证对比度）
const FRAME_GLOW: Record<string, string> = {
  loss: "#e8705f",
  gain: "#7fc98a",
  responsibility: "#e8c46a",
  conflict: "#c98ae8",
  human_interest: "#6ab8e8",
  other: "#9aa3ad",
};

const KIND_ZH: Record<string, string> = {
  attention_spike: "注意力聚集",
  narrative_shift: "叙事转变",
  divergence_rise: "叙事分歧升高",
  expectation_gap: "官方与市场预期错位",
};

const STRENGTH_ZH: Record<string, string> = {
  strong: "显著变化",
  notable: "值得关注",
  minor: "轻微迹象",
  insufficient: "证据不足",
};

const URGENCY_ZH: Record<string, string> = {
  high: "今天",
  medium: "48 小时内",
  low: "本周内",
};

function fmtInt(n: number): string {
  return n.toLocaleString("en-US");
}

export function HourglassHero() {
  const [scene, setScene] = useState<HourglassScene | null>(null);
  const [failed, setFailed] = useState(false);
  const seenRef = useRef(false);

  useEffect(() => {
    let alive = true;
    api
      .hourglass()
      .then((s) => {
        if (!alive) return;
        setScene(s);
        if (!seenRef.current) {
          seenRef.current = true;
          track("briefing_viewed", { freshness: s.freshness.as_of, fromPage: "/#hourglass" });
        }
      })
      .catch(() => {
        if (alive) setFailed(true);
      });
    return () => {
      alive = false;
    };
  }, []);

  if (failed) return null; // Hero 失败静默让位，Briefing 卡列表仍是主内容

  if (!scene) {
    return (
      <section className="hg-stage" aria-label="Orange Hourglass" aria-busy="true">
        <div className="hg-stage-inner hg-loading">正在汇聚两窗信息流…</div>
      </section>
    );
  }

  const noChanges = (scene.qualified_changes ?? []).length === 0;
  const blocked = (scene.quality_warnings ?? []).some(
    (w) => w.code === "window_empty" || w.code === "low_coverage" || w.code === "no_qualified_changes",
  );
  if (noChanges && blocked) {
    // 覆盖不足区：显式弃权，不硬凑视觉
    return (
      <section className="hg-stage" aria-label="Orange Hourglass">
        <div className="hg-stage-inner hg-empty">
          <p className="hg-kicker" style={{ color: ORANGE }}>
            ORANGE HOURGLASS
          </p>
          <p className="hg-line">
            当前窗口覆盖不足，系统选择不呈现沙漏——这不是没有变化，而是证据还不够说话。
          </p>
          {(scene.quality_warnings ?? []).length > 0 && (
            <ul className="hg-warnings">
              {(scene.quality_warnings ?? []).map((w) => (
                <li key={w.code}>{w.message}</li>
              ))}
            </ul>
          )}
          <p className="hg-fresh">数据截至 {scene.freshness.as_of}（UTC）· {scene.freshness.note}</p>
        </div>
      </section>
    );
  }

  return <HourglassStage scene={scene} />;
}

function HourglassStage({ scene }: { scene: HourglassScene }) {
  const bw = scene.baseline_window;
  const cw = scene.current_window;
  const maxSource = Math.max(
    1,
    ...(scene.source_streams ?? []).map((s) => Math.max(s.n_baseline, s.n_current)),
  );
  const stale = (scene.quality_warnings ?? []).some((w) => w.code === "stale_data");

  return (
    <section className="hg-stage" aria-label="Orange Hourglass：过去窗口与当前窗口的叙事对比">
      <div className="hg-stage-inner">
        <div className="hg-head">
          <p className="hg-kicker" style={{ color: ORANGE }}>
            ORANGE HOURGLASS · 叙事沙漏
          </p>
          <p className="hg-fresh">
            数据截至 {scene.freshness.as_of}（UTC）
            {stale ? " · 数据已过期，仅作参考" : ""}
          </p>
        </div>

        {/* 桌面：SVG 沙漏；移动端由 CSS 隐藏 */}
        <div className="hg-desktop" aria-hidden="true">
          <svg viewBox="0 0 1000 430" className="hg-svg" role="img">
            <defs>
              <linearGradient id="hg-glow" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor={ORANGE_DIM} stopOpacity="0.25" />
                <stop offset="50%" stopColor={ORANGE} stopOpacity="0.55" />
                <stop offset="100%" stopColor={ORANGE_DIM} stopOpacity="0.25" />
              </linearGradient>
            </defs>

            {/* 上层：baseline 窗 */}
            <text x="70" y="30" fill={PAPER} fontSize="15" className="hg-serif">
              过去窗口
            </text>
            <text x="150" y="30" fill={MUTED_INK} fontSize="12">
              {fmtInt(bw.n_articles)} 篇 · {bw.n_sources} 源
            </text>
            {(scene.source_streams ?? []).map((s, i) => {
              const y = 44 + i * 16;
              const w = Math.max(2, (s.n_baseline / maxSource) * 780);
              return (
                <g key={`b-${s.source_id}`}>
                  <rect x={70} y={y} width={w} height={9} rx={2} fill="url(#hg-glow)" opacity={0.85} />
                  {i < 6 && (
                    <text x={76 + w} y={y + 8} fill={MUTED_INK} fontSize="9">
                      {s.label}
                    </text>
                  )}
                </g>
              );
            })}

            {/* 腰部：变化点 */}
            <line x1="70" y1="212" x2="930" y2="212" stroke={ORANGE_DIM} strokeWidth="1" strokeDasharray="4 5" opacity={0.6} />
            {(scene.qualified_changes ?? []).map((c, i) => (
              <g key={c.change_id} className="hg-change">
                <circle cx={120 + i * 240} cy={212} r={6} fill={ORANGE} />
                <text x={134 + i * 240} y={208} fill={ORANGE} fontSize="13" className="hg-serif">
                  {c.headline}
                </text>
                <text x={134 + i * 240} y={226} fill={MUTED_INK} fontSize="10">
                  {KIND_ZH[c.kind] ?? c.kind} · {STRENGTH_ZH[c.strength_word] ?? c.strength_word} · 建议 {URGENCY_ZH[c.urgency] ?? c.urgency}查看
                </text>
              </g>
            ))}
            {(scene.qualified_changes ?? []).length === 0 && (
              <text x="70" y="216" fill={MUTED_INK} fontSize="12">
                本窗口没有通过质量门的变化
              </text>
            )}

            {/* 下层：current 窗 */}
            <text x="70" y="256" fill={PAPER} fontSize="15" className="hg-serif">
              当前窗口
            </text>
            <text x="150" y="256" fill={MUTED_INK} fontSize="12">
              {fmtInt(cw.n_articles)} 篇 · {cw.n_sources} 源
            </text>
            {(scene.source_streams ?? []).map((s, i) => {
              const y = 270 + i * 16;
              const w = Math.max(2, (s.n_current / maxSource) * 780);
              return (
                <rect key={`c-${s.source_id}`} x={70} y={y} width={w} height={9} rx={2} fill="url(#hg-glow)" />
              );
            })}

            {/* 叙事框架迁移注脚 */}
            {(scene.narrative_streams ?? [])
              .filter((n) => Math.abs(n.share_current - n.share_baseline) >= 0.1)
              .slice(0, 3)
              .map((n, i) => (
                <g key={n.frame}>
                  <circle cx={72} cy={404 + i * 0} r={0} />
                  <text x={70 + i * 300} y={418} fill={FRAME_GLOW[n.frame] ?? PAPER} fontSize="11">
                    {n.label} {Math.round(n.share_baseline * 100)}% → {Math.round(n.share_current * 100)}%
                  </text>
                </g>
              ))}
          </svg>
        </div>

        {/* 移动端：简化脉冲对比 + 纵向变化卡 */}
        <div className="hg-mobile">
          <div className="hg-pulse-row">
            <span className="hg-pulse-label">过去</span>
            <span className="hg-pulse-bar">
              <i style={{ width: `${(bw.n_articles / Math.max(bw.n_articles, cw.n_articles)) * 100}%` }} />
            </span>
            <span className="hg-pulse-num">{fmtInt(bw.n_articles)}</span>
          </div>
          <div className="hg-pulse-row">
            <span className="hg-pulse-label">当前</span>
            <span className="hg-pulse-bar">
              <i style={{ width: `${(cw.n_articles / Math.max(bw.n_articles, cw.n_articles)) * 100}%` }} />
            </span>
            <span className="hg-pulse-num">{fmtInt(cw.n_articles)}</span>
          </div>
        </div>

        {/* 无障碍/移动变化卡（DOM 覆盖层，两种视口都渲染为可聚焦链接） */}
        <ul className="hg-change-list">
          {(scene.qualified_changes ?? []).map((c) => (
            <li key={c.change_id}>
              <a
                href={`/changes/${encodeURIComponent(c.change_id)}`}
                onClick={() => track("change_opened", { objectId: c.change_id, fromPage: "/#hourglass" })}
              >
                <span className="hg-change-kind" style={{ color: ORANGE }}>
                  {KIND_ZH[c.kind] ?? c.kind}
                </span>
                <span className="hg-change-headline hg-serif">{c.headline}</span>
                <span className="hg-change-meta">
                  {STRENGTH_ZH[c.strength_word] ?? c.strength_word} · 建议 {URGENCY_ZH[c.urgency] ?? c.urgency}查看
                </span>
              </a>
            </li>
          ))}
        </ul>

        {(scene.quality_warnings ?? []).length > 0 && (
          <ul className="hg-warnings">
            {(scene.quality_warnings ?? []).map((w) => (
              <li key={w.code}>{w.message}</li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
