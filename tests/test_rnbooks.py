import unittest
from unittest.mock import Mock

from blindspot import ui
from blindspot.models import ItemKind
from blindspot.rnbooks import (
    BookCountdown,
    BookEntry,
    RNBooksClient,
    RNBooksError,
    parse_next_100,
    parse_top_100,
)


class ParserTests(unittest.TestCase):
    def test_top_100_parses_hero_and_ranked_cards(self):
        markup = """
        <h3 class="SongCountdownHero_title__abc">Boy Swallows Universe</h3>
        <div class="SongCountdownHero_artist__def">Trent Dalton</div>
        <div class="SongCard_position__x">2</div>
        <div class="SongCard_title__y">The Book Thief</div>
        <div data-testid="song-card-artist">Markus Zusak</div>
        """
        entries = parse_top_100(markup)
        self.assertEqual(
            [(entry.rank, entry.title, entry.author) for entry in entries],
            [
                (1, "Boy Swallows Universe", "Trent Dalton"),
                (2, "The Book Thief", "Markus Zusak"),
            ],
        )

    def test_next_100_parses_official_paragraph(self):
        markup = (
            "<h3>The Ones That Got Away</h3><p>"
            "101. Juice — Tim Winton<br/>"
            "102. Klara and the Sun — Kazuo Ishiguro</p>"
        )
        entries = parse_next_100(markup)
        self.assertEqual(
            [(entry.rank, entry.title, entry.author) for entry in entries],
            [(101, "Juice", "Tim Winton"), (102, "Klara and the Sun", "Kazuo Ishiguro")],
        )

    def test_client_combines_both_lists_and_requires_every_rank(self):
        client = RNBooksClient()
        client._top_html = (
            '<h3 class="SongCountdownHero_title__a">Book 1</h3>'
            '<div class="SongCountdownHero_artist__b">Author 1</div>'
            + "".join(
                f'<div class="SongCard_position__x">{rank}</div>'
                f'<div class="SongCard_title__y">Book {rank}</div>'
                f'<div data-testid="song-card-artist">Author {rank}</div>'
                for rank in range(2, 101)
            )
        )
        client._next_html = "<p>" + "<br/>".join(
            f"{rank}. Book {rank} — Author {rank}" for rank in range(101, 201)
        ) + "</p>"

        entries = client.countdown(BookCountdown(2025, 1, 200, "All"))

        self.assertEqual(len(entries), 200)
        self.assertEqual((entries[0].rank, entries[-1].rank), (1, 200))

    def test_client_rejects_partial_page(self):
        client = RNBooksClient()
        client._next_html = "<p>101. Juice — Tim Winton</p>"
        with self.assertRaises(RNBooksError):
            client.countdown(BookCountdown(2025, 101, 200, "Next"))


class RadioNationalWorkflowTests(unittest.TestCase):
    def panel(self, selection):
        panel = Mock()
        panel.loading = False
        panel.source.return_value = "historical"
        panel.history_chart.GetSelection.return_value = 4
        panel.rn_books_countdown.GetSelection.return_value = selection
        panel.frame.run_task = Mock()
        return panel

    def test_search_requires_an_explicit_countdown(self):
        panel = self.panel(0)

        ui.NewMusicPanel.on_search(panel)

        panel.frame.run_task.assert_not_called()
        panel.rn_books_countdown.SetFocus.assert_called_once()
        self.assertFalse(panel.loading)

    def test_selected_countdown_accounts_for_prompt_row(self):
        panel = self.panel(1)

        ui.NewMusicPanel.on_search(panel)

        worker = panel.frame.run_task.call_args.args[1]
        worker()
        panel.frame.rn_book_results.assert_called_once_with(
            ui.RN_BOOK_COUNTDOWNS[0]
        )

    def test_results_are_lazy_audiobook_rows(self):
        frame = Mock()
        frame.rn_books.countdown.return_value = [
            BookEntry("A Book", "An Author", 101)
        ]

        result = ui.MainFrame.rn_book_results(
            frame, BookCountdown(2025, 101, 200, "Next")
        )

        self.assertEqual(result.media_type, "rn_books")
        self.assertEqual(result.items[0].kind, ItemKind.AUDIOBOOK)
        self.assertTrue(result.items[0].raw["unresolved"])
        self.assertEqual(result.items[0].raw["chart_url"], ui.RN_BOOKS_NEXT_URL)


if __name__ == "__main__":
    unittest.main()
