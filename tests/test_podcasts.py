import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from blindspot.models import ItemKind, SpotifyItem
from blindspot.podcasts import (
    PodcastDownload,
    PodcastDownloadUnavailable,
    _normalise,
    _similarity,
    download_episode,
    find_episode_download,
)


class PodcastDownloadTests(unittest.TestCase):
    def test_non_latin_titles_remain_distinct(self):
        self.assertEqual(_normalise("你好，世界"), "你好 世界")
        self.assertLess(_similarity("你好，世界", "再见，月亮"), 0.55)
        self.assertEqual(_similarity("", ""), 0.0)

    def test_finds_matching_episode_enclosure(self):
        directory = json.dumps(
            {
                "results": [
                    {
                        "collectionName": "Example Show",
                        "artistName": "Example Publisher",
                        "feedUrl": "https://example.com/feed.xml",
                    }
                ]
            }
        ).encode()
        feed = b"""<?xml version="1.0"?>
        <rss><channel><item>
        <title>The Episode We Want</title>
        <enclosure url="https://cdn.example.com/wanted.m4a"
                   type="audio/mp4" length="12"/>
        </item></channel></rss>"""
        item = SpotifyItem(
            "episode",
            ItemKind.EPISODE,
            "The Episode We Want",
            artist="Example Publisher",
            album="Example Show",
        )

        with patch(
            "blindspot.podcasts._read_url",
            side_effect=(directory, feed),
        ):
            result = find_episode_download(item)

        self.assertEqual(result.url, "https://cdn.example.com/wanted.m4a")
        self.assertEqual(result.filename, "The Episode We Want.m4a")

    def test_rejects_unmatched_episode(self):
        directory = json.dumps(
            {
                "results": [
                    {
                        "collectionName": "Example Show",
                        "artistName": "Publisher",
                        "feedUrl": "https://example.com/feed.xml",
                    }
                ]
            }
        ).encode()
        feed = b"""<rss><channel><item><title>Something Else</title>
        <enclosure url="https://example.com/else.mp3"/>
        </item></channel></rss>"""
        item = SpotifyItem(
            "episode",
            ItemKind.EPISODE,
            "Wanted Episode",
            artist="Publisher",
            album="Example Show",
        )

        with patch(
            "blindspot.podcasts._read_url",
            side_effect=(directory, feed),
        ):
            with self.assertRaises(PodcastDownloadUnavailable):
                find_episode_download(item)

    def test_download_writes_media_to_selected_destination(self):
        download = PodcastDownload(
            "https://example.com/episode.mp3",
            "Episode.mp3",
        )
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.side_effect = (b"audio", b"")
        response.__exit__.return_value = False
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "Episode.mp3"
            with patch("urllib.request.urlopen", return_value=response):
                download_episode(download, destination)
            self.assertEqual(destination.read_bytes(), b"audio")
            self.assertFalse((Path(folder) / "Episode.mp3.part").exists())


if __name__ == "__main__":
    unittest.main()
