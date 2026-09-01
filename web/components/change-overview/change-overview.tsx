"use client";

import { useEffect, useRef, useState } from "react";
import { api, type HourglassScene } from "@/lib/api";
import { track } from "@/lib/track";
import { FRAME_COLORS, SIGNAL } from "@/lib/tokens";

/**
 * Change Overview（变化总览）——报纸风浅色两窗对比信息图。
 *
 * 数据面来自 /api/hourglass（HourglassScene，后端拼图）；
 * 视觉与全站同一血统：纸白底、墨黑数字、hairline 分隔、报纸红强调。
 * 上=过去窗口，下=当前窗口；框架迁移哑铃图；变化点可点击聚焦。
 * 移动端纵向降级；prefers-reduced-motion 禁过渡。
 */

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

export function ChangeOverview() {
  const [scene, setScene] = useState<HourglassScene | null>(null);
  const [failed, setFailed] = useState(false);
  const [days, setDays] = useState(7);
  const [flipping, setFlipping] = useState(false);
  const seenRef = useRef(false);

  useEffect(() => {
    let alive = true;
    api
      .hourglass(days)
      .then((s) => {
        if (!alive) return;
        setScene(s);
        if (!seenRef.current) {
          seenRef.current = true;
          track("briefing_viewed", { freshness: s.freshness.as_of, fromPage: "/#overview" });
        }
      })
      .catch(() => {
        if (alive) setFailed(true);
      });
    return () => {
      alive = false;
    };
  }, [days]);

  const flip = () => {
    if (flipping) return;
    setFlipping(true);
    api
      .hourglassFlip(days)
      .then((s) => {
        setScene(s);
        setFlipping(false);
      })
      .catch(() => setFlipping(false));
  };

  if (failed) return null; // 失败静默让位，Briefing 卡列表仍是主内容

  if (!scene) {
    return (
      <section className="ov-section" aria-label="变化总览" aria-busy="true">
        <div className="ov-inner ov-note">正在汇聚两窗信息流…</div>
      </section>
    );
  }

  const noChanges = (scene.qualified_changes ?? []).length === 0;
  const blocked = (scene.quality_warnings ?? []).some(
    (w) =>
      w.code === "window_empty" || w.code === "low_coverage" || w.code === "no_qualified_changes",
  );
  if (noChanges && blocked) {
    // 覆盖不足区：显式弃权，不硬凑视觉
    return (
      <section className="ov-section" aria-label="变化总览">
        <div className="ov-inner ov-note">
          <p className="ov-kicker">THE CHANGE OVERVIEW · 变化总览</p>
          <p className="ov-line">
            当前窗口覆盖不足，系统选择不呈现对比——这不是没有变化，而是证据还不够说话。
          </p>
          {(scene.quality_warnings ?? []).length > 0 && (
            <ul className="ov-warnings">
              {(scene.quality_warnings ?? []).map((w) => (
                <li key={w.code}>{w.message}</li>
              ))}
            </ul>
          )}
          <p className="ov-fresh">
            数据截至 {scene.freshness.as_of}（UTC）· {scene.freshness.note}
          </p>
        </div>
      </section>
    );
  }

  return (
    <OverviewStage scene={scene} days={days} flipping={flipping} onDaysChange={setDays} onFlip={flip} />
  );
}

