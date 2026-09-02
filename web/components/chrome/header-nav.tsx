"use client";

import Link from "next/link";
import { SearchBar } from "@/components/search/search-bar";
import { LOCALES } from "@/lib/i18n/locales";
import { useLocale, useT } from "@/lib/i18n/use-t";

/* 阶段 1.5 IA 手术：四入口 = 发现→调查→判断→追踪的产品路径（用户裁决） */
const NAV: { href: string; no: string; label: string; key: string }[] = [
  { href: "/", no: "01", label: "NOW", key: "nav.now" },
  { href: "/investigate", no: "02", label: "INVESTIGATE", key: "nav.investigate" },
  { href: "/watch", no: "03", label: "WATCH", key: "nav.watch" },
  { href: "/memory", no: "04", label: "MEMORY", key: "nav.memory" },
];

function LangSwitcher() {
  const { locale, setLocale } = useLocale();
  return (
    <select
      aria-label="UI language / 界面语言"
      value={locale}
      onChange={(e) => setLocale(e.target.value)}
      className="paper-kicker border border-border bg-transparent px-1 py-0.5"
    >
      {LOCALES.map((l) => (
        <option key={l.code} value={l.code}>
          {l.name}
        </option>
      ))}
    </select>
  );
}

export function HeaderNav() {
  const t = useT();
  const today = new Date().toLocaleDateString("en-US", {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  });
  return (
    <header className="mx-auto w-full max-w-7xl px-6 pt-6">
      <div className="flex items-end justify-between border-b pb-1">
        <p className="paper-kicker">Non-commercial research edition</p>
        <p className="paper-kicker">{today}</p>
      </div>
      <div className="flex items-baseline justify-between py-4">
        <Link href="/" className="font-paper text-4xl tracking-tight">
          {t("home.title")}
        </Link>
        <p className="font-paper text-sm italic text-muted-foreground">
          {t("nav.disclaimer")}
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
            <span className="hidden text-[11px] text-muted-foreground lg:inline">
              {t(n.key)}
            </span>
          </Link>
        ))}
        <span className="ml-auto flex items-center gap-4">
          <SearchBar />
          <LangSwitcher />
          <Link href="/settings/developer" className="paper-kicker hover:!text-primary">
            ⚙ {t("nav.settings")}
          </Link>
        </span>
      </nav>
    </header>
  );
}
