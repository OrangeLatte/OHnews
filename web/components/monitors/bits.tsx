"use client";

/**
 * 04/05/06 共享视觉原子：语义三元色（通过=绿 / 冲突=红 / 待复核=琥珀 / 信息=蓝 / 缺口=灰斜纹）、
 * 状态灯、统计卡。设计规范：卡片 12px 圆角、chips 6px、正文 13px、元数据 12px。
 */

import type { ReactNode } from "react";

export type TFunc = (key: string, params?: Record<string, string | number>) => string;

export type Tone = "ok" | "bad" | "warn" | "info" | "idle";

export const TONE_DOT: Record<Tone, string> = {
  ok: "bg-[#16a34a]",
  bad: "bg-[#dc2626]",
  warn: "bg-[#d97706]",
  info: "bg-[#2563eb]",
  idle: "bg-[#6b7280]",
};

export const TONE_CHIP: Record<Tone, string> = {
  ok: "bg-[#dcfce7] text-[#15803d] dark:bg-[#16a34a]/20 dark:text-[#4ade80]",
  bad: "bg-[#fee2e2] text-[#b91c1c] dark:bg-[#dc2626]/20 dark:text-[#f87171]",
  warn: "bg-[#fef3c7] text-[#b45309] dark:bg-[#d97706]/20 dark:text-[#fbbf24]",
  info: "bg-[#dbeafe] text-[#1d4ed8] dark:bg-[#2563eb]/20 dark:text-[#93c5fd]",
  idle: "bg-muted text-muted-foreground",
};

/** 灰色斜纹（缺口/草稿语义）。 */
export const STRIPES = "bg-[repeating-linear-gradient(45deg,transparent_0_4px,rgba(107,114,128,0.18)_4px_8px)]";

export function StatusDot({ tone, pulse = false }: { tone: Tone; pulse?: boolean }) {
  return (
    <span className="relative inline-flex h-2.5 w-2.5" aria-hidden="true">
      <span className={`h-2.5 w-2.5 rounded-full ${TONE_DOT[tone]} ${pulse ? "animate-pulse" : ""}`} />
    </span>
  );
}

export function ToneChip({
  tone,
  children,
  striped = false,
  strike = false,
  className = "",
}: {
  tone: Tone;
  children: ReactNode;
  striped?: boolean;
  strike?: boolean;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium ${TONE_CHIP[tone]} ${striped ? STRIPES : ""} ${className}`}
    >
      {strike ? <span className="line-through">{children}</span> : children}
    </span>
  );
}

export function StatCard({
  label,
  value,
  tone = "idle",
  hint,
}: {
  label: string;
  value: string | number;
  tone?: Tone;
  hint?: string;
}) {
  return (
    <div className="flex min-w-0 items-center gap-3 rounded-xl border bg-card px-3 py-2">
      <StatusDot tone={tone} />
      <div className="min-w-0">
        <div className="truncate text-xs text-muted-foreground">{label}</div>
        <div className="text-sm font-semibold tabular-nums">{value}</div>
      </div>
      {hint && <div className="ml-auto hidden text-xs text-muted-foreground sm:block">{hint}</div>}
    </div>
  );
}

export function MetaChip({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className="inline-flex max-w-full items-center gap-1 truncate rounded-md border bg-secondary/60 px-1.5 py-0.5 text-xs text-secondary-foreground"
    >
      {children}
    </span>
  );
}

export function EmptyGuide({
  title,
  body,
  action,
}: {
  title: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-dashed bg-card/60 p-6 text-center">
      <p className="text-sm font-semibold">{title}</p>
      <p className="mx-auto mt-1 max-w-md text-[13px] leading-relaxed text-muted-foreground">{body}</p>
      {action && <div className="mt-3 flex justify-center">{action}</div>}
    </div>
  );
}
