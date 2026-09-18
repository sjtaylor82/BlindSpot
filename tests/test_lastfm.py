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


if __name__ == "__main__":
    unittest.main()
