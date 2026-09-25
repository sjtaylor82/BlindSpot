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


class MusicDetailsTests(unittest.TestCase):
    def test_track_details_include_full_track_and_album(self):
        client = SpotifyClient.__new__(SpotifyClient)
        requests = []

        def request(method, path, **kwargs):
            requests.append((method, path))
            if path == "/tracks/track-id":
                return {"id": "track-id", "album": {"id": "album-id"}}
            return {"id": "album-id", "label": "Example Records"}

        client._request = request
        item = SpotifyItem("track-id", ItemKind.TRACK, "Song")

        details = client.music_details(item)

        self.assertEqual(
            requests,
            [("GET", "/tracks/track-id"), ("GET", "/albums/album-id")],
        )
        self.assertEqual(details["album"]["label"], "Example Records")

    def test_album_details_need_one_request(self):
        client = SpotifyClient.__new__(SpotifyClient)
        client._request = lambda method, path: {"id": "album-id"}

        details = client.music_details(
            SpotifyItem("album-id", ItemKind.ALBUM, "Album")
        )

        self.assertEqual(details, {"track": None, "album": {"id": "album-id"}})


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


class PlaylistBatchTests(unittest.TestCase):
    def test_add_items_to_playlist_preserves_order_and_batches_at_one_hundred(self):
        client = CommandClient([{}, {}])
        playlist = SpotifyItem("list", ItemKind.PLAYLIST, "List")
        items = [
            SpotifyItem(
                str(number),
                ItemKind.TRACK,
                f"Track {number}",
                uri=f"spotify:track:{number}",
            )
            for number in range(101)
        ]

        added = client.add_items_to_playlist(playlist, items)

        self.assertEqual(added, 101)
        self.assertEqual(
            client.calls[0][3]["uris"],
            [f"spotify:track:{number}" for number in range(100)],
        )
        self.assertEqual(client.calls[1][3]["uris"], ["spotify:track:100"])

    def test_remove_items_preserves_order_and_batches_at_one_hundred(self):
        client = CommandClient([{}, {}])
        playlist = SpotifyItem("list", ItemKind.PLAYLIST, "List")
        items = [
            SpotifyItem(
                str(number),
                ItemKind.TRACK,
                f"Track {number}",
                uri=f"spotify:track:{number}",
            )
            for number in range(101)
        ]

        removed = client.remove_items_from_playlist(playlist, items)

        self.assertEqual(removed, 101)
        self.assertEqual(
            client.calls[0][3]["items"][0], {"uri": "spotify:track:0"}
        )
        self.assertEqual(
            client.calls[1][3]["items"][0], {"uri": "spotify:track:100"}
        )


def country_client(responses):
    client = CommandClient(responses)
    # CommandClient bypasses SpotifyClient.__init__, so supply its state.
    client.token = {}
    client._account_country = ""
    return client


class RateLimitErrorTests(unittest.TestCase):
    def _raise(self, retry_after):
        import io
        import urllib.error

        headers = {} if retry_after is None else {"Retry-After": retry_after}
        error = urllib.error.HTTPError(
            "https://api.spotify.com/v1/search",
            429,
            "Too Many Requests",
            headers,
            io.BytesIO(b'{"error": {"message": "API rate limit exceeded"}}'),
        )
        client = SpotifyClient.__new__(SpotifyClient)
        request = urllib.request.Request("https://api.spotify.com/v1/search")
        with patch(
            "blindspot.spotify.urllib.request.urlopen",
            side_effect=error,
        ):
            with self.assertRaises(SpotifyError) as caught:
                client._open_json(request)
        return caught.exception

    def test_a_429_carries_status_and_retry_after_with_a_plain_message(self):
        error = self._raise("31745")

        self.assertEqual(error.status, 429)
        self.assertEqual(error.retry_after, 31745)
        self.assertIn("Try again in about 9 hours", str(error))
        self.assertNotIn("429", str(error))

    def test_a_429_without_a_usable_retry_after_still_explains_itself(self):
        for header in (None, "soon"):
            error = self._raise(header)
            self.assertIsNone(error.retry_after)
            self.assertIn("Wait a little while", str(error))

    def test_wait_is_described_in_the_most_natural_unit(self):
        from blindspot import messages

        self.assertIn("30 seconds", messages.spotify_rate_limited(30))
        self.assertIn("about a minute", messages.spotify_rate_limited(60))
        self.assertIn("about 10 minutes", messages.spotify_rate_limited(600))
        self.assertIn("about 2 hours", messages.spotify_rate_limited(7200))


