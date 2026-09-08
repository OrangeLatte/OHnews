"use client";

import { useEffect, useMemo, useState } from "react";
import { useT } from "@/lib/i18n/use-t";

// 18 元素闭集色板（snake_case，与 DB element_key 一一对应；顺序即拆解展示序）。
// 底色/图例/元素卡（case-shared elementColor）共用本表：颜色一致性由同一数据源保证。
import {
  ELEMENT_BG,
  SHAPE_GLYPH,
  elementEdge,
  elementShape,
  elementShort,
  elementZh,
} from "@/lib/element-tokens";

/** 兼容导出：底色真源在 lib/element-tokens（bg/edge/short/shape 三层辨识）。 */
export const ELEMENT_COLORS: Record<string, string> = ELEMENT_BG;

/** 事实类元素：精确锚定（下划线层），重叠时优先于论证/结构类。 */
export const FACT_CLASS_KEYS: ReadonlySet<string> = new Set([
  "hard_fact",
  "quant_data",
  "data_scope",
  "timeline",
  "actor",
  "target",
  "action",
]);

/** 论证/结构类元素：整段论证锚定（左侧竖线层），重叠时让位于事实类。 */
export const STRUCTURE_CLASS_KEYS: ReadonlySet<string> = new Set([
  "argument_structure",
  "causal_link",
  "narrative_frame",
]);

export type AnnoSpan = {
  /** evidence_spans.span_id（Show in text 按 data-span-id 定位；关键词伪 span 缺省）。 */
  span_id?: string;
  char_start: number;
  char_end: number;
  element_key: string;
  /** 所属 extraction_id（用户选中元素的重叠优先判定依据）。 */
  extraction_id?: string;
};

type Props = {
  text: string;
  spans: AnnoSpan[];
  onSpanClick?: (elementKey: string) => void;
  /** 闪炼定位的 span_id（Show in text 精确锚定；null 关闭）。 */
  highlightSpanId?: string | null;
  /** 用户当前选中的 extraction_id（重叠归属规则 a：选中元素优先）。 */
  activeExtractionId?: string | null;
};

type Segment = { text: string; spans: AnnoSpan[] };

function classRank(elementKey: string): number {
  if (FACT_CLASS_KEYS.has(elementKey)) return 0;
  if (STRUCTURE_CLASS_KEYS.has(elementKey)) return 2;
  return 1;
}

/**
 * 重叠归属确定性规则（纯函数，与渲染解耦）。
 * 同一字符区间被多个 span 覆盖时，按以下优先级唯一归属（元组逐位比较，全序确定）：
 *   a) 用户选中元素（activeExtractionId）的 span 优先；
 *   b) 事实类（FACT_CLASS_KEYS，精确事实）优先于其余元素，其余元素优先于
 *      论证/结构类（STRUCTURE_CLASS_KEYS，整段论证）；
 *   c) 跨度更短者优先（锚定更精确）；
 *   d) 同长按 element_key 字母序，再按 span_id 字母序（同元素重复 span 兜底）。
 */
function compareSpans(
  a: AnnoSpan,
  b: AnnoSpan,
  activeExtractionId: string | null | undefined,
): number {
  const aActive = a.extraction_id != null && a.extraction_id === activeExtractionId ? 0 : 1;
  const bActive = b.extraction_id != null && b.extraction_id === activeExtractionId ? 0 : 1;
  if (aActive !== bActive) return aActive - bActive;
  const aCls = classRank(a.element_key);
  const bCls = classRank(b.element_key);
  if (aCls !== bCls) return aCls - bCls;
  const aLen = a.char_end - a.char_start;
  const bLen = b.char_end - b.char_start;
  if (aLen !== bLen) return aLen - bLen;
  if (a.element_key !== b.element_key) return a.element_key < b.element_key ? -1 : 1;
  const aSid = a.span_id ?? "";
  const bSid = b.span_id ?? "";
  if (aSid !== bSid) return aSid < bSid ? -1 : 1;
  return 0;
}

function buildSegments(
  text: string,
  spans: AnnoSpan[],
  activeExtractionId: string | null | undefined,
): Segment[] {
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
    // 交叠渲染：保留覆盖该段的全部候选（compareSpans 排序，短/事实优先在前），
    // 渲染层按此序嵌套高亮——同段多元素并见，不再单元素覆盖（m2587 问题 2）。
    const covers = valid.filter((s) => s.char_start <= a && b <= s.char_end);
    covers.sort((x, y) => compareSpans(x, y, activeExtractionId));
    segments.push({ text: text.slice(a, b), spans: covers });
  }
  return segments.filter((seg) => seg.text.length > 0);
}

