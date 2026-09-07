import json
import unittest
import urllib.parse
from unittest.mock import patch

from blindspot.ticketmaster import (
    ConcertEvent,
    TICKETMASTER_COUNTRIES,
    TicketmasterClient,
)


class StubResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self.payload


class TicketmasterTests(unittest.TestCase):
    @patch("blindspot.ticketmaster.urllib.request.urlopen")
    def test_classifications_return_categories_with_stable_genre_ids(
        self, urlopen
    ):
        urlopen.return_value = StubResponse(
            {
                "_embedded": {
                    "classifications": [
                        {
                            "segment": {
                                "id": "music-id",
                                "name": "Music",
                                "_embedded": {
                                    "genres": [
                                        {"id": "rock-id", "name": "Rock"},
                                        {"id": "jazz-id", "name": "Jazz"},
                                    ]
                                },
                            }
                        }
                    ]
                }
            }
        )

        categories = TicketmasterClient("key").classifications()

        self.assertEqual(categories[0].name, "Music")
        self.assertEqual(
            categories[0].genres,
            [("jazz-id", "Jazz"), ("rock-id", "Rock")],
        )

    def test_country_choices_use_ticketmaster_codes(self):
        countries = dict(TICKETMASTER_COUNTRIES)

        self.assertEqual(countries["AU"], "Australia")
        self.assertEqual(countries["NZ"], "New Zealand")
        self.assertEqual(countries["US"], "United States")
        self.assertEqual(countries["GB"], "United Kingdom / Great Britain")
        self.assertNotIn("UK", countries)

    @patch("blindspot.ticketmaster.urllib.request.urlopen")
    def test_search_uses_requested_filters_and_fifty_item_page(self, urlopen):
        urlopen.return_value = StubResponse(
            {
                "_embedded": {"events": []},
                "page": {"number": 2, "totalPages": 4, "totalElements": 151},
            }
        )
        client = TicketmasterClient("secret key")

        page = client.search(
            keyword="festival",
            country="au",
            state="qld",
            city="Brisbane",
            genre="Rock",
            category_id="music-id",
            genre_id="rock-id",
            start_date="2026-10-01",
            end_date="2026-10-31",
            page=2,
        )

        query = urllib.parse.parse_qs(
            urllib.parse.urlsplit(urlopen.call_args.args[0].full_url).query
        )
        self.assertEqual(query["size"], ["50"])
        self.assertNotIn("segmentName", query)
        self.assertEqual(query["page"], ["2"])
        self.assertEqual(query["keyword"], ["festival"])
        self.assertEqual(query["countryCode"], ["AU"])
        self.assertEqual(query["stateCode"], ["QLD"])
        self.assertEqual(query["city"], ["Brisbane"])
        self.assertEqual(query["classificationName"], ["Rock"])
        self.assertEqual(query["segmentId"], ["music-id"])
        self.assertEqual(query["genreId"], ["rock-id"])
        self.assertEqual(query["startDateTime"], ["2026-10-01T00:00:00Z"])
        self.assertEqual(query["endDateTime"], ["2026-10-31T23:59:59Z"])
        self.assertTrue(page.has_more)

    def test_deep_paging_stops_before_ticketmaster_thousandth_result(self):
        from blindspot.ticketmaster import ConcertPage

        page = ConcertPage([], page=19, total_pages=30, total_events=1500)

        self.assertFalse(page.has_more)

    def test_event_label_contains_date_name_venue_location_and_genre(self):
        event = ConcertEvent(
            "event",
            "The Band",
            date="2026-10-01",
            time="19:30:00",
            venue="The Arena",
            city="Brisbane",
            state="Queensland",
            country="Australia",
            genre="Rock",
        )

        self.assertEqual(
            event.accessible_label(),
            "The Band — The Arena, Brisbane, Queensland, Australia — "
            "Rock — 2026-10-01 at 19:30",
        )


if __name__ == "__main__":
    unittest.main()