class AccountCountryTests(unittest.TestCase):
    def test_country_is_read_from_the_profile_once(self):
        client = country_client([{"country": "PL"}])

        self.assertEqual(client.account_country(), "PL")
        self.assertEqual(client.account_country(), "PL")
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0][1], "/me")

    def test_country_stays_out_of_the_stored_token(self):
        client = country_client([{"country": "PL"}])

        client.account_country()

        self.assertNotIn("account_country", client.token)

    def test_a_profile_without_a_country_yields_an_empty_string(self):
        client = country_client([{}, {"country": "AU"}])

        self.assertEqual(client.account_country(), "")
        self.assertEqual(client.account_country(), "AU")


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
                "items": {"total": 22},
                "tracks": {"total": 99},
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

    def test_user_playlists_loads_every_page_in_order(self):
        def playlist(number):
            return {
                "id": f"playlist-{number}",
                "name": f"Playlist {number}",
                "uri": f"spotify:playlist:playlist-{number}",
                "owner": {"id": "current-user"},
                "collaborative": False,
            }

        client = PlaylistClient(
            [
                {"id": "current-user"},
                {
                    "items": [playlist(number) for number in range(50)],
                    "total": 52,
                },
                {
                    "items": [playlist(50), playlist(51)],
                    "total": 52,
                },
            ]
        )

        playlists = client.user_playlists()

        self.assertEqual(len(playlists), 52)
        self.assertEqual(playlists[50].id, "playlist-50")
        self.assertEqual(playlists[51].id, "playlist-51")
        self.assertEqual(
            [call[2] for call in client.calls if call[1] == "/me/playlists"],
            [{"limit": 50}, {"limit": 50, "offset": 50}],
        )

    def test_liked_songs_loads_every_page_in_order(self):
        def saved_track(number):
            return {
                "added_at": f"2026-01-{number % 28 + 1:02d}T00:00:00Z",
                "track": {
                    "id": f"track-{number}",
                    "name": f"Track {number}",
                    "uri": f"spotify:track:track-{number}",
                }
            }

        client = PlaylistClient(
            [
                {
                    "items": [saved_track(number) for number in range(50)],
                    "total": 52,
                },
                {
                    "items": [saved_track(50), saved_track(51)],
                    "total": 52,
                },
            ]
        )

        tracks = client.liked_songs()

        self.assertEqual(len(tracks), 52)
        self.assertEqual(tracks[50].id, "track-50")
        self.assertEqual(tracks[51].id, "track-51")
        self.assertEqual(tracks[0].raw["added_at"], "2026-01-01T00:00:00Z")
        self.assertEqual(
            [call[2] for call in client.calls],
            [{"limit": 50}, {"limit": 50, "offset": 50}],
        )

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

    def test_reorder_playlist_item_uses_position_endpoint(self):
        client = CommandClient([])
        playlist = SpotifyItem(
            "playlist-1",
            ItemKind.PLAYLIST,
            "List",
        )

        client.reorder_playlist_item(playlist, 2, 5)

        self.assertEqual(
            client.calls[-1][0:2],
            ("PUT", "/playlists/playlist-1/items"),
        )
        self.assertEqual(
            client.calls[-1][3],
            {
                "range_start": 2,
                "insert_before": 6,
                "range_length": 1,
            },
        )
        self.assertTrue(client.calls[-1][4])

    def test_reorder_playlist_item_moving_up_uses_target_position(self):
        client = CommandClient([])
        playlist = SpotifyItem(
            "playlist-1",
            ItemKind.PLAYLIST,
            "List",
        )

        client.reorder_playlist_item(playlist, 5, 2)

        self.assertEqual(client.calls[-1][3]["insert_before"], 2)

    def test_alternate_versions_exclude_same_recording_and_other_artist(self):
        client = CommandClient(
            [
                {
                    "tracks": {
                        "items": [
                            {
                                "id": "same-recording",
                                "name": "Example Song - Remastered",
                                "uri": "spotify:track:same-recording",
                                "artists": [{"name": "Example Artist"}],
                                "external_ids": {"isrc": "SOURCE"},
                            },
                            {
                                "id": "acoustic",
                                "name": "Example Song (Acoustic Version)",
                                "uri": "spotify:track:acoustic",
                                "artists": [{"name": "Example Artist"}],
                                "external_ids": {"isrc": "ACOUSTIC"},
                            },
                            {
                                "id": "cover",
                                "name": "Example Song",
                                "uri": "spotify:track:cover",
                                "artists": [{"name": "Other Artist"}],
                                "external_ids": {"isrc": "COVER"},
                            },
                        ]
                    }
                },
                {"tracks": {"items": []}},
            ]
        )
        source = SpotifyItem(
            "source",
            ItemKind.TRACK,
            "Example Song - Live",
            artist="Example Artist",
            uri="spotify:track:source",
            raw={"external_ids": {"isrc": "SOURCE"}},
        )

        results = client.alternate_versions(source)

        self.assertEqual([item.id for item in results], ["acoustic"])
        self.assertIn('track:"Example Song"', client.calls[0][2]["q"])
        self.assertIn('artist:"Example Artist"', client.calls[0][2]["q"])

    def test_alternate_versions_strip_named_remix_suffix(self):
        client = CommandClient(
            [
                {
                    "tracks": {
                        "items": [
                            {
                                "id": "studio",
                                "name": "Never Really Over",
                                "uri": "spotify:track:studio",
                                "artists": [{"name": "Katy Perry"}],
                                "external_ids": {"isrc": "STUDIO"},
                            }
                        ]
                    }
                },
                {"tracks": {"items": []}},
            ]
        )
        source = SpotifyItem(
            "remix",
            ItemKind.TRACK,
            "Never Really Over - Wow & Flutter Remix",
            artist="Katy Perry, Wow & Flutter",
            uri="spotify:track:remix",
            raw={"external_ids": {"isrc": "REMIX"}},
        )

        results = client.alternate_versions(source)

        self.assertEqual([item.id for item in results], ["studio"])
        self.assertIn(
            'track:"Never Really Over"',
            client.calls[0][2]["q"],
        )
        self.assertIn('artist:"Katy Perry"', client.calls[0][2]["q"])

    def test_replace_playlist_item_inserts_then_removes_original(self):
        client = CommandClient([{"snapshot_id": "one"}, {"snapshot_id": "two"}])
        playlist = SpotifyItem("playlist", ItemKind.PLAYLIST, "List")
        original = SpotifyItem(
            "original",
            ItemKind.TRACK,
            "Live",
            uri="spotify:track:original",
        )
        replacement = SpotifyItem(
            "replacement",
            ItemKind.TRACK,
            "Studio",
            uri="spotify:track:replacement",
        )

        client.replace_playlist_item(
            playlist,
            original,
            replacement,
            7,
        )

        self.assertEqual(
            client.calls[-2][0:4],
            (
                "POST",
                "/playlists/playlist/items",
                None,
                {
                    "uris": ["spotify:track:replacement"],
                    "position": 7,
                },
            ),
        )
        self.assertEqual(
            client.calls[-1][0:4],
            (
                "DELETE",
                "/playlists/playlist/items",
                None,
                {"items": [{"uri": "spotify:track:original"}]},
            ),
        )

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
        client = PlaylistClient(
            [{"items": [{"item": track, "added_at": "2026-09-20T00:00:00Z"}]}]
        )
        playlist = SpotifyItem(
            "playlist-1",
            ItemKind.PLAYLIST,
            "List",
            uri="spotify:playlist:playlist-1",
        )

        result = client.children(playlist)[0]
        self.assertEqual(result.id, "track-1")
        self.assertEqual(result.raw["added_at"], "2026-09-20T00:00:00Z")

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

    def test_artist_albums_filter_to_albums_and_load_every_page(self):
        first_page = {
            "items": [
                {
                    "id": f"album-{index}",
                    "name": f"Album {index}",
                    "release_date": f"20{index:02d}-01-01",
                }
                for index in range(10)
            ],
            "total": 11,
        }
        second_page = {
            "items": [
                {
                    "id": "album-10",
                    "name": "Album 10",
                    "release_date": "2010-01-01",
                }
            ],
            "total": 11,
        }
        client = CommandClient([first_page, second_page])
        artist = SpotifyItem("artist-1", ItemKind.ARTIST, "Artist")

        albums = client.children(artist)

        self.assertEqual(len(albums), 11)
        self.assertEqual(albums[0].id, "album-10")
        self.assertEqual(
            client.calls[0][2],
            {"include_groups": "album", "limit": 10},
        )
        self.assertEqual(
            client.calls[1][2],
            {"include_groups": "album", "limit": 10, "offset": 10},
        )

    def test_artist_albums_remove_duplicate_ids(self):
        album = {
            "id": "album-1",
            "name": "Album",
            "release_date": "2026-01-01",
        }
        client = CommandClient([{"items": [album, dict(album)], "total": 2}])
        artist = SpotifyItem("artist-1", ItemKind.ARTIST, "Artist")

        albums = client.children(artist)

        self.assertEqual([item.id for item in albums], ["album-1"])

    def test_album_children_load_every_track_page_in_order(self):
        def track(number):
            return {
                "id": f"track-{number}",
                "name": f"Track {number}",
                "uri": f"spotify:track:{number}",
            }

        client = CommandClient(
            [
                {
                    "items": [track(number) for number in range(50)],
                    "total": 52,
                },
                {
                    "items": [track(50), track(51)],
                    "offset": 50,
                    "total": 52,
                },
            ]
        )
        album = SpotifyItem("album-1", ItemKind.ALBUM, "Large Album")

        tracks = client.children(album)

        self.assertEqual(len(tracks), 52)
        self.assertEqual(tracks[50].id, "track-50")
        self.assertEqual(tracks[51].album, "Large Album")
        self.assertEqual(
            [call[2] for call in client.calls],
            [{"limit": 50}, {"limit": 50, "offset": 50}],
        )

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

    def test_recently_played_sorts_play_events_newest_first(self):
        client = CommandClient(
            [
                {
                    "items": [
                        {
                            "played_at": "2026-07-24T23:00:00Z",
                            "track": {"id": "older", "name": "Older"},
                        },
                        {
                            "played_at": "2026-07-25T02:00:00Z",
                            "track": {"id": "newest", "name": "Newest"},
                        },
                        {
                            "played_at": "2026-07-25T01:00:00Z",
                            "track": {"id": "middle", "name": "Middle"},
                        },
                    ]
                }
            ]
        )
        client.token = {"scope": "user-read-recently-played"}

        items = client.recently_played()

        self.assertEqual([item.id for item in items], ["newest", "middle", "older"])

    def test_recently_played_omits_spotify_local_files(self):
        client = CommandClient(
            [
                {
                    "items": [
                        {
                            "played_at": "2026-07-25T03:00:00Z",
                            "track": {
                                "id": "local-flag",
                                "name": "Local by flag",
                                "is_local": True,
                                "uri": "spotify:track:local-flag",
                            },
                        },
                        {
                            "played_at": "2026-07-25T02:00:00Z",
                            "track": {
                                "id": "",
                                "name": "Local by URI",
                                "uri": "spotify:local:Artist:Album:Song:180",
                            },
                        },
                        {
                            "played_at": "2026-07-25T01:00:00Z",
                            "track": {
                                "id": "spotify-track",
                                "name": "Spotify track",
                                "uri": "spotify:track:spotify-track",
                            },
                        },
                    ]
                }
            ]
        )
        client.token = {"scope": "user-read-recently-played"}

        items = client.recently_played()

        self.assertEqual([item.id for item in items], ["spotify-track"])

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

    def test_saved_album_library_maps_albums(self):
        client = CommandClient(
            [
                {
                    "items": [
                        {
                            "added_at": "2026-09-20T00:00:00Z",
                            "album": {
                                "id": "album",
                                "name": "Album",
                                "type": "album",
                                "uri": "spotify:album:album",
                            }
                        }
                    ]
                }
            ]
        )

        albums = client.saved_albums()

        self.assertEqual(albums[0].kind, ItemKind.ALBUM)
        self.assertEqual(albums[0].name, "Album")
        self.assertEqual(albums[0].raw["added_at"], "2026-09-20T00:00:00Z")
        self.assertEqual(
            client.calls[0][0:3],
            ("GET", "/me/albums", {"limit": 50}),
        )

    def test_show_episode_browsing_exposes_next_fifty_page(self):
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
        self.assertEqual(client.calls[0][2], {"limit": 50, "offset": 0})
        self.assertEqual(episodes[0].album, "Show")
        self.assertEqual(episodes[0].artist, "Publisher")
        self.assertEqual(episodes[0].raw["show"]["id"], "show")
        self.assertTrue(episodes[-1].raw["load_more_episodes"])
        self.assertEqual(episodes[-1].raw["next_offset"], 50)

        next_page = client.podcast_episodes(show, 50)

        self.assertEqual(client.calls[1][2], {"limit": 50, "offset": 50})
        self.assertEqual([episode.id for episode in next_page], ["episode-50"])

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

    def test_transfer_playback_paused_pauses_current_device_before_transfer(self):
        client = CommandClient(
            [
                {
                    "is_playing": True,
                    "device": {"id": "current-device"},
                },
                {},
                {},
            ]
        )

        client.transfer_playback_paused("phone")

        self.assertEqual(
            [call[0:2] for call in client.calls],
            [
                ("GET", "/me/player"),
                ("PUT", "/me/player/pause"),
                ("PUT", "/me/player"),
            ],
        )
        self.assertEqual(
            client.calls[-1][3],
            {"device_ids": ["phone"], "play": False},
        )

    def test_transfer_playback_paused_does_not_pause_twice_when_already_paused(self):
        client = CommandClient(
            [
                {
                    "is_playing": False,
                    "device": {"id": "current-device"},
                },
                {},
            ]
        )

        client.transfer_playback_paused("phone")

        self.assertEqual(
            [call[0:2] for call in client.calls],
            [("GET", "/me/player"), ("PUT", "/me/player")],
        )

    def test_transfer_playback_paused_can_pause_session_without_device_id(self):
        client = CommandClient(
            [
                {"is_playing": True, "device": {"id": None}},
                {},
                {},
            ]
        )

        client.transfer_playback_paused("phone")

        self.assertEqual(
            [call[0:2] for call in client.calls],
            [
                ("GET", "/me/player"),
                ("PUT", "/me/player/pause"),
                ("PUT", "/me/player"),
            ],
        )
        self.assertIsNone(client.calls[1][2])

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

    def test_play_items_starts_an_ordered_playback_sequence(self):
        client = CommandClient([])
        tracks = [
            SpotifyItem(
                f"track-{number}",
                ItemKind.TRACK,
                f"Song {number}",
                uri=f"spotify:track:track-{number}",
            )
            for number in (1, 2, 3)
        ]

        client.play_items(tracks, "blindspot-device")

        self.assertEqual(client.calls[-1][1], "/me/player/play")
        self.assertEqual(
            client.calls[-1][3],
            {
                "uris": [
                    "spotify:track:track-1",
                    "spotify:track:track-2",
                    "spotify:track:track-3",
                ]
            },
        )

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


