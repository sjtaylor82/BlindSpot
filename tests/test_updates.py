import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from blindspot import updates
from blindspot.updates import (
    Release,
    download_and_install,
    newer_than,
    pick_asset,
    supports_automatic_update,
    supports_managed_download,
    version_parts,
)


class UpdateVersionTests(unittest.TestCase):
    def test_windows_update_download_uses_bundled_certificate_store(self):
        release = Release(
            "2026.9.1",
            "https://example.test/release",
            (
                {
                    "name": "BlindSpot-Windows.zip",
                    "browser_download_url": "https://example.test/app.zip",
                },
            ),
        )
        response = Mock()
        response.headers = {"Content-Length": "6"}
        response.read.side_effect = [b"abc", b"def", b""]
        response_context = Mock()
        response_context.__enter__ = Mock(return_value=response)
        response_context.__exit__ = Mock(return_value=False)
        progress = []

        with tempfile.TemporaryDirectory() as directory, patch(
            "blindspot.updates.supports_managed_download",
            return_value=True,
        ), patch(
            "blindspot.updates.tempfile.gettempdir",
            return_value=directory,
        ), patch(
            "blindspot.updates.urllib.request.urlopen",
            return_value=response_context,
        ) as urlopen, patch(
            "blindspot.updates.schedule_windows_replacement",
        ) as schedule:
            self.assertTrue(download_and_install(release, progress.append))

        self.assertIs(urlopen.call_args.kwargs["context"], updates.TLS_CONTEXT)
        self.assertEqual(progress[-1], 100)
        schedule.assert_called_once()

    def test_packaged_macos_can_download_matching_update(self):
        release = Release(
            "2026.9.1",
            "https://example.test/release",
            (
                {
                    "name": "BlindSpot-macOS.zip",
                    "browser_download_url": "https://example.test/app.zip",
                },
            ),
        )
        response = Mock()
        response.headers = {"Content-Length": "3"}
        response.read.side_effect = [b"zip", b""]
        response_context = Mock()
        response_context.__enter__ = Mock(return_value=response)
        response_context.__exit__ = Mock(return_value=False)

        with tempfile.TemporaryDirectory() as directory, patch(
            "blindspot.updates.sys.platform",
            "darwin",
        ), patch(
            "blindspot.updates.supports_managed_download",
            return_value=True,
        ), patch(
            "blindspot.updates.Path.home",
            return_value=Path(directory),
        ), patch(
            "blindspot.updates.urllib.request.urlopen",
            return_value=response_context,
        ), patch("blindspot.updates.subprocess.run") as reveal:
            self.assertTrue(download_and_install(release))
            destination = (
                Path(directory)
                / "Downloads"
                / "BlindSpot-macOS-2026.9.1.zip"
            )
            self.assertEqual(destination.read_bytes(), b"zip")

        reveal.assert_called_once_with(
            ["open", "-R", str(destination)],
            check=False,
        )

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

    def test_managed_download_supports_packaged_windows_and_macos(self):
        release = Release(
            "2026.9.1",
            "https://example.test",
            (
                {"name": "BlindSpot-Windows.zip"},
                {"name": "BlindSpot-macOS.zip"},
            ),
        )
        self.assertTrue(supports_managed_download(release, "win32", True))
        self.assertTrue(supports_managed_download(release, "darwin", True))
        self.assertFalse(supports_managed_download(release, "darwin", False))

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
