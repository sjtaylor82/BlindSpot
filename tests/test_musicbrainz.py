import io
import unittest
import urllib.error
from unittest.mock import patch

from blindspot import musicbrainz
from blindspot.musicbrainz import (
    CoversUnavailable,
    MusicBrainzClient,
    MusicBrainzError,
    key,
    rank_seed_candidates,
    select_covers,
    title_key,
)


def recording(
    identifier,
    title="Hallelujah",
    artists=("Someone",),
    year="2010",
    disambiguation="",
    video=False,
    score=100,
):
    return {
        "id": identifier,
        "title": title,
        "artist-credit": [{"name": name, "joinphrase": ""} for name in artists],
        "first-release-date": year,
        "disambiguation": disambiguation,
        "video": video,
        "score": score,
    }


COVER = frozenset({"cover"})
LIVE = frozenset({"live", "cover"})


class KeyTests(unittest.TestCase):
    def test_names_compare_without_case_accents_or_punctuation(self):
        self.assertEqual(key("Beyoncé"), key("beyonce"))
        self.assertEqual(key("Mr. Brightside"), key("mr brightside"))

    def test_titles_ignore_bracketed_version_notes(self):
        self.assertEqual(title_key("Hurt (Remastered 2011)"), title_key("Hurt"))

    def test_a_title_that_is_only_a_bracket_is_not_emptied(self):
        self.assertEqual(title_key("(Untitled)"), "untitled")


class SelectCoversTests(unittest.TestCase):
    def test_the_source_artist_is_left_out(self):
        recordings = [
            recording("a", artists=("Leonard Cohen",)),
            recording("b", artists=("Jeff Buckley",)),
        ]

        covers = select_covers(recordings, {"a": COVER, "b": COVER}, "Leonard Cohen")

        self.assertEqual([c.artist for c in covers], ["Jeff Buckley"])

    def test_a_collaboration_including_the_source_artist_is_left_out(self):
        recordings = [recording("a", artists=("Leonard Cohen", "Sharon Robinson"))]

        self.assertEqual(select_covers(recordings, {"a": COVER}, "leonard cohen"), [])

    def test_live_video_and_karaoke_recordings_are_left_out(self):
        recordings = [
            recording("live", artists=("A",)),
            recording("titled", title="Hallelujah (Live at Glastonbury)", artists=("B",)),
            recording("disamb", artists=("C",), disambiguation="live, 2008-10-29: Frankfurt"),
            recording("video", artists=("D",), video=True),
            recording("karaoke", title="Hallelujah (Karaoke Version)", artists=("E",)),
            recording("studio", artists=("Studio Act",)),
        ]
        flags = {"live": LIVE, "studio": COVER}

        covers = select_covers(recordings, flags, "Someone Else", "Hallelujah")

        self.assertEqual([c.artist for c in covers], ["Studio Act"])

    def test_marked_covers_come_first_then_alphabetical(self):
        recordings = [
            recording("1", artists=("Zed",)),
            recording("2", artists=("Amy",)),
            recording("3", artists=("Bob",)),
        ]

        covers = select_covers(
            recordings,
            {"1": COVER, "3": COVER},
            "Original",
            "Hallelujah",
        )

        self.assertEqual([c.artist for c in covers], ["Bob", "Zed", "Amy"])
        self.assertEqual([c.marked_cover for c in covers], [True, True, False])

    def test_unmarked_medleys_and_other_titles_are_dropped_but_marked_covers_kept(self):
        recordings = [
            recording("medley", title="Hallelujah / Something Else", artists=("Corps",)),
            recording("other", title="A Different Song", artists=("Band",)),
            recording("marked", title="Halleluiah", artists=("Choir",)),
            recording("plain", title="Hallelujah", artists=("Solo",)),
        ]

        covers = select_covers(recordings, {"marked": COVER}, "Original", "Hallelujah")

        self.assertEqual(sorted(c.artist for c in covers), ["Choir", "Solo"])

    def test_one_entry_per_artist_and_title_preferring_a_marked_dated_one(self):
        recordings = [
            recording("first", artists=("Alexandra Burke",), year=""),
            recording("second", artists=("Alexandra Burke",), year="2014"),
            recording("third", artists=("alexandra burke",), year="2012"),
        ]

        covers = select_covers(
            recordings,
            {"second": COVER, "third": COVER},
            "Cohen",
            "Hallelujah",
        )

        self.assertEqual(len(covers), 1)
        self.assertTrue(covers[0].marked_cover)
        self.assertEqual(covers[0].year, "2014")

    def test_novelty_versions_sort_after_everything_else(self):
        recordings = [
            recording("a", artists=("8-Bit Misfits",)),
            recording("b", artists=("Zoe",)),
            recording("c", title="Hallelujah (Bardcore)", artists=("Adam",)),
        ]

        covers = select_covers(
            recordings,
            {"a": COVER, "b": COVER, "c": COVER},
            "Cohen",
            "Hallelujah",
        )

        self.assertEqual(covers[0].artist, "Zoe")
        self.assertEqual({c.artist for c in covers[1:]}, {"8-Bit Misfits", "Adam"})

    def test_recordings_without_an_artist_are_skipped(self):
        anonymous = {"id": "x", "title": "Hallelujah", "artist-credit": []}

        self.assertEqual(select_covers([anonymous], {}, "Cohen"), [])

    def test_the_release_year_comes_from_the_first_release_date(self):
        covers = select_covers(
            [recording("a", artists=("A",), year="2014-03-11")],
            {"a": COVER},
            "Cohen",
        )

        self.assertEqual(covers[0].year, "2014")

    def test_joined_artist_credits_read_naturally(self):
        rec = {
            "id": "a",
            "title": "Hallelujah",
            "artist-credit": [
                {"name": "Anisha Jo", "joinphrase": " & "},
                {"name": "Star Academy", "joinphrase": ""},
            ],
        }

        covers = select_covers([rec], {"a": COVER}, "Cohen")

        self.assertEqual(covers[0].artist, "Anisha Jo & Star Academy")