class ClassicalWorkSearchTests(unittest.TestCase):
    class Client(SpotifyClient):
        def __init__(self, items):
            self.items = items
            self.query = None

        def _request(self, method, path, *, query=None, **kwargs):
            self.query = query
            return {f'{query["type"]}s': {"items": self.items}}

    @staticmethod
    def track(name, artist, album, number=2, duration=240000):
        return {
            "id": name,
            "name": name,
            "type": "track",
            "uri": f"spotify:track:{name}",
            "artists": [{"name": artist}],
            "album": {"name": album},
            "track_number": number,
            "disc_number": 1,
            "duration_ms": duration,
        }

    def test_prefers_matching_opening_recording_over_first_excerpt(self):
        client = self.Client([
            self.track(
                "St. Matthew Passion, BWV 244: Erbarme dich",
                "Anna Singer",
                "Bach Arias",
            ),
            self.track(
                "St. Matthew Passion, BWV 244: Part One",
                "Johann Sebastian Bach, Choir",
                "Bach: St. Matthew Passion (Complete)",
                number=1,
                duration=720000,
            ),
        ])

        result = client.find_classical_work(
            "St Matthew Passion", "Bach, Johann Sebastian"
        )

        self.assertEqual(result.id, "St. Matthew Passion, BWV 244: Part One")
        self.assertEqual(
            client.query["q"],
            '"St Matthew Passion" "Johann Sebastian Bach"',
        )

    def test_rejects_results_without_the_composer(self):
        client = self.Client([
            self.track(
                "St Matthew Passion",
                "Unrelated Ensemble",
                "Sacred Choral Favourites",
                number=1,
            )
        ])

        self.assertIsNone(
            client.find_classical_work(
                "St Matthew Passion", "Bach, Johann Sebastian"
            )
        )

    def test_album_search_prefers_complete_multi_track_recording(self):
        client = self.Client([
            {
                **self.track(
                    "Bach: St Matthew Passion Highlights",
                    "Johann Sebastian Bach",
                    "",
                    number=1,
                ),
                "total_tracks": 8,
            },
            {
                **self.track(
                    "Bach: St Matthew Passion (Complete)",
                    "Johann Sebastian Bach, Choir",
                    "",
                    number=1,
                ),
                "total_tracks": 68,
            },
        ])

        result = client.find_classical_album(
            "St Matthew Passion", "Bach, Johann Sebastian"
        )

        self.assertEqual(result.kind, ItemKind.ALBUM)
        self.assertEqual(result.name, "Bach: St Matthew Passion (Complete)")
        self.assertEqual(client.query["type"], "album")

    def test_vocal_album_search_rejects_piano_reduction(self):
        client = self.Client([
            {
                **self.track(
                    "Fauré: Requiem op. 48 (in a new version for piano)",
                    "Gabriel Fauré",
                    "",
                    number=1,
                ),
                "total_tracks": 7,
            }
        ])

        result = client.find_classical_album(
            "Requiem", "Fauré, Gabriel", require_vocal=True
        )

        self.assertIsNone(result)
        self.assertTrue(client.query["q"].endswith(" vocal"))

    def test_vocal_track_search_rejects_instrumental_version(self):
        client = self.Client([
            self.track(
                "The Pearl Fishers Duet (Instrumental)",
                "Georges Bizet, Orchestra",
                "Opera Favourites",
                number=1,
            )
        ])

        self.assertIsNone(
            client.find_classical_work(
                "The Pearl Fishers Duet",
                "Bizet, Georges",
                require_vocal=True,
            )
        )

    def test_catalogue_number_spacing_does_not_reject_messiah(self):
        client = self.Client([
            {
                **self.track(
                    "Handel: Messiah, HWV 56",
                    "George Frideric Handel, Choir",
                    "",
                    number=1,
                ),
                "total_tracks": 53,
            }
        ])

        result = client.find_classical_album(
            "Messiah, HWV56",
            "Handel, George Frideric",
            require_vocal=True,
        )

        self.assertEqual(result.name, "Handel: Messiah, HWV 56")

    def test_classical_album_alternates_cross_performers_and_exclude_current(self):
        current = {
            **self.track(
                "Handel: Messiah, HWV 56 (1751 Version)",
                "George Frideric Handel, Choir One",
                "",
                number=1,
            ),
            "uri": "spotify:album:current",
            "total_tracks": 53,
        }
        other = {
            **self.track(
                "Handel: Messiah, HWV 56",
                "George Frideric Handel, Choir Two",
                "",
                number=1,
            ),
            "uri": "spotify:album:other",
            "total_tracks": 51,
        }
        client = self.Client([current, other])

        results = client.alternate_classical_albums(
            "Messiah, HWV56",
            "Handel, George Frideric",
            require_vocal=True,
            exclude_uri="spotify:album:current",
        )

        self.assertEqual([item.uri for item in results], ["spotify:album:other"])

    def test_classical_album_alternates_exclude_single_track_excerpt_release(self):
        excerpt = {
            **self.track(
                "Handel: Messiah, HWV 56: Hallelujah",
                "George Frideric Handel, Choir",
                "",
                number=1,
            ),
            "uri": "spotify:album:hallelujah",
            "total_tracks": 1,
        }
        client = self.Client([excerpt])

        results = client.alternate_classical_albums(
            "Messiah, HWV 56",
            "Handel, George Frideric",
            require_vocal=True,
        )

        self.assertEqual(results, [])
        self.assertEqual(client.query["offset"], 40)


