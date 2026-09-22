import unittest
from datetime import date
from unittest.mock import patch

from blindspot.numberones import (
    Page,
    NumberOnesClient,
    merge_runs,
    parse_page,
)
from blindspot.ukcharts import Run, UKChartError

DECADE_TABLES = """
<h3>1990</h3>
<table class="wikitable"><tr><th>Date</th><th>Artist</th><th>Single</th>
<th>Weeks at number one</th></tr>
<tr><td>6 January</td><td rowspan="3">The B-52's</td>
<td rowspan="3">"Love Shack"</td><td rowspan="3">8 weeks</td></tr>
<tr><td>13 January</td></tr><tr><td>20 January</td></tr>
<tr><td>27 January</td><td>Vanilla Ice</td><td>"Ice Ice Baby"</td><td>1 week</td></tr>
<tr><td>3 February</td><td>Summer break \u2013 no chart</td><td>Summer break</td><td>1</td></tr>
<tr><td>10 February</td><td rowspan="2">Madonna</td><td rowspan="2">"Vogue"</td>
<td rowspan="2">2 weeks</td></tr><tr><td>17 February</td></tr>
<tr><td>24 February</td><td>Madonna</td><td>"Vogue"</td><td>2 weeks</td></tr>
<tr><td>3 March</td><td>A</td><td>"X1"</td><td>1</td></tr>
<tr><td>10 March</td><td>A</td><td>"X2"</td><td>1</td></tr>
<tr><td>17 March</td><td>A</td><td>"X3"</td><td>1</td></tr>
<tr><td>24 March</td><td>A</td><td>"X4"</td><td>1</td></tr>
<tr><td>31 March</td><td>A</td><td>"X5"</td><td>1</td></tr>
</table>
<h3>Number-one artists</h3>
<table class="wikitable"><tr><th>Position</th><th>Artist</th><th>Weeks #1</th></tr>
<tr><td>1</td><td>Madonna</td><td>7</td></tr></table>
"""

YEAR_PAGE = """
<h2>Chart history</h2>
<table class="wikitable"><tr><th>Week beginning</th><th>Song</th><th>Artist</th></tr>
<tr><td>2 January</td><td rowspan="2">"The Prayer"</td><td rowspan="2">Anthony Callea</td></tr>
<tr><td>9 January</td></tr>
<tr><td>16 January</td><td>"Second"</td><td>Someone</td></tr>
<tr><td>23 January</td><td>"Third"</td><td>Other</td></tr>
<tr><td>30 January</td><td>"Fourth"</td><td>Another</td></tr>
<tr><td>6 February</td><td>"Fifth"</td><td>One More</td></tr>
<tr><td>13 February</td><td>"Sixth"</td><td>Six</td></tr>
<tr><td>20 February</td><td>"Seventh"</td><td>Seven</td></tr>
<tr><td>27 February</td><td>"Eighth"</td><td>Eight</td></tr>
<tr><td>6 March</td><td>"Ninth"</td><td>Nine</td></tr>
<tr><td>13 March</td><td>"Tenth"</td><td>Ten</td></tr>
</table>
"""

RUN_TABLE = """
<table class="wikitable"><tr><th>Artist</th><th>Title</th>
<th>Weeks at number-one</th><th>Reached number-one</th><th>Reference</th></tr>
<tr><td>Stan Walker</td><td>"Black Box"</td><td>10</td><td>7 December 2009</td><td></td></tr>
<tr><td>Timbaland</td><td>"If We Ever Meet Again"</td><td>4</td><td>15 February 2010</td><td></td></tr>
</table>
<table class="wikitable"><tr><th>Title</th><th>Artist</th><th>Reached number one</th><th>Weeks at number one</th></tr>
<tr><td>"Happy"</td><td>Pharrell</td><td>6 January 2014</td><td>15</td></tr></table>
"""


class PageShapeTests(unittest.TestCase):
    def test_weekly_decade_tables_take_the_year_from_their_heading(self):
        runs = parse_page(DECADE_TABLES)

        love_shack = runs[0]
        self.assertEqual(
            (love_shack.title, love_shack.artist, love_shack.first_week),
            ("Love Shack", "The B-52's", date(1990, 1, 6)),
        )
        self.assertEqual(love_shack.weeks, 3)
        self.assertEqual(love_shack.length, 8)  # the run began the year before

    def test_no_chart_weeks_are_skipped_and_split_rows_of_a_song_join_up(self):
        runs = parse_page(DECADE_TABLES)

        titles = [run.title for run in runs]
        self.assertNotIn("Summer break", titles)
        vogue = next(run for run in runs if run.title == "Vogue")
        self.assertEqual((vogue.first_week, vogue.weeks), (date(1990, 2, 10), 3))

    def test_summary_tables_are_not_mistaken_for_weeks(self):
        runs = parse_page(DECADE_TABLES)

        self.assertNotIn("Madonna", [run.title for run in runs])

    def test_year_pages_take_the_year_from_the_page(self):
        runs = parse_page(YEAR_PAGE, 2005)

        prayer = runs[0]
        self.assertEqual(
            (prayer.title, prayer.first_week, prayer.weeks, prayer.week_starts),
            ("The Prayer", date(2005, 1, 2), 2, True),
        )

    def test_run_per_row_tables_still_read_as_runs_not_weeks(self):
        runs = parse_page(RUN_TABLE)

        self.assertEqual(
            [(r.title, r.weeks, r.first_week) for r in runs],
            [
                ("Black Box", 10, date(2009, 12, 7)),
                ("If We Ever Meet Again", 4, date(2010, 2, 15)),
            ],
        )

    def test_a_page_with_nothing_readable_is_an_error(self):
        with self.assertRaises(UKChartError):
            parse_page("<p>nothing</p>")


