"use client";

/**
 * SETTINGS 空间（06）：模型服务 / 用量 / 偏好 / 数据说明 四区块卡 + 旧开发者页入口。
 * 数据：GET /api/keys、GET /api/llm/health（真实 ping，?refresh=true 绕过 60s 缓存）、GET /api/usage。
 * 后端缺口时诚实文案（未计价、未连接），不伪装成功。
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { useLocale } from "@/lib/i18n/use-t";
import { Skeleton } from "@/components/ui/toast";
import { toast } from "@/components/ui/toast";
import { useExtraT } from "@/components/monitors/i18n-extra";
import { SectionCard } from "@/components/settings/section-card";
import { ModelServiceCard, type HealthOut, type KeysOut } from "@/components/settings/model-service-card";
import { UsageCard, type UsageOut } from "@/components/settings/usage-card";
import { PrefsCard } from "@/components/settings/prefs-card";
import { DataCard } from "@/components/settings/data-card";

async function getJson<T>(path: string): Promise<T> {
  const r = await fetch(`/api${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return (await r.json()) as T;
}

export default function SettingsPage() {
  const t = useExtraT();
  const { locale } = useLocale();
  const lang: "en" | "zh" = locale.startsWith("zh") ? "zh" : "en";

  const [keys, setKeys] = useState<KeysOut | null>(null);
  const [health, setHealth] = useState<HealthOut | null>(null);
  const [usage, setUsage] = useState<UsageOut | null>(null);
  const [checking, setChecking] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let alive = true;
    Promise.all([
      getJson<KeysOut>("/keys").catch(() => null),
      getJson<HealthOut>("/llm/health").catch(() => null),
      getJson<UsageOut>("/usage").catch(() => null),
    ]).then(([k, h, u]) => {
      if (!alive) return;
      setKeys(k);
      setHealth(h);
      setUsage(u);
      setLoaded(true);
    });
    return () => {
      alive = false;
    };
  }, []);

  const recheck = () => {
    setChecking(true);
    getJson<HealthOut>("/llm/health?refresh=true")
      .then((h) => {
        setHealth(h);
        setChecking(false);
        toast.success(h.ready ? t("settings.modelReady") : t("settings.modelDown"));
      })
      .catch(() => {
        setChecking(false);
        toast.error(t("settings.healthFailed"));
      });
  };

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold">{t("nav.settings")}</h1>
        <p className="mt-0.5 max-w-2xl text-[13px] text-muted-foreground">{t("settings.subtitle")}</p>
      </header>

      {!loaded ? (
        <div className="space-y-3" aria-hidden="true">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-28 w-full" />
          ))}
        </div>
      ) : (
        <>
          <ModelServiceCard
            health={health}
            keys={keys}
            checking={checking}
            onRecheck={recheck}
            t={t}
            lang={lang}
          />
          <UsageCard usage={usage} t={t} />
          <PrefsCard t={t} />
          <DataCard usage={usage} t={t} />
        </>
      )}

      <SectionCard title={t("settings.developer")} tone="idle">
        <p className="text-xs text-muted-foreground">{t("settings.developerHint")}</p>
        <Link
          href="/settings/developer"
          className="mt-2 inline-block rounded-md border px-3 py-1.5 text-[13px] font-medium hover:bg-accent"
        >
          {t("settings.openDeveloper")}
        </Link>
      </SectionCard>
    </div>
  );
}
