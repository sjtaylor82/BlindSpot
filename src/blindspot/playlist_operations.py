from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .i18n import ntr, tr
from .models import SpotifyItem


class PlaylistClient(Protocol):
    def children(self, playlist: SpotifyItem) -> list[SpotifyItem]: ...

    def add_items_to_playlist(
        self, playlist: SpotifyItem, items: list[SpotifyItem]
    ) -> int: ...

    def remove_items_from_playlist(
        self,
        playlist: SpotifyItem,
        items: list[SpotifyItem],
    ) -> int: ...


@dataclass(frozen=True, slots=True)
class PlaylistSelection:
    item: SpotifyItem
    source_index: int


@dataclass(frozen=True, slots=True)
class PlaylistClipboard:
    selections: tuple[PlaylistSelection, ...]
    cut: bool = False
    source: SpotifyItem | None = None


def locate_playlist_selections(
    source_items: list[SpotifyItem], selected_items: list[SpotifyItem]
) -> list[PlaylistSelection]:
    """Locate selected occurrences without collapsing equal duplicates."""
    unused = set(range(len(source_items)))
    selections = []
    for selected in selected_items:
        index = next(
            (
                candidate
                for candidate in sorted(unused)
                if source_items[candidate] is selected
            ),
            None,
        )
        if index is None:
            index = next(
                (
                    candidate
                    for candidate in sorted(unused)
                    if source_items[candidate] == selected
                ),
                None,
            )
        if index is not None:
            unused.remove(index)
            selections.append(PlaylistSelection(selected, index))
    return selections


class PlaylistMovePartialError(RuntimeError):
    """The destination write succeeded but the source removal did not."""

    def __init__(self, destination: SpotifyItem, count: int) -> None:
        super().__init__(
            ntr(
                "Copied {count} item to {destination}, but could not "
                "finish removing it from the source playlist. Review both "
                "playlists to see which source entries remain. "
                "Do not repeat Move, because that would create another copy; "
                "remove any remaining source entries manually instead.",
                "Copied {count} items to {destination}, but could not "
                "finish removing them from the source playlist. Review both "
                "playlists to see which source entries remain. "
                "Do not repeat Move, because that would create another copy; "
                "remove any remaining source entries manually instead.",
                count,
            ).format(count=count, destination=destination.name)
        )
        self.destination = destination
        self.count = count


class AmbiguousPlaylistMoveError(RuntimeError):
    pass


class PlaylistSourceChangedError(RuntimeError):
    pass


class PlaylistOperations:
    def __init__(self, client: PlaylistClient) -> None:
        self.client = client

    def copy(
        self,
        destination: SpotifyItem,
        selections: list[PlaylistSelection],
    ) -> int:
        return self.client.add_items_to_playlist(
            destination, [selection.item for selection in selections]
        )

    def move(
        self,
        source: SpotifyItem,
        destination: SpotifyItem,
        selections: list[PlaylistSelection],
    ) -> int:
        source_items = self.client.children(source)
        selected_uris = {selection.item.uri for selection in selections}
        missing = {
            uri
            for uri in selected_uris
            if uri and not any(item.uri == uri for item in source_items)
        }
        if missing:
            raise PlaylistSourceChangedError(
                tr(
                    "The source playlist changed after the items were cut. "
                    "Nothing was moved; select the items again."
                )
            )
        ambiguous = {
            uri
            for uri in selected_uris
            if uri and sum(item.uri == uri for item in source_items) > 1
        }
        if ambiguous:
            raise AmbiguousPlaylistMoveError(
                tr(
                    "One or more selected recordings occur more than once in "
                    "the source playlist. Spotify cannot remove one "
                    "occurrence safely. Use Copy to playlist, then remove "
                    "the intended source occurrences manually."
                )
            )
        items = [selection.item for selection in selections]
        added = self.client.add_items_to_playlist(destination, items)
        try:
            self.client.remove_items_from_playlist(
                source,
                items,
            )
        except Exception as error:
            raise PlaylistMovePartialError(destination, added) from error
        return added
