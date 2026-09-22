import unittest

from blindspot.applemusic import (
    CACHE_SECONDS,
    CHART_COUNTRIES,
    DEFAULT_COUNTRY,
    AppleMusicClient,
    AppleMusicError,
    country_name,
    loaded_label,
)


class StubAppleMusicClient(AppleMusicClient):
    def __init__(self, payload):
        super().__init__()
        self.payload = payload
        self.urls = []

    def _request(self, url):
        self.urls.append(url)
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class AppleMusicClientTests(unittest.TestCase):
    def test_top_songs_maps_names_artists_and_the_feed_timestamp(self):
        client = StubAppleMusicClient(
            {
                "feed": {
                    "country": "au",
                    "updated": "Sun, 20 Sep 2026 01:18:58 +0000",
                    "results": [
                        {
                            "name": "Choosin' Texas",
                            "artistName": "Ella Langley",
                            "id": "1844932150",
                            "url": "https://music.apple.com/au/song/1844932150",
                            "releaseDate": "2025-10-17",
                        }
                    ],
                }
            }
        )

        feed = client.top_songs("AU", limit=10)

        self.assertEqual(feed.country, "au")
        self.assertEqual(feed.updated, "Sun, 20 Sep 2026 01:18:58 +0000")
        self.assertEqual(feed.entries[0].name, "Choosin' Texas")
        self.assertEqual(feed.entries[0].artist, "Ella Langley")
        self.assertEqual(feed.entries[0].apple_id, "1844932150")
        self.assertEqual(feed.entries[0].release_date, "2025-10-17")

    def test_country_is_lowercased_into_the_storefront_path(self):
        client = StubAppleMusicClient({"feed": {"results": []}})

        client.top_songs("GB", limit=25)

        self.assertIn("/v2/gb/music/most-played/25/songs.json", client.urls[0])

    def test_top_albums_uses_the_album_chart_and_maps_entries(self):
        client = StubAppleMusicClient(
            {"feed": {"results": [{"name": "Album", "artistName": "Artist"}]}}
        )

        feed = client.top_albums("AU", limit=25)

        self.assertIn("/v2/au/music/most-played/25/albums.json", client.urls[0])
        self.assertEqual(feed.entries[0].name, "Album")

    def test_limit_is_clamped_to_the_supported_range(self):
        client = StubAppleMusicClient({"feed": {"results": []}})

        client.top_songs("au", limit=0)
        client.top_songs("au", limit=500)

        self.assertIn("/most-played/1/songs.json", client.urls[0])
        self.assertIn("/most-played/100/songs.json", client.urls[1])

    def test_entries_missing_a_name_or_artist_are_skipped(self):
        client = StubAppleMusicClient(
            {
                "feed": {
                    "results": [
                        {"name": "Good", "artistName": "Artist"},
                        {"name": "", "artistName": "Artist"},
                        {"name": "No Artist", "artistName": ""},
                    ]
                }
            }
        )

        feed = client.top_songs("au")

        self.assertEqual([entry.name for entry in feed.entries], ["Good"])

    def test_an_empty_country_is_rejected(self):
        client = StubAppleMusicClient({"feed": {"results": []}})

        with self.assertRaises(ValueError):
            client.top_songs("   ")

    def test_a_missing_feed_yields_no_entries(self):
        client = StubAppleMusicClient({})

        self.assertEqual(client.top_songs("au").entries, [])

    def test_request_failures_surface_as_apple_music_errors(self):
        client = StubAppleMusicClient(AppleMusicError("unavailable"))

        with self.assertRaises(AppleMusicError):
            client.top_songs("au")

    def test_a_repeat_request_is_served_from_the_cache(self):
        client = StubAppleMusicClient(
            {"feed": {"results": [{"name": "A", "artistName": "B"}]}}
        )

        first = client.top_songs("au", limit=50)
        second = client.top_songs("AU", limit=50)

        self.assertEqual(len(client.urls), 1)
        self.assertIs(first, second)

    def test_a_different_country_or_limit_is_fetched_separately(self):
        client = StubAppleMusicClient({"feed": {"results": []}})

        client.top_songs("au", limit=50)
        client.top_songs("gb", limit=50)
        client.top_songs("au", limit=20)

        self.assertEqual(len(client.urls), 3)

    def test_a_stale_cache_entry_is_refetched(self):
        client = StubAppleMusicClient({"feed": {"results": []}})

        client.top_songs("au", limit=50)
        stamp, chart = client._cache[("au", "songs", 50)]
        client._cache[("au", "songs", 50)] = (stamp - CACHE_SECONDS - 1, chart)
        client.top_songs("au", limit=50)

        self.assertEqual(len(client.urls), 2)

    def test_chart_countries_are_unique_two_letter_codes(self):
        codes = [code for code, _name in CHART_COUNTRIES]
        names = [name for _code, name in CHART_COUNTRIES]

        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(len(code) == 2 and code.isupper() for code in codes))
        self.assertIn(DEFAULT_COUNTRY, codes)

    def test_country_name_resolves_codes_and_falls_back_to_the_code(self):
        self.assertEqual(country_name("pl"), "Poland")
        self.assertEqual(country_name(" AU "), "Australia")
        self.assertEqual(country_name("zz"), "ZZ")

    def test_loaded_label_formats_the_fetch_time_readably(self):
        label = loaded_label(1_790_000_000.0)

        self.assertIn(" at ", label)
        self.assertTrue(label.split()[-1] in {"AM", "PM"})
        self.assertFalse(label.startswith("0"))

    def test_loaded_label_is_empty_when_the_time_is_unknown(self):
        self.assertEqual(loaded_label(0.0), "")

    def test_a_fetched_feed_records_when_it_was_loaded_not_apples_stamp(self):
        client = StubAppleMusicClient(
            {
                "feed": {
                    "updated": "Sun, 20 Sep 2026 01:18:58 +0000",
                    "results": [],
                }
            }
        )

        feed = client.top_songs("au")

        self.assertGreater(feed.fetched_at, 1_700_000_000)
        self.assertEqual(feed.updated, "Sun, 20 Sep 2026 01:18:58 +0000")


