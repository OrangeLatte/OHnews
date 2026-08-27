"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";

type ResearchResult = {
  answer: string;
  confidence: string;
  citations: string[];
  tool_calls: string[];
};

export default function ResearchPage() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<ResearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function ask() {
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    try {
      setResult(await api.research(question));
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">研究问诊（只读工具集，不触发重算）</h1>
      <Textarea
        rows={3}
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder="例：美联储最近的叙事分歧怎么样？"
      />
      <Button className="w-fit" onClick={ask} disabled={loading}>
        {loading ? "研究中…" : "提问"}
      </Button>
      {error && <p className="text-destructive">{error}</p>}
      {result && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-3 text-base">
              回答
              <Badge variant="outline">置信度：{result.confidence}</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <p className="whitespace-pre-wrap text-sm leading-6">{result.answer}</p>
            {result.tool_calls.length > 0 && (
              <div className="text-xs text-muted-foreground">
                工具调用：{result.tool_calls.join(" → ")}
              </div>
            )}
            {result.citations.length > 0 && (
              <div className="text-xs text-muted-foreground">
                引用：{result.citations.join(", ")}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
