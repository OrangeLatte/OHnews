"""采集器注册表 + YAML 配置装配（config/sources.yaml → adapters）。"""

from __future__ import annotations

from oh_contracts.enums import ArticleType, SourceTier
from oh_contracts.schemas import SourceMeta

from oh_sources.base import SourceAdapter
from oh_sources.fred import FredSeriesAdapter
from oh_sources.gdelt import GDELTDocAdapter
from oh_sources.rss import RssAdapter


class CollectorRegistry:
    """source_id → SourceAdapter 注册表（裁决 C）。"""

    def __init__(self) -> None:
        self._adapters: dict[str, SourceAdapter] = {}

    def register(self, adapter: SourceAdapter) -> None:
        if adapter.source_id in self._adapters:
            raise ValueError(f"source_id 重复注册: {adapter.source_id}")
        self._adapters[adapter.source_id] = adapter

    def get(self, source_id: str) -> SourceAdapter:
        try:
            return self._adapters[source_id]
        except KeyError as exc:
            raise ValueError(f"未注册的 source_id: {source_id}") from exc

    def all(self) -> list[SourceAdapter]:
        return list(self._adapters.values())


def _build_meta(spec: dict) -> SourceMeta:
    return SourceMeta(
        source_id=str(spec["source_id"]),
        language=str(spec.get("language", "zh")),  # type: ignore[arg-type]
        tier=SourceTier(spec["tier"]),
        credibility_prior=float(spec.get("credibility_prior", 0.7)),
        bias=spec.get("bias"),
        rate_limit_rpm=int(spec.get("rate_limit_rpm", 30)),
        needs_browser=bool(spec.get("needs_browser", False)),
        paywall=bool(spec.get("paywall", False)),
    )


def build_registry(config: dict) -> CollectorRegistry:
    """从 sources.yaml 解析出的 dict 装配注册表。

    Args:
        config: {"sources": [{source_id, adapter, tier, language, ..., params}]}。

    Raises:
        ValueError: 未知 adapter 类型或缺必填参数。
    """
    registry = CollectorRegistry()
    for spec in config.get("sources", []):
        meta = _build_meta(spec)
        kind = str(spec["adapter"])
        params: dict = spec.get("params", {})
        if kind == "rss":
            adapter: SourceAdapter = RssAdapter(
                meta,
                url=str(params["url"]),
                article_type=ArticleType(spec.get("article_type", "wire")),
            )
        elif kind == "gdelt":
            adapter = GDELTDocAdapter(
                meta,
                query=str(params["query"]),
                max_records=int(params.get("max_records", 75)),
            )
        elif kind == "fred":
            adapter = FredSeriesAdapter(meta, series_id=str(params["series_id"]))
        else:
            raise ValueError(f"未知适配器类型: {kind} (source_id={meta.source_id})")
        registry.register(adapter)
    return registry
