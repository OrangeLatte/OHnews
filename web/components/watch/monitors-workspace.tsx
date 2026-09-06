"use client";

/**
 * WATCH · 跟踪预警工作区（自 app/monitors/page.tsx 原样抽入）：监测台。
 * 顶部统计 + 状态 chips 过滤 + split view（左卡片列表 j/k 键盘流，右详情面板）。
 * 三概念分离：Monitor 配置状态（active/paused，error 预留）≠ Run 状态 ≠ Update
 * 审核状态（review_status 派生键）——"待复核"只数 unreviewed updates。
 * 详情 = 元数据 + 运行时间线 + 未复核 updates（HITL 三按钮）+ confirm-snapshot + 新建入口。
 * 所有写操作走 ConfirmButton 两击确认（文案说明不可逆性，无阻塞 dialog），决策后 toast + 局部刷新。
 * 深链契约（沿袭旧 /monitors）：/watch?tab=monitors&create=1 自动开创建表单；
 * /watch?tab=monitors&open=<monitor_id> 自动选中该监测器。
 */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  objectApi,
  type CaseRow,
  type MonitorRow,
  type MonitorSchedulerRow,
  type MonitorUpdateRow,
} from "@/lib/object-api";
import { useLocale } from "@/lib/i18n/use-t";
import { Button } from "@/components/ui/button";
import { ConfirmButton } from "@/components/ui/confirm-button";
import { Skeleton, toast } from "@/components/ui/toast";
import { HelpIcon } from "@/components/help/help-icon";
import { MonitorCard, statusTone } from "@/components/monitors/monitor-card";
import { RunsTimeline, type MonitorRunRow } from "@/components/monitors/runs-timeline";
import { UpdateCard } from "@/components/monitors/update-card";
import { CreateForm } from "@/components/monitors/create-form";
import { EmptyGuide, StatCard, TONE_DOT, ToneChip, type TFunc, type Tone } from "@/components/monitors/bits";
import { absTime, nowIso, relTime } from "@/components/monitors/format";
import { useExtraT } from "@/components/monitors/i18n-extra";

type RunsState = { list: MonitorRunRow[]; unavailable: boolean };

/** Monitor 配置状态闭集（三概念分离：needs_review 是 Update 审核概念，永不入此列）。 */
const CONFIG_STATUSES = ["active", "paused", "error"] as const;

/** 调度健康三色：scheduled=绿 / no_history=琥珀 / unscheduled=红（后端口径）。 */
function schedulerTone(h: MonitorSchedulerRow["scheduler_health"]): Tone {
  if (h === "scheduled") return "ok";
  if (h === "no_history") return "warn";
  return "bad";
}

/** 待复核 = review_status 为 unreviewed 的 updates（旧后端缺省键视为 unreviewed）。 */
function unreviewedCount(list: MonitorUpdateRow[]): number {
  return list.filter((u) => (u.review_status ?? "unreviewed") === "unreviewed").length;
}

async function postJson(path: string, body: unknown): Promise<unknown> {
  const r = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    // 透传后端根因（FastAPI {"detail": ...}）；非 JSON 错误体退回状态码
    let detail = "";
    try {
      const err = (await r.json()) as { detail?: unknown };
      if (err && typeof err.detail === "string") detail = err.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail || `HTTP ${r.status}`);
  }
  return r.json();
}

function isEditableTarget(e: Event): boolean {
  const el = e.target;
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || el.isContentEditable;
}

