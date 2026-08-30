"""实体 canonical registry（数据科学家裁决：Wikidata QID + 多语言别名 + 父子关系边）。

关键语义（数据科学家 P1-1）：Fed ≠ FOMC —— FOMC 是 Fed 的下属委员会，
建模为父子关系而非等价别名合并；`match` 返回命中的具体实体，
跨实体聚合用 `family` 沿 parent 边展开。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class EntitySpec:
    """canonical 实体：稳定 entity_id + 多语言别名 + 可选父子关系 + 类型先验。

    entity_type 对应 ranking.entity_importance 的先验键
    （central_bank/government/company_systemic/company/person/other），
    供 Intelligence Score 的 importance 因子消费。
    """

    entity_id: str
    aliases: tuple[str, ...]
    entity_type: str = "other"
    parent_id: str | None = None
    wikidata_qid: str | None = None


DEFAULT_ENTITIES: tuple[EntitySpec, ...] = (
    EntitySpec(
        "fed",
        ("Federal Reserve", "the Fed", "US central bank", "Fed", "美联储", "美国联储", "联储局"),
        entity_type="central_bank",
        wikidata_qid="Q16554",
    ),
    EntitySpec(
        "fomc",
        ("FOMC", "Federal Open Market Committee", "联邦公开市场委员会", "联储议息会议"),
        entity_type="central_bank",
        parent_id="fed",
        wikidata_qid="Q11417",
    ),
    EntitySpec(
        "pboc",
        ("People's Bank of China", "PBoC", "PBOC", "中国人民银行", "中国央行"),
        entity_type="central_bank",
        wikidata_qid="Q1624368",
    ),
    EntitySpec(
        "ecb",
        ("European Central Bank", "ECB", "欧洲央行", "欧央行", "欧元区央行"),
        entity_type="central_bank",
        wikidata_qid="Q217344",
    ),
    EntitySpec(
        "boj",
        ("Bank of Japan", "BOJ", "日本央行", "日银", "日本银行"),
        entity_type="central_bank",
        wikidata_qid="Q844731",
    ),
    EntitySpec(
        "boe",
        ("Bank of England", "BoE", "英格兰银行", "英国央行"),
        entity_type="central_bank",
        wikidata_qid="Q178845",
    ),
    EntitySpec(
        "us_treasury",
        ("U.S. Treasury", "US Treasury", "Treasury Department", "美国财政部"),
        entity_type="government",
        wikidata_qid="Q51011",
    ),
    EntitySpec(
        "china_mof",
        ("中国财政部", "财政部", "Ministry of Finance of China", "PRC Ministry of Finance"),
        entity_type="government",
    ),
    EntitySpec(
        "state_council",
        ("State Council", "中国国务院", "国务院"),
        entity_type="government",
        wikidata_qid="Q165345",
    ),
    EntitySpec(
        "ndrc",
        ("NDRC", "国家发改委", "国家发展和改革委员会", "发改委"),
        entity_type="government",
    ),
    EntitySpec(
        "csrc",
        ("CSRC", "证监会", "中国证监会", "China Securities Regulatory Commission"),
        entity_type="government",
    ),
    EntitySpec(
        "white_house",
        ("White House", "白宫", "the Biden administration", "the Trump administration"),
        entity_type="government",
        wikidata_qid="Q35731",
    ),
    EntitySpec(
        "us_congress",
        ("US Congress", "U.S. Congress", "Congress", "美国国会", "参议院", "众议院"),
        entity_type="government",
        wikidata_qid="Q11268",
    ),
    EntitySpec(
        "trump",
        ("Trump", "特朗普", "川普", "Donald Trump"),
        entity_type="person",
        wikidata_qid="Q22686",
    ),
    EntitySpec(
        "xi_jinping",
        ("Xi Jinping", "习近平"),
        entity_type="person",
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
        ("OPEC", "欧佩克", "石油输出国组织"),
        wikidata_qid="Q131055",
    ),
    # —— 市场与科技高频主体（词级结构解析 v2 扩充）——
    EntitySpec(
        "powell",
        ("Jerome Powell", "Jay Powell", "Powell", "鲍威尔", "鲍尔"),
        entity_type="person",
        wikidata_qid="Q1088480",
    ),
    EntitySpec(
        "musk",
        ("Elon Musk", "Musk", "马斯克"),
        entity_type="person",
        wikidata_qid="Q317521",
    ),
    EntitySpec(
        "nvidia",
        ("Nvidia", "NVIDIA", "英伟达"),
        entity_type="company_systemic",
        wikidata_qid="Q1162163",
    ),
    EntitySpec(
        "tesla",
        ("Tesla", "特斯拉"),
        entity_type="company_systemic",
        wikidata_qid="Q478214",
    ),
    EntitySpec(
        "apple",
        ("Apple", "苹果公司"),
        entity_type="company_systemic",
        wikidata_qid="Q312",
    ),
    EntitySpec(
        "microsoft",
        ("Microsoft", "微软"),
        entity_type="company_systemic",
        wikidata_qid="Q2283",
    ),
    EntitySpec(
        "google",
        ("Google", "Alphabet", "谷歌"),
        entity_type="company_systemic",
        wikidata_qid="Q95",
    ),
    EntitySpec(
        "openai",
        ("OpenAI", "Sam Altman", "Altman", "奥尔特曼", "奥特曼"),
        entity_type="company_systemic",
        wikidata_qid="Q19864517",
    ),
    EntitySpec(
        "ustr",
        (
            "United States Trade Representative",
            "U.S. Trade Representative",
            "美国贸易代表办公室",
            "贸易代表",
        ),
        entity_type="government",
        wikidata_qid="Q17149786",
    ),
    EntitySpec(
        "sec",
        ("Securities and Exchange Commission", "美国证券交易委员会"),
        entity_type="government",
        wikidata_qid="Q568481",
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

    def entity_type(self, entity_id: str) -> str:
        """实体类型先验键（ranking.entity_importance 消费）。"""
        return self._by_id[entity_id].entity_type

    def types(self) -> dict[str, str]:
        """全量 entity_id → entity_type 映射（entity_id 确定性排序）。"""
        return {eid: spec.entity_type for eid, spec in sorted(self._by_id.items())}

    def match(self, text: str) -> list[str]:
        """返回文本命中的 entity_id（去重保序；子实体与父实体可同时命中）。"""
        seen: list[str] = []
        for eid, _s, _e, _a in self.match_with_positions(text):
            if eid not in seen:
                seen.append(eid)
        return seen

    def match_with_positions(self, text: str) -> list[tuple[str, int, int, str]]:
        """词级实体定位：[(entity_id, start, end, matched_alias)]。

        ASCII 别名用 \\b 词边界匹配（根治 "the fed"⊂"the federal" 类误命中），
        中文别名子串匹配；同一位置重叠命中保留更长别名，输出按 start 排序。
        """
        low = text.lower()
        raw: list[tuple[int, int, str, str]] = []
        for alias, eid in self._index:
            if alias.isascii():
                for m in re.finditer(rf"\b{re.escape(alias)}\b", low):
                    raw.append((m.start(), m.end(), eid, alias))
            else:
                start = 0
                while (i := low.find(alias, start)) != -1:
                    raw.append((i, i + len(alias), eid, alias))
                    start = i + 1
        raw.sort(key=lambda t: (t[0], -(t[1] - t[0])))
        picked: list[tuple[str, int, int, str]] = []
        last_end = -1
        for s, e, eid, alias in raw:
            if s >= last_end:
                picked.append((eid, s, e, alias))
                last_end = e
        return picked

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
