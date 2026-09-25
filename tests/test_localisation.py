"""Checks on the translation catalogues that ship with BlindSpot.

These need Babel (a build-time tool, installed in CI); they are skipped when
it is missing so the rest of the suite still runs anywhere.
"""

import importlib.util
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from blindspot import i18n
from blindspot import messages as msg
from blindspot.applemusic import loaded_label

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "i18n.py"

try:
    import babel  # noqa: F401
except ImportError:  # pragma: no cover
    babel = None


def load_tool():
    spec = importlib.util.spec_from_file_location("i18n_tool", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(babel, "Babel is not installed")
class ShippedCatalogueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tool = load_tool()
        cls.directory = tempfile.TemporaryDirectory()
        cls.output = Path(cls.directory.name)
        cls.tool.compile_catalogues(quiet=True, output=cls.output)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.directory.cleanup()

    def setUp(self) -> None:
        i18n.use_locale_directory(self.output)
        self.addCleanup(self.reset)

    def reset(self) -> None:
        i18n.use_locale_directory(None)
        i18n.set_language("en")

    def test_template_matches_the_source(self) -> None:
        from babel.messages.pofile import read_po

        with self.tool.POT.open("rb") as handle:
            recorded = {(m.id, m.context) for m in read_po(handle) if m.id}
        current = {(m.id, m.context) for m in self.tool.build_template() if m.id}
        self.assertEqual(
            set(),
            current ^ recorded,
            "locale/blindspot.pot is stale; run scripts/i18n.py update",
        )

    def test_every_translation_keeps_placeholders_and_mnemonics(self) -> None:
        from babel.messages.pofile import read_po

        for path in self.tool.catalogue_files():
            with self.subTest(language=path.parent.parent.name):
                with path.open("rb") as handle:
                    catalog = read_po(handle, locale=path.parent.parent.name)
                self.assertEqual([], self.tool.problems(catalog))

    def test_every_language_lists_its_own_name(self) -> None:
        names = dict(i18n.available_languages())
        self.assertEqual("English", names["en"])
        for code, name in names.items():
            if code != "en":
                self.assertNotEqual(code, name, "missing native name entry")

    def test_polish_is_listed_and_loads(self) -> None:
        self.assertIn(("pl", "Polski"), i18n.available_languages())
        self.assertEqual("pl", i18n.set_language("pl"))
        self.assertEqual("Wyciszono.", msg.MUTED)
        self.assertEqual("Kolejka", i18n.tr("Queue"))

    def test_polish_plurals_follow_polish_rules(self) -> None:
        i18n.set_language("pl")
        self.assertEqual("1 element.", msg.item_count(1))
        self.assertEqual("2 elementy.", msg.item_count(2))
        self.assertEqual("5 elementów.", msg.item_count(5))
        self.assertEqual("22 elementy.", msg.item_count(22))
        self.assertEqual("12 elementów.", msg.item_count(12))
        self.assertEqual("3 minuty 5 sekund", msg.minutes_seconds(3, 5))

    def test_polish_dates_use_polish_words(self) -> None:
        i18n.set_language("pl")
        self.assertEqual("5 marca 2026", msg.long_date(date(2026, 3, 5)))
        from blindspot.spotify import played_at_label

        when = datetime(2026, 3, 5, 0, 5, tzinfo=timezone.utc)
        label = played_at_label(when.isoformat())
        self.assertTrue(label.startswith("odtworzono "), label)
        self.assertNotIn("PM", label)

    def test_polish_clock_keeps_the_hour_at_midnight(self) -> None:
        i18n.set_language("pl")
        self.assertEqual("0:05", msg.clock_time(datetime(2026, 3, 5, 0, 5)))
        self.assertEqual("18:05", msg.clock_time(datetime(2026, 3, 5, 18, 5)))
        self.assertEqual("6:05", msg.clock_time(datetime(2026, 3, 5, 6, 5)))

    def test_apple_music_timestamp_uses_polish_date_and_time(self) -> None:
        i18n.set_language("pl")
        label = loaded_label(1_790_000_000.0)
        self.assertNotIn(" at ", label)
        self.assertNotIn("AM", label)
        self.assertNotIn("PM", label)

    def test_english_clock_keeps_the_hour_at_midnight(self) -> None:
        self.assertEqual("12:05 AM", msg.clock_time(datetime(2026, 3, 5, 0, 5)))
        self.assertEqual("6:05 PM", msg.clock_time(datetime(2026, 3, 5, 18, 5)))

    def test_every_message_function_formats_in_polish(self) -> None:
        """A wrong placeholder in a translation would raise at run time."""
        i18n.set_language("pl")
        samples = [
            msg.exported_items(3, "a.txt", True),
            msg.result_count(4, "x"),
            msg.named_item_count("Name", 2),
            msg.audiobook_resume_permission(2),
            msg.saved_podcasts(1, 5),
            msg.update_available("1.0", "Do it"),
            msg.about("1.0"),
            msg.sleep_minutes(1),
            msg.queued_count(5),
            msg.playlist_information("me", 3, True, False, "d"),
            msg.spotify_rate_limited(None),
            msg.spotify_rate_limited(30),
            msg.spotify_rate_limited(120),
            msg.spotify_rate_limited(7200),
            msg.matching_items(2, 9),
            msg.finding_tag_results("rock", "album"),
        ]
        for text in samples:
            self.assertNotIn("{", text)
            self.assertTrue(text)

    def test_english_is_unchanged_when_switching_back(self) -> None:
        i18n.set_language("pl")
        i18n.set_language("en")
        self.assertEqual("Muted.", msg.MUTED)
        self.assertEqual("3 items.", msg.item_count(3))


if __name__ == "__main__":
    unittest.main()
