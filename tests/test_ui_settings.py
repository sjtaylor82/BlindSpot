import unittest

from blindspot.ui import playback_state_for_resume, resume_mode_from_settings


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


if __name__ == "__main__":
    unittest.main()
