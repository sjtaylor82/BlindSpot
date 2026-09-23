"""ABC Radio National listener-voted book countdowns."""

from __future__ import annotations

import html as html_module
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from .i18n import tr
from .network import TLS_CONTEXT

logger = logging.getLogger(__name__)

TOP_100_URL = (
    "https://www.abc.net.au/listen/radionational/countdown/top100books/25"
)
NEXT_100_URL = (
    "https://www.abc.net.au/listen/programs/the-bookshelf/"
    "we-reveal-the-books-that-didnt-quite-make-the-top-100/105871776"
)


class RNBooksError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BookCountdown:
    year: int
    start: int
    end: int
    label: str


@dataclass(frozen=True, slots=True)
class BookEntry:
    title: str
    author: str
    rank: int


# Add future years here once ABC publishes their final ranked pages.
COUNTDOWNS = (
    BookCountdown(2025, 1, 100, "Top 100 Books of the 21st Century (2025)"),
    BookCountdown(2025, 101, 200, "The Ones That Got Away, 101–200 (2025)"),
    BookCountdown(2025, 1, 200, "Complete Top 200 (2025)"),
)


def _text(value: str) -> str:
    return " ".join(html_module.unescape(re.sub(r"<[^>]+>", "", value)).split())


def parse_top_100(html: str) -> list[BookEntry]:
    hero = re.search(
        r'SongCountdownHero_title__[^" ]*"[^>]*>(.*?)</h3>.*?'
        r'SongCountdownHero_artist__[^" ]*"[^>]*>(.*?)</div>',
        html,
        re.DOTALL,
    )
    entries = [BookEntry(_text(hero.group(1)), _text(hero.group(2)), 1)] if hero else []
    cards = re.finditer(
        r'SongCard_position__[^" ]*"[^>]*>\s*(\d+)\s*</div>.*?'
        r'SongCard_title__[^" ]*"[^>]*>(.*?)</div>.*?'
        r'data-testid="song-card-artist"[^>]*>(.*?)</div>',
        html,
        re.DOTALL,
    )
    for match in cards:
        rank = int(match.group(1))
        title, author = _text(match.group(2)), _text(match.group(3))
        if 2 <= rank <= 100 and title and author:
            entries.append(BookEntry(title, author, rank))
    return _unique_ranked(entries)


def parse_next_100(html: str) -> list[BookEntry]:
    entries = []
    for match in re.finditer(
        r"(?:^|<p[^>]*>|<br\s*/?>)\s*(1\d\d|200)\.\s*(.*?)\s+[—–]\s+"
        r"(.*?)(?=<br\s*/?>|</p>)",
        html,
        re.DOTALL | re.IGNORECASE,
    ):
        rank = int(match.group(1))
        title, author = _text(match.group(2)), _text(match.group(3))
        if 101 <= rank <= 200 and title and author:
            entries.append(BookEntry(title, author, rank))
    return _unique_ranked(entries)


def _unique_ranked(entries: list[BookEntry]) -> list[BookEntry]:
    by_rank = {entry.rank: entry for entry in entries}
    return [by_rank[rank] for rank in sorted(by_rank)]


class RNBooksClient:
    def __init__(self) -> None:
        self._top_html: str | None = None
        self._next_html: str | None = None

    def countdown(self, countdown: BookCountdown) -> list[BookEntry]:
        logger.info(
            "Loading ABC Radio National books year=%d ranks=%d-%d",
            countdown.year,
            countdown.start,
            countdown.end,
        )
        try:
            entries = []
            if countdown.start <= 100:
                entries += parse_top_100(self._top_100_html())
            if countdown.end > 100:
                entries += parse_next_100(self._next_100_html())
        except (TypeError, ValueError) as error:
            raise RNBooksError(
                tr("The ABC Radio National book countdown could not be read.")
            ) from error
        entries = [
            entry
            for entry in _unique_ranked(entries)
            if countdown.start <= entry.rank <= countdown.end
        ]
        expected = countdown.end - countdown.start + 1
        if len(entries) != expected:
            raise RNBooksError(
                tr("The complete ABC Radio National book countdown was not found.")
            )
        logger.info("Loaded ABC Radio National books entries=%d", len(entries))
        return entries

    def _top_100_html(self) -> str:
        if self._top_html is None:
            self._top_html = self._request(TOP_100_URL)
        return self._top_html

    def _next_100_html(self) -> str:
        if self._next_html is None:
            self._next_html = self._request(NEXT_100_URL)
        return self._next_html

    @staticmethod
    def _request(url: str) -> str:
        logger.debug("ABC Radio National books request %s", url)
        request = urllib.request.Request(url, headers={"User-Agent": "BlindSpot"})
        try:
            with urllib.request.urlopen(
                request, timeout=15, context=TLS_CONTEXT
            ) as response:
                return response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise RNBooksError(
                tr("The ABC Radio National book countdown could not be reached.")
            ) from error
