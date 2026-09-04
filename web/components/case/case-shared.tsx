"use client";

/**
 * Case 工作台共享原子：类型、模块级纯函数（Date.now 只允许出现在模块级函数内）、
 * 元素色点 / 状态 pill / 灰斜纹空格等小 UI。供 read/map/compare/report/history 各模式复用。
 */

import Link from "next/link";
import { ELEMENT_COLORS } from "@/components/case/annotated-text";
import { HelpIcon } from "@/components/help/help-icon";
import { ELEMENT_HELP_KEYS } from "@/lib/help/registry";

export type DocRow = {
  document_revision_id: string;
  document_id: string;
  source_id: string;
  language: string;
  published_at: string;
  fetched_at: string;
  added_at: string;
};

export type SourceOption = { source_id: string; language: string; tier: string };

export const MODES = ["read", "map", "compare", "report", "history"] as const;
export type Mode = (typeof MODES)[number];

/** 关键词高亮伪元素键（命中处注入 mark，落在 18 元素色板之外）。 */
export const KEYWORD_KEY = "keyword";

/** 18 元素规范顺序（取色板键序，未知元素排最后）。 */
export const ELEMENT_ORDER: readonly string[] = Object.keys(ELEMENT_COLORS);

export function elementOrderIndex(key: string): number {
  const i = ELEMENT_ORDER.indexOf(key);
  return i < 0 ? ELEMENT_ORDER.length : i;
}

export function elementColor(key: string): string {
  return ELEMENT_COLORS[key] ?? "#e2e8f0";
}

/** 元素 snake_case → help registry camelCase 键（未注册返回 null）。 */
export function elementHelpKey(elementKey: string): string | null {
  const camel = elementKey.replace(/_([a-z])/g, (_m, c: string) => c.toUpperCase());
  const key = `element.${camel}`;
  return ELEMENT_HELP_KEYS_SET.has(key) ? key : null;
}

const ELEMENT_HELP_KEYS_SET: ReadonlySet<string> = new Set(ELEMENT_HELP_KEYS);

/** 时间戳 id（模块级：react-hooks/purity 禁止组件作用域内 Date.now）。 */
export const stampId = (prefix: string) => `${prefix}-${Date.now()}`;

/** 相对时间原料：秒差（渲染端配合 t("case.rel*") 出文案）。 */
export function secondsSince(iso?: string | null): number {
  if (!iso) return Number.POSITIVE_INFINITY;
  const ts = Date.parse(iso);
  if (!Number.isFinite(ts)) return Number.POSITIVE_INFINITY;
  return Math.max(0, (Date.now() - ts) / 1000);
}

/** 运行状态 → 节点色 / pill 类。succeeded 绿、failed 红、running 黄、其余灰。 */
export const RUN_META: Record<string, { dot: string; pill: string }> = {
  succeeded: {
    dot: "bg-emerald-500",
    pill: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  },
  failed: { dot: "bg-red-500", pill: "bg-red-500/10 text-red-700 dark:text-red-300" },
  running: { dot: "bg-amber-400", pill: "bg-amber-500/10 text-amber-700 dark:text-amber-300" },
  queued: { dot: "bg-zinc-400", pill: "bg-zinc-500/10 text-zinc-600 dark:text-zinc-300" },
  abstained: { dot: "bg-zinc-500", pill: "bg-zinc-500/10 text-zinc-600 dark:text-zinc-300" },
  cancelled: { dot: "bg-zinc-400", pill: "bg-zinc-500/10 text-zinc-600 dark:text-zinc-300" },
};

export function runMeta(status: string) {
  return RUN_META[status] ?? { dot: "bg-zinc-400", pill: "bg-zinc-500/10 text-zinc-600 dark:text-zinc-300" };
}

/** human_status → pill 类。confirmed 绿 / rejected 红 / unreviewed 琥珀。 */
export function reviewPillClass(status: string): string {
  if (status === "confirmed") return "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300";
  if (status === "rejected") return "bg-red-500/10 text-red-700 dark:text-red-300";
  return "bg-amber-500/10 text-amber-700 dark:text-amber-300";
}

/** 空单元格灰斜纹（缺口语义，同 COMPARE 灰 #6b7280 系）。 */
export const MISSING_CELL_BG =
  "bg-[repeating-linear-gradient(45deg,rgba(107,114,128,0.18)_0,rgba(107,114,128,0.18)_4px,transparent_4px,transparent_8px)]";

export function ElementDot({ elementKey }: { elementKey: string }) {
  return (
    <span
      aria-hidden
      className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm"
      style={{ backgroundColor: elementColor(elementKey) }}
    />
  );
}

export function ElementChip({ elementKey, count }: { elementKey: string; count?: number }) {
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium text-zinc-800 dark:text-zinc-900"
      style={{ backgroundColor: elementColor(elementKey) }}
    >
      {elementKey}
      {count !== undefined && count > 1 ? <span className="opacity-70">×{count}</span> : null}
    </span>
  );
}

export function StatusPill({ status, label }: { status: string; label: string }) {
  return (
    <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${runMeta(status).pill}`} data-status={status}>
      {label}
    </span>
  );
}

/** 空态引导卡：诚实空态 + 行动指向（如实说"没有数据"，不硬凑占位）。 */
export function EmptyHint({
  text,
  action,
  href,
}: {
  text: string;
  action?: string;
  href?: string;
}) {
  return (
    <div className="flex flex-col items-start gap-2 rounded-xl border border-dashed p-4 text-sm text-muted-foreground">
      <p>{text}</p>
      {action && href ? (
        <Link
          href={href}
          className="rounded-md border px-2 py-1 text-xs font-medium text-foreground hover:bg-muted"
        >
          {action}
        </Link>
      ) : null}
    </div>
  );
}

/** 模式标题行：14px semibold + 模式 HelpIcon。 */
export function ModeHeader({ title, helpKey, children }: { title: string; helpKey: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <h2 className="text-sm font-semibold">{title}</h2>
      <HelpIcon helpKey={helpKey} />
      {children ? <div className="ml-auto flex flex-wrap items-center gap-2">{children}</div> : null}
    </div>
  );
}
