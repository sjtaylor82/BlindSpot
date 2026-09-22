import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock

from blindspot.applemusic import ChartEntry, ChartFeed
from blindspot.followed import FollowedArtists, artist_key, primary_artist
from blindspot.portable import PortableStore
from blindspot.ui import MainFrame


def store():
    return PortableStore(root=Path(tempfile.mkdtemp()))


class FollowedArtistsTests(unittest.TestCase):
    def test_names_compare_ignoring_case_accents_and_credits(self):
        self.assertEqual(artist_key("Kesha Nevé"), artist_key("kesha neve"))
        self.assertEqual(primary_artist("Luke Bryan, Luke Combs"), "Luke Bryan")

    def test_following_is_saved_and_reloaded(self):
        shared = store()
        first = FollowedArtists(shared)
        self.assertTrue(first.follow("John Williamson, Guest"))
        self.assertFalse(first.follow("john williamson"))
        first.remember_apple_ids({"John Williamson": "6436885"})

        second = FollowedArtists(shared)

        self.assertEqual(
            [(a.name, a.apple_id) for a in second.artists],
            [("John Williamson", "6436885")],
        )
        self.assertTrue(second.is_following("JOHN WILLIAMSON"))

    def test_unfollow_removes_the_artist(self):
        followed = FollowedArtists(store())
        followed.follow("Noah Nine")
        self.assertTrue(followed.unfollow("noah nine"))
        self.assertFalse(followed.unfollow("noah nine"))
        self.assertEqual(followed.artists, [])

    def test_releases_are_reported_once(self):
        followed = FollowedArtists(store())
        self.assertEqual(followed.unseen(["1", "2"]), ["1", "2"])
        followed.mark_seen(["1"])
        self.assertEqual(followed.unseen(["1", "2"]), ["2"])
        followed.mark_seen(["1", "2"])
        self.assertEqual(followed.seen, ["1", "2"])


class FollowedClientTests(unittest.TestCase):
    def client(self, routes):
        from test_applemusic import RoutedAppleMusicClient

        return RoutedAppleMusicClient(routes)

    def test_names_are_resolved_once_then_one_lookup_covers_everyone(self):
        recent = (date.today() - timedelta(days=2)).isoformat() + "T07:00:00Z"
        client = self.client(
            {
                "entity=musicArtist": {
                    "results": [
                        {"artistId": 7, "artistName": "John Williamson"},
                        {"artistId": 8, "artistName": "John Williams"},
                    ]
                },
                "/lookup?": {
                    "results": [
                        {"wrapperType": "artist"},
                        {
                            "wrapperType": "collection",
                            "collectionId": 1,
                            "collectionName": "September Wind - Single",
                            "artistName": "John Williamson",
                            "releaseDate": recent,
                        },
                        {
                            "wrapperType": "collection",
                            "collectionId": 2,
                            "collectionName": "Not Followed",
                            "artistName": "Someone Else",
                            "releaseDate": recent,
                        },
                    ]
                },
            }
        )

        feed, resolved, authors = client.followed_releases(
            "AU", [("John Williamson", "")], days=30
        )

        self.assertEqual(authors, {})
        self.assertEqual(resolved, {"John Williamson": "7"})
        self.assertEqual([e.name for e in feed.entries], ["September Wind"])
        self.assertEqual(len([u for u in client.urls if "/lookup?" in u]), 1)

    def test_known_ids_skip_the_name_search(self):
        client = self.client({"/lookup?": {"results": []}})

        feed, resolved, _authors = client.followed_releases(
            "AU", [("A", "1"), ("B", "2")]
        )

        self.assertEqual(resolved, {})
        self.assertEqual(feed.entries, [])
        self.assertFalse(any("musicArtist" in url for url in client.urls))
        self.assertIn("id=1%2C2", client.urls[0])


class FollowedAuthorTests(unittest.TestCase):
    def test_authors_and_artists_are_kept_apart(self):
        from blindspot.followed import ARTIST, AUTHOR

        followed = FollowedArtists(store())
        self.assertTrue(followed.follow("Andy Weir", AUTHOR))
        self.assertTrue(followed.follow("Andy Weir", ARTIST))
        self.assertTrue(followed.is_following("andy weir", AUTHOR))
        followed.unfollow("Andy Weir", ARTIST)
        self.assertTrue(followed.is_following("Andy Weir", AUTHOR))
        self.assertFalse(followed.is_following("Andy Weir", ARTIST))
        followed.remember_apple_ids({"Andy Weir": "624083612"}, AUTHOR)

        reloaded = FollowedArtists(followed.store)

        self.assertEqual(
            [(a.name, a.kind, a.apple_id) for a in reloaded.artists],
            [("Andy Weir", AUTHOR, "624083612")],
        )
        self.assertEqual(reloaded.of_kind(ARTIST), [])

    def test_a_file_from_before_authors_loads_as_artists(self):
        from blindspot.followed import ARTIST

        shared = store()
        shared.write(
            "followed_artists.json",
            {"artists": [{"name": "Noah Nine", "apple_id": "5"}], "seen": []},
        )

        self.assertEqual(FollowedArtists(shared).artists[0].kind, ARTIST)

    def test_author_releases_keep_only_english_editions_and_are_marked(self):
        from test_applemusic import RoutedAppleMusicClient

        recent = (date.today() - timedelta(days=3)).isoformat() + "T07:00:00Z"
        client = RoutedAppleMusicClient(
            {
                "media=audiobook": {
                    "results": [
                        {"artistId": 99, "artistName": "Andy Weir"},
                        {"artistId": 98, "artistName": "Andy Weir & Natalie Gerhardt"},
                    ]
                },
                "/lookup?": {
                    "results": [
                        {"wrapperType": "artist"},
                        {
                            "wrapperType": "audiobook",
                            "collectionId": 10,
                            "collectionName": "The Egg (Unabridged)",
                            "artistName": "Andy Weir",
                            "releaseDate": recent,
                            "collectionViewUrl": "https://books.apple.com/10",
                        },
                        {
                            "wrapperType": "audiobook",
                            "collectionId": 11,
                            "collectionName": "Seul sur Mars",
                            "artistName": "Andy Weir",
                            "releaseDate": recent,
                        },
                    ]
                },
            }
        )

        feed, artists, authors = client.followed_releases(
            "AU", [], [("Andy Weir", "")], days=30
        )

        self.assertEqual(authors, {"Andy Weir": "99"})
        self.assertEqual(artists, {})
        self.assertEqual(
            [(e.name, e.kind) for e in feed.entries], [("The Egg", "audiobook")]
        )
        self.assertIn("entity=audiobook", client.urls[-1])


