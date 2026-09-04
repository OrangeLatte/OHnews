"use client";

/**
 * 用量卡：summary 四数字卡（calls/token_in/token_out/cost）+ counts 网格。
 * cost_usd=0 显示「未计价」而非 0（后端未接入计价时不得伪装成本）。
 */

import { type TFunc } from "@/components/monitors/bits";
import { SectionCard } from "./section-card";

export type UsageOut = {
  summary: { calls: number; token_in: number; token_out: number; cost_usd: number };
  counts: Record<string, number>;
};

export function UsageCard({
  usage,
  t,
}: {
  usage: UsageOut | null;
  t: TFunc;
}) {
  const s = usage?.summary;
  const unpriced = !s || !(s.cost_usd > 0);

  return (
    <SectionCard title={t("settings.usage")} tone={usage ? "info" : "idle"} helpKey="state.stale">
      {!usage ? (
        <p className="text-xs text-muted-foreground">{t("settings.loadFailed")}</p>
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
            {(
              [
                [t("settings.usageCalls"), s?.calls ?? 0],
                [t("settings.usageTokenIn"), s?.token_in ?? 0],
                [t("settings.usageTokenOut"), s?.token_out ?? 0],
              ] as const
            ).map(([label, value]) => (
              <div key={label} className="rounded-xl border bg-muted/30 p-3">
                <p className="text-xs text-muted-foreground">{label}</p>
                <p className="mt-0.5 text-lg font-semibold tabular-nums">{value.toLocaleString()}</p>
              </div>
            ))}
            <div className="rounded-xl border bg-muted/30 p-3">
              <p className="text-xs text-muted-foreground">{t("settings.usageCost")}</p>
              {unpriced ? (
                <p className="mt-1">
                  <span className="rounded-md bg-muted px-1.5 py-0.5 text-xs font-medium text-muted-foreground">
                    {t("settings.costUnpriced")}
                  </span>
                </p>
              ) : (
                <p className="mt-0.5 text-lg font-semibold tabular-nums">${(s?.cost_usd ?? 0).toFixed(4)}</p>
              )}
            </div>
          </div>
          {unpriced && <p className="text-xs text-muted-foreground">{t("settings.costNote")}</p>}

          <div>
            <p className="text-xs font-medium text-muted-foreground">{t("settings.counts")}</p>
            <div className="mt-1 grid grid-cols-2 gap-1.5 sm:grid-cols-3 lg:grid-cols-4">
              {Object.entries(usage.counts ?? {}).map(([k, v]) => (
                <div
                  key={k}
                  className="flex items-center justify-between gap-1 rounded-md border px-2 py-1 text-xs"
                  title={k}
                >
                  <span className="truncate text-muted-foreground">{k}</span>
                  <span className="font-mono tabular-nums">{v}</span>
                </div>
              ))}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{t("settings.countsNote")}</p>
          </div>
        </div>
      )}
    </SectionCard>
  );
}
