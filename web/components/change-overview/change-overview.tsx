"use client";

import type { EChartsOption } from "echarts";
import { ChartBase } from "@/components/visualizations/chart-base";
import { type ChangeLandscape } from "@/lib/api";
import { FRAME_COLORS, SIGNAL } from "@/lib/tokens";

/**
 * Change Overview（变化总览）——报纸风浅色两窗对比信息图。
 *
 * 数据面来自 /api/change-landscape（ChangeLandscape，后端拼图）；
 * 视觉与全站同一血统：纸白底、墨黑数字、hairline 分隔、报纸红强调。
 * 上=过去窗口，下=当前窗口；框架迁移哑铃图；变化点可点击聚焦。
 * 移动端纵向降级；prefers-reduced-motion 禁过渡。
 */

function fmtInt(n: number): string {
  return n.toLocaleString("en-US");
}

/**
 * 变化总览（受控组件，T4）：数据由父层 /api/home 单源提供，本组件只渲染。
 * 保留四态：loading（父层未就绪）/ 正常 / 覆盖不足显式弃权 / blocked 警告列表。
 */
export function ChangeOverview({
  scene,
  days,
  onDaysChange,
}: {
  scene: ChangeLandscape | null;
  days: number;
  onDaysChange: (d: number) => void;
}) {
  if (!scene) {
    return (
      <section className="ov-section" aria-label="变化总览" aria-busy="true">
        <div className="ov-inner ov-loading" aria-live="polite">
          <p className="ov-kicker">THE CHANGE OVERVIEW · 变化总览</p>
          <p className="ov-loading-title">正在比较两个时间窗口…</p>
          <div className="ov-loading-bars" aria-hidden="true">
            <i />
            <i />
            <i />
            <i />
          </div>
        </div>
      </section>
    );
  }

  return <OverviewStage scene={scene} days={days} onDaysChange={onDaysChange} />;
}

const WARNING_LABELS: Record<string, string> = {
  stale_data: "数据已过期",
  window_empty: "时间窗口没有数据",
  low_coverage: "来源覆盖不足",
  no_qualified_changes: "没有变化通过证据门",
  source_composition_shift: "两窗来源构成不同",
};