class FollowedFrameTests(unittest.TestCase):
    def frame(self, followed):
        frame = Mock()
        frame.followed = followed
        frame.current_track = lambda: MainFrame.current_track(frame)
        return frame

    def test_toggling_follows_then_unfollows_and_says_so(self):
        frame = self.frame(FollowedArtists(store()))

        MainFrame.toggle_follow_artist(frame, "John Williamson")
        self.assertTrue(frame.followed.is_following("John Williamson"))
        MainFrame.toggle_follow_artist(frame, "John Williamson")
        self.assertFalse(frame.followed.is_following("John Williamson"))
        self.assertEqual(frame.say.call_count, 2)
        MainFrame.toggle_follow_artist(frame, "")
        self.assertEqual(frame.say.call_count, 3)

    def test_startup_check_announces_only_releases_not_yet_seen(self):
        followed = FollowedArtists(store())
        followed.follow("John Williamson")
        frame = self.frame(followed)
        feed = ChartFeed(
            [
                ChartEntry(
                    "September Wind", "John Williamson", "1", "", "2026-09-21"
                ),
                ChartEntry("Old One", "John Williamson", "2", "", "2026-09-01"),
            ],
            "au",
        )
        followed.mark_seen(["2"])

        MainFrame.finish_followed_check(frame, feed, {"John Williamson": "7"})
        first_call = list(frame.say.call_args_list)
        MainFrame.finish_followed_check(frame, feed, {})

        self.assertEqual(len(first_call), 1)
        self.assertIn("September Wind", first_call[0].args[0])
        self.assertEqual(frame.say.call_count, 1)
        self.assertEqual(followed.artists[0].apple_id, "7")

    def test_startup_check_is_silent_when_nothing_is_new(self):
        followed = FollowedArtists(store())
        followed.follow("A")
        frame = self.frame(followed)

        MainFrame.finish_followed_check(frame, ChartFeed([], "au"), {})

        frame.say.assert_not_called()

    def test_audiobook_rows_and_author_targets(self):
        from blindspot.applemusic import ChartEntry
        from blindspot.followed import ARTIST, AUTHOR
        from blindspot.models import ItemKind, SpotifyItem

        rows = MainFrame.apple_release_rows(
            [
                ChartEntry("The Egg", "Andy Weir", "1", "", "2026-08-25", "audiobook"),
                ChartEntry("Signs", "Luke Bryan", "2", "", "2026-09-18"),
            ],
            ItemKind.ALBUM,
        )
        book = SpotifyItem("b", ItemKind.AUDIOBOOK, "The Egg", artist="Andy Weir")

        self.assertEqual([r.kind for r in rows], [ItemKind.AUDIOBOOK, ItemKind.ALBUM])
        self.assertEqual(MainFrame.follow_target(book), ("Andy Weir", AUTHOR))
        self.assertEqual(
            MainFrame.follow_target(
                SpotifyItem("t", ItemKind.TRACK, "Song", artist="Luke Bryan")
            ),
            ("Luke Bryan", ARTIST),
        )

    def test_following_an_author_says_author(self):
        from blindspot.followed import AUTHOR

        frame = self.frame(FollowedArtists(store()))

        MainFrame.toggle_follow_artist(frame, "Andy Weir", AUTHOR)

        self.assertTrue(frame.followed.is_following("Andy Weir", AUTHOR))
        self.assertIn("author", frame.say.call_args.args[0])

    def test_the_artist_comes_from_the_item_kind(self):
        from blindspot.models import ItemKind, SpotifyItem

        track = SpotifyItem(
            "t", ItemKind.TRACK, "Song", artist="Luke Bryan, Luke Combs"
        )
        artist = SpotifyItem("a", ItemKind.ARTIST, "Noah Nine")

        self.assertEqual(MainFrame.item_artist_name(track), "Luke Bryan")
        self.assertEqual(MainFrame.item_artist_name(artist), "Noah Nine")


if __name__ == "__main__":
    unittest.main()
