import re
import unittest
from pathlib import Path

from blindspot import __version__


ROOT = Path(__file__).resolve().parent.parent


class ReleaseMetadataTests(unittest.TestCase):
    def test_changelog_is_included_in_portable_builds(self):
        spec = (ROOT / "BlindSpot.spec").read_text(encoding="utf-8")

        self.assertIn('(\"CHANGELOG.txt\", \".\")', spec)
        self.assertIn(
            'Path(DISTPATH) / "BlindSpot" / "CHANGELOG.txt"',
            spec,
        )

    def test_version_is_synced_with_package_and_changelog(self):
        project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        changelog = (ROOT / "CHANGELOG.txt").read_text(encoding="utf-8")
        project_version = re.search(
            r'(?m)^version = "([^"]+)"$',
            project,
        )
        changelog_version = re.search(
            r"(?m)^(20[0-9.]+) - ",
            changelog,
        )

        self.assertIsNotNone(project_version)
        self.assertIsNotNone(changelog_version)
        self.assertEqual(project_version.group(1), __version__)
        self.assertEqual(changelog_version.group(1), __version__)


if __name__ == "__main__":
    unittest.main()
