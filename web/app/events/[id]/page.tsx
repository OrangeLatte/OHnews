"use client";

import { use, useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  api,
  type EvidenceRow,
  type NdiPoint,
  type SpectrumDoc,
  type SpectrumSentence,
} from "@/lib/api";

const FRAME_COLORS: Record<string, string> = {
  loss: "#e5534b",
  gain: "#3fb950",
  responsibility: "#d29922",
  conflict: "#bc8cff",
  human_interest: "#58a6ff",
  other: "#8b949e",
};

const FRAME_LABELS: Record<string, string> = {
  loss: "损失",
  gain: "收益",
  responsibility: "责任",
  conflict: "冲突",
  human_interest: "人情味",
  other: "其他",
};

function sentenceBg(s: SpectrumSentence): string | undefined {
  if (!s.frame) return undefined;
  const c = FRAME_COLORS[s.frame] ?? FRAME_COLORS.other;
  return `${c}1f`;
}

function SpectrumBlock({ docs }: { docs: SpectrumDoc[] }) {
  const [openKey, setOpenKey] = useState<string | null>(docs[0]?.item_key ?? null);
  if (docs.length === 0)
    return <p className="text-sm text-muted-foreground">暂无关联文章</p>;
  return (
    <div className="flex flex-col gap-2">
      {docs.map((d) => {
        const hits = d.sentences.filter((s) => s.frame).length;
        const open = openKey === d.item_key;
        return (
          <div key={d.item_key} className="rounded-md border border-border/60">
            <button
              type="button"
              onClick={() => setOpenKey(open ? null : d.item_key)}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted/40"
            >
              <span className="text-xs">{open ? "▼" : "▶"}</span>
              <span className="font-mono text-xs text-muted-foreground">{d.source_id}</span>
              <span className="flex-1 truncate">{d.title || "(无标题)"}</span>
              <Badge variant="outline" className="text-[10px]">
                {hits}/{d.sentences.length} 句命中
              </Badge>
            </button>
            {open && (
              <p className="border-t border-border/60 px-3 py-2 text-sm leading-7">
                {d.sentences.map((s) => (
                  <span
                    key={s.i}
                    className="mr-1 rounded px-1 py-0.5"
                    style={{ backgroundColor: sentenceBg(s) }}
                    title={
                      s.frame
                        ? `${FRAME_LABELS[s.frame] ?? s.frame}｜命中：${s.keywords.join("、")}${
                            s.stance ? `｜立场：${s.stance === "critical" ? "批评" : "支持"}` : ""
                          }`
                        : undefined
                    }
                  >
                    {s.text}
                    {s.stance && (
                      <sup
                        className="ml-0.5 text-[10px]"
                        style={{
                          color: s.stance === "critical" ? "#e5534b" : "#3fb950",
                        }}
                      >
                        {s.stance === "critical" ? "批" : "挺"}
                      </sup>
                    )}
                  </span>
                ))}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}

function NdiChart({ points }: { points: NdiPoint[] }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current || points.length === 0) return;
    const ts = points.map((p) => p.ts.replace("T", " ").slice(0, 16));
    const ndi = points.map((p) => p.ndi);
    const lo = points.map((p) => p.ci_low);
    const hi = points.map((p) => p.ci_high);
    const chart = echarts.init(ref.current);
    chart.setOption({
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      legend: { data: ["NDI", "CI 下界", "CI 上界"], textStyle: { color: "#9ca3af" } },
      grid: { left: 48, right: 24, top: 40, bottom: 32 },
      xAxis: { type: "category", data: ts, axisLabel: { color: "#9ca3af" } },
      yAxis: { type: "value", min: 0, max: 1, axisLabel: { color: "#9ca3af" } },
      series: [
        {
          name: "NDI",
          type: "line",
          data: ndi,
          connectNulls: true,
          lineStyle: { width: 2 },
          itemStyle: { color: "#3fb950" },
        },
        {
          name: "CI 下界",
          type: "line",
          data: lo,
          connectNulls: true,
          lineStyle: { type: "dashed", opacity: 0.5 },
          itemStyle: { color: "#58a6ff" },
          symbol: "none",
        },
        {
          name: "CI 上界",
          type: "line",
          data: hi,
          connectNulls: true,
          lineStyle: { type: "dashed", opacity: 0.5 },
          itemStyle: { color: "#d29922" },
          symbol: "none",
        },
      ],
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [points]);

  return <div ref={ref} className="h-72 w-full" />;
}

function citation(r: EvidenceRow) {
  return [
    `【摘录】${r.quote}`,
    `来源：${r.source_id}（tier 内信源）`,
    `PIT 时间：${r.ts}`,
    `框架：${r.frame} / 立场：${r.stance} / 置信度：${r.confidence.toFixed(2)}（${r.engine}）`,
    `item_key：${r.item_key}`,
  ].join("\n");
}

export default function EventPage({
  params,
}: PageProps<"/events/[id]">) {
  const { id } = use(params);
  const [ndi, setNdi] = useState<NdiPoint[] | null>(null);
  const [evidence, setEvidence] = useState<EvidenceRow[]>([]);
  const [spectrum, setSpectrum] = useState<SpectrumDoc[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.eventNdi(id), api.eventEvidence(id), api.eventSpectrum(id)])
      .then(([n, e, sp]) => {
        setNdi(n);
        setEvidence(e);
        setSpectrum(sp);
      })
      .catch((err) => setError(String(err)));
  }, [id]);

  async function copyCite(r: EvidenceRow) {
    await navigator.clipboard.writeText(citation(r));
    setCopied(r.item_key);
    setTimeout(() => setCopied(null), 1500);
  }

  if (error) return <p className="text-destructive">加载失败：{error}</p>;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <Link href="/" className="text-sm text-muted-foreground hover:text-foreground">
          ← 返回概览
        </Link>
        <h1 className="font-paper text-2xl tracking-tight">{id}</h1>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">NDI 时序（弃权点不绘制连线）</CardTitle>
        </CardHeader>
        <CardContent>
          {ndi && ndi.length > 0 ? (
            <NdiChart points={ndi} />
          ) : (
            <p className="text-sm text-muted-foreground">暂无 NDI 点位</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">叙事光谱（句级框架染色，只读派生）</CardTitle>
          <p className="text-xs text-muted-foreground">
            按句复用规则层线索词染色：损失红/收益绿/责任黄/冲突紫/人情味蓝；上标「批/挺」= 句内立场线索。悬浮查看命中词。
          </p>
        </CardHeader>
        <CardContent>
          <SpectrumBlock docs={spectrum} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">证据链（claim → 原文摘录，一键引用）</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>来源</TableHead>
                <TableHead>框架</TableHead>
                <TableHead>立场</TableHead>
                <TableHead>置信</TableHead>
                <TableHead>引擎</TableHead>
                <TableHead>PIT 时间</TableHead>
                <TableHead>摘录</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {evidence.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} className="text-muted-foreground">
                    暂无 stance（证据链为空）
                  </TableCell>
                </TableRow>
              ) : (
                evidence.map((r) => (
                  <TableRow key={r.item_key + r.frame}>
                    <TableCell className="font-mono text-xs">{r.source_id}</TableCell>
                    <TableCell>
                      <Badge variant="outline">{r.frame}</Badge>
                    </TableCell>
                    <TableCell>{r.stance}</TableCell>
                    <TableCell>{r.confidence.toFixed(2)}</TableCell>
                    <TableCell className="text-xs">{r.engine}</TableCell>
                    <TableCell className="font-mono text-xs">
                      {r.ts.replace("T", " ").slice(0, 16)}
                    </TableCell>
                    <TableCell className="max-w-[20rem] truncate" title={r.quote}>
                      {r.quote}
                    </TableCell>
                    <TableCell>
                      <Button size="sm" variant="outline" onClick={() => copyCite(r)}>
                        {copied === r.item_key ? "已复制" : "复制引用"}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
