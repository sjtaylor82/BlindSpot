from __future__ import annotations

import wx

from . import messages as msg
from .logging_setup import configure_logging
from .portable import PortableStore
from .spotify import SpotifyClient
from .ui import MainFrame


class BlindSpotApp(wx.App):
    def OnInit(self) -> bool:
        self.SetAppName("BlindSpot")
        self.instance_checker = wx.SingleInstanceChecker(
            f"BlindSpot-{wx.GetUserId()}"
        )
        if self.instance_checker.IsAnotherRunning():
            wx.MessageBox(
                msg.ALREADY_RUNNING,
                "BlindSpot",
                wx.OK | wx.ICON_INFORMATION,
            )
            return False
        store = PortableStore()
        settings = store.read("settings.json", {}) or {}
        configure_logging(
            store.root / "blindspot.log",
            settings.get("logging_level", "Off"),
        )
        spotify = SpotifyClient(store)
        frame = MainFrame(spotify, store)
        frame.Show()
        return True


def main() -> None:
    app = BlindSpotApp(False)
    app.MainLoop()
