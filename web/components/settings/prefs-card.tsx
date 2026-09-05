"use client";

/**
 * 偏好卡：① 界面语言 zh/en 切换（localStorage "oh-locale"，经 LanguageProvider 全站生效）；
 * ② 分析输出语言（localStorage "oh-analysis-locale"，三独立字段之 analysis_locale，
 * 控制拆解/报告的分析产出书写语言，与 UI 语言解耦）。
 */

import { useLocale } from "@/lib/i18n/use-t";
import { useAnalysisLocale } from "@/lib/analysis-locale";
import { type TFunc } from "@/components/monitors/bits";
import { SectionCard } from "./section-card";

export function PrefsCard({ t }: { t: TFunc }) {
  const { locale, setLocale } = useLocale();
  const supported = locale === "zh" || locale === "en";
  const [analysisLocale, setAnalysisLocale] = useAnalysisLocale();

  return (
    <SectionCard title={t("settings.prefs")} tone="info" helpKey="state.needsConfirm">
      <div className="max-w-md space-y-2">
        <label className="flex items-center gap-3 text-[13px]">
          <span className="shrink-0 font-medium">{t("settings.language")}</span>
          <select
            value={supported ? locale : ""}
            onChange={(e) => setLocale(e.target.value)}
            className="h-8 min-w-40 flex-1 rounded-md border bg-background px-2 text-xs"
          >
            <option value="zh">简体中文 (zh)</option>
            <option value="en">English (en)</option>
            {!supported && (
              <option value="" disabled>
                {locale} —
              </option>
            )}
          </select>
        </label>
        <p className="text-xs text-muted-foreground">
          {t("settings.languageNote")}
          {!supported && ` ${t("settings.localeOther", { v: locale })}`}
        </p>
        <label className="flex items-center gap-3 text-[13px]">
          <span className="shrink-0 font-medium">{t("settings.analysisLocale")}</span>
          <select
            value={analysisLocale}
            onChange={(e) => setAnalysisLocale(e.target.value === "zh" ? "zh" : "en")}
            className="h-8 min-w-40 flex-1 rounded-md border bg-background px-2 text-xs"
          >
            <option value="zh">简体中文 (zh)</option>
            <option value="en">English (en)</option>
          </select>
        </label>
        <p className="text-xs text-muted-foreground">{t("settings.analysisLocaleNote")}</p>
      </div>
    </SectionCard>
  );
}
