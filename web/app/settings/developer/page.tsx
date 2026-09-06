"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type LogFile } from "@/lib/api";
import KeySetup from "@/app/settings/developer/key-setup";
import MetricsSection from "@/app/settings/developer/metrics-section";

export default function DeveloperSettingsPage() {
  return (
    <div className="flex flex-col gap-10">
      <div>
        <h1 className="font-paper text-3xl tracking-tight">DEVELOPER · 系统设置</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          LLM Keys 与运行监控——产品前台不展示的工程面。信源管理已迁移至 /watch（WATCH）工作空间。
        </p>
      </div>
      <KeySetup />
      <MetricsSection />
      <DevMonitorSection />
    </div>
  );
}

function DevMonitorSection() {
  const [dir, setDir] = useState("");
  const [files, setFiles] = useState<LogFile[]>([]);
  const [preview, setPreview] = useState<{ file: string; lines: string[] } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const d = await api.devLogs();
      setDir(d.logs_dir);
      setFiles(d.files);
    } catch (err) {
      setError(String(err));
    }
  }, []);

  useEffect(() => {
    api
      .devLogs()
      .then((d) => {
        setDir(d.logs_dir);
        setFiles(d.files);
      })
      .catch((err) => setError(String(err)));
  }, []);

  async function open(name: string) {
    try {
      setPreview(await api.devLogPreview(name));
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold">opencode 会话监控</h1>
        <Badge variant="outline">{dir || "…"}</Badge>
        <Button size="sm" variant="outline" onClick={load}>
          刷新
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        数据源：uv run python scripts/dev/collect_logs.py 镜像的 opencode 会话日志
        （.opencode/logs/，gitignored）。空目录表示尚未运行采集脚本。
      </p>
      {error && <p className="text-destructive">{error}</p>}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[20rem_1fr]">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">会话文件（{files.length}）</CardTitle>
          </CardHeader>
          <CardContent className="flex max-h-[32rem] flex-col gap-1 overflow-y-auto">
            {files.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                暂无日志文件——先运行 collect_logs.py
              </p>
            ) : (
              files.map((f) => (
                <button
                  key={f.file}
                  onClick={() => open(f.file)}
                  className="flex items-center justify-between rounded px-2 py-1.5 text-left font-mono text-xs hover:bg-accent"
                >
                  <span className="truncate">{f.file}</span>
                  <span className="ml-2 shrink-0 text-muted-foreground">
                    {(f.size / 1024).toFixed(0)}KB
                  </span>
                </button>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              预览{preview ? `：${preview.file}` : "（点击左侧文件）"}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap text-xs leading-5">
              {preview ? preview.lines.join("\n") : "—"}
            </pre>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
