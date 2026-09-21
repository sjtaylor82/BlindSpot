import tempfile
import unittest
from pathlib import Path

from blindspot import diagnostics
from blindspot.diagnostics import (
    ErrorDetails,
    capture_error,
    diagnostic_report,
    error_report,
    hide_names,
    redact,
    tail_lines,
)
from blindspot.spotify import SpotifyError

API_KEY = "vO9otuFLuLWasgeulANu8kZ6UZFdwj2N"
BEARER = "BQC4abcDEFghi_jklMNOpqrSTUvwxYZ0123456789abcdefghijklmnopqrstuvwxyz"


class RedactTests(unittest.TestCase):
    def test_bearer_tokens_are_removed(self):
        result = redact(f"Authorization: Bearer {BEARER}")

        self.assertNotIn(BEARER, result)

    def test_secret_fields_in_json_and_query_strings_are_removed(self):
        result = redact(
            '{"access_token": "BQAsecretvalue123", "refresh_token": "AQDrefresh999"}'
            " http://127.0.0.1:43821/callback?code=AQBxyz123&state=abcDEF456"
        )

        for leaked in (
            "BQAsecretvalue123",
            "AQDrefresh999",
            "AQBxyz123",
            "abcDEF456",
        ):
            self.assertNotIn(leaked, result)

    def test_known_secrets_are_removed_wherever_they_appear(self):
        result = redact(f"key {API_KEY} in a sentence", secrets=[API_KEY])

        self.assertNotIn(API_KEY, result)
        self.assertIn("[redacted]", result)

    def test_very_short_secrets_are_ignored_rather_than_mangling_text(self):
        self.assertEqual(redact("a b c abc", secrets=["abc", "", None]), "a b c abc")

    def test_long_opaque_strings_are_treated_as_tokens(self):
        result = redact(f"value {BEARER} end")

        self.assertNotIn(BEARER, result)

    def test_ordinary_spotify_ids_and_uris_survive(self):
        text = "id=3XZ3OgA5LMn5U2Ifdj9wc4 uri=spotify:track:5pRAIs0GjhZemU5Xc1Co0X"

        self.assertEqual(redact(text), text)

    def test_traceback_source_lines_are_not_mangled(self):
        line = "    token = self.spotify.access_token()"

        self.assertEqual(redact(line), line)

    def test_user_profile_paths_lose_the_user_name(self):
        windows = redact(r'File "C:\Users\jane\AppData\Local\x.py"')
        mac = redact("/Users/jane/Library/Application Support/BlindSpot/x.log")
        linux = redact("/home/jane/.config/blindspot/x.log")

        for result in (windows, mac, linux):
            self.assertNotIn("jane", result)
            self.assertIn("[user]", result)

    def test_install_locations_shrink_to_the_package_relative_path(self):
        result = redact(r'File "C:\miab\BlindSpot\src\blindspot\spotify.py", line 9')

        self.assertNotIn("miab", result)
        self.assertIn(r"blindspot\spotify.py", result)

    def test_email_addresses_are_removed(self):
        self.assertNotIn("sam@example.com", redact("mail sam@example.com now"))

    def test_the_current_account_name_is_removed(self):
        from unittest.mock import patch

        with patch("blindspot.diagnostics.getpass.getuser", return_value="pawel99"):
            result = redact("owner pawel99 opened the file")

        self.assertNotIn("pawel99", result)


