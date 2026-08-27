"""采集器注册表 + YAML 配置装配（config/sources.yaml → adapters）。

Phase 1.5：支持 enabled 开关（用户选择性激活，未激活零开销——不建适配器、
不调度、不发请求）；新增 json_api/html/reddit_cdp 三种适配器分发。
"""

from __future__ import annotations

from oh_contracts.enums import ArticleType, SourceTier
from oh_contracts.schemas import SourceMeta

from oh_sources.base import SourceAdapter
from oh_sources.fred import FredSeriesAdapter
from oh_sources.gdelt import GDELTDocAdapter
from oh_sources.html import HtmlAdapter
from oh_sources.json_api import JsonApiAdapter
from oh_sources.reddit_cdp import RedditCdpAdapter
from oh_sources.rss import RssAdapter


class CollectorRegistry:
    """source_id → SourceAdapter 注册表（裁决 C）+ 备用源链（fallbacks）。"""

    def __init__(self) -> None:
        self._adapters: dict[str, SourceAdapter] = {}
        self._fallbacks: dict[str, list[SourceAdapter]] = {}

    def register(self, adapter: SourceAdapter) -> None:
        if adapter.source_id in self._adapters:
            raise ValueError(f"source_id 重复注册: {adapter.source_id}")
        self._adapters[adapter.source_id] = adapter

    def set_fallbacks(self, source_id: str, adapters: list[SourceAdapter]) -> None:
        """注册主源失败时的备用源采集链（按序尝试，全部失败才报错）。"""
        if adapters:
            self._fallbacks[source_id] = adapters

    def get(self, source_id: str) -> SourceAdapter:
        try:
            return self._adapters[source_id]
        except KeyError as exc:
            raise ValueError(f"未注册的 source_id: {source_id}") from exc

    def fallbacks(self, source_id: str) -> list[SourceAdapter]:
        return list(self._fallbacks.get(source_id, []))

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


def _article_type(spec: dict) -> ArticleType:
    return ArticleType(spec.get("article_type", "wire"))


def _base_kwargs(params: dict) -> dict:
    """透传 base 通用回退参数：window_days（稀疏源窗口放大）/ proxy_url（显式代理）。"""
    kwargs: dict = {}
    if params.get("window_days") is not None:
        kwargs["window_days"] = int(params["window_days"])
    if params.get("proxy_url"):
        kwargs["proxy_url"] = str(params["proxy_url"])
    return kwargs


def _build_adapter(kind: str, meta: SourceMeta, params: dict) -> SourceAdapter:
    if kind == "rss":
        return RssAdapter(
            meta,
            url=str(params["url"]),
            article_type=_article_type(params),
            date_fallback=bool(params.get("date_fallback", False)),
            **_base_kwargs(params),
        )
    if kind == "gdelt":
        return GDELTDocAdapter(
            meta,
            query=str(params["query"]),
            max_records=int(params.get("max_records", 75)),
            proxy_fallback=bool(params.get("proxy_fallback", False)),
            **_base_kwargs(params),
        )
    if kind == "fred":
        return FredSeriesAdapter(meta, series_id=str(params["series_id"]))
    if kind == "json_api":
        return JsonApiAdapter(
            meta,
            url=str(params["url"]),
            items_path=str(params["items_path"]),
            params={k: str(v) for k, v in (params.get("params") or {}).items()} or None,
            headers={k: str(v) for k, v in (params.get("headers") or {}).items()} or None,
            external_id_path=params.get("external_id_path"),
            title_path=params.get("title_path"),
            body_path=params.get("body_path"),
            url_path=params.get("url_path"),
            url_template=params.get("url_template"),
            published_path=params.get("published_path"),
            date_formats=params.get("date_formats"),
            tz_offset_hours=int(params.get("tz_offset_hours", 0)),
            article_type=_article_type(params),
            queries=[str(q) for q in params["queries"]] if params.get("queries") else None,
            **_base_kwargs(params),
        )
    if kind == "html":
        return HtmlAdapter(
            meta,
            list_url=str(params["list_url"]),
            item_selector=str(params["item_selector"]),
            params={k: str(v) for k, v in (params.get("params") or {}).items()} or None,
            headers={k: str(v) for k, v in (params.get("headers") or {}).items()} or None,
            encoding=params.get("encoding"),
            link_attr=str(params.get("link_attr", "href")),
            date_regex=str(params.get("date_regex", r"\d{4}-\d{2}-\d{2}")),
            date_formats=params.get("date_formats"),
            tz_offset_hours=int(params.get("tz_offset_hours", 8)),
            date_scope=str(params.get("date_scope", "parent")),
            max_items=int(params.get("max_items", 30)),
            detail=params.get("detail"),
            article_type=_article_type(params),
            **_base_kwargs(params),
        )
    if kind == "reddit_cdp":
        return RedditCdpAdapter(
            meta,
            subreddits=[str(s) for s in params["subreddits"]],
            cookies_file=str(params.get("cookies_file", ".opencode/cookies/reddit.json")),
            limit=int(params.get("limit", 25)),
            article_type=_article_type(params),
            **_base_kwargs(params),
        )
    raise ValueError(f"未知适配器类型: {kind} (source_id={meta.source_id})")


def build_registry(config: dict) -> CollectorRegistry:
    """从 sources.yaml 解析出的 dict 装配注册表。

    enabled=false 的源直接跳过（不注册、零开销）；
    needs_browser=true 且源未被显式启用时同样注册（登录门源由用户开）。

    fallbacks 解析（两遍扫描）：
    - 条目为 source_id 字符串 → 引用其他已启用源（被禁用/不存在则跳过，降级不报错）
    - 条目为完整 spec dict → 内联备用源（不注册进主表，仅作 fallback 采集，
      以其自身 source_id 写 Bronze / 记健康度）

    Args:
        config: {"sources": [{source_id, adapter, tier, language, enabled?, params}]}

    Raises:
        ValueError: 未知 adapter 类型或缺必填参数。
    """
    registry = CollectorRegistry()
    specs = [s for s in config.get("sources", []) if bool(s.get("enabled", True))]
    by_id = {str(s["source_id"]): s for s in specs}
    for spec in specs:
        registry.register(
            _build_adapter(str(spec["adapter"]), _build_meta(spec), spec.get("params", {}))
        )
    for spec in specs:
        adapters: list[SourceAdapter] = []
        for fb in spec.get("fallbacks") or []:
            if isinstance(fb, str):
                if fb in by_id:
                    adapters.append(registry.get(fb))
            elif isinstance(fb, dict):
                adapters.append(
                    _build_adapter(str(fb["adapter"]), _build_meta(fb), fb.get("params", {}))
                )
        if adapters:
            registry.set_fallbacks(str(spec["source_id"]), adapters)
    return registry
