"use client";

/**
 * WATCH 空间（03）：信源管理 + 跟踪预警 双工作区合并页。
 * - tab 状态读 URL ?tab=（默认 sources；非法值回落 sources），effect 内 setTimeout(0)
 *   异步读取：避免 SSR 首帧不一致（hydration mismatch）与 set-state-in-effect 规则冲突。
 * - 切换 tab 用 history.replaceState 同步 URL（不触发路由导航），刷新/分享可保持工作区，
 *   其余 query 参数（open/create 等）原样保留，由对应 workspace 自行消费。
 * - 深链：/watch?tab=monitors&create=1、/watch?tab=monitors&open=<id>
 *   （沿袭旧 /monitors 契约；旧 /sources /monitors 路由由薄壳页 redirect 兜底）。
 */

import { useEffect, useState } from "react";
import { useT } from "@/lib/i18n/use-t";
import { SourcesWorkspace } from "@/components/watch/sources-workspace";
import { MonitorsWorkspace } from "@/components/watch/monitors-workspace";

type WatchTab = "sources" | "monitors";

const TABS: WatchTab[] = ["sources", "monitors"];

function tabOf(params: URLSearchParams): WatchTab {
  return params.get("tab") === "monitors" ? "monitors" : "sources";
}

export default function WatchPage() {
  const t = useT();
  const [tab, setTab] = useState<WatchTab>("sources");

  useEffect(() => {
    const timer = setTimeout(() => {
      setTab(tabOf(new URLSearchParams(window.location.search)));
    }, 0);
    return () => clearTimeout(timer);
  }, []);

  const selectTab = (next: WatchTab): void => {
    setTab(next);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", next);
    window.history.replaceState(null, "", url.toString());
  };

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold">{t("watch.title")}</h1>
        <p className="mt-0.5 max-w-2xl text-[13px] text-muted-foreground">{t("watch.sub")}</p>
      </header>

      <div role="tablist" aria-label={t("watch.title")} className="flex flex-wrap items-center gap-1.5">
        {TABS.map((id) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            aria-controls={`watch-panel-${id}`}
            className={`rounded-md border px-3 py-1.5 text-[13px] hover:bg-accent ${
              tab === id ? "bg-accent font-medium" : ""
            }`}
            onClick={() => selectTab(id)}
          >
            {t(id === "sources" ? "watch.tab.sources" : "watch.tab.monitors")}
          </button>
        ))}
      </div>

      <div id={`watch-panel-${tab}`} role="tabpanel" aria-label={t(tab === "sources" ? "watch.tab.sources" : "watch.tab.monitors")}>
        {tab === "sources" ? <SourcesWorkspace /> : <MonitorsWorkspace />}
      </div>
    </div>
  );
}
