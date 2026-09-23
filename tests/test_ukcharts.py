import unittest
from datetime import date
from unittest.mock import patch

from unittest.mock import Mock

from blindspot import ui
from blindspot.ui import MainFrame
from blindspot.ukcharts import (
    UKChartError,
    Run,
    YearEntry,
    artist_candidates,
    UKChartsClient,
    order_entries,
    parse_runs,
    parse_weeks,
    run_for_date,
    weeks_text,
    year_entries,
)

ENDING_TABLE = """
<table class="wikitable"><tr><th>No.</th><th>nth single</th></tr>
<tr><td>re</td><td>Return</td></tr></table>
<table class="wikitable plainrowheaders">
<tr><th>No.</th><th>Artist</th><th>Single</th><th>Record label</th>
<th>Week ending date</th><th>Weeks at<br/>number one</th></tr>
<tr><th colspan="6">1989</th></tr>
<tr><th>1</th><td>Band Aid II</td><td>"Do They Know It's Christmas?"<sup>[1]</sup></td>
<td>PWL</td><td><span>23 December 1989</span></td>
<td>3<span style="display:none">3.0</span><sup>[a]</sup></td></tr>
<tr><th colspan="6">1990</th></tr>
<tr><th>2</th><td><a href="#">Hit</a> Maker</td><td>"Second Song"</td><td>EMI</td>
<td>20 January 1990</td><td>2</td></tr>
<tr><th>3</th><td>Someone Else</td><td>"Third Song"</td><td>EMI</td>
<td>3 February 1990</td><td>1</td></tr>
<tr><th>re</th><td>Hit Maker</td><td>"Second Song"</td><td>EMI</td>
<td>17 February 1990</td><td>2</td></tr>
</table>
"""

STARTING_TABLE = """
<table class="wikitable">
<tr><th>No.</th><th>Artist</th><th>Single</th><th>Record label</th>
<th>Week starting date</th><th>Weeks at number one</th></tr>
<tr><th>1</th><td>Al Martino</td><td>"Here in My Heart"</td><td>Capitol</td>
<td>14 November 1952</td><td>9</td></tr>
<tr><th>2</th><td>Half Weeks</td><td>"Shared"</td><td>X</td>
<td>16 January 1953</td><td>7½</td></tr>
</table>
"""

ALBUM_TABLE = """
<table class="wikitable">
<tr><th>No.</th><th>Artist</th><th>Album</th><th>Record label</th>
<th>Reached number one for the week ending</th><th>Weeks at number one</th>
<th>Certification</th></tr>
<tr><th>1</th><td>Rod Stewart</td><td>Greatest Hits, Vol. 1</td><td>Riva</td>
<td>8 December 1979</td><td>5</td><td>Platinum</td></tr>
</table>
"""


class ParsingTests(unittest.TestCase):
    def test_runs_are_read_with_marks_footnotes_and_hidden_text_removed(self):
        runs = parse_runs(ENDING_TABLE)

        self.assertEqual(
            [(r.title, r.artist, r.weeks, r.first_week) for r in runs],
            [
                ("Do They Know It's Christmas?", "Band Aid II", 3, date(1989, 12, 23)),
                ("Second Song", "Hit Maker", 2, date(1990, 1, 20)),
                ("Third Song", "Someone Else", 1, date(1990, 2, 3)),
                ("Second Song", "Hit Maker", 2, date(1990, 2, 17)),
            ],
        )
        self.assertFalse(runs[0].week_starts)

    def test_week_starting_and_half_weeks(self):
        runs = parse_runs(STARTING_TABLE)

        self.assertTrue(runs[0].week_starts)
        self.assertEqual(runs[1].weeks, 7.5)
        self.assertEqual(weeks_text(7.5), "7½")
        self.assertEqual(weeks_text(0.5), "½")
        self.assertEqual(weeks_text(3.0), "3")

    def test_album_tables_with_a_reached_number_one_column(self):
        (run,) = parse_runs(ALBUM_TABLE)

        self.assertEqual(
            (run.title, run.artist, run.first_week, run.weeks),
            ("Greatest Hits, Vol. 1", "Rod Stewart", date(1979, 12, 8), 5),
        )

    def test_a_page_without_a_chart_table_is_an_error(self):
        with self.assertRaises(UKChartError):
            parse_runs("<table class='wikitable'><tr><th>Nothing</th></tr></table>")

    def test_weeks_text_parsing(self):
        self.assertEqual(parse_weeks("12"), 12)
        self.assertEqual(parse_weeks("½"), 0.5)
        self.assertEqual(parse_weeks("4[a]"), 4)
        self.assertIsNone(parse_weeks("n/a"))


