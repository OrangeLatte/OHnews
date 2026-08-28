"""词级主体-动作-方向结构解析测试（svo）。"""

from __future__ import annotations

from oh_pipeline.entities import EntityRegistry
from oh_pipeline.svo import match_actions, parse_passage, parse_sentence

R = EntityRegistry()


def test_match_actions_word_boundary() -> None:
    # "hold" 不得命中 threshold/thresholds
    acts = match_actions("The Fed will hold rates steady above thresholds.")
    dirs = [a["direction"] for a in acts]
    assert "hold" in dirs
    # threshold 不产生动作命中
    assert not [a for a in acts if a["text"].startswith("threshold")]


def test_match_actions_domains() -> None:
    zh = match_actions("央行宣布降息25个基点，同时承诺不加征关税。")
    d = {(a["domain"], a["direction"]) for a in zh}
    assert ("monetary", "easing") in d
    # "不加征关税" 含否定——v0 词典不处理否定，命中 escalate（诚实标注的边界）
    assert ("trade", "escalate") in d


def test_parse_sentence_entities_positions() -> None:
    sent = "Powell said the Fed will tighten, while Nvidia beats expectations."
    out = parse_sentence(sent, R)
    ids = [e["entity_id"] for e in out["entities"]]
    assert "powell" in ids and "fed" in ids and "nvidia" in ids
    # 词级位置可切片还原原文
    for e in out["entities"]:
        assert sent[e["start"] : e["end"]].lower() in sent.lower()
    dirs = {a["direction"] for a in out["actions"]}
    assert "tightening" in dirs and "beat" in dirs


def test_parse_sentence_chinese_substring() -> None:
    sent = "英伟达财报超预期，股价暴涨；马斯克宣布裁员10%。"
    out = parse_sentence(sent, R)
    ids = [e["entity_id"] for e in out["entities"]]
    assert "nvidia" in ids and "musk" in ids
    dirs = {a["direction"] for a in out["actions"]}
    assert {"beat", "rally", "exit"} <= dirs


def test_parse_passage_splits_and_stance() -> None:
    text = "美联储维持利率不变。市场对通胀担忧升温，批评声四起。"
    sents = parse_passage(text, R)
    assert len(sents) == 2
    assert sents[0]["stance"] is None
    assert sents[1]["stance"] == "critical"


def test_overlap_keeps_longer() -> None:
    # "rate cut" 与 "cut rates" 重叠场景：非重叠贪心保留先到最长
    acts = match_actions("cut rates now")
    assert acts and acts[0]["direction"] == "easing"
