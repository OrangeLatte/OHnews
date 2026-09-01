"use client";

import { useEffect, useState } from "react";

type KeysStatus = { deepseek: boolean; zhipu: boolean; llm_ready: boolean };

export default function KeySetup() {
  const [keys, setKeys] = useState<KeysStatus | null>(null);
  const [inputs, setInputs] = useState({ DEEPSEEK_API_KEY: "", ZHIPU_API_KEY: "" });
  const [msg, setMsg] = useState<string | null>(null);

  const loadKeys = () =>
    fetch("/api/keys")
      .then((r) => r.json())
      .then(setKeys)
      .catch(() => undefined);

  useEffect(() => {
    loadKeys();
  }, []);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setMsg("保存中…");
    const body: Record<string, string> = {};
    for (const [k, v] of Object.entries(inputs)) if (v.trim()) body[k] = v.trim();
    if (Object.keys(body).length === 0) {
      setMsg("请先填写至少一个 key");
      return;
    }
    try {
      const r = await fetch("/api/keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const d = await r.json();
      setKeys(d);
      setInputs({ DEEPSEEK_API_KEY: "", ZHIPU_API_KEY: "" });
      setMsg(d.llm_ready ? "已生效：LLM 增强已启用" : "已保存（LLM 增强需可用的模型配置）");
    } catch (err) {
      setMsg(String(err));
    }
  }

  return (
    <div>
      <h2 className="paper-kicker mb-2 !text-[11px] !text-foreground">API Keys</h2>
      <div className="mb-2 flex gap-3 text-xs">
        <span>DeepSeek {keys?.deepseek ? "●" : "○"}</span>
        <span>Zhipu {keys?.zhipu ? "●" : "○"}</span>
        <span className={keys?.llm_ready ? "text-primary" : "text-muted-foreground"}>
          {keys?.llm_ready ? "LLM 增强 ON" : "离线降级"}
        </span>
      </div>
      <form onSubmit={save} className="space-y-1.5">
        <input
          type="password"
          placeholder="DeepSeek API Key"
          value={inputs.DEEPSEEK_API_KEY}
          onChange={(e) => setInputs((m) => ({ ...m, DEEPSEEK_API_KEY: e.target.value }))}
          className="w-full border border-input bg-transparent px-2 py-1 font-mono text-[11px]"
        />
        <input
          type="password"
          placeholder="Zhipu API Key"
          value={inputs.ZHIPU_API_KEY}
          onChange={(e) => setInputs((m) => ({ ...m, ZHIPU_API_KEY: e.target.value }))}
          className="w-full border border-input bg-transparent px-2 py-1 font-mono text-[11px]"
        />
        <button
          type="submit"
          className="w-full border border-foreground/25 px-2 py-1 text-[11px] hover:bg-muted"
        >
          保存并热生效
        </button>
        {msg && <p className="text-[10px] text-muted-foreground">{msg}</p>}
        <p className="text-[10px] leading-4 text-muted-foreground">
          key 仅存本机 data/runtime_keys.json（gitignored，0600），不回显、不入库。
        </p>
      </form>
    </div>
  );
}
