import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from blindspot.app import BlindSpotApp


class SingleInstanceTests(unittest.TestCase):
    def test_second_instance_exits_before_initialization(self):
        app = type(
            "App",
            (),
            {"SetAppName": lambda self, name: None},
        )()
        checker = Mock()
        checker.IsAnotherRunning.return_value = True

        with (
            patch("blindspot.app.wx.GetUserId", return_value="user"),
            patch(
                "blindspot.app.wx.SingleInstanceChecker",
                return_value=checker,
            ) as checker_factory,
            patch("blindspot.app.wx.MessageBox") as message_box,
            patch("blindspot.app.PortableStore") as store_factory,
        ):
            initialized = BlindSpotApp.OnInit(app)

        self.assertFalse(initialized)
        checker_factory.assert_called_once_with("BlindSpot-user")
        message_box.assert_called_once()
        store_factory.assert_not_called()
        self.assertIs(app.instance_checker, checker)

    def test_first_instance_opens_main_window(self):
        app = type(
            "App",
            (),
            {"SetAppName": lambda self, name: None},
        )()
        checker = Mock()
        checker.IsAnotherRunning.return_value = False
        store = Mock()
        store.read.return_value = {}
        store.root = Path("data")
        frame = Mock()

        with (
            patch("blindspot.app.wx.GetUserId", return_value="user"),
            patch(
                "blindspot.app.wx.SingleInstanceChecker",
                return_value=checker,
            ),
            patch("blindspot.app.PortableStore", return_value=store),
            patch("blindspot.app.configure_logging"),
            patch("blindspot.app.SpotifyClient"),
            patch("blindspot.app.MainFrame", return_value=frame),
        ):
            initialized = BlindSpotApp.OnInit(app)

        self.assertTrue(initialized)
        frame.Show.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