class HideNamesTests(unittest.TestCase):
    def test_labelled_names_are_hidden_but_ids_stay(self):
        result = hide_names(
            "Opening kind=album id=3XZ3OgA5LMn5U2Ifdj9wc4 name='A Boy Was Born'"
        )

        self.assertNotIn("Boy", result)
        self.assertIn("3XZ3OgA5LMn5U2Ifdj9wc4", result)

    def test_names_with_apostrophes_are_hidden(self):
        result = hide_names('Deferred queue item id=1 name="Don\'t Stop"')

        self.assertNotIn("Stop", result)

    def test_lookup_failures_hide_both_names(self):
        result = hide_names("lookup failed for \"Don't Stop\" by 'Fleetwood Mac': 500")

        self.assertNotIn("Fleetwood", result)
        self.assertNotIn("Stop", result)
        self.assertIn(": 500", result)

    def test_every_quoted_string_on_a_blindspot_log_line_is_hidden(self):
        # These are the exact shapes found in a real BlindSpot log.
        lines = [
            "2026-09-20 10:00:00,000 INFO blindspot.ui: Displaying 12 children for 'Secret Album'",
            "2026-09-20 10:00:00,000 INFO blindspot.ui: Resumed 'Secret Track' at 3000 ms",
            "2026-09-20 10:00:00,000 INFO blindspot.transcripts: Looking for publisher transcript: show='Secret Show' episode='Secret Episode' feeds=2",
            "2026-09-20 10:00:00,000 INFO blindspot.transcripts: Matched transcript episode 'Secret Episode' in https://example.com/feed",
            "2026-09-20 10:00:00,000 INFO blindspot.ui: Playback started kind=track id=abc name='Secret Track'",
            "2026-09-20 10:00:00,000 INFO blindspot.spotify: Retrying playback on device name='Jane\\'s Laptop' type=Computer",
            "2026-09-20 10:00:00,000 DEBUG blindspot.lastfm: Last.fm tag response tag='secret genre' kind=album page=1",
        ]

        result = hide_names("\n".join(lines))

        self.assertNotIn("Secret", result)
        self.assertNotIn("Laptop", result)
        self.assertNotIn("secret genre", result)
        # The technical parts around the names stay useful to a developer.
        self.assertIn("Displaying 12 children for [hidden]", result)
        self.assertIn("Resumed [hidden] at 3000 ms", result)
        self.assertIn("id=abc", result)
        self.assertIn("kind=album page=1", result)

    def test_names_containing_apostrophes_and_both_quote_kinds_are_fully_hidden(self):
        lines = [
            "2026-09-20 10:00:00,000 INFO blindspot.ui: Displaying 3 children for \"We've Only Just Begun\"",
            "2026-09-20 10:00:00,000 INFO blindspot.ui: Resumed 'Say \"hi\" We\\'ve Only Just Begun' at 5 ms",
        ]

        result = hide_names("\n".join(lines))

        self.assertNotIn("Begun", result)
        self.assertNotIn("Only", result)
        self.assertIn("at 5 ms", result)

    def test_technical_quoted_values_stay_readable(self):
        lines = [
            "2026-09-20 10:00:00,000 DEBUG blindspot.spotify: Spotify request GET /search query_fields=['limit', 'q', 'type']",
            "2026-09-20 10:00:00,000 INFO blindspot.spotify: New music search type=single scanned=100 types={'single': 81, 'album': 16} total=100",
            "2026-09-20 10:00:00,000 INFO blindspot.web_player: Hidden web player created backend=b'wxWebViewEdge'",
        ]

        result = hide_names("\n".join(lines))

        self.assertIn("query_fields=['limit', 'q', 'type']", result)
        self.assertIn("types={'single': 81, 'album': 16}", result)
        self.assertIn("backend=b'wxWebViewEdge'", result)

    def test_lines_from_other_libraries_and_tracebacks_are_left_alone(self):
        lines = [
            "2026-09-20 10:00:00,000 DEBUG libloader.com: Attempting to load COM objects: ('gwspeak.speak',)",
            '  File "blindspot\\spotify.py", line 67, in access_token',
        ]

        result = hide_names("\n".join(lines))

        self.assertEqual(result, "\n".join(lines))

    def test_line_structure_and_trailing_newlines_are_preserved(self):
        text = "2026-09-20 10:00:00,000 INFO blindspot.ui: Resumed 'X' at 1 ms\nplain line\n"

        self.assertEqual(
            hide_names(text),
            "2026-09-20 10:00:00,000 INFO blindspot.ui: Resumed [hidden] at 1 ms\nplain line\n",
        )


class ErrorReportTests(unittest.TestCase):
    def _details(self):
        try:
            raise SpotifyError("limited", status=429, retry_after=600)
        except SpotifyError as error:
            return capture_error(error, "limited", "Finding Song on Spotify")

    def test_capture_keeps_type_status_retry_and_traceback(self):
        details = self._details()

        self.assertEqual(details.error_type, "blindspot.spotify.SpotifyError")
        self.assertEqual(details.status, 429)
        self.assertEqual(details.retry_after, 600)
        self.assertIn("Traceback", details.traceback)
        self.assertEqual(details.task, "Finding Song on Spotify")

    def test_capture_without_an_exception_still_records_the_message(self):
        details = capture_error(None, "Something failed")

        self.assertEqual(details.message, "Something failed")
        self.assertEqual(details.traceback, "")

    def test_report_names_the_failure_and_the_system(self):
        report = error_report(self._details())

        self.assertIn("BlindSpot error details", report)
        self.assertIn("Finding Song on Spotify", report)
        self.assertIn("Spotify status: 429", report)
        self.assertIn("asked to wait: 600 seconds", report)
        self.assertIn(f"BlindSpot: {diagnostics.__version__}", report)
        self.assertIn("Operating system:", report)

    def test_report_is_safe_to_share(self):
        details = ErrorDetails(
            f"failed with key {API_KEY} and Bearer {BEARER}",
            traceback=r'  File "C:\Users\jane\x.py", line 1',
        )

        report = error_report(details, secrets=[API_KEY])

        for leaked in (API_KEY, BEARER, "jane"):
            self.assertNotIn(leaked, report)


