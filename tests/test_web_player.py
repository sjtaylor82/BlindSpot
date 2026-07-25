import urllib.request
import unittest

from blindspot.web_player import PlayerPageServer


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
        self.assertIn("window.blindSpotToggleMute", html)
        self.assertIn("window.blindSpotPreviousTrack", html)
        self.assertIn("window.blindSpotNextTrack", html)
        self.assertIn("player.getVolume()", html)
        self.assertIn("player.setVolume(target)", html)
        self.assertIn('"playback_update"', html)
        self.assertIn("state.track_window.current_track", html)
        self.assertIn("state.context.uri", html)
        self.assertIn("window.blindspot.postMessage", html)
        self.assertNotIn("access_token", html)


if __name__ == "__main__":
    unittest.main()
