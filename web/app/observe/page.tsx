"use client";

/**
 * OBSERVE 空间（Clean-slate 重构）：双区布局（左栏 facet + 主舞台七 tab）。
 * 认知流程：Signal 发现变化 → 五 Lens 下钻 → Inbox 检索证据 → 建研究 Case。
 * 窗口/tab 状态经 ?mode=&days= replaceState 同步；键盘 1-7 切 tab（输入框聚焦时跳过）。
 */

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { HelpIcon } from "@/components/help/help-icon";
import { ChangeDrawer, drawerEntity, drawerSubject, type ChangeSelection } from "@/components/observe/change-drawer";
import { DivergencePanel } from "@/components/observe/divergence-panel";
import { EmotionPanel } from "@/components/observe/emotion-panel";
import { ActionPanel } from "@/components/observe/action-panel";
import { EntitiesPanel } from "@/components/observe/entities-panel";
import { FlowPanel } from "@/components/observe/flow-panel";
import { HourglassPanel } from "@/components/observe/hourglass-panel";
import { InboxPanel, type InboxFilterHandlers, type InboxFilters } from "@/components/observe/inbox-panel";
import { NarrativePanel } from "@/components/observe/narrative-panel";
import { useOt } from "@/components/observe/i18n-bridge";
import {
  OBSERVE_MODES,
  getUrlServerSnapshot,
  getUrlSnapshot,
  setUrlState,
  subscribeUrl,
  type ObserveMode,
} from "@/components/observe/url-state";
import { Skeleton, toast } from "@/components/ui/toast";
import {
  fetchEmotion,
  fetchEntities,
  fetchEntityGraph,
  fetchEntityTimeline,
  fetchLandscape,
  fetchMonitorStrip,
  fetchNdiRank,
  fetchSources,
  type EmotionRow,
  type EntityGraphPayload,
  type EntityRow,
  type EntityTimeline,
  type Landscape,
  type NdiRankRow,
  type SourceRow,
} from "@/lib/landscape-api";
import { LOCALES } from "@/lib/i18n/locales";
import { useT } from "@/lib/i18n/use-t";

/** days=0（All）在只读端点按 3650d 展开；inbox 侧省略 days。 */
const ALL_DAYS_FETCH = 3650;
const WINDOWS: { d: number; label: string }[] = [
  { d: 1, label: "1d" },
  { d: 7, label: "7d" },
  { d: 15, label: "15d" },
  { d: 30, label: "30d" },
  { d: 0, label: "All" },
];

type MainData = { days: number; landscape: Landscape; ndi: NdiRankRow[]; emotion: EmotionRow[] };

function RailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-1.5">
      <h3 className="text-sm font-semibold">{title}</h3>
      {children}
    </section>
  );
}

function FilterChip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-[6px] border bg-muted/50 px-2 py-0.5 text-xs">
      {label}
      <button
        type="button"
        aria-label={`remove ${label}`}
        onClick={onRemove}
        className="opacity-60 hover:opacity-100"
      >
        ×
      </button>
    </span>
  );
}