class SearchBatchTests(unittest.TestCase):
    def test_podcast_search_uses_explicit_fifty_item_pages(self):
        class PodcastSearchClient(SpotifyClient):
            def __init__(self):
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
                self.calls.append((method, path, query))
                offset = query["offset"]
                return {
                    "shows": {
                        "items": [
                            {
                                "id": f"show-{offset}",
                                "name": f"Show {offset}",
                                "type": "show",
                                "uri": f"spotify:show:{offset}",
                                "publisher": "Publisher",
                            }
                        ],
                        "total": 75,
                    }
                }

        client = PodcastSearchClient()

        first_page = client.search("query", "show")
        second_page = client.search("query", "show", 50)

        self.assertTrue(
            all(call[2]["limit"] == 10 for call in client.calls)
        )
        self.assertEqual(
            [call[2]["offset"] for call in client.calls],
            [0, 10, 20, 30, 40, 50, 60, 70, 80, 90],
        )
        self.assertEqual(first_page[-1].name, "Show more podcasts")
        self.assertEqual(first_page[-1].raw["next_offset"], 50)
        self.assertEqual(
            [item.id for item in second_page],
            ["show-50", "show-60", "show-70", "show-80", "show-90"],
        )

    def test_live_category_search_combines_two_ten_item_requests(self):
        client = SearchClient()

        results = client.search("query", "track")

        self.assertEqual(len(results), 20)
        self.assertEqual(
            [call[2]["offset"] for call in client.calls],
            [0, 10],
        )

    def test_artist_search_hides_artists_without_albums(self):
        class ArtistClient(SpotifyClient):
            def __init__(self):
                self.album_probes = []

            def _request(self, method, path, *, query=None, **kwargs):
                if path == "/search":
                    if query["offset"]:
                        return {}
                    return {
                        "artists": {
                            "items": [
                                {"id": "has", "name": "Has Albums"},
                                {"id": "none", "name": "Laverty"},
                                {"id": "broken", "name": "Unchecked"},
                            ],
                            "total": 3,
                        }
                    }
                artist_id = path.split("/")[2]
                self.album_probes.append((artist_id, query))
                if artist_id == "broken":
                    raise SpotifyError("boom", status=500)
                return {"items": [{"id": "album"}] if artist_id == "has" else []}

        client = ArtistClient()

        names = [item.name for item in client.search("x", "artist")]

        self.assertEqual(names, ["Has Albums", "Unchecked"])
        self.assertEqual(
            client.album_probes[0][1],
            {"include_groups": "album", "limit": 1},
        )
        client.search("x", "artist")
        self.assertEqual(len(client.album_probes), 3 + 1)

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

class FindAudiobookTests(unittest.TestCase):
    def client(self, items):
        return CommandClient([{"audiobooks": {"items": items}}])

    def book(self, book_id, name, author):
        return {
            "id": book_id,
            "name": name,
            "type": "audiobook",
            "authors": [{"name": author}],
            "uri": f"spotify:show:{book_id}",
        }

    def test_the_exact_title_by_the_right_author_wins(self):
        client = self.client(
            [
                self.book("a", "The Egg", "Someone Else"),
                self.book("b", "The Egg and Other Stories", "Andy Weir"),
                self.book("c", "the egg", "Andy Weir"),
            ]
        )

        found = client.find_audiobook("The Egg", "Andy Weir")

        self.assertEqual(found.id, "c")
        self.assertEqual(client.calls[0][2]["type"], "audiobook")

    def test_no_exact_title_means_not_found(self):
        client = self.client([self.book("b", "The Egg and Other Stories", "Andy Weir")])

        self.assertIsNone(client.find_audiobook("The Egg", "Andy Weir"))