export function MonitorsWorkspace() {
  const t: TFunc = useExtraT();
  const { locale } = useLocale();
  const lang: "en" | "zh" = locale.startsWith("zh") ? "zh" : "en";

  const [rows, setRows] = useState<MonitorRow[]>([]);
  const [pending, setPending] = useState<Record<string, MonitorUpdateRow[]>>({});
  const [cases, setCases] = useState<CaseRow[]>([]);
  const [runs, setRuns] = useState<Record<string, RunsState>>({});
  const [openId, setOpenId] = useState("");
  const [joinPick, setJoinPick] = useState<Record<string, string>>({});
  const [busyUpdate, setBusyUpdate] = useState("");
  const [snapBusy, setSnapBusy] = useState(false);
  // 调度健康小卡：sched[id] 有值=ok / schedErr[id]=加载失败 / 两者皆空=加载中。
  // 懒加载（打开详情时 fetch），失败诚实显示，不编造。
  const [sched, setSched] = useState<Record<string, MonitorSchedulerRow>>({});
  const [schedErr, setSchedErr] = useState<Record<string, boolean>>({});
  const [verdicts, setVerdicts] = useState<Record<string, Record<string, number>>>({});
  const [runBusy, setRunBusy] = useState(false);
  const [statusFilter, setStatusFilter] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [loadErr, setLoadErr] = useState("");
  const [editOpen, setEditOpen] = useState(false);
  const [editQ, setEditQ] = useState("");
  const [editW, setEditW] = useState("");
  const [editS, setEditS] = useState("");
  const [editBusy, setEditBusy] = useState(false);
  // 跳转落地：/watch?tab=monitors&create=1 自动打开创建表单（OBSERVE Drawer）；
  // /watch?tab=monitors&open=<monitor_id> 自动选中该监测器（全局搜索 monitor 结果入口，P1-A）。
  // 必须在 effect 内异步打开：惰性初始化会导致 SSR(false) 与客户端(true) 首帧
  // 不一致 → hydration mismatch；同步 setState 又违反 set-state-in-effect 规则。
  // open= 指向不存在/已删除的 id：rows.find(...) ?? null 落回详情空态（诚实忽略不崩）。
  const [createOpen, setCreateOpen] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => {
      const params = new URLSearchParams(window.location.search);
      if (params.get("create") === "1") setCreateOpen(true);
      const open = params.get("open");
      if (open) setOpenId(open);
    }, 0);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    let alive = true;
    Promise.all([
      objectApi.monitors().catch(() => null),
      objectApi.cases(undefined, true).catch(() => [] as CaseRow[]),
    ])
      .then(([monitors, caseRows]) => {
        if (!alive) return;
        if (!monitors) {
          setLoadErr(t("monitors.loadFailed"));
          setLoaded(true);
          return;
        }
        setRows(monitors);
        setCases(caseRows);
        setLoadErr("");
        return Promise.all(
          monitors.map((m) => objectApi.monitorUpdates(m.monitor_id).catch(() => [] as MonitorUpdateRow[])),
        ).then((lists) => {
          if (!alive) return;
          const map: Record<string, MonitorUpdateRow[]> = {};
          monitors.forEach((m, i) => {
            map[m.monitor_id] = lists[i];
          });
          setPending(map);
          setLoaded(true);
        });
      })
      .catch(() => {
        if (alive) {
          setLoadErr(t("monitors.loadFailed"));
          setLoaded(true);
        }
      });
    return () => {
      alive = false;
    };
  }, [t]);

  useEffect(() => {
    if (!openId || runs[openId]) return;
    let alive = true;
    fetch(`/api/monitors/${encodeURIComponent(openId)}/runs`, { cache: "no-store" })
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return (await r.json()) as MonitorRunRow[];
      })
      .then((list) => {
        if (alive) setRuns((s) => ({ ...s, [openId]: { list, unavailable: false } }));
      })
      .catch(() => {
        if (alive) setRuns((s) => ({ ...s, [openId]: { list: [], unavailable: true } }));
      });
    return () => {
      alive = false;
    };
  }, [openId, runs]);

  // 关联 Case 判断摘要懒加载（R7-3）：monitor.case_id → claims verdict 计数。
  useEffect(() => {
    if (!openId || verdicts[openId]) return;
    const mon = rows.find((r) => r.monitor_id === openId);
    if (!mon?.case_id) return;
    let alive = true;
    objectApi
      .caseDetail(mon.case_id)
      .then((d) => {
        if (!alive) return;
        const counts: Record<string, number> = {};
        for (const c of d.claims ?? []) {
          counts[c.status] = (counts[c.status] ?? 0) + 1;
        }
        setVerdicts((s) => ({ ...s, [openId]: counts }));
      })
      .catch(() => {
        if (alive) setVerdicts((s) => ({ ...s, [openId]: {} }));
      });
    return () => {
      alive = false;
    };
  }, [openId, rows, verdicts]);

  // 调度健康懒加载：打开详情时 fetch 一次；无实时 scheduler 进程由 note 诚实标注。
  useEffect(() => {
    if (!openId || sched[openId] || schedErr[openId]) return;
    let alive = true;
    objectApi
      .monitorScheduler(openId)
      .then((row) => {
        if (alive) setSched((s) => ({ ...s, [openId]: row }));
      })
      .catch(() => {
        if (alive) setSchedErr((s) => ({ ...s, [openId]: true }));
      });
    return () => {
      alive = false;
    };
  }, [openId, sched, schedErr]);

  const configStatuses = useMemo(
    () => CONFIG_STATUSES.filter((s) => rows.some((r) => r.status === s)),
    [rows],
  );
  const filtered = useMemo(
    () => (statusFilter ? rows.filter((r) => r.status === statusFilter) : rows),
    [rows, statusFilter],
  );

  const pendingTotal = useMemo(
    () => rows.reduce((acc, m) => acc + unreviewedCount(pending[m.monitor_id] ?? []), 0),
    [rows, pending],
  );
  const activeCount = rows.filter((r) => r.status === "active").length;
  const pausedCount = rows.filter((r) => r.status === "paused").length;

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.metaKey || e.ctrlKey || e.altKey || isEditableTarget(e)) return;
      if (e.key !== "j" && e.key !== "k" && e.key !== "Escape") return;
      e.preventDefault();
      if (e.key === "Escape") {
        setOpenId("");
        return;
      }
      setOpenId((cur) => {
        if (filtered.length === 0) return "";
        const idx = filtered.findIndex((m) => m.monitor_id === cur);
        const delta = e.key === "j" ? 1 : -1;
        const next = idx < 0 ? (delta > 0 ? 0 : filtered.length - 1) : (idx + delta + filtered.length) % filtered.length;
        return filtered[next].monitor_id;
      });
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [filtered]);

  const refreshOne = (monitorId: string) => {
    objectApi
      .monitorUpdates(monitorId)
      .then((list) => setPending((p) => ({ ...p, [monitorId]: list })))
      .catch(() => toast.error(t("monitors.loadFailed")));
  };

  const handleCreated = (monitorId: string) => {
    setCreateOpen(false);
    setOpenId(monitorId);
    objectApi
      .monitors()
      .then((list) => setRows(list))
      .catch(() => toast.error(t("monitors.loadFailed")));
  };

  const openEdit = (m: MonitorRow) => {
    setEditQ(m.question);
    setEditW(m.window);
    setEditS(m.schedule);
    setEditOpen(true);
  };

  const saveEdit = () => {
    if (!open || editBusy) return;
    const patch: { question?: string; window?: string; schedule?: string } = {};
    if (editQ.trim() && editQ !== open.question) patch.question = editQ.trim();
    if (editW.trim() && editW !== open.window) patch.window = editW.trim();
    if (editS.trim() && editS !== open.schedule) patch.schedule = editS.trim();
    if (Object.keys(patch).length === 0) {
      setEditOpen(false);
      return;
    }
    setEditBusy(true);
    objectApi
      .patchMonitor(open.monitor_id, patch)
      .then((r) => {
        setEditOpen(false);
        setRows((prev) =>
          prev.map((m) =>
            m.monitor_id === r.monitor_id
              ? {
                  ...m,
                  ...(patch.question !== undefined ? { question: patch.question } : {}),
                  ...(patch.window !== undefined ? { window: patch.window } : {}),
                  ...(patch.schedule !== undefined ? { schedule: patch.schedule } : {}),
                }
              : m,
          ),
        );
        toast.success(`${t("monitors.saved")}: ${r.updated.join(", ")}`);
      })
      .catch(() => toast.error(t("monitors.decisionFailed")))
      .finally(() => setEditBusy(false));
  };

  const deleteMonitorRow = (m: MonitorRow) => {
    objectApi
      .deleteMonitor(m.monitor_id)
      .then(() => {
        setOpenId((cur) => (cur === m.monitor_id ? "" : cur));
        setRows((prev) => prev.filter((x) => x.monitor_id !== m.monitor_id));
        toast.success(t("monitors.deleted"));
      })
      .catch(() => toast.error(t("monitors.decisionFailed")));
  };

  const decide = (u: MonitorUpdateRow, decision: "new_case" | "join_case" | "ignore") => {
    if (decision === "join_case" && !joinPick[u.update_id]) {
      toast.error(t("monitors.pickCaseFirst"));
      return;
    }
    const monitor = rows.find((m) => m.monitor_id === u.monitor_id);
    setBusyUpdate(u.update_id);
    objectApi
      .reviewUpdate(u.update_id, {
        decision,
        ...(decision === "join_case" ? { case_id: joinPick[u.update_id] } : {}),
      })
      .then((r) => {
        if (r.decision === "new_case") {
          toast.success(`${t("monitors.caseCreated")}: ${r.case_id}`);
          if (monitor) {
            setCases((cs) => [
              {
                case_id: r.case_id,
                question: monitor.question,
                status: "open",
                origin: "watch_candidate",
                context_note: "",
                created_at: nowIso(),
                updated_at: nowIso(),
              },
              ...cs,
            ]);
          }
        } else if (r.decision === "join_case") {
          toast.success(`${t("monitors.joinedToast")}: ${r.case_id}`);
        } else {
          toast.info(t("monitors.ignoredToast"));
        }
        setBusyUpdate("");
        refreshOne(u.monitor_id);
      })
      .catch(() => {
        setBusyUpdate("");
        toast.error(t("monitors.decisionFailed"));
      });
  };

  const confirmSnapshot = (m: MonitorRow) => {
    setSnapBusy(true);
    postJson(`/monitors/${encodeURIComponent(m.monitor_id)}/confirm-snapshot`, { snapshot_at: nowIso() })
      .then((out) => {
        const at =
          out && typeof out === "object" && "confirmed_at" in out
            ? String((out as { confirmed_at: unknown }).confirmed_at)
            : nowIso();
        setRows((rs) => rs.map((r) => (r.monitor_id === m.monitor_id ? { ...r, last_confirmed_snapshot_at: at } : r)));
        setSnapBusy(false);
        toast.success(t("monitors.snapshotConfirmed"));
      })
      .catch((e: unknown) => {
        setSnapBusy(false);
        // 后端 422（无成功运行结果不可确认快照）等根因如实透出
        const reason = e instanceof Error ? e.message : String(e);
        toast.error(reason ? `${t("monitors.confirmFailed")}: ${reason}` : t("monitors.decisionFailed"));
      });
  };

  /** 登记一次监测运行（HITL confirm）：成功 toast + 刷新 runs 时间线与调度小卡；失败 toast 带根因。 */
  const runNow = (m: MonitorRow) => {
    if (runBusy) return;
    setRunBusy(true);
    const busyTimer = window.setTimeout(() => setRunBusy(false), 12000);
    objectApi
      .runMonitorNow(m.monitor_id)
      .then((r) => {
        window.clearTimeout(busyTimer);
        setRunBusy(false);
        toast.success(`${t("monitors.runNowOk")}: ${r.run_id}`);
        fetch(`/api/monitors/${encodeURIComponent(m.monitor_id)}/runs`, { cache: "no-store" })
          .then(async (res) => {
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return (await res.json()) as MonitorRunRow[];
          })
          .then((list) => setRuns((s) => ({ ...s, [m.monitor_id]: { list, unavailable: false } })))
          .catch(() => setRuns((s) => ({ ...s, [m.monitor_id]: { list: [], unavailable: true } })));
        // last_run 变化 → 丢弃调度小卡缓存，触发懒加载 effect 重取。
        setSched((s) => {
          const next = { ...s };
          delete next[m.monitor_id];
          return next;
        });
        setSchedErr((s) => {
          const next = { ...s };
          delete next[m.monitor_id];
          return next;
        });
      })
      .catch((e: unknown) => {
        window.clearTimeout(busyTimer);
        setRunBusy(false);
        const reason = e instanceof Error ? e.message : String(e);
        toast.error(reason ? `${t("monitors.runNowFailed")}: ${reason}` : t("monitors.runNowFailed"));
      });
  };

  const open = rows.find((m) => m.monitor_id === openId) ?? null;
  const openUpdates = open ? (pending[open.monitor_id] ?? []) : [];
  const schedRow = open ? (sched[open.monitor_id] ?? null) : null;
  const schedFailed = open ? (schedErr[open.monitor_id] ?? false) : false;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">{t("monitors.consoleTitle")}</h1>
          <p className="mt-0.5 max-w-2xl text-[13px] text-muted-foreground">{t("monitors.consoleSub")}</p>
        </div>
        <HelpIcon helpKey="agent.hitl" />
      </header>

      <section className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4" aria-label="monitor stats">
        <StatCard label={t("monitors.statTotal")} value={rows.length} tone="info" />
        <StatCard label={t("monitors.statPending")} value={pendingTotal} tone={pendingTotal > 0 ? "warn" : "ok"} />
        <StatCard label={t("monitors.statActive")} value={activeCount} tone="ok" />
        <StatCard label={t("monitors.statPaused")} value={pausedCount} tone="idle" />
      </section>

      <div className="flex flex-wrap items-center gap-1.5" role="tablist" aria-label="status filter">
        <button
          type="button"
          role="tab"
          aria-selected={statusFilter === ""}
          className={`rounded-md border px-2 py-1 text-xs hover:bg-accent ${statusFilter === "" ? "bg-accent font-medium" : ""}`}
          onClick={() => setStatusFilter("")}
        >
          {t("monitors.filterAll")} · {rows.length}
        </button>
        {configStatuses.map((s) => (
          <button
            key={s}
            type="button"
            role="tab"
            aria-selected={statusFilter === s}
            className={`rounded-md border px-2 py-1 text-xs hover:bg-accent ${statusFilter === s ? "bg-accent font-medium" : ""}`}
            onClick={() => setStatusFilter(s)}
          >
            <span className="inline-flex items-center gap-1">
              <span className={`inline-block h-1.5 w-1.5 rounded-full ${TONE_DOT[statusTone(s)]}`} />
              {s} · {rows.filter((r) => r.status === s).length}
            </span>
          </button>
        ))}
        <Button
          size="sm"
          className="ml-auto"
          onClick={() => setCreateOpen((v) => !v)}
          aria-expanded={createOpen}
        >
          + {t("monitors.create.open")}
        </Button>
      </div>

      {createOpen && (
        <CreateForm t={t} onCreated={handleCreated} onClose={() => setCreateOpen(false)} />
      )}

      {loadErr && <p className="text-xs text-destructive">{loadErr}</p>}

      {!loaded ? (
        <div className="space-y-2" aria-hidden="true">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <EmptyGuide
          title={t("monitors.emptyTitle")}
          body={t("monitors.emptyBody")}
          action={
            <Link
              href="/watch?tab=sources"
              className="rounded-md border px-3 py-1.5 text-[13px] font-medium hover:bg-accent"
            >
              {t("monitors.goSources")}
            </Link>
          }
        />
      ) : (
        <div className="grid items-start gap-4 lg:grid-cols-[minmax(320px,380px)_1fr]">
          <ul className="space-y-2" aria-label="monitor list">
            {filtered.map((m) => (
              <li key={m.monitor_id}>
                <MonitorCard
                  m={m}
                  pending={unreviewedCount(pending[m.monitor_id] ?? [])}
                  selected={openId === m.monitor_id}
                  onSelect={setOpenId}
                  t={t}
                  lang={lang}
                />
              </li>
            ))}
            {filtered.length === 0 && (
              <li className="rounded-xl border border-dashed p-4 text-center text-[13px] text-muted-foreground">
                {t("monitors.filterAll")}: 0
              </li>
            )}
          </ul>

          <section
            className="rounded-xl border bg-card p-4 lg:sticky lg:top-4"
            aria-label={t("monitors.detailTitle")}
          >
            {!open ? (
              <EmptyGuide title={t("monitors.detailTitle")} body={t("monitors.detailHint")} />
            ) : (
              <div className="space-y-5">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-sm font-semibold">{t("monitors.detailTitle")}</h2>
                    <span className="font-mono text-xs text-muted-foreground">{open.monitor_id}</span>
                    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                      <span
                        className={`inline-block h-2 w-2 rounded-full ${TONE_DOT[statusTone(open.status)]}`}
                      />
                      {open.status}
                    </span>
                    <span className="ml-auto flex gap-1">
                      {!editOpen && (
                        <button
                          type="button"
                          onClick={() => openEdit(open)}
                          className="rounded-md border px-2 py-0.5 text-xs hover:bg-accent"
                        >
                          {t("monitors.edit")}
                        </button>
                      )}
                      <ConfirmButton
                        onConfirm={() => deleteMonitorRow(open)}
                        confirmLabel={t("monitors.confirmDelete").replace("{id}", open.monitor_id)}
                        className="rounded-md border border-[#dc2626]/40 px-2 py-0.5 text-xs text-[#dc2626] hover:bg-[#fee2e2]"
                        armedClassName="bg-[#dc2626] text-white hover:bg-[#b91c1c]"
                      >
                        {t("monitors.deleteBtn")}
                      </ConfirmButton>
                    </span>
                  </div>
                  {editOpen ? (
                    <div className="mt-2 space-y-2 rounded-lg border bg-muted/40 p-3">
                      <label className="block text-xs text-muted-foreground">
                        {t("monitors.question")}
                        <input
                          value={editQ}
                          onChange={(e) => setEditQ(e.target.value)}
                          className="mt-1 w-full rounded-md border bg-card px-2 py-1 text-[13px] text-foreground"
                        />
                      </label>
                      <div className="flex gap-2">
                        <label className="block flex-1 text-xs text-muted-foreground">
                          {t("monitors.window")}
                          <input
                            value={editW}
                            onChange={(e) => setEditW(e.target.value)}
                            className="mt-1 w-full rounded-md border bg-card px-2 py-1 text-[13px] text-foreground"
                          />
                        </label>
                        <label className="block flex-1 text-xs text-muted-foreground">
                          {t("monitors.schedule")}
                          <input
                            value={editS}
                            onChange={(e) => setEditS(e.target.value)}
                            className="mt-1 w-full rounded-md border bg-card px-2 py-1 text-[13px] text-foreground"
                          />
                        </label>
                      </div>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          disabled={editBusy}
                          onClick={saveEdit}
                          className="rounded-md bg-[#16a34a] px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
                        >
                          {t("monitors.save")}
                        </button>
                        <button
                          type="button"
                          onClick={() => setEditOpen(false)}
                          className="rounded-md border px-3 py-1 text-xs hover:bg-accent"
                        >
                          {t("monitors.cancel")}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <p className="mt-1 text-[13px] leading-relaxed">{open.question}</p>
                  )}
                  <dl className="mt-2 grid gap-x-4 gap-y-1 text-xs text-muted-foreground sm:grid-cols-2">
                    <div className="flex min-w-0 gap-1">
                      <dt className="shrink-0">{t("monitors.target")}:</dt>
                      <dd className="truncate font-mono" title={open.target_ref}>
                        {open.target_type}:{open.target_ref}
                      </dd>
                    </div>
                    <div className="flex gap-1">
                      <dt className="shrink-0">{t("monitors.window")}:</dt>
                      <dd>
                        {open.window} / {open.schedule}
                      </dd>
                    </div>
                    <div className="flex gap-1">
                      <dt className="shrink-0">{t("monitors.notify")}:</dt>
                      <dd>{open.notification}</dd>
                    </div>
                    <div className="flex gap-1">
                      <dt className="shrink-0">{t("monitors.createdBy")}:</dt>
                      <dd>{open.created_by}</dd>
                    </div>
                    <div className="flex gap-1">
                      <dt className="shrink-0">{t("monitors.lastSnapshot")}:</dt>
                      <dd>{relTime(open.last_confirmed_snapshot_at, lang)}</dd>
                    </div>
                    {open.case_id && (
                      <div className="flex gap-1">
                        <dt className="shrink-0">{t("monitors.linkedCase")}:</dt>
                        <dd className="truncate">
                          <Link href={`/cases/${encodeURIComponent(open.case_id)}`} className="underline hover:text-foreground">
                            {open.case_id}
                          </Link>
                        </dd>
                      </div>
                    )}
                  </dl>
                  {open.trigger_conditions.length > 0 && (
                    <p className="mt-2 text-xs text-muted-foreground">
                      {t("monitors.triggers")}: {open.trigger_conditions.join(" · ")}
                    </p>
                  )}
                   {/* 关联 Case 判断摘要（R7-3）：监控增量可能影响已有判断 → Review Judgment */}
                   {open.case_id && verdicts[openId] ? (
                     Object.keys(verdicts[openId]).length > 0 ? (
                       <div className="mt-3 rounded-lg border border-amber-500/40 bg-amber-50/50 p-2.5 text-xs dark:bg-amber-950/20">
                         <div className="flex flex-wrap items-center gap-1.5">
                           <h4 className="font-semibold">{t("monitors.reviewJudgment")}</h4>
                           {Object.entries(verdicts[openId]).map(([s, n]) => (
                             <span key={s} className="rounded bg-background px-1.5 py-0.5 font-mono">
                               {t(`case.claimStatus.${s}`)} {n}
                             </span>
                           ))}
                         </div>
                         <p className="mt-1 text-muted-foreground">
                           {t("monitors.reviewJudgmentHint")}{" "}
                           <Link
                             href={`/cases/${encodeURIComponent(open.case_id)}?mode=history`}
                             className="underline"
                           >
                             {t("monitors.linkedCase")}
                           </Link>
                         </p>
                       </div>
                     ) : null
                   ) : null}
                   {/* 调度健康小卡（懒加载；失败诚实显示，不编造） */}
                   <div className="mt-3 rounded-lg border bg-muted/30 p-2.5">
                     <div className="flex flex-wrap items-center gap-2">
                      <h4 className="text-xs font-semibold">{t("monitors.scheduler.title")}</h4>
                      {schedFailed ? (
                        <span className="text-xs text-amber-700 dark:text-amber-400">
                          {t("monitors.scheduler.loadFailed")}
                        </span>
                      ) : schedRow ? (
                        <ToneChip tone={schedulerTone(schedRow.scheduler_health)}>
                          {t(`monitors.scheduler.${schedRow.scheduler_health}`)}
                        </ToneChip>
                      ) : (
                        <span className="text-xs text-muted-foreground">{t("common.loading")}</span>
                      )}
                      {schedRow && (
                        <span className="ml-auto font-mono text-xs text-muted-foreground">
                          ⏱ {schedRow.schedule}
                        </span>
                      )}
                    </div>
                    {schedRow && (
                      <>
                        <p className="mt-1.5 flex flex-wrap gap-x-3 text-xs text-muted-foreground">
                          <span>
                            {t("monitors.started")}: {relTime(schedRow.last_run?.started_at ?? null, lang)}
                          </span>
                          <span>
                            {t("monitors.scheduler.nextRun")}:{" "}
                            {schedRow.next_run_estimate ? absTime(schedRow.next_run_estimate, lang) : "—"}
                          </span>
                        </p>
                        <p className="mt-1 text-[11px] text-muted-foreground">{schedRow.note}</p>
                      </>
                    )}
                  </div>
                </div>

                <div>
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="text-sm font-semibold">{t("monitors.runs")}</h3>
                    <span className="flex gap-1">
                      <ConfirmButton
                        onConfirm={() => runNow(open)}
                        confirmLabel={t("monitors.runNowConfirm")}
                        disabled={runBusy}
                        className="inline-flex h-8 items-center justify-center gap-1.5 whitespace-nowrap rounded-md border px-3 text-xs font-medium hover:bg-accent"
                        armedClassName="bg-amber-600 text-white hover:bg-amber-700"
                      >
                        {t("monitors.runNow")}
                      </ConfirmButton>
                      <ConfirmButton
                        onConfirm={() => confirmSnapshot(open)}
                        confirmLabel={t("monitors.confirmSnapshotAsk")}
                        disabled={snapBusy}
                        className="inline-flex h-8 items-center justify-center gap-1.5 whitespace-nowrap rounded-md border px-3 text-xs font-medium hover:bg-accent"
                        armedClassName="bg-amber-600 text-white hover:bg-amber-700"
                        title={t("monitors.confirmSnapshot")}
                      >
                        {t("monitors.confirmSnapshot")}
                      </ConfirmButton>
                    </span>
                  </div>
                  <div className="mt-2">
                    <RunsTimeline
                      runs={runs[open.monitor_id]?.list ?? []}
                      unavailable={runs[open.monitor_id]?.unavailable ?? false}
                      t={t}
                      lang={lang}
                    />
                  </div>
                </div>

                <div>
                  <h3 className="text-sm font-semibold">
                    {t("monitors.pendingUpdates")} ({openUpdates.length})
                  </h3>
                  <ul className="mt-2 space-y-2">
                    {openUpdates.map((u) => (
                      <UpdateCard
                        key={u.update_id}
                        u={u}
                        cases={cases}
                        joinCaseId={joinPick[u.update_id] ?? ""}
                        onJoinCaseChange={(uid, cid) => setJoinPick((p) => ({ ...p, [uid]: cid }))}
                        onDecide={decide}
                        busy={busyUpdate === u.update_id}
                        t={t}
                        lang={lang}
                      />
                    ))}
                    {openUpdates.length === 0 && (
                      <li className="rounded-lg bg-[#dcfce7]/60 px-3 py-2 text-xs text-[#15803d] dark:bg-[#16a34a]/10 dark:text-[#4ade80]">
                        {t("monitors.noPending")}
                      </li>
                    )}
                  </ul>
                </div>
              </div>
            )}
          </section>
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        j / k · Esc — <HelpIcon helpKey="state.needsConfirm" />
      </p>
    </div>
  );
}
