"use client";

import Link from "next/link";
import { SearchBar } from "@/components/search/search-bar";
import { LOCALES } from "@/lib/i18n/locales";
import { useLocale, useT } from "@/lib/i18n/use-t";

/* Clean-slate A7：旧四入口（NOW/INVESTIGATE/WATCH/MEMORY）判 REPLACE，导航换新六空间 */
const NAV: { href: string; no: string; label: string; key: string }[] = [
  { href: "/observe", no: "01", label: "OBSERVE", key: "nav.observe" },
  { href: "/cases", no: "02", label: "CASES", key: "nav.cases" },
  { href: "/sources", no: "03", label: "SOURCES", key: "nav.sources" },
  { href: "/monitors", no: "04", label: "MONITORS", key: "nav.monitors" },
  { href: "/archive", no: "05", label: "ARCHIVE", key: "nav.archive" },
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
            <span className="paper-kicker !text-foreground">{n.label}</span>
            <span className="hidden text-[11px] text-muted-foreground lg:inline">
              {t(n.key)}
            </span>
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
