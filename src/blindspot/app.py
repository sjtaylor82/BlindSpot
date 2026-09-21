from __future__ import annotations

from pathlib import Path

import wx

from . import i18n
from . import messages as msg
from .logging_setup import configure_logging
from .portable import PortableStore, resource_directory
from .spotify import SpotifyClient
from .ui import MainFrame


def activate_wx_locale(code: str) -> wx.Locale | None:
    """Translate wxWidgets' own text (stock buttons) into the app language.

    The returned object must stay alive for the translation to remain active.
    """
    if code == i18n.DEFAULT_LANGUAGE:
        return None
    info = wx.Locale.FindLanguageInfo(code)
    if info is None:
        return None
    for folder in (
        Path(wx.__file__).resolve().parent / "locale",
        resource_directory() / "wx" / "locale",
    ):
        wx.Locale.AddCatalogLookupPathPrefix(str(folder))
    locale = wx.Locale()
    if not locale.Init(info.Language, wx.LOCALE_DONT_LOAD_DEFAULT):
        return None
    locale.AddCatalog("wxstd")
    return locale


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
        language = i18n.set_language(
            settings.get("language") or i18n.DEFAULT_LANGUAGE_SETTING
        )
        self.wx_locale = activate_wx_locale(language)
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
