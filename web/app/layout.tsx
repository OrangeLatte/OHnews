import type { Metadata } from "next";
import { FilterProvider } from "@/components/filters/filter-context";
import { HeaderNav } from "@/components/chrome/header-nav";
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
        <main className="mx-auto w-full max-w-7xl flex-1 px-6 py-6">{children}</main>
        <footer className="mx-auto w-full max-w-7xl border-t px-6 py-3 text-xs text-muted-foreground">
          叙事分歧指数 NDI 为描述性监测指标；测量效度 ρ≥0.8 通过前不对外引用。
          本项目为非商业研究，不构成投资建议。
        </footer>
          </FilterProvider>
        </LanguageProvider>
      </body>
    </html>
  );
}