class TotalTests(unittest.TestCase):
    def test_a_total_repeated_on_each_run_is_not_added_up(self):
        from blindspot.ukcharts import year_entries

        # "Brothers in Arms": four separate runs, each row saying 34 weeks.
        runs = [
            Run("Album", "Band", date(1985, 5, 27), 5, week_starts=True, total=34),
            Run("Album", "Band", date(1985, 7, 29), 11, week_starts=True, total=34),
            Run("Album", "Band", date(1985, 10, 28), 7, week_starts=True, total=34),
            Run("Album", "Band", date(1986, 2, 3), 11, week_starts=True, total=34),
        ]

        (entry,) = year_entries(runs, 1985)

        self.assertEqual(entry.total_weeks, 34)
        self.assertEqual(entry.weeks_in_year, 23)

    def test_runs_without_a_stated_total_are_added_up(self):
        from blindspot.ukcharts import year_entries

        runs = [
            Run("Song", "Band", date(2015, 1, 5), 7),
            Run("Song", "Band", date(2015, 6, 1), 2),
        ]

        (entry,) = year_entries(runs, 2015)

        self.assertEqual(entry.total_weeks, 9)


class DecadeEdgeTests(unittest.TestCase):
    def test_a_year_ending_in_nine_reads_the_next_decade_not_a_nonexistent_one(self):
        from blindspot.ukcharts import UKChartsClient

        asked = []
        uk = UKChartsClient()
        with patch.object(
            uk, "_page_html", side_effect=lambda title: asked.append(title) or RUN_TABLE
        ):
            uk.year("singles", 1989)
        client = NumberOnesClient()
        with patch.object(
            client._uk, "_page_html", side_effect=lambda title: asked.append(title) or DECADE_TABLES
        ):
            client.year("NZ", "singles", 1989)

        self.assertIn("List of UK singles chart number ones of the 1990s", asked)
        self.assertIn("List of number-one singles from the 1990s (New Zealand)", asked)
        self.assertFalse(any("1999s" in title or "1989s" in title for title in asked))


class MergeTests(unittest.TestCase):
    def test_a_run_split_over_two_pages_is_joined_with_its_full_length(self):
        first = Run("Song", "Artist", date(2005, 12, 18), 2, week_starts=True)
        second = Run("Song", "Artist", date(2006, 1, 1), 3, week_starts=True)

        (run,) = merge_runs([second, first])

        self.assertEqual((run.first_week, run.weeks, run.length), (date(2005, 12, 18), 5, 5))

    def test_a_run_dated_a_few_days_differently_on_two_pages_counts_once(self):
        from blindspot.ukcharts import year_entries

        one = Run("Come On Over", "Shania Twain", date(1999, 12, 11), 5)
        other = Run("Come On Over", "Shania Twain", date(1999, 12, 5), 5)

        merged = merge_runs([one, other])

        self.assertEqual(len(merged), 1)
        (entry,) = year_entries(merged, 1999)
        self.assertEqual(entry.weeks_in_year, 3)

    def test_the_same_run_on_two_pages_keeps_the_fuller_reading(self):
        short = Run("Black Box", "Stan Walker", date(2009, 12, 7), 4)
        full = Run("Black Box", "Stan Walker", date(2009, 12, 7), 10)

        (run,) = merge_runs([short, full])

        self.assertEqual(run.weeks, 10)


class ClientTests(unittest.TestCase):
    def client(self, pages):
        client = NumberOnesClient()
        asked = []

        def html(title):
            asked.append(title)
            return pages[title]

        patcher = patch.object(client._uk, "_page_html", side_effect=html)
        patcher.start()
        self.addCleanup(patcher.stop)
        return client, asked

    def test_australia_before_2000_reads_one_decade_page(self):
        client, asked = self.client(
            {"List of number-one singles in Australia during the 1990s": DECADE_TABLES}
        )

        entries = client.year("AU", "singles", 1990)

        self.assertEqual(
            asked, ["List of number-one singles in Australia during the 1990s"]
        )
        love_shack = next(e for e in entries if e.title == "Love Shack")
        self.assertEqual((love_shack.weeks_in_year, love_shack.total_weeks), (3, 8))

    def test_australia_from_2000_reads_the_year_and_its_neighbours(self):
        pages = {
            "List of number-one singles of 2005 (Australia)": YEAR_PAGE,
            "List of number-one singles of 2004 (Australia)": YEAR_PAGE.replace(
                "2 January", "5 December"
            ),
            "List of number-one singles of 2006 (Australia)": YEAR_PAGE,
        }
        client, asked = self.client(pages)

        client.year("AU", "singles", 2005)

        self.assertEqual(len(asked), 3)
        self.assertIn("List of number-one singles of 2004 (Australia)", asked)

    def test_new_zealand_albums_use_the_decade_page_named_for_them(self):
        client, asked = self.client(
            {"List of number 1 albums from the 1980s (New Zealand)": RUN_TABLE}
        )

        client.year("NZ", "albums", 1985)

        self.assertEqual(
            asked, ["List of number 1 albums from the 1980s (New Zealand)"]
        )

    def test_ranges_are_per_country_and_kind(self):
        client = NumberOnesClient()

        self.assertEqual(client.first_year("AU", "singles"), 1940)
        self.assertEqual(client.first_year("AU", "albums"), 1965)
        self.assertEqual(client.first_year("NZ", "singles"), 1980)
        with self.assertRaises(UKChartError) as caught:
            client.year("NZ", "singles", 1975)
        self.assertIn("New Zealand", str(caught.exception))
        self.assertIn("1980", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
