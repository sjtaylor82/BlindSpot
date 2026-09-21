import struct
import tempfile
import unittest
from pathlib import Path

from blindspot import i18n
from blindspot import messages as msg

PLURAL_FORMS = (
    "nplurals=3; plural=(n==1 ? 0 : n%10>=2 && n%10<=4 && "
    "(n%100<10 || n%100>=20) ? 1 : 2);"
)
NATIVE_KEY = (
    "The name of this language, written in that language\x04English"
)


def write_mo(path: Path, entries: dict[str, str]) -> None:
    """Write a minimal GNU .mo file (the format gettext reads)."""
    header = f"Content-Type: text/plain; charset=utf-8\nPlural-Forms: {PLURAL_FORMS}\n"
    entries = {"": header, **entries}
    keys = sorted(entries)
    ids = strs = b""
    offsets = []
    for key in keys:
        key_bytes = key.encode("utf-8")
        value_bytes = entries[key].encode("utf-8")
        offsets.append((len(ids), len(key_bytes), len(strs), len(value_bytes)))
        ids += key_bytes + b"\0"
        strs += value_bytes + b"\0"
    key_start = 7 * 4 + 16 * len(keys)
    value_start = key_start + len(ids)
    table = []
    for id_offset, id_length, str_offset, str_length in offsets:
        table += [id_length, id_offset + key_start]
    for id_offset, id_length, str_offset, str_length in offsets:
        table += [str_length, str_offset + value_start]
    data = struct.pack(
        "Iiiiiii",
        0x950412DE,
        0,
        len(keys),
        7 * 4,
        7 * 4 + len(keys) * 8,
        0,
        0,
    )
    data += struct.pack(f"{len(table)}i", *table) + ids + strs
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


class LocaleTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        i18n.use_locale_directory(self.root)
        self.addCleanup(self.reset)

    def reset(self) -> None:
        i18n.use_locale_directory(None)
        i18n.set_language("en")
        self.directory.cleanup()

    def add_polish(self, **extra: str) -> None:
        entries = {
            "Muted.": "Wyciszono.",
            "{count} item.\0{count} items.": (
                "{count} element.\0{count} elementy.\0{count} elementów."
            ),
            "Queue\x04Queue": "Kolejka",
            NATIVE_KEY: "Polski",
        }
        entries.update(extra)
        write_mo(self.root / "pl" / "LC_MESSAGES" / "blindspot.mo", entries)


class NormaliseTests(unittest.TestCase):
    def test_reduces_region_and_encoding(self) -> None:
        for raw in ("pl", "pl_PL", "pl-PL", "pl_PL.UTF-8", "PL", "pl@euro"):
            self.assertEqual("pl", i18n.normalise_language(raw), raw)

    def test_empty_is_english(self) -> None:
        self.assertEqual("en", i18n.normalise_language(""))
        self.assertEqual("en", i18n.normalise_language(None))


class TranslationTests(LocaleTestCase):
    def test_english_is_the_default_and_passes_text_through(self) -> None:
        self.assertEqual("en", i18n.set_language("en"))
        self.assertEqual("Muted.", i18n.tr("Muted."))
        self.assertEqual("", i18n.tr(""))
        self.assertEqual("1 item.", i18n.ntr("{0} item.", "{0} items.", 1).format(1))

    def test_translates_when_a_catalogue_exists(self) -> None:
        self.add_polish()
        self.assertEqual("pl", i18n.set_language("pl_PL"))
        self.assertEqual("Wyciszono.", i18n.tr("Muted."))
        self.assertEqual("pl", i18n.current_language())

    def test_missing_strings_fall_back_to_english(self) -> None:
        self.add_polish()
        i18n.set_language("pl")
        self.assertEqual("Unmuted.", i18n.tr("Unmuted."))

    def test_polish_plural_forms(self) -> None:
        self.add_polish()
        i18n.set_language("pl")
        expected = {
            1: "1 element.",
            2: "2 elementy.",
            5: "5 elementów.",
            12: "12 elementów.",
            22: "22 elementy.",
        }
        for count, text in expected.items():
            with self.subTest(count=count):
                self.assertEqual(
                    text,
                    i18n.ntr("{count} item.", "{count} items.", count).format(
                        count=count
                    ),
                )

    def test_context_separates_identical_english(self) -> None:
        self.add_polish()
        i18n.set_language("pl")
        self.assertEqual("Kolejka", i18n.ptr("Queue", "Queue"))
        self.assertEqual("Queue", i18n.ptr("Other", "Queue"))

    def test_unknown_language_falls_back_to_english(self) -> None:
        self.assertEqual("en", i18n.set_language("xx"))
        self.assertEqual("Muted.", i18n.tr("Muted."))

    def test_corrupt_catalogue_falls_back_to_english(self) -> None:
        path = self.root / "pl" / "LC_MESSAGES" / "blindspot.mo"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"not a catalogue")
        self.assertEqual("en", i18n.set_language("pl"))

    def test_switching_back_to_english_restores_text(self) -> None:
        self.add_polish()
        i18n.set_language("pl")
        i18n.set_language("en")
        self.assertEqual("Muted.", i18n.tr("Muted."))


