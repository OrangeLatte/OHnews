"""轻量 dashboard（Phase 5a：服务端渲染单页；Next.js 完整版 = Phase 5b）。

页面：NDI 概览 / 事件下钻证据链 / 晨报 / 问诊框 / 决策日志 + 合规尾注。
纯 HTML+原生 JS（fetch 调 /api/*），零前端构建链。
"""

from __future__ import annotations

import html
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

_NAV = """<nav>
<span class="brand">OH!News</span>
<a href="/">仪表盘</a><a href="/brief">晨报</a><a href="/research">问诊</a>
<a href="/decisions">决策日志</a>
<span class="muted">叙事分歧指数 NDI = EPU 式条件变量，非收益预测器</span>
</nav>"""

_STYLE = """<style>
*{box-sizing:border-box}
body{font-family:-apple-system,system-ui,sans-serif;margin:0;background:#0d1117;color:#e6edf3}
nav{display:flex;gap:16px;padding:12px 24px;border-bottom:1px solid #21262d;align-items:center}
nav a{color:#58a6ff;text-decoration:none}.brand{font-weight:700;font-size:18px}
.muted{margin-left:auto;color:#8b949e;font-size:12px}
main{max-width:1100px;margin:0 auto;padding:24px}
h2{border-bottom:1px solid #21262d;padding-bottom:6px}
table{width:100%;border-collapse:collapse;margin:12px 0}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #21262d;font-size:14px}
.badge{padding:2px 8px;border-radius:10px;font-size:12px}
.ok{background:#1a7f3733;color:#3fb950}.abstain{background:#9e6a0333;color:#d29922}
details{margin:8px 0}summary{cursor:pointer;color:#58a6ff}
pre{background:#161b22;padding:10px;border-radius:6px;white-space:pre-wrap;font-size:13px}
input,textarea{background:#161b22;border:1px solid #30363d;color:#e6edf3;
padding:8px;border-radius:6px;width:100%}

button{background:#238636;color:#fff;border:none;padding:8px 16px;
border-radius:6px;cursor:pointer;margin-top:8px}
.ev{background:#161b22;border:1px solid #21262d;border-radius:8px;padding:14px;margin:10px 0}
</style>"""


def _esc(s: Any) -> str:
    return html.escape(str(s))


def register_dashboard(
    app: FastAPI,
    get_store: Callable[[], Any],
    get_bronze: Callable[[], Any],
    get_decisions: Callable[[], Any],
    get_tier_map: Callable[[], dict],
) -> None:
    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        store = get_store()
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        rows: list[str] = []
        for e in store.events_asof(now):
            series = store.ndi_series(e.event_id)
            p = series[-1] if series else None
            if p is None:
                continue
            ndi = f"{p.ndi:.3f}" if p.ndi is not None else "—"
            cls = "ok" if p.status == "ok" else "abstain"
            rows.append(
                f"<tr><td>{_esc(e.event_id)}</td><td>{_esc(e.title)}</td>"
                f"<td>{_esc(','.join(e.entities))}</td>"
                f"<td><span class='badge {cls}'>{ndi}（{p.status}）</span></td>"
                f"<td>{p.n_sources}</td></tr>"
            )
        table = (
            "<table><tr><th>事件</th><th>标题</th><th>实体</th><th>NDI</th><th>源数</th></tr>"
            + ("".join(rows) or "<tr><td colspan=5>暂无数据——先运行 backfill + run_daily</td></tr>")
            + "</table>"
        )
        return f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>OH!News</title>{_STYLE}</head><body>{_NAV}<main>
<h2>叙事分歧概览</h2>{table}
<p class="muted">NDI=叙事分歧指数（描述性监测）；测量效度 ρ≥0.8 通过前不对外引用。</p>
</main></body></html>"""

    @app.get("/brief", response_class=HTMLResponse)
    def brief_page() -> str:
        from datetime import UTC, datetime

        from oh_agents.morning_brief import build_brief

        b = build_brief(
            get_bronze(),
            get_store(),
            get_store(),
            ["fed", "trump", "ecb", "pboc", "boe"],
            now=datetime.now(UTC),
        )
        return f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>晨报 · OH!News</title>{_STYLE}</head><body>{_NAV}<main>
<h2>晨报（Top{len(b.items)}）</h2><pre>{_esc(b.render_text())}</pre>
</main></body></html>"""

    @app.get("/research", response_class=HTMLResponse)
    def research_page() -> str:
        return f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>问诊 · OH!News</title>{_STYLE}</head><body>{_NAV}<main>
<h2>研究问诊</h2>
<input id="q" placeholder="例：美联储最近的叙事分歧怎么样？">
<button onclick="ask()">提问</button><pre id="out">（回答将显示在此）</pre>
<script>
async function ask() {{
  const q = document.getElementById('q').value;
  const r = await fetch('/api/research', {{method:'POST',
    headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{question:q}})}});
  const j = await r.json();
  document.getElementById('out').textContent =
    (j.answer || JSON.stringify(j)) + '\\n\\n置信度: ' + (j.confidence ?? '-') +
    '\\n引用: ' + (j.citations || []).join(', ');
}}
</script></main></body></html>"""

    @app.get("/decisions", response_class=HTMLResponse)
    def decisions_page() -> str:
        return f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>决策日志 · OH!News</title>{_STYLE}</head><body>{_NAV}<main>
<h2>决策日志（记录判断 → 回填结果 = 个人资产）</h2>
<input id="eid" placeholder="实体（如 fed）">
<textarea id="dec" rows="2" placeholder="据此判断…"></textarea>
<button onclick="add()">记录</button>
<input id="did" placeholder="decision_id">
<input id="out" placeholder="结果">
<button onclick="resolve()">回填结果</button>
<pre id="list">（查询将显示在此）</pre>
<script>
async function add() {{
  await fetch('/api/decisions', {{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{entity_id: eid.value, decision: dec.value}})}});
  query();
}}
async function resolve() {{
  await fetch('/api/decisions/' + did.value + '/resolve', {{method:'POST',
    headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{outcome: out.value}})}});
  query();
}}
async function query() {{
  const r = await fetch('/api/decisions?entity_id=' + encodeURIComponent(eid.value || 'fed'));
  const j = await r.json();
  document.getElementById('list').textContent = JSON.stringify(j, null, 2);
}}
</script></main></body></html>"""
