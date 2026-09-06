"use client";

/**
 * ARCHIVE 空间（05）：只存经用户确认（UserCommit）的不可变版本。
 * 顶部统计 + 六 tab + 前端搜索 + 富行列表（行展开版本链）+ Press Edition 向导。
 * GET /api/artifacts 只返回 committed；版本链懒加载（展开行时拉取）。
 */

import { useEffect, useMemo, useState } from "react";
import { objectApi } from "@/lib/object-api";
import { useLocale } from "@/lib/i18n/use-t";
import { Skeleton } from "@/components/ui/toast";
import { HelpIcon } from "@/components/help/help-icon";
import { relTime } from "@/components/monitors/format";
import { EmptyGuide, StatCard, type TFunc } from "@/components/monitors/bits";
import { useExtraT } from "@/components/monitors/i18n-extra";
import { KlassChip, KLASSES, klassLabel, type Klass } from "@/components/archive/klass";
import { RevisionChain, type RevisionWithContent } from "@/components/archive/revision-chain";
import { PressWizard, type ArchiveRowExt } from "@/components/archive/press-wizard";

type Tab = Klass | "all";

export default function ArchivePage() {
  const t: TFunc = useExtraT();
  const { locale } = useLocale();
  const lang: "en" | "zh" = locale.startsWith("zh") ? "zh" : "en";

  const [rows, setRows] = useState<ArchiveRowExt[]>([]);
  const [tab, setTab] = useState<Tab>("all");
  const [query, setQuery] = useState("");
  const [chain, setChain] = useState<Record<string, RevisionWithContent[]>>({});
  const [openChain, setOpenChain] = useState("");
  const [sel, setSel] = useState<Record<string, boolean>>({});
  const [loaded, setLoaded] = useState(false);
  const [loadErr, setLoadErr] = useState("");

  const load = (onDone?: () => void) => {
    objectApi
      .archive()
      .then((list) => {
        setRows(list as ArchiveRowExt[]);
        setLoadErr("");
        setLoaded(true);
        onDone?.();
      })
      .catch(() => {
        setLoadErr(t("archive.loadFailed"));
        setLoaded(true);
        onDone?.();
      });
  };

  useEffect(() => {
    let alive = true;
    objectApi
      .archive()
      .then((list) => {
        if (!alive) return;
        setRows(list as ArchiveRowExt[]);
        setLoadErr("");
        setLoaded(true);
      })
      .catch(() => {
        if (alive) {
          setLoadErr(t("archive.loadFailed"));
          setLoaded(true);
        }
      });
    return () => {
      alive = false;
    };
  }, [t]);

  const toggleChain = (artifactId: string) => {
    setOpenChain((cur) => (cur === artifactId ? "" : artifactId));
    if (chain[artifactId]) return;
    objectApi
      .artifactRevisions(artifactId)
      .then((list) => setChain((c) => ({ ...c, [artifactId]: list as RevisionWithContent[] })))
      .catch(() => setChain((c) => ({ ...c, [artifactId]: [] })));
  };

  const counts = useMemo(() => {
    const map: Record<string, number> = {};
    rows.forEach((r) => {
      map[r.klass] = (map[r.klass] ?? 0) + 1;
    });
    return map;
  }, [rows]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter((r) => {
      if (tab !== "all" && r.klass !== tab) return false;
      if (!q) return true;
      const hay = [r.title, r.case_id, r.klass, r.commit_note ?? ""].join(" ").toLowerCase();
      return hay.includes(q);
    });
  }, [rows, tab, query]);

  const selected = useMemo(() => rows.filter((r) => sel[r.artifact_id]), [rows, sel]);
  const editionsCount = counts["press_edition"] ?? 0;
  const casesCovered = useMemo(() => new Set(rows.map((r) => r.case_id)).size, [rows]);

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">{t("nav.archive")}</h1>
          <p className="mt-0.5 max-w-2xl text-[13px] text-muted-foreground">{t("archive.onlyCommitted")}</p>
        </div>
        <HelpIcon helpKey="state.needsConfirm" />
      </header>

      <section className="grid gap-2 sm:grid-cols-3" aria-label="archive stats">
        <StatCard label={t("archive.statItems")} value={rows.length} tone="ok" />
        <StatCard label={t("archive.statEditions")} value={editionsCount} tone="info" />
        <StatCard label={t("archive.statCases")} value={casesCovered} tone="idle" />
      </section>

      <PressWizard
        selected={selected}
        onRemove={(id) => setSel((s) => ({ ...s, [id]: false }))}
        onClear={() => setSel({})}
        onPublished={() => load()}
        t={t}
        lang={lang}
      />

      <div className="flex flex-wrap items-center gap-1.5" role="tablist" aria-label="klass filter">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "all"}
          className={`rounded-md border px-2 py-1 text-xs hover:bg-accent ${tab === "all" ? "bg-accent font-medium" : ""}`}
          onClick={() => setTab("all")}
        >
          {t("archive.filterAll")} · {rows.length}
        </button>
        {KLASSES.map((k) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={tab === k}
            className={`rounded-md border px-2 py-1 text-xs hover:bg-accent ${tab === k ? "bg-accent font-medium" : ""}`}
            onClick={() => setTab(k)}
          >
            {klassLabel(k, t)} · {counts[k] ?? 0}
          </button>
        ))}
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("archive.search")}
          className="ml-auto h-8 w-56 rounded-md border bg-background px-2 text-xs"
          aria-label={t("archive.search")}
        />
      </div>

      {loadErr && <p className="text-xs text-destructive">{loadErr}</p>}

      {!loaded ? (
        <div className="space-y-2" aria-hidden="true">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <EmptyGuide title={t("nav.archive")} body={t("archive.empty")} />
      ) : visible.length === 0 ? (
        <p className="rounded-xl border border-dashed p-4 text-center text-[13px] text-muted-foreground">
          {query.trim() ? t("archive.emptySearch") : t("archive.emptyTab")}
        </p>
      ) : (
        <ul className="space-y-2" aria-label="archive list">
          {visible.map((a) => {
            const open = openChain === a.artifact_id;
            const revisions = chain[a.artifact_id];
            const checked = sel[a.artifact_id] ?? false;
            return (
              <li key={`${a.artifact_id}-${a.current_revision_id}`} className="rounded-xl border bg-card">
                <div className="flex min-h-11 items-center gap-2 p-2.5">
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={(e) => setSel((s) => ({ ...s, [a.artifact_id]: e.target.checked }))}
                    onClick={(e) => e.stopPropagation()}
                    aria-label={`select ${a.title}`}
                    className="h-4 w-4 shrink-0"
                  />
                  <button
                    type="button"
                    className="flex min-w-0 flex-1 flex-col items-start gap-0.5 text-left"
                    aria-expanded={open}
                    onClick={() => toggleChain(a.artifact_id)}
                  >
                    <span className="flex w-full flex-wrap items-center gap-1.5">
                      <KlassChip klass={a.klass} />
                      <span className="min-w-0 truncate text-[13px] font-semibold">{a.title}</span>
                      {revisions && (
                        <span className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                          {revisions.length >= 2 ? `v1→v${revisions.length}` : `v${revisions.length}`}
                        </span>
                      )}
                    </span>
                    <span className="flex w-full flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                      <span className="font-mono">{a.case_id}</span>
                      {a.commit_note && <span title={a.commit_note}>· {a.commit_note}</span>}
                      <span>· {t("archive.committedAt")} {relTime(a.committed_at ?? a.revision_created_at, lang)}</span>
                      {!revisions && <span className="hidden sm:inline">· {t("archive.chainHint")}</span>}
                    </span>
                  </button>
                  <button
                    type="button"
                    className="shrink-0 rounded-md border px-2 py-1 text-xs hover:bg-accent"
                    aria-expanded={open}
                    onClick={() => toggleChain(a.artifact_id)}
                  >
                    {t("archive.chain")} {open ? "▾" : "▸"}
                  </button>
                </div>
                {open && (
                  <div className="border-t p-3">
                    {/* P0-C 档案元数据：创建者/确认者/确认时间/确认说明/来源 Case。
                        契约诚实降级：user_commits 无独立身份列，本地单操作者模式下两者均为
                        本地操作者，以 UserCommit（id/备注/时间戳）留痕，不编造身份。 */}
                    <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg bg-muted/30 px-2 py-1.5 text-[11px] text-muted-foreground">
                      <span>
                        {t("archive.creator")} ·{" "}
                        {a.case_created_by
                          ? t(
                              a.case_created_by === "watch"
                                ? "cases.originWatch"
                                : a.case_created_by === "agent"
                                  ? "cases.originAgent"
                                  : "cases.originUser",
                            )
                          : t("archive.actorLocal")}
                      </span>
                      <span>
                        {t("archive.confirmer")} · {a.confirmed_by || t("archive.actorLocal")}
                      </span>
                      <span>
                        {t("archive.committedAt")} {relTime(a.committed_at ?? a.revision_created_at, lang)}
                      </span>
                      {a.commit_id ? <span className="font-mono">{a.commit_id}</span> : null}
                      {a.commit_note ? (
                        <span title={a.commit_note}>
                          {t("archive.commitNote")}: {a.commit_note}
                        </span>
                      ) : null}
                      {a.case_id ? (
                        <a
                          href={`/cases/${encodeURIComponent(a.case_id)}`}
                          className="underline underline-offset-2 hover:text-foreground"
                        >
                          {t("archive.sourceCase")}: {a.case_id}
                        </a>
                      ) : (
                        <span title={t("archive.noCaseLink")}>{t("archive.noCaseLink")}</span>
                      )}
                    </div>
                    <p className="mb-2 text-[11px] text-muted-foreground">{t("archive.actorNote")}</p>
                    <RevisionChain
                      revisions={revisions ?? []}
                      t={t}
                      lang={lang}
                      artifactKlass={a.klass}
                      artifactTitle={a.title}
                      commitId={a.commit_id ?? undefined}
                      caseId={a.case_id || undefined}
                    />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

    </div>
  );
}
