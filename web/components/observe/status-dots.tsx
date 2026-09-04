"use client";

/** 状态色点（色板语义：一致/通过=绿、信息=蓝、待复核=琥珀、缺口=灰）。 */
const TONE_CLS: Record<string, string> = {
  ok: "bg-green-600",
  info: "bg-blue-600",
  warn: "bg-amber-600",
  conflict: "bg-red-600",
  gap: "bg-gray-400",
};

export function StatusDot({ tone, className = "" }: { tone: keyof typeof TONE_CLS; className?: string }) {
  return <span aria-hidden className={`inline-block h-2 w-2 shrink-0 rounded-full ${TONE_CLS[tone]} ${className}`} />;
}
