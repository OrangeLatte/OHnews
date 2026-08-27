"""实体 registry：父子关系不合并（Fed ≠ FOMC）+ 别名匹配语义。"""

from __future__ import annotations

import pytest
from oh_pipeline.entities import DEFAULT_ENTITIES, EntityRegistry, EntitySpec


@pytest.fixture()
def reg() -> EntityRegistry:
    return EntityRegistry()


def test_fomc_is_child_not_alias_of_fed(reg: EntityRegistry) -> None:
    """数据科学家 P1-1：FOMC 是 Fed 下属委员会，命中具体实体不向父归并。"""
    hits = reg.match("The FOMC minutes were released")
    assert hits == ["fomc"]


def test_parent_and_family(reg: EntityRegistry) -> None:
    assert reg.parent("fomc") == "fed"
    assert reg.parent("fed") is None
    family = reg.family("fed")
    assert {"fed", "fomc"} <= family


def test_multi_entity_match_dedup(reg: EntityRegistry) -> None:
    hits = reg.match("美联储与 FOMC 的分歧")
    assert set(hits) == {"fed", "fomc"}
    assert len(hits) == len(set(hits))


def test_multilingual_aliases(reg: EntityRegistry) -> None:
    assert "ecb" in reg.match("欧洲央行宣布利率决议")
    assert "pboc" in reg.match("中国人民银行开展逆回购操作")
    assert "trump" in reg.match("Trump threatens new tariffs")


def test_no_match_returns_empty(reg: EntityRegistry) -> None:
    assert reg.match("今天天气不错") == []


def test_match_is_case_insensitive(reg: EntityRegistry) -> None:
    assert "fed" in reg.match("the FED and federal reserve officials")


def test_duplicate_entity_id_rejected() -> None:
    dup = (
        EntitySpec("fed", ("a",)),
        EntitySpec("fed", ("b",)),
    )
    with pytest.raises(ValueError, match="重复"):
        EntityRegistry(dup)


def test_default_registry_size(reg: EntityRegistry) -> None:
    assert len(reg.ids()) == len(DEFAULT_ENTITIES)
