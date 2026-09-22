"""Apple Music's public RSS chart feeds.

Apple publishes a most-played feed per storefront at rss.applemarketingtools.com.
It needs no API key and reports real play data from Apple Music's whole user
base, with a refresh timestamp, which is why BlindSpot prefers it to a
scrobble-derived chart.
"""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from datetime import date, datetime, timedelta
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import messages as msg
from .i18n import tr, tr_noop
from .network import TLS_CONTEXT

API_ROOT = "https://rss.applemarketingtools.com/api/v2"
DEFAULT_LIMIT = 50
# The feed is refreshed hourly at most, and it intermittently stalls, so
# serve repeat searches from memory rather than re-fetching.
CACHE_SECONDS = 15 * 60
# A chart feed answers in about two seconds when healthy; a long timeout
# only makes an occasional stall painful, so fail fast and retry.
REQUEST_TIMEOUT = 8
logger = logging.getLogger(__name__)

# Apple Music storefronts, by ISO country code and the name shown in Discover.
CHART_COUNTRIES = (
    ("AR", tr_noop("Argentina")),
    ("AU", tr_noop("Australia")),
    ("AT", tr_noop("Austria")),
    ("BE", tr_noop("Belgium")),
    ("BR", tr_noop("Brazil")),
    ("CA", tr_noop("Canada")),
    ("CL", tr_noop("Chile")),
    ("CO", tr_noop("Colombia")),
    ("CZ", tr_noop("Czech Republic")),
    ("DK", tr_noop("Denmark")),
    ("FI", tr_noop("Finland")),
    ("FR", tr_noop("France")),
    ("DE", tr_noop("Germany")),
    ("GR", tr_noop("Greece")),
    ("HK", tr_noop("Hong Kong")),
    ("HU", tr_noop("Hungary")),
    ("IN", tr_noop("India")),
    ("ID", tr_noop("Indonesia")),
    ("IE", tr_noop("Ireland")),
    ("IL", tr_noop("Israel")),
    ("IT", tr_noop("Italy")),
    ("JP", tr_noop("Japan")),
    ("MY", tr_noop("Malaysia")),
    ("MX", tr_noop("Mexico")),
    ("NL", tr_noop("Netherlands")),
    ("NZ", tr_noop("New Zealand")),
    ("NO", tr_noop("Norway")),
    ("PH", tr_noop("Philippines")),
    ("PL", tr_noop("Poland")),
    ("PT", tr_noop("Portugal")),
    ("RO", tr_noop("Romania")),
    ("SA", tr_noop("Saudi Arabia")),
    ("SG", tr_noop("Singapore")),
    ("ZA", tr_noop("South Africa")),
    ("KR", tr_noop("South Korea")),
    ("ES", tr_noop("Spain")),
    ("SE", tr_noop("Sweden")),
    ("CH", tr_noop("Switzerland")),
    ("TW", tr_noop("Taiwan")),
    ("TH", tr_noop("Thailand")),
    ("TR", tr_noop("Turkey")),
    ("AE", tr_noop("United Arab Emirates")),
    ("GB", tr_noop("United Kingdom")),
    ("US", tr_noop("United States")),
    ("VN", tr_noop("Vietnam")),
)

DEFAULT_COUNTRY = "AU"

# Apple's iTunes Store genre numbers, as accepted by its per-genre charts.
GENRES = (
    ("", tr_noop("Any genre")),
    ("20", tr_noop("Alternative")),
    ("2", tr_noop("Blues")),
    ("22", tr_noop("Christian and Gospel")),
    ("5", tr_noop("Classical")),
    ("6", tr_noop("Country music")),
    ("17", tr_noop("Dance")),
    ("7", tr_noop("Electronic")),
    ("18", tr_noop("Hip-Hop and Rap")),
    ("11", tr_noop("Jazz")),
    ("1153", tr_noop("Metal")),
    ("14", tr_noop("Pop")),
    ("15", tr_noop("R&B and Soul")),
    ("24", tr_noop("Reggae")),
    ("21", tr_noop("Rock")),
    ("10", tr_noop("Singer-Songwriter")),
    ("16", tr_noop("Soundtrack")),
)

