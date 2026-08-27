"""OH!News 采集层：SourceAdapter 框架（裁决 C）+ 免费源适配器 + 健康度治理。"""

from oh_sources.base import USER_AGENT, Draft, SourceAdapter
from oh_sources.fred import FredSeriesAdapter
from oh_sources.gdelt import GDELTDocAdapter
from oh_sources.health import SourceHealthTracker
from oh_sources.registry import CollectorRegistry, build_registry
from oh_sources.rss import RssAdapter
from oh_sources.runner import FetchResult, collect_all, run_collector

__all__ = [
    "USER_AGENT",
    "CollectorRegistry",
    "Draft",
    "FetchResult",
    "FredSeriesAdapter",
    "GDELTDocAdapter",
    "RssAdapter",
    "SourceAdapter",
    "SourceHealthTracker",
    "build_registry",
    "collect_all",
    "run_collector",
]