class YearTests(unittest.TestCase):
    def setUp(self):
        self.runs = parse_runs(ENDING_TABLE)

    def test_a_run_over_new_year_is_split_between_the_years(self):
        in_1989 = {e.title: e for e in year_entries(self.runs, 1989)}
        in_1990 = {e.title: e for e in year_entries(self.runs, 1990)}

        christmas = "Do They Know It's Christmas?"
        self.assertEqual(in_1989[christmas].weeks_in_year, 2)
        self.assertEqual(in_1990[christmas].weeks_in_year, 1)
        self.assertEqual(in_1990[christmas].total_weeks, 3)

    def test_a_song_that_returned_is_listed_once_with_its_runs_added(self):
        entries = year_entries(self.runs, 1990)
        titles = [e.title for e in entries]

        self.assertEqual(titles.count("Second Song"), 1)
        second = next(e for e in entries if e.title == "Second Song")
        self.assertEqual((second.weeks_in_year, second.total_weeks), (4, 4))
        self.assertEqual(second.first_week, date(1990, 1, 20))

    def test_ordering_by_date_or_by_weeks(self):
        entries = year_entries(self.runs, 1990)

        by_date = [e.title for e in order_entries(entries, False)]
        by_weeks = [e.title for e in order_entries(entries, True)]

        self.assertEqual(by_date[0], "Do They Know It's Christmas?")
        self.assertEqual(by_weeks[0], "Second Song")
        self.assertEqual(by_weeks[-1], "Third Song")


class DateTests(unittest.TestCase):
    def test_week_ending_dates_cover_the_seven_days_up_to_them(self):
        runs = parse_runs(ENDING_TABLE)

        self.assertEqual(run_for_date(runs, date(1990, 1, 20)).title, "Second Song")
        self.assertEqual(run_for_date(runs, date(1990, 1, 14)).title, "Second Song")
        self.assertEqual(run_for_date(runs, date(1990, 1, 27)).title, "Second Song")
        self.assertEqual(run_for_date(runs, date(1990, 1, 28)).title, "Third Song")
        self.assertIsNone(run_for_date(runs, date(1990, 3, 30)))

    def test_week_starting_dates_cover_the_seven_days_from_them(self):
        runs = parse_runs(STARTING_TABLE)

        self.assertEqual(run_for_date(runs, date(1952, 11, 14)).title, "Here in My Heart")
        self.assertEqual(run_for_date(runs, date(1952, 11, 20)).title, "Here in My Heart")
        self.assertIsNone(run_for_date(runs, date(1952, 11, 13)))


class ClientTests(unittest.TestCase):
    def test_pages_are_fetched_once_and_neighbouring_decades_are_joined(self):
        client = UKChartsClient()
        pages = []

        def fake_page(title):
            pages.append(title)
            return ENDING_TABLE

        with patch.object(client, "_page_html", side_effect=fake_page):
            entries = client.year("singles", 1990)
            client.year("singles", 1990)

        # 1990 borders the 1980s, so both decades are read, each only once.
        self.assertEqual(len(pages), 2)
        self.assertTrue(any("1980s" in title for title in pages))
        christmas = next(e for e in entries if e.title.startswith("Do They"))
        self.assertEqual(christmas.weeks_in_year, 1)

    def test_years_outside_the_lists_are_refused(self):
        client = UKChartsClient()

        with self.assertRaises(UKChartError):
            client.year("singles", 1940)
        with self.assertRaises(UKChartError):
            client.year("albums", 1955)
        with self.assertRaises(UKChartError):
            client.week("singles", date(2999, 1, 1))


