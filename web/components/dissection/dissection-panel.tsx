"use client";

/**
 * B1 前端：文章拆解面板（02 证据区内嵌）。
 * 选一篇文章 → POST /api/agent/dissect（缓存幂等）→ 18 元素结构化渲染。
 * engine=offline 时诚实标注「词典降级」；缺失元素显示「未提取」不空壳。
 */

import { useState } from "react";
import { api } from "@/lib/api";
import { track } from "@/lib/track";
import { SIGNAL } from "@/lib/tokens";

type Dissection = Awaited<ReturnType<typeof api.dissectArticle>>;

export const ELEMENT_ZH: Record<string, string> = {
  actor: "主体",
  target: "客体",
  stakeholder: "利益相关方",
  hard_fact: "核心事实",
  quant_data: "硬核数据",
  data_scope: "数据定义域",
  action: "核心动作",
  causal_link: "因果链条",
  timeline: "时间线",
  perspective: "叙事视角",
  explicit_stance: "显性立场",
  implicit_bias: "隐性倾向",
  tone: "情绪基调",
  diction: "修辞与用词",
  source_reliability: "信源属性",
  argument_structure: "论证逻辑",
  intent: "发布动机",
  context: "背景",
};

const ELEMENT_ORDER = Object.keys(ELEMENT_ZH);

function shortLabel(itemKey: string): string {
  // src:URL:ts → 取 URL 域名+尾段，避免超长
  const parts = itemKey.split(":");
  return parts.length >= 3 ? `${parts[1].replace(/^https?:\/\//, "").slice(0, 24)}…` : itemKey.slice(0, 28);
}

export function DissectionPanel({ itemKeys }: { itemKeys: string[] }) {
  const [selected, setSelected] = useState<string>("");
  const [data, setData] = useState<Dissection | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");

  if (itemKeys.length === 0) return null;

  const run = () => {
    if (!selected) return;
    setLoading(true);
    setError("");
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 100_000);
    api
      .dissectArticle(selected, false, ctrl.signal)
      .then((d) => {
        setData(d);
        track("evidence_opened", { objectId: selected, fromPage: "/events#dissection" });
      })
      .catch(() => setError("拆解失败——模型未在预期时间内返回，可稍后重试。"))
      .finally(() => {
        clearTimeout(timer);
        setLoading(false);
      });
  };

  type El = NonNullable<Dissection["elements"]>[number];
  const byElement = new Map<string, El>(
    (data?.elements ?? []).map((e) => [e.element as string, e]),
  );

  return (
    <div className="mt-4 border-t border-dashed border-border pt-3" aria-label="文章拆解">
      <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        文章拆解（18 要素 · 消息来源结构分析）
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <select
          aria-label="选择要拆解的文章"
          value={selected}
          onChange={(e) => {
            setSelected(e.target.value);
            setData(null);
            setError("");
          }}
          className="border border-border bg-transparent px-2 py-1 text-xs"
        >
          <option value="">选择一篇文章…</option>
          {itemKeys.slice(0, 20).map((k) => (
            <option key={k} value={k}>
              {shortLabel(k)}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={run}
          disabled={!selected || loading}
          className="border border-border px-3 py-1 text-xs hover:border-primary disabled:opacity-40"
        >
          {loading ? "拆解中（约需 1–2 分钟，超时自动降级为词典拆解）…" : "拆解本文"}
        </button>
      </div>
      {error && <p className="mt-2 text-xs text-[var(--color-signal-divergence)]">{error}</p>}
      {data && (
        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
          <p className="col-span-full text-[10px] uppercase text-muted-foreground">
            {data.engine === "llm"
              ? `AI 拆解 · ${data.model_hint}`
              : "词典降级拆解（未配置模型或模型不可用）"}
          </p>
          {ELEMENT_ORDER.map((k) => {
            const el = byElement.get(k);
            return (
              <div
                key={k}
                className="border border-border/50 px-2 py-1.5"
                style={el ? { borderLeft: `3px solid ${SIGNAL.narrative}` } : undefined}
              >
                <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  {ELEMENT_ZH[k]}
                </p>
                <p className="text-xs leading-5">
                  {el ? el.content : <span className="text-muted-foreground/60">未提取</span>}
                </p>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
