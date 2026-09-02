"""Phase D ArchiveStore：三档案库 + 报纸（确认式存档，store 纯读写）。"""

from oh_agents.archive import ArchiveStore


def _store(tmp_path):
    return ArchiveStore(tmp_path / "archive.sqlite")


def test_save_list_get_remove_roundtrip(tmp_path) -> None:
    s = _store(tmp_path)
    aid = s.save_item(
        kind="report",
        title="美联储暂停加息的真实性核查",
        ref_kind="report",
        ref_id="rp-abc12345",
        payload={"engine": "llm", "sections": []},
        note="用户确认存档",
    )
    assert aid.startswith("ar-")
    items = s.list_items("report")
    assert len(items) == 1 and items[0]["archive_id"] == aid
    got = s.get_item(aid)
    assert got is not None and got["payload"]["engine"] == "llm"
    assert s.remove_item(aid) is True
    assert s.get_item(aid) is None
    assert s.remove_item(aid) is False


def test_kind_filter_and_counts(tmp_path) -> None:
    s = _store(tmp_path)
    s.save_item(
        kind="dissection",
        title="拆解要素存档示例文本",
        ref_kind="dissection",
        ref_id="ik1",
        payload={},
    )
    s.save_item(
        kind="report", title="研究报告存档示例文本", ref_kind="report", ref_id="rp1", payload={}
    )
    assert s.counts() == {"dissection": 1, "report": 1}
    assert len(s.list_items("dissection")) == 1
    assert len(s.list_items()) == 2


def test_paper_roundtrip(tmp_path) -> None:
    s = _store(tmp_path)
    pid = s.save_paper(
        title="本期档案报纸：美联储专题", item_ids=["ar-1", "ar-2"], foreword="编者按"
    )
    assert pid.startswith("pp-")
    papers = s.list_papers()
    assert papers[0]["item_ids"] == ["ar-1", "ar-2"]