class TitleTests(unittest.TestCase):
    def test_double_a_sides_lose_their_inner_quotes_and_are_tried_by_side(self):
        from blindspot.ukcharts import clean_title, title_candidates

        title = clean_title('"Day Tripper" / "We Can Work It Out"')

        self.assertEqual(title, "Day Tripper / We Can Work It Out")
        self.assertEqual(
            title_candidates(title),
            ["Day Tripper / We Can Work It Out", "Day Tripper", "We Can Work It Out"],
        )
        self.assertEqual(clean_title("\u201cFrankie\u201d\u2020"), "Frankie")
        self.assertEqual(title_candidates("Frankie"), ["Frankie"])


class ArtistCandidateTests(unittest.TestCase):
    def test_joint_credits_are_tried_whole_then_by_their_lead(self):
        self.assertEqual(
            artist_candidates("Elaine Paige and Barbara Dickson"),
            ["Elaine Paige and Barbara Dickson", "Elaine Paige"],
        )
        self.assertEqual(
            artist_candidates("Stormzy featuring Ed Sheeran"),
            ["Stormzy featuring Ed Sheeran", "Stormzy"],
        )
        self.assertEqual(artist_candidates("Madonna"), ["Madonna"])


class DiscoverRowTests(unittest.TestCase):
    def frame(self, charts):
        frame = Mock()
        frame.numberones = charts
        return frame

    def test_year_rows_say_weeks_that_year_and_in_total_once_per_song(self):
        charts = Mock()
        charts.year.return_value = [
            YearEntry("Relax", "Frankie Goes to Hollywood", 2, 5, date(1984, 12, 22)),
            YearEntry("Frankie", "Sister Sledge", 4, 4, date(1985, 6, 29)),
        ]
        frame = self.frame(charts)

        result = MainFrame.number_ones_results(
            frame, "GB", "singles", 1985, None, True
        )

        self.assertEqual(result.media_type, "number_ones")
        self.assertEqual(
            [row.raw["list_note"] for row in result.items],
            [
                "2 weeks at number one in 1985, 5 in total",
                "4 weeks at number one in 1985",
            ],
        )
        self.assertTrue(all(row.raw["unresolved"] for row in result.items))
        self.assertEqual(result.items[0].kind, ui.ItemKind.TRACK)
        self.assertIn("most weeks at number one first", result.detail)
        charts.year.assert_called_once_with("GB", "singles", 1985, by_weeks=True)
        self.assertIn("United Kingdom number one singles", result.detail)

    def test_a_date_gives_the_one_number_one_and_its_run(self):
        charts = Mock()
        charts.week.return_value = Run(
            "Frankie", "Sister Sledge", date(1985, 6, 29), 4
        )
        frame = self.frame(charts)

        result = MainFrame.number_ones_results(
            frame, "GB", "albums", None, date(1985, 7, 13), False
        )

        (row,) = result.items
        self.assertEqual(row.kind, ui.ItemKind.ALBUM)
        self.assertEqual(
            row.raw["list_note"], "4 weeks at number one from 29 June 1985"
        )
        self.assertIn("13 July 1985", result.detail)

    def test_a_week_with_no_number_one_gives_an_empty_list(self):
        charts = Mock()
        charts.week.return_value = None

        result = MainFrame.number_ones_results(
            self.frame(charts), "GB", "singles", None, date(1985, 7, 13), False
        )

        self.assertEqual(result.items, [])

    def test_half_weeks_are_shown_as_a_half(self):
        charts = Mock()
        charts.year.return_value = [
            YearEntry("Shared", "Someone", 7.5, 8.0, date(1953, 11, 13))
        ]

        result = MainFrame.number_ones_results(
            self.frame(charts), "GB", "singles", 1953, None, False
        )

        self.assertEqual(
            result.items[0].raw["list_note"],
            "7\u00bd weeks at number one in 1953, 8 in total",
        )


