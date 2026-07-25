import unittest

from blindspot.models import ItemKind, SpotifyItem


class SpotifyItemTests(unittest.TestCase):
    def test_accessible_track_label_has_meaningful_order(self) -> None:
        item = SpotifyItem(
            id="1",
            kind=ItemKind.TRACK,
            name="Song",
            artist="Artist",
            album="Album",
            duration_ms=222_000,
            explicit=True,
        )

        self.assertEqual(
            item.accessible_label(),
            "Song — Artist — Album — 3 minutes 42 seconds — explicit",
        )

    def test_bookmark_position_is_in_accessible_label(self) -> None:
        item = SpotifyItem(
            id="track-id",
            kind=ItemKind.TRACK,
            name="Song",
            raw={"bookmark_position_label": "bookmarked at 2 minutes 5 seconds"},
        )

        self.assertEqual(
            item.accessible_label(),
            "Song — bookmarked at 2 minutes 5 seconds",
        )

    def test_show_total_is_announced_as_episodes(self) -> None:
        item = SpotifyItem(
            id="show-id",
            kind=ItemKind.SHOW,
            name="Podcast",
            total=12,
        )

        self.assertEqual(
            item.accessible_label(),
            "Podcast — 12 episodes",
        )

    def test_audiobook_total_and_chapter_resume_are_announced(self) -> None:
        audiobook = SpotifyItem(
            id="book-id",
            kind=ItemKind.AUDIOBOOK,
            name="Book",
            total=7,
        )
        chapter = SpotifyItem(
            id="chapter-id",
            kind=ItemKind.CHAPTER,
            name="Chapter One",
            raw={"resume_position_label": "resume at 2 minutes 5 seconds"},
        )

        self.assertEqual(audiobook.accessible_label(), "Book — 7 chapters")
        self.assertEqual(
            chapter.accessible_label(),
            "Chapter One — resume at 2 minutes 5 seconds",
        )
        self.assertTrue(chapter.playable)


if __name__ == "__main__":
    unittest.main()
