from __future__ import annotations

import json
import logging
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
import time

from . import __version__
from .network import TLS_CONTEXT


API_ROOT = "https://ws.audioscrobbler.com/2.0/"
DEFAULT_API_KEY = "89b5734bfa551e2b56ca0b041f170b4a"
CACHE_SECONDS = 24 * 60 * 60
logger = logging.getLogger(__name__)


class LastfmError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SimilarTrack:
    name: str
    artist: str
    url: str = ""


@dataclass(frozen=True, slots=True)
class SimilarArtist:
    name: str
    url: str = ""


@dataclass(frozen=True, slots=True)
class TaggedItem:
    name: str
    artist: str = ""
    url: str = ""


@dataclass(frozen=True, slots=True)
class GenreTag:
    name: str
    weight: int = 0


@dataclass(frozen=True, slots=True)
class TagPage:
    items: list[TaggedItem]
    page: int
    total_pages: int


# Community tags mix genres with opinions, listening habits and
# demographics. These never describe a musical genre, so they are dropped
# when a track or artist's tags are offered for browsing.
NON_GENRE_TAGS = frozenset(
    {
        "seen live", "want to see live", "favorites", "favourites",
        "favorite", "favourite", "favorite songs", "favourite songs",
        "female vocalists", "male vocalists", "female vocalist",
        "male vocalist", "love", "love at first listen", "awesome",
        "beautiful", "albums i own", "my music", "good music",
        "best songs ever", "all time favorites", "under 2000 listeners",
        "spotify", "lastfm", "mix", "legend", "cover", "covers",
    }
)
YEAR_TAG = re.compile(r"^\d{4}$")


def _tag_key(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value).casefold()
    return " ".join(
        "".join(
            character
            for character in folded
            if not unicodedata.combining(character)
        ).split()
    )


class LastfmClient:
    def __init__(self, api_key: str = DEFAULT_API_KEY) -> None:
        self.api_key = api_key.strip()
        self._cache: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[float, dict]] = {}

    def similar_tracks(
        self, name: str, artist: str, *, limit: int = 50
    ) -> list[SimilarTrack]:
        data = self._request(
            "track.getSimilar",
            track=name,
            artist=artist,
            limit=str(limit),
            autocorrect="1",
        )
        return [
            SimilarTrack(
                str(value.get("name") or ""),
                str((value.get("artist") or {}).get("name") or ""),
                str(value.get("url") or ""),
            )
            for value in (data.get("similartracks") or {}).get("track", [])
            if value.get("name") and (value.get("artist") or {}).get("name")
        ]

    def similar_artists(
        self, name: str, *, limit: int = 20
    ) -> list[SimilarArtist]:
        data = self._request(
            "artist.getSimilar",
            artist=name,
            limit=str(limit),
            autocorrect="1",
        )
        return [
            SimilarArtist(
                str(value.get("name") or ""),
                str(value.get("url") or ""),
            )
            for value in (data.get("similarartists") or {}).get("artist", [])
            if value.get("name")
        ]

    def top_genre_tags(
        self,
        kind: str,
        name: str,
        artist: str = "",
        *,
        limit: int = 8,
    ) -> list[GenreTag]:
        """Return the strongest community tags for a track or artist.

        Weights are Last.fm's own 0-100 scale relative to the top tag. Tags
        that only repeat the artist or title, name a year, or are not about
        genre at all are dropped.
        """
        if kind == "track":
            data = self._request(
                "track.getTopTags",
                track=name,
                artist=artist,
                autocorrect="1",
            )
        elif kind == "artist":
            data = self._request(
                "artist.getTopTags",
                artist=name,
                autocorrect="1",
            )
        else:
            raise ValueError(f"Unsupported Last.fm tag source: {kind}")
        own_names = {_tag_key(name), _tag_key(artist)} - {""}
        tags: list[GenreTag] = []
        seen: set[str] = set()
        for value in (data.get("toptags") or {}).get("tag", []):
            tag_name = str(value.get("name") or "").strip()
            key = _tag_key(tag_name)
            if (
                not key
                or key in seen
                or key in own_names
                or key in NON_GENRE_TAGS
                or YEAR_TAG.match(key)
            ):
                continue
            seen.add(key)
            tags.append(GenreTag(tag_name, int(value.get("count") or 0)))
        tags.sort(key=lambda tag: tag.weight, reverse=True)
        logger.debug(
            "Last.fm genre tags kind=%s name=%r tags=%d",
            kind,
            name,
            len(tags),
        )
        return tags[:limit]

    def top_tag_items(
        self,
        tag: str,
        kind: str,
        *,
        page: int = 1,
        limit: int = 20,
    ) -> TagPage:
        methods = {
            "track": ("tag.getTopTracks", "tracks", "track"),
            "album": ("tag.getTopAlbums", "albums", "album"),
            "artist": ("tag.getTopArtists", "artists", "artist"),
        }
        if kind not in methods:
            raise ValueError(f"Unsupported Last.fm tag result type: {kind}")
        method, container, item_key = methods[kind]
        data = self._request(
            method,
            tag=tag,
            page=str(page),
            limit=str(limit),
        )
        section = data.get(container) or {}
        attributes = section.get("@attr") or {}
        total_pages = int(attributes.get("totalPages") or page)
        items = []
        for value in section.get(item_key, []):
            name = str(value.get("name") or "")
            artist_value = value.get("artist") or ""
            artist = (
                str(artist_value.get("name") or "")
                if isinstance(artist_value, dict)
                else str(artist_value)
            )
            if name:
                items.append(
                    TaggedItem(name, artist, str(value.get("url") or ""))
                )
        logger.debug(
            "Last.fm tag response tag=%r kind=%s page=%d items=%d total_pages=%d",
            tag,
            kind,
            page,
            len(items),
            total_pages,
        )
        return TagPage(items, page, total_pages)

    def _request(self, method: str, **parameters: str) -> dict:
        if not self.api_key:
            raise LastfmError("Enter a Last.fm API key in Preferences first.")
        cache_key = (method, tuple(sorted(parameters.items())))
        cached = self._cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
            return cached[1]
        query = {
            "method": method,
            "api_key": self.api_key,
            "format": "json",
            **parameters,
        }
        request = urllib.request.Request(
            f"{API_ROOT}?{urllib.parse.urlencode(query)}",
            headers={
                "User-Agent": (
                    f"BlindSpot/{__version__} "
                    "(https://github.com/sjtaylor82/BlindSpot)"
                )
            },
        )
        logger.debug("Last.fm request method=%s", method)
        try:
            with urllib.request.urlopen(
                request, timeout=20, context=TLS_CONTEXT
            ) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise LastfmError(f"Last.fm request failed: {error}") from error
        if data.get("error"):
            raise LastfmError(
                f"Last.fm returned error {data['error']}: "
                f"{data.get('message') or 'Unknown error'}"
            )
        self._cache[cache_key] = (time.monotonic(), data)
        return data