class DefaultLanguageTests(LocaleTestCase):
    def test_new_installations_follow_the_system_language(self) -> None:
        self.assertEqual(i18n.SYSTEM_LANGUAGE, i18n.DEFAULT_LANGUAGE_SETTING)

    def test_system_language_picks_an_installed_translation(self) -> None:
        self.add_polish()
        original = i18n.detect_system_language
        self.addCleanup(setattr, i18n, "detect_system_language", original)
        i18n.detect_system_language = lambda: "pl"
        self.assertEqual("pl", i18n.set_language(i18n.SYSTEM_LANGUAGE))
        self.assertEqual("Wyciszono.", i18n.tr("Muted."))

    def test_system_language_without_a_translation_is_english(self) -> None:
        self.add_polish()
        original = i18n.detect_system_language
        self.addCleanup(setattr, i18n, "detect_system_language", original)
        i18n.detect_system_language = lambda: "de"
        self.assertEqual("en", i18n.set_language(i18n.SYSTEM_LANGUAGE))
        self.assertEqual("Muted.", i18n.tr("Muted."))


class AvailableLanguageTests(LocaleTestCase):
    def test_lists_english_then_installed_languages_by_native_name(self) -> None:
        self.add_polish()
        self.assertEqual(
            [("en", "English"), ("pl", "Polski")], i18n.available_languages()
        )

    def test_language_without_a_name_is_listed_by_code(self) -> None:
        write_mo(self.root / "de" / "LC_MESSAGES" / "blindspot.mo", {})
        self.assertEqual(
            [("en", "English"), ("de", "de")], i18n.available_languages()
        )

    def test_only_english_when_no_catalogues_exist(self) -> None:
        self.assertEqual([("en", "English")], i18n.available_languages())

    def test_ignores_folders_without_a_compiled_catalogue(self) -> None:
        (self.root / "fr" / "LC_MESSAGES").mkdir(parents=True)
        self.assertEqual([("en", "English")], i18n.available_languages())


class MessagesTests(LocaleTestCase):
    def test_constants_are_retranslated_and_restored(self) -> None:
        self.add_polish()
        self.assertEqual("Muted.", msg.MUTED)
        i18n.set_language("pl")
        self.assertEqual("Wyciszono.", msg.MUTED)
        i18n.set_language("en")
        self.assertEqual("Muted.", msg.MUTED)

    def test_functions_use_the_active_language(self) -> None:
        self.add_polish()
        i18n.set_language("pl")
        self.assertEqual("5 elementów.", msg.item_count(5))
        self.assertEqual("2 elementy.", msg.item_count(2))

    def test_english_plurals(self) -> None:
        self.assertEqual("1 item.", msg.item_count(1))
        self.assertEqual("3 items.", msg.item_count(3))
        self.assertEqual("1 result.", msg.result_count(1, "x"))
        self.assertEqual("2 results.", msg.result_count(2, "x"))
        self.assertEqual("No results for x.", msg.result_count(0, "x"))
        self.assertEqual(
            "Queued 1 track.", msg.queued_count(1)
        )
        self.assertEqual("Queued 4 tracks.", msg.queued_count(4))


if __name__ == "__main__":
    unittest.main()
