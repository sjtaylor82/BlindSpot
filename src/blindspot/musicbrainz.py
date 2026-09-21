"""Cover versions of a song, from MusicBrainz.

MusicBrainz is a free, open music database. It links every recording of a song
to one shared "work" and marks which recordings are covers, which Spotify cannot
tell us. The lookup takes a handful of requests: find the song, find its work,
read which recordings are flagged as covers, then list the work's recordings.

MusicBrainz asks clients to identify themselves and to make no more than one
request a second, so requests are spaced out here whatever thread makes them.
"""

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
from collections.abc import Mapping
from dataclasses import dataclass

from . import __version__
from .network import TLS_CONTEXT

API_ROOT = "https://musicbrainz.org/ws/2"
CONTACT = "https://github.com/sjtaylor82/BlindSpot"
USER_AGENT = f"BlindSpot/{__version__} ( {CONTACT} )"
MIN_INTERVAL = 1.1
PAGE_SIZE = 100
# Popular songs have thousands of recordings, most of them live. Reading three
# pages keeps a lookup to about fifteen seconds, and the result says when it
# stopped. (Five pages measured at over twenty.)
MAX_RECORDINGS = 300
MAX_SEED_CANDIDATES = 3
# Recordings that share the song's title but are not linked to it in
# MusicBrainz. Editors link new releases slowly, so a recent cover is often
# missing from the song's own list. A same-title recording can be a different
# song, so these are length-checked and capped.
TITLE_SEARCH_LIMIT = 100
MAX_UNLINKED = 40
LENGTH_TOLERANCE = 0.35
CACHE_SECONDS = 24 * 60 * 60
logger = logging.getLogger(__name__)

_LIVE_TITLE = re.compile(
    r"(?i)\((?:[^)]*\b)?live\b|\blive (?:at|in|from|on|version)\b|[-–—:] live\b"
)
_LIVE_DISAMBIGUATION = re.compile(r"(?i)^live\b|\blive\b.*\d{4}")
_UNWANTED = re.compile(r"(?i)\b(?:karaoke|backing track|sing[- ]?along)\b")
_VERSION_NOISE = re.compile(r"\s*[\(\[][^)\]]*[\)\]]")
# Recordings that are real covers but rarely what someone wants to hear. They
# stay in the list, at the end.
_NOVELTY = re.compile(
    r"(?i)\b(?:8[- ]?bit|chiptune|bardcore|lullaby|tribute|midi|vocaloid|"
    r"music box|nightcore|medieval)\b"
)


class MusicBrainzError(RuntimeError):
    pass


class CoversUnavailable(MusicBrainzError):
    """MusicBrainz answered, but cannot list covers for this song.

    This is a notice for the user rather than a fault.
    """


@dataclass(frozen=True, slots=True)
class Cover:
    title: str
    artist: str
    year: str
    marked_cover: bool
    recording_id: str
    # False for a same-title recording MusicBrainz has not linked to the song.
    linked: bool = True


@dataclass(frozen=True, slots=True)
class CoverResults:
    covers: list[Cover]
    work_title: str
    total_recordings: int
    examined: int
    unlinked: int = 0


def key(value: str) -> str:
    """Compare names ignoring case, accents and punctuation."""
    folded = unicodedata.normalize("NFKD", value).casefold()
    plain = "".join(c for c in folded if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w\s]", " ", plain).split())


def title_key(value: str) -> str:
    """Compare titles ignoring bracketed notes such as "(remastered)"."""
    return key(_VERSION_NOISE.sub("", value)) or key(value)


