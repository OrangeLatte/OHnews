import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "OH!News",
  description: "Agent 原生市场叙事情报台（非商业研究）",
};

const NAV = [
  { href: "/", label: "仪表盘" },
  { href: "/brief", label: "晨报" },
  { href: "/research", label: "问诊" },
  { href: "/decisions", label: "决策日志" },
  { href: "/dev/monitor", label: "Dev 监控" },
];

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="zh" className="dark h-full antialiased">
      <body className="min-h-full flex flex-col">
        <nav className="flex items-center gap-4 border-b px-6 py-3">
          <span className="text-lg font-bold">OH!News</span>
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              className="text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              {n.label}
            </Link>
          ))}
          <span className="ml-auto text-xs text-muted-foreground">
            NDI = EPU 式条件变量，非收益预测器
          </span>
        </nav>
        <main className="mx-auto w-full max-w-6xl flex-1 p-6">{children}</main>
        <footer className="border-t px-6 py-3 text-xs text-muted-foreground">
          叙事分歧指数 NDI 为描述性监测指标；测量效度 ρ≥0.8 通过前不对外引用。
          本项目为非商业研究，不构成投资建议。
        </footer>
      </body>
    </html>
  );
}
