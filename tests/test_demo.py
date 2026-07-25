import unittest

from blindspot.demo import DemoSpotifyClient
from blindspot.models import ItemKind


class DemoSpotifyClientTests(unittest.TestCase):
    def test_demo_track_resolves_to_its_album(self):
        client = DemoSpotifyClient()

        album = client.album_for_track(client.tracks[0])

        self.assertEqual(album.name, client.tracks[0].album)

    def test_category_search_returns_twenty_results(self):
        client = DemoSpotifyClient()

        results = client.search("demo", "track")

        self.assertEqual(len(results), 20)
        self.assertTrue(all(item.kind == ItemKind.TRACK for item in results))

    def test_real_world_query_still_returns_demo_results(self):
        client = DemoSpotifyClient()

        results = client.search("an artist not present in fixtures", "album")

        self.assertEqual(len(results), 20)
        self.assertTrue(all(item.kind == ItemKind.ALBUM for item in results))

    def test_demo_album_drills_into_tracks(self):
        client = DemoSpotifyClient()

        tracks = client.children(client.albums[0])

        self.assertEqual(len(tracks), 12)
        self.assertTrue(all(item.kind == ItemKind.TRACK for item in tracks))

    def test_demo_playback_commands_change_state(self):
        client = DemoSpotifyClient()
        track = client.tracks[5]

        client.play(track, "demo-device")
        client.seek_relative(5_000, "demo-device")
        volume = client.adjust_volume(-5, "demo-device")

        self.assertIs(client.current, track)
        self.assertTrue(client.is_playing)
        self.assertEqual(client.progress_ms, 5_000)
        self.assertEqual(volume, 75)

    def test_demo_queue_contains_only_explicit_additions(self):
        client = DemoSpotifyClient()

        self.assertEqual(client.queue(), [])
        client.add_to_queue(client.tracks[16])

        self.assertEqual(client.queue(), [client.tracks[16]])

    def test_demo_adds_selected_track_to_playlist(self):
        client = DemoSpotifyClient()
        playlist = client.user_playlists()[0]
        track = client.tracks[3]

        client.add_to_playlist(playlist, track)

        self.assertIs(client.playlist_items[playlist.id][-1], track)

    def test_demo_shuffle_repeat_and_up_next(self):
        client = DemoSpotifyClient()
        client.add_to_queue(client.tracks[8])

        self.assertIs(client.next_queued(), client.tracks[8])
        self.assertTrue(client.toggle_shuffle("demo-device"))
        self.assertEqual(client.cycle_repeat("demo-device"), "context")
        self.assertEqual(client.cycle_repeat("demo-device"), "track")

    def test_demo_playlist_create_and_remove(self):
        client = DemoSpotifyClient()
        playlist = client.create_playlist("Quiet test playlist")
        track = client.tracks[4]
        client.add_to_playlist(playlist, track)

        client.remove_from_playlist(playlist, track)

        self.assertEqual(playlist.name, "Quiet test playlist")
        self.assertEqual(client.playlist_items[playlist.id], [])


if __name__ == "__main__":
    unittest.main()
