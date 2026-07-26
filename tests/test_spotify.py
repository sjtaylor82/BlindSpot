import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import urllib.request

from blindspot.models import ItemKind, SpotifyItem
from blindspot.portable import PortableStore
from blindspot.spotify import (
    PlaylistContentsUnavailable,
    SpotifyClient,
    SpotifyError,
)


class StubResponse:
    def __init__(self, status=204, payload=b""):
        self.status = status
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self.payload


class ResponseParsingTests(unittest.TestCase):
    @patch(
        "blindspot.spotify.urllib.request.urlopen",
        return_value=StubResponse(),
    )
    def test_no_content_response_does_not_attempt_json_decoding(self, _urlopen):
        client = SpotifyClient.__new__(SpotifyClient)
        request = urllib.request.Request("https://api.spotify.com/v1/me/player/next")

        self.assertEqual(client._open_json(request), {})

    @patch(
        "blindspot.spotify.urllib.request.urlopen",
        return_value=StubResponse(status=200, payload=b"OK"),
    )
    def test_allow_empty_ignores_non_json_success_body(self, _urlopen):
        client = SpotifyClient.__new__(SpotifyClient)
        request = urllib.request.Request("https://api.spotify.com/v1/me/player/pause")

        self.assertEqual(client._open_json(request, allow_empty=True), {})


