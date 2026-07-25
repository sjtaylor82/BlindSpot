import unittest

from blindspot.models import ItemKind, SpotifyItem, ViewState
from blindspot.navigation import NavigationHistory


class NavigationHistoryTests(unittest.TestCase):
    def test_back_restores_selected_leaf(self) -> None:
        results = ViewState(
            "Results",
            [
                SpotifyItem("a", ItemKind.ALBUM, "First"),
                SpotifyItem("b", ItemKind.ALBUM, "Second"),
            ],
        )
        history = NavigationHistory(results)
        history.remember_selection(1)
        history.push(
            ViewState(
                "Second",
                [SpotifyItem("t", ItemKind.TRACK, "A track")],
            )
        )

        restored = history.back()

        self.assertIs(restored, results)
        self.assertEqual(restored.selected, 1)

    def test_back_at_root_is_stable(self) -> None:
        root = ViewState("Search", [])
        history = NavigationHistory(root)

        self.assertIs(history.back(), root)
        self.assertFalse(history.can_go_back)


if __name__ == "__main__":
    unittest.main()
