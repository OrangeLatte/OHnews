import type { Metadata } from "next";
import { FilterProvider } from "@/components/filters/filter-context";
import { HeaderNav } from "@/components/chrome/header-nav";
import { ApiHealthBanner } from "@/components/chrome/api-health-banner";
import { AgentDock } from "@/components/agent/agent-dock";
import { ToastViewport } from "@/components/ui/toast";
import { LanguageProvider } from "@/lib/i18n/use-t";
import "./globals.css";

export const metadata: Metadata = {
  title: "OH!News",
  description: "Agent 原生市场叙事情报台（非商业研究）",
};




export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col">
        <LanguageProvider>
          <FilterProvider>
        <HeaderNav />
        <ApiHealthBanner />
        <main className="mx-auto w-full max-w-[1400px] flex-1 px-6 py-6">{children}</main>
        <footer className="mx-auto w-full max-w-[1400px] border-t px-6 py-3 text-xs text-muted-foreground">
          叙事分歧指数 NDI 为描述性监测指标；测量效度 ρ≥0.8 通过前不对外引用。
          本项目为非商业研究，不构成投资建议。
        </footer>
        {/* 全局单一 Agent Runtime：布局级挂载，跨页面保持同一会话 */}
        <AgentDock agentKind="parent" title="OH! Agent" position="right" />
        <ToastViewport />
          </FilterProvider>
        </LanguageProvider>
      </body>
    </html>
  );
}
