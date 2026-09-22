from __future__ import annotations

import json
import logging
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from statistics import median
from typing import Any

from . import __version__
from .models import SpotifyItem
from . import messages as msg
from .network import TLS_CONTEXT

logger = logging.getLogger(__name__)

API_ROOT = "https://lrclib.net/api"
USER_AGENT = f"BlindSpot/{__version__} (accessible Spotify client)"
TIMESTAMP = re.compile(r"^\[\d{1,3}:\d{2}(?:\.\d+)?\]\s*")
SYNCED_LINE = re.compile(
    r"^\[(\d{1,3}):(\d{2})(?:\.(\d+))?\]\s*(.*)$"
)
INSTRUMENTAL_WORDS = (
    r"instrumental|karaoke|backing track|no vocals?|minus one"
)
INSTRUMENTAL_QUALIFIER = re.compile(
    rf"\s*[\(\[].*?\b(?:{INSTRUMENTAL_WORDS})\b.*?[\)\]]",
    re.IGNORECASE,
)
KARAOKE_ATTRIBUTION = re.compile(
    (
        r"\s*[\(\[].*?\b(?:originally performed by|in the style of|"
        r"made famous by)\b.*?[\)\]]"
    ),
    re.IGNORECASE,
)
INSTRUMENTAL_SUFFIX = re.compile(
    rf"\s*(?:[-–—]\s*)?(?:{INSTRUMENTAL_WORDS})(?:\s+version)?\s*$",
    re.IGNORECASE,
)
TITLE_DIVIDER = re.compile(r"\s*(?::|[,;]|[–—]|\s+-\s+)\s*")
TITLE_WORD = re.compile(r"[^\W_]+|\d+", re.UNICODE)
MOVEMENT_TITLE_SIMILARITY = 0.88
SECTION_SILENCE_MS = 4_000
SECTION_UNMARKED_GAP_MS = 8_000
SECTION_NEAR_MS = 250
SECTION_RESTART_MS = 2_000


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
    substitute: bool = False
    synced_breaks: list[int] = field(default_factory=list)
    translated_text: str = ""
    translated_language: str = ""