class LogTailTests(unittest.TestCase):
    def test_returns_only_the_last_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "blindspot.log"
            path.write_text(
                "\n".join(f"line {number}" for number in range(1000)),
                encoding="utf-8",
            )

            lines = tail_lines(path, count=5)

        self.assertEqual(lines[-1], "line 999")
        self.assertEqual(len(lines), 5)

    def test_a_huge_file_is_read_from_the_end_without_a_partial_first_line(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "blindspot.log"
            path.write_text(
                "\n".join(f"line {number:06d}" for number in range(5000)),
                encoding="utf-8",
            )

            lines = tail_lines(path, count=10_000, max_bytes=1000)

        self.assertTrue(all(line.startswith("line ") and len(line) == 11 for line in lines))
        self.assertEqual(lines[-1], "line 004999")

    def test_a_missing_log_is_an_empty_list(self):
        self.assertEqual(tail_lines(Path("does-not-exist.log")), [])


class DiagnosticReportTests(unittest.TestCase):
    def _report(self, **overrides):
        options = dict(
            settings={
                "logging_level": "Debug",
                "resume_mode": "track",
                "ticketmaster_api_key": API_KEY,
                "global_shortcuts": {"pause": "Ctrl+Alt+P"},
            },
            secrets_configured={"Ticketmaster key": "set", "Last.fm key": "default"},
            connected=True,
            last_error=None,
            log_lines=None,
            logging_level="Debug",
            secrets=[API_KEY],
        )
        options.update(overrides)
        return diagnostic_report(**options)

    def test_only_allow_listed_settings_are_reported(self):
        report = self._report()

        self.assertIn("logging_level: Debug", report)
        self.assertIn("resume_mode: track", report)
        self.assertIn("custom global shortcuts: 1", report)
        self.assertNotIn("ticketmaster_api_key", report)
        self.assertNotIn(API_KEY, report)
        self.assertNotIn("Ctrl+Alt+P", report)

    def test_credentials_are_reported_as_set_or_not_never_as_values(self):
        report = self._report()

        self.assertIn("Ticketmaster key: set", report)
        self.assertIn("Last.fm key: default", report)
        self.assertIn("Spotify connected: yes", report)

    def test_the_log_is_left_out_unless_requested(self):
        self.assertIn("Log: not included.", self._report())

    def test_an_empty_log_with_logging_off_explains_how_to_capture_one(self):
        report = self._report(log_lines=[], logging_level="Off")

        self.assertIn("logging is switched off", report)
        self.assertIn("Preferences", report)

    def test_included_log_lines_hide_names_by_default(self):
        report = self._report(
            log_lines=["Opening kind=album id=abc123 name='Private Playlist'"],
        )

        self.assertIn("names and search terms hidden", report)
        self.assertIn("id=abc123", report)
        self.assertNotIn("Private Playlist", report)

    def test_names_appear_only_when_the_user_opts_in(self):
        report = self._report(
            log_lines=["Opening kind=album id=abc123 name='Private Playlist'"],
            include_names=True,
        )

        self.assertIn("names and search terms included", report)
        self.assertIn("Private Playlist", report)

    def test_secrets_are_removed_even_from_included_log_lines(self):
        report = self._report(
            log_lines=[f"request used {API_KEY} and Bearer {BEARER}"],
            include_names=True,
        )

        self.assertNotIn(API_KEY, report)
        self.assertNotIn(BEARER, report)

    def test_the_last_error_is_summarised_once_without_repeating_the_header(self):
        report = self._report(
            last_error=ErrorDetails("It broke", "Loading chart", "x.Error"),
        )

        self.assertIn("Last error this session:", report)
        self.assertIn("It broke", report)
        self.assertEqual(report.count("Operating system:"), 1)

    def test_no_error_is_stated_plainly(self):
        report = self._report()

        self.assertIn("Last error this session:\n  none", report)


if __name__ == "__main__":
    unittest.main()
