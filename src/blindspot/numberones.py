"""Number-one lists for the UK, Australia and New Zealand, from Wikipedia.

Each country keeps its lists in a different shape, so this reads the three
shapes in use:

* one row per run at number one, with the date it reached number one and its
  length in weeks (the UK, and New Zealand from 2010);
* one row per week, with the year given by a heading above each table
  (Australian and New Zealand decade pages);
* one row per week, on a page for a single year (Australia from 2000).

Every shape becomes a list of runs, so a year or a date is answered the same
way for every country. The UK keeps its own reader in ``ukcharts``.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from html.parser import HTMLParser

from .i18n import tr
from .ukcharts import (
    ALBUMS,
    CACHE_SECONDS,
    SINGLES,
    Run,
    UKChartError,
    UKChartsClient,
    YearEntry,
    _plain,
    clean_text,
    clean_title,
    order_entries,
    parse_runs,
    run_for_date,
    same_run,
    year_entries,
)

UK = "GB"
AUSTRALIA = "AU"
NEW_ZEALAND = "NZ"
COUNTRIES = (UK, AUSTRALIA, NEW_ZEALAND)
YEAR = re.compile(r"\b(19\d\d|20\d\d)\b")
NO_CHART = re.compile(r"no chart|summer break|break", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Page:
    """A Wikipedia page holding number ones, and its year if it has just one."""

    title: str
    year: int | None = None


class _Table:
    def __init__(self, heading: str, rows: list[list[str]]) -> None:
        self.heading = heading
        self.rows = rows


class _Tables(HTMLParser):
    """Wikitables with merged cells expanded, each with the heading above it."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[_Table] = []
        self._heading = ""
        self._heading_text: list[str] | None = None
        self._depth = 0
        self._raw: list[list[dict]] = []
        self._row: list[dict] | None = None
        self._cell: dict | None = None
        self._skip = 0
        self._hidden = 0

    def handle_starttag(self, tag, attrs):
        details = dict(attrs)
        if tag in ("h2", "h3", "h4") and not self._depth:
            self._heading_text = []
        if tag == "span" and self._hidden:
            self._hidden += 1
        elif (
            tag == "span"
            and "display:none" in (details.get("style") or "").replace(" ", "")
        ):
            self._hidden = 1
        elif (
            tag == "table"
            and "wikitable" in (details.get("class") or "")
            and not self._depth
        ):
            self._depth = 1
            self._raw = []
            self._table_heading = self._heading
        elif tag == "table" and self._depth:
            self._depth += 1
        elif tag == "tr" and self._depth == 1:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = {
                "text": [],
                "rowspan": self._span(details.get("rowspan")),
                "colspan": self._span(details.get("colspan")),
            }
        elif tag in ("sup", "style") and self._cell is not None:
            self._skip += 1
        elif tag == "br" and self._cell is not None:
            self._cell["text"].append(" ")

    @staticmethod
    def _span(value) -> int:
        return int(re.sub(r"\D", "", str(value or "1")) or 1)

    def handle_endtag(self, tag):
        if tag in ("h2", "h3", "h4") and self._heading_text is not None:
            self._heading = " ".join("".join(self._heading_text).split())
            self._heading_text = None
        if tag == "span" and self._hidden:
            self._hidden -= 1
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self._raw.append(self._row)
            self._row = None
        elif tag == "table" and self._depth:
            self._depth -= 1
            if not self._depth:
                self.tables.append(_Table(self._table_heading, self._expand(self._raw)))
        elif tag in ("sup", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._heading_text is not None:
            self._heading_text.append(data)
        if self._cell is not None and not self._skip and not self._hidden:
            self._cell["text"].append(data)

    @staticmethod
    def _expand(rows: list[list[dict]]) -> list[list[str]]:
        """Copy each merged cell down and across so every row is complete."""
        expanded: list[list[str]] = []
        carried: dict[int, tuple[str, int]] = {}
        for row in rows:
            cells = list(row)
            line: list[str] = []
            column = 0
            while cells or column in carried:
                if column in carried:
                    text, remaining = carried[column]
                    line.append(text)
                    if remaining > 1:
                        carried[column] = (text, remaining - 1)
                    else:
                        del carried[column]
                    column += 1
                    continue
                cell = cells.pop(0)
                text = " ".join("".join(cell["text"]).split())
                for _ in range(cell["colspan"]):
                    line.append(text)
                    if cell["rowspan"] > 1:
                        carried[column] = (text, cell["rowspan"] - 1)
                    column += 1
            expanded.append(line)
        return expanded


def parse_tables(html: str) -> list[_Table]:
    parser = _Tables()
    parser.feed(html)
    return parser.tables


def _week_date(text: str, year: int | None) -> date | None:
    text = clean_text(text)
    for pattern in ("%d %B %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            pass
    if year is not None:
        try:
            return datetime.strptime(f"{text} {year}", "%d %B %Y").date()
        except ValueError:
            pass
    return None


def _first_number(text: str) -> float | None:
    match = re.search(r"\d+", clean_text(text))
    return float(match.group()) if match else None


@dataclass(slots=True)
class _Week:
    when: date
    title: str
    artist: str
    total: float | None
    starts: bool


def parse_week_rows(tables: list[_Table], page_year: int | None) -> list[_Week]:
    """Weekly rows from every table that has a date, a title and an artist."""
    weeks: list[_Week] = []
    for table in tables:
        if not table.rows:
            continue
        header = [_plain(cell) for cell in table.rows[0]]
        try:
            date_at = next(
                i
                for i, cell in enumerate(header)
                if cell.startswith(("date", "issue date"))
                or (cell.startswith("week") and not cell.startswith("weeks"))
            )
            title_at = next(
                i
                for i, cell in enumerate(header)
                if cell.startswith(("single", "album", "title", "song"))
            )
            artist_at = next(
                i for i, cell in enumerate(header) if cell.startswith("artist")
            )
        except StopIteration:
            continue
        weeks_at = next(
            (i for i, cell in enumerate(header) if cell.startswith("weeks at")),
            None,
        )
        found = YEAR.search(table.heading)
        year = int(found.group()) if found else page_year
        starts = "ending" not in header[date_at]
        rows: list[_Week] = []
        for row in table.rows[1:]:
            if len(row) <= max(date_at, title_at, artist_at):
                continue
            title = clean_title(row[title_at])
            artist = clean_text(row[artist_at])
            when = _week_date(row[date_at], year)
            if not (when and title and artist) or NO_CHART.search(title):
                continue
            rows.append(
                _Week(
                    when,
                    title,
                    artist,
                    _first_number(row[weeks_at])
                    if weeks_at is not None and len(row) > weeks_at
                    else None,
                    starts,
                )
            )
        if _is_weekly(rows):
            weeks += rows
    return weeks


def _is_weekly(rows: list[_Week]) -> bool:
    """Whether rows are consecutive chart weeks, not a summary of some other kind."""
    if len(rows) < 10:
        return False
    gaps = [
        (later.when - earlier.when).days
        for earlier, later in zip(rows, rows[1:])
    ]
    return sum(1 for gap in gaps if gap == 7) >= 0.6 * len(gaps)


def runs_from_weeks(weeks: list[_Week]) -> list[Run]:
    """Join consecutive weeks of the same song into runs."""
    runs: list[Run] = []
    for week in sorted(weeks, key=lambda w: w.when):
        last = runs[-1] if runs else None
        if (
            last
            and (last.title, last.artist) == (week.title, week.artist)
            and week.when == last.first_week + timedelta(days=7 * int(last.weeks))
        ):
            total = max(last.total or 0, week.total or 0) or None
            runs[-1] = replace(last, weeks=last.weeks + 1, total=total)
            continue
        runs.append(
            Run(
                week.title,
                week.artist,
                week.when,
                1,
                "",
                week.starts,
                week.total,
            )
        )
    return [
        replace(run, total=None) if run.total is not None and run.total <= run.weeks else run
        for run in runs
    ]


def merge_runs(runs: list[Run]) -> list[Run]:
    """Join a run split over two pages into one, and drop repeats."""
    merged: list[Run] = []
    # The same run can appear on two pages; keep the more complete reading.
    best: list[Run] = []
    for run in runs:
        for position, known in enumerate(best):
            if same_run(run, known):
                if run.length > known.length:
                    best[position] = run
                break
        else:
            best.append(run)
    for run in sorted(best, key=lambda r: r.first_week):
        last = merged[-1] if merged else None
        if (
            last
            and (last.title, last.artist) == (run.title, run.artist)
            and run.first_week == last.first_week + timedelta(days=7 * int(last.weeks))
        ):
            total = max(last.length, run.length, last.weeks + run.weeks)
            merged[-1] = replace(
                last, weeks=last.weeks + run.weeks, total=total
            )
            continue
        merged.append(run)
    return merged


def parse_page(html: str, page_year: int | None = None) -> list[Run]:
    """Runs from a page, whichever of the shapes it uses."""
    weekly = runs_from_weeks(parse_week_rows(parse_tables(html), page_year))
    if weekly:
        return weekly
    try:
        return parse_runs(html)
    except UKChartError:
        raise UKChartError(tr("The number ones list could not be read.")) from None


def _decade(year: int) -> int:
    return year - year % 10


@dataclass(frozen=True, slots=True)
class Country:
    code: str
    first_year: dict[str, int]

    def pages(self, kind: str, year: int) -> list[Page]:
        raise NotImplementedError


class _Australia(Country):
    def _page(self, kind: str, year: int) -> Page:
        which = "singles" if kind == SINGLES else "albums"
        if year < 2000:
            return Page(
                f"List of number-one {which} in Australia during the {_decade(year)}s"
            )
        return Page(f"List of number-one {which} of {year} (Australia)", year)

    def pages(self, kind: str, year: int) -> list[Page]:
        pages = [self._page(kind, year)]
        if pages[0].year is not None:
            # A run over New Year continues on the next page.
            for neighbour in (year - 1, year + 1):
                if self.first_year[kind] <= neighbour <= date.today().year:
                    pages.append(self._page(kind, neighbour))
        return list(dict.fromkeys(pages))


class _NewZealand(Country):
    def _page(self, kind: str, decade: int) -> Page:
        if kind == ALBUMS and decade == 1980:
            return Page("List of number 1 albums from the 1980s (New Zealand)")
        which = "singles" if kind == SINGLES else "albums"
        return Page(f"List of number-one {which} from the {decade}s (New Zealand)")

    def pages(self, kind: str, year: int) -> list[Page]:
        decades = {_decade(year)}
        # The newer run-per-row pages start with a run begun the year before.
        if year % 10 == 0:
            decades.add(year - 10)
        if year % 10 == 9:
            decades.add(_decade(year) + 10)
        return [
            self._page(kind, decade)
            for decade in sorted(decades)
            if self.first_year[kind] <= decade + 9
            and decade <= date.today().year
        ]


class _UnitedKingdom(Country):
    def pages(self, kind: str, year: int) -> list[Page]:
        return []


COUNTRY_SOURCES: dict[str, Country] = {
    UK: _UnitedKingdom(UK, {SINGLES: 1952, ALBUMS: 1956}),
    AUSTRALIA: _Australia(AUSTRALIA, {SINGLES: 1940, ALBUMS: 1965}),
    NEW_ZEALAND: _NewZealand(NEW_ZEALAND, {SINGLES: 1980, ALBUMS: 1980}),
}


class NumberOnesClient:
    """Answers year and date questions for any supported country."""

    def __init__(self) -> None:
        self._uk = UKChartsClient()
        self._cache: dict[str, tuple[float, list[Run]]] = {}
        self._lock = threading.Lock()

    def first_year(self, country: str, kind: str) -> int:
        return COUNTRY_SOURCES[country].first_year[kind]

    def check_year(self, country: str, kind: str, year: int) -> None:
        first = self.first_year(country, kind)
        if not first <= year <= date.today().year:
            from .applemusic import country_name

            which = tr("singles") if kind == SINGLES else tr("albums")
            raise UKChartError(
                tr(
                    "{country} number one {which} are available from "
                    "{first} to {last}."
                ).format(
                    country=country_name(country),
                    which=which,
                    first=first,
                    last=date.today().year,
                )
            )

    def _page_runs(self, page: Page) -> list[Run]:
        with self._lock:
            cached = self._cache.get(page.title)
        if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
            return cached[1]
        runs = parse_page(self._uk._page_html(page.title), page.year)
        with self._lock:
            self._cache[page.title] = (time.monotonic(), runs)
        return runs

    def _runs(self, country: str, kind: str, year: int) -> list[Run]:
        if country == UK:
            return self._uk._runs_around(kind, year)
        runs: list[Run] = []
        for page in COUNTRY_SOURCES[country].pages(kind, year):
            runs += self._page_runs(page)
        return merge_runs(runs)

    def year(
        self, country: str, kind: str, year: int, *, by_weeks: bool = False
    ) -> list[YearEntry]:
        self.check_year(country, kind, year)
        return order_entries(
            year_entries(self._runs(country, kind, year), year), by_weeks
        )

    def week(self, country: str, kind: str, day: date) -> Run | None:
        self.check_year(country, kind, day.year)
        return run_for_date(self._runs(country, kind, day.year), day)
