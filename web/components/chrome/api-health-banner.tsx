"use client";

/**
 * 后端健康探测横幅：/api/health 不可达时全站顶部提示降级，
 * 恢复后自动消失。纯 client 轮询，不阻塞渲染（后端未起不再白屏/500）。
 */

import { useCallback, useEffect, useState } from "react";
import { useT } from "@/lib/i18n/use-t";

const CHECK_MS = 15_000;

export function ApiHealthBanner() {
  const t = useT();
  const [down, setDown] = useState(false);

  const check = useCallback(() => {
    fetch("/api/health", { cache: "no-store" })
      .then((r) => setDown(!r.ok))
      .catch(() => setDown(true));
  }, []);

  useEffect(() => {
    check();
    const id = setInterval(check, CHECK_MS);
    return () => clearInterval(id);
  }, [check]);

  if (!down) return null;
  return (
    <div
      role="alert"
      className="sticky top-0 z-50 bg-amber-100 px-4 py-2 text-center text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200"
    >
      {t("health.down")}
    </div>
  );
}