export function AnnotatedText({
  text,
  spans,
  onSpanClick,
  highlightSpanId,
  activeExtractionId,
}: Props) {
  const t = useT();
  // 点击浮窗（m2826）：显示元素种类人话名称；点空白/再点关闭。
  const [pop, setPop] = useState<{ x: number; y: number; key: string } | null>(null);
  useEffect(() => {
    if (!pop) return;
    const close = () => setPop(null);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [pop]);
  const segments = useMemo(
    () => buildSegments(text, spans, activeExtractionId),
    [text, spans, activeExtractionId],
  );
  if (!text) return null;
  const annotated = spans.length > 0;
  const clampX = Math.min(Math.max(pop?.x ?? 0, 8), (typeof window !== "undefined" ? window.innerWidth : 1280) - 230);
  return (
    // min-w-0 + overflow-wrap:anywhere：390px 下长行/长 token 允许任意断行（继承至 mark 子元素）
    <div className="min-w-0 whitespace-pre-wrap text-sm leading-7 [overflow-wrap:anywhere]">
      {segments.map((seg, i) => {
        if (seg.spans.length === 0) {
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
        // 单层高亮（m2826）：每段取 compareSpans 首位（选中/事实/更短最精确）单一归属，
        // 不再嵌套叠加；点击弹浮窗显示元素种类。
        const sp = seg.spans[0];
        const color = ELEMENT_COLORS[sp.element_key] ?? "#fef9c3";
        const edge = elementEdge(sp.element_key);
        const shape = elementShape(sp.element_key);
        const flashed = highlightSpanId != null && sp.span_id === highlightSpanId;
        return (
          <span key={i}>
            <mark
              onClick={(e) => {
                e.stopPropagation();
                setPop({ x: e.clientX, y: e.clientY, key: sp.element_key });
                onSpanClick?.(sp.element_key);
              }}
              data-span-id={sp.span_id}
              data-element={sp.element_key}
              style={{
                backgroundColor: color,
                cursor: onSpanClick ? "pointer" : "default",
                border: `1px solid ${edge}`,
                ...(shape === "underline"
                  ? {
                      textDecoration: "underline",
                      textDecorationThickness: "2px",
                      textUnderlineOffset: "2px",
                    }
                  : {}),
                ...(shape === "leftbar" ? { borderLeft: `3px solid ${edge}`, paddingLeft: 2 } : {}),
              }}
              className={`rounded px-0.5 transition-opacity hover:opacity-80 ${
                flashed ? "ring-2 ring-sky-500 ring-offset-1" : ""
              }`}
            >
              {seg.text}
            </mark>
          </span>
        );
      })}
      {pop && (
        <div
          role="status"
          className="fixed z-50 max-w-52 rounded border border-[var(--border)] bg-background px-2.5 py-1.5 text-xs shadow-md"
          style={{ left: clampX, top: (pop.y ?? 0) + 14 }}
          onMouseDown={(e: React.MouseEvent) => e.stopPropagation()}
        >
          <span className="inline-flex items-center gap-1.5 font-medium">
            <span
              aria-hidden
              className="inline-block h-2.5 w-2.5 rounded-sm"
              style={{ backgroundColor: ELEMENT_COLORS[pop.key] ?? "#fef9c3", border: `1px solid ${elementEdge(pop.key)}` }}
            />
            {elementZh(pop.key)}
          </span>
          <span className="ml-1.5 font-mono text-[10px] text-muted-foreground">{pop.key}</span>
        </div>
      )}
      {annotated && (
        <div className="mt-3 space-y-1 border-t pt-2 text-xs text-muted-foreground">
          <p className="flex flex-wrap gap-1.5">
            {[...new Set(spans.map((s) => s.element_key))].map((k) => (
              <span key={k} className="inline-flex items-center gap-1" title={k}>
                <span
                  aria-hidden
                  className="inline-block h-2.5 w-2.5 rounded-sm"
                  style={{
                    backgroundColor: ELEMENT_COLORS[k] ?? "#fef9c3",
                    border: `1px solid ${elementEdge(k)}`,
                  }}
                />
                <span aria-hidden className="font-mono text-[10px]">
                  {SHAPE_GLYPH[elementShape(k)]}
                </span>
                <span className="font-mono text-[10px] font-semibold">{elementShort(k)}</span>
                {k}
              </span>
            ))}
          </p>
          <p>{t("case.spanLegendDirect")}</p>
          <p>{t("case.spanLegendInferred")}</p>
          <p className="inline-flex items-center gap-1">
            <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm bg-muted/60" />
            {t("case.unannotatedLegend")}
          </p>
        </div>
      )}
    </div>
  );
}
