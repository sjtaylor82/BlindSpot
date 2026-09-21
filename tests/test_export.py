import csv
import io
import unittest
from datetime import date

from blindspot import export
from blindspot.models import ItemKind, SpotifyItem


def track(number, name="Song", artist="Artist", album="Album", ms=232_000, uri=True):
    return SpotifyItem(
        f"id{number}",
        ItemKind.TRACK,
        f"{name} {number}" if name == "Song" else name,
        artist=artist,
        album=album,
        duration_ms=ms,
        uri=f"spotify:track:id{number}" if uri else "",
    )


class DurationTests(unittest.TestCase):
    def test_minutes_and_seconds(self):
        self.assertEqual(export.duration_label(232_000), "3:52")
        self.assertEqual(export.duration_label(65_000), "1:05")

    def test_an_hour_or_more_includes_hours(self):
        self.assertEqual(export.duration_label(3_723_000), "1:02:03")

    def test_unknown_duration_is_blank(self):
        self.assertEqual(export.duration_label(0), "")


class LinkTests(unittest.TestCase):
    def test_tracks_and_episodes_become_open_spotify_links(self):
        self.assertEqual(
            export.spotify_link(track(1)),
            "https://open.spotify.com/track/id1",
        )
        episode = SpotifyItem("e", ItemKind.EPISODE, "Ep", uri="spotify:episode:abc9")
        self.assertEqual(
            export.spotify_link(episode),
            "https://open.spotify.com/episode/abc9",
        )

    def test_missing_or_unrecognised_uris_give_no_link(self):
        self.assertEqual(export.spotify_link(track(1, uri=False)), "")
        odd = SpotifyItem("x", ItemKind.TRACK, "X", uri="spotify:local:a:b:c:1")
        self.assertEqual(export.spotify_link(odd), "")


class RowTests(unittest.TestCase):
    def test_headings_are_skipped_and_positions_stay_consecutive(self):
        heading = SpotifyItem(
            "h", ItemKind.HEADING, "Show more", raw={"load_more": True}
        )
        album = SpotifyItem("a", ItemKind.ALBUM, "An album")

        rows = export.export_rows([track(1), heading, album, track(2)])

        self.assertEqual([row.position for row in rows], [1, 2])
        self.assertEqual([row.title for row in rows], ["Song 1", "Song 2"])

    def test_episodes_are_exported_alongside_tracks(self):
        episode = SpotifyItem("e", ItemKind.EPISODE, "Ep", artist="Publisher")

        self.assertEqual(len(export.export_rows([track(1), episode])), 2)

    def test_repeated_tracks_stay_as_separate_positions(self):
        rows = export.export_rows([track(1), track(1)])

        self.assertEqual([row.position for row in rows], [1, 2])

    def test_partial_lists_are_detected_from_any_load_more_row(self):
        for key in ("load_more", "lastfm_tag_load_more", "load_more_episodes"):
            marker = SpotifyItem("m", ItemKind.HEADING, "More", raw={key: True})
            self.assertTrue(export.is_partial([track(1), marker]), key)

    def test_a_complete_list_is_not_partial(self):
        heading = SpotifyItem("h", ItemKind.HEADING, "Section")
        self.assertFalse(export.is_partial([track(1), heading]))


class TextTests(unittest.TestCase):
    def test_text_lists_position_title_artist_album_duration_and_link(self):
        rows = export.export_rows([track(1), track(2)])

        text = export.to_text("My list", rows, today=date(2026, 9, 20))

        self.assertTrue(text.startswith("My list\n"))
        self.assertIn("Exported from BlindSpot on 20 September 2026: 2 items", text)
        self.assertIn(
            "1. Song 1 - Artist - Album - 3:52 (https://open.spotify.com/track/id1)",
            text,
        )
        self.assertIn("2. Song 2", text)
        self.assertNotIn("partial", text)

    def test_a_single_item_is_not_pluralised(self):
        text = export.to_text("L", export.export_rows([track(1)]))

        self.assertIn("1 item\n", text)

    def test_missing_fields_do_not_leave_stray_separators(self):
        rows = export.export_rows([track(1, artist="", album="", ms=0, uri=False)])

        line = export.to_text("L", rows).splitlines()[-1]

        self.assertEqual(line, "1. Song 1")

    def test_a_partial_list_says_so(self):
        text = export.to_text("L", export.export_rows([track(1)]), partial=True)

        self.assertIn("partial list", text)


