from __future__ import annotations

import json
import re
import shutil
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from .models import SpotifyItem


DIRECTORY_URL = "https://itunes.apple.com/search"
USER_AGENT = "BlindSpot podcast downloader"


class PodcastDownloadUnavailable(Exception):
    pass


@dataclass(frozen=True, slots=True)
class PodcastDownload:
    url: str
    filename: str


def _normalise(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    return " ".join(re.findall(r"[a-z0-9]+", value))


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, _normalise(left), _normalise(right)).ratio()


def _read_url(url: str, *, limit: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:
        value = response.read(limit + 1)
    if len(value) > limit:
        raise PodcastDownloadUnavailable("Podcast feed too large.")
    return value


def _directory_feeds(show: str, publisher: str) -> list[str]:
    query = urllib.parse.urlencode(
        {
            "term": f"{show} {publisher}".strip(),
            "media": "podcast",
            "entity": "podcast",
            "limit": 10,
        }
    )
    try:
        payload = json.loads(_read_url(f"{DIRECTORY_URL}?{query}", limit=2_000_000))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise PodcastDownloadUnavailable("Podcast directory unavailable.") from error

    ranked: list[tuple[float, str]] = []
    for result in payload.get("results", []):
        feed_url = str(result.get("feedUrl") or "")
        if not feed_url:
            continue
        show_score = _similarity(show, str(result.get("collectionName") or ""))
        publisher_score = _similarity(
            publisher, str(result.get("artistName") or "")
        )
        ranked.append((show_score * 0.8 + publisher_score * 0.2, feed_url))
    ranked.sort(reverse=True)
    return [url for score, url in ranked[:3] if score >= 0.55]


def _episode_from_feed(feed_url: str, episode_name: str) -> PodcastDownload | None:
    try:
        root = ET.fromstring(_read_url(feed_url, limit=15_000_000))
    except (OSError, ET.ParseError, PodcastDownloadUnavailable):
        return None

    matches: list[tuple[float, str, str]] = []
    for entry in root.findall(".//item"):
        title = (entry.findtext("title") or "").strip()
        enclosure = entry.find("enclosure")
        url = str(enclosure.get("url") or "") if enclosure is not None else ""
        if not title or not url:
            continue
        score = _similarity(episode_name, title)
        if _normalise(episode_name) == _normalise(title):
            score = 1.0
        matches.append((score, title, url))
    if not matches:
        return None
    score, title, url = max(matches)
    if score < 0.78:
        return None
    return PodcastDownload(url, _safe_filename(title, url))


def _safe_filename(title: str, url: str) -> str:
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title).strip(" .")
    title = title[:180].rstrip(" .") or "Podcast episode"
    extension = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if extension not in {".aac", ".flac", ".m4a", ".m4v", ".mp3", ".mp4", ".ogg",
                         ".opus", ".wav", ".webm"}:
        extension = ".mp3"
    return f"{title}{extension}"


def find_episode_download(item: SpotifyItem) -> PodcastDownload:
    show = item.album or str((item.raw.get("show") or {}).get("name") or "")
    publisher = item.artist or str(
        (item.raw.get("show") or {}).get("publisher") or ""
    )
    if not show:
        raise PodcastDownloadUnavailable("Podcast feed unavailable.")
    for feed_url in _directory_feeds(show, publisher):
        download = _episode_from_feed(feed_url, item.name)
        if download:
            return download
    raise PodcastDownloadUnavailable("Episode download unavailable.")


def download_episode(download: PodcastDownload, destination: Path) -> None:
    request = urllib.request.Request(
        download.url,
        headers={"User-Agent": USER_AGENT},
    )
    temporary = destination.with_name(f"{destination.name}.part")
    try:
        with (
            urllib.request.urlopen(request, timeout=30) as response,
            temporary.open("wb") as output,
        ):
            shutil.copyfileobj(response, output, length=1024 * 1024)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