function OverviewStage({
  scene,
  days,
  onDaysChange,
}: {
  scene: ChangeLandscape;
  days: number;
  onDaysChange: (d: number) => void;
}) {
  const bw = scene.baseline_window;
  const cw = scene.current_window;
  const stale = (scene.quality_warnings ?? []).some((w) => w.code === "stale_data");
  const blocked = (scene.quality_warnings ?? []).some((warning) =>
    ["window_empty", "low_coverage", "no_qualified_changes"].includes(warning.code),
  );
  // 框架迁移哑铃：按显示口径（adjusted 优先）的变化幅度降序取前 5
  type NarrStream = NonNullable<ChangeLandscape["narrative_streams"]>[number];
  const dispDelta = (n: NarrStream) =>
    n.adjusted_share_baseline != null && n.adjusted_share_current != null
      ? Math.abs(n.adjusted_share_current - n.adjusted_share_baseline)
      : Math.abs(n.share_current - n.share_baseline);
  const frames = [...(scene.narrative_streams ?? [])]
    .sort((a, b) => dispDelta(b) - dispDelta(a))
    .slice(0, 5);
  const comparableFrames = frames.filter((frame) => frame.n_cohort_sources >= 3);
  const maxShare = Math.max(
    0.05,
    ...comparableFrames.map((frame) =>
      Math.max(
        frame.adjusted_share_baseline ?? frame.share_baseline,
        frame.adjusted_share_current ?? frame.share_current,
      ),
    ),
  );
  const minCohort = frames.length > 0 ? Math.min(...frames.map((frame) => frame.n_cohort_sources)) : 0;

  const frameOption: EChartsOption = {
    tooltip: {
      trigger: "axis",
      formatter: (raw: unknown) => {
        const params = raw as Array<{ name: string; seriesName: string; value: number }>;
        const label = params[0]?.name;
        const n = frames.find((f) => f.label === label);
        if (!n) return label ?? "";
        // U3 弃权门：共同来源 <3 不展示百分比；<5 标注方向性迹象
        if (n.n_cohort_sources < 3) {
          return `${label}<br/>共同来源不足（${n.n_cohort_sources} 个）——仅方向性迹象，不呈现百分比`;
        }
        const tag = n.n_cohort_sources < 5 ? "方向性迹象（共同来源 <5）" : null;
        const bias =
          n.adjusted_share_baseline != null
            ? `共同来源 ${n.n_cohort_sources} 个（校正口径）`
            : "原始口径，来源构成差异未校正";
        const b = n.adjusted_share_baseline ?? n.share_baseline;
        const c = n.adjusted_share_current ?? n.share_current;
        const nums = `${Math.round(b * 100)}% → ${Math.round(c * 100)}%（Δ ${Math.round((c - b) * 100)}）`;
        return `${label}<br/>${bias}${tag ? `<br/>${tag}` : ""}<br/>${nums}`;
      },
    },
    legend: { top: 0, textStyle: { color: SIGNAL.muted, fontSize: 11 } },
    grid: { left: 70, right: 40, top: 26, bottom: 20, containLabel: true },
    xAxis: {
      type: "value",
      max: maxShare,
      axisLabel: { formatter: (v: number) => `${Math.round(v * 100)}%`, color: SIGNAL.muted },
    },
    yAxis: {
      type: "category",
      data: comparableFrames.map((frame) => frame.label),
      axisLabel: { color: SIGNAL.muted },
    },
    series: [
      {
        name: "过去窗口",
        type: "bar",
        itemStyle: { color: "#c9c2b4" },
        barGap: "20%",
        data: comparableFrames.map((frame) =>
          frame.adjusted_share_baseline ?? frame.share_baseline
        ),
      },
      {
        name: "当前窗口",
        type: "bar",
        itemStyle: {
          color: (params) =>
            FRAME_COLORS[comparableFrames[params.dataIndex]?.frame] ?? SIGNAL.muted,
        },
        data: comparableFrames.map((frame) =>
          frame.adjusted_share_current ?? frame.share_current
        ),
      },
    ],
  };

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
                  onDaysChange(Number(e.target.value));
                }}
              >
                <option value={3}>近 3 天</option>
                <option value={7}>近 7 天</option>
                <option value={14}>近 14 天</option>
              </select>
            </label>
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

        {blocked && (
          <div className="ov-gate" role="status">
            <strong>证据门未通过</strong>
            <span>这不等于没有变化，而是当前样本不足以形成可靠结论。可切换时间窗口继续查看。</span>
          </div>
        )}

        {comparableFrames.length > 0 ? (
          <div
            className="ov-chart"
            role="img"
            aria-label="叙事框架份额迁移（共同来源校正口径优先）"
          >
            <div className="ov-chart-note">
              <span>变化透镜：同一批来源在两个窗口中的叙事结构</span>
              <strong>
                {minCohort < 5
                  ? `${minCohort} 个共同来源 · 方向性迹象`
                  : `${minCohort} 个共同来源 · 可比较`}
              </strong>
            </div>
            <ChartBase
              option={frameOption}
              state="ready"
              height={comparableFrames.length * 64 + 80}
            />
          </div>
        ) : frames.length > 0 ? (
          <div className="ov-chart ov-chart-abstain">
            共同来源少于 3 个，系统不展示百分比变化。当前只能确认“可能发生变化”，不能判断变化幅度。
          </div>
        ) : null}

        {(scene.quality_warnings ?? []).length > 0 && (
          <ul className="ov-warnings">
              {(scene.quality_warnings ?? []).map((w) => (
              <li key={w.code} title={w.message}>
                {WARNING_LABELS[w.code] ?? w.message}
              </li>
              ))}
          </ul>
        )}
      </div>
    </section>
  );
}