class LRCLibClient:
    def __init__(self) -> None:
        self._request_lock = threading.Lock()

    def lyrics_for(self, item: SpotifyItem) -> Lyrics:
        if not item.name or not item.artist:
            raise LyricsUnavailable(msg.NOT_ENOUGH_LYRIC_INFO)

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
            movement = _movement_title(item.name)
            if result is None and movement != item.name:
                matches = self._request(
                    "/search",
                    {
                        "track_name": movement,
                        "artist_name": _primary_artist(item.artist),
                    },
                )
                result = self._best_match(item, matches)
        substitute = False
        title_is_instrumental = (
            _normalized(_commercial_title(item.name)) != _normalized(item.name)
        )
        if (
            bool(result and result.get("instrumental"))
            or (not result and title_is_instrumental)
        ):
            substitute_result = self._instrumental_match(item)
            if substitute_result:
                result = substitute_result
                substitute = True
        if not result:
            raise LyricsUnavailable(msg.lyrics_unavailable(item.name))
        lyrics = self._map_result(result)
        lyrics.track_id = item.id
        lyrics.substitute = substitute
        return lyrics

    def _instrumental_match(
        self,
        item: SpotifyItem,
    ) -> dict[str, Any] | None:
        title = _commercial_title(item.name)
        matches = self._request("/search", {"track_name": title})
        wanted_title = _normalized(title)
        wanted_artist = _normalized(item.artist)
        wanted_duration = round(item.duration_ms / 1000) if item.duration_ms else 0
        ranked: list[tuple[int, dict[str, Any]]] = []
        for match in matches:
            if bool(match.get("instrumental")) or not match.get("syncedLyrics"):
                continue
            if _normalized(str(match.get("trackName") or "")) != wanted_title:
                continue
            duration = int(match.get("duration") or 0)
            if wanted_duration and (
                not duration or abs(duration - wanted_duration) > 10
            ):
                continue
            score = 100
            if _normalized(str(match.get("artistName") or "")) == wanted_artist:
                score += 50
            if wanted_duration and duration:
                score += 10 - abs(duration - wanted_duration)
            ranked.append((score, match))
        return max(ranked, key=lambda value: value[0])[1] if ranked else None

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
            with self._request_lock:
                for attempt in range(2):
                    try:
                        return self._fetch(request)
                    except TimeoutError:
                        if attempt == 0:
                            continue
                        raise
                    except urllib.error.HTTPError as error:
                        if error.code != 503 or attempt != 0:
                            raise
                        retry_after = (
                            error.headers.get("Retry-After")
                            if error.headers
                            else None
                        )
                        try:
                            delay = float(retry_after) if retry_after else 2.0
                        except ValueError:
                            delay = 2.0
                        delay = max(0.5, min(delay, 5.0))
                        logger.info(
                            "LRCLIB returned 503; retrying once in %.1f seconds",
                            delay,
                        )
                        time.sleep(delay)
        except urllib.error.HTTPError as error:
            if error.code == 404 and missing_ok:
                return None
            if error.code == 404:
                raise LyricsUnavailable(msg.LYRICS_UNAVAILABLE_TRACK) from error
            if error.code == 429:
                retry_after = error.headers.get("Retry-After")
                message = msg.LRCLIB_BUSY
                if retry_after:
                    message = msg.lrclib_retry(retry_after)
                raise LyricsError(message) from error
            raise LyricsError(msg.lrclib_error(error.code)) from error
        except (OSError, ValueError) as error:
            raise LyricsError(msg.LYRICS_RETRIEVAL_FAILED) from error

    @staticmethod
    def _fetch(request: urllib.request.Request) -> Any:
        with urllib.request.urlopen(
            request,
            timeout=15,
            context=TLS_CONTEXT,
        ) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _best_match(
        item: SpotifyItem,
        matches: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        wanted_artist = _primary_artist(item.artist)
        wanted_album = _normalized(item.album)
        wanted_duration = round(item.duration_ms / 1000) if item.duration_ms else 0

        ranked: list[tuple[int, dict[str, Any]]] = []
        for match in matches:
            title_score = _title_match_score(
                item.name,
                str(match.get("trackName") or ""),
            )
            if title_score is None or not _artist_matches(
                wanted_artist,
                str(match.get("artistName") or ""),
            ):
                continue
            score = title_score
            if wanted_album and _normalized(str(match.get("albumName") or "")) == wanted_album:
                score += 20
            if wanted_duration:
                duration = int(match.get("duration") or 0)
                if not duration:
                    continue
                difference = abs(duration - wanted_duration)
                if difference <= 2:
                    score += 30
                elif difference <= 10:
                    score += 10
                else:
                    continue
            ranked.append((score, match))
        return max(ranked, key=lambda value: value[0])[1] if ranked else None

    @staticmethod
    def _map_result(value: dict[str, Any]) -> Lyrics:
        instrumental = bool(value.get("instrumental"))
        plain = str(value.get("plainLyrics") or "").strip()
        synced = str(value.get("syncedLyrics") or "").strip()
        text = plain or _plain_from_synced(synced)
        if not instrumental and not text:
            raise LyricsUnavailable(msg.LYRICS_UNAVAILABLE_TRACK)
        return Lyrics(
            track_name=str(value.get("trackName") or "Untitled"),
            artist_name=str(value.get("artistName") or ""),
            text=text,
            synced=bool(synced),
            instrumental=instrumental,
            synced_lines=_synced_lines(synced),
            synced_breaks=_synced_breaks(synced),
        )


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def _title_words(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    value = "".join(character for character in value if not unicodedata.combining(character))
    return " ".join(TITLE_WORD.findall(value))


def _movement_title(value: str) -> str:
    parts = [part.strip() for part in TITLE_DIVIDER.split(value) if part.strip()]
    return parts[-1] if parts else value


def _title_match_score(wanted: str, candidate: str) -> int | None:
    wanted_title = _title_words(wanted)
    candidate_title = _title_words(candidate)
    if not wanted_title or not candidate_title:
        return None
    if wanted_title == candidate_title:
        return 120

    wanted_movement = _title_words(_movement_title(wanted))
    candidate_movement = _title_words(_movement_title(candidate))
    if wanted_movement == candidate_movement:
        return 100
    similarity = SequenceMatcher(
        None,
        wanted_movement,
        candidate_movement,
    ).ratio()
    if similarity >= MOVEMENT_TITLE_SIMILARITY:
        return 90
    return None


def _primary_artist(value: str) -> str:
    return _normalized(value.split(",", 1)[0])


def _artist_matches(wanted_primary: str, candidate: str) -> bool:
    candidate_artist = _normalized(candidate)
    if not wanted_primary or not candidate_artist:
        return False
    return (
        candidate_artist == wanted_primary
        or _primary_artist(candidate) == wanted_primary
    )


def _commercial_title(value: str) -> str:
    title = INSTRUMENTAL_QUALIFIER.sub("", value)
    title = KARAOKE_ATTRIBUTION.sub("", title)
    title = INSTRUMENTAL_SUFFIX.sub("", title)
    return " ".join(title.split()).strip(" -–—") or value


def _plain_from_synced(value: str) -> str:
    lines = []
    for line in value.splitlines():
        text = TIMESTAMP.sub("", line).strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def _timed_lines(value: str) -> list[tuple[int, str]]:
    lines = []
    for line in value.splitlines():
        match = SYNCED_LINE.match(line)
        if not match:
            continue
        minutes, seconds, fraction, text = match.groups()
        milliseconds = (int(minutes) * 60 + int(seconds)) * 1000
        if fraction:
            milliseconds += int((fraction + "000")[:3])
        lines.append((milliseconds, text.strip()))
    return lines


def _synced_lines(value: str) -> list[tuple[int, str]]:
    return [(ms, text) for ms, text in _timed_lines(value) if text]


def _synced_breaks(value: str) -> list[int]:
    """Timestamps of empty timed lines, which mark where the singing stops."""
    return [ms for ms, text in _timed_lines(value) if not text]


def section_starts(
    lines: list[tuple[int, str]],
    breaks: list[int] | tuple[int, ...] = (),
    text: str = "",
) -> list[int]:
    """Start times of the lyric sections (verses, choruses) in a song.

    When the plain lyrics separate stanzas with blank lines, those stanzas are
    matched to the timed lines. Otherwise a section begins after a gap in the
    vocals. When the lyrics mark where a
    line stops singing, the silence before the next line is measured directly.
    Otherwise a section begins where the spacing between two lines is much
    longer than the song's usual line spacing.
    """
    if not lines:
        return []
    stanzas = _stanza_starts(lines, text)
    if stanzas:
        return stanzas
    starts = [lines[0][0]]
    spacings = [later[0] - earlier[0] for earlier, later in zip(lines, lines[1:])]
    typical = median(spacings) if spacings else 0
    unmarked_gap = max(SECTION_UNMARKED_GAP_MS, 2 * typical)
    for (previous_ms, _), (start_ms, _) in zip(lines, lines[1:]):
        stops = [stop for stop in breaks if previous_ms < stop < start_ms]
        if stops:
            is_break = start_ms - min(stops) >= SECTION_SILENCE_MS
        else:
            is_break = start_ms - previous_ms >= unmarked_gap
        if is_break:
            starts.append(start_ms)
    return starts


def _stanza_starts(
    lines: list[tuple[int, str]],
    text: str,
) -> list[int] | None:
    """Section starts from the blank lines between stanzas in ``text``."""
    entries: list[tuple[str, bool]] = []
    after_blank = False
    for row in text.splitlines():
        if not row.strip():
            after_blank = bool(entries)
            continue
        entries.append((_normalized(row), after_blank))
        after_blank = False
    if not any(starts_stanza for _, starts_stanza in entries):
        return None
    starts = [lines[0][0]]
    position = 0
    matched = 0
    for wanted, starts_stanza in entries:
        for index in range(position, min(position + 3, len(lines))):
            if _normalized(lines[index][1]) != wanted:
                continue
            if starts_stanza and index > 0:
                starts.append(lines[index][0])
            position = index + 1
            matched += 1
            break
    if matched < 0.8 * min(len(entries), len(lines)):
        return None
    return sorted(set(starts))


def section_target(
    starts: list[int],
    position_ms: int,
    direction: int,
) -> int | None:
    """Index of the section to jump to from ``position_ms``, if there is one."""
    if direction > 0:
        return next(
            (
                index
                for index, start in enumerate(starts)
                if start > position_ms + SECTION_NEAR_MS
            ),
            None,
        )
    earlier = [
        index
        for index, start in enumerate(starts)
        if start < position_ms - SECTION_RESTART_MS
    ]
    return earlier[-1] if earlier else None
