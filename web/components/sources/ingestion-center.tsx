"use client";

import { useEffect, useRef, useState } from "react";
import type { SourceRow } from "@/lib/landscape-api";
import { useLocale } from "@/lib/i18n/use-t";

type Kind = "collect" | "analyze" | "collect_analyze";
type Payload = { kind: Kind; source_ids: string[]; days: number };
type Detail = { source_id?: string; stage?: string; ok: boolean; written?: number; fetched?: number;
  error?: string; documents?: number; annotated?: number; events?: number; ndi_points?: number; note?: string };
type Job = { id: string; payload: Payload; status: string; stage: string; done: number; total: number;
  details: Detail[]; error: string; created_at: number; finished_at: number | null; origin: string };
type SchedulePayload = Payload & { enabled: boolean; interval_hours: number };
type Snapshot = { jobs: Job[]; worker_online: boolean; last_success: Record<string, number>;
  schedule: { payload: SchedulePayload; next_run: number | null } | null };

async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(`/api/ingestion/${path}`, { method, cache: "no-store",
    headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail : `HTTP ${response.status}`);
  if (!data) throw new Error("Invalid server response");
  return data as T;
}

/** Shared, durable collection/analysis controls for Inbox and WATCH. */
export function IngestionCenter({ sources, onComplete }: { sources: SourceRow[]; onComplete?: () => void }) {
  const { locale } = useLocale();
  const zh = locale.startsWith("zh") || locale === "yue";
  const text = (cn: string, en: string) => zh ? cn : en;
  const [data, setData] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [days, setDays] = useState(1);
  const [interval, setIntervalHours] = useState(24);
  const [scheduleKind, setScheduleKind] = useState<Kind>("collect_analyze");
  const initialized = useRef(false);
  const seen = useRef<Map<string, string>>(new Map());
  const complete = useRef(onComplete);
  useEffect(() => { complete.current = onComplete; }, [onComplete]);
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    const poll = async () => {
      try {
        const response = await fetch("/api/ingestion/status", { cache: "no-store", signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const next = await response.json() as Snapshot;
        if (!Array.isArray(next.jobs)) throw new Error("Invalid status response");
        if (disposed) return;
        for (const job of next.jobs) {
          const previous = seen.current.get(job.id);
          if ((previous ? ["queued", "running"].includes(previous) : initialized.current) && !["queued", "running"].includes(job.status)) {
            complete.current?.();
            setNotice(zh ? `任务已结束：${job.status === "succeeded" ? "成功" : "有失败，请展开运行记录查看明细"}` : `Job finished: ${job.status}. Expand run history for details.`);
          }
          seen.current.set(job.id, job.status);
        }
        if (!initialized.current) {
          if (next.schedule) {
            setSelected(next.schedule.payload.source_ids);
            setDays(next.schedule.payload.days);
            setIntervalHours(next.schedule.payload.interval_hours);
            setScheduleKind(next.schedule.payload.kind);
          }
          initialized.current = true;
        }
        setData(next);
        setError("");
      } catch (e) {
        if (!disposed) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!disposed) timer = setTimeout(poll, 2000);
      }
    };
    void poll();
    return () => { disposed = true; controller.abort(); clearTimeout(timer); };
  }, [zh]);

  const active = data?.jobs.find(j => ["queued", "running"].includes(j.status));
  const enabledSources = sources.filter(s => s.enabled);
  const sourceIds = selected.filter(id => enabledSources.some(s => s.source_id === id));
  const date = (ts?: number | null) => ts ? new Date(ts * 1000).toLocaleString() : text("尚无记录", "Not yet");
  const name = (kind: Kind) => ({ collect: text("采集", "Collection"), analyze: text("分析", "Analysis"), collect_analyze: text("采集后分析", "Collect then analyze") })[kind];
  const stateName = (state: string) => ({ queued: text("排队中", "Queued"), running: text("运行中", "Running"),
    succeeded: text("成功", "Succeeded"), partial: text("部分失败", "Partial failure"), failed: text("失败", "Failed") })[state] ?? state;
  const stageName = (stage: string) => stage.startsWith("collect:") ? `${name("collect")} · ${stage.slice(8)}` :
    ({ queued: text("等待执行", "Waiting"), scan: text("扫描窗口内文章", "Scanning articles"), annotations: text("情绪与动作标注", "Semantic annotations"),
      events_ndi: text("事件聚合与 NDI 计算", "Events and NDI"), finished: text("已结束", "Finished") })[stage] ?? stage;
  const run = async (payload: Payload) => {
    setBusy(true); setActionError(""); setNotice("");
    try {
      const job = await request<Job>("jobs", "POST", payload);
      seen.current.set(job.id, job.status);
      setData(previous => previous ? { ...previous, jobs: [job, ...previous.jobs] } : previous);
      setNotice(text("任务已提交，关闭页面不会中断。", "Job submitted; closing this page will not interrupt it."));
    } catch (e) { setActionError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const saveSchedule = async (enabled: boolean) => {
    setBusy(true); setActionError(""); setNotice("");
    try {
      const payload = !enabled && data?.schedule ? { ...data.schedule.payload, enabled: false } :
        { kind: scheduleKind, source_ids: sourceIds, days, interval_hours: interval, enabled };
      const schedule = await request<Snapshot["schedule"]>("schedule", "PUT", payload);
      setData(previous => previous ? { ...previous, schedule } : previous);
      setNotice(enabled ? text("定时任务已保存并启用。", "Schedule saved and enabled.") : text("定时任务已暂停；当前任务不受影响。", "Schedule paused; the current job is unaffected."));
    } catch (e) { setActionError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const blocked = busy || !!active || !!error || !data?.worker_online;
  const button = "rounded-md border px-3 py-1.5 text-sm hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed";
  return <section aria-label={text("采集与分析运行中心", "Collection and analysis center")} className="rounded-xl border bg-muted/10 p-4 space-y-3">
    <header className="flex flex-wrap items-center justify-between gap-2">
      <h2 className="font-semibold">{text("更新收件箱", "Update Inbox")}</h2>
      <span className="text-xs">{error ? text("状态同步失败", "Status unavailable") : !data ? text("正在连接…", "Connecting…") : data.worker_online ? text("后台执行器在线", "Worker online") : text("后台执行器离线，无法启动任务", "Worker offline; jobs cannot start")}</span>
    </header>
    <p className="text-xs text-muted-foreground">{text("采集将新闻写入收件箱；运行分析处理当前时间窗口内的全部信源，执行词典标注、事件聚合与描述性 NDI，不调用付费模型、不自动归档报告。", "Collection adds articles to Inbox. Analysis processes all sources in the selected window: lexicon annotations, event grouping and descriptive NDI. No paid model calls or report archiving.")}</p>
    <div className="flex flex-wrap items-center gap-3">
      <label className="text-sm">{text("处理窗口", "Window")} <select aria-label={text("处理窗口", "Window")} value={days} onChange={e => setDays(Number(e.target.value))} className="rounded border bg-background p-1">
        {[1, 7, 30].map(d => <option key={d} value={d}>{d}d</option>)}
      </select></label>
      <span className="text-xs">{text("已选信源", "Selected sources")}: {sourceIds.length}</span>
      <button className={button} disabled={blocked || !sourceIds.length} onClick={() => void run({ kind: "collect", source_ids: sourceIds, days })}>{text("立即采集", "Collect now")}</button>
      <button className={button} disabled={blocked} onClick={() => void run({ kind: "analyze", source_ids: [], days })}>{text("运行分析", "Run analysis")}</button>
    </div>
    <details className="text-sm"><summary className="cursor-pointer">{text("选择采集信源与定时设置", "Select sources and configure schedule")}</summary>
      <div className="mt-3 space-y-3">
        <div className="flex gap-3"><button className={button} onClick={() => setSelected(enabledSources.map(s => s.source_id))}>{text("全选已启用信源", "Select all enabled")}</button><button className={button} onClick={() => setSelected([])}>{text("清空", "Clear")}</button></div>
        <div className="max-h-48 overflow-auto grid gap-2 sm:grid-cols-2 lg:grid-cols-3 rounded border p-2">
          {enabledSources.length === 0 ? <p>{text("无可用的已启用信源，请先在 WATCH 配置。", "No enabled sources; configure them in WATCH first.")}</p> : enabledSources.map(s => <label key={s.source_id} className="flex items-center gap-2 min-w-0"><input type="checkbox" checked={sourceIds.includes(s.source_id)} onChange={e => setSelected(prev => e.target.checked ? [...prev, s.source_id] : prev.filter(id => id !== s.source_id))} /><span className="truncate" title={s.source_id}>{s.source_id}</span></label>)}
        </div>
        <div className="flex flex-wrap gap-3 items-center">
          <label>{text("周期", "Interval")} <select className="border rounded bg-background p-1" value={interval} onChange={e => setIntervalHours(Number(e.target.value))}>{[1, 6, 12, 24].map(h => <option key={h} value={h}>{h}h</option>)}</select></label>
          <label>{text("执行内容", "Operation")} <select className="border rounded bg-background p-1" value={scheduleKind} onChange={e => setScheduleKind(e.target.value as Kind)}>{(["collect", "analyze", "collect_analyze"] as Kind[]).map(k => <option key={k} value={k}>{name(k)}</option>)}</select></label>
          <button className={button} disabled={busy || !data || !!error || (scheduleKind !== "analyze" && !sourceIds.length)} onClick={() => void saveSchedule(true)}>{text("保存并启用定时", "Save and enable schedule")}</button>
          <button className={button} disabled={busy || !data?.schedule?.payload.enabled || !!error} onClick={() => void saveSchedule(false)}>{text("暂停定时", "Pause schedule")}</button>
        </div>
        <p className="text-xs text-muted-foreground">{text("依赖 API 服务持续运行。停机期间不执行；恢复后仅补一次，不重复积压任务。新设置不会中断当前任务。", "Requires the API service to remain running. After downtime, missed intervals coalesce into one run. Changes do not interrupt an active job.")}</p>
      </div>
    </details>
    <div className="text-xs space-y-1">
      <p>{text("最近成功采集", "Last successful collection")}: {date(Math.max(data?.last_success.collect ?? 0, data?.last_success.collect_analyze ?? 0))} · {text("最近成功分析", "Last successful analysis")}: {date(Math.max(data?.last_success.analyze ?? 0, data?.last_success.collect_analyze ?? 0))}</p>
      <p>{text("定时状态", "Schedule")}: {data?.schedule?.payload.enabled ? `${name(data.schedule.payload.kind)} · ${data.schedule.payload.interval_hours}h · ${text("下次计划时间", "Next scheduled time")}: ${date(data.schedule.next_run)}${!data.worker_online ? text("（执行器离线，等待恢复）", " (worker offline)") : ""}` : text("未启用", "Disabled")}</p>
    </div>
    {error || actionError ? <p role="alert" className="text-sm text-red-600">{error || actionError}</p> : null}
    {notice ? <p role="status" className="text-sm">{notice}</p> : null}
    {active ? <div role="status" className="rounded border p-3 text-sm space-y-2"><p>{name(active.payload.kind)} · {stateName(active.status)} · {stageName(active.stage)}</p>{active.total > 0 ? <><progress className="w-full" max={active.total} value={active.done} aria-label={stageName(active.stage)} /><p>{active.done} / {active.total} {text("（当前阶段）", "(current stage)")}</p></> : <p>{text("本阶段无预估百分比，等待真实处理结果。", "No estimated percentage for this stage; awaiting actual results.")}</p>}</div> : null}
    <details><summary className="cursor-pointer text-sm">{text("运行记录与失败明细", "Run history and failure details")} ({data?.jobs.length ?? 0})</summary>
      <div className="mt-2 space-y-2 max-h-96 overflow-auto">{data?.jobs.length === 0 ? <p className="text-sm">{text("暂无运行记录", "No runs yet")}</p> : data?.jobs.map(job => <details key={job.id} className="rounded border p-3 text-xs" open={job.status === "failed" || job.status === "partial"}>
        <summary className="cursor-pointer">{date(job.created_at)} · {name(job.payload.kind)} · {stateName(job.status)} · {job.origin === "scheduled" ? text("定时", "Scheduled") : text("手动", "Manual")}</summary>
        <p className="mt-2 break-all">{job.id} · {job.payload.days}d · {stageName(job.stage)}</p>
        {job.error ? <p className="text-red-600">{job.error}</p> : null}
        {job.details.map((detail, index) => <p key={index} className={`mt-1 ${detail.ok ? "" : "text-red-600"}`}>{detail.source_id ?? stageName(detail.stage ?? "")} · {detail.ok ? text("成功", "OK") : text("失败", "Failed")}{detail.written !== undefined ? ` · ${text("获取/新增", "Fetched/new")}: ${detail.fetched ?? 0}/${detail.written}` : ""}{detail.annotated !== undefined ? ` · ${text("已标注/文章", "Annotated/articles")}: ${detail.annotated}/${detail.documents}` : ""}{detail.events !== undefined ? ` · ${text("合格事件/NDI 点", "Events/NDI points")}: ${detail.events}/${detail.ndi_points}` : ""}{detail.note === "no_qualifying_events" ? ` · ${text("无合格事件，不生成指标", "No qualifying events; no metrics generated")}` : ""}{detail.error ? ` · ${detail.error}` : ""}</p>)}
        {["partial", "failed"].includes(job.status) ? <button className={`${button} mt-2`} disabled={blocked} onClick={() => {
          const failed = job.details.filter(d => d.source_id && !d.ok).map(d => d.source_id!);
          void run(failed.length && job.status === "partial" ? { ...job.payload, kind: "collect", source_ids: failed } : job.payload);
        }}>{text("重试失败任务（仅失败信源优先）", "Retry failure (failed sources first)")}</button> : null}
      </details>)}</div>
    </details>
  </section>;
}
