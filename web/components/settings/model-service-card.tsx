"use client";

/**
 * 模型服务卡：llm_ready 状态灯 + 真实 health（ping）detail/latency/checked_at + keys 状态 + 重新检测。
 * 诚实原则：未检测 / 检测失败如实显示，不伪装成功。
 */

import { Button } from "@/components/ui/button";
import { relTime } from "@/components/monitors/format";
import { ToneChip, type TFunc, type Tone } from "@/components/monitors/bits";
import { SectionCard } from "./section-card";

export type KeysOut = {
  deepseek: boolean;
  zhipu: boolean;
  tavily: boolean;
  llm_ready: boolean;
};

export type HealthOut = {
  ready: boolean;
  detail: string;
  latency_ms: number;
  checked_at: string | null;
};

export function modelTone(health: HealthOut | null, checking: boolean): Tone {
  if (checking) return "warn";
  if (!health) return "idle";
  return health.ready ? "ok" : "bad";
}

export function ModelServiceCard({
  health,
  keys,
  checking,
  onRecheck,
  t,
  lang,
}: {
  health: HealthOut | null;
  keys: KeysOut | null;
  checking: boolean;
  onRecheck: () => void;
  t: TFunc;
  lang: "en" | "zh";
}) {
  const tone = modelTone(health, checking);
  const label = checking
    ? t("settings.modelChecking")
    : health
      ? health.ready
        ? t("settings.modelReady")
        : t("settings.modelDown")
      : t("settings.loadFailed");

  return (
    <SectionCard
      title={t("settings.model")}
      tone={tone}
      pulse={checking}
      helpKey="state.notConfigured"
      actions={
        <Button size="sm" variant="outline" disabled={checking} onClick={onRecheck}>
          {t("settings.recheck")}
        </Button>
      }
    >
      <div className="space-y-2 text-[13px]">
        <p className="flex flex-wrap items-center gap-2">
          <ToneChip tone={tone}>{label}</ToneChip>
          {keys && (
            <span className="text-xs text-muted-foreground">
              llm_ready: <span className="font-mono">{String(keys.llm_ready)}</span>
            </span>
          )}
        </p>
        {health ? (
          <dl className="grid gap-x-4 gap-y-1 text-xs text-muted-foreground sm:grid-cols-2">
            <div className="flex min-w-0 gap-1 sm:col-span-2">
              <dt className="shrink-0">{t("settings.healthDetail")}:</dt>
              <dd className="truncate" title={health.detail}>
                {health.detail || "—"}
              </dd>
            </div>
            <div className="flex gap-1">
              <dt className="shrink-0">{t("settings.healthLatency")}:</dt>
              <dd className="font-mono">
                {typeof health.latency_ms === "number" ? `${health.latency_ms} ms` : "—"}
              </dd>
            </div>
            <div className="flex gap-1">
              <dt className="shrink-0">{t("settings.healthCheckedAt")}:</dt>
              <dd>{health.checked_at ? relTime(health.checked_at, lang) : t("settings.healthNever")}</dd>
            </div>
          </dl>
        ) : (
          <p className="text-xs text-muted-foreground">{t("settings.healthNever")}</p>
        )}
        {keys && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-muted-foreground">{t("settings.keys")}:</span>
            {(["deepseek", "zhipu", "tavily"] as const).map((k) => (
              <ToneChip key={k} tone={keys[k] ? "ok" : "idle"} striped={!keys[k]}>
                {k} · {keys[k] ? t("settings.keyOn") : t("settings.keyOff")}
              </ToneChip>
            ))}
          </div>
        )}
      </div>
    </SectionCard>
  );
}
