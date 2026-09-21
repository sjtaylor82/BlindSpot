"""Apple Music's public RSS chart feeds.

Apple publishes a most-played feed per storefront at rss.applemarketingtools.com.
It needs no API key and reports real play data from Apple Music's whole user
base, with a refresh timestamp, which is why BlindSpot prefers it to a
scrobble-derived chart.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

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
    ("AR", "Argentina"), ("AU", "Australia"), ("AT", "Austria"),
    ("BE", "Belgium"), ("BR", "Brazil"), ("CA", "Canada"),
    ("CL", "Chile"), ("CO", "Colombia"), ("CZ", "Czech Republic"),
    ("DK", "Denmark"), ("FI", "Finland"), ("FR", "France"),
    ("DE", "Germany"), ("GR", "Greece"), ("HK", "Hong Kong"),
    ("HU", "Hungary"), ("IN", "India"), ("ID", "Indonesia"),
    ("IE", "Ireland"), ("IL", "Israel"), ("IT", "Italy"),
    ("JP", "Japan"), ("MY", "Malaysia"), ("MX", "Mexico"),
    ("NL", "Netherlands"), ("NZ", "New Zealand"), ("NO", "Norway"),
    ("PH", "Philippines"), ("PL", "Poland"), ("PT", "Portugal"),
    ("RO", "Romania"), ("SA", "Saudi Arabia"), ("SG", "Singapore"),
    ("ZA", "South Africa"), ("KR", "South Korea"), ("ES", "Spain"),
    ("SE", "Sweden"), ("CH", "Switzerland"), ("TW", "Taiwan"),
    ("TH", "Thailand"), ("TR", "Turkey"), ("AE", "United Arab Emirates"),
    ("GB", "United Kingdom"), ("US", "United States"), ("VN", "Vietnam"),
)

DEFAULT_COUNTRY = "AU"


def country_name(code: str) -> str:
    """Return the display name for a storefront code, else the code."""
    wanted = code.strip().upper()
    return next(
        (name for value, name in CHART_COUNTRIES if value == wanted),
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
    return moment.strftime("%d %B %Y at %I:%M %p").lstrip("0").replace(
        " 0",
        " ",
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


@dataclass(frozen=True, slots=True)
class ChartFeed:
    entries: list[ChartEntry]
    country: str
    updated: str = ""
    fetched_at: float = 0.0


class AppleMusicClient:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, str, int], tuple[float, ChartFeed]] = {}

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
                    payload = response.read().decode("utf-8")
                break
            except urllib.error.HTTPError as error:
                raise AppleMusicError(
                    f"Apple Music charts are unavailable ({error.code})."
                ) from error
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                if attempt == 0:
                    logger.debug("Apple Music request retrying after %s", error)
                    time.sleep(1)
                    continue
                raise AppleMusicError(
                    "Apple Music charts could not be reached."
                ) from error
        try:
            return json.loads(payload)
        except ValueError as error:
            raise AppleMusicError(
                "Apple Music returned an unreadable chart."
            ) from error
