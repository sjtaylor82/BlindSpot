import unittest

from blindspot.ui import (
    MainFrame,
    playback_state_for_resume,
    resume_mode_from_settings,
)


class PlaybackMemorySettingsTests(unittest.TestCase):
    def test_legacy_enabled_setting_migrates_to_track_and_position(self):
        self.assertEqual(
            resume_mode_from_settings({"resume_last_track": True}),
            "track_and_position",
        )

    def test_explicit_mode_takes_precedence_over_legacy_setting(self):
        self.assertEqual(
            resume_mode_from_settings(
                {"resume_mode": "track", "resume_last_track": True}
            ),
            "track",
        )

    def test_track_only_storage_resets_position_without_mutating_state(self):
        state = {"progress_ms": 42_000, "item": {"id": "track"}}

        stored = playback_state_for_resume(state, "track")

        self.assertEqual(stored["progress_ms"], 0)
        self.assertEqual(state["progress_ms"], 42_000)


class UpdatePromptFocusTests(unittest.TestCase):
    class FocusTarget:
        def __init__(self, shown=True, enabled=True):
            self.shown = shown
            self.enabled = enabled
            self.focused = False

        def IsShown(self):
            return self.shown

        def IsEnabled(self):
            return self.enabled

        def SetFocus(self):
            self.focused = True

    class Search:
        def __init__(self):
            self.focused = False

        def focus_query(self):
            self.focused = True

    def test_restores_control_that_had_focus_before_update_prompt(self):
        target = self.FocusTarget()
        frame = type("Frame", (), {"search": self.Search()})()

        MainFrame._restore_focus_after_update_prompt(frame, target)

        self.assertTrue(target.focused)
        self.assertFalse(frame.search.focused)

    def test_falls_back_to_search_when_previous_control_is_unavailable(self):
        target = self.FocusTarget(shown=False)
        frame = type("Frame", (), {"search": self.Search()})()

        MainFrame._restore_focus_after_update_prompt(frame, target)

        self.assertFalse(target.focused)
        self.assertTrue(frame.search.focused)


if __name__ == "__main__":
    unittest.main()
