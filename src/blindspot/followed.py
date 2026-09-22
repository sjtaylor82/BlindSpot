"""Artists and audiobook authors you follow for new releases.

The list is kept in BlindSpot's own data folder. It is separate from following
an artist on Spotify: it is a short local list that Discover and the start-up
check use to look for new releases by name.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .portable import PortableStore

FILE_NAME = "followed_artists.json"
MAX_SEEN = 500
ARTIST = "artist"
AUTHOR = "author"


def artist_key(name: str) -> str:
    """A comparable form of a name, ignoring case and accents."""
    value = unicodedata.normalize("NFKD", name).casefold()
    value = "".join(c for c in value if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w]+", " ", value).split())


def primary_artist(name: str) -> str:
    """The first credited name in a comma-separated list."""
    return " ".join(name.split(",", 1)[0].split())


@dataclass(slots=True)
class FollowedArtist:
    name: str
    apple_id: str = ""
    kind: str = ARTIST


class FollowedArtists:
    def __init__(self, store: PortableStore) -> None:
        self.store = store
        self.artists: list[FollowedArtist] = []
        self.seen: list[str] = []
        self._load()

    def _load(self) -> None:
        data = self.store.read(FILE_NAME, {}) or {}
        if not isinstance(data, dict):
            return
        for record in data.get("artists") or []:
            if isinstance(record, dict) and str(record.get("name") or "").strip():
                kind = AUTHOR if record.get("kind") == AUTHOR else ARTIST
                self.artists.append(
                    FollowedArtist(
                        str(record["name"]).strip(),
                        str(record.get("apple_id") or ""),
                        kind,
                    )
                )
        self.seen = [str(value) for value in data.get("seen") or []]

    def save(self) -> None:
        self.store.write(
            FILE_NAME,
            {
                "artists": [
                    {
                        "name": artist.name,
                        "apple_id": artist.apple_id,
                        "kind": artist.kind,
                    }
                    for artist in self.artists
                ],
                "seen": self.seen[-MAX_SEEN:],
            },
        )

    def of_kind(self, kind: str) -> list[FollowedArtist]:
        return [artist for artist in self.artists if artist.kind == kind]

    def find(self, name: str, kind: str = ARTIST) -> FollowedArtist | None:
        key = artist_key(name)
        return next(
            (
                artist
                for artist in self.artists
                if artist.kind == kind and artist_key(artist.name) == key
            ),
            None,
        )

    def is_following(self, name: str, kind: str = ARTIST) -> bool:
        return self.find(name, kind) is not None

    def follow(self, name: str, kind: str = ARTIST) -> bool:
        """Start following ``name``. Returns False if already followed."""
        name = primary_artist(name)
        if not artist_key(name) or self.find(name, kind):
            return False
        self.artists.append(FollowedArtist(name, "", kind))
        self.save()
        return True

    def unfollow(self, name: str, kind: str = ARTIST) -> bool:
        artist = self.find(name, kind)
        if not artist:
            return False
        self.artists.remove(artist)
        self.save()
        return True

    def remember_apple_ids(self, ids: dict[str, str], kind: str = ARTIST) -> None:
        """Keep Apple's numbers so later checks skip the name search."""
        changed = False
        for name, apple_id in ids.items():
            artist = self.find(name, kind)
            if artist and apple_id and artist.apple_id != apple_id:
                artist.apple_id = apple_id
                changed = True
        if changed:
            self.save()

    def unseen(self, release_ids: list[str]) -> list[str]:
        known = set(self.seen)
        return [value for value in release_ids if value not in known]

    def mark_seen(self, release_ids: list[str]) -> None:
        known = set(self.seen)
        added = [value for value in release_ids if value not in known]
        if added:
            self.seen.extend(added)
            self.save()
