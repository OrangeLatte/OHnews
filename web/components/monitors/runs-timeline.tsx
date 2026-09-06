"use client";

/**
 * Monitor 运行时间线：垂直虚线 + 状态色节点 + 相对时间戳；error 如实展示。
 */

import { absTime, relTime } from "./format";
import { StatusDot, TONE_DOT, type TFunc, type Tone } from "./bits";

export type MonitorRunRow = {
  run_id: string;
  status: string;
  started_at: string;
  finished_at: string;
  error: string;
  /** P0-B：run 终态输出（命中数/增量数）；null = 无输出，诚实不显示。 */
  output?: { hits?: number; new_articles?: number; stage?: string; window_applied?: boolean } | null;
};

export function runTone(status: string): Tone {
  switch (status) {
    case "succeeded":
      return "ok";
    case "failed":
      return "bad";
    case "running":
    case "started":
      return "info";
    case "abstained":
      return "warn";
    default:
      return "idle";
  }
}

export function RunsTimeline({
  runs,
  unavailable,
  t,
  lang,
}: {
  runs: MonitorRunRow[];
  unavailable: boolean;
  t: TFunc;
  lang: "en" | "zh";
}) {
  if (unavailable) {
    return <p className="text-xs text-amber-700">{t("monitors.runsUnavailable")}</p>;
  }
  if (runs.length === 0) {
    return <p className="text-xs text-muted-foreground">{t("monitors.runEmpty")}</p>;
  }
  return (
    <ul className="relative space-y-3 border-l border-dashed border-border pl-4">
      {runs.slice(-30).map((r) => {
        const tone = runTone(r.status);
        const label = t(`monitors.runStatus.${r.status}`);
        return (
          <li key={r.run_id} className="relative">
            <span
              className={`absolute -left-[21px] top-1.5 inline-flex h-2.5 w-2.5 rounded-full ${TONE_DOT[tone]}`}
              aria-hidden="true"
            />
            <div className="flex flex-wrap items-center gap-2">
              <StatusDot tone={tone} />
              <span className="font-mono text-xs">{r.run_id}</span>
              <span className="text-xs text-muted-foreground">
                · {label} · {relTime(r.started_at, lang)}
              </span>
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {t("monitors.started")}: {absTime(r.started_at, lang)}
              {r.finished_at ? ` · ${t("monitors.finished")}: ${absTime(r.finished_at, lang)}` : ""}
            </p>
            {r.output && (
              <p className="mt-0.5 text-xs text-muted-foreground">
                {t("monitors.runHits", { n: r.output.hits ?? 0, m: r.output.new_articles ?? 0 })}
                {r.output.window_applied === false && (
                  <span
                    className="ml-1 rounded border border-amber-500/50 px-1 py-px text-[10px] text-amber-700 dark:text-amber-300"
                    title={t("monitors.staleScopeTitle")}
                  >
                    {t("monitors.staleScope")}
                  </span>
                )}
              </p>
            )}
            {r.error && <p className="mt-0.5 text-xs text-[#b91c1c] dark:text-[#f87171]">{r.error}</p>}
          </li>
        );
      })}
    </ul>
  );
}
