import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from blindspot import portable


class PortablePathTests(unittest.TestCase):
    def test_macos_bundle_uses_enclosing_folder_as_portable_root(self):
        executable = (
            Path("/Users/sam/BlindSpot/BlindSpot.app/Contents/MacOS/BlindSpot")
        )
        with (
            patch.object(portable.sys, "frozen", True, create=True),
            patch.object(portable.sys, "platform", "darwin"),
            patch.object(portable.sys, "executable", str(executable)),
        ):
            self.assertEqual(
                portable.application_directory(),
                executable.resolve().parents[3],
            )

    def test_frozen_resources_use_pyinstaller_resource_directory(self):
        with (
            patch.object(portable.sys, "frozen", True, create=True),
            patch.object(portable.sys, "_MEIPASS", "/bundle/resources", create=True),
        ):
            self.assertEqual(
                portable.resource_directory(),
                Path("/bundle/resources").resolve(),
            )

    def test_macos_store_falls_back_when_sidecar_data_is_not_writable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            portable_parent = root / "portable"
            portable_parent.mkdir()
            (portable_parent / "data").write_text("blocked", encoding="utf-8")
            home = root / "home"
            with (
                patch.object(portable.sys, "platform", "darwin"),
                patch.object(portable, "application_directory", return_value=portable_parent),
                patch.object(Path, "home", return_value=home),
            ):
                store = portable.PortableStore()

            self.assertEqual(
                store.root,
                home / "Library" / "Application Support" / "BlindSpot",
            )
            self.assertTrue(store.root.is_dir())


if __name__ == "__main__":
    unittest.main()
