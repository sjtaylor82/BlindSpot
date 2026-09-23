"""ABC Classic 100 listener-poll countdowns."""

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

ARCHIVE_URL = "https://www.abc.net.au/classic/classic100/archive/"
ARCHIVE_SEARCH_URL = f"{ARCHIVE_URL}search/"
CURRENT_URL = "https://www.abc.net.au/listen/classic/countdown/classic100"


class Classic100Error(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ClassicCountdown:
    year: int
    pollname: str
    label: str
    current: bool = False


@dataclass(frozen=True, slots=True)
class ClassicEntry:
    work: str
    composer: str
    rank: int


COUNTDOWNS = (
    ClassicCountdown(2026, "greatest", "Greatest of All Time (2026)", True),
    ClassicCountdown(2025, "piano", "Piano (2025)"),
    ClassicCountdown(2024, "feelgood", "Feel Good (2024)"),
    ClassicCountdown(2023, "instrument", "Your Favourite Instrument (2023)"),
    ClassicCountdown(2022, "screen", "Music for the Screen (2022)"),
    ClassicCountdown(2021, "livewithout", "Music You Can't Live Without (2021)"),
    ClassicCountdown(2020, "beethoven", "Beethoven (2020)"),
    ClassicCountdown(2019, "composers", "Composers (2019)"),
    ClassicCountdown(2018, "dance", "Dance (2018)"),
    ClassicCountdown(2017, "love", "Love (2017)"),
    ClassicCountdown(2016, "voice", "Voice (2016)"),
    ClassicCountdown(2015, "swoon", "Swoon (2015)"),
    ClassicCountdown(2014, "baroque", "Baroque (2014)"),
    ClassicCountdown(2013, "movies", "Music in the Movies (2013)"),
    ClassicCountdown(2012, "france", "Music of France (2012)"),
    ClassicCountdown(2011, "20thc", "20th Century (2011)"),
    ClassicCountdown(2010, "10years", "10 Years On (2010)"),
    ClassicCountdown(2009, "symphony", "Symphony (2009)"),
    ClassicCountdown(2008, "chamber", "Chamber Music (2008)"),
    ClassicCountdown(2007, "concerto", "Concerto (2007)"),
    ClassicCountdown(2006, "mozart", "Mozart (2006)"),
    ClassicCountdown(2005, "opera", "Opera (2005)"),
    ClassicCountdown(2004, "piano", "Piano (2004)"),
    ClassicCountdown(2001, "original", "Original (2001)"),
)


def _javascript_array(html: str, variable: str) -> list[dict]:
    match = re.search(rf"\bvar\s+{re.escape(variable)}\s*=\s*", html)
    if not match:
        raise ValueError(variable)
    value, _end = json.JSONDecoder().raw_decode(html, match.end())
    if not isinstance(value, list):
        raise ValueError(variable)
    return [row for row in value if isinstance(row, dict)]


def parse_archive(html: str, countdown: ClassicCountdown) -> list[ClassicEntry]:
    entries = []
    for value in _javascript_array(html, "tracks"):
        if value.get("pollyear") != countdown.year:
            continue
        if str(value.get("pollname") or "") != countdown.pollname:
            continue
        entry = _entry(value, "work", "composer")
        if entry:
            entries.append(entry)
    return sorted(entries, key=lambda entry: entry.rank)


def parse_current(html: str) -> list[ClassicEntry]:
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        raise ValueError("__NEXT_DATA__")
    payload = json.loads(match.group(1))
    components = payload["props"]["pageProps"]["data"]["componentsContent"]
    countdown = next(
        value for value in components if value.get("component") == "SongCountdown"
    )
    entries = []
    for value in countdown["componentProps"].get("songsPrepared") or []:
        entry = _entry(value, "title", "artist")
        if entry:
            entries.append(entry)
    return sorted(entries, key=lambda entry: entry.rank)


def _entry(value: dict, work_key: str, composer_key: str) -> ClassicEntry | None:
    work = str(value.get(work_key) or "").strip()
    composer = str(value.get(composer_key) or "").strip()
    try:
        rank = int(value.get("position"))
    except (TypeError, ValueError):
        return None
    if not work or not composer or rank < 1:
        return None
    return ClassicEntry(work, composer, rank)


class Classic100Client:
    def __init__(self) -> None:
        self._archive: str | None = None
        self._current: str | None = None

    def countdown(self, countdown: ClassicCountdown) -> list[ClassicEntry]:
        logger.info(
            "Loading ABC Classic 100 countdown year=%d poll=%s",
            countdown.year,
            countdown.pollname,
        )
        try:
            if countdown.current:
                entries = parse_current(self._current_html())
            else:
                entries = parse_archive(self._archive_html(), countdown)
        except (KeyError, StopIteration, TypeError, ValueError) as error:
            raise Classic100Error(
                tr("The ABC Classic 100 archive could not be read.")
            ) from error
        if not entries:
            raise Classic100Error(tr("That ABC Classic 100 countdown was not found."))
        logger.info(
            "Loaded ABC Classic 100 countdown year=%d entries=%d",
            countdown.year,
            len(entries),
        )
        return entries

    def _archive_html(self) -> str:
        if self._archive is None:
            self._archive = self._request(ARCHIVE_SEARCH_URL)
        return self._archive

    def _current_html(self) -> str:
        if self._current is None:
            self._current = self._request(CURRENT_URL)
        return self._current

    @staticmethod
    def _request(url: str) -> str:
        logger.debug("ABC Classic 100 request %s", url)
        request = urllib.request.Request(url, headers={"User-Agent": "BlindSpot"})
        try:
            with urllib.request.urlopen(
                request, timeout=15, context=TLS_CONTEXT
            ) as response:
                return response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise Classic100Error(
                tr("The ABC Classic 100 archive could not be reached.")
            ) from error
