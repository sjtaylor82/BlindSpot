import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from blindspot.lyrics import LRCLibClient, LyricsUnavailable
from blindspot.models import ItemKind, SpotifyItem


class FakeResponse:
    def __init__(self, value):
        self.body = json.dumps(value).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self.body


class LRCLibClientTests(unittest.TestCase):
    def setUp(self):
        self.item = SpotifyItem(
            id="spotify-track",
            kind=ItemKind.TRACK,
            name="Example Song",
            artist="Example Artist",
            album="Example Album",
            duration_ms=183_000,
        )

    @patch("blindspot.lyrics.urllib.request.urlopen")
    def test_exact_match_returns_plain_lyrics(self, urlopen):
        urlopen.return_value = FakeResponse(
            {
                "trackName": "Example Song",
                "artistName": "Example Artist",
                "plainLyrics": "First line\nSecond line",
                "syncedLyrics": "[00:01.00] First line",
            }
        )

        lyrics = LRCLibClient().lyrics_for(self.item)

        self.assertEqual(lyrics.text, "First line\nSecond line")
        self.assertTrue(lyrics.synced)
        self.assertEqual(lyrics.synced_lines, [(1_000, "First line")])
        self.assertEqual(lyrics.track_id, "spotify-track")
        request = urlopen.call_args.args[0]
        self.assertIn("duration=183", request.full_url)
        self.assertIn("BlindSpot/", request.get_header("User-agent"))

    @patch("blindspot.lyrics.urllib.request.urlopen")
    def test_search_fallback_removes_timestamps(self, urlopen):
        not_found = urllib.error.HTTPError(
            "https://lrclib.net/api/get",
            404,
            "Not Found",
            {},
            io.BytesIO(),
        )
        urlopen.side_effect = [
            not_found,
            FakeResponse(
                [
                    {
                        "trackName": "Example Song",
                        "artistName": "Example Artist",
                        "albumName": "Another Edition",
                        "duration": 184,
                        "plainLyrics": None,
                        "syncedLyrics": (
                            "[00:01.00] First line\n"
                            "[00:04.50] Second line"
                        ),
                    }
                ]
            ),
        ]

        lyrics = LRCLibClient().lyrics_for(self.item)

        self.assertEqual(lyrics.text, "First line\nSecond line")
        self.assertEqual(
            lyrics.synced_lines,
            [(1_000, "First line"), (4_500, "Second line")],
        )
        self.assertEqual(urlopen.call_count, 2)

    @patch("blindspot.lyrics.urllib.request.urlopen")
    def test_no_matching_search_result_is_unavailable(self, urlopen):
        not_found = urllib.error.HTTPError(
            "https://lrclib.net/api/get",
            404,
            "Not Found",
            {},
            io.BytesIO(),
        )
        urlopen.side_effect = [not_found, FakeResponse([])]

        with self.assertRaisesRegex(LyricsUnavailable, "Example Song"):
            LRCLibClient().lyrics_for(self.item)

    @patch("blindspot.lyrics.urllib.request.urlopen")
    def test_instrumental_uses_synced_commercial_match_within_ten_seconds(
        self,
        urlopen,
    ):
        self.item.name = (
            "Example Song (Karaoke Version) "
            "[Originally Performed By Example Artist]"
        )
        urlopen.side_effect = [
            FakeResponse({"instrumental": True}),
            FakeResponse(
                [
                    {
                        "trackName": "Example Song",
                        "artistName": "Example Artist",
                        "duration": 192,
                        "syncedLyrics": "[00:01.00] First line",
                    },
                    {
                        "trackName": "Example Song",
                        "artistName": "Example Artist",
                        "duration": 194,
                        "syncedLyrics": "[00:01.00] Too long",
                    },
                ]
            ),
        ]

        lyrics = LRCLibClient().lyrics_for(self.item)

        self.assertTrue(lyrics.substitute)
        self.assertEqual(lyrics.track_name, "Example Song")
        self.assertEqual(lyrics.synced_lines, [(1_000, "First line")])
        self.assertIn("track_name=Example+Song", urlopen.call_args.args[0].full_url)


if __name__ == "__main__":
    unittest.main()
