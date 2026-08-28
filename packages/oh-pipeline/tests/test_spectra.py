"""句级叙事光谱测试（spectra 纯函数）。"""

from __future__ import annotations

from oh_pipeline.spectra import sentence_spectrum, split_sentences


def test_split_sentences_zh_and_newline() -> None:
    text = "衰退风险上升。市场损失惨重！\n裁员加剧；失业恶化"
    assert split_sentences(text) == [
        "衰退风险上升。",
        "市场损失惨重！",
        "裁员加剧；",
        "失业恶化",
    ]


def test_split_sentences_keeps_decimals() -> None:
    # v0 设计：不切英文句号，小数/缩写不被打断
    assert split_sentences("growth at 0.5 percent risk rises") == [
        "growth at 0.5 percent risk rises"
    ]


def test_spectrum_hit_and_neutral() -> None:
    sents = sentence_spectrum("衰退风险上升。今天天气不错。")
    assert sents[0]["frame"] == "loss"
    assert sents[0]["hits"]["loss"] >= 2
    assert "衰退" in sents[0]["keywords"]
    assert sents[1]["frame"] is None
    assert sents[1]["hits"] == {}


def test_spectrum_stance_keywords() -> None:
    # "批评"（负立场）+"政策失败"：失败不在中文线索词表（有"失误"无"失败"）
    # → frame=None 但 stance=critical——光谱捕捉立场句而文章级不产行的场景
    sents = sentence_spectrum("官员批评政策失败。")
    assert sents[0]["stance"] == "critical"
    assert sents[0]["frame"] is None
    pos = sentence_spectrum("市场欢迎改善并称赞复苏。")
    assert pos[0]["stance"] == "supportive"
    assert pos[0]["frame"] == "gain"


def test_spectrum_empty_and_other_frame() -> None:
    assert sentence_spectrum("") == []
    assert sentence_spectrum("   \n  ") == []
    # other 框架词表为空，句中无任何命中 → frame None
    s = sentence_spectrum("一份普通陈述。")
    assert s[0]["frame"] is None
