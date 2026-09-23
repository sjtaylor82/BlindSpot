"""What a song is about, from its English Wikipedia article.

One search request returns the introduction of the best few articles. Articles
are accepted only when they look like the right song: a song-like description,
the song's title in the article title, and the artist named in the
introduction. A wrong article is worse than none. A second request then reads
the whole article, minus lists of charts, personnel and references.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from typing import Any

from . import __version__
from . import messages as msg
from .network import TLS_CONTEXT
from .spotify import _base_track_title, _primary_track_artist

logger = logging.getLogger(__name__)

API_ROOT = "https://en.wikipedia.org/w/api.php"
CONTACT = "https://github.com/sjtaylor82/BlindSpot"
USER_AGENT = f"BlindSpot/{__version__} ( {CONTACT} )"
SONG_WORDS = re.compile(
    r"\b(?:song|single|ballad|track|recording|composition|anthem|hit)\b",
    re.IGNORECASE,
)
ARTIST_WORDS = re.compile(
    r"\b(?:band|composer|conductor|dj|ensemble|group|musician|orchestra|"
    r"producer|rapper|singer|songwriter)\b",
    re.IGNORECASE,
)
INTRO_SENTENCES = 6
MAX_ARTICLE_CHARS = 20_000
HEADING = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$", re.MULTILINE)
SKIPPED_SECTIONS = frozenset(
    {
        "references", "external links", "see also", "notes", "footnotes",
        "sources", "further reading", "bibliography", "citations",
        "personnel", "credits", "credits and personnel", "track listing",
        "track listings", "charts", "weekly charts", "year-end charts",
        "decade-end charts", "all-time charts", "certifications",
        "sales and certifications", "release history", "formats and track listings",
        "chart performance", "chart positions", "commercial performance",
    }
)


class WikipediaError(RuntimeError):
    pass


class SongStoryUnavailable(WikipediaError):
    pass


@dataclass(frozen=True, slots=True)
class SongStory:
    title: str
    summary: str
    url: str
    text: str = ""


def _plain(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    value = "".join(c for c in value if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w]+", " ", value).split())


def format_article(text: str) -> str:
    """Readable plain text from an article, without list-like sections."""
    matches = list(HEADING.finditer(text))
    parts = [text[: matches[0].start()] if matches else text]
    skip_level = 0
    for index, match in enumerate(matches):
        level = len(match.group(1))
        title = match.group(2).strip()
        if skip_level and level > skip_level:
            continue
        skip_level = level if title.casefold() in SKIPPED_SECTIONS else 0
        if skip_level:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end].strip()
        if body:
            parts.append(f"{title}\n\n{body}")
    article = "\n\n".join(part.strip() for part in parts if part.strip())
    article = re.sub(r"\n{3,}", "\n\n", article)
    if len(article) > MAX_ARTICLE_CHARS:
        article = article[:MAX_ARTICLE_CHARS].rsplit("\n", 1)[0].rstrip()
    return article


def choose_story(
    pages: list[dict[str, Any]],
    title: str,
    artist: str,
) -> SongStory | None:
    """Pick the article about this song from search results, if any is."""
    wanted_title = _plain(title)
    wanted_artist = _plain(artist)
    if not wanted_title:
        return None
    for page in sorted(pages, key=lambda value: value.get("index", 0)):
        summary = str(page.get("extract") or "").strip()
        description = str(page.get("description") or "")
        page_title = str(page.get("title") or "")
        if not summary or "may refer to" in summary[:200]:
            continue
        if wanted_title not in _plain(page_title):
            continue
        if not SONG_WORDS.search(description) and not SONG_WORDS.search(
            summary[:300]
        ):
            continue
        if wanted_artist and wanted_artist not in _plain(
            f"{description} {summary}"
        ):
            continue
        url = str(page.get("fullurl") or "")
        if not url:
            url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(
                page_title.replace(" ", "_")
            )
        return SongStory(page_title, summary, url)
    return None


def choose_artist_story(
    pages: list[dict[str, Any]], name: str
) -> SongStory | None:
    """Pick a biographical article for an unambiguous musical artist."""
    wanted = _plain(name)
    if not wanted:
        return None
    for page in sorted(pages, key=lambda value: value.get("index", 0)):
        summary = str(page.get("extract") or "").strip()
        description = str(page.get("description") or "")
        page_title = str(page.get("title") or "")
        plain_title = _plain(page_title)
        if (
            not summary
            or "may refer to" in summary[:200]
            or not (
                plain_title == wanted
                or plain_title.startswith(f"{wanted} ")
            )
            or not ARTIST_WORDS.search(f"{description} {summary[:400]}")
        ):
            continue
        url = str(page.get("fullurl") or "") or (
            "https://en.wikipedia.org/wiki/"
            + urllib.parse.quote(page_title.replace(" ", "_"))
        )
        return SongStory(page_title, summary, url)
    return None


class WikipediaClient:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], SongStory | None] = {}
        self._lock = threading.Lock()

    def song_story(self, name: str, artist: str) -> SongStory:
        title = _base_track_title(name)
        primary = _primary_track_artist(artist)
        key = (_plain(title), _plain(primary))
        with self._lock:
            cached = key in self._cache
            story = self._cache.get(key)
        if not cached:
            story = choose_story(self._search(title, primary), title, primary)
            if story is not None:
                story = self._with_full_text(story)
            with self._lock:
                self._cache[key] = story
        if story is None:
            raise SongStoryUnavailable(msg.song_story_unavailable(name))
        return story

    def artist_story(self, name: str) -> SongStory:
        key = ("artist", _plain(name))
        with self._lock:
            cached = key in self._cache
            story = self._cache.get(key)
        if not cached:
            story = choose_artist_story(self._search_artist(name), name)
            if story is not None:
                story = self._with_full_text(story)
            with self._lock:
                self._cache[key] = story
        if story is None:
            raise SongStoryUnavailable(msg.song_story_unavailable(name))
        return story

    def _with_full_text(self, story: SongStory) -> SongStory:
        try:
            pages = self._get(
                {
                    "action": "query",
                    "format": "json",
                    "formatversion": "2",
                    "titles": story.title,
                    "prop": "extracts",
                    "explaintext": "1",
                    "exlimit": "1",
                }
            ).get("pages") or []
        except WikipediaError:
            return replace(story, text=story.summary)
        full = format_article(str(pages[0].get("extract") or "")) if pages else ""
        return replace(story, text=full or story.summary)

    def _search(self, title: str, artist: str) -> list[dict[str, Any]]:
        query = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "generator": "search",
            "gsrsearch": f"{title} {artist} song",
            "gsrnamespace": "0",
            "gsrlimit": "6",
            "prop": "extracts|description|info",
            "inprop": "url",
            "exintro": "1",
            "explaintext": "1",
            "exsentences": str(INTRO_SENTENCES),
            "exlimit": "max",
        }
        return list(self._get(query).get("pages") or [])

    def _search_artist(self, name: str) -> list[dict[str, Any]]:
        query = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "generator": "search",
            "gsrsearch": f'"{name}" musician OR band OR composer',
            "gsrnamespace": "0",
            "gsrlimit": "6",
            "prop": "extracts|description|info",
            "inprop": "url",
            "exintro": "1",
            "explaintext": "1",
            "exsentences": str(INTRO_SENTENCES),
            "exlimit": "max",
        }
        return list(self._get(query).get("pages") or [])

    def _get(self, query: dict[str, str]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{API_ROOT}?{urllib.parse.urlencode(query)}",
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=15,
                context=TLS_CONTEXT,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise WikipediaError(msg.wikipedia_error(error.code)) from error
        except (OSError, ValueError) as error:
            logger.warning("Wikipedia lookup failed: %s", error)
            raise WikipediaError(msg.WIKIPEDIA_RETRIEVAL_FAILED) from error
        return payload.get("query") or {}