class SearchInputTests(unittest.TestCase):
    def panel(self, text):
        tasks = []
        panel = Mock()
        panel.chart_date.GetValue.return_value = text
        panel.release_media.return_value = "songs"
        panel.number_ones_order.GetSelection.return_value = 0
        panel.number_ones_country.GetSelection.return_value = 1
        panel.frame.run_task = lambda message, worker, success, **kw: tasks.append(worker)
        panel.tasks = tasks
        return panel

    def test_a_four_digit_entry_is_a_year_and_anything_else_a_date(self):
        year_panel = self.panel("1985")
        ui.NewMusicPanel.search_number_ones(year_panel)
        year_panel.tasks[0]()
        year_panel.frame.number_ones_results.assert_called_once_with(
            "AU", "singles", 1985, None, False
        )

        date_panel = self.panel("1985-07-13")
        ui.NewMusicPanel.search_number_ones(date_panel)
        date_panel.tasks[0]()
        date_panel.frame.number_ones_results.assert_called_once_with(
            "AU", "singles", None, date(1985, 7, 13), False
        )

    def test_an_unreadable_entry_is_reported_and_nothing_is_fetched(self):
        panel = self.panel("last week")

        ui.NewMusicPanel.search_number_ones(panel)

        self.assertEqual(panel.tasks, [])
        panel.frame.say.assert_called_once()
        self.assertFalse(panel.loading)


if __name__ == "__main__":
    unittest.main()


class DiscoverOrderTests(unittest.TestCase):
    """Choosing the UK chart must leave Songs/Albums after it, not before it."""

    @classmethod
    def setUpClass(cls):
        import wx
        from types import SimpleNamespace

        cls.wx = wx
        cls.app = wx.App(False)

        class Frame(wx.Frame):
            def __init__(self):
                super().__init__(None)
                self.spotify = SimpleNamespace(connected=True)

            def say(self, message):
                pass

        cls.frame = Frame()
        cls.panel = ui.NewMusicPanel(cls.frame, cls.frame)

    @classmethod
    def tearDownClass(cls):
        cls.frame.Destroy()

    def order(self):
        names = {
            id(getattr(self.panel, name)): name
            for name in (
                "discovery_source", "history_chart", "number_ones_country",
                "triple_j_countdown", "classic_100_countdown",
                "rn_books_countdown",
                "release_types", "number_ones_order",
                "genre", "release_window", "keyword", "chart_country",
                "chart_date", "search_button",
            )
        }
        windows = [
            item.GetWindow()
            for item in self.panel.GetSizer().GetChildren()
            if item.GetWindow() is not None
        ]
        return [
            names[id(window)]
            for window in windows
            if id(window) in names and window.IsEnabled()
        ]

    def test_uk_choice_reaches_show_and_order_after_the_chart_choice(self):
        self.panel.discovery_source.SetSelection(3)  # Charts
        self.panel.history_chart.SetSelection(1)  # UK number ones
        self.panel.update_source_controls()

        self.assertEqual(
            self.order(),
            [
                "discovery_source",
                "history_chart",
                "number_ones_country",
                "release_types",
                "number_ones_order",
                "chart_date",
                "search_button",
            ],
        )

    def test_the_us_hot_100_needs_neither_show_nor_order(self):
        self.panel.discovery_source.SetSelection(3)
        self.panel.history_chart.SetSelection(0)
        self.panel.update_source_controls()

        self.assertEqual(
            self.order(),
            ["discovery_source", "history_chart", "chart_date", "search_button"],
        )

    def test_triple_j_chart_offers_only_the_countdown(self):
        self.panel.discovery_source.SetSelection(3)
        self.panel.history_chart.SetSelection(2)
        self.panel.update_source_controls()

        self.assertEqual(
            self.order(),
            [
                "discovery_source",
                "history_chart",
                "triple_j_countdown",
                "search_button",
            ],
        )

    def test_classic_100_chart_offers_only_the_countdown(self):
        self.panel.discovery_source.SetSelection(3)
        self.panel.history_chart.SetSelection(3)
        self.panel.update_source_controls()

        self.assertEqual(
            self.order(),
            [
                "discovery_source",
                "history_chart",
                "classic_100_countdown",
                "search_button",
            ],
        )

    def test_radio_national_chart_offers_only_the_countdown(self):
        self.panel.discovery_source.SetSelection(3)
        self.panel.history_chart.SetSelection(4)
        self.panel.update_source_controls()

        self.assertEqual(
            self.order(),
            [
                "discovery_source",
                "history_chart",
                "rn_books_countdown",
                "search_button",
            ],
        )
