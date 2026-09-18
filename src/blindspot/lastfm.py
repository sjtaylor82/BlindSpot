from __future__ import annotations

import json
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
