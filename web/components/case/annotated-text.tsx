"use client";

import { useMemo } from "react";
import { useT } from "@/lib/i18n/use-t";

// 18 元素闭集色板（snake_case，与 DB element_key 一致）；柔和底色保证黑字可读。
export const ELEMENT_COLORS: Record<string, string> = {
  actor: "#fde68a",
  target: "#fecaca",
  hard_fact: "#bbf7d0",
  action: "#bfdbfe",
  causal_link: "#ddd6fe",
  timeline: "#fbcfe8",
  condition: "#c7d2fe",
  magnitude: "#fed7aa",
  location: "#a7f3d0",
  source_attribution: "#e9d5ff",
  perspective: "#fca5a5",
  uncertainty: "#a5f3fc",
  intent: "#f9a8d4",
  framing: "#d9f99d",
  tone: "#fde4cf",
  implicit_bias: "#f5d0fe",
  missing_context: "#e2e8f0",
  rhetorical_device: "#fef08a",
};

export type AnnoSpan = {
  char_start: number;
  char_end: number;
  element_key: string;
};

type Props = {
  text: string;
  spans: AnnoSpan[];
  onSpanClick?: (elementKey: string) => void;
};

type Segment = { text: string; span: AnnoSpan | null };

function buildSegments(text: string, spans: AnnoSpan[]): Segment[] {
  const valid = spans.filter(
    (s) => Number.isFinite(s.char_start) && s.char_end > s.char_start && s.char_start >= 0 && s.char_end <= text.length,
  );
  const bounds = new Set<number>([0, text.length]);
  for (const s of valid) {
    bounds.add(s.char_start);
    bounds.add(s.char_end);
  }
  const points = [...bounds].sort((a, b) => a - b);
  const segments: Segment[] = [];
  for (let i = 0; i < points.length - 1; i += 1) {
    const a = points[i];
    const b = points[i + 1];
    // 重叠归属：取覆盖该段的 span 中跨度最长者（而非数组序先到先得），
    // 保证多个元素重叠时各段归给最具代表性的元素。
    let cover: AnnoSpan | null = null;
    let best = -1;
    for (const s of valid) {
      if (s.char_start <= a && b <= s.char_end) {
        const len = s.char_end - s.char_start;
        if (len > best) {
          best = len;
          cover = s;
        }
      }
    }
    segments.push({ text: text.slice(a, b), span: cover });
  }
  return segments.filter((seg) => seg.text.length > 0);
}

export function AnnotatedText({ text, spans, onSpanClick }: Props) {
  const t = useT();
  const segments = useMemo(() => buildSegments(text, spans), [text, spans]);
  if (!text) return null;
  const annotated = spans.length > 0;
  return (
    // min-w-0 + overflow-wrap:anywhere：390px 下长行/长 token 允许任意断行（继承至 mark 子元素）
    <div className="min-w-0 whitespace-pre-wrap text-sm leading-7 [overflow-wrap:anywhere]">
      {segments.map((seg, i) => {
        if (!seg.span) {
          if (!annotated) return <span key={i}>{seg.text}</span>;
          return (
            <span
              key={i}
              title={t("case.unannotatedLegend")}
              className="rounded bg-muted/40 px-0.5"
            >
              {seg.text}
            </span>
          );
        }
        const color = ELEMENT_COLORS[seg.span.element_key] ?? "#fef9c3";
        return (
          <mark
            key={i}
            title={seg.span.element_key}
            onClick={() => onSpanClick?.(seg.span!.element_key)}
            style={{ backgroundColor: color, cursor: onSpanClick ? "pointer" : "default" }}
            className="rounded px-0.5 transition-opacity hover:opacity-80"
            data-element={seg.span.element_key}
          >
            {seg.text}
          </mark>
        );
      })}
      {annotated && (
        <p className="mt-3 flex flex-wrap gap-1.5 border-t pt-2 text-xs text-muted-foreground">
          {[...new Set(spans.map((s) => s.element_key))].map((k) => (
            <span key={k} className="inline-flex items-center gap-1">
              <span
                aria-hidden
                className="inline-block h-2.5 w-2.5 rounded-sm"
                style={{ backgroundColor: ELEMENT_COLORS[k] ?? "#fef9c3" }}
              />
              {k}
            </span>
          ))}
          <span className="inline-flex items-center gap-1">
            <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm bg-muted/60" />
            {t("case.unannotatedLegend")}
          </span>
        </p>
      )}
    </div>
  );
}