# How recent a release must be to appear in a genre chart, in days (0 = any).
RELEASE_WINDOWS = (
    (7, tr_noop("Last 7 days")),
    (14, tr_noop("Last 14 days")),
    (30, tr_noop("Last 30 days")),
    (90, tr_noop("Last 90 days")),
    (0, tr_noop("Any time")),
)
DEFAULT_RELEASE_WINDOW = 30

LEGACY_ROOT = "https://itunes.apple.com"
KEYWORD_ARTISTS = 25
KEYWORD_RESULTS = 50
KEYWORD_TITLE_RESULTS = 200
EDITION_SUFFIX = re.compile(r"\s+-\s+(?:Single|EP)$", re.IGNORECASE)
AUDIOBOOK_EDITION = re.compile(r"\s*\((?:Un)?abridged\)\s*$", re.IGNORECASE)


def country_name(code: str) -> str:
    """Return the display name for a storefront code, else the code."""
    wanted = code.strip().upper()
    return next(
        (tr(name) for value, name in CHART_COUNTRIES if value == wanted),
        wanted,
    )


def loaded_label(fetched_at: float) -> str:
    """Format when a chart was fetched, in the user's local time.

    Apple's own `updated` field is not used for this: it tracks the moment of
    the request rather than when the ranking was measured, so presenting it
    as a freshness date would overstate what is known.
    """
    if not fetched_at:
        return ""
    moment = datetime.fromtimestamp(fetched_at)
    clock = msg.clock_time(moment)
    return tr("{date} at {time}").format(
        date=msg.long_date(moment.date()),
        time=clock,
    )


class AppleMusicError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ChartEntry:
    name: str
    artist: str
    apple_id: str = ""
    url: str = ""
    release_date: str = ""
    kind: str = "album"


@dataclass(frozen=True, slots=True)
class ChartFeed:
    entries: list[ChartEntry]
    country: str
    updated: str = ""
    fetched_at: float = 0.0


def release_title(name: str) -> str:
    """A release name without Apple's "- Single" or "- EP" edition suffix."""
    return EDITION_SUFFIX.sub("", name).strip() or name


def audiobook_title(name: str) -> str:
    """An audiobook's name without Apple's "(Unabridged)" edition marker."""
    return AUDIOBOOK_EDITION.sub("", name).strip() or name


