from __future__ import annotations

from typing import Any

from .models import ItemKind, SpotifyItem


def _track(number: int, album_number: int = 1) -> SpotifyItem:
    return SpotifyItem(
        id=f"demo-track-{number}",
        kind=ItemKind.TRACK,
        name=f"Demo Song {number:02d}",
        artist=f"Demo Artist {((number - 1) % 5) + 1}",
        album=f"Demo Album {album_number}",
        duration_ms=150_000 + number * 3_000,
        explicit=number % 9 == 0,
        uri=f"spotify:track:demo-track-{number}",
    )


class DemoSpotifyClient:
    """In-memory Spotify substitute for keyboard and accessibility testing."""

    demo_mode = True
    connected = True
    web_playback_authorized = False
    client_id = "demo"
    token: dict[str, Any] = {}

    def __init__(self) -> None:
        self.albums = [
            SpotifyItem(
                id=f"demo-album-{number}",
                kind=ItemKind.ALBUM,
                name=f"Demo Album {number}",
                artist=f"Demo Artist {((number - 1) % 5) + 1}",
                year=str(2010 + number),
                total=12,
                uri=f"spotify:album:demo-album-{number}",
            )
            for number in range(1, 25)
        ]
        self.artists = [
            SpotifyItem(
                id=f"demo-artist-{number}",
                kind=ItemKind.ARTIST,
                name=f"Demo Artist {number}",
                uri=f"spotify:artist:demo-artist-{number}",
            )
            for number in range(1, 21)
        ]
        self.playlists = [
            SpotifyItem(
                id=f"demo-playlist-{number}",
                kind=ItemKind.PLAYLIST,
                name=f"Demo Playlist {number}",
                total=8,
                uri=f"spotify:playlist:demo-playlist-{number}",
            )
            for number in range(1, 21)
        ]
        for playlist in self.playlists:
            playlist.raw["editable"] = not playlist.id.endswith("-20")
            playlist.raw["owned"] = not playlist.id.endswith("-20")
        self.shows = [
            SpotifyItem(
                id=f"demo-show-{number}",
                kind=ItemKind.SHOW,
                name=f"Demo Podcast {number}",
                total=10,
                uri=f"spotify:show:demo-show-{number}",
            )
            for number in range(1, 21)
        ]
        self.tracks = [_track(number, ((number - 1) // 12) + 1) for number in range(1, 41)]
        self.saved_ids = {track.id for track in self.tracks[:15]}
        self.queue_items: list[SpotifyItem] = []
        self.playlist_items: dict[str, list[SpotifyItem]] = {
            playlist.id: list(self.tracks[:8]) for playlist in self.playlists
        }
        self.current = self.tracks[0]
        self.is_playing = False
        self.shuffle_enabled = False
        self.repeat_state = "off"
        self.progress_ms = 35_000
        self.volume_percent = 80

    def search(self, query: str, category: str) -> list[SpotifyItem]:
        query = query.casefold()
        buckets = {
            "track": self.tracks,
            "album": self.albums,
            "artist": self.artists,
            "playlist": self.playlists,
            "show": self.shows,
        }
        if category == "all":
            results: list[SpotifyItem] = []
            for key, values in buckets.items():
                matches = self._matches(values, query)[:4]
                if matches:
                    results.append(
                        SpotifyItem(key, ItemKind.HEADING, f"{key.title()}s")
                    )
                    results.extend(matches)
            return results
        return self._matches(buckets.get(category, []), query)[:20]

    def _matches(
        self,
        items: list[SpotifyItem],
        query: str,
    ) -> list[SpotifyItem]:
        matches = [
            item
            for item in items
            if query in f"{item.name} {item.artist} {item.album}".casefold()
        ]
        # Demo mode tests interaction rather than catalog accuracy. An ordinary
        # real-world query should still populate the selected result view.
        return matches or list(items)

    def children(self, item: SpotifyItem) -> list[SpotifyItem]:
        if item.kind == ItemKind.ALBUM:
            album_number = int(item.id.rsplit("-", 1)[-1])
            return [_track(number, album_number) for number in range(1, 13)]
        if item.kind == ItemKind.ARTIST:
            return [
                album
                for album in self.albums
                if album.artist == item.name
            ]
        if item.kind == ItemKind.PLAYLIST:
            return list(self.playlist_items.get(item.id, []))
        if item.kind == ItemKind.SHOW:
            return [
                SpotifyItem(
                    id=f"{item.id}-episode-{number}",
                    kind=ItemKind.EPISODE,
                    name=f"{item.name}, Episode {number}",
                    duration_ms=1_800_000 + number * 60_000,
                    uri=f"spotify:episode:{item.id}-{number}",
                )
                for number in range(1, 11)
            ]
        return []

    def album_for_track(self, item: SpotifyItem) -> SpotifyItem:
        return next(
            album for album in self.albums if album.name == item.album
        )

    def liked_songs(self) -> list[SpotifyItem]:
        return [track for track in self.tracks if track.id in self.saved_ids]

    def recently_played(self) -> list[SpotifyItem]:
        items = list(reversed(self.tracks[:20]))
        for item in items:
            item.raw["played_at_label"] = "played recently"
        return items

    def user_playlists(self) -> list[SpotifyItem]:
        return list(self.playlists)

    def add_to_playlist(self, playlist: SpotifyItem, item: SpotifyItem) -> None:
        self.playlist_items[playlist.id].append(item)

    def create_playlist(self, name: str, public: bool = False) -> SpotifyItem:
        number = len(self.playlists) + 1
        playlist = SpotifyItem(
            id=f"demo-playlist-{number}",
            kind=ItemKind.PLAYLIST,
            name=name,
            total=0,
            uri=f"spotify:playlist:demo-playlist-{number}",
            raw={"editable": True, "owned": True, "public": public},
        )
        self.playlists.insert(0, playlist)
        self.playlist_items[playlist.id] = []
        return playlist

    def rename_playlist(self, playlist: SpotifyItem, name: str) -> None:
        playlist.name = name

    def remove_playlist_from_library(self, playlist: SpotifyItem) -> None:
        self.playlists = [
            existing for existing in self.playlists if existing.id != playlist.id
        ]

    def remove_from_playlist(
        self,
        playlist: SpotifyItem,
        item: SpotifyItem,
    ) -> None:
        self.playlist_items[playlist.id] = [
            existing
            for existing in self.playlist_items[playlist.id]
            if existing.uri != item.uri
        ]

    def queue(self) -> list[SpotifyItem]:
        return list(self.queue_items)

    def playback(self) -> SpotifyItem:
        return self.current

    def playback_state(self) -> dict[str, Any]:
        return {
            "is_playing": self.is_playing,
            "shuffle_state": self.shuffle_enabled,
            "repeat_state": self.repeat_state,
            "progress_ms": self.progress_ms,
            "item": {
                "duration_ms": self.current.duration_ms,
            },
            "device": {
                "id": "demo-device",
                "name": "BlindSpot Demo",
                "volume_percent": self.volume_percent,
            },
        }

    def available_devices(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "demo-device",
                "name": "BlindSpot Demo",
                "type": "computer",
                "is_active": True,
                "is_restricted": False,
                "volume_percent": self.volume_percent,
                "supports_volume": True,
            }
        ]

    def transfer_playback(self, device_id: str, *, play: bool = True) -> None:
        self.is_playing = play

    def play(self, item: SpotifyItem, device_id: str | None = None) -> None:
        self.current = item
        self.progress_ms = 0
        self.is_playing = True

    def play_at(
        self,
        item: SpotifyItem,
        position_ms: int,
        device_id: str,
        context_uri: str = "",
    ) -> None:
        self.current = item
        self.progress_ms = max(0, position_ms)
        self.is_playing = True

    def add_to_queue(self, item: SpotifyItem) -> None:
        self.queue_items.append(item)

    def next_queued(self) -> SpotifyItem | None:
        return self.queue_items[0] if self.queue_items else None

    def save(self, item: SpotifyItem) -> None:
        self.saved_ids.add(item.id)

    def remove(self, item: SpotifyItem) -> None:
        self.saved_ids.discard(item.id)

    def toggle_saved(self, item: SpotifyItem) -> bool:
        if item.id in self.saved_ids:
            self.saved_ids.remove(item.id)
            return False
        self.saved_ids.add(item.id)
        return True

    def toggle_playback(self, device_id: str) -> bool:
        self.is_playing = not self.is_playing
        return self.is_playing

    def pause_playback(self, device_id: str) -> None:
        self.is_playing = False

    def toggle_shuffle(self, device_id: str) -> bool:
        return self.set_shuffle(not self.shuffle_enabled, device_id)

    def set_shuffle(self, enabled: bool, device_id: str) -> bool:
        self.shuffle_enabled = enabled
        return enabled

    def cycle_repeat(self, device_id: str) -> str:
        return self.set_repeat({
            "off": "context",
            "context": "track",
            "track": "off",
        }[self.repeat_state], device_id)

    def set_repeat(self, state: str, device_id: str) -> str:
        self.repeat_state = state
        return state

    def seek_relative(self, delta_ms: int, device_id: str) -> int:
        self.progress_ms = max(
            0,
            min(self.current.duration_ms - 1, self.progress_ms + delta_ms),
        )
        return self.progress_ms

    def seek_to(self, position_ms: int, device_id: str) -> int:
        self.progress_ms = max(
            0,
            min(self.current.duration_ms - 1, position_ms),
        )
        return self.progress_ms

    def adjust_volume(self, delta_percent: int, device_id: str) -> int:
        self.volume_percent = max(
            0,
            min(100, self.volume_percent + delta_percent),
        )
        return self.volume_percent

    def next_track(self, device_id: str) -> None:
        if self.queue_items:
            self.current = self.queue_items.pop(0)
            self.progress_ms = 0

    def previous_track(self, device_id: str) -> None:
        self.progress_ms = 0

    def set_client_id(self, client_id: str) -> None:
        return

    def sign_out(self) -> None:
        return