function OverviewStage({
  scene,
  days,
  flipping,
  onDaysChange,
  onFlip,
}: {
  scene: HourglassScene;
  days: number;
  flipping: boolean;
  onDaysChange: (d: number) => void;
  onFlip: () => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const bw = scene.baseline_window;
  const cw = scene.current_window;
  const stale = (scene.quality_warnings ?? []).some((w) => w.code === "stale_data");
  const changes = scene.qualified_changes ?? [];
  const sel = changes.find((c) => c.change_id === selected) ?? null;
  // 框架迁移哑铃：变化幅度降序取前 5
  const frames = [...(scene.narrative_streams ?? [])].sort(
    (a, b) => Math.abs(b.share_current - b.share_baseline) - Math.abs(a.share_current - a.share_baseline),
  ).slice(0, 5);
  const maxShare = Math.max(0.05, ...frames.map((n) => Math.max(n.share_baseline, n.share_current)));

  return (
    <section className="ov-section" aria-label="变化总览：过去窗口与当前窗口的对比">
      <div className="ov-inner">
        <div className="ov-head">
          <p className="ov-kicker">THE CHANGE OVERVIEW · 变化总览</p>
          <p className="ov-fresh">
            数据截至 {scene.freshness.as_of}（UTC）
            {stale ? " · 数据已过期，仅作参考" : ""}
          </p>
          <div className="ov-controls">
            <label className="ov-control">
              窗口
              <select
                value={days}
                onChange={(e) => {
                  setSelected(null);
                  onDaysChange(Number(e.target.value));
                }}
              >
                <option value={3}>近 3 天</option>
                <option value={7}>近 7 天</option>
                <option value={14}>近 14 天</option>
              </select>
            </label>
            <button
              type="button"
              className="ov-flip"
              disabled={flipping}
              onClick={() => {
                setSelected(null);
                onFlip();
              }}
              title="把当前窗口设为新基线，此后对比从翻转时刻重新积累"
            >
              {flipping ? "切换中…" : "以此为新基线"}
            </button>
          </div>
        </div>

        {/* 两窗覆盖对比：编辑式数字行 */}
        <div className="ov-windows">
          <div className="ov-window">
            <span className="ov-window-label">过去 {days} 天</span>
            <span className="ov-window-num">
              {fmtInt(bw.n_articles)}
              <em> 篇 · {bw.n_sources} 源</em>
            </span>
          </div>
          <span className="ov-arrow" aria-hidden="true">
            →
          </span>
          <div className="ov-window">
            <span className="ov-window-label">当前 {days} 天</span>
            <span className="ov-window-num ov-now">
              {fmtInt(cw.n_articles)}
              <em> 篇 · {cw.n_sources} 源</em>
            </span>
          </div>
        </div>

        {/* 框架迁移哑铃图（报纸色板） */}
        {frames.length > 0 && (
          <div className="ov-frames" role="img" aria-label="叙事框架份额迁移">
            {frames.map((n) => {
              const color = FRAME_COLORS[n.frame] ?? SIGNAL.muted;
              const moved = Math.abs(n.share_current - n.share_baseline) >= 0.1;
              return (
                <div key={n.frame} className={`ov-frame${moved ? " ov-frame-moved" : ""}`}>
                  <span className="ov-frame-label">{n.label}</span>
                  <span className="ov-frame-track">
                    <i
                      className="ov-dot ov-dot-base"
                      style={{ left: `${(n.share_baseline / maxShare) * 100}%` }}
                    />
                    <i
                      className="ov-line-seg"
                      style={{
                        left: `${(Math.min(n.share_baseline, n.share_current) / maxShare) * 100}%`,
                        width: `${(Math.abs(n.share_current - n.share_baseline) / maxShare) * 100}%`,
                        background: color,
                      }}
                    />
                    <i
                      className="ov-dot ov-dot-cur"
                      style={{ left: `${(n.share_current / maxShare) * 100}%`, background: color }}
                    />
                  </span>
                  <span className="ov-frame-num">
                    {Math.round(n.share_baseline * 100)}% → {Math.round(n.share_current * 100)}%
                  </span>
                </div>
              );
            })}
          </div>
        )}

        {/* 聚焦摘要：点击变化卡后显示（报纸剪报面板） */}
        {sel && (
          <aside className="ov-summary" aria-label="变化摘要">
            <button type="button" className="ov-summary-close" onClick={() => setSelected(null)}>
              关闭
            </button>
            <p className="ov-summary-kind">{KIND_ZH[sel.kind] ?? sel.kind} · {STRENGTH_ZH[sel.strength_word] ?? sel.strength_word}</p>
            <p className="ov-summary-headline">{sel.headline}</p>
            <p className="ov-summary-text">{sel.what}</p>
            <p className="ov-summary-text">{sel.why_now}</p>
            {(sel.subjects ?? []).length > 0 && (
              <p className="ov-summary-meta">涉及：{(sel.subjects ?? []).join("、")}</p>
            )}
            <a
              className="ov-summary-link"
              href={`/changes/${encodeURIComponent(sel.change_id)}`}
              onClick={() => track("change_opened", { objectId: sel.change_id, fromPage: "/#overview" })}
            >
              查看证据与完整档案 →
            </a>
          </aside>
        )}

        {/* 变化卡（可聚焦链接） */}
        <ul className="ov-change-list">
          {changes.map((c) => {
            const active = c.change_id === selected;
            return (
              <li key={c.change_id}>
                <button
                  type="button"
                  className={`ov-change-card${active ? " ov-change-active" : ""}`}
                  onClick={() => setSelected(active ? null : c.change_id)}
                >
                  <span className="ov-change-kind">{KIND_ZH[c.kind] ?? c.kind}</span>
                  <span className="ov-change-headline">{c.headline}</span>
                  <span className="ov-change-meta">
                    {STRENGTH_ZH[c.strength_word] ?? c.strength_word} · 建议 {URGENCY_ZH[c.urgency] ?? c.urgency}查看
                  </span>
                </button>
              </li>
            );
          })}
        </ul>

        {(scene.quality_warnings ?? []).length > 0 && (
          <ul className="ov-warnings">
            {(scene.quality_warnings ?? []).map((w) => (
              <li key={w.code}>{w.message}</li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
