"""chat 指挥模式（run_chat_command）：意图路由 / 执行接线 / 卡片 / 持久化。

FakeRouter 模式与 test_chat.py 一致（invoke 返回三元组 (result, ref, None)）；
工作流用 FakeWorkflows 记录调用，真实异步协议（queued→running→终态）由
ResearchStore 断言，不造数据：无法执行时必须 abstention + 根因。
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from datetime import timedelta
from pathlib import Path

from conftest import make_now
from oh_agents.chat import (
    ChatOutput,
    ChatStore,
    classify_intent,
    hitl_gate,
    run_chat_command,
)
from oh_contracts.agent_runtime import AgentRun, AgentThread, HITLRequest
from oh_contracts.case import AnalysisRun, ResearchCase
from oh_storage.research_store import ResearchStore

T = make_now().isoformat()


def _research(tmp_path: Path) -> ResearchStore:
    return ResearchStore.open(tmp_path / "research.sqlite")


def _case(store: ResearchStore, case_id: str = "case-1") -> None:
    store.create_case(
        ResearchCase(case_id=case_id, question="该事件谁在说谎？", created_at=T, updated_at=T)
    )


def _agent_run(store: ResearchStore, run_id: str = "run-1") -> None:
    """agent_run（hitl_requests.run_id 的 FK 目标是 agent_runs）。"""
    store.create_thread(AgentThread(thread_id="th-1", case_id="case-1", created_at=T))
    store.add_agent_run(
        AgentRun(
            run_id=run_id,
            thread_id="th-1",
            workflow="CommitArtifact",
            status="succeeded",
            started_at=T,
            finished_at=T,
        )
    )


def _doc(store: ResearchStore, case_id: str, rev_id: str, doc_id: str, seq: int = 0) -> None:
    """挂载文档；added_at 随 seq 递增保证「最近挂载」断言确定。"""
    store.add_document_revision(
        rev_id,
        doc_id,
        source_id="gov",
        body="正文内容",
        fetched_at=T,
        content_hash=f"hash-{rev_id}",
    )
    store.link_case_document(case_id, rev_id, (make_now() + timedelta(seconds=seq)).isoformat())


class FakeWorkflows:
    """记录调用的假工作流（走真实 run 生命周期 queued→running→succeeded）。"""

    def __init__(self, research: ResearchStore) -> None:
        self.research = research
        self.calls: list[tuple[str, ...]] = []

    def _finish(self, run_id: str) -> None:
        self.research.start_analysis_run(str(run_id))
        self.research.finish_analysis_run(str(run_id), status="succeeded", finished_at=T)

    async def dissect_document(self, case_id: str, rev_id: str, *, run_id=None) -> dict:
        self.calls.append(("dissect", case_id, rev_id, str(run_id)))
        self._finish(str(run_id))
        return {"run_id": run_id, "status": "succeeded"}

    async def build_report(
        self, case_id: str, *, report_type: str, title: str, item_key: str = "", run_id=None
    ) -> dict:
        self.calls.append(("report", case_id, report_type, title, str(run_id)))
        self._finish(str(run_id))
        return {"run_id": run_id, "status": "succeeded"}

    def compare_sources(self, case_id: str, rev_ids: list[str], *, run_id=None) -> dict:
        self.calls.append(("compare", case_id, ",".join(rev_ids), str(run_id)))
        self._finish(str(run_id))
        return {"run_id": run_id, "status": "succeeded"}


class ScriptRouter:
    """单轮直接回复（模拟 question 路径 LLM）。"""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def invoke(self, tier, system, user, schema):
        self.prompts.append(user)
        return ChatOutput(reply="基于上下文的回答。"), object(), None


# ---------------------------------------------------------------- 意图分类


def test_classify_intent_rules() -> None:
    """规则兜底：中文/英文领域词 → 十意图；未命中一律 question。

    T3：疑问句 + Case 上下文指代词 → answer_case_question（优先于 status）。
    """
    assert classify_intent("帮我拆解这篇文章") == "dissect"
    assert classify_intent("比较两个版本的口径差异") == "compare"
    assert classify_intent("生成一份研究报告") == "report"
    assert classify_intent("挑战这个主张，有没有反证") == "challenge"
    assert classify_intent("给这个 Case 做个研究计划") == "plan"
    assert classify_intent("拆解状态如何？跑到哪了") == "status"  # 元意图优先
    assert classify_intent("看看收件箱有什么新变化") == "observe"
    assert classify_intent("有没有待审批的事项") == "hitl"
    assert classify_intent("美联储最近怎么样？") == "question"
    assert classify_intent("what's new in the inbox") == "observe"
    assert classify_intent("run status please") == "status"
    assert classify_intent("当前 Case 只有几篇文章？") == "answer_case_question"
    assert classify_intent("这个 Case 有哪些主张？") == "answer_case_question"
    assert classify_intent("how many documents in this case?") == "answer_case_question"


# ---------------------------------------------------------------- abstention


def test_command_without_case_abstains(tmp_path: Path) -> None:
    """无 case_id：执行类意图必须 abstention + 根因，不造 run。"""
    result = asyncio.run(
        run_chat_command("拆解这篇文档", [], bronze=None, store=None, gold=None, registry=None)
    )
    assert result["message_type"] == "abstention"
    assert "请先打开一个研究 Case" in result["reply"]
    assert "未提供 case_id" in result["reply"]
    assert not [c for c in result["cards"] if c["type"] == "progress"]


def test_command_unknown_case_abstains_with_root_cause(tmp_path: Path) -> None:
    """case_id 不存在：abstention 携带根因（case not found），不虚构运行。"""
    result = asyncio.run(
        run_chat_command(
            "拆解这篇文档",
            [],
            bronze=None,
            store=None,
            gold=None,
            registry=None,
            research=_research(tmp_path),
            case_id="case-404",
        )
    )
    assert result["message_type"] == "abstention"
    assert "case-404" in result["reply"]


def test_command_dissect_without_documents_abstains(tmp_path: Path) -> None:
    """Case 存在但无挂载文档：abstention + 根因（诚实披露，不挑默认文档）。"""
    research = _research(tmp_path)
    _case(research)
    result = asyncio.run(
        run_chat_command(
            "拆解这篇文档",
            [],
            bronze=None,
            store=None,
            gold=None,
            registry=None,
            research=research,
            case_id="case-1",
        )
    )
    assert result["message_type"] == "abstention"
    assert "文档" in result["reply"]


# ---------------------------------------------------------------- 执行接线


def test_command_dissect_launches_workflow(tmp_path: Path) -> None:
    """拆解意图：默认取最近挂载文档触发工作流；卡片含 tool_call/progress/case。"""
    research = _research(tmp_path)
    _case(research)
    _doc(research, "case-1", "drev-a", "doc-a", seq=1)
    _doc(research, "case-1", "drev-b", "doc-b", seq=2)
    wf = FakeWorkflows(research)
    result = asyncio.run(
        run_chat_command(
            "拆解这篇文档",
            [],
            bronze=None,
            store=None,
            gold=None,
            registry=None,
            research=research,
            workflows=wf,
            case_id="case-1",
            confirmed=True,
        )
    )
    assert result["message_type"] == "tool_call"
    assert wf.calls and wf.calls[0] == ("dissect", "case-1", "drev-b", wf.calls[0][3])
    types = [c["type"] for c in result["cards"]]
    assert types[0] == "tool_call" and types[1] == "progress" and types[2] == "case"
    progress = result["cards"][1]
    assert progress["kind"] == "dissect" and progress["run_id"] == wf.calls[0][3]
    # 真实 run 生命周期落库（同步模式：返回前已到终态）
    run = research.get_analysis_run(progress["run_id"])
    assert run["status"] == "succeeded"
    # 不破坏既有会话字段
    assert result["reply"].startswith("已触发 DissectDocument")


def test_command_launch_reuses_active_run(tmp_path: Path) -> None:
    """幂等协议：同 kind+case+refs 的活跃 run 复用，不重复触发。"""
    research = _research(tmp_path)
    _case(research)
    _doc(research, "case-1", "drev-a", "doc-a")
    research.add_analysis_run(
        AnalysisRun(
            run_id="run-existing",
            case_id="case-1",
            kind="dissect",
            status="queued",
            input_refs=["drev-a"],
            started_at=T,
        )
    )
    wf = FakeWorkflows(research)
    result = asyncio.run(
        run_chat_command(
            "拆解这篇文档",
            [],
            bronze=None,
            store=None,
            gold=None,
            registry=None,
            research=research,
            workflows=wf,
            case_id="case-1",
            confirmed=True,
        )
    )
    assert wf.calls == []
    progress = next(c for c in result["cards"] if c["type"] == "progress")
    assert progress["run_id"] == "run-existing"
    assert "复用" in result["reply"]


def test_command_compare_requires_two_revisions(tmp_path: Path) -> None:
    """比较意图：文档不足 2 版 → abstention；足量 → 默认取最近两版触发（rule 引擎同步执行）。"""
    research = _research(tmp_path)
    _case(research)
    _doc(research, "case-1", "drev-a", "doc-a", seq=1)
    wf = FakeWorkflows(research)
    result = asyncio.run(
        run_chat_command(
            "比较这些版本",
            [],
            bronze=None,
            store=None,
            gold=None,
            registry=None,
            research=research,
            workflows=wf,
            case_id="case-1",
            confirmed=True,
        )
    )
    assert result["message_type"] == "abstention" and wf.calls == []
    _doc(research, "case-1", "drev-b", "doc-b", seq=2)
    result2 = asyncio.run(
        run_chat_command(
            "比较这些版本",
            [],
            bronze=None,
            store=None,
            gold=None,
            registry=None,
            research=research,
            workflows=wf,
            case_id="case-1",
            confirmed=True,
        )
    )
    assert result2["message_type"] == "tool_call"
    # 同步 rule 工作流：调用到达且最近两版按 added_at 倒序
    assert wf.calls and wf.calls[0] == ("compare", "case-1", "drev-b,drev-a", wf.calls[0][3])


def test_command_challenge_without_claims_abstains(tmp_path: Path) -> None:
    """挑战意图：Case 无 claim → abstention + 根因。"""
    research = _research(tmp_path)
    _case(research)
    _doc(research, "case-1", "drev-a", "doc-a")
    result = asyncio.run(
        run_chat_command(
            "挑战这个主张",
            [],
            bronze=None,
            store=None,
            gold=None,
            registry=None,
            research=research,
            case_id="case-1",
            confirmed=True,
        )
    )
    assert result["message_type"] == "abstention"
    assert "claim" in result["reply"]


def test_command_report_uses_case_question_as_title(tmp_path: Path) -> None:
    """报告意图：title 缺省回落 Case title/question；report_type 缺省 summary。"""
    research = _research(tmp_path)
    _case(research)
    wf = FakeWorkflows(research)
    result = asyncio.run(
        run_chat_command(
            "生成一份报告",
            [],
            bronze=None,
            store=None,
            gold=None,
            registry=None,
            research=research,
            workflows=wf,
            case_id="case-1",
            confirmed=True,
        )
    )
    assert result["message_type"] == "tool_call"
    # calls 元组序：(op, case_id, report_type, title, run_id)
    assert wf.calls and wf.calls[0][2] == "structured_summary"
    assert wf.calls[0][3] == "该事件谁在说谎？"


def test_command_background_factory_mode(tmp_path: Path) -> None:
    """工厂模式：后台线程经 factory 重建连接执行；chat 不等待即返回 run_id。"""
    research = _research(tmp_path)
    _case(research)
    _doc(research, "case-1", "drev-a", "doc-a")
    calls: list[tuple[str, ...]] = []
    done = threading.Event()

    class ThreadFake(FakeWorkflows):
        async def dissect_document(self, case_id, rev_id, *, run_id=None):
            out = await super().dissect_document(case_id, rev_id, run_id=run_id)
            calls.append((case_id, rev_id, str(run_id)))
            done.set()
            return out

    def wf_factory() -> ThreadFake:
        return ThreadFake(_research(tmp_path))

    result = asyncio.run(
        run_chat_command(
            "拆解这篇文档",
            [],
            bronze=None,
            store=None,
            gold=None,
            registry=None,
            research=research,
            research_factory=lambda: _research(tmp_path),
            workflows_factory=wf_factory,
            case_id="case-1",
            confirmed=True,
        )
    )
    progress = next(c for c in result["cards"] if c["type"] == "progress")
    assert progress["status"] == "queued"
    assert done.wait(timeout=10), "后台工作流未在超时内完成"
    assert calls[0][2] == progress["run_id"]
    for _ in range(100):
        run = _research(tmp_path).get_analysis_run(progress["run_id"])
        if run and run["status"] == "succeeded":
            break
        time.sleep(0.05)
    assert run["status"] == "succeeded"


# ---------------------------------------------------------------- 只读意图


def test_command_status_intent_summary(tmp_path: Path) -> None:
    """状态意图：runs_summary 卡 + 计数汇总（只读，不触发新 run）。"""
    research = _research(tmp_path)
    _case(research)
    research.add_analysis_run(
        AnalysisRun(
            run_id="run-1",
            case_id="case-1",
            kind="dissect",
            status="succeeded",
            input_refs=["drev-a"],
            started_at=T,
        )
    )
    result = asyncio.run(
        run_chat_command(
            "看看运行状态",
            [],
            bronze=None,
            store=None,
            gold=None,
            registry=None,
            research=research,
            case_id="case-1",
        )
    )
    assert result["message_type"] == "answer"
    summary = next(c for c in result["cards"] if c["type"] == "runs_summary")
    assert summary["runs"][0]["run_id"] == "run-1"
    assert "succeeded×1" in result["reply"]


def test_command_observe_intent(tmp_path: Path) -> None:
    """观察意图：observe_summary 卡（事件数 + 最近事件），无事件也如实说明。"""
    research = _research(tmp_path)
    _case(research)
    store = _ObserveStoreStub()
    result = asyncio.run(
        run_chat_command(
            "观察一下最新变化",
            [],
            bronze=None,
            store=store,
            gold=None,
            registry=None,
            research=research,
            case_id="case-1",
        )
    )
    card = next(c for c in result["cards"] if c["type"] == "observe_summary")
    assert card["n_events"] == 1 and card["recent_events"][0]["event_id"] == "E01"
    assert "E01" in result["reply"]


class _ObserveStoreStub:
    """observe 卡最小依赖：events_asof(now) 返回升序列表（末位=最新）。"""

    def __init__(self) -> None:
        from datetime import datetime

        self._now = datetime.fromisoformat(T)
        self._events = [
            type("Ev", (), {"event_id": "E01", "title": "测试事件", "as_of": self._now})()
        ]

    def events_asof(self, now):
        return [e for e in self._events if e.as_of <= now]


def test_command_hitl_intent_and_gate_injection(tmp_path: Path) -> None:
    """hitl 意图 → hitl_request 类型 + hitl 卡；question 路径 hitl_gate 前置注入。"""
    research = _research(tmp_path)
    _case(research)
    _agent_run(research, "run-1")
    research.create_hitl(
        HITLRequest(hitl_id="h-1", run_id="run-1", action="commit_artifact", payload={})
    )
    assert hitl_gate(research)[0]["type"] == "hitl"
    result = asyncio.run(
        run_chat_command(
            "有没有待审批的事项",
            [],
            bronze=None,
            store=None,
            gold=None,
            registry=None,
            research=research,
            case_id="case-1",
        )
    )
    assert result["message_type"] == "hitl_request"
    assert any(c["type"] == "hitl" and c["hitl_id"] == "h-1" for c in result["cards"])
    # 无待办 → 如实回答，不造卡
    research.decide_hitl("h-1", status="approved", decided_by="user", decided_at=T)
    result2 = asyncio.run(
        run_chat_command(
            "有没有待审批的事项",
            [],
            bronze=None,
            store=None,
            gold=None,
            registry=None,
            research=research,
            case_id="case-1",
        )
    )
    assert result2["message_type"] == "answer" and "没有" in result2["reply"]


# ---------------------------------------------------------------- question 路径


def test_command_question_injects_case_context(tmp_path: Path) -> None:
    """question 路径：context_injector 把 Case 摘要注入 prompt；router 在 → answer。

    prompts[0] 是意图分类调用（未命中规则词时 LLM 兜底），对话 prompt 是最后一条。
    消息不含 Case 指代词（否则 T3 会路由到 answer_case_question）。
    """
    research = _research(tmp_path)
    _case(research)
    _doc(research, "case-1", "drev-a", "doc-a", seq=1)
    router = ScriptRouter()
    result = asyncio.run(
        run_chat_command(
            "美联储最近有什么新表态？",
            [],
            bronze=None,
            store=None,
            gold=None,
            registry=None,
            research=research,
            router=router,
            case_id="case-1",
        )
    )
    assert result["message_type"] == "answer"
    assert result["intent"] == "question"
    assert result["reply"] == "基于上下文的回答。"
    assert "case-1" in router.prompts[-1] and "研究问题" in router.prompts[-1]
    assert any(c["type"] == "case" and c["case_id"] == "case-1" for c in result["cards"])


def test_command_answer_case_question_read_only(tmp_path: Path) -> None:
    """T3 answer_case_question：只读直答（文档数/标题）+ optional_actions 建议卡；零业务记录。"""
    research = _research(tmp_path)
    _case(research)
    _doc(research, "case-1", "drev-a", "doc-a", seq=1)
    _doc(research, "case-1", "drev-b", "doc-b", seq=2)
    wf = FakeWorkflows(research)
    result = asyncio.run(
        run_chat_command(
            "当前 Case 只有几篇文章？",
            [],
            bronze=None,
            store=None,
            gold=None,
            registry=None,
            research=research,
            workflows=wf,
            case_id="case-1",
        )
    )
    assert result["intent"] == "answer_case_question"
    assert result["message_type"] == "answer"
    assert "2" in result["reply"]
    # 只读：不触发工作流、不创建 analysis_run（chat 消息持久化在 API 层）
    assert wf.calls == []
    assert research.analysis_runs() == []
    actions = next(c for c in result["cards"] if c["type"] == "optional_actions")
    assert actions["needs_confirmation"] is False
    assert actions["actions"]
    # 无 case 上下文 → abstention + 根因
    result2 = asyncio.run(
        run_chat_command(
            "当前 Case 只有几篇文章？",
            [],
            bronze=None,
            store=None,
            gold=None,
            registry=None,
            research=research,
        )
    )
    assert result2["message_type"] == "abstention"
    assert "未提供 case_id" in result2["reply"]


# ---------------------------------------------------------------- ChatStore 持久化


def test_chat_store_cards_roundtrip(tmp_path: Path) -> None:
    """cards 随消息持久化：append 写 JSON，messages 读回结构化列表。"""
    cs = ChatStore(tmp_path / "chat.sqlite")
    cs.append("t1", "user", "拆解这篇文档", T)
    cs.append(
        "t1",
        "assistant",
        "已触发 DissectDocument",
        T,
        message_type="tool_call",
        cards=[{"type": "progress", "run_id": "run-1", "kind": "dissect", "status": "queued"}],
    )
    msgs = cs.messages("t1")
    assert msgs[0]["cards"] == []
    assert msgs[1]["message_type"] == "tool_call"
    assert msgs[1]["cards"][0]["run_id"] == "run-1"


def test_chat_store_legacy_db_cards_migration(tmp_path: Path) -> None:
    """旧库（无 cards_json 列）打开即幂等补列，历史消息 cards=[]。"""
    db = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE chat_messages ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " thread_id TEXT NOT NULL, role TEXT NOT NULL,"
        " content TEXT NOT NULL, ts TEXT NOT NULL,"
        " message_type TEXT NOT NULL DEFAULT 'answer')"
    )
    conn.execute(
        "INSERT INTO chat_messages (thread_id, role, content, ts)"
        " VALUES ('t0', 'assistant', '旧消息', '2026-01-01T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()
    cs = ChatStore(db)
    msgs = cs.messages("t0")
    assert msgs[0]["cards"] == []
    cs.append(
        "t0",
        "assistant",
        "新消息",
        "2026-01-02T00:00:00+00:00",
        message_type="progress",
        cards=[{"type": "progress", "run_id": "r", "kind": "report", "status": "queued"}],
    )
    assert cs.messages("t0")[1]["cards"][0]["kind"] == "report"


def test_command_read_only_constraint_blocks_write(tmp_path: Path) -> None:
    """P0-1：用户否定约束下，执行类意图绝不触发工作流（最高优先级）。"""
    research = _research(tmp_path)
    _case(research)
    _doc(research, "case-1", "drev-a", "doc-a", seq=1)
    _doc(research, "case-1", "drev-b", "doc-b", seq=2)
    wf = FakeWorkflows(research)
    result = asyncio.run(
        run_chat_command(
            "仅基于当前 Case 比较两篇文档是否同一事件，不要创建保存修改",
            [],
            bronze=None,
            store=None,
            gold=None,
            registry=None,
            research=research,
            workflows=wf,
            case_id="case-1",
        )
    )
    assert result["read_only_forced"] is True
    assert result["message_type"] == "abstention"
    assert "不会创建" in result["reply"]
    assert wf.calls == []
    assert not any(c["type"] in ("tool_call", "progress") for c in result["cards"])


def test_command_write_requires_confirmation_card(tmp_path: Path) -> None:
    """P0-1：未确认的写操作返回 confirm_action 预览卡，不触发工作流。"""
    research = _research(tmp_path)
    _case(research)
    _doc(research, "case-1", "drev-a", "doc-a", seq=1)
    _doc(research, "case-1", "drev-b", "doc-b", seq=2)
    wf = FakeWorkflows(research)
    result = asyncio.run(
        run_chat_command(
            "比较这两篇文档",
            [],
            bronze=None,
            store=None,
            gold=None,
            registry=None,
            research=research,
            workflows=wf,
            case_id="case-1",
        )
    )
    conf = [c for c in result["cards"] if c["type"] == "confirm_action"]
    assert len(conf) == 1
    assert conf[0]["needs_confirmation"] is True
    assert conf[0]["intent"] == "compare"
    assert result["message_type"] == "hitl_request"
    assert wf.calls == []
    assert not any(c["type"] == "progress" for c in result["cards"])


def test_command_confirmed_channel_executes(tmp_path: Path) -> None:
    """P0-1：confirmed=True 放行写操作门，正常触发工作流。"""
    research = _research(tmp_path)
    _case(research)
    _doc(research, "case-1", "drev-a", "doc-a", seq=1)
    _doc(research, "case-1", "drev-b", "doc-b", seq=2)
    wf = FakeWorkflows(research)
    result = asyncio.run(
        run_chat_command(
            "比较这两篇文档",
            [],
            bronze=None,
            store=None,
            gold=None,
            registry=None,
            research=research,
            workflows=wf,
            case_id="case-1",
            confirmed=True,
        )
    )
    assert any(c["type"] == "tool_call" for c in result["cards"])
    assert not any(c["type"] == "confirm_action" for c in result["cards"])
    assert len(wf.calls) == 1 and wf.calls[0][0] == "compare"
