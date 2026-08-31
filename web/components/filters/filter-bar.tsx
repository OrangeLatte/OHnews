"use client";

/**
 * R5c 过滤器条：FilterContext 的默认 UI。
 *
 * - options 按 key 提供候选值（值/标签）；未提供的 key 不渲染控件
 * - 内置标签：timeRange/signalKind/frame/entityType/language 已有中文映射；
 *   entity/source 的候选来自页面接入方（/api/entities、/api/sources）
 * - 时间范围变化即 URL 更新，R6 图表层读取后作为 days 参数
 */

import { useFilters, type FilterKey } from "./filter-context";
import { FRAME_ZH } from "@/lib/tokens";

type Option = { value: string; label: string };

const TIME_OPTIONS: Option[] = [
  { value: "7d", label: "近 7 天" },
  { value: "14d", label: "近 14 天" },
  { value: "30d", label: "近 30 天" },
  { value: "60d", label: "近 60 天" },
  { value: "90d", label: "近 90 天" },
];

const SIGNAL_KIND_OPTIONS: Option[] = [
  { value: "attention_spike", label: "注意力聚集" },
  { value: "narrative_shift", label: "叙事转变" },
  { value: "ndi_alert", label: "叙事分歧升高" },
  { value: "expectation_gap", label: "官方与市场预期错位" },
];

const ENTITY_TYPE_OPTIONS: Option[] = [
  { value: "central_bank", label: "央行" },
  { value: "government", label: "政府" },
  { value: "company_systemic", label: "系统性公司" },
  { value: "company", label: "公司" },
  { value: "person", label: "人物" },
  { value: "other", label: "其他机构" },
];

const LANGUAGE_OPTIONS: Option[] = [
  { value: "zh", label: "中文语料" },
  { value: "en", label: "英文语料" },
];

const FRAME_OPTIONS: Option[] = Object.entries(FRAME_ZH).map(([value, label]) => ({
  value,
  label,
}));

const BUILTIN_OPTIONS: Partial<Record<FilterKey, Option[]>> = {
  timeRange: TIME_OPTIONS,
  signalKind: SIGNAL_KIND_OPTIONS,
  entityType: ENTITY_TYPE_OPTIONS,
  language: LANGUAGE_OPTIONS,
  frame: FRAME_OPTIONS,
};

const KEY_LABELS: Record<FilterKey, string> = {
  timeRange: "时间",
  entity: "实体",
  entityType: "实体类型",
  source: "信息源",
  frame: "叙事框架",
  emotion: "情绪",
  signalKind: "信号类型",
  language: "语料语言",
};

export type FilterBarOptions = Partial<Record<FilterKey, Option[]>>;

export function FilterBar({ options, className }: { options?: FilterBarOptions; className?: string }) {
  const { filters, setFilter, clearFilters, isDefault } = useFilters();

  const visibleKeys = (Object.keys(KEY_LABELS) as FilterKey[]).filter(
    (key) => (options?.[key] ?? BUILTIN_OPTIONS[key])?.length,
  );
  if (!visibleKeys.length) return null;

  const active = visibleKeys.filter((key) => filters[key]);

  return (
    <div
      className={`flex flex-wrap items-center gap-x-4 gap-y-2 border-y border-border/60 py-2 text-[13px] ${className ?? ""}`}
    >
      {visibleKeys.map((key) => {
        const opts = options?.[key] ?? BUILTIN_OPTIONS[key] ?? [];
        const value = filters[key] ?? "";
        return (
          <label key={key} className="flex items-center gap-1.5 text-muted-foreground">
            <span className="paper-kicker">{KEY_LABELS[key]}</span>
            <select
              className="max-w-52 rounded-none border border-border bg-transparent px-1.5 py-0.5 text-[13px] text-foreground"
              value={value}
              onChange={(e) => setFilter(key, e.target.value || null)}
            >
              <option value="">全部</option>
              {opts.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
        );
      })}
      {!isDefault && (
        <button
          type="button"
          className="ml-auto underline underline-offset-4 decoration-dotted text-muted-foreground hover:text-foreground"
          onClick={clearFilters}
        >
          清除过滤{active.length ? `（${active.length}）` : ""}
        </button>
      )}
    </div>
  );
}
