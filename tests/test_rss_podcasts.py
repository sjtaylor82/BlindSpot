from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from blindspot.models import ItemKind
from blindspot.portable import PortableStore
from blindspot.rss_podcasts import (
    RSSSubscription,
    RSSSubscriptionStore,
    feed_episodes,
    parse_opml,
    subscription_item,
)


class OPMLImportTests(unittest.TestCase):
    def test_nested_outlines_are_imported_and_duplicate_urls_are_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "podcasts.opml"
            path.write_text(
                """<?xml version="1.0"?><opml version="2.0"><body>
                <outline text="News">
                  <outline text="Example" xmlUrl="https://example.com/feed/" />
                  <outline title="Duplicate" xmlUrl="https://example.com/feed" />
                </outline></body></opml>""",
                encoding="utf-8",
            )

            values = parse_opml(path)

        self.assertEqual(
            values,
            [RSSSubscription("Example", "https://example.com/feed/")],
        )

    def test_import_is_portable_and_reports_only_new_feeds(self):
        with tempfile.TemporaryDirectory() as folder:
            store = RSSSubscriptionStore(PortableStore(Path(folder)))
            path = Path(folder) / "podcasts.opml"
            path.write_text(
                """<opml><body><outline text="Example"
                xmlUrl="https://example.com/feed" /></body></opml>""",
                encoding="utf-8",
            )

            self.assertEqual(store.import_file(path), (1, 1))
            self.assertEqual(store.import_file(path), (0, 1))
            self.assertTrue((Path(folder) / "podcast_subscriptions.json").is_file())


class RSSFeedTests(unittest.TestCase):
    def test_feed_episode_keeps_direct_audio_and_publisher_transcript(self):
        show = subscription_item(
            RSSSubscription("Example", "https://example.com/feed")
        )
        payload = b"""<rss xmlns:podcast="https://podcastindex.org/namespace/1.0">
          <channel><title>Example Show</title><item>
            <title>Episode One</title><guid>one</guid>
            <description>&lt;p&gt;Episode description.&lt;/p&gt;</description>
            <enclosure url="https://cdn.example.com/one.mp3" type="audio/mpeg" />
            <podcast:transcript url="https://cdn.example.com/one.vtt"
              type="text/vtt" rel="captions" />
            <itunes:duration xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">1:02</itunes:duration>
          </item></channel></rss>"""

        with patch("blindspot.rss_podcasts._read_feed", return_value=payload):
            episodes = feed_episodes(show)

        self.assertEqual(len(episodes), 1)
        episode = episodes[0]
        self.assertEqual(episode.kind, ItemKind.EPISODE)
        self.assertEqual(episode.duration_ms, 62_000)
        self.assertEqual(episode.raw["audio_url"], "https://cdn.example.com/one.mp3")
        self.assertEqual(
            episode.raw["transcript_url"], "https://cdn.example.com/one.vtt"
        )
        self.assertEqual(episode.raw["description"], "Episode description.")


if __name__ == "__main__":
    unittest.main()
