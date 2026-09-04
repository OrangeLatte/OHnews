"use client";

/**
 * SOURCES 空间共享 UI：健康灯语义（绿=7d 有产出、黄=30d 有产出、红=stale）、
 * 相对时间、i18n 兜底、分步 stepper 头。
 */

import { useCallback } from "react";
import { useT } from "@/lib/i18n/use-t";
import type { SourceRow } from "@/lib/landscape-api";

export type Health = "green" | "yellow" | "red";

export function healthOf(s: SourceRow): Health {
  if (s.n_7d > 0) return "green";
  if (s.n_30d > 0) return "yellow";
  return "red";
}

export const HEALTH_DOT: Record<Health, string> = {
  green: "bg-[#16a34a]",
  yellow: "bg-[#d97706]",
  red: "bg-[#dc2626]",
};

export const HEALTH_BADGE: Record<Health, string> = {
  green: "bg-[#dcfce7] text-[#16a34a]",
  yellow: "bg-[#fef3c7] text-[#d97706]",
  red: "bg-[#fee2e2] text-[#dc2626]",
};

/** health 文案复用既有 sources.healthy/degraded/stale 键。 */
export const HEALTH_KEY: Record<Health, string> = {
  green: "sources.healthy",
  yellow: "sources.degraded",
  red: "sources.stale",
};

export const RUN_BADGE: Record<string, string> = {
  queued: "bg-zinc-100 text-[#6b7280]",
  running: "bg-[#dbeafe] text-[#2563eb]",
  succeeded: "bg-[#dcfce7] text-[#16a34a]",
  failed: "bg-[#fee2e2] text-[#dc2626]",
};

export const RUN_EN: Record<string, string> = {
  queued: "Queued",
  running: "Running",
  succeeded: "Succeeded",
  failed: "Failed",
};

export const RUN_ZH: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  succeeded: "成功",
  failed: "失败",
};

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

export function validHttpUrl(raw: string): boolean {
  try {
    const u = new URL(raw);
    return u.protocol === "http:" || u.protocol === "https:";
  } catch {
    return false;
  }
}

export function StepHeader({
  steps,
  current,
  onBack,
}: {
  steps: string[];
  current: number;
  onBack?: (step: number) => void;
}) {
  return (
    <ol className="flex flex-wrap items-center text-xs">
      {steps.map((label, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <li key={label} className="flex items-center">
            {i > 0 ? <span className="mx-1.5 h-px w-5 bg-border" aria-hidden="true" /> : null}
            <button
              type="button"
              disabled={!done || !onBack}
              onClick={() => onBack?.(i)}
              className={`flex items-center gap-1.5 rounded-full px-2 py-0.5 ${
                active
                  ? "bg-[#2563eb]/10 font-semibold text-[#2563eb]"
                  : done
                    ? "text-[#16a34a] hover:bg-muted"
                    : "text-muted-foreground"
              } ${done && onBack ? "cursor-pointer" : "cursor-default"}`}
            >
              <span
                className={`flex size-4 items-center justify-center rounded-full text-[10px] font-semibold ${
                  active
                    ? "bg-[#2563eb] text-white"
                    : done
                      ? "bg-[#16a34a] text-white"
                      : "bg-muted text-muted-foreground"
                }`}
                aria-hidden="true"
              >
                {done ? "✓" : i + 1}
              </span>
              {label}
            </button>
          </li>
        );
      })}
    </ol>
  );
}
