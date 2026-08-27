"""实体 canonical registry（数据科学家裁决：Wikidata QID + 多语言别名 + 父子关系边）。

关键语义（数据科学家 P1-1）：Fed ≠ FOMC —— FOMC 是 Fed 的下属委员会，
建模为父子关系而非等价别名合并；`match` 返回命中的具体实体，
跨实体聚合用 `family` 沿 parent 边展开。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EntitySpec:
    """canonical 实体：稳定 entity_id + 多语言别名 + 可选父子关系。"""

    entity_id: str
    aliases: tuple[str, ...]
    parent_id: str | None = None
    wikidata_qid: str | None = None


DEFAULT_ENTITIES: tuple[EntitySpec, ...] = (
    EntitySpec(
        "fed",
        ("Federal Reserve", "the Fed", "US central bank", "美联储", "美国联储", "联储局"),
        wikidata_qid="Q16554",
    ),
    EntitySpec(
        "fomc",
        ("FOMC", "Federal Open Market Committee", "联邦公开市场委员会", "联储议息会议"),
        parent_id="fed",
        wikidata_qid="Q11417",
    ),
    EntitySpec(
        "pboc",
        ("People's Bank of China", "PBoC", "PBOC", "中国人民银行", "中国央行"),
        wikidata_qid="Q1624368",
    ),
    EntitySpec(
        "ecb",
        ("European Central Bank", "ECB", "欧洲央行", "欧央行", "欧元区央行"),
        wikidata_qid="Q217344",
    ),
    EntitySpec(
        "boj",
        ("Bank of Japan", "BOJ", "日本央行", "日银", "日本银行"),
        wikidata_qid="Q844731",
    ),
    EntitySpec(
        "boe",
        ("Bank of England", "BoE", "英格兰银行", "英国央行"),
        wikidata_qid="Q178845",
    ),
    EntitySpec(
        "us_treasury",
        ("U.S. Treasury", "US Treasury", "Treasury Department", "美国财政部"),
        wikidata_qid="Q51011",
    ),
    EntitySpec(
        "china_mof",
        ("中国财政部", "财政部", "Ministry of Finance of China", "PRC Ministry of Finance"),
    ),
    EntitySpec(
        "state_council",
        ("State Council", "中国国务院", "国务院"),
        wikidata_qid="Q165345",
    ),
    EntitySpec(
        "ndrc",
        ("NDRC", "国家发改委", "国家发展和改革委员会", "发改委"),
    ),
    EntitySpec(
        "csrc",
        ("CSRC", "证监会", "中国证监会", "China Securities Regulatory Commission"),
    ),
    EntitySpec(
        "white_house",
        ("White House", "白宫", "the Biden administration", "the Trump administration"),
        wikidata_qid="Q35731",
    ),
    EntitySpec(
        "us_congress",
        ("US Congress", "U.S. Congress", "Congress", "美国国会", "参议院", "众议院"),
        wikidata_qid="Q11268",
    ),
    EntitySpec(
        "trump",
        ("Trump", "特朗普", "川普", "Donald Trump"),
        wikidata_qid="Q22686",
    ),
    EntitySpec(
        "xi_jinping",
        ("Xi Jinping", "习近平"),
        wikidata_qid="Q15933",
    ),
    EntitySpec(
        "imf",
        ("IMF", "International Monetary Fund", "国际货币基金组织"),
        wikidata_qid="Q1064",
    ),
    EntitySpec(
        "world_bank",
        ("World Bank", "世界银行"),
        wikidata_qid="Q217402",
    ),
    EntitySpec(
        "opec",
        ("OPEC", "OPEC+", "石油输出国组织", "欧佩克"),
        wikidata_qid="Q4603",
    ),
)

_MIN_ALIAS_LEN = 2


class EntityRegistry:
    """实体注册表：别名索引匹配（长别名优先，命中具体实体不向父归并）。"""

    def __init__(self, entities: tuple[EntitySpec, ...] = DEFAULT_ENTITIES) -> None:
        self._by_id: dict[str, EntitySpec] = {e.entity_id: e for e in entities}
        if len(self._by_id) != len(entities):
            raise ValueError("entity_id 重复")
        # (alias_lower, entity_id) 长别名优先排序，防短别名抢先命中
        self._index: list[tuple[str, str]] = sorted(
            (
                (alias.lower(), eid)
                for eid, e in self._by_id.items()
                for alias in e.aliases
                if len(alias) >= _MIN_ALIAS_LEN
            ),
            key=lambda p: len(p[0]),
            reverse=True,
        )

    def get(self, entity_id: str) -> EntitySpec:
        return self._by_id[entity_id]

    def ids(self) -> tuple[str, ...]:
        return tuple(self._by_id)

    def match(self, text: str) -> list[str]:
        """返回文本命中的 entity_id（去重保序；子实体与父实体可同时命中）。"""
        low = text.lower()
        hits: list[str] = []
        for alias, eid in self._index:
            if alias in low and eid not in hits:
                hits.append(eid)
        return hits

    def parent(self, entity_id: str) -> str | None:
        return self._by_id[entity_id].parent_id

    def family(self, entity_id: str) -> frozenset[str]:
        """实体及其全部后代（沿 parent 边向下），用于跨别名聚合。"""
        result = {entity_id}
        changed = True
        while changed:
            changed = False
            for e in self._by_id.values():
                if e.parent_id in result and e.entity_id not in result:
                    result.add(e.entity_id)
                    changed = True
        return frozenset(result)
