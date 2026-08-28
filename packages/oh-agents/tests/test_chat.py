"""chat_graph 多轮会话（离线 FakeRouter）：工具循环/降级/上限/存储。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from conftest import TIER_MAP, make_now, seed_event
from oh_agents.chat import (
    MAX_TOOL_ROUNDS,
    ChatOutput,
    ChatStore,
    ChatToolCall,
    execute_tool,
    run_chat,
)
from oh_pipeline.entities import EntityRegistry
from oh_pipeline.run import run_pipeline
from oh_storage.bronze_parquet import ParquetBronzeWriter
from oh_storage.connection import connect
from oh_storage.sqlite_store import SqliteStore


def _setup(tmp_path: Path):
    bronze = ParquetBronzeWriter(tmp_path / "bronze")
    store = SqliteStore(connect(tmp_path / "s.sqlite"))
    now = make_now()
    ev = seed_event(bronze, store, "E01", now)
    run_pipeline(
        bronze, store, store, [ev], TIER_MAP, as_of=now, lookback_days=1, min_per_source=10
    )
    return bronze, store, now


def test_chat_offline_mode(tmp_path: Path) -> None:
    """无 router：只读工具聚合降级仍可用（可用性优先）。"""
    bronze, store, now = _setup(tmp_path)
    result = asyncio.run(
        run_chat(
            "美联储最近怎么样？",
            [],
            bronze=bronze,
            store=store,
            gold=store,
            registry=EntityRegistry(),
            now=now,
        )
    )
    assert "E01" in result["reply"]
    assert "晨报" in result["reply"]
    assert result["tools_used"] == ()


class ScriptRouter:
    """按脚本依次返回 ChatOutput（模拟多轮工具循环）。"""

    def __init__(self, outs: list[ChatOutput]) -> None:
        self.outs = list(outs)
        self.prompts: list[str] = []

    async def invoke(self, tier, system, user, schema):
        self.prompts.append(user)
        return self.outs.pop(0), object()


def test_chat_tool_loop(tmp_path: Path) -> None:
    """第一轮声明工具 → tools 节点执行 → 第二轮基于结果回复。"""
    bronze, store, now = _setup(tmp_path)
    router = ScriptRouter(
        [
            ChatOutput(
                tool_calls=[
                    ChatToolCall(name="query_events", args={"days": 7}),
                    ChatToolCall(name="get_ndi", args={}),
                ]
            ),
            ChatOutput(reply="近窗 1 个事件 E01，NDI 见上。", citations=["E01"]),
        ]
    )
    result = asyncio.run(
        run_chat(
            "美联储的叙事分歧？",
            [],
            bronze=bronze,
            store=store,
            gold=store,
            registry=EntityRegistry(),
            router=router,
            now=now,
        )
    )
    assert result["reply"].startswith("近窗 1 个事件")
    assert result["citations"] == ["E01"]
    assert result["tools_used"] == ("query_events", "get_ndi")
    assert result["rounds"] == 2
    # 第二轮 prompt 应注入工具结果
    assert "E01" in router.prompts[1]


def test_chat_unknown_tool_fed_back(tmp_path: Path) -> None:
    bronze, store, now = _setup(tmp_path)
    router = ScriptRouter(
        [
            ChatOutput(tool_calls=[ChatToolCall(name="no_such_tool", args={})]),
            ChatOutput(reply="收到，改用本地数据回答。"),
        ]
    )
    result = asyncio.run(
        run_chat(
            "测试",
            [],
            bronze=bronze,
            store=store,
            gold=store,
            registry=EntityRegistry(),
            router=router,
            now=now,
        )
    )
    assert result["tools_used"] == ("no_such_tool",)
    assert "未知工具" in router.prompts[1]
    assert result["reply"] == "收到，改用本地数据回答。"


def test_chat_max_rounds_guard(tmp_path: Path) -> None:
    """工具轮次达上限：强制收尾，不死循环。"""
    bronze, store, now = _setup(tmp_path)
    loop = ChatOutput(tool_calls=[ChatToolCall(name="get_ndi", args={})])
    router = ScriptRouter([loop] * (MAX_TOOL_ROUNDS + 2))
    result = asyncio.run(
        run_chat(
            "测试",
            [],
            bronze=bronze,
            store=store,
            gold=store,
            registry=EntityRegistry(),
            router=router,
            now=now,
        )
    )
    assert "上限" in result["reply"]
    assert result["rounds"] == MAX_TOOL_ROUNDS + 1


def test_chat_fetch_online_degrades(tmp_path: Path) -> None:
    """fetch_online 网络失败 → 友好降级字符串（不抛异常）。"""
    import httpx

    bronze, store, now = _setup(tmp_path)

    def _boom(*a, **kw):
        raise httpx.ConnectTimeout("blocked")

    orig = httpx.get
    httpx.get = _boom
    try:
        out = execute_tool(
            _ChatDepsStub(bronze, store, store), "fetch_online", {"query": "fed"}, now
        )
    finally:
        httpx.get = orig
    assert "在线检索失败" in out


class _ChatDepsStub:
    """最小 deps 满足 fetch_online（仅需 gdelt_proxy 字段）。"""

    def __init__(self, bronze, store, gold) -> None:
        self.bronze = bronze
        self.store = store
        self.gold = gold
        self.registry = None
        self.gdelt_proxy = None


def test_chat_store(tmp_path: Path) -> None:
    cs = ChatStore(tmp_path / "chat.sqlite")
    cs.append("t1", "user", "你好", "2026-08-28T00:00:00+00:00")
    cs.append("t1", "assistant", "你好，我是情报研究员", "2026-08-28T00:00:01+00:00")
    cs.append("t2", "user", "第二条会话", "2026-08-28T00:00:02+00:00")
    assert [m["role"] for m in cs.messages("t1")] == ["user", "assistant"]
    threads = cs.threads()
    assert len(threads) == 2
    assert threads[0]["thread_id"] == "t2"  # 按最后消息时间倒序
    assert threads[0]["n"] == 1
