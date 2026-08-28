"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import * as echarts from "echarts";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, type IntelReport } from "@/lib/api";

const TERM_META: Record<string, { zh: string; color: string }> = {
  almost_certain: { zh: "几乎必然 ≥95%", color: "#3fb950" },
  highly_likely: { zh: "极可能 80-95%", color: "#56d364" },
  likely: { zh: "可能 55-80%", color: "#d29922" },
  roughly_even: { zh: "大致对半 45-55%", color: "#8b949e" },
  unlikely: { zh: "不太可能 20-45%", color: "#d29922" },
  highly_unlikely: { zh: "极不可能 5-20%", color: "#f0883e" },
  almost_impossible: { zh: "几乎不可能 <5%", color: "#e5534b" },
};

const KIND_META: Record<string, string> = {
  volume_spike: "量级突刺",
  new_entity: "新实体",
  cadence_shift: "节奏突变",
};

function NetworkChart({ report }: { report: IntelReport }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current || !report.network.nodes.length) return;
    const chart = echarts.init(ref.current);
    chart.setOption({
      backgroundColor: "transparent",
      tooltip: {},
      series: [
        {
          type: "graph",
          layout: "force",
          roam: true,
          label: { show: true, color: "#c9d1d9" },
          force: { repulsion: 260, edgeLength: 90 },
          data: report.network.nodes.map((n) => ({
            id: n.id,
            name: n.id,
            symbolSize: 14 + Math.sqrt(n.strength) * 5,
            itemStyle: { color: "#f0b429" },
          })),
          links: report.network.edges.map((e) => ({
            source: e.source,
            target: e.target,
            lineStyle: { width: 1 + e.weight, opacity: 0.5, color: "#58a6ff" },
          })),
        },
      ],
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [report]);
  return <div ref={ref} className="h-80 w-full" />;
}

