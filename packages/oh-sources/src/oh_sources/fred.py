"""FRED 序列快照适配器（宏观基线回填，免 key：fredgraph.csv 端点）。

快照语义（PIT 纪律）：一次 fetch 产出一条 BronzeRecord（全量序列进 body），
external_id 含观察窗内最后一个有效观测日 → 新观测到达才产生新 item；
published_at = 该观测日（序列快照的"信息可得时点"近似下界）。
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime, time

import httpx
from oh_contracts.enums import ArticleType
from oh_contracts.schemas import SourceMeta

from oh_sources.base import USER_AGENT, Draft, SourceAdapter

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
_MISSING_VALUES = {"", "."}


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_csv(text: str) -> list[tuple[date, str]]:
    """fredgraph.csv → [(obs_date, value)]（纯函数，离线可测；首列日期末列值）。"""
    out: list[tuple[date, str]] = []
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or len(reader.fieldnames) < 2:
        return out
    for row in reader:
        obs_date = _parse_date(str(row[reader.fieldnames[0]]).strip())
        if obs_date is None:
            continue
        out.append((obs_date, str(row[reader.fieldnames[-1]]).strip()))
    return out


class FredSeriesAdapter(SourceAdapter):
    """单序列快照适配器：观察窗 [since, until] 内有新观测才产出新快照。"""

    def __init__(self, meta: SourceMeta, *, series_id: str) -> None:
        super().__init__(meta)
        self._series_id = series_id

    async def fetch(self, since: datetime, until: datetime) -> list[Draft]:
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
            text = await self.get_text(client, FRED_CSV_URL, params={"id": self._series_id})
        return self.snapshot_drafts(_parse_csv(text), since, until)

    def snapshot_drafts(
        self,
        rows: list[tuple[date, str]],
        since: datetime,
        until: datetime,
    ) -> list[Draft]:
        """行 → 快照 Draft（纯函数钩子，离线可测；窗内无有效观测返回空）。"""
        window = [
            (d, v)
            for d, v in rows
            if since.date() <= d <= until.date() and v not in _MISSING_VALUES
        ]
        if not window:
            return []
        last_obs = window[-1][0]
        body = "observation_date,value\n" + "\n".join(f"{d},{v}" for d, v in rows)
        return [
            Draft(
                external_id=f"{self._series_id}:{last_obs:%Y%m%d}",
                title=f"FRED {self._series_id} snapshot @{last_obs:%Y-%m-%d}",
                url=f"{FRED_CSV_URL}?id={self._series_id}",
                published_at=datetime.combine(last_obs, time.min, tzinfo=UTC),
                body=body,
                lang=self.meta.language,
                article_type=ArticleType.WIRE,
                raw={
                    "series_id": self._series_id,
                    "n_obs": len(rows),
                    "window_obs": len(window),
                },
            )
        ]
