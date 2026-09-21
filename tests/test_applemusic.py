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