if __name__ == "__main__":
    unittest.main()


def chart_payload(*entries):
    return {
        "feed": {
            "entry": [
                {
                    "im:name": {"label": name},
                    "im:artist": {"label": artist},
                    "id": {"label": f"https://music.apple.com/{ident}", "attributes": {"im:id": ident}},
                    "im:releaseDate": {"label": f"{released}T00:00:00-07:00"},
                }
                for ident, name, artist, released in entries
            ]
        }
    }


class RoutedAppleMusicClient(AppleMusicClient):
    """Answers each Apple endpoint from a table, recording what was asked."""

    def __init__(self, routes):
        super().__init__()
        self.routes = routes
        self.urls = []

    def _request(self, url):
        self.urls.append(url)
        for fragment, payload in self.routes.items():
            if fragment in url:
                return payload
        raise AssertionError(f"unexpected request {url}")


class NewReleaseTests(unittest.TestCase):
    def test_genre_chart_keeps_only_recent_entries_newest_first(self):
        from datetime import date
        from unittest.mock import patch

        client = RoutedAppleMusicClient(
            {
                "/au/rss/topsongs/genre=6/": chart_payload(
                    ("1", "Old Hit", "A", "2025-01-01"),
                    ("2", "Fresh", "B", "2026-09-18"),
                    ("3", "Freshest", "C", "2026-09-20"),
                    ("4", "Undated", "D", ""),
                )
            }
        )
        with patch("blindspot.applemusic.date") as fake_date:
            fake_date.today.return_value = date(2026, 9, 21)
            fake_date.fromisoformat = date.fromisoformat
            fake_date.min = date.min
            feed = client.new_releases("AU", media_type="songs", genre="6", days=30)

        self.assertEqual([e.name for e in feed.entries], ["Freshest", "Fresh"])
        self.assertIn("/au/rss/topsongs/genre=6/limit=100/json", client.urls[0])

    def test_any_time_and_any_genre_use_the_plain_album_chart(self):
        client = RoutedAppleMusicClient(
            {"/au/rss/topalbums/limit=100": chart_payload(("9", "Signs - EP", "L", "2020-01-01"))}
        )

        feed = client.new_releases("AU", media_type="albums", genre="", days=0)

        self.assertEqual([e.name for e in feed.entries], ["Signs"])
        self.assertNotIn("genre=", client.urls[0])

    def test_a_single_chart_entry_arrives_as_an_object_not_a_list(self):
        client = RoutedAppleMusicClient(
            {"topsongs": {"feed": {"entry": chart_payload(("1", "Only", "A", "2026-09-20"))["feed"]["entry"][0]}}}
        )

        feed = client.new_releases("AU", genre="6", days=0)

        self.assertEqual([e.name for e in feed.entries], ["Only"])

    def test_keyword_lists_the_matching_artists_newest_releases_first(self):
        client = RoutedAppleMusicClient(
            {
                "entity=musicArtist": {
                    "results": [
                        {"artistId": 11, "artistName": "John Williamson"},
                        {"artistId": 12, "artistName": "John Williams"},
                    ]
                },
                "/lookup?id=11&": {
                    "results": [
                        {"wrapperType": "artist"},
                        {
                            "wrapperType": "collection",
                            "collectionId": 5,
                            "collectionName": "September Wind - Single",
                            "artistName": "John Williamson",
                            "releaseDate": "2026-09-21T07:00:00Z",
                            "collectionViewUrl": "https://music.apple.com/5",
                        },
                        {
                            "wrapperType": "collection",
                            "collectionId": 4,
                            "collectionName": "How Many Songs",
                            "artistName": "John Williamson",
                            "releaseDate": "2025-04-04T07:00:00Z",
                        },
                    ]
                },
                "entity=album": {
                    "results": [
                        {
                            "wrapperType": "collection",
                            "collectionId": 5,
                            "collectionName": "September Wind - Single",
                            "artistName": "John Williamson",
                            "releaseDate": "2026-09-21T07:00:00Z",
                        },
                        {
                            "wrapperType": "collection",
                            "collectionId": 8,
                            "collectionName": "Other Williamson Title",
                            "artistName": "Someone Else",
                            "releaseDate": "2024-01-01T07:00:00Z",
                        },
                    ]
                },
            }
        )

        feed = client.new_releases("AU", keyword="Williamson", days=0)

        self.assertEqual(
            [(e.name, e.artist) for e in feed.entries],
            [
                ("September Wind", "John Williamson"),
                ("How Many Songs", "John Williamson"),
                ("Other Williamson Title", "Someone Else"),
            ],
        )
        # John Williams is not a match for "williamson", so it is never looked up.
        lookups = [url for url in client.urls if "/lookup?" in url]
        self.assertEqual(len(lookups), 1)
        self.assertNotIn("12", lookups[0].split("id=")[1].split("&")[0])
        self.assertTrue(any("sort=recent" in url for url in client.urls))

    def test_repeat_queries_are_served_from_memory(self):
        client = RoutedAppleMusicClient(
            {"topsongs": chart_payload(("1", "Fresh", "B", "2026-09-18"))}
        )

        client.new_releases("AU", genre="6", days=0)
        client.new_releases("AU", genre="6", days=0)

        self.assertEqual(len(client.urls), 1)