class TokenRefreshTests(unittest.TestCase):
    def test_concurrent_access_refreshes_and_writes_token_once(self):
        with tempfile.TemporaryDirectory() as folder:
            store = PortableStore(Path(folder))
            store.write(
                "authentication.json",
                {
                    "client_id": "client-id",
                    "refresh_token": "refresh-token",
                    "expires_at": 0,
                },
            )
            client = SpotifyClient(store)
            results = []
            errors = []

            def access_token():
                try:
                    results.append(client.access_token())
                except Exception as error:
                    errors.append(error)

            with patch.object(
                client,
                "_token_request",
                return_value={
                    "access_token": "new-token",
                    "expires_in": 3600,
                },
            ) as token_request:
                threads = [
                    threading.Thread(target=access_token)
                    for _ in range(2)
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()

            self.assertEqual(errors, [])
            self.assertEqual(results, ["new-token", "new-token"])
            token_request.assert_called_once()
            self.assertEqual(client.token["client_id"], "client-id")


class ClientIdStorageTests(unittest.TestCase):
    def test_client_id_is_saved_with_authentication(self):
        with tempfile.TemporaryDirectory() as folder:
            store = PortableStore(Path(folder))
            client = SpotifyClient(store)

            client.set_client_id(" client-id ")

            authentication = store.read("authentication.json")
            self.assertEqual(authentication["client_id"], "client-id")
            self.assertNotIn(
                "spotify_client_id",
                store.read("settings.json", {}) or {},
            )

    def test_completed_authorization_keeps_client_id_with_token(self):
        with tempfile.TemporaryDirectory() as folder:
            store = PortableStore(Path(folder))
            client = SpotifyClient(store)
            client.set_client_id("client-id")

            with patch.object(
                client,
                "_token_request",
                return_value={
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "expires_in": 3600,
                },
            ):
                client.complete_authorization("code", "verifier")

            authentication = store.read("authentication.json")
            self.assertEqual(authentication["client_id"], "client-id")
            self.assertEqual(
                authentication["refresh_token"],
                "refresh-token",
            )


class PlaybackFallbackClient(SpotifyClient):
    def __init__(self, devices):
        self.devices = devices
        self.calls = []

    def _request(
        self,
        method,
        path,
        *,
        query=None,
        body=None,
        allow_empty=False,
    ):
        self.calls.append((method, path, query, body))
        play_calls = [call for call in self.calls if call[1] == "/me/player/play"]
        if path == "/me/player/play" and len(play_calls) == 1:
            raise SpotifyError(
                "Spotify returned 404: Player command failed: "
                "No active device found"
            )
        if path == "/me/player/devices":
            return {"devices": self.devices}
        return {}


class PlaybackFallbackTests(unittest.TestCase):
    def test_play_retries_against_available_device(self):
        client = PlaybackFallbackClient(
            [
                {
                    "id": "device-1",
                    "name": "My computer",
                    "type": "computer",
                    "is_active": False,
                    "is_restricted": False,
                }
            ]
        )
        track = SpotifyItem(
            id="track-1",
            kind=ItemKind.TRACK,
            name="Song",
            uri="spotify:track:track-1",
        )

        client.play(track)

        self.assertEqual(client.calls[-1][1], "/me/player/play")
        self.assertEqual(client.calls[-1][2], {"device_id": "device-1"})

    def test_play_explains_when_no_device_is_available(self):
        client = PlaybackFallbackClient([])
        track = SpotifyItem(
            id="track-1",
            kind=ItemKind.TRACK,
            name="Song",
            uri="spotify:track:track-1",
        )

        with self.assertRaisesRegex(SpotifyError, "Open Spotify"):
            client.play(track)


class CommandClient(SpotifyClient):
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def _request(
        self,
        method,
        path,
        *,
        query=None,
        body=None,
        allow_empty=False,
    ):
        self.calls.append((method, path, query, body, allow_empty))
        return self.responses.pop(0) if self.responses else {}


class PlaylistClient(CommandClient):
    def _map_item(self, value, kind):
        return SpotifyItem(
            value["id"],
            kind,
            value["name"],
            uri=value["uri"],
            raw=dict(value),
        )


class ForbiddenPlaylistClient(PlaylistClient):
    def _request(self, *args, **kwargs):
        raise SpotifyError("Spotify returned 403: Forbidden")


class PlaybackCommandTests(unittest.TestCase):
    def test_container_totals_are_mapped_from_kind_specific_fields(self):
        client = SpotifyClient.__new__(SpotifyClient)

        album = client._map_item(
            {"id": "album", "name": "Album", "total_tracks": 11},
            ItemKind.ALBUM,
        )
        playlist = client._map_item(
            {
                "id": "playlist",
                "name": "Playlist",
                "tracks": {"total": 22},
            },
            ItemKind.PLAYLIST,
        )
        show = client._map_item(
            {
                "id": "show",
                "name": "Show",
                "publisher": "Publisher",
                "total_episodes": 33,
            },
            ItemKind.SHOW,
        )

        self.assertEqual(album.total, 11)
        self.assertEqual(playlist.total, 22)
        self.assertEqual(show.total, 33)
        self.assertEqual(show.artist, "Publisher")
        self.assertIn("33 episodes", show.accessible_label())

    def test_followed_playlist_is_marked_read_only(self):
        client = PlaylistClient(
            [
                {"id": "current-user"},
                {
                    "items": [
                        {
                            "id": "playlist-1",
                            "name": "Followed list",
                            "uri": "spotify:playlist:playlist-1",
                            "owner": {"id": "someone-else"},
                            "collaborative": False,
                        }
                    ]
                },
            ]
        )

        playlist = client.user_playlists()[0]

        self.assertFalse(playlist.raw["editable"])
        self.assertFalse(playlist.raw["owned"])

    def test_rename_playlist_uses_details_endpoint(self):
        client = CommandClient([])
        playlist = SpotifyItem(
            "playlist-1",
            ItemKind.PLAYLIST,
            "Old name",
            uri="spotify:playlist:playlist-1",
        )

        client.rename_playlist(playlist, "New name")

        self.assertEqual(client.calls[-1][0:2], ("PUT", "/playlists/playlist-1"))
        self.assertEqual(client.calls[-1][3], {"name": "New name"})
        self.assertTrue(client.calls[-1][4])

    def test_remove_playlist_uses_library_endpoint(self):
        client = CommandClient([])
        playlist = SpotifyItem(
            "playlist-1",
            ItemKind.PLAYLIST,
            "List",
            uri="spotify:playlist:playlist-1",
        )

        client.remove_playlist_from_library(playlist)

        self.assertEqual(client.calls[-1][0:2], ("DELETE", "/me/library"))
        self.assertEqual(
            client.calls[-1][2],
            {"uris": "spotify:playlist:playlist-1"},
        )

    def test_playlist_children_accept_current_item_field(self):
        track = {
            "id": "track-1",
            "name": "Current track",
            "uri": "spotify:track:track-1",
            "type": "track",
        }
        client = PlaylistClient([{"items": [{"item": track}]}])
        playlist = SpotifyItem(
            "playlist-1",
            ItemKind.PLAYLIST,
            "List",
            uri="spotify:playlist:playlist-1",
        )

        self.assertEqual(client.children(playlist)[0].id, "track-1")

    def test_playlist_children_accept_legacy_track_field(self):
        track = {
            "id": "track-1",
            "name": "Legacy track",
            "uri": "spotify:track:track-1",
            "type": "track",
        }
        client = PlaylistClient([{"items": [{"track": track}]}])
        playlist = SpotifyItem(
            "playlist-1",
            ItemKind.PLAYLIST,
            "List",
            uri="spotify:playlist:playlist-1",
        )

        self.assertEqual(client.children(playlist)[0].id, "track-1")

    def test_album_for_track_uses_embedded_album_without_request(self):
        client = PlaylistClient([])
        track = SpotifyItem(
            "track-1",
            ItemKind.TRACK,
            "Song",
            raw={
                "album": {
                    "id": "album-1",
                    "name": "The Album",
                    "uri": "spotify:album:album-1",
                    "type": "album",
                }
            },
        )

        album = client.album_for_track(track)

        self.assertEqual(album.id, "album-1")
        self.assertEqual(client.calls, [])

    def test_album_for_track_fetches_track_when_album_is_missing(self):
        client = PlaylistClient(
            [
                {
                    "id": "track-1",
                    "album": {
                        "id": "album-1",
                        "name": "The Album",
                        "uri": "spotify:album:album-1",
                        "type": "album",
                    },
                }
            ]
        )
        track = SpotifyItem("track-1", ItemKind.TRACK, "Song")

        album = client.album_for_track(track)

        self.assertEqual(album.id, "album-1")
        self.assertEqual(client.calls[-1][1], "/tracks/track-1")

    def test_forbidden_playlist_has_actionable_message(self):
        client = ForbiddenPlaylistClient([])
        playlist = SpotifyItem(
            "playlist-1",
            ItemKind.PLAYLIST,
            "List",
            uri="spotify:playlist:playlist-1",
        )

        with self.assertRaisesRegex(
            PlaylistContentsUnavailable,
            "Press F4",
        ):
            client.children(playlist)

    def test_seek_forward_is_clamped_to_track_duration(self):
        client = CommandClient(
            [{"progress_ms": 98_000, "item": {"duration_ms": 100_000}}]
        )

        position = client.seek_relative(5_000, "blindspot-device")

        self.assertEqual(position, 99_999)
        self.assertEqual(
            client.calls[-1][2],
            {"position_ms": 99_999, "device_id": "blindspot-device"},
        )
        self.assertTrue(client.calls[-1][4])

    def test_seek_to_is_clamped_to_track_duration(self):
        client = CommandClient(
            [{"progress_ms": 20_000, "item": {"duration_ms": 100_000}}]
        )

        position = client.seek_to(120_000, "blindspot-device")

        self.assertEqual(position, 99_999)
        self.assertEqual(
            client.calls[-1][2],
            {"position_ms": 99_999, "device_id": "blindspot-device"},
        )
        self.assertTrue(client.calls[-1][4])

    def test_toggle_playback_pauses_when_playing(self):
        client = CommandClient([{"is_playing": True}])

        playing = client.toggle_playback("blindspot-device")

        self.assertFalse(playing)
        self.assertEqual(client.calls[-1][1], "/me/player/pause")

    def test_pause_playback_never_toggles_to_playing(self):
        client = CommandClient([])

        client.pause_playback("speaker")

        self.assertEqual(client.calls[-1][0:2], ("PUT", "/me/player/pause"))
        self.assertEqual(client.calls[-1][2], {"device_id": "speaker"})

    def test_available_devices_excludes_restricted_and_missing_ids(self):
        client = CommandClient(
            [
                {
                    "devices": [
                        {"id": "speaker", "name": "Kitchen"},
                        {
                            "id": "restricted",
                            "name": "Restricted",
                            "is_restricted": True,
                        },
                        {"id": None, "name": "No identifier"},
                    ]
                }
            ]
        )

        devices = client.available_devices()

        self.assertEqual([device["id"] for device in devices], ["speaker"])

    def test_recently_played_maps_track_and_played_time(self):
        client = CommandClient(
            [
                {
                    "items": [
                        {
                            "played_at": "2026-07-25T01:30:00Z",
                            "track": {
                                "id": "track-1",
                                "name": "Remembered Song",
                                "type": "track",
                                "uri": "spotify:track:track-1",
                                "artists": [{"name": "The Artist"}],
                                "album": {"name": "The Album"},
                            },
                        }
                    ]
                }
            ]
        )
        client.token = {"scope": "user-read-recently-played"}

        items = client.recently_played()

        self.assertEqual(items[0].name, "Remembered Song")
        self.assertIn("played", items[0].accessible_label())
        self.assertEqual(
            client.calls[0][2],
            {"limit": 50},
        )

    def test_recently_played_explains_missing_permission(self):
        client = CommandClient([])
        client.token = {"scope": ""}

        with self.assertRaisesRegex(
            SpotifyError,
            "Recently Played needs an additional Spotify permission",
        ):
            client.recently_played()

    def test_recently_played_keeps_only_most_recent_track_occurrence(self):
        client = CommandClient(
            [
                {
                    "items": [
                        {
                            "played_at": "2026-07-25T01:00:00Z",
                            "track": {
                                "id": "repeated",
                                "name": "Repeated Song",
                                "type": "track",
                            },
                        },
                        {
                            "played_at": "2026-07-24T23:00:00Z",
                            "track": {
                                "id": "repeated",
                                "name": "Repeated Song",
                                "type": "track",
                            },
                        },
                    ]
                }
            ]
        )
        client.token = {"scope": "user-read-recently-played"}

        items = client.recently_played()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].raw["played_at"], "2026-07-25T01:00:00Z")

    def test_saved_audiobooks_maps_authors_and_chapter_count(self):
        client = CommandClient(
            [
                {
                    "items": [
                        {
                            "id": "book-1",
                            "name": "The Book",
                            "uri": "spotify:audiobook:book-1",
                            "authors": [{"name": "The Author"}],
                            "total_chapters": 9,
                        }
                    ]
                }
            ]
        )

        items = client.saved_audiobooks()

        self.assertEqual(items[0].kind, ItemKind.AUDIOBOOK)
        self.assertEqual(items[0].artist, "The Author")
        self.assertEqual(items[0].total, 9)
        self.assertEqual(
            client.calls[0][0:3],
            ("GET", "/me/audiobooks", {"limit": 50}),
        )

    def test_audiobook_chapters_include_saved_resume_position(self):
        client = CommandClient(
            [
                {
                    "items": [
                        {
                            "id": "chapter-1",
                            "name": "Chapter One",
                            "uri": "spotify:chapter:chapter-1",
                            "duration_ms": 600_000,
                            "resume_point": {
                                "fully_played": False,
                                "resume_position_ms": 125_000,
                            },
                        }
                    ]
                }
            ]
        )
        audiobook = SpotifyItem(
            id="book-1",
            kind=ItemKind.AUDIOBOOK,
            name="The Book",
            raw={"authors": [{"name": "The Author"}]},
        )

        chapters = client.audiobook_chapters(audiobook)

        self.assertEqual(chapters[0].kind, ItemKind.CHAPTER)
        self.assertEqual(chapters[0].artist, "The Author")
        self.assertEqual(chapters[0].album, "The Book")
        self.assertEqual(chapters[0].raw["resume_position_ms"], 125_000)
        self.assertIn("resume at 2 minutes 5 seconds", chapters[0].accessible_label())
        self.assertEqual(
            client.calls[0][0:3],
            ("GET", "/audiobooks/book-1/chapters", {"limit": 50}),
        )

    def test_search_supports_audiobooks_and_direct_podcast_episodes(self):
        audiobook_client = CommandClient(
            [
                {
                    "audiobooks": {
                        "items": [
                            {
                                "id": "book",
                                "name": "Book",
                                "uri": "spotify:audiobook:book",
                                "authors": [{"name": "Author"}],
                            }
                        ]
                    }
                },
                {"audiobooks": {"items": []}},
            ]
        )
        episode_client = CommandClient(
            [
                {
                    "episodes": {
                        "items": [
                            {
                                "id": "episode",
                                "name": "Episode",
                                "type": "episode",
                                "uri": "spotify:episode:episode",
                            }
                        ]
                    }
                },
                {"episodes": {"items": []}},
            ]
        )

        books = audiobook_client.search("query", "audiobook")
        episodes = episode_client.search("query", "episode")

        self.assertEqual(books[0].kind, ItemKind.AUDIOBOOK)
        self.assertEqual(books[0].artist, "Author")
        self.assertEqual(episodes[0].kind, ItemKind.EPISODE)
        self.assertEqual(
            audiobook_client.calls[0][2]["type"],
            "audiobook",
        )
        self.assertEqual(episode_client.calls[0][2]["type"], "episode")

    def test_saved_podcast_library_maps_shows_and_episodes(self):
        client = CommandClient(
            [
                {
                    "items": [
                        {
                            "show": {
                                "id": "show",
                                "name": "Show",
                                "type": "show",
                                "uri": "spotify:show:show",
                            }
                        }
                    ]
                },
                {
                    "items": [
                        {
                            "episode": {
                                "id": "episode",
                                "name": "Episode",
                                "type": "episode",
                                "uri": "spotify:episode:episode",
                            }
                        }
                    ]
                },
            ]
        )

        shows = client.saved_shows()
        episodes = client.saved_episodes()

        self.assertEqual(shows[0].kind, ItemKind.SHOW)
        self.assertEqual(episodes[0].kind, ItemKind.EPISODE)
        self.assertEqual(client.calls[0][0:3], ("GET", "/me/shows", {"limit": 50}))
        self.assertEqual(
            client.calls[1][0:3],
            ("GET", "/me/episodes", {"limit": 50}),
        )

    def test_show_episode_browsing_fetches_every_page(self):
        first_page = [
            {
                "id": f"episode-{number}",
                "name": f"Episode {number}",
                "type": "episode",
                "uri": f"spotify:episode:{number}",
            }
            for number in range(50)
        ]
        client = CommandClient(
            [
                {"items": first_page, "total": 51},
                {
                    "items": [
                        {
                            "id": "episode-50",
                            "name": "Episode 50",
                            "type": "episode",
                            "uri": "spotify:episode:50",
                        }
                    ],
                    "total": 51,
                },
            ]
        )
        show = SpotifyItem(
            "show",
            ItemKind.SHOW,
            "Show",
            artist="Publisher",
        )

        episodes = client.children(show)

        self.assertEqual(len(episodes), 51)
        self.assertEqual(client.calls[1][2], {"limit": 50, "offset": 50})
        self.assertEqual(episodes[0].album, "Show")
        self.assertEqual(episodes[0].artist, "Publisher")
        self.assertEqual(episodes[0].raw["show"]["id"], "show")

    def test_episode_metadata_includes_description_and_resume_position(self):
        client = SpotifyClient.__new__(SpotifyClient)
        episode = client._map_item(
            {
                "id": "episode",
                "name": "Episode",
                "type": "episode",
                "uri": "spotify:episode:episode",
                "description": "Publisher description",
                "show": {"name": "The Show", "publisher": "Publisher"},
                "resume_point": {
                    "fully_played": False,
                    "resume_position_ms": 125_000,
                },
            },
            ItemKind.EPISODE,
        )

        self.assertEqual(episode.album, "The Show")
        self.assertEqual(episode.artist, "Publisher")
        self.assertEqual(episode.raw["description"], "Publisher description")
        self.assertEqual(episode.raw["resume_position_ms"], 125_000)
        self.assertIn("resume at 2 minutes 5 seconds", episode.accessible_label())

    def test_transfer_playback_targets_one_device_and_starts_playing(self):
        client = CommandClient([])

        client.transfer_playback("kitchen-speaker")

        self.assertEqual(client.calls[-1][0:2], ("PUT", "/me/player"))
        self.assertEqual(
            client.calls[-1][3],
            {"device_ids": ["kitchen-speaker"], "play": True},
        )

    def test_add_to_queue_targets_device_without_starting_playback(self):
        client = CommandClient([])
        track = SpotifyItem(
            "track-1",
            ItemKind.TRACK,
            "Song",
            uri="spotify:track:track-1",
        )

        client.add_to_queue(track, "blindspot-device")

        self.assertEqual(client.calls[-1][0:2], ("POST", "/me/player/queue"))
        self.assertEqual(
            client.calls[-1][2],
            {
                "uri": "spotify:track:track-1",
                "device_id": "blindspot-device",
            },
        )

    def test_play_at_restores_track_and_position(self):
        client = CommandClient([])
        track = SpotifyItem(
            "track-1",
            ItemKind.TRACK,
            "Song",
            uri="spotify:track:track-1",
        )

        client.play_at(track, 42_000, "blindspot-device")

        self.assertEqual(client.calls[-1][1], "/me/player/play")
        self.assertEqual(
            client.calls[-1][3],
            {
                "uris": ["spotify:track:track-1"],
                "position_ms": 42_000,
            },
        )
        self.assertTrue(client.calls[-1][4])

    def test_play_at_restores_playlist_context_and_track_offset(self):
        client = CommandClient([])
        track = SpotifyItem(
            "track-1",
            ItemKind.TRACK,
            "Song",
            uri="spotify:track:track-1",
        )

        client.play_at(
            track,
            42_000,
            "blindspot-device",
            "spotify:playlist:playlist-1",
        )

        self.assertEqual(
            client.calls[-1][3],
            {
                "context_uri": "spotify:playlist:playlist-1",
                "offset": {"uri": "spotify:track:track-1"},
                "position_ms": 42_000,
            },
        )

    def test_toggle_shuffle_uses_opposite_state(self):
        client = CommandClient([{"shuffle_state": False}])

        enabled = client.toggle_shuffle("blindspot-device")

        self.assertTrue(enabled)
        self.assertEqual(
            client.calls[-1][2],
            {"state": "true", "device_id": "blindspot-device"},
        )

    def test_set_shuffle_does_not_reread_playback_state(self):
        client = CommandClient([])

        enabled = client.set_shuffle(False, "blindspot-device")

        self.assertFalse(enabled)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(
            client.calls[0][2],
            {"state": "false", "device_id": "blindspot-device"},
        )

    def test_repeat_cycles_from_all_to_one(self):
        client = CommandClient([{"repeat_state": "context"}])

        state = client.cycle_repeat("blindspot-device")

        self.assertEqual(state, "track")
        self.assertEqual(
            client.calls[-1][2],
            {"state": "track", "device_id": "blindspot-device"},
        )

    def test_set_repeat_does_not_reread_playback_state(self):
        client = CommandClient([])

        state = client.set_repeat("off", "blindspot-device")

        self.assertEqual(state, "off")
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(
            client.calls[0][2],
            {"state": "off", "device_id": "blindspot-device"},
        )

    def test_create_playlist_defaults_private_and_marks_editable(self):
        client = CommandClient(
            [{"id": "playlist-1", "name": "New list", "uri": "spotify:playlist:1"}]
        )

        playlist = client.create_playlist("New list")

        self.assertTrue(playlist.raw["editable"])
        self.assertEqual(client.calls[-1][1], "/me/playlists")
        self.assertEqual(
            client.calls[-1][3],
            {"name": "New list", "public": False},
        )

    def test_remove_from_playlist_uses_current_items_endpoint(self):
        client = CommandClient([{}])
        playlist = SpotifyItem(
            "playlist-1",
            ItemKind.PLAYLIST,
            "List",
            uri="spotify:playlist:playlist-1",
        )
        track = SpotifyItem(
            "track-1",
            ItemKind.TRACK,
            "Track",
            uri="spotify:track:track-1",
        )

        client.remove_from_playlist(playlist, track)

        self.assertEqual(client.calls[-1][1], "/playlists/playlist-1/items")
        self.assertEqual(
            client.calls[-1][3],
            {"items": [{"uri": "spotify:track:track-1"}]},
        )

    def test_volume_increase_is_clamped_to_one_hundred(self):
        client = CommandClient(
            [{"device": {"volume_percent": 98}}]
        )

        volume = client.adjust_volume(5, "blindspot-device")

        self.assertEqual(volume, 100)
        self.assertEqual(
            client.calls[-1][2],
            {"volume_percent": 100, "device_id": "blindspot-device"},
        )

    def test_absolute_volume_is_clamped_and_sent_to_device(self):
        client = CommandClient([])

        volume = client.set_volume(-5, "blindspot-device")

        self.assertEqual(volume, 0)
        self.assertEqual(
            client.calls[-1][2],
            {"volume_percent": 0, "device_id": "blindspot-device"},
        )

    def test_toggle_saved_removes_an_existing_like(self):
        client = CommandClient([[True]])
        track = SpotifyItem(
            id="track-1",
            kind=ItemKind.TRACK,
            name="Song",
            uri="spotify:track:track-1",
        )

        saved = client.toggle_saved(track)

        self.assertFalse(saved)
        self.assertEqual(client.calls[-1][0:2], ("DELETE", "/me/library"))


