"use client";

/**
 * 偏好卡：界面语言 zh/en 切换（读写 localStorage "oh-locale"，经 LanguageProvider 全站生效）。
 */

import { useLocale } from "@/lib/i18n/use-t";
import { type TFunc } from "@/components/monitors/bits";
import { SectionCard } from "./section-card";

export function PrefsCard({ t }: { t: TFunc }) {
  const { locale, setLocale } = useLocale();
  const supported = locale === "zh" || locale === "en";

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
      </div>
    </SectionCard>
  );
}
