from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ItemKind(StrEnum):
    TRACK = "track"
    ALBUM = "album"
    ARTIST = "artist"
    PLAYLIST = "playlist"
    SHOW = "show"
    EPISODE = "episode"
    HEADING = "heading"


@dataclass(slots=True)
class SpotifyItem:
    id: str
    kind: ItemKind
    name: str
    artist: str = ""
    album: str = ""
    duration_ms: int = 0
    explicit: bool = False
    year: str = ""
    total: int | None = None
    uri: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def playable(self) -> bool:
        return self.kind in {ItemKind.TRACK, ItemKind.EPISODE}

    @property
    def container(self) -> bool:
        return self.kind in {
            ItemKind.ALBUM,
            ItemKind.ARTIST,
            ItemKind.PLAYLIST,
            ItemKind.SHOW,
        }

    def accessible_label(self) -> str:
        parts = [self.name]
        if self.artist:
            parts.append(self.artist)
        if self.album and self.album != self.name:
            parts.append(self.album)
        if self.year:
            parts.append(self.year)
        if self.duration_ms:
            minutes, seconds = divmod(self.duration_ms // 1000, 60)
            parts.append(f"{minutes} minutes {seconds} seconds")
        if self.total is not None:
            noun = "song" if self.total == 1 else "songs"
            parts.append(f"{self.total} {noun}")
        if self.explicit:
            parts.append("explicit")
        if self.kind == ItemKind.PLAYLIST and self.raw.get("editable") is False:
            parts.append("read only")
        if self.raw.get("played_at_label"):
            parts.append(str(self.raw["played_at_label"]))
        if self.raw.get("bookmark_position_label"):
            parts.append(str(self.raw["bookmark_position_label"]))
        return " — ".join(parts)


@dataclass(slots=True)
class ViewState:
    title: str
    items: list[SpotifyItem]
    selected: int = 0
    query: str = ""
    category: str = "track"
