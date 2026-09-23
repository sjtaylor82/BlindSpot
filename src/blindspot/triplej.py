"""Triple J Hottest 100 countdowns from the official ABC archive."""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from .i18n import tr
from .network import TLS_CONTEXT

logger = logging.getLogger(__name__)

ARCHIVE_URL = "https://www.abc.net.au/triplej/hottest100/archive/"
SEARCH_URL = f"{ARCHIVE_URL}search/"


class Hottest100Error(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Countdown:
    year: int
    special: bool
    label: str


@dataclass(frozen=True, slots=True)
class Hottest100Entry:
    name: str
    artist: str
    rank: int
    release_year: str = ""


# The order and names mirror the official archive. The actual results remain
# live ABC data; this small catalogue only makes every countdown selectable
# before the first network request.
COUNTDOWNS = (
    Countdown(2025, False, "2025"),
    Countdown(2025, True, "Of Australian Songs (2025)"),
    Countdown(2024, False, "2024"),
    Countdown(2023, False, "2023"),
    Countdown(2023, True, "Like A Version (2023)"),
    *(Countdown(year, False, str(year)) for year in range(2022, 2013, -1)),
    Countdown(2013, False, "2013"),
    Countdown(2013, True, "Twenty Years (2013)"),
    Countdown(2012, False, "2012"),
    Countdown(2011, False, "2011"),
    Countdown(2011, True, "Australian Albums (2011)"),
    *(Countdown(year, False, str(year)) for year in range(2010, 2008, -1)),
    Countdown(2009, True, "All-time (2009)"),
    *(Countdown(year, False, str(year)) for year in range(2008, 1997, -1)),
    Countdown(1998, True, "All-time (1998)"),
    *(Countdown(year, False, str(year)) for year in range(1997, 1992, -1)),
    Countdown(1991, True, "All-time (1991)"),
    Countdown(1990, True, "All-time (1990)"),
    Countdown(1989, True, "All-time (1989)"),
)


def _javascript_array(html: str, variable: str) -> list[dict]:
    """Decode a JSON-compatible JavaScript array assigned to ``variable``."""
    match = re.search(rf"\bvar\s+{re.escape(variable)}\s*=\s*", html)
    if not match:
        raise ValueError(variable)
    value, _end = json.JSONDecoder().raw_decode(html, match.end())
    if not isinstance(value, list):
        raise ValueError(variable)
    return [row for row in value if isinstance(row, dict)]


def parse_countdown(html: str, countdown: Countdown) -> list[Hottest100Entry]:
    entries = []
    for value in _javascript_array(html, "tracks"):
        if value.get("pollyear") != countdown.year:
            continue
        if bool(value.get("alltime")) != countdown.special:
            continue
        name = str(value.get("track") or "").strip()
        artist = str(value.get("artist") or "").strip()
        try:
            rank = int(value.get("position"))
        except (TypeError, ValueError):
            continue
        if name and artist and rank > 0:
            entries.append(
                Hottest100Entry(
                    name,
                    artist,
                    rank,
                    str(value.get("releaseyear") or "").strip(),
                )
            )
    return sorted(entries, key=lambda entry: entry.rank)


class Hottest100Client:
    def __init__(self) -> None:
        self._html: str | None = None

    def countdown(self, countdown: Countdown) -> list[Hottest100Entry]:
        logger.info(
            "Loading ABC Triple J Hottest 100 countdown year=%d special=%s",
            countdown.year,
            countdown.special,
        )
        try:
            entries = parse_countdown(self._archive_html(), countdown)
        except (ValueError, TypeError) as error:
            raise Hottest100Error(
                tr("The Triple J Hottest 100 archive could not be read.")
            ) from error
        if not entries:
            raise Hottest100Error(
                tr("That Triple J Hottest 100 countdown was not found.")
            )
        logger.info(
            "Loaded ABC Triple J Hottest 100 countdown year=%d special=%s "
            "entries=%d",
            countdown.year,
            countdown.special,
            len(entries),
        )
        return entries

    def _archive_html(self) -> str:
        if self._html is None:
            request = urllib.request.Request(
                SEARCH_URL, headers={"User-Agent": "BlindSpot"}
            )
            logger.debug("ABC Triple J archive request %s", SEARCH_URL)
            try:
                with urllib.request.urlopen(
                    request, timeout=15, context=TLS_CONTEXT
                ) as response:
                    self._html = response.read().decode("utf-8")
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                raise Hottest100Error(
                    tr("The Triple J Hottest 100 archive could not be reached.")
                ) from error
        return self._html
