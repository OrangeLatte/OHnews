"use client";

/**
 * CASES 空间共享 UI：状态语义色 / origin 图标 / 相对时间 / i18n 兜底。
 * 语义色板（全站规范）：进行=绿 #16a34a(#dcfce7)、需关注=红 #dc2626(#fee2e2)、
 * 候选/待复核=琥珀 #d97706(#fef3c7)、关闭/停用=灰 #6b7280、信息=蓝 #2563eb。
 */

import { useCallback } from "react";
import { useT } from "@/lib/i18n/use-t";

/** 新文案先英文字面量兜底：字典缺键时显示 en（待 dictionaries.ts 补录）。 */
export function useTr(): (key: string, en: string, params?: Record<string, string | number>) => string {
  const t = useT();
  return useCallback(
    (key: string, en: string, params?: Record<string, string | number>): string => {
      const out = t(key, params);
      return out === key ? en : out;
    },
    [t],
  );
}

export type Tr = ReturnType<typeof useTr>;

/* Date.now() 只允许出现在模块级函数（eslint 纪律）。 */
export function timeNow(): number {
  return Date.now();
}

export function nowIso(): string {
  return new Date().toISOString();
}

export function newCaseId(): string {
  return `case-${Date.now()}`;
}

export function relTime(iso: string | null | undefined, zh: boolean): string {
  if (!iso) return "—";
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return iso.slice(0, 10);
  const sec = Math.max(0, Math.round((timeNow() - ms) / 1000));
  if (sec < 60) return zh ? "刚刚" : "just now";
  const min = Math.floor(sec / 60);
  if (min < 60) return zh ? `${min} 分钟前` : `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return zh ? `${hr} 小时前` : `${hr}h ago`;
  const d = Math.floor(hr / 24);
  if (d < 30) return zh ? `${d} 天前` : `${d}d ago`;
  return iso.slice(0, 10);
}

export const STATUS_BADGE: Record<string, string> = {
  candidate: "bg-[#fef3c7] text-[#d97706]",
  active: "bg-[#dcfce7] text-[#16a34a]",
  needs_attention: "bg-[#fee2e2] text-[#dc2626]",
  suspended: "bg-zinc-100 text-[#6b7280]",
  closed: "bg-zinc-100 text-[#6b7280]",
  rejected: "bg-zinc-100 text-[#6b7280]",
};

export const STATUS_DOT: Record<string, string> = {
  candidate: "bg-[#d97706]",
  active: "bg-[#16a34a]",
  needs_attention: "bg-[#dc2626]",
  suspended: "bg-[#6b7280]",
  closed: "bg-[#6b7280]",
  rejected: "bg-[#6b7280]",
};

const STATUS_EN: Record<string, string> = {
  candidate: "Candidate",
  active: "Active",
  needs_attention: "Needs attention",
  suspended: "Suspended",
  closed: "Closed",
  rejected: "Rejected",
};

const STATUS_ZH: Record<string, string> = {
  candidate: "候选",
  active: "进行中",
  needs_attention: "需关注",
  suspended: "已暂停",
  closed: "已关闭",
  rejected: "已否决",
};

export function statusLabel(status: string, zh: boolean): string {
  return zh ? (STATUS_ZH[status] ?? status) : (STATUS_EN[status] ?? status);
}

const ORIGIN_EN: Record<string, string> = {
  user: "Created by you",
  watch: "From monitor watch",
  agent: "Agent drafted",
};

const ORIGIN_ZH: Record<string, string> = {
  user: "手动创建",
  watch: "来自监视器",
  agent: "Agent 起草",
};

export function originLabel(origin: string, zh: boolean): string {
  return zh ? (ORIGIN_ZH[origin] ?? origin) : (ORIGIN_EN[origin] ?? origin);
}

export function OriginIcon({ origin, className }: { origin: string; className?: string }) {
  const cls = className ?? "size-3.5 shrink-0";
  const common = {
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    className: cls,
    "aria-hidden": true,
  };
  if (origin === "watch") {
    return (
      <svg {...common}>
        <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
        <circle cx="12" cy="12" r="3" />
      </svg>
    );
  }
  if (origin === "agent") {
    return (
      <svg {...common}>
        <rect x="4" y="8" width="16" height="12" rx="2" />
        <path d="M12 4v4" />
        <circle cx="9" cy="14" r="1" />
        <circle cx="15" cy="14" r="1" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c0-4 4-6 8-6s8 2 8 6" />
    </svg>
  );
}
