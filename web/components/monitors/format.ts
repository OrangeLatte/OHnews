/**
 * 时间/ID 格式化工具（03 空间共享给 04/05/06）。
 * 约束：Date.now() 只允许出现在模块级函数内。
 */

export function nowMs(): number {
  return Date.now();
}

export function nowIso(): string {
  return new Date().toISOString();
}

export function stampId(prefix: string): string {
  return `${prefix}-${nowMs().toString(36)}`;
}

const rtfCache: Record<string, Intl.RelativeTimeFormat> = {};

function rtf(lang: "en" | "zh"): Intl.RelativeTimeFormat {
  const key = lang === "zh" ? "zh" : "en";
  if (!rtfCache[key]) rtfCache[key] = new Intl.RelativeTimeFormat(key, { numeric: "auto" });
  return rtfCache[key];
}

/** 相对时间："3 minutes ago" / "3 分钟前"；无法解析返回 "—"。 */
export function relTime(iso: string | null | undefined, lang: "en" | "zh"): string {
  if (!iso) return "—";
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return iso;
  const diffMs = ts - nowMs();
  const abs = Math.abs(diffMs);
  const r = rtf(lang);
  const MIN = 60_000;
  const HOUR = 3_600_000;
  const DAY = 86_400_000;
  if (abs < MIN) return r.format(Math.round(diffMs / 1000), "second");
  if (abs < HOUR) return r.format(Math.round(diffMs / MIN), "minute");
  if (abs < DAY) return r.format(Math.round(diffMs / HOUR), "hour");
  if (abs < 30 * DAY) return r.format(Math.round(diffMs / DAY), "day");
  return r.format(Math.round(diffMs / (30 * DAY)), "month");
}

/** 绝对时间（本地时区短格式）；无法解析返回原文。 */
export function absTime(iso: string | null | undefined, lang: "en" | "zh"): string {
  if (!iso) return "—";
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return iso;
  return new Date(ts).toLocaleString(lang === "zh" ? "zh-CN" : "en-US", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** 任意值压成短字符串（delta / content 预览用）。 */
export function shortValue(v: unknown, max = 96): string {
  const s = typeof v === "string" ? v : JSON.stringify(v);
  if (s === undefined) return "—";
  return s.length > max ? `${s.slice(0, max)}…` : s;
}