function AchMatrixTable({ report }: { report: IntelReport }) {
  const ach = report.ach;
  if (!ach) return <p className="text-sm text-muted-foreground">无 ACH 矩阵</p>;
  const scoreCell = (s: number | null) => {
    if (s === 1) return <span className="text-[#3fb950]">+1</span>;
    if (s === -1) return <span className="font-bold text-[#e5534b]">−1</span>;
    if (s === 0) return <span className="text-muted-foreground">0</span>;
    return <span className="text-muted-foreground/50">N/A</span>;
  };
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border/60 text-left text-xs text-muted-foreground">
            <th className="px-2 py-2">竞争假设</th>
            {ach.evidence.map((e, i) => (
              <th key={i} className="px-2 py-2 font-normal">
                E{i + 1}
              </th>
            ))}
            <th className="px-2 py-2">矛盾数</th>
          </tr>
        </thead>
        <tbody>
          {ach.hypotheses.map((h, hi) => {
            const concl = hi === ach.conclusion_index;
            const inc = h.cells.filter((c) => c.score === -1).length;
            return (
              <tr
                key={hi}
                className={`border-b border-border/40 ${concl ? "bg-[#3fb950]/10" : ""}`}
              >
                <td className="px-2 py-2">
                  {concl && <span className="mr-1 text-[#3fb950]">★</span>}
                  <span className={concl ? "font-medium" : ""}>{h.hypothesis}</span>
                  {h.note && (
                    <p className="text-xs text-muted-foreground">{h.note}</p>
                  )}
                </td>
                {h.cells.map((c, ci) => (
                  <td key={ci} className="px-2 py-2 text-center">
                    {scoreCell(c.score)}
                  </td>
                ))}
                <td className="px-2 py-2 text-center text-xs">{inc}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="mt-2 space-y-1 text-xs text-muted-foreground">
        {ach.evidence.map((e, i) => (
          <p key={i}>
            <span className="font-mono">E{i + 1}</span> {e}
          </p>
        ))}
      </div>
    </div>
  );
}

export default function IntelPage() {
  const [report, setReport] = useState<IntelReport | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .intelLatest()
      .then(setReport)
      .catch(() => setReport(null));
  }, []);

  useEffect(load, [load]);

  async function runCycle() {
    setRunning(true);
    setError(null);
    try {
      setReport(await api.intelRun());
    } catch (err) {
      setError(String(err));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col gap-5 bg-[#070b14] text-[#c9d1d9]">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="font-mono text-xl font-bold tracking-wide text-[#e6edf3]">
          情报巡逻 · INTEL CYCLE
        </h1>
        {report && (
          <>
            <Badge variant="outline" className="font-mono text-[10px]">
              {report.report_id}
            </Badge>
            <Badge
              variant="outline"
              className="text-[10px]"
              style={{
                color: report.engine === "llm" ? "#3fb950" : "#8b949e",
                borderColor: report.engine === "llm" ? "#3fb95055" : "#8b949e55",
              }}
            >
              {report.engine === "llm" ? "LLM 增强" : "离线降级"}
            </Badge>
            <span className="text-xs text-muted-foreground">{report.scope}</span>
          </>
        )}
        <Button
          size="sm"
          onClick={runCycle}
          disabled={running}
          className="ml-auto bg-[#1f6feb] hover:bg-[#388bfd]"
        >
          {running ? "巡逻中…" : "▶ 运行巡逻"}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        六角色情报循环：Scout 巡逻 → Cartographer 实体网络 → Red Team（CIA ACH
        竞争假设）→ Chief Analyst（ICD 203 概率语言 Key Judgments）。全部判断为
        描述性情报，非投资建议。
      </p>
      {error && <p className="text-sm text-[#e5534b]">{error}</p>}

      {!report && !running && (
        <div className="rounded-lg border border-dashed border-border/60 p-10 text-center text-sm text-muted-foreground">
          尚无情报简报——点击「运行巡逻」启动第一轮六角色循环。
        </div>
      )}

      {report && (
        <>
          {report.key_judgments.length > 0 && (
            <section className="rounded-lg border border-border/60 bg-[#0d1117] p-4">
              <h2 className="mb-3 text-sm font-semibold tracking-widest text-[#e6edf3]">
                KEY JUDGMENTS · ICD 203
              </h2>
              <div className="grid gap-3 md:grid-cols-2">
                {report.key_judgments.map((k, i) => {
                  const meta = TERM_META[k.term] ?? { zh: k.term, color: "#8b949e" };
                  return (
                    <div
                      key={i}
                      className="rounded-md border border-border/50 bg-[#070b14] p-3"
                      style={{ borderLeft: `3px solid ${meta.color}` }}
                    >
                      <p className="text-sm">{k.judgment}</p>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <span
                          className="rounded px-1.5 py-0.5 font-mono text-[10px] font-bold"
                          style={{ backgroundColor: `${meta.color}22`, color: meta.color }}
                        >
                          {meta.zh}
                        </span>
                        <span className="font-mono text-[10px] text-muted-foreground">
                          p={k.probability.toFixed(2)}
                        </span>
                        {k.drivers.map((d, j) => (
                          <span
                            key={j}
                            className="rounded bg-muted/40 px-1.5 py-0.5 text-[10px] text-muted-foreground"
                          >
                            {d}
                          </span>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
              {report.summary && (
                <p className="mt-3 border-t border-border/40 pt-2 text-xs text-muted-foreground">
                  {report.summary}
                </p>
              )}
            </section>
          )}

          {report.scout_findings.length > 0 && (
            <section className="rounded-lg border border-border/60 bg-[#0d1117] p-4">
              <h2 className="mb-3 text-sm font-semibold tracking-widest text-[#e6edf3]">
                SCOUT FINDINGS · 异常巡逻
              </h2>
              <div className="flex flex-wrap gap-2">
                {report.scout_findings.map((f, i) => (
                  <div
                    key={i}
                    className="rounded-md border border-[#f0883e]/40 bg-[#f0883e]/10 px-3 py-1.5 text-xs"
                  >
                    <span className="font-medium text-[#f0883e]">
                      {KIND_META[f.kind] ?? f.kind}
                    </span>{" "}
                    <span className="font-mono">{f.target}</span>{" "}
                    <span className="text-muted-foreground">z={f.score}</span>
                    <p className="mt-0.5 text-[10px] text-muted-foreground">{f.detail}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className="rounded-lg border border-border/60 bg-[#0d1117] p-4">
            <h2 className="mb-3 text-sm font-semibold tracking-widest text-[#e6edf3]">
              ACH · 竞争假设矩阵（★ = 最经得起反证）
            </h2>
            <AchMatrixTable report={report} />
          </section>

          {report.network.nodes.length > 0 && (
            <section className="rounded-lg border border-border/60 bg-[#0d1117] p-4">
              <h2 className="mb-3 text-sm font-semibold tracking-widest text-[#e6edf3]">
                CARTOGRAPHER · 实体共现网络
              </h2>
              <NetworkChart report={report} />
            </section>
          )}
        </>
      )}
    </div>
  );
}
