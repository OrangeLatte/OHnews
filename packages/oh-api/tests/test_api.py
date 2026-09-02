"""oh-api 测试：TestClient 冒烟（种子 1 事件全链数据）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import TIER_MAP, make_now, seed_event
from fastapi.testclient import TestClient
from oh_api.app import AppPaths, create_app
from oh_contracts.briefing import EvidenceCitation, EvidenceSet
from oh_contracts.signals import Signal, SignalKind
from oh_pipeline.run import run_pipeline
from oh_storage.bronze_parquet import ParquetBronzeWriter
from oh_storage.connection import connect
from oh_storage.sqlite_store import SqliteStore


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    bronze = ParquetBronzeWriter(tmp_path / "bronze")
    # 文件名必须对齐 AppPaths 默认布局（root/silver.sqlite），否则 API 读到空库
    store = SqliteStore(connect(tmp_path / "silver.sqlite"))
    now = make_now()
    ev = seed_event(bronze, store, "E01", now)
    run_pipeline(
        bronze, store, store, [ev], TIER_MAP, as_of=now, lookback_days=1, min_per_source=10
    )
    # anatomy 端点从 sources.yaml 读 tier_map——写 mini 配置对齐 conftest.TIER_MAP
    sources_yaml = tmp_path / "sources.yaml"
    sources_yaml.write_text(
        "sources:\n"
        + "".join(
            f"  - source_id: {sid}\n    tier: {tier.value}\n" for sid, tier in TIER_MAP.items()
        ),
        encoding="utf-8",
    )
    app = create_app(AppPaths(root=tmp_path, sources_yaml=sources_yaml, now_fn=make_now))
    return TestClient(app)


def test_health(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_today_briefing(client: TestClient) -> None:
    """/api/today：极化种子事件应产出 NDI_ALERT / EXPECTATION_GAP Signal。"""
    r = client.get("/api/today", params={"min_per_source": 1})
    assert r.status_code == 200
    data = r.json()
    assert data["date"] == make_now().date().isoformat()
    kinds = {s["kind"] for s in data["signals"]}
    assert "ndi_alert" in kinds and "expectation_gap" in kinds
    for s in data["signals"]:
        assert s["title"] and s["what_changed"]
        assert 0 <= s["strength"] <= 100
        assert s["evidence_ids"] == ["E01"]
    strengths = [s["strength"] for s in data["signals"]]
    assert strengths == sorted(strengths, reverse=True)


def test_status_and_events(client: TestClient) -> None:
    s = client.get("/api/status").json()
    assert s["events"] == 1 and s["ndi_ok"] == 1
    evs = client.get("/api/events?days=7").json()
    assert evs[0]["event_id"] == "E01"
    assert evs[0]["ndi_status"] == "ok"


def test_event_ndi_and_evidence(client: TestClient) -> None:
    ndi = client.get("/api/events/E01/ndi").json()
    assert len(ndi) == 1 and ndi[0]["status"] == "ok"
    assert ndi[0]["language"] == "all"
    ev = client.get("/api/events/E01/evidence").json()
    assert len(ev) == 24
    assert all(e["quote"] for e in ev)
    assert {"gov", "wscn"} <= {e["source_id"] for e in ev}


def test_event_ndi_language_filter(client: TestClient) -> None:
    """language 查询参数过滤（within-language，裁决 F）。"""
    assert len(client.get("/api/events/E01/ndi", params={"language": "all"}).json()) == 1
    assert client.get("/api/events/E01/ndi", params={"language": "zh"}).json() == []


def test_evidence_404(client: TestClient) -> None:
    assert client.get("/api/events/NOPE/evidence").status_code == 404


def test_event_spectrum(client: TestClient) -> None:
    """句级叙事光谱：24 篇文章逐句染色，LOSS/GAIN 正文帧命中。"""
    docs = client.get("/api/events/E01/spectrum").json()
    assert len(docs) == 24
    assert {"gov", "wscn"} <= {d["source_id"] for d in docs}
    by_src = {d["source_id"]: d for d in docs}
    loss_sents = by_src["gov"]["sentences"]
    assert any(s["frame"] == "loss" for s in loss_sents)
    gain_sents = by_src["wscn"]["sentences"]
    assert any(s["frame"] == "gain" for s in gain_sents)
    assert all("text" in s and "hits" in s for d in docs for s in d["sentences"])


def test_spectrum_404(client: TestClient) -> None:
    assert client.get("/api/events/NOPE/spectrum").status_code == 404


def test_agent_invoke_offline(client: TestClient) -> None:
    """Intent 驱动入口（离线路径）：EVENT target → 五层 Artifact。"""
    r = client.post(
        "/api/agent/invoke",
        json={"intent": "show_evidence", "target_kind": "event", "target_id": "E01"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["offline"] is True
    art = data["artifact"]
    assert art["engine"] == "offline" and art["intent"] == "show_evidence"
    assert art["observation"] and art["interpretation"]
    assert data["packet"]["event"]["event_id"] == "E01"
    assert data["packet"]["stances"]


def test_agent_invoke_validation(client: TestClient) -> None:
    assert client.post("/api/agent/invoke", json={}).status_code == 422
    bad = {"intent": "show_evidence", "target_kind": "nope", "target_id": "x"}
    assert client.post("/api/agent/invoke", json=bad).status_code == 422
    unk = {"intent": "nope", "target_kind": "event", "target_id": "E01"}
    assert client.post("/api/agent/invoke", json=unk).status_code == 422


def test_entities_list(client: TestClient) -> None:
    ents = client.get("/api/entities").json()["entities"]
    ids = {e["entity_id"] for e in ents}
    assert {"fed", "fomc", "ecb"} <= ids
    assert any(e["parent_id"] == "fed" for e in ents)


def test_entity_timeline(client: TestClient) -> None:
    """R3 时间轴：窗口点位/事件卡/NDI 关联。"""
    tl = client.get("/api/timeline/fed", params={"days": 7}).json()
    assert tl["entity_id"] == "fed" and len(tl["points"]) == 7
    total_articles = sum(p["articles"] for p in tl["points"])
    assert total_articles == 24  # seed: 12 gov + 12 wscn 全部含 fed
    assert tl["points"][-1]["n_events"] == 1  # E01 as_of=now（末日）
    assert tl["events"][0]["event_id"] == "E01"
    assert tl["events"][0]["ndi"] is not None  # run_pipeline 已出 NDI
    official_rows = sum(p["official_rows"] for p in tl["points"])
    assert official_rows > 0  # gov=OFFICIAL tier

    assert client.get("/api/timeline/nope").status_code == 404


def test_spectrum_v2_spans(client: TestClient) -> None:
    """词级主体/动作 spans：LOSS_BODY 有中文实体与框架词命中。"""
    docs = client.get("/api/events/E01/spectrum").json()
    assert docs
    spans = [s for d in docs for s in d["sentences"] for s in s["spans"]]
    assert spans, "种子正文含 美联储/衰退/损失 应产生 spans"
    kinds = {
        s["kind"] if "kind" in s else ("entity" if "entity_id" in s else "action") for s in spans
    }
    assert kinds <= {"entity", "action"}


def test_event_anatomy(client: TestClient) -> None:
    """分歧构成：官方(gov) vs 市场(wscn) 簇对 + fed 主体对立。"""
    a = client.get("/api/events/E01/anatomy").json()
    assert a["event_id"] == "E01"
    assert a["ndi"] is not None
    assert {"L1", "L3"} <= set(a["clusters"])  # gov=OFFICIAL wscn=FINANCIAL_PRESS
    pairs = a["cluster_pairs"]
    assert pairs and pairs[0]["official_vs_market"] is True
    opp = a["entity_opposition"]
    assert opp and opp[0]["entity_id"] == "fed"
    assert opp[0]["n_official"] == 12 and opp[0]["n_market"] == 12


def test_anatomy_404(client: TestClient) -> None:
    assert client.get("/api/events/NOPE/anatomy").status_code == 404


def test_intel_cycle_endpoints(client: TestClient) -> None:
    """六角色情报循环：离线降级跑通 + latest/reports 读取。"""
    r = client.post("/api/intel/run", json={"scope": "测试巡逻"})
    assert r.status_code == 200
    rep = r.json()
    assert rep["engine"] == "offline"
    assert rep["ach"]["hypotheses"]
    assert rep["ach"]["conclusion_index"] < len(rep["ach"]["hypotheses"])
    assert all(k["term"] for k in rep["key_judgments"])
    latest = client.get("/api/intel/latest").json()
    assert latest["report_id"] == rep["report_id"]
    assert client.get("/api/intel/reports").json()[0]["report_id"] == rep["report_id"]


def test_brief_endpoint(client: TestClient) -> None:
    r = client.get("/api/brief?watchlist=fed").json()
    assert "NDI" in r["text"] and r["items"] == 1


def test_research_endpoint(client: TestClient) -> None:
    r = client.post("/api/research", json={"question": "美联储的叙事分歧怎么样？"})
    assert r.status_code == 200
    body = r.json()
    assert "E01" in body["answer"] and body["confidence"] == 0.3
    assert client.post("/api/research", json={"question": ""}).status_code == 422


def test_decision_endpoints(client: TestClient) -> None:
    r = client.post("/api/decisions", json={"entity_id": "fed", "decision": "判断叙事将转向"})
    assert r.status_code == 200
    did = r.json()["decision_id"]
    assert client.get("/api/decisions?entity_id=fed").json()[0]["decision"] == "判断叙事将转向"
    assert client.post(f"/api/decisions/{did}/resolve", json={"outcome": "正确"}).status_code == 200


def test_dashboard_pages(client: TestClient) -> None:
    for path in ("/", "/brief", "/research", "/decisions"):
        r = client.get(path)
        assert r.status_code == 200
        assert "OH!News" in r.text
    assert "叙事分歧概览" in client.get("/").text


def test_sse_route_registered(client: TestClient) -> None:
    """SSE 流测试改为路由级：长驻流在 TestClient 中不消费（keepalive 会挂）。
    实际连通性由 scripts/dev/serve.py 手动冒烟。"""
    # include_router 会产生无 path 属性的 _IncludedRouter 项，过滤后再取
    paths = [r.path for r in client.app.routes if hasattr(r, "path")]  # type: ignore[attr-defined]
    assert "/api/stream" in paths


def test_publish_sse_no_subscriber_zero_cost() -> None:
    import asyncio

    from oh_api.app import publish_sse

    asyncio.run(publish_sse("tick", {"x": 1}))  # 无订阅者：静默返回


def test_dev_logs(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "s1.json").write_text('{"a": 1}\n', encoding="utf-8")
    (logs / "s2.jsonl").write_text('{"b": 2}\n{"c": 3}\n', encoding="utf-8")
    (logs / "skip.xyz").write_text("x", encoding="utf-8")
    app = create_app(AppPaths(root=tmp_path, sources_yaml=tmp_path / "none.yaml", logs_dir=logs))
    c = TestClient(app)
    r = c.get("/api/dev/logs").json()
    assert r["logs_dir"] == str(logs)
    assert {f["file"] for f in r["files"]} == {"s1.json", "s2.jsonl"}
    preview = c.get("/api/dev/logs/s2.jsonl").json()
    assert len(preview["lines"]) == 2
    assert c.get("/api/dev/logs/skip.xyz").status_code == 404
    assert c.get("/api/dev/logs/..%2Fescape").status_code in {400, 404}
    assert c.get("/api/dev/logs").status_code == 200


def test_dev_logs_empty_dir(tmp_path: Path) -> None:
    app = create_app(AppPaths(root=tmp_path, sources_yaml=tmp_path / "none.yaml"))
    c = TestClient(app)
    r = c.get("/api/dev/logs").json()
    assert r["files"] == []  # 默认 logs_dir 不存在 → 空列表不报错


def test_alert_endpoints(client: TestClient) -> None:
    r = client.post("/api/alerts/rules", json={"entity_id": "fed", "percentile": 0.9})
    assert r.status_code == 200 and r.json()["rule_id"]
    rules = client.get("/api/alerts/rules").json()
    assert len(rules) == 1 and rules[0]["entity_id"] == "fed"
    # 历史样本不足 → 样本门弃权，0 触发但不报错
    chk = client.post("/api/alerts/check").json()
    assert chk["triggered"] == 0
    assert client.get("/api/alerts/hits").json() == []
    bad = client.post("/api/alerts/rules", json={"entity_id": "fed", "percentile": 1.5})
    assert bad.status_code == 422
    rid = rules[0]["rule_id"]
    assert client.delete(f"/api/alerts/rules/{rid}").json()["deleted"] == "true"
    assert client.delete(f"/api/alerts/rules/{rid}").status_code == 404


def test_chat_endpoints(client: TestClient) -> None:
    """chat：无 keys/config → 离线聚合降级；历史持久化 + 线程列表。"""
    r = client.post("/api/chat", json={"message": "美联储最近怎么样？"})
    assert r.status_code == 200
    body = r.json()
    assert body["thread_id"] and body["offline"] is True
    assert "E01" in body["reply"]
    tid = body["thread_id"]
    # 多轮：同一 thread 追加历史
    r2 = client.post("/api/chat", json={"message": "继续", "thread_id": tid}).json()
    assert r2["thread_id"] == tid
    msgs = client.get(f"/api/chat/{tid}/messages").json()
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    threads = client.get("/api/chat/threads").json()
    assert threads[0]["thread_id"] == tid and threads[0]["n"] == 4
    assert client.post("/api/chat", json={}).status_code == 422


def test_watch_endpoints(client: TestClient) -> None:
    """Watch 订阅中心：三类 CRUD + refresh 确定性快照（REDESIGN §3 Watch 页）。"""
    # entity：refresh 过滤该实体 Signal + 事件
    w = client.post("/api/watches", json={"type": "entity", "query": "fed"}).json()
    r = client.post(f"/api/watches/{w['watch_id']}/refresh", params={"min_per_source": 1}).json()
    assert r["type"] == "entity" and r["last_summary"]["kind"] == "entity"
    assert r["last_summary"]["n_events"] >= 1  # seed E01 entities=[fed]
    # topic：关键词命中 Bronze 计数 + 事件匹配
    t = client.post("/api/watches", json={"type": "topic", "query": "衰退,增长"}).json()
    rt = client.post(f"/api/watches/{t['watch_id']}/refresh").json()
    st = rt["last_summary"]
    assert st["kind"] == "topic" and st["n_articles"] >= 12  # LOSS/GAIN body 各 12 篇
    # 事件 title/summary 不含关键词 → 0 命中（匹配语义正确）；结构完整即可
    assert isinstance(st["n_events"], int) and st["top_sources"]
    # question：Investigator 接入（R4）——无 keys 但命中事件 → 离线确定性回答
    q = client.post("/api/watches", json={"type": "question", "query": "事件"}).json()
    rq = client.post(f"/api/watches/{q['watch_id']}/refresh").json()
    qs = rq["last_summary"]
    assert qs["status"] == "answered" and qs["engine"] == "offline"
    assert "相关事件" in qs["answer"] and qs["n_matched_events"] >= 1
    # 完全不相关问题：无 keys 且无命中 → pending_agent
    q2 = client.post("/api/watches", json={"type": "question", "query": "量子纠缠与期货"}).json()
    rq2 = client.post(f"/api/watches/{q2['watch_id']}/refresh").json()
    assert rq2["last_summary"]["status"] == "pending_agent"
    # 校验与 404
    assert client.post("/api/watches", json={"type": "bad", "query": "x"}).status_code == 422
    assert client.post("/api/watches", json={"type": "topic", "query": "  "}).status_code == 422
    assert client.post("/api/watches/NOPE/refresh").status_code == 404
    # 列表 + 删除
    lst = client.get("/api/watches").json()["watches"]
    assert {x["watch_id"] for x in lst} >= {w["watch_id"], t["watch_id"]}
    for wid in (w["watch_id"], t["watch_id"], q["watch_id"], q2["watch_id"]):
        assert client.delete(f"/api/watches/{wid}").status_code == 200


def test_library_endpoints(client: TestClient) -> None:
    """Library Research Memory：三类条目 CRUD（REDESIGN §3 Library 页）。"""
    # 保存 Agent Artifact（五层 JSON）
    a = client.post(
        "/api/library",
        json={
            "item_type": "analysis",
            "title": "fed 叙事解读",
            "ref_kind": "intent",
            "ref_id": "explain_signal",
            "payload": {
                "observation": "NDI 0.279",
                "interpretation": "官方与市场框架分化",
                "evidence": ["boe_news", "fed_press"],
                "alternative": None,
                "uncertainty": "离线声明",
            },
        },
    ).json()
    assert a["item_id"].startswith("lib-") and a["item_type"] == "analysis"
    # 收藏事件 + 手写笔记
    e = client.post(
        "/api/library",
        json={
            "item_type": "event",
            "title": "E01 事件",
            "ref_kind": "event",
            "ref_id": "E01",
            "payload": {"event_id": "E01", "ndi": 0.81},
        },
    ).json()
    n = client.post(
        "/api/library",
        json={"item_type": "note", "title": "研究思路", "payload": {"text": "关注官方簇样本量"}},
    ).json()
    # 列表（倒序）+ 类型过滤
    lst = client.get("/api/library").json()["items"]
    assert {i["item_type"] for i in lst} == {"analysis", "event", "note"}
    only = client.get("/api/library", params={"item_type": "event"}).json()["items"]
    assert [i["item_id"] for i in only] == [e["item_id"]]
    # 校验与 404
    assert client.post("/api/library", json={"item_type": "bad", "title": "x"}).status_code == 422
    assert client.post("/api/library", json={"item_type": "note", "title": " "}).status_code == 422
    assert client.get("/api/library", params={"item_type": "bad"}).status_code == 422
    assert client.delete("/api/library/NOPE").status_code == 404
    # 删除
    for iid in (a["item_id"], e["item_id"], n["item_id"]):
        assert client.delete(f"/api/library/{iid}").status_code == 200
    assert client.get("/api/library").json()["items"] == []


def test_keys_roundtrip_and_llm_ready(client: TestClient) -> None:
    """运行时 keys：POST 热生效（无 models.yaml 时 llm_ready 仍 false=诚实降级）。"""
    r = client.get("/api/keys").json()
    assert r == {"deepseek": False, "zhipu": False, "tavily": False, "llm_ready": False}
    r2 = client.post(
        "/api/keys",
        json={"DEEPSEEK_API_KEY": "sk-test-abc", "ZHIPU_API_KEY": "  ", "EVIL": "x"},
    )
    assert r2.status_code == 422  # 未知字段拒绝
    r3 = client.post("/api/keys", json={"DEEPSEEK_API_KEY": "sk-test-abc"}).json()
    assert r3["deepseek"] is True and r3["zhipu"] is False
    # 值不回显
    assert "sk-test-abc" not in str(r3)
    # repo 真实 config/models.yaml 存在 → key 注入后 router 可构造（llm_ready=True 热生效）
    assert r3["llm_ready"] is True


def test_event_detail_endpoint(client: TestClient) -> None:
    """/api/events/{id} 单事件详情（R0：详情页不再拉全量列表 .find）。"""
    r = client.get("/api/events/E01")
    assert r.status_code == 200
    d = r.json()
    assert d["event_id"] == "E01" and d["entities"] == ["fed"]
    assert d["title"] == "事件E01"
    assert d["ndi"] is not None and d["ndi_status"] in {"ok", "low_confidence", "abstain"}
    assert d["n_sources"] >= 1
    assert client.get("/api/events/NOPE").status_code == 404


def test_evidence_by_keys_endpoint(client: TestClient) -> None:
    """/api/evidence/by_keys item_key 反查（R0：narrative_shift 证据链入口）。"""
    rows = client.get("/api/events/E01/evidence").json()
    keys = [x["item_key"] for x in rows]
    assert keys
    r = client.post("/api/evidence/by_keys", json={"item_keys": [keys[0], "ghost-key"]})
    assert r.status_code == 200
    out = r.json()
    assert len(out) == 1  # 未命中跳过
    assert out[0]["item_key"] == keys[0]
    assert out[0]["source_id"] in {"gov", "wscn"}
    assert out[0]["quote"]  # LOSS/GAIN body 非空
    # 去重保序
    r2 = client.post("/api/evidence/by_keys", json={"item_keys": [keys[0], keys[0]]}).json()
    assert [x["item_key"] for x in r2] == [keys[0]]
    # 校验：空列表 / 超限
    assert client.post("/api/evidence/by_keys", json={"item_keys": []}).status_code == 422
    assert client.post("/api/evidence/by_keys", json={"item_keys": ["k"] * 201}).status_code == 422


def test_event_detail_includes_assessment(client: TestClient) -> None:
    """R1：event_detail 内联 EventAssessment（评估层接入事件详情）。"""
    d = client.get("/api/events/E01").json()
    a = d["assessment"]
    assert a is not None
    assert a["event_id"] == "E01"
    assert a["status"] in {"confirmed", "contested", "developing", "unverified"}
    assert 0 <= a["confidence"] <= 1
    assert a["evidence_strength"] in {"strong", "moderate", "limited", "insufficient"}
    assert a["engine"] == "offline"
    assert a["observation"]


def test_intel_daily_endpoint(client: TestClient) -> None:
    """/api/intel/daily：M2 四层快照（评估/信号/叙事/洞察，engine=offline）。"""
    r = client.get("/api/intel/daily", params={"days": 1, "min_per_source": 1})
    assert r.status_code == 200
    d = r.json()
    assert set(d) == {"as_of", "assessments", "signals", "narratives", "insights"}
    assert d["assessments"] and d["assessments"][0]["event_id"] == "E01"
    kinds = {s["kind"] for s in d["signals"]}
    assert "ndi_alert" in kinds and "expectation_gap" in kinds
    for s in d["signals"]:
        assert s["evidence_kind"] in {"item_key", "event_id"}
        assert "intelligence_score" in s["metrics"]
    for n in d["narratives"]:
        assert n["narrative_id"].startswith("nar-")
        assert n["engine"] == "offline"
    for i in d["insights"]:
        assert i["insight_id"].startswith("ins-")
        assert len(i["alternative_explanations"]) >= 1
        assert i["engine"] == "offline"


def test_graph_endpoint(client: TestClient, tmp_path: Path) -> None:
    """/api/graph：entity_edges 表只读投影（种子库空图 → 手动 upsert 后可见）。"""
    r = client.get("/api/graph")
    assert r.status_code == 200
    base = r.json()
    assert set(base) == {"generated_at", "nodes", "edges"}
    assert base["nodes"] == [] and base["edges"] == []

    store = SqliteStore(connect(tmp_path / "silver.sqlite"))
    store.upsert_edges(
        [
            {
                "edge_key": "fed|fomc|parent_of",
                "src": "fed",
                "dst": "fomc",
                "kind": "parent_of",
                "weight": 2.0,
                "first_seen": "2026-08-27T00:00:00+00:00",
                "last_seen": "2026-08-28T00:00:00+00:00",
                "evidence": ["fed"],
            },
            {
                "edge_key": "fed|ecb|co_occurs",
                "src": "fed",
                "dst": "ecb",
                "kind": "co_occurs",
                "weight": 0.5,
                "first_seen": "2026-08-27T00:00:00+00:00",
                "last_seen": "2026-08-28T00:00:00+00:00",
                "evidence": ["evt-1"],
            },
        ]
    )
    r2 = client.get("/api/graph", params={"min_weight": 1.0})
    data = r2.json()
    ids = {n["id"] for n in data["nodes"]}
    assert ids == {"fed", "fomc"}  # 0.5 权重边被 min_weight 滤除
    fed = next(n for n in data["nodes"] if n["id"] == "fed")
    assert fed["entity_type"] == "central_bank" and fed["degree"] == 1
    assert data["edges"][0]["kind"] == "parent_of"
    assert data["edges"][0]["n_evidence"] == 1


def test_briefing_endpoint(client: TestClient) -> None:
    """/api/briefing：DataFreshness + ChangeBrief（人话字段，禁内部指标泄漏）。"""
    r = client.get("/api/briefing", params={"min_per_source": 1})
    assert r.status_code == 200
    data = r.json()
    fresh = data["freshness"]
    assert fresh["as_of"] and fresh["staleness"] in {"fresh", "aging", "stale"}
    assert fresh["note"]
    changes = data["changes"]
    assert changes, "极化种子事件应产出至少一张变化卡"
    for c in changes:
        assert c["change_id"].startswith("sig-")
        assert c["headline"] and c["what"] and c["why_now"]
        assert c["strength_word"] in {"strong", "notable", "minor", "insufficient"}
        assert c["subjects"] and c["subjects"][0]["kind"] == "entity"
        assert c["subjects"][0]["label"] == "美联储"
    kinds = {c["kind"] for c in changes}
    assert "divergence_rise" in kinds


def test_change_dossier_endpoint(client: TestClient) -> None:
    """/api/changes/{id}：Dossier 三桶证据 + 缺口 + 覆盖摘要 + 技术附页。"""
    changes = client.get("/api/briefing", params={"min_per_source": 1}).json()["changes"]
    cid = changes[0]["change_id"]
    r = client.get(f"/api/changes/{cid}")
    assert r.status_code == 200
    d = r.json()
    assert d["change_id"] == cid
    assert d["status"] in {"confirmed", "contested", "developing", "unverified"}
    ev = d["evidence"]
    cites = ev["supporting"] + ev["contradicting"] + ev["context"]
    assert cites
    assert all(c["quote"] for c in cites)
    # 质量门 1.5-b：coverage 与三桶严格一致（从分桶引文实算）
    assert d["coverage"]["n_independent_sources"] == len({c["source_id"] for c in cites})
    assert d["freshness"]["as_of"]
    assert d["technical"]["signal_id"] == cid
    missing = client.get("/api/changes/sig-nope-x")
    assert missing.status_code == 404


def test_quote_quality_gate() -> None:
    """引文质量门：HTML 清洗 + 实体相关性切取（不取文章任意前 400 字符）。"""
    from oh_api.briefing import _relevant_quote

    body = (
        "<p>日元干预疑云笼罩市场，交易员严阵以待。</p>"
        "<p>美联储官员表示，衰退风险上升，损失惨重。</p>"
    )
    quote = _relevant_quote(body, ["美联储"])
    assert "<" not in quote and ">" not in quote
    assert quote.startswith("美联储") or "美联储" in quote[:50]
    assert "日元" not in quote
    # 无别名命中：退回首句窗口（清洗后全文）
    fallback = _relevant_quote("<p>日元干预疑云。</p><p>市场观望。</p>", ["美联储"])
    assert fallback.startswith("日元")
    assert _relevant_quote("", ["美联储"]) == ""


def test_change_evidence_bucket_endpoint(client: TestClient) -> None:
    """/api/changes/{id}/evidence?bucket=：三桶惰性加载 + 非法桶 422。"""
    changes = client.get("/api/briefing", params={"min_per_source": 1}).json()["changes"]
    cid = changes[0]["change_id"]
    ctx = client.get(f"/api/changes/{cid}/evidence", params={"bucket": "context"})
    assert ctx.status_code == 200
    assert isinstance(ctx.json(), list)
    bad = client.get(f"/api/changes/{cid}/evidence", params={"bucket": "noise"})
    assert bad.status_code == 422


def test_track_endpoint(client: TestClient) -> None:
    """阶段 1-e：主路径埋点闭集 + 匿名 session 必填。"""
    r = client.post("/api/track", json={"event": "briefing_viewed", "session": "s-1"})
    assert r.status_code == 204
    r = client.post(
        "/api/track",
        json={
            "event": "change_opened",
            "session": "s-1",
            "object_id": "sig-x",
            "from_page": "/",
        },
    )
    assert r.status_code == 204
    # 闭集违规 422
    bad = client.post("/api/track", json={"event": "page_view", "session": "s-1"})
    assert bad.status_code == 422
    # session 必填
    assert client.post("/api/track", json={"event": "change_opened"}).status_code == 422


def test_beliefs_flow(client: TestClient) -> None:
    """POST /api/beliefs：change_type 自动判定（new→revised）+ 快照可回读。"""
    changes = client.get("/api/briefing", params={"min_per_source": 1}).json()["changes"]
    cid = changes[0]["change_id"]
    body = {
        "change_id": cid,
        "subject_id": "fed",
        "subject_label": "美联储",
        "stance": "maintain",
        "confidence": 0.6,
        "rationale": "官方与市场口径一致",
    }
    r1 = client.post("/api/beliefs", json=body)
    assert r1.status_code == 201
    b1 = r1.json()
    assert b1["change_type"] == "new"
    assert b1["snapshot_id"].startswith("bs-")
    r2 = client.post(
        "/api/beliefs",
        json={**body, "stance": "reverse", "confidence": 0.3},
    )
    assert r2.json()["change_type"] == "revised"
    rows = client.get("/api/beliefs", params={"change_id": cid}).json()
    assert [b["stance"] for b in rows] == ["maintain", "reverse"]
    tl = client.get("/api/beliefs/timeline", params={"subject_id": "fed"}).json()
    assert len(tl) == 2


def test_beliefs_validation(client: TestClient) -> None:
    """stance 闭集与 confidence 值域 422；timeline 空列表。"""
    bad = client.post(
        "/api/beliefs",
        json={
            "change_id": "sig-x",
            "subject_id": "fed",
            "stance": "agree",
            "confidence": 0.5,
        },
    )
    assert bad.status_code == 422
    assert (
        client.post(
            "/api/beliefs",
            json={
                "change_id": "sig-x",
                "subject_id": "fed",
                "stance": "maintain",
                "confidence": 1.5,
            },
        ).status_code
        == 422
    )
    empty = client.get("/api/beliefs/timeline", params={"subject_id": "nobody"}).json()
    assert empty == []


def test_watch_update_and_review(client: TestClient) -> None:
    """增量更新（只读）+ 显式复核（阶段 3）：查看 ≠ 复核。"""
    w = client.post("/api/watches", json={"type": "entity", "query": "fed"}).json()
    wid = w["watch_id"]
    u = client.get(f"/api/watches/{wid}/update").json()
    assert u["kind"] == "entity" and u["watch_id"] == wid
    assert isinstance(u["has_changes"], bool) and "自" in u["summary"]
    assert u["since"] is None  # 无复核/无判断 → 无基线（全量为新）
    assert u["freshness"]["staleness"] in {"fresh", "aging", "stale"}
    # topic：命中计数分支
    t = client.post("/api/watches", json={"type": "topic", "query": "衰退,增长"}).json()
    ut = client.get(f"/api/watches/{t['watch_id']}/update").json()
    assert ut["kind"] == "topic" and ut["new_articles"] >= 1
    # question：诚实边界
    q = client.post("/api/watches", json={"type": "question", "query": "事件"}).json()
    uq = client.get(f"/api/watches/{q['watch_id']}/update").json()
    assert uq["kind"] == "question" and "暂不支持" in uq["summary"]
    # 复核：推进 last_checked_at；404
    rv = client.post(f"/api/watches/{wid}/review")
    assert rv.status_code == 200 and rv.json()["watch_id"] == wid
    u2 = client.get(f"/api/watches/{wid}/update").json()
    assert u2["since"] is not None  # 复核后出现基线
    assert client.post("/api/watches/NOPE/review").status_code == 404


def test_home_endpoint(client: TestClient) -> None:
    """首页单次聚合（T4）：briefing + 变化场 + watchlist 一次返回。"""
    h = client.get("/api/home?days=7").json()
    assert set(h) == {"briefing", "landscape", "watches"}
    # briefing 嵌套完整
    assert set(h["briefing"]) >= {"freshness", "changes"}
    # landscape 嵌套完整（两窗等长基线在前）
    ls = h["landscape"]
    assert ls["baseline_window"]["end"] == ls["current_window"]["start"]
    # 与独立端点同源（days 相同则变化队列一致）
    b = client.get("/api/briefing?days=7").json()
    assert [c["change_id"] for c in h["briefing"]["changes"]] == [
        c["change_id"] for c in b["changes"]
    ]


def test_change_landscape_endpoint(client: TestClient) -> None:
    """变化场场景聚合（阶段 1.5-c，T1 更名）：后端拼图，前端渲染；scene_id 确定性。"""
    a = client.get("/api/change-landscape").json()
    assert set(a) >= {
        "scene_id",
        "generated_at",
        "baseline_window",
        "current_window",
        "source_streams",
        "narrative_streams",
        "qualified_changes",
        "evidence_refs",
        "freshness",
        "quality_warnings",
    }
    # 两窗等长且基线在前
    assert a["baseline_window"]["end"] == a["current_window"]["start"]
    assert a["baseline_window"]["start"] < a["baseline_window"]["end"]
    # 流带结构
    for s in a["source_streams"]:
        assert s["cluster"] in {"official", "market"}
        assert s["n_baseline"] >= 0 and s["n_current"] >= 0
    for n in a["narrative_streams"]:
        assert 0.0 <= n["share_current"] <= 1.0
        assert 0.0 <= n["share_baseline"] <= 1.0
    # 腰部变化与 briefing 同源（同一次 detect 的人话管道）
    b = client.get("/api/briefing?top=5").json()
    brief_ids = [c["change_id"] for c in b["changes"][:5]]
    scene_ids = [c["change_id"] for c in a["qualified_changes"]]
    assert scene_ids == brief_ids[: len(scene_ids)]
    # 质量门告警码闭集
    valid = {
        "low_coverage",
        "single_source_dominant",
        "window_empty",
        "stale_data",
        "no_qualified_changes",
        "gate_insufficient_coverage",
        "source_composition_shift",
    }
    assert all(w["code"] in valid for w in a["quality_warnings"])
    # 确定性：同 now 重跑 scene_id 与窗口统计稳定
    b2 = client.get("/api/change-landscape").json()
    assert b2["scene_id"] == a["scene_id"]
    assert b2["current_window"]["n_articles"] == a["current_window"]["n_articles"]


def _sig(entity_id: str = "fed") -> Signal:
    now = make_now()
    return Signal(
        signal_id="sig-gate-test",
        kind=SignalKind.NARRATIVE_SHIFT,
        entity_id=entity_id,
        title="Fed Narrative Shift",
        what_changed="主导叙事迁移",
        strength=60.0,
        confidence=0.5,
        detected_at=now,
        as_of=now,
    )


def _cite(item_key: str, source_id: str, quote: str) -> EvidenceCitation:
    return EvidenceCitation(
        item_key=item_key,
        source_id=source_id,
        source_tier="L3",
        title="标题",
        quote=quote,
    )


def test_hero_gate_blocks_insufficient_evidence() -> None:
    """Hero Gate（1.5-d）：单源/HTML/无关引文拦，双源干净引文过。"""
    from oh_api.change_landscape import _hero_gate
    from oh_pipeline.entities import DEFAULT_ENTITIES, EntityRegistry

    registry = EntityRegistry(DEFAULT_ENTITIES)
    ok = EvidenceSet(
        supporting=[
            _cite("k1", "govcn", "美联储宣布维持利率不变。"),
            _cite("k2", "wscn", "市场解读 Fed 鹰派信号。"),
        ]
    )
    assert _hero_gate(ok, _sig(), registry) == []
    single = EvidenceSet(supporting=[_cite("k1", "govcn", "美联储宣布维持利率不变。")])
    assert any("独立来源" in r for r in _hero_gate(single, _sig(), registry))
    html = EvidenceSet(
        supporting=[
            _cite("k1", "govcn", "美联储宣布维持利率不变。"),
            _cite("k2", "wscn", "<b>Fed</b> 鹰派信号。"),
        ]
    )
    assert any("HTML" in r for r in _hero_gate(html, _sig(), registry))
    off = EvidenceSet(
        supporting=[
            _cite("k1", "govcn", "日元干预情绪蔓延。"),
            _cite("k2", "wscn", "东京市场波动加剧。"),
        ]
    )
    assert any("相关性" in r for r in _hero_gate(off, _sig(), registry))
    empty = EvidenceSet()
    assert _hero_gate(empty, _sig(), registry) == ["无任何可展示引文"]


def test_change_field_endpoint(client: TestClient) -> None:
    """叙事场时序（T8）：每日×泳道×框架计数矩阵 + 合格变化点。"""
    r = client.get("/api/change-field?days=30").json()
    assert {"days", "series", "changes", "freshness"} == set(r)
    dates = [p["date"] for p in r["series"]]
    assert dates == sorted(dates)
    for point in r["series"]:
        for lane, frames in point["lanes"].items():
            assert lane in {"official", "press", "market", "social", "unknown"}
            assert all(v >= 1 for v in frames.values())


def test_agent_sessions_flow(client: TestClient) -> None:
    """A4：会话创建/列表/user_gate 随时补充输入通道。"""
    r = client.post("/api/agent/sessions", json={"kind": "dissection", "title": "拆解演示"})
    assert r.status_code == 201
    tid = r.json()["thread_id"]
    assert tid.startswith("dissection:")
    assert client.post("/api/agent/sessions", json={"kind": "bogus"}).status_code == 422
    sessions = client.get("/api/agent/sessions?kind=dissection").json()["sessions"]
    assert any(x["thread_id"] == tid for x in sessions)
    push = client.post(f"/api/agent/sessions/{tid}/inputs", json={"text": "重点看利率段"})
    assert push.status_code == 202
    assert client.post(f"/api/agent/sessions/{tid}/inputs", json={"text": "  "}).status_code == 422
    ghost = client.post("/api/agent/sessions/ghost:0000/inputs", json={"text": "x"})
    assert ghost.status_code == 404


def test_agent_dissect_flow(client: TestClient, tmp_path: Path) -> None:
    """B1 拆解：无 LLM key 走 offline 降级（诚实 engine=offline）+ 缓存复用。"""
    from oh_contracts.ids import make_item_key
    from oh_contracts.schemas import BronzeRecord

    ts = make_now()
    rec = BronzeRecord(
        source_id="wscn",
        item_key=make_item_key("wscn", "dissect-1", ts),
        external_id="dissect-1",
        url_hash="u",
        content_hash="c",
        fetched_at=ts,
        published_at=ts,
        raw={},
        normalized={
            "title": "美联储暗示九月暂停加息",
            "body": "通胀放缓令九月的利率决定保有空间。",
        },
    )
    ParquetBronzeWriter(tmp_path / "bronze").write([rec])
    body = {"item_key": rec.item_key}
    r1 = client.post("/api/agent/dissect", json=body)
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["item_key"] == rec.item_key
    assert d1["engine"] in {"offline", "llm"}
    if d1["engine"] == "offline":
        assert d1["model_hint"] == ""
    r2 = client.post("/api/agent/dissect", json=body)
    assert r2.status_code == 200
    assert r2.json()["dissected_at"] == d1["dissected_at"]  # 缓存未重拆
    assert client.post("/api/agent/dissect", json={"item_key": "ghost"}).status_code == 404
    assert client.post("/api/agent/dissect", json={}).status_code == 422


def test_agent_report_flow(client: TestClient, tmp_path: Path) -> None:
    """B2 报告端点：409 未拆解 → 拆解后生成（测试无 key 走 offline）→ 列表回读。"""
    from oh_contracts.ids import make_item_key
    from oh_contracts.schemas import BronzeRecord

    ts = make_now()
    rec = BronzeRecord(
        source_id="wscn",
        item_key=make_item_key("wscn", "report-1", ts),
        external_id="report-1",
        url_hash="u",
        content_hash="c",
        fetched_at=ts,
        published_at=ts,
        raw={},
        normalized={"title": "美联储暗示九月暂停加息", "body": "通胀放缓。"},
    )
    ParquetBronzeWriter(tmp_path / "bronze").write([rec])
    ik = rec.item_key
    r0 = client.post("/api/agent/report", json={"item_key": ik, "kind": "truth"})
    assert r0.status_code == 409
    r1 = client.post("/api/agent/dissect", json={"item_key": ik})
    assert r1.status_code == 200
    r2 = client.post("/api/agent/report", json={"item_key": ik, "kind": "truth"})
    assert r2.status_code == 200
    rep = r2.json()
    assert rep["report_id"].startswith("rp-")
    assert rep["kind"] == "truth"
    assert rep["engine"] in {"llm", "offline"}
    assert len(rep["sections"]) >= 1
    assert all(len(s["title"]) >= 8 for s in rep["sections"])
    r3 = client.post("/api/agent/report", json={"item_key": ik, "kind": "bogus"})
    assert r3.status_code == 422
    r4 = client.get(f"/api/agent/reports/{ik}")
    assert r4.status_code == 200
    assert any(x["report_id"] == rep["report_id"] for x in r4.json())


def test_agent_queue_suggestions_and_decide(client: TestClient, tmp_path: Path) -> None:
    """B0：建议列表（打分+幂等入队）→ 用户裁决 accept/dismiss → ghost 404。"""
    from oh_contracts.ids import make_item_key
    from oh_contracts.schemas import BronzeRecord

    ts = make_now()
    recs = [
        BronzeRecord(
            source_id="wscn",
            item_key=make_item_key("wscn", f"q-{i}", ts),
            external_id=f"q-{i}",
            url_hash="u",
            content_hash="c",
            fetched_at=ts,
            published_at=ts,
            raw={},
            normalized={"title": f"美联储政策观察第 {i} 篇", "body": "通胀放缓。"},
        )
        for i in range(2)
    ]
    ParquetBronzeWriter(tmp_path / "bronze").write(recs)
    r1 = client.get("/api/agent/dissect/suggestions?limit=5")
    assert r1.status_code == 200
    items = r1.json()
    assert len(items) >= 1
    first = items[0]
    assert {"item_key", "score", "reasons"} <= set(first)
    ik = first["item_key"]
    r2 = client.post("/api/agent/dissect/queue", json={"item_key": ik, "action": "accept"})
    assert r2.status_code == 200 and r2.json()["status"] == "accepted"
    r3 = client.post("/api/agent/dissect/queue", json={"item_key": ik, "action": "dismiss"})
    assert r3.status_code == 200 and r3.json()["status"] == "dismissed"
    assert (
        client.post(
            "/api/agent/dissect/queue", json={"item_key": "ghost", "action": "accept"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/agent/dissect/queue", json={"item_key": ik, "action": "maybe"}
        ).status_code
        == 422
    )


def test_sources_filter(client: TestClient) -> None:
    """C1：服务端筛选（tier/q）。"""
    r = client.get("/api/sources", params={"tier": "L1"})
    assert r.status_code == 200
    srcs = r.json()["sources"]
    assert srcs and all(s["tier"] == "L1" for s in srcs)
    r2 = client.get("/api/sources", params={"q": "gov"})
    assert all("gov" in s["source_id"] for s in r2.json()["sources"])


def test_source_suggest_and_register(client: TestClient) -> None:
    """C2：URL→启发式建议→确认注册（写 tmp sources.yaml）→冲突 409/非法 422。"""
    r = client.post("/api/sources/suggest", json={"url": "https://www.example.cn/rss.xml"})
    assert r.status_code == 200
    sug = r.json()["suggestion"]
    assert sug["adapter"] == "rss"
    assert sug["language"] == "zh"
    sid = sug["source_id"]
    r1 = client.post(
        "/api/sources",
        json={
            "source_id": sid,
            "adapter": sug["adapter"],
            "tier": sug["tier"],
            "language": sug["language"],
            "url": "https://www.example.cn/rss.xml",
        },
    )
    assert r1.status_code == 200
    assert r1.json()["source_id"] == sid
    lst = client.get("/api/sources").json()["sources"]
    assert any(s["source_id"] == sid for s in lst)
    r2 = client.post(
        "/api/sources",
        json={
            "source_id": sid,
            "adapter": "rss",
            "tier": "L3",
            "language": "zh",
            "url": "https://x",
        },
    )
    assert r2.status_code == 409
    r3 = client.post("/api/sources/suggest", json={"url": "ftp://bad"})
    assert r3.status_code == 422
    r4 = client.post(
        "/api/sources",
        json={
            "source_id": "okname",
            "adapter": "unknown_kind",
            "tier": "L3",
            "language": "en",
            "url": "https://x",
        },
    )
    assert r4.status_code == 422


def test_tracking_flow(client: TestClient, tmp_path: Path) -> None:
    """C3 跟踪预警统一：四类单元 CRUD + entity/topic 增量 + element 拆解命中。"""
    from oh_contracts.ids import make_item_key
    from oh_contracts.schemas import BronzeRecord

    ts = make_now()
    rec = BronzeRecord(
        source_id="wscn",
        item_key=make_item_key("wscn", "track-1", ts),
        external_id="track-1",
        url_hash="u",
        content_hash="c",
        fetched_at=ts,
        published_at=ts,
        raw={},
        normalized={"title": "美联储暗示九月暂停加息", "body": "通胀放缓。"},
    )
    ParquetBronzeWriter(tmp_path / "bronze").write([rec])
    r1 = client.post("/api/tracking", json={"kind": "entity", "query": "fed", "label": "美联储"})
    assert r1.status_code == 201
    unit = r1.json()
    assert unit["unit_id"].startswith("tu-en-")
    assert client.post("/api/tracking", json={"kind": "bogus", "query": "x"}).status_code == 422
    assert client.post("/api/tracking", json={"kind": "topic", "query": ""}).status_code == 422
    lst = client.get("/api/tracking").json()
    assert any(u["unit_id"] == unit["unit_id"] for u in lst["units"])
    upd = client.get(f"/api/tracking/{unit['unit_id']}/update").json()
    assert "summary" in upd and "since" in upd
    u2 = client.post(
        "/api/tracking",
        json={"kind": "element", "query": "tone:optimism", "mode": "track"},
    ).json()
    client.post("/api/agent/dissect", json={"item_key": rec.item_key})
    upd2 = client.get(f"/api/tracking/{u2['unit_id']}/update").json()
    assert "元素" in upd2["summary"]
    assert client.post(f"/api/tracking/{u2['unit_id']}/review").status_code == 200
    assert client.delete(f"/api/tracking/{u2['unit_id']}").status_code == 204
    assert client.delete(f"/api/tracking/{u2['unit_id']}").status_code == 404