def _plain(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    value = "".join(c for c in value if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w]+", " ", value).split())


def released_on(value: str) -> date | None:
    """The calendar date at the start of one of Apple's release timestamps."""
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def parse_genre_chart(payload: dict, media_type: str) -> list[ChartEntry]:
    """Read entries from Apple's iTunes Store genre chart feed."""
    entries = (payload.get("feed") or {}).get("entry") or []
    if isinstance(entries, dict):
        entries = [entries]
    parsed = []
    for value in entries:
        name = str((value.get("im:name") or {}).get("label") or "")
        artist = str((value.get("im:artist") or {}).get("label") or "")
        identifier = value.get("id") or {}
        if not name or not artist:
            continue
        parsed.append(
            ChartEntry(
                release_title(name) if media_type == "albums" else name,
                artist,
                str((identifier.get("attributes") or {}).get("im:id") or ""),
                str(identifier.get("label") or ""),
                str((value.get("im:releaseDate") or {}).get("label") or ""),
            )
        )
    return parsed


def recent_first(
    entries: list[ChartEntry],
    days: int,
    today: date | None = None,
) -> list[ChartEntry]:
    """Keep released items from the last ``days`` days (0 = any), newest first.

    Pre-orders are dated in the future and are not released yet, so they are
    always left out.
    """
    today = today or date.today()
    oldest = today - timedelta(days=days) if days else None
    kept = []
    for entry in entries:
        released = released_on(entry.release_date)
        if released is not None and released > today:
            continue
        if oldest is not None and (released is None or released < oldest):
            continue
        kept.append((released or date.min, entry))
    kept.sort(key=lambda pair: pair[0], reverse=True)
    return [entry for _released, entry in kept]


class AppleMusicClient:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, str, int], tuple[float, ChartFeed]] = {}
        self._new_cache: dict[tuple[str, ...], tuple[float, list[ChartEntry]]] = {}

    def new_releases(
        self,
        country: str,
        *,
        media_type: str = "songs",
        genre: str = "",
        days: int = DEFAULT_RELEASE_WINDOW,
        keyword: str = "",
    ) -> ChartFeed:
        """Recent releases: a keyword's newest, else a genre chart's new entries."""
        code = country.strip().lower()
        if not code:
            raise ValueError("An Apple Music storefront is required.")
        keyword = keyword.strip()
        if keyword:
            entries = self._keyword_releases(code, keyword)
            if days:
                entries = recent_first(entries, days)
        else:
            entries = recent_first(
                self._genre_chart(code, media_type, genre), days
            )
        return ChartFeed(entries, code, "", time.time())

    def followed_releases(
        self,
        country: str,
        artists: list[tuple[str, str]],
        authors: list[tuple[str, str]] = (),
        *,
        days: int = DEFAULT_RELEASE_WINDOW,
    ) -> tuple[ChartFeed, dict[str, str], dict[str, str]]:
        """Recent releases by followed artists and authors.

        Each list holds ``(name, apple_id)`` pairs. Names without an Apple
        number are looked up first, one search each, and the numbers found are
        returned (artists, then authors) so they can be kept. Every list then
        needs a single lookup request.
        """
        code = country.strip().lower()
        entries: list[ChartEntry] = []
        artist_ids: dict[str, str] = {}
        author_ids: dict[str, str] = {}
        music, artist_ids = self._resolve(code, artists, self._find_artist_id)
        if music:
            wanted = {_plain(name) for name, _apple_id in artists}
            lookup = self._lookup(code, music, "album")
            # A collection can credit the artist among several names.
            entries += [
                entry
                for entry in self._collections(lookup)
                if any(name in _plain(entry.artist) for name in wanted if name)
            ]
        books, author_ids = self._resolve(code, authors, self._find_author_id)
        if books:
            wanted = {_plain(name) for name, _apple_id in authors}
            lookup = self._lookup(code, books, "audiobook")
            entries += [
                entry
                for entry in self._audiobooks(lookup)
                if any(name in _plain(entry.artist) for name in wanted if name)
            ]
        seen: set[str] = set()
        unique = []
        for entry in recent_first(entries, days):
            if entry.apple_id not in seen:
                seen.add(entry.apple_id)
                unique.append(entry)
        return ChartFeed(unique, code, "", time.time()), artist_ids, author_ids

    def _resolve(
        self,
        code: str,
        people: list[tuple[str, str]],
        finder,
    ) -> tuple[list[str], dict[str, str]]:
        """Apple numbers for ``people``, searching only for the unknown ones."""
        ids: list[str] = []
        found: dict[str, str] = {}
        for name, apple_id in people:
            if not apple_id:
                apple_id = finder(code, name)
                if apple_id:
                    found[name] = apple_id
            if apple_id:
                ids.append(apple_id)
        return ids, found

    def _lookup(self, code: str, ids: list[str], entity: str) -> list[dict]:
        return self._request(
            f"{LEGACY_ROOT}/lookup?"
            + urllib.parse.urlencode(
                {
                    "id": ",".join(ids),
                    "entity": entity,
                    "sort": "recent",
                    "limit": KEYWORD_RESULTS,
                    "country": code,
                }
            )
        ).get("results") or []

    def _find_author_id(self, code: str, name: str) -> str:
        found = self._request(
            f"{LEGACY_ROOT}/search?"
            + urllib.parse.urlencode(
                {
                    "term": name,
                    "country": code,
                    "media": "audiobook",
                    "entity": "audiobook",
                    "limit": 25,
                }
            )
        ).get("results") or []
        wanted = _plain(name)
        words = wanted.split()
        exact = ""
        partial = ""
        for value in found:
            author = _plain(str(value.get("artistName") or ""))
            author_id = str(value.get("artistId") or "")
            if not author_id:
                continue
            if author == wanted:
                exact = exact or author_id
            elif words and all(word in author.split() for word in words):
                partial = partial or author_id
        return exact or partial

    @staticmethod
    def _audiobooks(results: list[dict]) -> list[ChartEntry]:
        """Audiobook releases, keeping only titles marked (Un)abridged.

        Apple lists translated editions alongside the English ones with no
        language field, and only the English editions carry that marker.
        """
        entries = []
        for value in results:
            name = str(value.get("collectionName") or "")
            author = str(value.get("artistName") or "")
            if (
                value.get("wrapperType") != "audiobook"
                or not name
                or not author
                or not AUDIOBOOK_EDITION.search(name)
            ):
                continue
            entries.append(
                ChartEntry(
                    audiobook_title(name),
                    author,
                    str(value.get("collectionId") or ""),
                    str(value.get("collectionViewUrl") or ""),
                    str(value.get("releaseDate") or ""),
                    "audiobook",
                )
            )
        return entries

    def _find_artist_id(self, code: str, name: str) -> str:
        found = self._request(
            f"{LEGACY_ROOT}/search?"
            + urllib.parse.urlencode(
                {
                    "term": name,
                    "country": code,
                    "media": "music",
                    "entity": "musicArtist",
                    "limit": 5,
                }
            )
        ).get("results") or []
        wanted = _plain(name)
        for value in found:
            if value.get("artistId") and _plain(str(value.get("artistName") or "")) == wanted:
                return str(value["artistId"])
        return ""

    def _cached(
        self,
        key: tuple[str, ...],
        fetch,
    ) -> list[ChartEntry]:
        cached = self._new_cache.get(key)
        if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
            return cached[1]
        entries = fetch()
        self._new_cache[key] = (time.monotonic(), entries)
        return entries

    def _genre_chart(
        self,
        code: str,
        media_type: str,
        genre: str,
    ) -> list[ChartEntry]:
        kind = "topalbums" if media_type == "albums" else "topsongs"
        genre_part = f"/genre={urllib.parse.quote(genre)}" if genre else ""
        url = f"{LEGACY_ROOT}/{urllib.parse.quote(code)}/rss/{kind}{genre_part}/limit=100/json"
        return self._cached(
            ("chart", code, kind, genre),
            lambda: parse_genre_chart(self._request(url), media_type),
        )

    def _keyword_releases(self, code: str, keyword: str) -> list[ChartEntry]:
        return self._cached(
            ("keyword", code, _plain(keyword)),
            lambda: self._search_releases(code, keyword),
        )

    def _search_releases(self, code: str, keyword: str) -> list[ChartEntry]:
        """An artist's newest releases first, then other releases by title."""
        wanted = _plain(keyword)
        words = wanted.split()
        found = self._request(
            f"{LEGACY_ROOT}/search?"
            + urllib.parse.urlencode(
                {
                    "term": keyword,
                    "country": code,
                    "media": "music",
                    "entity": "musicArtist",
                    "limit": KEYWORD_ARTISTS,
                }
            )
        ).get("results") or []
        artists = [
            value
            for value in found
            if value.get("artistId")
            and all(word in _plain(str(value.get("artistName") or "")).split() for word in words)
        ]
        artists.sort(
            key=lambda value: _plain(str(value.get("artistName") or "")) != wanted
        )
        by_artist: list[ChartEntry] = []
        if artists:
            # One request covers every matching artist.
            lookup = self._request(
                f"{LEGACY_ROOT}/lookup?"
                + urllib.parse.urlencode(
                    {
                        "id": ",".join(
                            str(artist["artistId"]) for artist in artists
                        ),
                        "entity": "album",
                        "sort": "recent",
                        "limit": KEYWORD_RESULTS,
                        "country": code,
                    }
                )
            ).get("results") or []
            by_artist = recent_first(self._collections(lookup), 0)
        by_title = self._collections(
            self._request(
                f"{LEGACY_ROOT}/search?"
                + urllib.parse.urlencode(
                    {
                        "term": keyword,
                        "country": code,
                        "media": "music",
                        "entity": "album",
                        "limit": KEYWORD_TITLE_RESULTS,
                    }
                )
            ).get("results")
            or []
        )
        merged: list[ChartEntry] = []
        seen: set[str] = set()
        for entry in by_artist + by_title:
            if entry.apple_id in seen:
                continue
            seen.add(entry.apple_id)
            merged.append(entry)
        return merged

    @staticmethod
    def _collections(results: list[dict]) -> list[ChartEntry]:
        entries = []
        for value in results:
            name = str(value.get("collectionName") or "")
            artist = str(value.get("artistName") or "")
            if value.get("wrapperType") != "collection" or not name or not artist:
                continue
            entries.append(
                ChartEntry(
                    release_title(name),
                    artist,
                    str(value.get("collectionId") or ""),
                    str(value.get("collectionViewUrl") or ""),
                    str(value.get("releaseDate") or ""),
                )
            )
        return entries

    def top_songs(
        self,
        country: str,
        *,
        limit: int = DEFAULT_LIMIT,
    ) -> ChartFeed:
        """Return the most-played songs for one Apple Music storefront."""
        return self._top_music(country, "songs", limit=limit)

    def top_albums(
        self,
        country: str,
        *,
        limit: int = DEFAULT_LIMIT,
    ) -> ChartFeed:
        """Return the most-played albums for one Apple Music storefront."""
        return self._top_music(country, "albums", limit=limit)

    def _top_music(
        self,
        country: str,
        media_type: str,
        *,
        limit: int,
    ) -> ChartFeed:
        code = country.strip().lower()
        if not code:
            raise ValueError("An Apple Music storefront is required.")
        count = max(1, min(int(limit), 100))
        cache_key = (code, media_type, count)
        cached = self._cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
            logger.debug("Apple Music chart served from cache country=%s", code)
            return cached[1]
        url = (
            f"{API_ROOT}/{urllib.parse.quote(code)}"
            f"/music/most-played/{count}/{media_type}.json"
        )
        feed = (self._request(url).get("feed") or {})
        entries = []
        for value in feed.get("results") or []:
            name = str(value.get("name") or "")
            artist = str(value.get("artistName") or "")
            if name and artist:
                entries.append(
                    ChartEntry(
                        name,
                        artist,
                        str(value.get("id") or ""),
                        str(value.get("url") or ""),
                        str(value.get("releaseDate") or ""),
                    )
                )
        updated = str(feed.get("updated") or "")
        logger.debug(
            "Apple Music chart country=%s requested=%d entries=%d updated=%s",
            code,
            count,
            len(entries),
            updated,
        )
        chart = ChartFeed(entries, code, updated, time.time())
        self._cache[cache_key] = (time.monotonic(), chart)
        return chart

    def _request(self, url: str) -> dict:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "BlindSpot"},
        )
        logger.debug("Apple Music request %s", url)
        # The feed occasionally drops a connection mid-redirect, so allow one
        # retry before surfacing a failure to the user.
        for attempt in range(2):
            try:
                with urllib.request.urlopen(
                    request, timeout=REQUEST_TIMEOUT, context=TLS_CONTEXT
                ) as response:
                    payload = response.read().decode("utf-8-sig")
                break
            except urllib.error.HTTPError as error:
                raise AppleMusicError(
                    tr(
                        "Apple Music charts are unavailable ({code})."
                    ).format(code=error.code)
                ) from error
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                if attempt == 0:
                    logger.debug("Apple Music request retrying after %s", error)
                    time.sleep(1)
                    continue
                raise AppleMusicError(
                    tr("Apple Music charts could not be reached.")
                ) from error
        try:
            return json.loads(payload)
        except ValueError as error:
            raise AppleMusicError(
                tr("Apple Music returned an unreadable chart.")
            ) from error