class SeedTests(unittest.TestCase):
    def test_a_studio_recording_is_preferred_over_live_ones(self):
        hits = [
            recording("live", artists=("Leonard Cohen",), disambiguation="live, 2008: Frankfurt"),
            recording("studio", artists=("Leonard Cohen",), score=90),
        ]

        ranked = rank_seed_candidates(hits, "Hallelujah", "Leonard Cohen")

        self.assertEqual([r["id"] for r in ranked], ["studio", "live"])

    def test_recordings_by_other_artists_are_not_used_as_the_seed(self):
        hits = [recording("other", artists=("Jeff Buckley",))]

        self.assertEqual(rank_seed_candidates(hits, "Hallelujah", "Leonard Cohen"), [])

    def test_a_different_title_by_the_right_artist_is_a_fallback(self):
        hits = [recording("x", title="Hallelujah (2011 remaster)x", artists=("Leonard Cohen",))]

        self.assertEqual(
            len(rank_seed_candidates(hits, "Something Else", "Leonard Cohen")),
            1,
        )


class ScriptedClient(MusicBrainzClient):
    """A client whose network answers come from a script."""

    def __init__(self, answers):
        super().__init__()
        self.answers = answers
        self.calls = []

    def _get(self, path, **parameters):
        self.calls.append((path, parameters))
        answer = self.answers[path.split("/")[0]] if "/" not in path else self.answers[path]
        return answer(parameters) if callable(answer) else answer


def scripted(*, work=True, total=250, pages=None):
    seed = recording("seed", artists=("Leonard Cohen",))
    pages = pages or {
        0: [recording(f"r{n}", artists=(f"Artist {n}",)) for n in range(100)],
        100: [recording(f"r{n}", artists=(f"Artist {n}",)) for n in range(100, 200)],
        200: [recording(f"r{n}", artists=(f"Artist {n}",)) for n in range(200, 250)],
    }
    relations = [{"work": {"id": "work1", "title": "Hallelujah"}}] if work else []

    def browse_or_search(parameters):
        if "query" in parameters:
            return {"recordings": [seed]}
        offset = parameters["offset"]
        return {"recordings": pages.get(offset, []), "recording-count": total}

    return {
        "recording": browse_or_search,
        "recording/seed": {"relations": relations},
        "work/work1": {
            "relations": [
                {"recording": {"id": f"r{n}"}, "attributes": ["cover"]}
                for n in range(250)
            ]
        },
    }


