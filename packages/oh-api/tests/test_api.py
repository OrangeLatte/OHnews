"""oh-api 测试：TestClient 冒烟（种子 1 事件全链数据）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import TIER_MAP, make_now, seed_event
from fastapi.testclient import TestClient
from oh_api.app import AppPaths, create_app
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
    app = create_app(AppPaths(root=tmp_path, sources_yaml=tmp_path / "none.yaml", now_fn=make_now))
    return TestClient(app)


def test_health(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


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
    paths = [r.path for r in client.app.routes]  # type: ignore[attr-defined]
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
