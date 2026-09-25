from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from blindspot.models import ItemKind, SpotifyItem
from blindspot.portable import PortableStore
from blindspot.transcripts import (
    EpisodeMedia,
    Transcript,
    TranscriptCache,
    TranscriptLine,
    _episode_media_from_feed,
    parse_transcript,
)


class TranscriptParsingTests(unittest.TestCase):
    def test_parses_webvtt_timestamps(self):
        transcript = parse_transcript(
            b"WEBVTT\n\n00:01.250 --> 00:03.000\nHello there.\n\n"
            b"00:03.500 --> 00:05.000\nGeneral Kenobi.\n",
            "text/vtt",
        )

        self.assertEqual(
            transcript.lines,
            (
                TranscriptLine(1250, "Hello there."),
                TranscriptLine(3500, "General Kenobi."),
            ),
        )

    def test_parses_podcasting_json(self):
        transcript = parse_transcript(
            b'{"segments":[{"startTime":1.5,"body":"Hello"}]}',
            "application/json",
        )

        self.assertEqual(transcript.lines, (TranscriptLine(1500, "Hello"),))

    def test_finds_transcript_and_audio_on_matching_feed_item(self):
        feed = b"""<?xml version="1.0"?>
        <rss xmlns:podcast="https://podcastindex.org/namespace/1.0">
          <channel><item><title>The exact episode</title>
            <enclosure url="https://example.com/audio.mp3" />
            <podcast:transcript url="https://example.com/transcript.vtt"
              type="text/vtt" rel="captions" />
          </item></channel>
        </rss>"""
        with patch("blindspot.transcripts._read_url", return_value=feed):
            media = _episode_media_from_feed(
                "https://example.com/feed", "The exact episode"
            )

        self.assertEqual(
            media,
            EpisodeMedia(
                "https://example.com/audio.mp3",
                "https://example.com/transcript.vtt",
                "text/vtt",
            ),
        )


class TranscriptCacheTests(unittest.TestCase):
    def test_audio_cache_path_is_episode_specific_and_outside_json_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            store = PortableStore(Path(folder))
            cache = TranscriptCache(store)

            path = cache.audio_path("spotify:episode/unsafe")

            self.assertEqual(path.parent, store.root / "transcript-audio")
            self.assertEqual(path.name, "spotify_episode_unsafe.media")

    def test_cache_lives_under_portable_store_and_preserves_partial_state(self):
        with tempfile.TemporaryDirectory() as folder:
            store = PortableStore(Path(folder))
            cache = TranscriptCache(store)
            transcript = Transcript(
                (TranscriptLine(1000, "First words"),),
                "whisper",
                False,
            )

            cache.write("spotify:episode/unsafe", transcript)

            self.assertEqual(cache.read("spotify:episode/unsafe"), transcript)
            self.assertEqual(cache.path("spotify:episode/unsafe").parent, store.root / "transcripts")

    def test_legacy_whisper_cache_is_marked_for_timing_regeneration(self):
        with tempfile.TemporaryDirectory() as folder:
            store = PortableStore(Path(folder))
            cache = TranscriptCache(store)
            cache.path("episode").write_text(
                '{"source":"whisper","complete":true,'
                '"lines":[{"start_ms":0,"text":"A long segment"}]}',
                encoding="utf-8",
            )

            transcript = cache.read("episode")

            self.assertIsNotNone(transcript)
            self.assertFalse(transcript.complete)

    def test_new_whisper_cache_preserves_precise_timing_version(self):
        with tempfile.TemporaryDirectory() as folder:
            store = PortableStore(Path(folder))
            cache = TranscriptCache(store)
            transcript = Transcript(
                (TranscriptLine(2500, "Precisely timed words"),),
                "whisper",
                True,
            )

            cache.write("episode", transcript)

            self.assertEqual(cache.read("episode"), transcript)

    def test_translation_cache_requires_matching_source_and_language(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = TranscriptCache(PortableStore(Path(folder)))
            transcript = Transcript(
                (TranscriptLine(0, "Hello"), TranscriptLine(1000, "World")),
                "publisher",
            )

            translated = cache.write_translation(
                "episode", transcript, "DE", "Hallo\nWelt"
            )

            self.assertEqual(translated.translated_text, "Hallo\nWelt")
            self.assertEqual(
                cache.read_translation("episode", transcript, "DE"),
                translated,
            )
            self.assertEqual(
                cache.read_translation("episode", transcript, "FR"),
                transcript,
            )
            changed = Transcript((TranscriptLine(0, "Changed"),), "publisher")
            self.assertEqual(
                cache.read_translation("episode", changed, "DE"),
                changed,
            )


if __name__ == "__main__":
    unittest.main()
