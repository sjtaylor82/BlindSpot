"""Experimental access to a community-maintained Billboard Hot 100 archive."""

from __future__ import annotations

import bisect
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date

from .i18n import tr
from .network import TLS_CONTEXT

PROJECT_URL = "https://github.com/mhollingshead/billboard-hot-100"
RAW_ROOT = (
    "https://raw.githubusercontent.com/mhollingshead/"
    "billboard-hot-100/main"
)


class HistoricalChartError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class HistoricalChartEntry:
    name: str
    artist: str
    rank: int
    previous_rank: int | None = None
    peak_rank: int | None = None
    weeks: int | None = None


@dataclass(frozen=True, slots=True)
class HistoricalChart:
    chart_date: date
    entries: list[HistoricalChartEntry]


class HistoricalHot100Client:
    def __init__(self) -> None:
        self._dates: list[str] | None = None

    def chart_for_date(self, requested: date) -> HistoricalChart:
        dates = self._valid_dates()
        wanted = requested.isoformat()
        position = bisect.bisect_right(dates, wanted) - 1
        if position < 0:
            raise HistoricalChartError(
                tr(
                    "The experimental US Hot 100 archive begins on 4 August "
                    "1958."
                )
            )
        chart_date = dates[position]
        payload = self._request(f"{RAW_ROOT}/date/{chart_date}.json")
        entries = []
        for value in payload.get("data") or []:
            name = str(value.get("song") or "").strip()
            artist = str(value.get("artist") or "").strip()
            if not name or not artist:
                continue
            entries.append(
                HistoricalChartEntry(
                    name,
                    artist,
                    int(value.get("this_week") or len(entries) + 1),
                    self._optional_int(value.get("last_week")),
                    self._optional_int(value.get("peak_position")),
                    self._optional_int(value.get("weeks_on_chart")),
                )
            )
        return HistoricalChart(date.fromisoformat(chart_date), entries)

    def _valid_dates(self) -> list[str]:
        if self._dates is None:
            values = self._request(f"{RAW_ROOT}/valid_dates.json")
            if not isinstance(values, list):
                raise HistoricalChartError(
                    tr(
                        "The experimental chart archive returned an "
                        "unreadable date list."
                    )
                )
            self._dates = sorted(str(value) for value in values)
        return self._dates

    @staticmethod
    def _optional_int(value: object) -> int | None:
        return int(value) if value is not None else None

    def _request(self, url: str):
        request = urllib.request.Request(url, headers={"User-Agent": "BlindSpot"})
        try:
            with urllib.request.urlopen(
                request, timeout=10, context=TLS_CONTEXT
            ) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            raise HistoricalChartError(
                tr(
                    "The experimental US Hot 100 archive could not be "
                    "reached."
                )
            ) from error
