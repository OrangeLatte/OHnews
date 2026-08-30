"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

export default function BriefPage() {
  const [watchlist, setWatchlist] = useState("fed,trump,ecb,pboc,boe");
  const [text, setText] = useState<string | null>(null);
  const [items, setItems] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const b = await api.brief(watchlist, 5);
      setText(b.text);
      setItems(b.items);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    api
      .brief(watchlist, 5)
      .then((b) => {
        setText(b.text);
        setItems(b.items);
      })
      .catch((err) => setError(String(err)));
    // 初次挂载加载；手动重载走 load()（含 loading 态）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">晨报（watchlist 实体 24h 分歧变化 + 证据链）</h1>
      <div className="flex items-center gap-2">
        <Input
          className="max-w-md"
          value={watchlist}
          onChange={(e) => setWatchlist(e.target.value)}
          placeholder="逗号分隔实体 ID"
        />
        <Button onClick={load} disabled={loading}>
          {loading ? "生成中…" : "刷新"}
        </Button>
      </div>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            晨报{items !== null ? ` · Top ${items}` : ""}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {error ? (
            <p className="text-destructive">{error}</p>
          ) : (
            <pre className="whitespace-pre-wrap text-sm leading-6">{text ?? "加载中…"}</pre>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
