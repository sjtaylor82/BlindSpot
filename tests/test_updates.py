import unittest

from blindspot.updates import Release, newer_than, pick_asset, version_parts


class UpdateVersionTests(unittest.TestCase):
    def test_parses_release_tag(self):
        self.assertEqual(version_parts("v2026.7.0.0"), (2026, 7, 0, 0))

    def test_detects_newer_release(self):
        self.assertTrue(newer_than("2026.7.0.1", "2026.7.0.0"))
        self.assertFalse(newer_than("2026.7.0.0", "2026.7.0.0"))
        self.assertFalse(newer_than("invalid", "2026.7.0.0"))

    def test_selects_platform_asset(self):
        release = Release(
            "2026.7.0.1",
            "https://example.test",
            (
                {"name": "BlindSpot-Windows.zip"},
                {"name": "BlindSpot-macOS.zip"},
            ),
        )
        self.assertEqual(
            pick_asset(release, "win32")["name"],
            "BlindSpot-Windows.zip",
        )
        self.assertEqual(
            pick_asset(release, "darwin")["name"],
            "BlindSpot-macOS.zip",
        )