class SearchClient(SpotifyClient):
    def __init__(self, total=None):
        self.calls = []
        self.total = total

    def _request(
        self,
        method,
        path,
        *,
        query=None,
        body=None,
        allow_empty=False,
    ):
        self.calls.append((method, path, query))
        offset = query["offset"]
        tracks = {
                "items": [
                    {
                        "id": f"track-{offset + number}",
                        "name": f"Track {offset + number}",
                        "type": "track",
                        "uri": f"spotify:track:{offset + number}",
                        "artists": [{"name": "Artist"}],
                    }
                    for number in range(10)
                ]
        }
        if self.total is not None:
            tracks["total"] = self.total
        return {"tracks": tracks}


class SearchBatchTests(unittest.TestCase):
    def test_live_category_search_combines_two_ten_item_requests(self):
        client = SearchClient()

        results = client.search("query", "track")

        self.assertEqual(len(results), 20)
        self.assertEqual(
            [call[2]["offset"] for call in client.calls],
            [0, 10],
        )

    def test_search_adds_load_more_row_and_accepts_page_offset(self):
        client = SearchClient(total=45)

        first_page = client.search("query", "track")
        second_page = client.search("query", "track", 20)

        self.assertTrue(first_page[-1].raw["load_more"])
        self.assertEqual(first_page[-1].raw["next_offset"], 20)
        self.assertEqual(
            [call[2]["offset"] for call in client.calls],
            [0, 10, 20, 30],
        )
        self.assertEqual(second_page[0].id, "track-20")
        self.assertEqual(second_page[-1].raw["next_offset"], 40)


if __name__ == "__main__":
    unittest.main()
