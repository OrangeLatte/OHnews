"use client";

import Link from "next/link";
import { SearchBar } from "@/components/search/search-bar";
import { LOCALES } from "@/lib/i18n/locales";
import { useLocale, useT } from "@/lib/i18n/use-t";

/* IA 迁移：顶层收敛为四空间 NOW/INVESTIGATE/WATCH/MEMORY（旧 /sources /monitors
   并入 /watch 双 tab，路由由薄壳 redirect 兜底）。label 走 t(key)（缺键回退 en）。 */
const NAV: { href: string; no: string; key: string }[] = [
  { href: "/observe", no: "01", key: "nav.now" },
  { href: "/cases", no: "02", key: "nav.investigate" },
  { href: "/watch", no: "03", key: "nav.watch" },
  { href: "/archive", no: "04", key: "nav.memory" },
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
    <header className="mx-auto w-full max-w-[1400px] px-6 pt-6">
      <div className="flex flex-wrap items-end justify-between gap-x-4 border-b pb-1">
        <p className="paper-kicker">Non-commercial research edition</p>
        <p className="paper-kicker">{today}</p>
      </div>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 py-4">
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
            <span className="paper-kicker !text-foreground">{t(n.key)}</span>
          </Link>
        ))}
        <span className="ml-auto flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1.5">
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
