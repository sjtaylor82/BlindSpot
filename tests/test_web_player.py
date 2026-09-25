import urllib.request
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from blindspot.web_player import PlayerPageServer, WebPlaybackController


class PlayerPageServerTests(unittest.TestCase):
    def test_local_server_hosts_sdk_bridge_without_tokens(self):
        server = PlayerPageServer()
        server.start()
        try:
            with urllib.request.urlopen(server.url, timeout=2) as response:
                html = response.read().decode("utf-8")
        finally:
            server.close()

        self.assertIn("https://sdk.scdn.co/spotify-player.js", html)
        self.assertIn("window.blindSpotProvideToken", html)
        self.assertIn("window.blindSpotAdjustVolume", html)
        self.assertIn("window.blindSpotSetVolume", html)
        self.assertIn("window.blindSpotToggleMute", html)
        self.assertIn("window.blindSpotPause", html)
        self.assertIn("window.blindSpotPreviousTrack", html)
        self.assertIn("window.blindSpotNextTrack", html)
        self.assertIn("window.blindSpotPlayDirect", html)
        self.assertIn("const directAudio = new Audio()", html)
        self.assertIn('directActive && eventName === "playback_error"', html)
        self.assertIn("player.getCurrentState().then(state =>", html)
        self.assertIn("directAudio.currentTime", html)
        self.assertIn("player.getVolume()", html)
        self.assertIn("player.setVolume(target)", html)
        self.assertIn('"playback_update"', html)
        self.assertIn("state.track_window.current_track", html)
        self.assertIn("state.context.uri", html)
        self.assertIn("window.blindspot.postMessage", html)
        self.assertNotIn("access_token", html)

    def test_local_media_supports_byte_range_seeking(self):
        server = PlayerPageServer()
        server.start()
        try:
            with TemporaryDirectory() as folder:
                path = Path(folder) / "episode.media"
                path.write_bytes(b"0123456789")
                url = server.media_url("episode:1", path)
                request = urllib.request.Request(
                    url, headers={"Range": "bytes=3-6"}
                )
                with urllib.request.urlopen(request, timeout=2) as response:
                    self.assertEqual(response.status, 206)
                    self.assertEqual(response.headers["Content-Range"], "bytes 3-6/10")
                    self.assertEqual(response.read(), b"3456")
        finally:
            server.close()

    def test_ready_player_restores_initial_volume(self):
        scripts = []
        ready = []
        controller = WebPlaybackController.__new__(WebPlaybackController)
        controller.device_id = None
        controller.initial_volume_percent = 67
        controller.on_ready = ready.append
        controller._run_script = scripts.append
        event = type(
            "Event",
            (),
            {"GetString": lambda self: '{"type":"ready","device_id":"local"}'},
        )()

        controller._on_message(event)

        self.assertEqual(controller.device_id, "local")
        self.assertEqual(scripts, ["window.blindSpotSetVolume(67);"])
        self.assertEqual(ready, ["local"])

    def test_direct_audio_command_serializes_url_item_and_position(self):
        scripts = []
        controller = WebPlaybackController.__new__(WebPlaybackController)
        controller.page_ready = True
        controller._run_script = scripts.append

        controller.play_direct(
            "https://example.com/episode.mp3",
            {"id": "rss:episode:1", "name": "Episode"},
            12_500,
        )

        self.assertEqual(len(scripts), 1)
        self.assertIn("blindSpotPlayDirect", scripts[0])
        self.assertIn("episode.mp3", scripts[0])
        self.assertIn("12500", scripts[0])

    def test_page_ready_does_not_request_token_when_spotify_is_disconnected(self):
        controller = WebPlaybackController.__new__(WebPlaybackController)
        controller.spotify = type("Spotify", (), {"connected": False})()
        controller.page_ready = False
        controller.pending_direct = None
        controller.provide_token = Mock()
        event = type(
            "Event",
            (),
            {"GetString": lambda self: '{"type":"page_ready"}'},
        )()

        controller._on_message(event)

        self.assertTrue(controller.page_ready)
        controller.provide_token.assert_not_called()


if __name__ == "__main__":
    unittest.main()
