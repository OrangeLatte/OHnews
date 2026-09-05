"use client";

/**
 * 内部码 → i18n 标签（P1-8 审计：UI 不得裸渲染 run kind / run status /
 * revision status / artifact klass 等内部枚举）。未知值诚实回退原码，
 * 不编造译文；键缺失时 t() 的 fallback 行为同此约定。
 */

type TFn = (key: string, params?: Record<string, string | number>) => string;

/** 运行 kind（dissect/translate/compare/report/challenge/commit_check）。 */
export function runKindLabel(t: TFn, kind: string): string {
  const label = t(`run.kind.${kind}`);
  return label === `run.kind.${kind}` ? kind : label;
}

/** 运行状态（queued/running/succeeded/abstained/failed/cancelled）。 */
export function runStatusLabel(t: TFn, status: string): string {
  const label = t(`run.status.${status}`);
  return label === `run.status.${status}` ? status : label;
}

/** Artifact 版本状态（draft/committed/superseded）。 */
export function revStatusLabel(t: TFn, status: string): string {
  const label = t(`rev.status.${status}`);
  return label === `rev.status.${status}` ? status : label;
}

/** Artifact 类别（research_report/press_edition/...）。 */
export function klassLabel(t: TFn, klass: string): string {
  const label = t(`archive.klass.${klass}`);
  return label === `archive.klass.${klass}` ? klass : label;
}
