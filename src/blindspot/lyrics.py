from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from . import __version__
from .models import SpotifyItem

API_ROOT = "https://lrclib.net/api"
USER_AGENT = f"BlindSpot/{__version__} (accessible Spotify client)"
TIMESTAMP = re.compile(r"^\[\d{1,3}:\d{2}(?:\.\d+)?\]\s*")
SYNCED_LINE = re.compile(
    r"^\[(\d{1,3}):(\d{2})(?:\.(\d+))?\]\s*(.*)$"
)


class LyricsError(RuntimeError):
    pass


class LyricsUnavailable(LyricsError):
    pass


@dataclass(slots=True)
class Lyrics:
    track_name: str
    artist_name: str
    text: str
    synced: bool
    instrumental: bool = False
    track_id: str = ""
    synced_lines: list[tuple[int, str]] = field(default_factory=list)


class LRCLibClient:
    def lyrics_for(self, item: SpotifyItem) -> Lyrics:
        if not item.name or not item.artist:
            raise LyricsUnavailable("There is not enough track information to find lyrics.")

        result: dict[str, Any] | None = None
        if item.album and item.duration_ms:
            result = self._request(
                "/get",
                {
                    "track_name": item.name,
                    "artist_name": item.artist,
                    "album_name": item.album,
                    "duration": round(item.duration_ms / 1000),
                },
                missing_ok=True,
            )
        if result is None:
            matches = self._request(
                "/search",
                {
                    "track_name": item.name,
                    "artist_name": item.artist,
                },
            )
            result = self._best_match(item, matches)
        if not result:
            raise LyricsUnavailable(f"Lyrics are unavailable for {item.name}.")
        lyrics = self._map_result(result)
        lyrics.track_id = item.id
        return lyrics

    def _request(
        self,
        endpoint: str,
        query: dict[str, object],
        *,
        missing_ok: bool = False,
    ) -> Any:
        url = f"{API_ROOT}{endpoint}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code == 404 and missing_ok:
                return None
            if error.code == 404:
                raise LyricsUnavailable("Lyrics are unavailable for this track.") from error
            if error.code == 429:
                retry_after = error.headers.get("Retry-After")
                message = "LRCLIB is busy. Please try again later."
                if retry_after:
                    message = f"LRCLIB is busy. Try again in {retry_after} seconds."
                raise LyricsError(message) from error
            raise LyricsError(f"LRCLIB returned error {error.code}.") from error
        except (OSError, ValueError) as error:
            raise LyricsError("Lyrics could not be retrieved.") from error

    @staticmethod
    def _best_match(
        item: SpotifyItem,
        matches: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        wanted_title = _normalized(item.name)
        wanted_artist = _normalized(item.artist)
        wanted_album = _normalized(item.album)
        wanted_duration = round(item.duration_ms / 1000) if item.duration_ms else 0

        ranked: list[tuple[int, dict[str, Any]]] = []
        for match in matches:
            title = _normalized(str(match.get("trackName") or ""))
            artist = _normalized(str(match.get("artistName") or ""))
            if title != wanted_title or artist != wanted_artist:
                continue
            score = 100
            if wanted_album and _normalized(str(match.get("albumName") or "")) == wanted_album:
                score += 20
            if wanted_duration:
                difference = abs(int(match.get("duration") or 0) - wanted_duration)
                if difference <= 2:
                    score += 30
                elif difference <= 10:
                    score += 10
                else:
                    score -= difference
            ranked.append((score, match))
        return max(ranked, key=lambda value: value[0])[1] if ranked else None

    @staticmethod
    def _map_result(value: dict[str, Any]) -> Lyrics:
        instrumental = bool(value.get("instrumental"))
        plain = str(value.get("plainLyrics") or "").strip()
        synced = str(value.get("syncedLyrics") or "").strip()
        text = plain or _plain_from_synced(synced)
        if not instrumental and not text:
            raise LyricsUnavailable("Lyrics are unavailable for this track.")
        return Lyrics(
            track_name=str(value.get("trackName") or "Untitled"),
            artist_name=str(value.get("artistName") or ""),
            text=text,
            synced=bool(synced),
            instrumental=instrumental,
            synced_lines=_synced_lines(synced),
        )


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def _plain_from_synced(value: str) -> str:
    lines = []
    for line in value.splitlines():
        text = TIMESTAMP.sub("", line).strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def _synced_lines(value: str) -> list[tuple[int, str]]:
    lines = []
    for line in value.splitlines():
        match = SYNCED_LINE.match(line)
        if not match:
            continue
        minutes, seconds, fraction, text = match.groups()
        if not text.strip():
            continue
        milliseconds = (int(minutes) * 60 + int(seconds)) * 1000
        if fraction:
            milliseconds += int((fraction + "000")[:3])
        lines.append((milliseconds, text.strip()))
    return lines
