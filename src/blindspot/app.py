from __future__ import annotations

import sys

import wx

from .demo import DemoSpotifyClient
from .logging_setup import configure_logging
from .portable import PortableStore
from .spotify import SpotifyClient
from .ui import MainFrame


class BlindSpotApp(wx.App):
    def OnInit(self) -> bool:
        self.SetAppName("BlindSpot")
        store = PortableStore()
        settings = store.read("settings.json", {}) or {}
        configure_logging(
            store.root / "blindspot.log",
            settings.get("logging_level", "Off"),
        )
        spotify = (
            DemoSpotifyClient()
            if "--demo" in sys.argv
            else SpotifyClient(store)
        )
        frame = MainFrame(spotify, store)
        frame.Show()
        return True


def main() -> None:
    app = BlindSpotApp(False)
    app.MainLoop()
