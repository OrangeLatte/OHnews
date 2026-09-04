"""专项 Agent 注册表测试（阶段 2 Agent OS）：9 项闭集与契约一致性。"""

from oh_agents.specialists import SPECIALIST_STATUSES, SPECIALISTS, specialist_ids
from oh_contracts.agent_runtime import WORKFLOWS


def test_registry_has_nine_unique_specialists() -> None:
    assert len(SPECIALISTS) == 9
    ids = [s["id"] for s in SPECIALISTS]
    assert len(set(ids)) == 9
    assert specialist_ids() == tuple(ids)


def test_expected_specialist_ids() -> None:
    assert set(specialist_ids()) == {
        "observe_analyst",
        "dissection",
        "translation_alignment",
        "cross_source_analyst",
        "report",
        "challenge",
        "source_expansion",
        "monitor",
        "archive_editor",
    }


def test_registry_entries_conform_to_contract() -> None:
    for s in SPECIALISTS:
        # endpoint 必须是合法 REST 路径形状（/api/ 开头，路径段非空）
        assert s["endpoint"].startswith("/api/")
        assert all(seg for seg in s["endpoint"].split("/")[1:])
        # workflow 只能是 11 值闭集之一或 None（无直接 workflow）
        assert s["workflow"] is None or s["workflow"] in WORKFLOWS
        assert s["status"] in SPECIALIST_STATUSES
        # 中英双语 title + 一句话中文 description
        assert "/" in str(s["title"]) and len(str(s["title"])) > 4
        assert isinstance(s["description"], str) and s["description"]
