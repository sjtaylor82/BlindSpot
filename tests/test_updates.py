import unittest
from pathlib import Path

from blindspot.updates import (
    Release,
    newer_than,
    pick_asset,
    supports_automatic_update,
    version_parts,
)


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

    def test_automatic_update_is_only_available_in_packaged_windows_build(self):
        release = Release(
            "2026.7.0.1",
            "https://example.test",
            ({"name": "BlindSpot-Windows.zip"},),
        )
        self.assertTrue(supports_automatic_update(release, "win32", True))
        self.assertFalse(supports_automatic_update(release, "win32", False))
        self.assertFalse(supports_automatic_update(release, "darwin", True))

    def test_automatic_update_requires_windows_asset(self):
        release = Release(
            "2026.7.0.1",
            "https://example.test",
            ({"name": "BlindSpot-macOS.zip"},),
        )
        self.assertFalse(supports_automatic_update(release, "win32", True))


class PortableUpdaterTests(unittest.TestCase):
    def test_backup_is_completed_before_installed_files_are_removed(self):
        script = (
            Path(__file__).resolve().parents[1] / "portable_updater.ps1"
        ).read_text(encoding="utf-8")

        backup_completed = script.index(
            'Write-UpdateLog "Current application backup completed."'
        )
        installation_started = script.index("$installationStarted = $true")
        installed_files_removed = script.index(
            "Remove-Item -Recurse -Force",
            installation_started,
        )

        self.assertLess(backup_completed, installation_started)
        self.assertLess(installation_started, installed_files_removed)
        self.assertIn("$preserveStaging = $true", script)
