import unittest

from blindspot.models import ItemKind, SpotifyItem
from blindspot.playlist_operations import (
    AmbiguousPlaylistMoveError,
    PlaylistMovePartialError,
    PlaylistOperations,
    PlaylistSelection,
    PlaylistSourceChangedError,
    locate_playlist_selections,
)


class FakeClient:
    def __init__(self, *, removal_error=None):
        self.calls = []
        self.removal_error = removal_error
        self.source_items = []

    def children(self, playlist):
        self.calls.append(("children", playlist))
        return self.source_items

    def add_items_to_playlist(self, playlist, items):
        self.calls.append(("add", playlist, items))
        return len(items)

    def remove_items_from_playlist(self, playlist, items):
        self.calls.append(("remove", playlist, items))
        if self.removal_error:
            raise self.removal_error
        return len(items)


class PlaylistOperationsTests(unittest.TestCase):
    def setUp(self):
        self.source = SpotifyItem("source", ItemKind.PLAYLIST, "Source")
        self.destination = SpotifyItem(
            "destination", ItemKind.PLAYLIST, "Destination"
        )
        self.track = SpotifyItem(
            "track", ItemKind.TRACK, "Track", uri="spotify:track:track"
        )

    def test_move_adds_before_removing_source(self):
        client = FakeClient()
        client.source_items = [self.track]

        PlaylistOperations(client).move(
            self.source,
            self.destination,
            [PlaylistSelection(self.track, 7)],
        )

        self.assertEqual(
            [call[0] for call in client.calls], ["children", "add", "remove"]
        )

    def test_failed_addition_never_removes_source(self):
        class AddFailureClient(FakeClient):
            def add_items_to_playlist(self, playlist, items):
                self.calls.append(("add", playlist, items))
                raise RuntimeError("add failed")

        client = AddFailureClient()
        client.source_items = [self.track]

        with self.assertRaisesRegex(RuntimeError, "add failed"):
            PlaylistOperations(client).move(
                self.source,
                self.destination,
                [PlaylistSelection(self.track, 2)],
            )

        self.assertEqual(
            [call[0] for call in client.calls], ["children", "add"]
        )

    def test_failed_removal_reports_copy_without_encouraging_retry(self):
        client = FakeClient(removal_error=RuntimeError("remove failed"))
        client.source_items = [self.track]

        with self.assertRaises(PlaylistMovePartialError) as raised:
            PlaylistOperations(client).move(
                self.source,
                self.destination,
                [PlaylistSelection(self.track, 2)],
            )

        self.assertIn("Do not repeat Move", str(raised.exception))
        self.assertIn("Review both playlists", str(raised.exception))

    def test_move_refuses_ambiguous_duplicate_occurrences_before_copying(self):
        duplicate = SpotifyItem(
            "track", ItemKind.TRACK, "Track", uri="spotify:track:track"
        )
        client = FakeClient()
        client.source_items = [self.track, duplicate]

        with self.assertRaises(AmbiguousPlaylistMoveError):
            PlaylistOperations(client).move(
                self.source,
                self.destination,
                [PlaylistSelection(self.track, 0)],
            )

        self.assertEqual([call[0] for call in client.calls], ["children"])

    def test_move_refuses_when_cut_item_no_longer_exists(self):
        client = FakeClient()

        with self.assertRaises(PlaylistSourceChangedError):
            PlaylistOperations(client).move(
                self.source,
                self.destination,
                [PlaylistSelection(self.track, 0)],
            )

        self.assertEqual([call[0] for call in client.calls], ["children"])

    def test_equal_duplicate_occurrences_keep_distinct_positions(self):
        duplicate = SpotifyItem(
            "track", ItemKind.TRACK, "Track", uri="spotify:track:track"
        )
        source = [self.track, duplicate]

        selections = locate_playlist_selections(source, source)

        self.assertEqual(
            [selection.source_index for selection in selections], [0, 1]
        )
