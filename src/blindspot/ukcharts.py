"""UK number ones by year or date, read from Wikipedia's decade lists.

Wikipedia keeps a "List of UK singles chart number ones of the 1980s" page (and
a matching one for albums) for every decade. Each has one table with a row per
run at number one: the artist, the title, and the date and length of the run.
That is enough to say which songs were number one in a year and for how many
weeks, or which was number one in a given week. It is community-edited data
under a share-alike licence, and only the number ones, not the whole chart.
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html.parser import HTMLParser

from . import __version__
from .i18n import tr
from .network import TLS_CONTEXT

logger = logging.getLogger(__name__)

API_ROOT = "https://en.wikipedia.org/w/api.php"
USER_AGENT = (
    f"BlindSpot/{__version__} ( https://github.com/sjtaylor82/BlindSpot )"
)
SINGLES = "singles"
ALBUMS = "albums"
FIRST_YEAR = {SINGLES: 1952, ALBUMS: 1956}
PAGE_TITLES = {
    SINGLES: "List of UK singles chart number ones of the {decade}s",
    ALBUMS: "List of UK Albums Chart number ones of the {decade}s",
}
FOOTNOTE = re.compile(r"\[[^\]]*\]")
MARKS = re.compile(r"[†‡§¶*^♦•]")
CACHE_SECONDS = 24 * 60 * 60


class UKChartError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Run:
    """One spell at number one: its title, artist, first week and length."""

    title: str
    artist: str
    first_week: date
    # Weeks are whole except in the 1950s, when two versions of a song could
    # share a week, giving runs such as 7.5 weeks.
    weeks: float
    label: str = ""
    # Older lists give the date a week starts; newer ones the date it ends.
    week_starts: bool = False
    # The run's full length when the list states it and it is longer than the
    # weeks read here, as when the run continues on another page.
    total: float | None = None

    @property
    def length(self) -> float:
        return self.total if self.total is not None else self.weeks

    def week_shares(self) -> list[tuple[date, float]]:
        """Each chart week of the run and how much of it the run had."""
        return [
            (self.first_week + timedelta(days=7 * n), min(1.0, self.weeks - n))
            for n in range(math.ceil(self.weeks))
        ]

    def week_dates(self) -> list[date]:
        return [week for week, _share in self.week_shares()]


@dataclass(frozen=True, slots=True)
class YearEntry:
    """A song's weeks at number one in a year, gathered over all its runs."""

    title: str
    artist: str
    weeks_in_year: float
    total_weeks: float
    first_week: date


def same_run(first: "Run", second: "Run") -> bool:
    """Whether two readings are one run: the same song and the same week.

    Neighbouring decade pages can list the run that straddles them a few days
    apart, because one dates a week by its start and the other by its end.
    """
    return (
        _plain(first.title) == _plain(second.title)
        and _plain(first.artist) == _plain(second.artist)
        and abs((first.first_week - second.first_week).days) <= 6
    )


