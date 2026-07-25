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


if __name__ == "__main__":
    unittest.main()
