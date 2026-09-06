"use client";

/**
 * 04/05/06 三空间新增文案的过渡层：
 * dictionaries.ts 暂未收录这些键，此处提供 en|zh fallback；
 * 键正式迁入 dictionaries.ts 后自动失效（useT 命中优先）。
 * 键清单见交付报告（key = en | zh）。
 */

import { useCallback } from "react";
import { useLocale, useT } from "@/lib/i18n/use-t";

type Pair = { en: string; zh: string };

export const EXTRA: Record<string, Pair> = {
  // ── monitors ──
  "monitors.consoleTitle": { en: "Monitors console", zh: "监测台" },
  "monitors.consoleSub": {
    en: "Watches produce incremental updates; every update waits for your decision — new candidate Case, join an existing Case, or ignore. Decisions are logged.",
    zh: "监测器持续产生增量更新；每条更新都等待你的决策——建候选 Case、加入已有 Case 或忽略，决策即留痕。",
  },
  "monitors.statTotal": { en: "Monitors", zh: "监测器" },
  "monitors.statPending": { en: "Pending review", zh: "待复核" },
  "monitors.statActive": { en: "Active", zh: "活跃" },
  "monitors.statPaused": { en: "Paused", zh: "暂停" },
  "monitors.filterAll": { en: "All", zh: "全部" },
  "monitors.target": { en: "Target", zh: "监测对象" },
  "monitors.window": { en: "Window", zh: "窗口" },
  "monitors.schedule": { en: "Schedule", zh: "调度" },
  "monitors.notify": { en: "Notify", zh: "通知" },
  "monitors.createdBy": { en: "By", zh: "创建者" },
  "monitors.created": { en: "Created", zh: "创建于" },
  "monitors.linkedCase": { en: "Linked Case", zh: "关联 Case" },
  "monitors.detailTitle": { en: "Monitor detail", zh: "监测器详情" },
  "monitors.detailHint": {
    en: "Select a monitor (click or j / k) to see its run timeline and decide pending updates.",
    zh: "选择一个监测器（点击或 j / k 键）查看运行时间线并处理待复核更新。",
  },
  "monitors.runs": { en: "Run timeline", zh: "运行时间线" },
  "monitors.runsUnavailable": {
    en: "Backend gap: GET /monitors/{id}/runs is not implemented yet.",
    zh: "后端缺口：GET /monitors/{id}/runs 尚未实现。",
  },
  "monitors.runEmpty": { en: "No runs recorded yet.", zh: "暂无运行记录。" },
  "monitors.started": { en: "Started", zh: "开始于" },
  "monitors.finished": { en: "Finished", zh: "结束于" },
  "monitors.delta": { en: "Delta", zh: "变化" },
  "monitors.evidence": { en: "Evidence refs", zh: "证据引用" },
  "monitors.confirmSnapshot": { en: "Confirm snapshot", zh: "确认快照" },
  "monitors.confirmSnapshotAsk": {
    en: "Stamp this monitor's confirmed snapshot at the current time? The stamp is written once and cannot be undone.",
    zh: "将当前时刻写入该监测器的已确认快照？快照时间一经写入不可撤销。",
  },
  "monitors.snapshotConfirmed": { en: "Snapshot confirmed.", zh: "快照已确认。" },
  "monitors.confirmNewCase": {
    en: "Create a new candidate Case from this update and mark it reviewed? The Case reuses the monitor's question. This cannot be undone.",
    zh: "基于该更新创建候选 Case 并标记为已复核？Case 将沿用监测器的问题。操作不可撤销。",
  },
  "monitors.confirmJoinCase": {
    en: "Join this update into the selected Case and mark it reviewed? This cannot be undone.",
    zh: "将该更新并入所选 Case 并标记为已复核？操作不可撤销。",
  },
  "monitors.confirmIgnore": {
    en: "Ignore this update? It will be marked reviewed and will never appear again. This cannot be undone.",
    zh: "忽略该更新？它将被标记为已复核且不再出现。操作不可撤销。",
  },
  "monitors.ignoredToast": { en: "Update ignored.", zh: "已忽略该更新。" },
  "monitors.joinedToast": { en: "Update joined into Case", zh: "更新已并入 Case" },
  "monitors.decisionFailed": { en: "Decision failed — nothing was written.", zh: "决策失败——未写入任何数据。" },
  "monitors.loadFailed": { en: "Failed to load monitors.", zh: "监测器加载失败。" },
  "monitors.emptyTitle": { en: "No monitors yet", zh: "尚无监测器" },
  "monitors.emptyBody": {
    en: "Monitors watch a source / case stream and surface incremental updates for your HITL decision. Configure collection in WATCH (source management) first; once data flows, monitors are attached to a source or Case.",
    zh: "监测器观察信源 / Case 数据流，产生增量更新并等待你复核（HITL）。请先到 WATCH·信源管理配置采集；数据流动后即可在信源或 Case 上挂载监测器。",
  },
  "monitors.goSources": { en: "Go to source management →", zh: "前往信源管理 →" },
  "monitors.allReviewed": { en: "All updates reviewed.", zh: "全部更新已复核。" },
  "monitors.reviewing": { en: "Recording decision…", zh: "记录决策中…" },
  "monitors.runStatus.succeeded": { en: "succeeded", zh: "成功" },
  "monitors.runStatus.failed": { en: "failed", zh: "失败" },
  "monitors.runStatus.running": { en: "running", zh: "运行中" },
  "monitors.runStatus.queued": { en: "queued", zh: "排队中" },
  "monitors.runStatus.abstained": { en: "abstained", zh: "弃权" },
  "monitors.runStatus.cancelled": { en: "cancelled", zh: "已取消" },
  "monitors.runStatus.pending": { en: "pending", zh: "进行中" },

  // ── archive ──
  "archive.search": { en: "Search title / note", zh: "搜索标题 / 备注" },
  "archive.statItems": { en: "Committed items", zh: "已确认条目" },
  "archive.statEditions": { en: "Press editions", zh: "报纸版面" },
  "archive.statCases": { en: "Cases covered", zh: "覆盖 Case" },
  "archive.chainHint": { en: "Version chain loads when a row is expanded.", zh: "版本链在展开行时加载。" },
  "archive.versions": { en: "Versions", zh: "版本" },
  "archive.committedAt": { en: "Committed", zh: "确认于" },
  "archive.commitNote": { en: "Commit note", zh: "提交备注" },
  "archive.content": { en: "Content", zh: "内容" },
  "archive.contentNone": { en: "No content payload in this revision.", zh: "该版本无内容负载。" },
  "archive.noteLabel": { en: "Note", zh: "备注" },
  "archive.revDraft": { en: "draft", zh: "草稿" },
  "archive.revCommitted": { en: "committed", zh: "已确认" },
  "archive.revSuperseded": { en: "superseded", zh: "已替代" },
  "archive.klass.element_map": { en: "Element map", zh: "要素图谱" },
  "archive.klass.research_report": { en: "Research report", zh: "研究报告" },
  "archive.klass.cross_source_analysis": { en: "Cross-source analysis", zh: "跨源比对" },
  "archive.klass.monitor_review": { en: "Monitor review", zh: "监测回顾" },
  "archive.klass.press_edition": { en: "Press edition", zh: "报纸版面" },
  "archive.emptyTab": {
    en: "No committed items in this category yet. Versions you confirm (UserCommit) land here automatically.",
    zh: "该分类暂无已确认条目。经你确认（UserCommit）的版本会自动归档于此。",
  },
  "archive.emptySearch": { en: "No items match your search.", zh: "没有匹配搜索的条目。" },
  "archive.selectHint": {
    en: "Tick rows to compose them into a Press Edition.",
    zh: "勾选条目即可编入报纸版面。",
  },
  "archive.stepPick": { en: "1 · Pick artifacts", zh: "1 · 勾选条目" },
  "archive.stepForm": { en: "2 · Title & note", zh: "2 · 标题与备注" },
  "archive.stepPreview": { en: "3 · Draft preview", zh: "3 · 草稿预览" },
  "archive.noteField": { en: "Edition note (optional)", zh: "版面备注（可选）" },
  "archive.notePlaceholder": { en: "Why this edition, for whom…", zh: "这期版面为何而编、给谁看…" },
  "archive.composing": { en: "Composing…", zh: "编排中…" },
  "archive.back": { en: "Back", zh: "上一步" },
  "archive.cancel": { en: "Cancel", zh: "取消" },
  "archive.composedN": { en: "Composed {n} sections", zh: "已编排 {n} 个章节" },
  "archive.closeWizard": { en: "Close wizard", zh: "收起向导" },
  "archive.openWizard": { en: "Compose a Press Edition", zh: "编排报纸版面" },
  "archive.publishFailed": { en: "Publish failed — the draft remains a draft.", zh: "发布失败——草稿仍为草稿。" },
  "archive.composeFailed": { en: "Compose failed.", zh: "编排失败。" },
  "archive.newEditionHint": {
    en: "After publishing, the new edition appears in the list (klass = press_edition).",
    zh: "发布后新 Edition 会出现在列表中（klass = press_edition）。",
  },
  "archive.loadFailed": { en: "Failed to load archive.", zh: "档案加载失败。" },

  // ── settings ──
  "settings.subtitle": {
    en: "Model services, usage and preferences for this research workstation.",
    zh: "本认知研究工作站的模型服务、用量与偏好。",
  },
  "settings.model": { en: "Model service", zh: "模型服务" },
  "settings.modelReady": { en: "LLM reachable", zh: "模型连通" },
  "settings.modelDown": { en: "LLM unreachable", zh: "模型不可达" },
  "settings.modelChecking": { en: "Checking…", zh: "检测中…" },
  "settings.recheck": { en: "Re-check", zh: "重新检测" },
  "settings.healthDetail": { en: "Detail", zh: "详情" },
  "settings.healthLatency": { en: "Latency", zh: "延迟" },
  "settings.healthCheckedAt": { en: "Checked", zh: "检测于" },
  "settings.healthNever": { en: "Not checked yet.", zh: "尚未检测。" },
  "settings.keys": { en: "Keys configured", zh: "已配置 Key" },
  "settings.keyOn": { en: "configured", zh: "已配置" },
  "settings.keyOff": { en: "missing", zh: "未配置" },
  "settings.healthFailed": { en: "Health check failed.", zh: "健康检测失败。" },
  "settings.usage": { en: "Usage", zh: "用量" },
  "settings.usageCalls": { en: "LLM calls", zh: "模型调用" },
  "settings.usageTokenIn": { en: "Tokens in", zh: "输入 tokens" },
  "settings.usageTokenOut": { en: "Tokens out", zh: "输出 tokens" },
  "settings.usageCost": { en: "Cost", zh: "成本" },
  "settings.costUnpriced": { en: "Unpriced", zh: "未计价" },
  "settings.costNote": {
    en: "cost_usd is 0 — the backend does not price tokens yet; showing “Unpriced” instead of a fake 0.",
    zh: "cost_usd 为 0——后端尚未接入计价；这里如实显示“未计价”而非 0。",
  },
  "settings.counts": { en: "Object counts", zh: "对象计数" },
  "settings.countsNote": {
    en: "Counts are read from the research store and are descriptive only.",
    zh: "计数读取自 research 存储，仅作描述性说明。",
  },
  "settings.prefs": { en: "Preferences", zh: "偏好" },
  "settings.language": { en: "Interface language", zh: "界面语言" },
  "settings.languageNote": {
    en: "Stored in localStorage (oh-locale) and applied across the whole app immediately.",
    zh: "保存在 localStorage（oh-locale），切换后全站立即生效。",
  },
  "settings.localeOther": {
    en: "Current locale “{v}” is outside zh/en; switching will override it.",
    zh: "当前语言“{v}”不在 zh/en 选项内；切换将覆盖它。",
  },
  "settings.data": { en: "Data layers", zh: "数据架构" },
  "settings.dataLine": {
    en: "research.sqlite keeps three layers — bronze raw captures → silver cleaned / structured records → gold research objects (Cases / Artifacts / Monitors); the Archive only exposes gold objects you confirmed via UserCommit.",
    zh: "research.sqlite 单库三层：bronze 原始抓取 → silver 清洗结构化 → gold 研究对象（Case / Artifact / Monitor）；ARCHIVE 只呈现经 UserCommit 确认的 gold 对象。",
  },
  "settings.developerHint": {
    en: "The legacy developer page stays at /settings/developer.",
    zh: "旧开发者页保留于 /settings/developer。",
  },
  "settings.openDeveloper": { en: "Open developer settings →", zh: "打开开发者设置 →" },
  "settings.loadFailed": { en: "Backend not reachable.", zh: "后端未连接。" },
  "settings.loading": { en: "Loading…", zh: "加载中…" },
};

function interpolate(template: string, params?: Record<string, string | number>): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (_, k: string) => (k in params ? String(params[k]) : `{${k}}`));
}

/**
 * 与 useT 同签名的 t()：DICTS 命中优先；未收录键落到 EXTRA（zh* → zh，其余 en）。
 * dictionaries.ts 正式补键后本层自动让位。
 */
export function useExtraT() {
  const t = useT();
  const { locale } = useLocale();
  return useCallback(
    (key: string, params?: Record<string, string | number>): string => {
      const hit = t(key, params);
      if (hit !== key) return hit;
      const pair = EXTRA[key];
      if (!pair) return interpolate(key, params);
      const lang: "en" | "zh" = locale.startsWith("zh") ? "zh" : "en";
      return interpolate(pair[lang], params);
    },
    [t, locale],
  );
}