class ClientFlowTests(unittest.TestCase):
    def test_a_lookup_finds_the_work_reads_flags_and_lists_the_recordings(self):
        client = ScriptedClient(scripted())

        result = client.find_covers("Hallelujah", "Leonard Cohen")

        self.assertEqual(result.work_title, "Hallelujah")
        self.assertEqual(result.total_recordings, 250)
        self.assertEqual(result.examined, 250)
        self.assertEqual(len(result.covers), 250)
        self.assertTrue(all(c.marked_cover for c in result.covers))
        paths = [path for path, _ in client.calls]
        self.assertEqual(paths[:3], ["recording", "recording/seed", "work/work1"])
        # Search, work lookup, flags, three browse pages, then the same-title search.
        self.assertEqual(len(paths), 7)

    def test_the_search_is_quoted_and_escaped(self):
        client = ScriptedClient(scripted())

        # The scripted song is a different one, so this ends in a notice; only
        # the first request matters here.
        with self.assertRaises(CoversUnavailable):
            client.find_covers('Say "Hi"', "AC\\DC")
        query = client.calls[0][1]["query"]

        self.assertIn('recording:"Say \\"Hi\\""', query)
        self.assertIn('artist:"AC\\\\DC"', query)

    def test_reading_stops_at_the_recording_cap_and_says_how_many_were_examined(self):
        pages = {
            offset: [recording(f"r{offset + n}", artists=(f"A{offset + n}",)) for n in range(100)]
            for offset in range(0, 1000, 100)
        }
        client = ScriptedClient(scripted(total=1000, pages=pages))

        result = client.find_covers("Hallelujah", "Leonard Cohen")

        self.assertEqual(result.examined, musicbrainz.MAX_RECORDINGS)
        self.assertEqual(result.total_recordings, 1000)
        browse_calls = [c for c in client.calls if "offset" in c[1]]
        self.assertEqual(len(browse_calls), musicbrainz.MAX_RECORDINGS // 100)

    def test_a_song_not_in_musicbrainz_is_a_notice(self):
        answers = scripted()
        answers["recording"] = lambda parameters: {"recordings": []}
        client = ScriptedClient(answers)

        with self.assertRaises(CoversUnavailable) as caught:
            client.find_covers("Nonexistent", "Nobody")

        self.assertIn("could not find Nonexistent by Nobody", str(caught.exception))

    def test_a_recording_with_no_work_is_a_notice_and_stops_early(self):
        client = ScriptedClient(scripted(work=False))

        with self.assertRaises(CoversUnavailable) as caught:
            client.find_covers("Hallelujah", "Leonard Cohen")

        self.assertIn("no song entry linked", str(caught.exception))
        self.assertNotIn("work/work1", [path for path, _ in client.calls])

    def test_same_title_recordings_missing_from_the_work_are_added_after_it(self):
        answers = scripted()
        seed = recording("seed", artists=("Leonard Cohen",))
        newcomer = loose(
            "new", "Olivia Dean", title="Hallelujah", year="2025", length=250_000
        )
        answers["recording"] = lambda parameters: (
            {"recordings": [seed, newcomer]}
            if "query" in parameters
            else scripted()["recording"](parameters)
        )
        client = ScriptedClient(answers)

        result = client.find_covers("Hallelujah", "Leonard Cohen", 240_000)

        newcomers = [c for c in result.covers if c.artist == "Olivia Dean"]
        self.assertEqual(len(newcomers), 1)
        self.assertFalse(newcomers[0].linked)
        self.assertEqual(result.unlinked, 1)
        self.assertEqual(result.covers[-1].artist, "Olivia Dean")

    def test_a_failure_in_the_same_title_search_keeps_the_songs_own_list(self):
        answers = scripted()
        original = answers["recording"]

        def flaky(parameters):
            if "query" in parameters and parameters["query"].count("artist") == 0:
                raise MusicBrainzError("MusicBrainz is busy. Try again in a minute.")
            return original(parameters)

        answers["recording"] = flaky
        client = ScriptedClient(answers)

        result = client.find_covers("Hallelujah", "Leonard Cohen")

        self.assertEqual(len(result.covers), 250)
        self.assertEqual(result.unlinked, 0)

    def test_a_repeat_lookup_uses_the_cache(self):
        client = ScriptedClient(scripted())

        first = client.find_covers("Hallelujah", "Leonard Cohen")
        calls = len(client.calls)
        second = client.find_covers("HALLELUJAH", "leonard cohen")

        self.assertIs(first, second)
        self.assertEqual(len(client.calls), calls)

    def test_an_expired_cache_entry_is_fetched_again(self):
        client = ScriptedClient(scripted())
        client.find_covers("Hallelujah", "Leonard Cohen")
        cache_key = next(iter(client._cache))
        stamp, result = client._cache[cache_key]
        client._cache[cache_key] = (stamp - musicbrainz.CACHE_SECONDS - 1, result)
        calls = len(client.calls)

        client.find_covers("Hallelujah", "Leonard Cohen")

        self.assertGreater(len(client.calls), calls)


def loose(identifier, artist, title="Diamonds on the Soles of Her Shoes", length=344_000, **kw):
    item = recording(identifier, title=title, artists=(artist,), **kw)
    item["length"] = length
    return item


class TitleMatchTests(unittest.TestCase):
    TITLE = "Diamonds on the Soles of Her Shoes"

    def _select(self, recordings, known=(), length=344_000, artist="Paul Simon"):
        return musicbrainz.select_title_matches(
            recordings, set(known), self.TITLE, artist, length
        )

    def test_a_same_title_recording_by_someone_else_is_included(self):
        covers = self._select([loose("a", "Olivia Dean", year="2025")])

        self.assertEqual([c.artist for c in covers], ["Olivia Dean"])
        self.assertFalse(covers[0].linked)
        self.assertFalse(covers[0].marked_cover)
        self.assertEqual(covers[0].year, "2025")

    def test_recordings_already_in_the_songs_own_list_are_not_repeated(self):
        self.assertEqual(self._select([loose("a", "Olivia Dean")], known={"a"}), [])

    def test_the_source_artist_and_other_titles_are_excluded(self):
        covers = self._select(
            [
                loose("a", "Paul Simon"),
                loose("b", "Someone", title="Diamonds"),
                loose("c", "Another"),
            ]
        )

        self.assertEqual([c.artist for c in covers], ["Another"])

    def test_live_video_and_karaoke_same_title_recordings_are_excluded(self):
        covers = self._select(
            [
                loose("a", "A", disambiguation="live, 2008-10-29: Frankfurt"),
                loose("b", "B", video=True),
                loose("c", "C", title=self.TITLE + " (Karaoke Version)"),
                loose("d", "D", title=self.TITLE + " (Live)"),
                loose("e", "Keeper"),
            ]
        )

        self.assertEqual([c.artist for c in covers], ["Keeper"])

    def test_a_recording_of_a_very_different_length_is_probably_another_song(self):
        covers = self._select(
            [loose("short", "Short", length=90_000), loose("ok", "Fine", length=300_000)]
        )

        self.assertEqual([c.artist for c in covers], ["Fine"])

    def test_without_a_known_length_the_check_is_skipped(self):
        covers = self._select([loose("a", "Anyone", length=30_000)], length=0)

        self.assertEqual(len(covers), 1)

    def test_a_missing_length_counts_only_for_a_distinctive_title(self):
        long_title = self._select([loose("a", "Anyone", length=0)])
        short = musicbrainz.select_title_matches(
            [loose("b", "Anyone", title="Hurt", length=0)],
            set(),
            "Hurt",
            "Nine Inch Nails",
            134_000,
        )

        self.assertEqual(len(long_title), 1)
        self.assertEqual(short, [])

    def test_one_entry_per_artist_and_the_list_is_capped(self):
        many = [loose(f"r{n}", f"Artist {n:03d}") for n in range(100)]
        many += [loose("dup", "Artist 000")]

        covers = self._select(many)

        self.assertEqual(len(covers), musicbrainz.MAX_UNLINKED)
        self.assertEqual(len({c.artist for c in covers}), len(covers))


class SortTests(unittest.TestCase):
    def test_marked_then_linked_then_same_title_with_novelty_last(self):
        covers = [
            musicbrainz.Cover("S", "Zoe", "", False, "1", linked=False),
            musicbrainz.Cover("S", "Yan", "", False, "2"),
            musicbrainz.Cover("S", "Xia", "", True, "3"),
            musicbrainz.Cover("S", "8-Bit Band", "", True, "4"),
        ]

        ordered = musicbrainz.sort_covers(covers)

        self.assertEqual([c.artist for c in ordered], ["Xia", "Yan", "Zoe", "8-Bit Band"])


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self.payload


class TransportTests(unittest.TestCase):
    def _client(self):
        client = MusicBrainzClient()
        client._last_request = 0.0
        return client

    def test_requests_identify_the_app_and_ask_for_json(self):
        seen = []

        def urlopen(request, timeout, context):
            seen.append(request)
            return Response(b'{"ok": true}')

        with patch("blindspot.musicbrainz.urllib.request.urlopen", urlopen):
            data = self._client()._get("recording", query="x", limit=1)

        self.assertEqual(data, {"ok": True})
        request = seen[0]
        self.assertIn("BlindSpot/", request.get_header("User-agent"))
        self.assertIn("github.com/sjtaylor82/BlindSpot", request.get_header("User-agent"))
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertIn("fmt=json", request.full_url)

    def test_requests_are_spaced_at_least_a_second_apart(self):
        sleeps = []
        client = self._client()

        with (
            patch("blindspot.musicbrainz.urllib.request.urlopen", lambda *a, **k: Response(b"{}")),
            patch("blindspot.musicbrainz.time.sleep", sleeps.append),
        ):
            client._get("recording")
            client._get("recording")

        self.assertEqual(len(sleeps), 1)
        self.assertGreater(sleeps[0], 0.5)
        self.assertLessEqual(sleeps[0], musicbrainz.MIN_INTERVAL)

    def test_a_busy_server_is_reported_plainly(self):
        error = urllib.error.HTTPError("u", 503, "Busy", {}, io.BytesIO(b""))

        with patch("blindspot.musicbrainz.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(MusicBrainzError) as caught:
                self._client()._get("recording")

        self.assertIn("busy", str(caught.exception))
        self.assertNotIsInstance(caught.exception, CoversUnavailable)

    def test_other_http_errors_and_network_failures_are_reported(self):
        cases = [
            (urllib.error.HTTPError("u", 500, "x", {}, io.BytesIO(b"")), "(500)"),
            (urllib.error.URLError("down"), "could not be reached"),
            (TimeoutError(), "could not be reached"),
        ]
        for failure, expected in cases:
            with patch("blindspot.musicbrainz.urllib.request.urlopen", side_effect=failure):
                with self.assertRaises(MusicBrainzError) as caught:
                    self._client()._get("recording")
            self.assertIn(expected, str(caught.exception))

    def test_an_unreadable_answer_is_reported(self):
        with patch(
            "blindspot.musicbrainz.urllib.request.urlopen",
            lambda *a, **k: Response(b"<html>not json"),
        ):
            with self.assertRaises(MusicBrainzError) as caught:
                self._client()._get("recording")

        self.assertIn("unreadable", str(caught.exception))

    def test_the_spacing_clock_advances_even_when_a_request_fails(self):
        client = self._client()

        with patch(
            "blindspot.musicbrainz.urllib.request.urlopen",
            side_effect=urllib.error.URLError("down"),
        ):
            with self.assertRaises(MusicBrainzError):
                client._get("recording")

        self.assertGreater(client._last_request, 0)


if __name__ == "__main__":
    unittest.main()
