import unittest

from blindspot.lastfm import LastfmClient


class StubLastfmClient(LastfmClient):
    def __init__(self, payload):
        super().__init__("key")
        self.payload = payload
        self.calls = []

    def _request(self, method, **parameters):
        self.calls.append((method, parameters))
        return self.payload


class LastfmClientTests(unittest.TestCase):
    def test_similar_tracks_maps_names_artists_and_attribution_url(self):
        client = StubLastfmClient(
            {
                "similartracks": {
                    "track": [
                        {
                            "name": "Related song",
                            "artist": {"name": "Related artist"},
                            "url": "https://last.fm/related",
                        }
                    ]
                }
            }
        )

        results = client.similar_tracks("Source", "Source artist")

        self.assertEqual(results[0].name, "Related song")
        self.assertEqual(results[0].artist, "Related artist")
        self.assertEqual(results[0].url, "https://last.fm/related")
        self.assertEqual(client.calls[0][0], "track.getSimilar")
        self.assertEqual(client.calls[0][1]["limit"], "50")

    def test_similar_artists_ignores_unnamed_results(self):
        client = StubLastfmClient(
            {
                "similarartists": {
                    "artist": [
                        {"name": "Related artist", "url": "https://last.fm/a"},
                        {"name": ""},
                    ]
                }
            }
        )

        results = client.similar_artists("Source artist")

        self.assertEqual([result.name for result in results], ["Related artist"])
        self.assertEqual(client.calls[0][0], "artist.getSimilar")

    def test_top_tag_albums_maps_artist_and_pagination(self):
        client = StubLastfmClient(
            {
                "albums": {
                    "album": [
                        {
                            "name": "Kind of Blue",
                            "artist": {"name": "Miles Davis"},
                            "url": "https://last.fm/album",
                        }
                    ],
                    "@attr": {"page": "2", "totalPages": "7"},
                }
            }
        )

        result = client.top_tag_items("jazz", "album", page=2)

        self.assertEqual(result.items[0].name, "Kind of Blue")
        self.assertEqual(result.items[0].artist, "Miles Davis")
        self.assertEqual(result.page, 2)
        self.assertEqual(result.total_pages, 7)
        self.assertEqual(client.calls[0][0], "tag.getTopAlbums")

    def test_top_tag_tracks_uses_live_api_response_container(self):
        client = StubLastfmClient(
            {
                "tracks": {
                    "track": [
                        {
                            "name": "Like a Tattoo",
                            "artist": {"name": "Sade"},
                        }
                    ],
                    "@attr": {"totalPages": "68"},
                }
            }
        )

        result = client.top_tag_items("jazz", "track")

        self.assertEqual(result.items[0].name, "Like a Tattoo")
        self.assertEqual(result.items[0].artist, "Sade")
        self.assertEqual(result.total_pages, 68)
    def test_genre_tags_are_ranked_and_drop_names_years_and_opinions(self):
        client = StubLastfmClient(
            {
                "toptags": {
                    "tag": [
                        {"name": "rock", "count": 62},
                        {"name": "alternative", "count": 100},
                        {"name": "radiohead", "count": 17},
                        {"name": "seen live", "count": 40},
                        {"name": "female vocalists", "count": 30},
                        {"name": "2025", "count": 20},
                        {"name": "Indie", "count": 41},
                        {"name": "indie", "count": 10},
                    ]
                }
            }
        )

        tags = client.top_genre_tags("track", "Creep", "Radiohead")

        self.assertEqual(
            [(tag.name, tag.weight) for tag in tags],
            [("alternative", 100), ("rock", 62), ("Indie", 41)],
        )
        self.assertEqual(client.calls[0][0], "track.getTopTags")
        self.assertEqual(client.calls[0][1]["artist"], "Radiohead")

    def test_artist_genre_tags_use_the_artist_method_and_limit(self):
        client = StubLastfmClient(
            {
                "toptags": {
                    "tag": [
                        {"name": f"genre {number}", "count": 100 - number}
                        for number in range(20)
                    ]
                }
            }
        )

        tags = client.top_genre_tags("artist", "Someone", limit=3)

        self.assertEqual(client.calls[0][0], "artist.getTopTags")
        self.assertEqual(len(tags), 3)
        self.assertEqual(tags[0].name, "genre 0")

    def test_genre_tags_ignore_accent_and_case_when_dropping_the_artist_name(self):
        client = StubLastfmClient(
            {"toptags": {"tag": [{"name": "ADÉLA", "count": 90}, {"name": "pop", "count": 5}]}}
        )

        tags = client.top_genre_tags("track", "Song", "Adela")

        self.assertEqual([tag.name for tag in tags], ["pop"])

    def test_genre_tags_are_empty_when_lastfm_has_none(self):
        client = StubLastfmClient({})

        self.assertEqual(client.top_genre_tags("artist", "Unknown"), [])

    def test_genre_tags_reject_unsupported_sources(self):
        client = StubLastfmClient({})

        with self.assertRaises(ValueError):
            client.top_genre_tags("album", "Anything")


if __name__ == "__main__":
    unittest.main()
