import unittest
from unittest.mock import patch

from blindspot.models import ItemKind, SpotifyItem, ViewState
from blindspot.navigation import NavigationHistory
from blindspot.ui import (
    SearchPanel,
    best_batch_track,
    parse_batch_song_list,
    space_belongs_to_control,
)


def track(item_id: str, title: str, artist: str) -> SpotifyItem:
    return SpotifyItem(
        item_id,
        ItemKind.TRACK,
        title,
        artist=artist,
        uri=f"spotify:track:{item_id}",
    )


class BatchSongListTests(unittest.TestCase):
    def test_parses_bullets_numbers_and_dash_variants(self):
        value = """* Troye Sivan - Party
2. Poppy – Time Will Tell
• Underscores — The Peace
Title without an artist
"""

        self.assertEqual(
            parse_batch_song_list(value),
            [
                ("Troye Sivan", "Party"),
                ("Poppy", "Time Will Tell"),
                ("Underscores", "The Peace"),
                ("", "Title without an artist"),
            ],
        )

    def test_ignores_blank_lines(self):
        self.assertEqual(parse_batch_song_list("\n * Artist - Song\n\n"), [
            ("Artist", "Song")
        ])


class BatchTrackMatchingTests(unittest.TestCase):
    def test_prefers_exact_artist_and_title_over_first_result(self):
        wrong = track("wrong", "Party", "Another Artist")
        right = track("right", "Party", "Troye Sivan")

        self.assertIs(
            best_batch_track("Troye Sivan", "Party", [wrong, right]),
            right,
        )

    def test_accepts_version_suffix_and_featured_artist(self):
        result = track(
            "match",
            "Time Will Tell - Single Version",
            "Poppy, Guest",
        )

        self.assertIs(
            best_batch_track("Poppy", "Time Will Tell", [result]),
            result,
        )

    def test_rejects_unrelated_results(self):
        result = track("wrong", "A Different Song", "Poppy")

        self.assertIsNone(
            best_batch_track("Poppy", "Time Will Tell", [result])
        )


class BatchSearchTests(unittest.TestCase):
    def test_space_is_reserved_for_the_batch_checklist(self):
        checklist_type = type("CheckListBox", (), {})

        with patch("blindspot.ui.wx.CheckListBox", checklist_type):
            self.assertTrue(space_belongs_to_control(checklist_type()))

    def test_parallel_search_results_keep_the_pasted_order(self):
        looked_up = []

        def search(_spotify, query, category):
            looked_up.append((query, category))
            artist, title = query.split(" ", 1)
            return [track(title, title, artist)]

        statuses = []
        panel = type(
            "Panel",
            (),
            {
                "frame": type(
                    "Frame",
                    (),
                    {"spotify": type("Spotify", (), {"search": search})()},
                )(),
                "status": type(
                    "Status",
                    (),
                    {"SetLabel": lambda self, value: statuses.append(value)},
                )(),
            },
        )()
        songs = [("A", "First"), ("B", "Second"), ("C", "Third")]

        with patch("blindspot.ui.wx.CallAfter", side_effect=lambda fn, *args: fn(*args)):
            results = SearchPanel.find_batch_matches(panel, songs)

        self.assertEqual([item.name for item in results], [
            "First", "Second", "Third"
        ])
        self.assertCountEqual(looked_up, [
            ("A First", "track"),
            ("B Second", "track"),
            ("C Third", "track"),
        ])
        self.assertEqual(statuses[-1], "Found 3 of 3 songs")

    def test_only_checked_matches_are_queued(self):
        first = track("first", "First", "A")
        second = track("second", "Second", "B")
        first.raw["batch_checked"] = True
        second.raw["batch_checked"] = True
        queued = []
        panel = type(
            "Panel",
            (),
            {
                "history": NavigationHistory(
                    ViewState("Review", [first, second], category="batch")
                ),
                "batch_results": type(
                    "Checks",
                    (),
                    {"GetCheckedItems": lambda self: (1,)},
                )(),
                "frame": type(
                    "Frame",
                    (),
                    {"queue_many": lambda self, items: queued.extend(items)},
                )(),
                "remember_batch_checks": lambda self: (
                    SearchPanel.remember_batch_checks(self)
                ),
            },
        )()

        SearchPanel.on_queue_batch_matches(panel)

        self.assertEqual(queued, [second])
        self.assertFalse(first.raw["batch_checked"])
        self.assertTrue(second.raw["batch_checked"])


if __name__ == "__main__":
    unittest.main()
