import unittest
from unittest.mock import patch

from blindspot import keymap


class KeyMapTests(unittest.TestCase):
    def test_platform_defaults_differ_for_item_actions_and_lyrics(self):
        windows = keymap.KeyMap(platform="win32")
        mac = keymap.KeyMap(platform="darwin")

        self.assertEqual(windows.bindings("item_actions"), ("Shift+F10",))
        self.assertEqual(mac.bindings("item_actions"), ("Option+M",))
        self.assertEqual(
            mac.bindings("previous_lyric_line"),
            ("Option+Command+Up",),
        )

    def test_assignment_replaces_duplicate_in_same_context_only(self):
        value = keymap.KeyMap(platform="win32")

        value.set_binding("seek_forward", "F5")

        self.assertEqual(value.bindings("seek_forward"), ("F5",))
        self.assertEqual(value.bindings("seek_backward"), ())
        self.assertEqual(
            value.bindings("previous_lyric_line"),
            ("Control+Up",),
        )

    def test_clear_disables_default_and_round_trips(self):
        value = keymap.KeyMap(platform="win32")
        value.clear("pause_resume")
        saved = value.to_json({"os"})
        loaded = keymap.KeyMap(saved, platform="win32")

        self.assertEqual(loaded.bindings("pause_resume"), ())
        self.assertTrue(
            loaded.disabled_default("F8", ("Main",))
        )
        self.assertEqual(keymap.warnings_seen(saved), {"os"})

    def test_restore_defaults_removes_context_overrides(self):
        value = keymap.KeyMap(platform="darwin")
        value.set_binding("speak_current", "Command+I")
        value.clear("show_lyrics")

        value.restore_defaults("Main")

        self.assertEqual(
            value.bindings("speak_current"),
            ("Control+Shift+I",),
        )
        self.assertEqual(value.bindings("show_lyrics"), ("Control+Y",))

    def test_invalid_saved_entries_are_ignored(self):
        value = keymap.normalized_keymap(
            {
                "bindings": {
                    "show_lyrics": ["ctrl+y", "bad+modifier+y", "Ctrl+Y"],
                    "unknown": ["F1"],
                    "seek_forward": "F6",
                }
            }
        )

        self.assertEqual(value, {"show_lyrics": ["Control+Y"]})

    def test_conflict_warnings_are_classified(self):
        self.assertEqual(
            keymap.conflict_warning("Control+F4", "darwin"),
            "os",
        )
        self.assertEqual(
            keymap.conflict_warning("Control+Option+M", "darwin"),
            "voiceover",
        )
        self.assertEqual(
            keymap.conflict_warning("Up", "win32"),
            "navigation",
        )
        self.assertEqual(
            keymap.conflict_warning("A", "win32"),
            "typing",
        )
        self.assertEqual(
            keymap.conflict_warning("Period", "darwin"),
            "typing",
        )
        self.assertIsNone(
            keymap.conflict_warning("Option+Command+Up", "darwin")
        )

    def test_mac_event_distinguishes_command_from_physical_control(self):
        event = type(
            "Event",
            (),
            {
                "GetKeyCode": lambda self: ord("M"),
                "GetModifiers": lambda self: 5,
                "AltDown": lambda self: True,
                "ShiftDown": lambda self: False,
            },
        )()

        with (
            patch("blindspot.keymap.wx.MOD_CONTROL", 1),
            patch("blindspot.keymap.wx.MOD_RAW_CONTROL", 2),
            patch("blindspot.keymap.wx.MOD_ALT", 4),
        ):
            self.assertEqual(
                keymap.chord_from_event(event, "darwin"),
                "Option+Command+M",
            )


if __name__ == "__main__":
    unittest.main()