def escape_phrase(value: str) -> str:
    """Escape a value for use inside a quoted Lucene phrase."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def credit_artists(recording: Mapping) -> list[str]:
    return [
        str(credit["name"])
        for credit in recording.get("artist-credit") or []
        if isinstance(credit, dict) and credit.get("name")
    ]


def credit_string(recording: Mapping) -> str:
    return "".join(
        f"{credit['name']}{credit.get('joinphrase', '')}"
        for credit in recording.get("artist-credit") or []
        if isinstance(credit, dict) and credit.get("name")
    ).strip()


def is_live(recording: Mapping, attributes: frozenset[str]) -> bool:
    return bool(
        "live" in attributes
        or _LIVE_TITLE.search(str(recording.get("title") or ""))
        or _LIVE_DISAMBIGUATION.search(str(recording.get("disambiguation") or ""))
    )


def is_unwanted(recording: Mapping, attributes: frozenset[str]) -> bool:
    """Live recordings, videos and karaoke tracks are not covers to play."""
    if recording.get("video") or is_live(recording, attributes):
        return True
    text = f"{recording.get('title') or ''} {recording.get('disambiguation') or ''}"
    return bool(_UNWANTED.search(text))


def rank_seed_candidates(
    recordings: list[Mapping],
    title: str,
    artist: str,
) -> list[Mapping]:
    """Order search hits so a studio recording of exactly this song comes first.

    A live recording is a poor starting point: it is more likely to be filed
    against a different song than the studio original.
    """
    wanted_title = title_key(title)
    wanted_artist = key(artist)

    def by_artist(recording: Mapping) -> bool:
        return any(key(name) == wanted_artist for name in credit_artists(recording))

    exact = [
        r
        for r in recordings
        if title_key(str(r.get("title") or "")) == wanted_title and by_artist(r)
    ]
    pool = exact or [r for r in recordings if by_artist(r)]
    return sorted(
        pool,
        key=lambda r: (
            is_live(r, frozenset()) or bool(r.get("video")),
            -int(r.get("score") or 0),
        ),
    )


def select_covers(
    recordings: list[Mapping],
    flags: Mapping[str, frozenset[str]],
    source_artist: str,
    work_title: str = "",
) -> list[Cover]:
    """Turn a work's recordings into one entry per artist and title.

    Recordings by the source artist are left out, as are live, video and
    karaoke recordings. Recordings MusicBrainz marks as covers are trusted.
    Unmarked ones are kept only when their title is the song's own, which
    drops medleys and arrangements filed under the same work. Marked covers
    come first, and novelty versions such as 8-bit arrangements come last.
    """
    own = key(source_artist)
    song = title_key(work_title)
    chosen: dict[tuple[str, str], Cover] = {}
    for recording in recordings:
        artist = credit_string(recording)
        if not artist:
            continue
        if own and any(key(name) == own for name in credit_artists(recording)):
            continue
        attributes = flags.get(str(recording.get("id")), frozenset())
        if is_unwanted(recording, attributes):
            continue
        marked = "cover" in attributes
        recording_title = str(recording.get("title") or "")
        if not marked and song and not title_key(recording_title).startswith(song):
            continue
        if not marked and " / " in recording_title:
            continue
        cover = Cover(
            recording_title,
            artist,
            str(recording.get("first-release-date") or "")[:4],
            marked,
            str(recording.get("id") or ""),
        )
        identity = (title_key(cover.title), key(artist))
        kept = chosen.get(identity)
        if kept is None or (cover.marked_cover, bool(cover.year)) > (
            kept.marked_cover,
            bool(kept.year),
        ):
            chosen[identity] = cover
    return sort_covers(list(chosen.values()))


def sort_covers(covers: list[Cover]) -> list[Cover]:
    """Order covers: marked ones, then linked ones, then same-title ones.

    Novelty versions such as 8-bit arrangements go last within the whole list.
    """

    def tier(cover: Cover) -> int:
        if not cover.linked:
            return 2
        return 0 if cover.marked_cover else 1

    return sorted(
        covers,
        key=lambda c: (
            bool(_NOVELTY.search(f"{c.artist} {c.title}")),
            tier(c),
            key(c.artist),
            key(c.title),
        ),
    )


def select_title_matches(
    recordings: list[Mapping],
    known_ids: set[str],
    title: str,
    source_artist: str,
    source_length_ms: int = 0,
) -> list[Cover]:
    """Pick same-title recordings that MusicBrainz has not linked to the song.

    These are only a hint that something may be a cover, so they are held to
    the same exclusions as linked ones plus a check that the length is close
    to the source recording's. A recording with no length is accepted only for
    a title of three or more words, where an accidental match is unlikely.
    """
    wanted = title_key(title)
    own = key(source_artist)
    long_title = len(wanted.split()) >= 3
    found: dict[tuple[str, str], Cover] = {}
    for recording in recordings:
        identifier = str(recording.get("id") or "")
        if identifier in known_ids:
            continue
        recording_title = str(recording.get("title") or "")
        if title_key(recording_title) != wanted:
            continue
        artist = credit_string(recording)
        if not artist:
            continue
        if own and any(key(name) == own for name in credit_artists(recording)):
            continue
        if is_unwanted(recording, frozenset()):
            continue
        length = int(recording.get("length") or 0)
        if length and source_length_ms:
            if abs(length - source_length_ms) / source_length_ms > LENGTH_TOLERANCE:
                continue
        elif not length and not long_title:
            continue
        identity = (wanted, key(artist))
        found.setdefault(
            identity,
            Cover(
                recording_title,
                artist,
                str(recording.get("first-release-date") or "")[:4],
                False,
                identifier,
                linked=False,
            ),
        )
    return sort_covers(list(found.values()))[:MAX_UNLINKED]


class MusicBrainzClient:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_request = 0.0
        self._cache: dict[tuple[str, str], tuple[float, CoverResults]] = {}

    def find_covers(
        self,
        title: str,
        artist: str,
        duration_ms: int = 0,
    ) -> CoverResults:
        """List other artists' recordings of the same song.

        `duration_ms` is the length of the track being looked up. It is used
        only to sanity-check same-title recordings that are not linked to the
        song, so it does not change what is cached.
        """
        cache_key = (title_key(title), key(artist))
        cached = self._cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
            logger.debug("MusicBrainz covers served from cache")
            return cached[1]
        work_id, work_title = self._find_work(title, artist)
        flags = self._work_flags(work_id)
        recordings, total = self._browse_recordings(work_id)
        covers = select_covers(recordings, flags, artist, work_title)
        unlinked = self._unlinked_matches(
            title,
            artist,
            duration_ms,
            {str(r.get("id")) for r in recordings} | set(flags),
        )
        seen = {(title_key(c.title), key(c.artist)) for c in covers}
        unlinked = [
            c for c in unlinked if (title_key(c.title), key(c.artist)) not in seen
        ]
        covers = sort_covers(covers + unlinked)
        result = CoverResults(
            covers, work_title, total, len(recordings), len(unlinked)
        )
        logger.info(
            "MusicBrainz covers title=%r artist=%r recordings=%d examined=%d "
            "covers=%d unlinked=%d",
            title,
            artist,
            total,
            len(recordings),
            len(covers),
            len(unlinked),
        )
        self._cache[cache_key] = (time.monotonic(), result)
        return result

    def _unlinked_matches(
        self,
        title: str,
        artist: str,
        duration_ms: int,
        known_ids: set[str],
    ) -> list[Cover]:
        """Find same-title recordings missing from the song's own list."""
        try:
            data = self._get(
                "recording",
                query=f'recording:"{escape_phrase(title)}"',
                limit=TITLE_SEARCH_LIMIT,
            )
        except MusicBrainzError as error:
            # The song's own list is still good; do not lose it for this.
            logger.debug("Same-title search skipped: %s", error)
            return []
        return select_title_matches(
            data.get("recordings") or [],
            known_ids,
            title,
            artist,
            duration_ms,
        )

    def _find_work(self, title: str, artist: str) -> tuple[str, str]:
        data = self._get(
            "recording",
            query=(
                f'recording:"{escape_phrase(title)}" '
                f'AND artist:"{escape_phrase(artist)}"'
            ),
            limit=25,
        )
        candidates = rank_seed_candidates(
            data.get("recordings") or [],
            title,
            artist,
        )[:MAX_SEED_CANDIDATES]
        if not candidates:
            raise CoversUnavailable(
                f"MusicBrainz could not find {title} by {artist}."
            )
        for candidate in candidates:
            recording = self._get(
                f"recording/{candidate['id']}",
                inc="work-rels",
            )
            for relation in recording.get("relations") or []:
                work = relation.get("work")
                if work and work.get("id"):
                    return str(work["id"]), str(work.get("title") or title)
        raise CoversUnavailable(
            f"MusicBrainz has no song entry linked to {title} by {artist}, so "
            "it cannot list covers of it."
        )

    def _work_flags(self, work_id: str) -> dict[str, frozenset[str]]:
        data = self._get(f"work/{work_id}", inc="recording-rels")
        flags: dict[str, frozenset[str]] = {}
        for relation in data.get("relations") or []:
            recording = relation.get("recording")
            if recording and recording.get("id"):
                flags[str(recording["id"])] = frozenset(
                    str(attribute).casefold()
                    for attribute in relation.get("attributes") or []
                )
        return flags

    def _browse_recordings(self, work_id: str) -> tuple[list[dict], int]:
        recordings: list[dict] = []
        total = 0
        while len(recordings) < MAX_RECORDINGS:
            page = self._get(
                "recording",
                work=work_id,
                inc="artist-credits",
                limit=PAGE_SIZE,
                offset=len(recordings),
            )
            batch = page.get("recordings") or []
            total = int(page.get("recording-count") or 0)
            if not batch:
                break
            recordings.extend(batch)
            if len(recordings) >= total:
                break
        return recordings, total

    def _get(self, path: str, **parameters: object) -> dict:
        parameters["fmt"] = "json"
        url = f"{API_ROOT}/{path}?{urllib.parse.urlencode(parameters)}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        # One lock around the wait and the request keeps every thread inside
        # MusicBrainz's one-request-a-second rule.
        with self._lock:
            wait = MIN_INTERVAL - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            logger.debug("MusicBrainz request %s", path.split("/")[0])
            try:
                with urllib.request.urlopen(
                    request, timeout=20, context=TLS_CONTEXT
                ) as response:
                    payload = response.read().decode("utf-8")
            except urllib.error.HTTPError as error:
                if error.code in (429, 503):
                    raise MusicBrainzError(
                        "MusicBrainz is busy. Try again in a minute."
                    ) from error
                raise MusicBrainzError(
                    f"MusicBrainz returned an error ({error.code})."
                ) from error
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                raise MusicBrainzError(
                    "MusicBrainz could not be reached."
                ) from error
            finally:
                self._last_request = time.monotonic()
        try:
            return json.loads(payload)
        except ValueError as error:
            raise MusicBrainzError(
                "MusicBrainz returned an unreadable answer."
            ) from error
