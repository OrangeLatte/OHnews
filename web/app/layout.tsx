import type { Metadata } from "next";
import Link from "next/link";
import { FilterProvider } from "@/components/filters/filter-context";
import "./globals.css";

export const metadata: Metadata = {
  title: "OH!News",
  description: "Agent 原生市场叙事情报台（非商业研究）",
};

const NAV: { href: string; no: string; label: string; zh: string }[] = [
  { href: "/", no: "01", label: "INTELLIGENCE", zh: "情报总览" },
  { href: "/today", no: "02", label: "SIGNALS", zh: "今日信号" },
  { href: "/events", no: "03", label: "EVENTS", zh: "事件与叙事" },
  { href: "/watch", no: "04", label: "WATCHLIST", zh: "关注与订阅" },
  { href: "/research", no: "05", label: "RESEARCH", zh: "研究工作台" },
  { href: "/library", no: "06", label: "ARCHIVE", zh: "研究档案" },
];

/* 工具页：主导航之外的深水区入口（R5e 路由收敛 19→6 主+工具区） */
const TOOLS: { href: string; label: string; zh: string }[] = [
  { href: "/intel", label: "PATROL", zh: "情报巡逻" },
  { href: "/brief", label: "BRIEF", zh: "晨报" },
  { href: "/timeline", label: "TIMELINE", zh: "叙事时间轴" },
  { href: "/analyze", label: "ANATOMY", zh: "事件解剖" },
  { href: "/alerts", label: "ALERTS", zh: "预警" },
  { href: "/dev/monitor", label: "DEV", zh: "开发监控" },
];

export default function RootLayout({ children }: LayoutProps<"/">) {
  const today = new Date().toLocaleDateString("en-US", {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  });
  return (
    <html lang="zh" className="h-full antialiased">
      <body className="min-h-full flex flex-col">
        <FilterProvider>
        <header className="mx-auto w-full max-w-7xl px-6 pt-6">
          <div className="flex items-end justify-between border-b pb-1">
            <p className="paper-kicker">Non-commercial research edition</p>
            <p className="paper-kicker">{today}</p>
          </div>
          <div className="flex items-baseline justify-between py-4">
            <Link href="/" className="font-paper text-4xl tracking-tight">
              OH!News
            </Link>
            <p className="font-paper text-sm italic text-muted-foreground">
              叙事分歧 · 每日监测
            </p>
          </div>
          <nav className="paper-rule flex flex-wrap items-center gap-x-5 gap-y-1.5 pb-2">
            {NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                className="group flex items-baseline gap-1.5 hover:!text-primary"
              >
                <span className="paper-kicker !text-muted-foreground/70">{n.no}</span>
                <span className="paper-kicker !text-foreground">{n.label}</span>
                <span className="hidden text-[11px] text-muted-foreground lg:inline">{n.zh}</span>
              </Link>
            ))}
            <span className="ml-auto paper-kicker hidden md:inline">
              NDI = EPU 式条件变量，非收益预测器
            </span>
          </nav>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-foreground/10 py-1.5">
            <span className="paper-kicker !text-muted-foreground/60">TOOLS</span>
            {TOOLS.map((t) => (
              <Link
                key={t.href}
                href={t.href}
                className="group flex items-baseline gap-1 hover:!text-primary"
              >
                <span className="paper-kicker !text-[10px] !text-muted-foreground">{t.label}</span>
                <span className="hidden text-[10px] text-muted-foreground/70 lg:inline">{t.zh}</span>
              </Link>
            ))}
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-6 py-6">{children}</main>
        <footer className="mx-auto w-full max-w-7xl border-t px-6 py-3 text-xs text-muted-foreground">
          叙事分歧指数 NDI 为描述性监测指标；测量效度 ρ≥0.8 通过前不对外引用。
          本项目为非商业研究，不构成投资建议。
        </footer>
        </FilterProvider>
      </body>
    </html>
  );
}
