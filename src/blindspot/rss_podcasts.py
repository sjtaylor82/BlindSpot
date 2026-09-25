from __future__ import annotations

import hashlib
import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .i18n import tr
from .models import ItemKind, SpotifyItem
from .network import TLS_CONTEXT
from .portable import PortableStore


USER_AGENT = "BlindSpot RSS podcast reader"
PODCAST_NAMESPACE = "https://podcastindex.org/namespace/1.0"


class RSSPodcastError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RSSSubscription:
    title: str
    feed_url: str
    html_url: str = ""


def normalise_feed_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url.strip())
    path = parsed.path.rstrip("/") or "/"
    return urllib.parse.urlunsplit(
        (parsed.scheme.casefold(), parsed.netloc.casefold(), path, parsed.query, "")
    )


def parse_opml(path: Path) -> list[RSSSubscription]:
    try:
        root = ET.fromstring(path.read_bytes())
    except (OSError, ET.ParseError) as error:
        raise RSSPodcastError(tr("The OPML file could not be read.")) from error
    subscriptions: list[RSSSubscription] = []
    seen: set[str] = set()
    for outline in root.findall(".//outline"):
        feed_url = str(
            outline.get("xmlUrl") or outline.get("xmlurl") or ""
        ).strip()
        if not feed_url:
            continue
        parsed = urllib.parse.urlsplit(feed_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        key = normalise_feed_url(feed_url)
        if key in seen:
            continue
        seen.add(key)
        subscriptions.append(
            RSSSubscription(
                str(outline.get("title") or outline.get("text") or feed_url).strip(),
                feed_url,
                str(outline.get("htmlUrl") or outline.get("htmlurl") or "").strip(),
            )
        )
    if not subscriptions:
        raise RSSPodcastError(tr("The OPML file contains no podcast feeds."))
    return subscriptions


class RSSSubscriptionStore:
    def __init__(self, store: PortableStore) -> None:
        self.store = store

    def read(self) -> list[RSSSubscription]:
        values = self.store.read("podcast_subscriptions.json", []) or []
        return [
            RSSSubscription(
                str(value.get("title") or value.get("feed_url") or ""),
                str(value.get("feed_url") or ""),
                str(value.get("html_url") or ""),
            )
            for value in values
            if isinstance(value, dict) and value.get("feed_url")
        ]

    def write(self, subscriptions: list[RSSSubscription]) -> None:
        self.store.write(
            "podcast_subscriptions.json",
            [
                {
                    "title": subscription.title,
                    "feed_url": subscription.feed_url,
                    "html_url": subscription.html_url,
                }
                for subscription in subscriptions
            ],
        )

    def import_file(self, path: Path) -> tuple[int, int]:
        existing = self.read()
        known = {normalise_feed_url(value.feed_url) for value in existing}
        additions = [
            value for value in parse_opml(path)
            if normalise_feed_url(value.feed_url) not in known
        ]
        self.write([*existing, *additions])
        return len(additions), len(existing) + len(additions)

    def remove(self, feed_url: str) -> None:
        wanted = normalise_feed_url(feed_url)
        self.write([
            value for value in self.read()
            if normalise_feed_url(value.feed_url) != wanted
        ])

    def shows(self) -> list[SpotifyItem]:
        return [subscription_item(value) for value in self.read()]


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
    return f"rss:{prefix}:{digest}"


def subscription_item(subscription: RSSSubscription) -> SpotifyItem:
    return SpotifyItem(
        _stable_id("show", normalise_feed_url(subscription.feed_url)),
        ItemKind.SHOW,
        subscription.title,
        raw={
            "rss_subscription": True,
            "feed_url": subscription.feed_url,
            "html_url": subscription.html_url,
            "description": tr("Imported RSS podcast subscription."),
        },
    )


def _read_feed(url: str, limit: int = 15_000_000) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=25, context=TLS_CONTEXT) as response:
            payload = response.read(limit + 1)
    except OSError as error:
        raise RSSPodcastError(tr("The podcast feed could not be loaded.")) from error
    if len(payload) > limit:
        raise RSSPodcastError(tr("The podcast feed is too large."))
    return payload


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _child_text(element: ET.Element, *names: str) -> str:
    wanted = {name.casefold() for name in names}
    for child in element:
        if _local_name(child.tag) in wanted and child.text:
            return child.text.strip()
    return ""


def _plain_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", html.unescape(value))
    return " ".join(value.split())


def _duration_ms(value: str) -> int:
    value = value.strip()
    if not value:
        return 0
    try:
        if ":" not in value:
            return int(float(value) * 1000)
        parts = [int(part) for part in value.split(":")]
    except ValueError:
        return 0
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds * 1000


def feed_episodes(show: SpotifyItem) -> list[SpotifyItem]:
    feed_url = str(show.raw.get("feed_url") or "")
    if not feed_url:
        raise RSSPodcastError(tr("Podcast feed unavailable."))
    try:
        root = ET.fromstring(_read_feed(feed_url))
    except ET.ParseError as error:
        raise RSSPodcastError(tr("The podcast feed is invalid.")) from error
    channel = next(
        (element for element in root.iter() if _local_name(element.tag) in {"channel", "feed"}),
        root,
    )
    show_title = _child_text(channel, "title") or show.name
    entries = [
        element for element in root.iter()
        if _local_name(element.tag) in {"item", "entry"}
    ]
    episodes: list[SpotifyItem] = []
    for entry in entries:
        title = _child_text(entry, "title")
        if not title:
            continue
        audio_url = ""
        for child in entry:
            name = _local_name(child.tag)
            if name == "enclosure":
                audio_url = str(child.get("url") or child.get("href") or "")
                if audio_url:
                    break
            if name == "link" and str(child.get("rel") or "") == "enclosure":
                audio_url = str(child.get("href") or "")
                if audio_url:
                    break
        if not audio_url:
            continue
        transcript_url = ""
        transcript_type = ""
        for child in entry:
            if _local_name(child.tag) != "transcript":
                continue
            candidate = str(child.get("url") or child.get("href") or "")
            if candidate:
                transcript_url = candidate
                transcript_type = str(child.get("type") or "text/plain")
                if child.get("rel") == "captions" or "vtt" in transcript_type:
                    break
        guid = _child_text(entry, "guid", "id") or audio_url
        description = _plain_text(
            _child_text(entry, "description", "summary", "content")
        )
        duration = _duration_ms(_child_text(entry, "duration"))
        episodes.append(
            SpotifyItem(
                _stable_id("episode", f"{feed_url}\n{guid}"),
                ItemKind.EPISODE,
                title,
                artist=show_title,
                album=show_title,
                duration_ms=duration,
                raw={
                    "rss_subscription": True,
                    "feed_url": feed_url,
                    "audio_url": audio_url,
                    "transcript_url": transcript_url,
                    "transcript_type": transcript_type,
                    "description": description,
                    "show": {"name": show_title, "publisher": ""},
                },
            )
        )
    return episodes