def _plain(value: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", value.casefold()).split())


def clean_text(value: str) -> str:
    value = FOOTNOTE.sub("", value)
    value = MARKS.sub("", value)
    return " ".join(value.replace("\xa0", " ").split())


CREDIT_SPLIT = re.compile(
    r"\s+(?:featuring|feat\.?|with|vs\.?|versus|presents|and|&)\s+",
    re.IGNORECASE,
)
FEATURE_SPLIT = re.compile(
    r"\s+(?:featuring|feat\.?|with|vs\.?|versus|presents)\s+", re.IGNORECASE
)


def artist_candidates(credit: str) -> list[str]:
    """Names to try when finding a joint credit on Spotify, best first.

    "Elaine Paige and Barbara Dickson" is tried whole, then as its lead artist.
    Splitting only on featuring-style words first keeps bands such as
    "Simon & Garfunkel" together.
    """
    names = [credit]
    for split in (FEATURE_SPLIT, CREDIT_SPLIT):
        lead = split.split(credit, 1)[0].strip()
        if lead and lead not in names:
            names.append(lead)
    return names


def weeks_text(weeks: float) -> str:
    """Weeks for display: whole numbers, or a half as in 7½."""
    whole = int(weeks)
    if weeks == whole:
        return str(whole)
    return f"{whole}½" if whole else "½"


def parse_weeks(value: str) -> float | None:
    text = clean_text(value)
    match = re.match(r"^(\d+)?\s*(½)?$", text)
    if not match or not (match.group(1) or match.group(2)):
        return None
    return int(match.group(1) or 0) + (0.5 if match.group(2) else 0.0)


def clean_title(value: str) -> str:
    """A title without its quotation marks, including those round a double A-side."""
    return " ".join(re.sub("[\"\u201c\u201d]", "", clean_text(value)).split())


def title_candidates(title: str) -> list[str]:
    """Titles to try on Spotify: a double A-side whole, then each side."""
    titles = [title]
    for part in title.split(" / "):
        part = part.strip()
        if part and part not in titles:
            titles.append(part)
    return titles


class _TableParser(HTMLParser):
    """Collect the cell text of every wikitable, row by row."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._depth = 0
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._skip = 0
        self._hidden = 0

    def handle_starttag(self, tag, attrs):
        details = dict(attrs)
        classes = details.get("class") or ""
        if tag == "span" and self._hidden:
            self._hidden += 1
        elif (
            tag == "span"
            and "display:none" in (details.get("style") or "").replace(" ", "")
        ):
            self._hidden = 1
        elif tag == "table" and "wikitable" in classes and not self._depth:
            self.tables.append([])
            self._depth = 1
        elif tag == "table" and self._depth:
            self._depth += 1
        elif tag == "tr" and self._depth == 1:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag in ("sup", "style", "script") and self._cell is not None:
            self._skip += 1
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag == "span" and self._hidden:
            self._hidden -= 1
        elif tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append("".join(self._cell))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.tables[-1].append(self._row)
            self._row = None
        elif tag == "table" and self._depth:
            self._depth -= 1
        elif tag in ("sup", "style", "script") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._cell is not None and not self._skip and not self._hidden:
            self._cell.append(data)


def _parse_date(value: str) -> date | None:
    text = clean_text(value)
    for pattern in ("%d %B %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def parse_runs(html: str) -> list[Run]:
    """Read the runs at number one from one decade page's main table."""
    parser = _TableParser()
    parser.feed(html)
    for table in parser.tables:
        header = [_plain(cell) for cell in table[0]] if table else []
        try:
            artist_at = next(
                i for i, cell in enumerate(header) if cell.startswith("artist")
            )
            title_at = next(
                i
                for i, cell in enumerate(header)
                if cell.startswith(("single", "album", "title", "song"))
            )
            date_at = next(
                i
                for i, cell in enumerate(header)
                if cell.startswith("reached")
                or (cell.startswith("week") and not cell.startswith("weeks at"))
            )
            weeks_at = next(
                i for i, cell in enumerate(header) if cell.startswith("weeks at")
            )
        except (ValueError, StopIteration):
            continue
        label_at = header.index("record label") if "record label" in header else None
        starts = "starting" in header[date_at]
        runs = []
        for row in table[1:]:
            if len(row) <= max(artist_at, title_at, date_at, weeks_at):
                continue
            first = _parse_date(row[date_at])
            weeks = parse_weeks(row[weeks_at])
            title = clean_title(row[title_at])
            artist = clean_text(row[artist_at])
            if not (first and weeks and title and artist):
                continue
            runs.append(
                Run(
                    title,
                    artist,
                    first,
                    weeks,
                    clean_text(row[label_at]) if label_at is not None else "",
                    starts,
                )
            )
        if runs:
            return runs
    raise UKChartError(tr("The UK number ones list could not be read."))


def year_entries(runs: list[Run], year: int) -> list[YearEntry]:
    """One entry per song for ``year``, with its weeks that year and in total.

    A song that returned to number one appears once, its runs added together.
    """
    grouped: dict[tuple[str, str], list[Run]] = {}
    for run in runs:
        grouped.setdefault((_plain(run.title), _plain(run.artist)), []).append(run)
    entries = []
    for group in grouped.values():
        in_year = [
            (week, share)
            for run in group
            for week, share in run.week_shares()
            if week.year == year
        ]
        if not in_year:
            continue
        first = group[0]
        # Some lists give the song's total on every run, so a song that came
        # back is not added up twice; the weeks actually read are the floor.
        declared = [run.total for run in group if run.total is not None]
        counted = sum(run.weeks for run in group)
        entries.append(
            YearEntry(
                first.title,
                first.artist,
                sum(share for _week, share in in_year),
                max([counted, *declared]),
                min(week for week, _share in in_year),
            )
        )
    return entries


def order_entries(entries: list[YearEntry], by_weeks: bool) -> list[YearEntry]:
    if by_weeks:
        return sorted(
            entries, key=lambda entry: (-entry.weeks_in_year, entry.first_week)
        )
    return sorted(entries, key=lambda entry: entry.first_week)


def run_for_date(runs: list[Run], day: date) -> Run | None:
    """The run at number one in the chart week containing ``day``."""
    for run in runs:
        for week in run.week_dates():
            if run.week_starts:
                within = week <= day < week + timedelta(days=7)
            else:
                within = week - timedelta(days=7) < day <= week
            if within:
                return run
    return None


class UKChartsClient:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, int], tuple[float, list[Run]]] = {}
        self._lock = threading.Lock()

    def decade_runs(self, kind: str, decade: int) -> list[Run]:
        key = (kind, decade)
        with self._lock:
            cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
            return cached[1]
        runs = parse_runs(self._page_html(PAGE_TITLES[kind].format(decade=decade)))
        with self._lock:
            self._cache[key] = (time.monotonic(), runs)
        return runs

    def _runs_around(self, kind: str, year: int) -> list[Run]:
        """Runs from the year's decade, plus a neighbour when it borders one."""
        decades = {year - year % 10}
        if year % 10 == 0:
            decades.add(year - 10)
        if year % 10 == 9:
            decades.add(year - year % 10 + 10)
        first = FIRST_YEAR[kind]
        runs: list[Run] = []
        for decade in sorted(decades):
            if decade + 9 < first or decade > date.today().year:
                continue
            for run in self.decade_runs(kind, decade):
                if not any(same_run(run, known) for known in runs):
                    runs.append(run)
        return runs

    def check_year(self, kind: str, year: int) -> None:
        if not FIRST_YEAR[kind] <= year <= date.today().year:
            raise UKChartError(
                tr(
                    "UK number ones are available from {first} to {last}."
                ).format(first=FIRST_YEAR[kind], last=date.today().year)
            )

    def year(self, kind: str, year: int, *, by_weeks: bool = False) -> list[YearEntry]:
        self.check_year(kind, year)
        entries = year_entries(self._runs_around(kind, year), year)
        return order_entries(entries, by_weeks)

    def week(self, kind: str, day: date) -> Run | None:
        self.check_year(kind, day.year)
        return run_for_date(self._runs_around(kind, day.year), day)

    def _page_html(self, title: str) -> str:
        query = urllib.parse.urlencode(
            {
                "action": "parse",
                "page": title,
                "prop": "text",
                "format": "json",
                "formatversion": "2",
                "redirects": "1",
            }
        )
        request = urllib.request.Request(
            f"{API_ROOT}?{query}",
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(
                request, timeout=30, context=TLS_CONTEXT
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise UKChartError(
                tr("Wikipedia returned error {status}.").format(status=error.code)
            ) from error
        except (OSError, ValueError) as error:
            logger.warning("UK charts lookup failed: %s", error)
            raise UKChartError(tr("Wikipedia could not be reached.")) from error
        html = (payload.get("parse") or {}).get("text")
        if not html:
            raise UKChartError(tr("The UK number ones list could not be read."))
        return str(html)