export default function ObservePage() {
  const t = useT();
  const ot = useOt();

  const { mode, days, entity: urlEntity } = useSyncExternalStore(subscribeUrl, getUrlSnapshot, getUrlServerSnapshot);
  const fetchDays = days === 0 ? ALL_DAYS_FETCH : days;
  const setMode = useCallback((m: ObserveMode) => setUrlState({ mode: m }), []);
  const setDays = useCallback((d: number) => setUrlState({ days: d }), []);

  const [mainData, setMainData] = useState<MainData | null>(null);
  const [mainErr, setMainErr] = useState("");
  const [reloadTick, setReloadTick] = useState(0);

  const [sources, setSources] = useState<SourceRow[] | null>(null);
  const [sourcesErr, setSourcesErr] = useState("");
  const [selSourcesRaw, setSelSourcesRaw] = useState<string[] | null>(null);
  const [lang, setLang] = useState("");
  const [q, setQ] = useState("");
  const [qInput, setQInput] = useState("");
  const [element, setElement] = useState("");
  const [value, setValue] = useState("");
  const [valueInput, setValueInput] = useState("");
  const [includeCased, setIncludeCased] = useState(false);
  const qTimer = useRef<number | null>(null);
  const valueTimer = useRef<number | null>(null);

  const [entities, setEntities] = useState<EntityRow[] | null>(null);
  const [kg, setKg] = useState<EntityGraphPayload | null>(null);
  const [selEntity, setSelEntity] = useState("");
  const [timeline, setTimeline] = useState<EntityTimeline | null>(null);
  const [entityErr, setEntityErr] = useState("");

  const [strip, setStrip] = useState<{ total: number; pending: number } | null>(null);

  // <lg 左栏 facet 折叠抽屉（默认收起：390px 首屏主舞台全宽可见）
  const [filtersOpen, setFiltersOpen] = useState(false);

  // 统一 Change Drawer：任意数据点点击后打开（P1 图表联动）
  const [drawer, setDrawer] = useState<ChangeSelection | null>(null);
  // Drawer → Inbox 传实体通道（{q, entity?, days}；days 即当前窗口，Inbox 结果行已随窗口）
  const [inboxEntity, setInboxEntity] = useState("");
  // P0-D 硬验收：候选变化沿唯一主路径进入 Case 时携带原始 change_id（审计可追溯）
  const [inboxChangeId, setInboxChangeId] = useState("");
  const openDrawer = useCallback((sel: ChangeSelection) => setDrawer(sel), []);
  const closeDrawer = useCallback(() => setDrawer(null), []);
  const createCaseFromDrawer = useCallback(
    (sel: ChangeSelection) => {
      if (qTimer.current !== null) {
        window.clearTimeout(qTimer.current);
        qTimer.current = null;
      }
      const subject = drawerSubject(sel);
      if (subject) {
        setQ(subject);
        setQInput(subject);
      }
      setInboxEntity(drawerEntity(sel));
      setInboxChangeId(sel.kind === "change" ? sel.change.change_id : "");
      // 主路径保障（P0-D 硬验收：不得只跳回空列表）——清默认源预选，
      // 让 q/entity 全源检索；源筛选由用户到 Inbox 左栏显式设置
      setSelSourcesRaw([]);
      // 诚实降级：变化卡未提取到实体（subjects 空）→ 明示仅用标题关键词检索
      if (sel.kind === "change" && sel.change.subjects.length === 0) {
        toast.info(
          ot(
            "observe.drawer.noEntityFallback",
            "No entity extracted for this change; searched with the headline keyword instead.",
          ),
        );
      }
      setUrlState({ mode: "inbox" });
      setDrawer(null);
    },
    [ot],
  );

  // 搜索跳转 ?entity=：URL 参数自动选中实体（setTimeout(0) 异步初始化，
  // 规避 effect 内同步 setState 与 hydration mismatch；ref 防同值重复触发）
  const urlEntityApplied = useRef("");
  useEffect(() => {
    if (!urlEntity || urlEntity === urlEntityApplied.current) return;
    const timer = setTimeout(() => {
      urlEntityApplied.current = urlEntity;
      setSelEntity(urlEntity);
      setTimeline(null);
      setEntityErr("");
    }, 0);
    return () => clearTimeout(timer);
  }, [urlEntity]);

  // 主舞台只读数据（change-landscape + ndi/rank + emotion），窗口/来源/语言筛选变化整体重拉。
  // P0-3：来源/语言作用于 landscape 全链（两窗/检测/证据）。用户未显式选择信源
  // （selSourcesRaw=null）时主舞台不过滤（Inbox 的 Top3 预选不影响全局视图）。
  // NDI/Emotion 端点按全量数据计算，筛选不作用时在对应 Lens 诚实标注。
  useEffect(() => {
    let alive = true;
    Promise.all([
      fetchLandscape({
        days: fetchDays,
        sourceIds: selSourcesRaw ?? [],
        language: lang || undefined,
      }),
      fetchNdiRank(8),
      fetchEmotion(fetchDays),
    ])
      .then(([ls, rank, emo]) => {
        if (alive) {
          setMainData({ days: fetchDays, landscape: ls, ndi: rank, emotion: emo });
          setMainErr("");
        }
      })
      .catch((e: unknown) => {
        if (alive) setMainErr(e instanceof Error ? e.message : String(e));
      });
    return () => {
      alive = false;
    };
  }, [fetchDays, selSourcesRaw, lang, reloadTick]);

  // 左栏信源目录（一次性）
  useEffect(() => {
    let alive = true;
    fetchSources({})
      .then((r) => {
        if (alive) setSources(r.sources);
      })
      .catch((e: unknown) => {
        if (alive) setSourcesErr(e instanceof Error ? e.message : String(e));
      });
    return () => {
      alive = false;
    };
  }, []);

  // Entities 清单：进入 Entities tab 时惰性加载
  useEffect(() => {
    if (mode !== "entities" || entities !== null) return;
    let alive = true;
    fetchEntities()
      .then((list) => {
        if (alive) setEntities(list);
      })
      .catch((e: unknown) => {
        if (alive) setEntityErr(e instanceof Error ? e.message : String(e));
      });
    return () => {
      alive = false;
    };
  }, [mode, entities]);

  // KG 关系边：独立 effect（与 entities 同链时 setEntities 触发的 cleanup 会杀掉 setKg）
  useEffect(() => {
    if (mode !== "entities" || kg !== null) return;
    let alive = true;
    fetchEntityGraph()
      .then((g) => {
        if (alive) setKg(g);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [mode, kg]);

  // 实体时间轴：选中实体或窗口变化时重拉（stale-while-revalidate，顶部显示刷新中）
  useEffect(() => {
    if (!selEntity) return;
    let alive = true;
    fetchEntityTimeline(selEntity, fetchDays)
      .then((tl) => {
        if (alive) setTimeline(tl);
      })
      .catch((e: unknown) => {
        if (alive) setEntityErr(e instanceof Error ? e.message : String(e));
      });
    return () => {
      alive = false;
    };
  }, [selEntity, fetchDays]);

  // Monitors 窄条（失败不打断主舞台）
  useEffect(() => {
    let alive = true;
    fetchMonitorStrip()
      .then((s) => {
        if (alive) setStrip(s);
      })
      .catch(() => {
        /* 窄条失败不打断主舞台 */
      });
    return () => {
      alive = false;
    };
  }, []);

  // 键盘 1-7 切 tab；INPUT/TEXTAREA/SELECT 聚焦时跳过
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const el = e.target as HTMLElement | null;
      if (
        el &&
        (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable)
      ) {
        return;
      }
      const idx = "1234567".indexOf(e.key);
      if (idx >= 0 && idx < OBSERVE_MODES.length) setUrlState({ mode: OBSERVE_MODES[idx] });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // 筛选只表达用户显式选择。过去在首屏静默预选 Top3，但主舞台仍按全量计算，
  // 造成“看起来已筛选、数据却未筛选”的幽灵状态。空数组现在始终等于全量。
  const selSources = useMemo(() => selSourcesRaw ?? [], [selSourcesRaw]);

  const onToggleSource = useCallback(
    (id: string) => {
      setSelSourcesRaw((prev) => {
        const cur = prev ?? [];
        return cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id];
      });
    },
    [],
  );
  const onQInput = useCallback((v: string) => {
    setQInput(v);
    if (qTimer.current !== null) window.clearTimeout(qTimer.current);
    qTimer.current = window.setTimeout(() => setQ(v.trim()), 400);
  }, []);
  const onQCommit = useCallback(() => {
    if (qTimer.current !== null) {
      window.clearTimeout(qTimer.current);
      qTimer.current = null;
    }
    setQ(qInput.trim());
  }, [qInput]);
  const onValueInput = useCallback((v: string) => {
    setValueInput(v);
    if (valueTimer.current !== null) window.clearTimeout(valueTimer.current);
    valueTimer.current = window.setTimeout(() => setValue(v.trim()), 400);
  }, []);
  const onValueCommit = useCallback(() => {
    if (valueTimer.current !== null) {
      window.clearTimeout(valueTimer.current);
      valueTimer.current = null;
    }
    setValue(valueInput.trim());
  }, [valueInput]);
  const onElementChange = useCallback((v: string) => {
    setElement(v);
    setValue("");
    setValueInput("");
  }, []);
  const onClearFilters = useCallback(() => {
    setSelSourcesRaw([]);
    setLang("");
    setQ("");
    setQInput("");
    setElement("");
    setValue("");
    setValueInput("");
    setInboxEntity("");
  }, []);

  const onClearEntity = useCallback(() => setInboxEntity(""), []);

  const inboxFilters: InboxFilters = {
    q,
    qInput,
    lang,
    element,
    value,
    valueInput,
    includeCased,
    selSources,
    entity: inboxEntity,
  };
  const inboxHandlers: InboxFilterHandlers = {
    onQInput,
    onQCommit,
    onValueInput,
    onValueCommit,
    onElementChange,
    onToggleSource,
    onToggleIncludeCased: useCallback(() => setIncludeCased((v) => !v), []),
    onClearFilters,
    onClearEntity,
  };

  const openEntity = useCallback((entityId: string, jump = false) => {
    setSelEntity(entityId);
    setTimeline(null);
    setEntityErr("");
    if (jump) setUrlState({ mode: "entities" });
  }, []);

  // Drawer 内"查看实体时间线"：关 Drawer + 跳 Entities tab
  const openEntityTimeline = useCallback(
    (entityId: string) => {
      setDrawer(null);
      openEntity(entityId, true);
    },
    [openEntity],
  );

  const mainStale = mainData !== null && mainData.days !== fetchDays;
  // 诚实表述：数据截至 = freshness 覆盖尾（缺覆盖尾时退回场景生成时间），不用绝对"现在"
  const coverageEnd = mainData?.landscape.freshness?.coverage_end ?? null;
  const asOfText = coverageEnd
    ? `${coverageEnd.slice(0, 10)} ${coverageEnd.slice(11, 16)}`
    : mainData
      ? `${mainData.landscape.generated_at.slice(0, 10)} ${mainData.landscape.generated_at.slice(11, 16)}`
      : null;

  const tabLabels: Record<ObserveMode, string> = {
    signal: ot("observe.tab.signal", "Signal"),
    flow: t("lens.flow"),
    narrative: t("lens.narrative"),
    divergence: t("lens.divergence"),
    emotion: t("lens.emotion"),
    entities: t("lens.entities"),
    inbox: ot("observe.tab.inbox", "Inbox"),
  };
  const tabHelp: Record<ObserveMode, string> = {
    signal: "state.empty",
    flow: "lens.flow",
    narrative: "lens.narrative",
    divergence: "lens.divergence",
    emotion: "lens.emotion",
    entities: "lens.entities",
    inbox: "agent.hitl",
  };

  const tierGroups = useMemo(() => {
    const m = new Map<string, SourceRow[]>();
    for (const s of sources ?? []) {
      if ((s.n_7d ?? 0) <= 0) continue; // demo 裁剪：零产出源不进目录
      const arr = m.get(s.tier) ?? [];
      arr.push(s);
      m.set(s.tier, arr);
    }
    return [...m.entries()];
  }, [sources]);

  const langCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const s of sources ?? []) m.set(s.language, (m.get(s.language) ?? 0) + s.n_7d);
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [sources]);

  const langName = (code: string): string => LOCALES.find((l) => l.code === code)?.name ?? code;

  return (
    <div className="space-y-6">
      {/* 顶栏：标题 + 窗口切换 + data as of */}
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">{t("nav.now")}</h1>
        <button
          type="button"
          onClick={() => setFiltersOpen((v) => !v)}
          aria-expanded={filtersOpen}
          className="rounded-[6px] border px-2 py-0.5 text-xs lg:hidden"
        >
          {filtersOpen ? "✕ " : "☰ "}
          {t("observe.filters")}
        </button>
        <span className="flex items-center gap-1" role="group" aria-label={ot("observe.rail.window", "Time window")}>
          {WINDOWS.map((w) => (
            <button
              key={w.d}
              type="button"
              onClick={() => setDays(w.d)}
              aria-pressed={days === w.d}
              className={`rounded-[6px] border px-2 py-0.5 text-xs transition-colors ${
                days === w.d ? "bg-foreground text-background" : "hover:bg-muted/60"
              }`}
            >
              {w.label}
            </button>
          ))}
        </span>
        {asOfText ? (
          <span className="text-xs text-muted-foreground">{t("observe.coverageAsOf", { t: asOfText })}</span>
        ) : (
          <Skeleton className="h-4 w-44" />
        )}
        {mainStale ? (
          <span className="text-xs text-amber-600">⟳ {ot("observe.refreshing", "refreshing…")}</span>
        ) : null}
      </header>

      {mainErr ? (
        <div className="flex flex-wrap items-center gap-3 rounded-[12px] border border-red-300 bg-red-100 px-3 py-2 text-[13px] text-red-700 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-300">
          <span>{mainErr}</span>
          <button
            type="button"
            onClick={() => setReloadTick((x) => x + 1)}
            className="rounded-[6px] border px-2 py-0.5 text-xs hover:bg-background/50"
          >
            {ot("observe.retry", "Retry")}
          </button>
        </div>
      ) : null}

      {/* 生效筛选 chips（可 × 移除） */}
      {days !== 7 || lang !== "" || q !== "" || element !== "" || selSources.length > 0 ? (
        <div className="flex flex-wrap items-center gap-1.5" aria-label={ot("observe.activeFilters", "Active filters")}>
          {days !== 7 ? (
            <FilterChip
              label={`${ot("observe.rail.window", "Time window")}: ${WINDOWS.find((w) => w.d === days)?.label ?? days}`}
              onRemove={() => setDays(7)}
            />
          ) : null}
          {selSources.map((id) => (
            <FilterChip key={id} label={id} onRemove={() => onToggleSource(id)} />
          ))}
          {lang !== "" ? <FilterChip label={langName(lang)} onRemove={() => setLang("")} /> : null}
          {q !== "" ? <FilterChip label={`“${q}”`} onRemove={() => { setQ(""); setQInput(""); }} /> : null}
          {element !== "" ? (
            <FilterChip
              label={value ? `${element}: ${value}` : element}
              onRemove={() => onElementChange("")}
            />
          ) : null}
          <button
            type="button"
            onClick={onClearFilters}
            className="rounded-[6px] px-1.5 py-0.5 text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
          >
            {ot("observe.inbox.clearFilters", "Clear filters")}
          </button>
        </div>
      ) : null}

      {/* 双区：左栏 facet + 主舞台；<lg 左栏收进抽屉（默认收起），lg+ 常驻左栏 */}
      <div className="relative flex flex-col gap-6 lg:flex-row">
        {filtersOpen ? (
          <div
            className="fixed inset-0 z-40 bg-black/40 lg:hidden"
            aria-hidden="true"
            onClick={() => setFiltersOpen(false)}
          />
        ) : null}
        <aside
          className={`${
            filtersOpen
              ? "fixed inset-y-0 left-0 z-50 w-72 max-w-[85vw] overflow-y-auto bg-background p-4 shadow-xl"
              : "hidden"
          } shrink-0 space-y-5 lg:static lg:z-auto lg:block lg:w-[220px] lg:overflow-visible lg:bg-transparent lg:p-0 lg:shadow-none`}
        >
          <div className="flex items-center justify-between lg:hidden">
            <h2 className="text-sm font-semibold">{t("observe.filters")}</h2>
            <button
              type="button"
              onClick={() => setFiltersOpen(false)}
              aria-label={t("observe.filters")}
              className="rounded-[6px] border px-2 py-0.5 text-xs"
            >
              ×
            </button>
          </div>
          <RailSection title={ot("observe.rail.window", "Time window")}>
            <div className="grid grid-cols-4 gap-1">
              {WINDOWS.map((w) => (
                <button
                  key={w.d}
                  type="button"
                  onClick={() => setDays(w.d)}
                  aria-pressed={days === w.d}
                  className={`rounded-[6px] border px-1 py-0.5 text-xs transition-colors ${
                    days === w.d ? "bg-foreground text-background" : "hover:bg-muted/60"
                  }`}
                >
                  {w.label}
                </button>
              ))}
            </div>
          </RailSection>

          <RailSection title={ot("observe.rail.sources", "Sources")}>
            {sourcesErr ? <p className="text-xs text-red-600">{sourcesErr}</p> : null}
            {sources === null ? (
              <div className="space-y-1" aria-busy="true">
                <Skeleton className="h-5 rounded-[6px]" />
                <Skeleton className="h-5 rounded-[6px]" />
                <Skeleton className="h-5 rounded-[6px]" />
              </div>
            ) : sources.length === 0 ? (
              <p className="text-xs text-muted-foreground">{ot("observe.rail.noSources", "No registered sources.")}</p>
            ) : (
              <div className="max-h-64 space-y-0.5 overflow-y-auto pr-1">
                {tierGroups.map(([tier, rows]) => (
                  <div key={tier}>
                    <p className="mt-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                      {tier} · {rows.reduce((s, r) => s + r.n_7d, 0)}
                    </p>
                    {rows.map((s) => {
                      const on = selSources.includes(s.source_id);
                      return (
                        <label key={s.source_id} className="flex items-center gap-1.5 py-0.5 text-xs">
                          <input
                            type="checkbox"
                            checked={on}
                            onChange={() => onToggleSource(s.source_id)}
                            className="accent-foreground"
                          />
                          <span className="min-w-0 flex-1 truncate" title={s.source_id}>
                            {s.source_id}
                          </span>
                          <span className="tabular-nums text-muted-foreground" title="n_7d">
                            {s.n_7d}
                          </span>
                        </label>
                      );
                    })}
                  </div>
                ))}
              </div>
            )}
          </RailSection>

          <RailSection title={ot("observe.rail.language", "Language")}>
            <div className="space-y-0.5">
              <button
                type="button"
                onClick={() => setLang("")}
                aria-pressed={lang === ""}
                className={`flex w-full items-center gap-1.5 rounded-[6px] px-1.5 py-0.5 text-xs transition-colors ${
                  lang === "" ? "bg-muted font-medium" : "hover:bg-muted/60"
                }`}
              >
                <span className="flex-1 text-left">{ot("observe.rail.allLanguages", "All languages")}</span>
              </button>
              {langCounts.map(([code, count]) => (
                <button
                  key={code}
                  type="button"
                  onClick={() => setLang(code)}
                  aria-pressed={lang === code}
                  className={`flex w-full items-center gap-1.5 rounded-[6px] px-1.5 py-0.5 text-xs transition-colors ${
                    lang === code ? "bg-muted font-medium" : "hover:bg-muted/60"
                  }`}
                >
                  <span className="min-w-0 flex-1 truncate text-left" title={code}>
                    {langName(code)}
                  </span>
                  <span className="tabular-nums text-muted-foreground">{count}</span>
                </button>
              ))}
            </div>
          </RailSection>
        </aside>

        <div className="min-w-0 flex-1 space-y-6">
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-1.5" role="tablist" aria-label={t("observe.stage")}>
              {OBSERVE_MODES.map((m, i) => (
                <button
                  key={m}
                  type="button"
                  role="tab"
                  aria-selected={mode === m}
                  onClick={() => setMode(m)}
                  title={ot("observe.tab.kbd", "Shortcut {n}", { n: i + 1 })}
                  className={`rounded-[6px] border px-2.5 py-1 text-xs transition-colors ${
                    mode === m ? "bg-foreground text-background" : "hover:bg-muted/60"
                  }`}
                >
                  {tabLabels[m]}
                </button>
              ))}
              <span className="ml-1 flex items-center gap-1 text-xs text-muted-foreground">
                {tabLabels[mode]}
                <HelpIcon helpKey={tabHelp[mode]} />
              </span>
            </div>

            <div role="tabpanel" aria-label={tabLabels[mode]}>
              {/* P0-3 筛选诚实边界：NDI/情绪/实体端点按全量数据计算，来源/语言筛选不作用 */}
              {(mode === "divergence" || mode === "emotion" || mode === "entities") &&
              (selSourcesRaw?.length ?? 0) + (lang ? 1 : 0) > 0 ? (
                <p className="mb-3 rounded-[6px] border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
                  {ot(
                    "observe.filterScope",
                    "Source/language filters apply to Signal, Flow, Narrative, change detection and Inbox. This view is computed from the full dataset and is shown unchanged.",
                  )}
                </p>
              ) : null}
              {mode === "signal" ? (
                <HourglassPanel
                  landscape={mainData?.landscape ?? null}
                  ndi={mainData?.ndi ?? []}
                  emotion={mainData?.emotion ?? []}
                  sources={sources}
                  windowLabel={WINDOWS.find((w) => w.d === days)?.label ?? String(days)}
                  onOpenDrawer={openDrawer}
                />
              ) : null}
              {mode === "flow" ? (
                <FlowPanel landscape={mainData?.landscape ?? null} onOpenSource={openDrawer} />
              ) : null}
              {mode === "narrative" ? (
                <NarrativePanel landscape={mainData?.landscape ?? null} onOpenNarrative={openDrawer} />
              ) : null}
              {mode === "divergence" ? (
                <DivergencePanel
                  ndi={mainData?.ndi ?? []}
                  landscape={mainData?.landscape ?? null}
                  loading={mainData === null}
                  warnings={mainData?.landscape?.quality_warnings?.length ?? 0}
                  onOpenDrawer={(entity, label, ndi, nSources) =>
                    openDrawer({ kind: "entity", entity, label, ndi, nSources })
                  }
                />
              ) : null}
              {mode === "emotion" ? (
                <><EmotionPanel emotion={mainData?.emotion ?? []} loading={mainData === null} onOpenEmotion={(emotionKey, value, date) => openDrawer({ kind: "emotion", emotionKey, value, date })} /><ActionPanel days={fetchDays} /></>
              ) : null}
              {mode === "entities" ? (
                <EntitiesPanel
                  entities={entities}
                  entityErr={entityErr}
                  selEntity={selEntity}
                  timeline={timeline}
                  days={fetchDays}
                  ndi={mainData?.ndi ?? []}
                  kg={kg}
                  onOpen={openEntity}
                  onOpenDrawer={(id, label, ndi) => openDrawer({ kind: "entity", entity: id, label, ndi })}
                />
              ) : null}
              {mode === "inbox" ? (
                <InboxPanel
                  sources={sources ?? []}
                  sourcesErr={sourcesErr}
                  days={days}
                  filters={inboxFilters}
                  handlers={inboxHandlers}
                  changeId={inboxChangeId}
                  onChangeIdConsumed={() => setInboxChangeId("")}
                />
              ) : null}
            </div>
          </div>

          <footer className="rounded-[12px] border px-3 py-2 text-xs text-muted-foreground">
            {strip
              ? t("observe.monitorStrip", { total: strip.total, pending: strip.pending })
              : t("monitors.empty")}
          </footer>
        </div>
      </div>

      {/* 统一 Change Drawer（图表联动 P1）；chips=真正作用于本图数据的窗口筛选 */}
      <ChangeDrawer
        selection={drawer}
        landscape={mainData?.landscape ?? null}
        chips={
          drawer
            ? [
                {
                  label: `${ot("observe.rail.window", "Time window")}: ${
                    WINDOWS.find((w) => w.d === days)?.label ?? String(days)
                  }`,
                },
              ]
            : []
        }
        onClose={closeDrawer}
        onCreateCase={createCaseFromDrawer}
        onOpenEntityTimeline={openEntityTimeline}
      />
    </div>
  );
}