class UnreleasedTests(unittest.TestCase):
    def test_pre_orders_are_never_listed_as_new_releases(self):
        from datetime import date

        from blindspot.applemusic import ChartEntry, recent_first

        entries = [
            ChartEntry("Future", "A", release_date="2027-02-05T00:00:00Z"),
            ChartEntry("Today", "B", release_date="2026-09-21T00:00:00Z"),
            ChartEntry("Older", "C", release_date="2026-08-30T00:00:00Z"),
        ]
        today = date(2026, 9, 21)

        self.assertEqual(
            [e.name for e in recent_first(entries, 30, today)],
            ["Today", "Older"],
        )
        self.assertEqual(
            [e.name for e in recent_first(entries, 0, today)],
            ["Today", "Older"],
        )


class KeywordWindowTests(unittest.TestCase):
    def test_keyword_results_honour_the_release_window(self):
        from datetime import date, timedelta

        recent = (date.today() - timedelta(days=3)).isoformat()
        old = (date.today() - timedelta(days=200)).isoformat()
        client = RoutedAppleMusicClient(
            {
                "entity=musicArtist": {
                    "results": [{"artistId": 1, "artistName": "John Williamson"}]
                },
                "/lookup?": {
                    "results": [
                        {
                            "wrapperType": "collection",
                            "collectionId": 1,
                            "collectionName": "Fresh",
                            "artistName": "John Williamson",
                            "releaseDate": recent + "T07:00:00Z",
                        },
                        {
                            "wrapperType": "collection",
                            "collectionId": 2,
                            "collectionName": "Stale",
                            "artistName": "John Williamson",
                            "releaseDate": old + "T07:00:00Z",
                        },
                    ]
                },
                "entity=album": {"results": []},
            }
        )

        within_30 = client.new_releases("AU", keyword="john", days=30)
        any_time = client.new_releases("AU", keyword="john", days=0)

        self.assertEqual([e.name for e in within_30.entries], ["Fresh"])
        self.assertEqual([e.name for e in any_time.entries], ["Fresh", "Stale"])