class CsvTests(unittest.TestCase):
    def _parse(self, text):
        return list(csv.reader(io.StringIO(text)))

    def test_header_and_rows(self):
        parsed = self._parse(export.to_csv(export.export_rows([track(1)])))

        self.assertEqual(
            parsed[0],
            ["Position", "Title", "Artist", "Album", "Duration", "Spotify link"],
        )
        self.assertEqual(
            parsed[1],
            ["1", "Song 1", "Artist", "Album", "3:52", "https://open.spotify.com/track/id1"],
        )

    def test_commas_quotes_and_newlines_round_trip(self):
        awkward = track(1, name='He said "hi", then left', artist="A, B", album="Two\nLines")

        parsed = self._parse(export.to_csv(export.export_rows([awkward])))

        self.assertEqual(parsed[1][1:4], ['He said "hi", then left', "A, B", "Two\nLines"])

    def test_polish_and_other_unicode_survive(self):
        parsed = self._parse(
            export.to_csv(export.export_rows([track(1, name="Następna stacja", artist="Łódź")]))
        )

        self.assertEqual(parsed[1][1:3], ["Następna stacja", "Łódź"])

    def test_titles_that_look_like_formulas_are_neutralised(self):
        rows = export.export_rows(
            [track(1, name="=HYPERLINK(\"http://x\")"), track(2, name="+1 call", artist="@handle")]
        )

        parsed = self._parse(export.to_csv(rows))

        self.assertEqual(parsed[1][1], "'=HYPERLINK(\"http://x\")")
        self.assertEqual(parsed[2][1], "'+1 call")
        self.assertEqual(parsed[2][2], "'@handle")

    def test_ordinary_titles_are_left_untouched(self):
        parsed = self._parse(export.to_csv(export.export_rows([track(1, name="Normal")])))

        self.assertEqual(parsed[1][1], "Normal")


class FilenameTests(unittest.TestCase):
    def test_characters_windows_forbids_are_replaced(self):
        self.assertEqual(export.safe_filename('AC/DC: "Best" <of>?'), "AC DC Best of")

    def test_trailing_dots_and_spaces_are_stripped(self):
        self.assertEqual(export.safe_filename("Road trip. "), "Road trip")

    def test_empty_names_get_a_fallback(self):
        self.assertEqual(export.safe_filename(" /// "), "BlindSpot list")

    def test_very_long_names_are_shortened(self):
        self.assertLessEqual(len(export.safe_filename("x" * 300)), 100)


class WriteExportTests(unittest.TestCase):
    def test_text_export_writes_a_readable_utf8_file(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "list.txt"

            count = export.write_export(
                target, "txt", "Mój zestaw", [track(1, name="Następna stacja")]
            )

            content = target.read_text(encoding="utf-8")

        self.assertEqual(count, 1)
        self.assertTrue(content.startswith("M\u00f3j zestaw\n"))
        self.assertIn("1. Następna stacja", content)

    def test_csv_export_has_a_byte_order_mark_and_crlf_rows(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "list.csv"

            export.write_export(target, "csv", "L", [track(1), track(2)])

            raw = target.read_bytes()

        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(raw.count(b"\r\n"), 3)
        self.assertNotIn(b"\r\r", raw)

    def test_csv_export_reads_back_with_a_spreadsheet_style_reader(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "list.csv"
            export.write_export(target, "csv", "L", [track(1, name="Łódź, 1")])

            with open(target, encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.reader(handle))

        self.assertEqual(rows[1][1], "Łódź, 1")

    def test_a_partial_flag_reaches_the_text_file(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "list.txt"
            export.write_export(target, "txt", "L", [track(1)], partial=True)

            self.assertIn("partial list", target.read_text(encoding="utf-8"))

    def test_an_unwritable_path_raises_for_the_caller_to_report(self):
        with self.assertRaises(OSError):
            export.write_export("/no/such/folder/here/list.txt", "txt", "L", [track(1)])


class FormatChoiceTests(unittest.TestCase):
    def test_the_typed_extension_wins(self):
        self.assertEqual(export.format_for_path("a.CSV", 0), "csv")
        self.assertEqual(export.format_for_path("a.txt", 1), "txt")

    def test_otherwise_the_chosen_filter_decides(self):
        self.assertEqual(export.format_for_path("a", 0), "txt")
        self.assertEqual(export.format_for_path("a", 1), "csv")


if __name__ == "__main__":
    unittest.main()
