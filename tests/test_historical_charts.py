import unittest
from datetime import date

from blindspot.historical_charts import (
    HistoricalChartError,
    HistoricalHot100Client,
)


class StubClient(HistoricalHot100Client):
    def __init__(self, responses):
        super().__init__()
        self.responses = responses
        self.urls = []

    def _request(self, url):
        self.urls.append(url)
        return self.responses[url.rsplit("/", 1)[-1]]


class HistoricalHot100Tests(unittest.TestCase):
    def test_requested_day_maps_to_latest_chart_date(self):
        client = StubClient(
            {
                "valid_dates.json": ["1979-12-29", "1980-01-05", "1980-01-12"],
                "1980-01-05.json": {
                    "date": "1980-01-05",
                    "data": [
                        {
                            "song": "Please Don't Go",
                            "artist": "KC And The Sunshine Band",
                            "this_week": 1,
                            "last_week": 3,
                            "peak_position": 1,
                            "weeks_on_chart": 20,
                        }
                    ],
                },
            }
        )

        chart = client.chart_for_date(date(1980, 1, 8))

        self.assertEqual(chart.chart_date, date(1980, 1, 5))
        self.assertEqual(chart.entries[0].name, "Please Don't Go")
        self.assertEqual(chart.entries[0].rank, 1)

    def test_date_before_archive_is_explained(self):
        client = StubClient({"valid_dates.json": ["1958-08-04"]})

        with self.assertRaisesRegex(HistoricalChartError, "begins"):
            client.chart_for_date(date(1950, 1, 1))

    def test_valid_dates_are_cached(self):
        client = StubClient(
            {
                "valid_dates.json": ["1980-01-05"],
                "1980-01-05.json": {"data": []},
            }
        )

        client.chart_for_date(date(1980, 1, 5))
        client.chart_for_date(date(1980, 1, 6))

        self.assertEqual(client.urls.count(client.urls[0]), 1)


if __name__ == "__main__":
    unittest.main()
