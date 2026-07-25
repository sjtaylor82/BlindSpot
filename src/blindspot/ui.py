from __future__ import annotations

import logging
import sys
import threading
import time
import uuid
import webbrowser
from collections.abc import Callable

import wx
from accessible_output2.outputs.auto import Auto

from . import __version__
from .auth_callback import CallbackServer
from .logging_setup import LOG_LEVELS, configure_logging
from .lyrics import LRCLibClient, Lyrics, LyricsUnavailable
from .models import ItemKind, SpotifyItem, ViewState
from .navigation import NavigationHistory
from .portable import PortableStore, resource_directory
from .spotify import (
    REDIRECT_URI,
    PlaylistContentsUnavailable,
    RecentlyPlayedPermissionRequired,
    SpotifyClient,
    SpotifyError,
)
from .updates import download_and_install, latest_release, newer_than
from .web_player import WebPlaybackController

logger = logging.getLogger("blindspot.ui")

SEARCH_LABELS = ["Songs", "Albums", "Artists", "Playlists", "Podcasts", "All"]
SEARCH_TYPES = ["track", "album", "artist", "playlist", "show", "all"]
DEVELOPER_DASHBOARD_URL = "https://developer.spotify.com/dashboard"
GLOBAL_HOTKEY_SEEK_BACKWARD = 3101
GLOBAL_HOTKEY_SEEK_FORWARD = 3102
GLOBAL_HOTKEY_VOLUME_DOWN = 3103
GLOBAL_HOTKEY_VOLUME_UP = 3104
RESUME_MODES = ("none", "track", "track_and_position")
RESUME_MODE_LABELS = (
    "Do not remember the last played track",
    "Remember the last played track",
    "Remember the last played track and position",
)


def resume_mode_from_settings(settings: dict) -> str:
    mode = str(settings.get("resume_mode") or "")
    if mode in RESUME_MODES:
        return mode
    return "track_and_position" if settings.get("resume_last_track") else "none"


def playback_state_for_resume(state: dict, mode: str) -> dict:
    stored = dict(state)
    if mode == "track":
        stored["progress_ms"] = 0
    return stored


def physical_control_down(event: wx.KeyEvent) -> bool:
    return (
        event.RawControlDown()
        if sys.platform == "darwin"
        else event.ControlDown()
    )


class SetupDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, client_id: str = "") -> None:
        super().__init__(
            parent,
            title="BlindSpot setup",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        outer = wx.BoxSizer(wx.VERTICAL)
        welcome = wx.StaticText(
            self,
            label=(
                "Welcome to BlindSpot\n"
                "This app requires a developer account. This is a one-time setup."
            ),
        )
        instructions_label = wx.StaticText(
            self,
            label="Setup instructions",
        )
        instructions = wx.TextCtrl(
            self,
            value=(
                "1. Open the Spotify Developer Dashboard and create an app.\n"
                "2. Use BlindSpot Personal as its name. Select both Web API "
                "and Web Playback SDK.\n"
                "3. Add this redirect URI: "
                "http://127.0.0.1:43821/callback\n"
                "4. Open the app's settings, copy its Client ID, and paste it here.\n"
                "Do not copy or share the Client Secret."
            ),
            style=wx.TE_MULTILINE | wx.TE_READONLY,
            size=(-1, 125),
        )
        self.open_dashboard = wx.Button(
            self, label="&Open Spotify Developer Dashboard"
        )
        redirect_label = wx.StaticText(self, label="Redirect URI")
        self.redirect = wx.TextCtrl(self, value=REDIRECT_URI, style=wx.TE_READONLY)
        client_label = wx.StaticText(self, label="Spotify Client ID")
        self.client_id = wx.TextCtrl(self, value=client_id)
        buttons = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        connect_button = self.FindWindow(wx.ID_OK)
        if isinstance(connect_button, wx.Button):
            connect_button.SetLabel("&Connect to Spotify")

        outer.Add(welcome, 0, wx.EXPAND | wx.ALL, 12)
        outer.Add(instructions_label, 0, wx.LEFT | wx.RIGHT, 12)
        outer.Add(instructions, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        outer.Add(self.open_dashboard, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        outer.Add(redirect_label, 0, wx.LEFT | wx.RIGHT, 12)
        outer.Add(self.redirect, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        outer.Add(client_label, 0, wx.LEFT | wx.RIGHT, 12)
        outer.Add(self.client_id, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        if buttons:
            outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizerAndFit(outer)
        self.SetMinSize((600, self.GetSize().height))
        self.open_dashboard.Bind(
            wx.EVT_BUTTON,
            lambda event: webbrowser.open(DEVELOPER_DASHBOARD_URL),
        )
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)

    def on_ok(self, event: wx.CommandEvent) -> None:
        if not self.client_id.GetValue().strip():
            wx.MessageBox(
                "Paste the Client ID from your Spotify application.",
                "BlindSpot setup",
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            self.client_id.SetFocus()
            return
        event.Skip()

    def get_client_id(self) -> str:
        return self.client_id.GetValue().strip()


class PreferencesDialog(wx.Dialog):
    def __init__(
        self,
        parent: wx.Window,
        logging_level: str,
        announce_track_changes: bool,
        resume_mode: str,
        global_seek_volume_hotkeys: bool,
    ) -> None:
        super().__init__(parent, title="BlindSpot preferences")
        outer = wx.BoxSizer(wx.VERTICAL)
        self.announce_track_changes = wx.CheckBox(
            self,
            label="Speak track name when playback changes",
        )
        self.announce_track_changes.SetValue(announce_track_changes)
        outer.Add(
            self.announce_track_changes,
            0,
            wx.ALL,
            12,
        )
        self.resume_mode = wx.RadioBox(
            self,
            label="Startup playback memory",
            choices=RESUME_MODE_LABELS,
            majorDimension=1,
            style=wx.RA_SPECIFY_ROWS,
        )
        self.resume_mode.SetSelection(
            RESUME_MODES.index(resume_mode)
            if resume_mode in RESUME_MODES
            else 0
        )
        outer.Add(
            self.resume_mode,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        self.global_seek_volume_hotkeys = wx.CheckBox(
            self,
            label="Enable global seek and volume shortcuts",
        )
        self.global_seek_volume_hotkeys.SetValue(global_seek_volume_hotkeys)
        outer.Add(
            self.global_seek_volume_hotkeys,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        self.logging_level = wx.RadioBox(
            self,
            label="Logging level",
            choices=list(LOG_LEVELS),
            majorDimension=1,
            style=wx.RA_SPECIFY_ROWS,
        )
        self.logging_level.SetStringSelection(
            logging_level if logging_level in LOG_LEVELS else "Off"
        )
        outer.Add(
            self.logging_level,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        buttons = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        if buttons:
            outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizerAndFit(outer)
        self.announce_track_changes.SetFocus()

    def get_logging_level(self) -> str:
        return self.logging_level.GetStringSelection()

    def get_announce_track_changes(self) -> bool:
        return self.announce_track_changes.GetValue()

    def get_resume_mode(self) -> str:
        return RESUME_MODES[self.resume_mode.GetSelection()]

    def get_global_seek_volume_hotkeys(self) -> bool:
        return self.global_seek_volume_hotkeys.GetValue()


class LyricsDialog(wx.Dialog):
    def __init__(self, parent: "MainFrame", lyrics: Lyrics) -> None:
        super().__init__(
            parent,
            title=f"Lyrics for {lyrics.track_name} - BlindSpot",
            size=(650, 600),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        outer = wx.BoxSizer(wx.VERTICAL)
        heading = lyrics.track_name
        if lyrics.artist_name:
            heading += f" by {lyrics.artist_name}"
        outer.Add(
            wx.StaticText(self, label=heading),
            0,
            wx.EXPAND | wx.ALL,
            12,
        )
        self.follow_braille = wx.CheckBox(
            self,
            label=(
                "Follow playback on braille display; VoiceOver may also speak"
                if sys.platform == "darwin"
                else "Follow playback on braille display"
            ),
        )
        self.follow_braille.Enable(bool(lyrics.synced_lines))
        outer.Add(
            self.follow_braille,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        self.text = wx.TextCtrl(
            self,
            value=lyrics.text,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
        )
        self.text.SetName(f"Lyrics for {heading}")
        outer.Add(
            self.text,
            1,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        buttons = self.CreateSeparatedButtonSizer(wx.CLOSE)
        if buttons:
            outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizer(outer)
        self.frame = parent
        self.track_id = lyrics.track_id
        self.synced_lines = lyrics.synced_lines
        self.last_braille_line = -1
        self.braille_timer = wx.Timer(self)
        self.Bind(wx.EVT_CHECKBOX, self.on_follow_braille, self.follow_braille)
        self.Bind(wx.EVT_TIMER, self.on_braille_timer, self.braille_timer)
        self.Bind(wx.EVT_BUTTON, self.on_close_button, id=wx.ID_CLOSE)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.text.SetInsertionPoint(0)
        self.text.SetFocus()

    def on_follow_braille(self, event: wx.CommandEvent) -> None:
        if self.follow_braille.GetValue():
            self.last_braille_line = -1
            self.braille_timer.Start(250)
            self.update_braille_line()
        else:
            self.braille_timer.Stop()

    def on_braille_timer(self, event: wx.TimerEvent) -> None:
        self.update_braille_line()

    def update_braille_line(self) -> None:
        position_ms = self.frame.playback_position_ms(self.track_id)
        if position_ms is None:
            self.follow_braille.SetValue(False)
            self.braille_timer.Stop()
            return
        line_index = -1
        for index, (timestamp_ms, text) in enumerate(self.synced_lines):
            if timestamp_ms > position_ms:
                break
            line_index = index
        if line_index < 0 or line_index == self.last_braille_line:
            return
        self.last_braille_line = line_index
        try:
            line = self.synced_lines[line_index][1]
            if sys.platform == "darwin":
                # AO2's VoiceOver backend has no separate braille method.
                # VoiceOver's output command reaches its announcement and
                # braille channels, and may also speak unless speech is muted.
                self.frame.announcer.output(line)
            else:
                self.frame.announcer.braille(line)
        except Exception:
            logger.exception("Braille lyric output failed")
            self.follow_braille.SetValue(False)
            self.braille_timer.Stop()

    def on_close_button(self, event: wx.CommandEvent) -> None:
        self.braille_timer.Stop()
        self.EndModal(wx.ID_CLOSE)

    def on_close(self, event: wx.CloseEvent) -> None:
        self.braille_timer.Stop()
        if self.IsModal():
            self.EndModal(wx.ID_CLOSE)
        else:
            event.Skip()


class CreatePlaylistDialog(wx.Dialog):
    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, title="Create playlist")
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(
            wx.StaticText(self, label="Playlist name"),
            0,
            wx.LEFT | wx.RIGHT | wx.TOP,
            12,
        )
        self.name = wx.TextCtrl(self)
        self.public = wx.CheckBox(self, label="Public playlist")
        outer.Add(self.name, 0, wx.EXPAND | wx.ALL, 12)
        outer.Add(self.public, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        buttons = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        if buttons:
            outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizerAndFit(outer)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        # Run after the modal window is shown; otherwise Windows may give the
        # default OK button focus when the dialog is activated.
        wx.CallAfter(self.focus_name)

    def focus_name(self) -> None:
        self.name.SetFocus()
        self.name.SelectAll()

    def on_ok(self, event: wx.CommandEvent) -> None:
        if not self.name.GetValue().strip():
            self.name.SetFocus()
            return
        event.Skip()


class ItemList(wx.ListBox):
    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, style=wx.LB_SINGLE)
        self.items: list[SpotifyItem] = []

    def set_items(self, items: list[SpotifyItem], selected: int = 0) -> None:
        self.items = items
        self.Set([item.accessible_label() for item in items])
        if items:
            self.SetSelection(min(max(0, selected), len(items) - 1))

    def selected_item(self) -> SpotifyItem | None:
        index = self.GetSelection()
        return self.items[index] if 0 <= index < len(self.items) else None

    def remove_at(self, index: int) -> None:
        if not 0 <= index < len(self.items):
            return
        del self.items[index]
        self.Delete(index)
        if self.items:
            self.SetSelection(min(index, len(self.items) - 1))


class SearchPanel(wx.Panel):
    def __init__(self, parent: wx.Window, frame: "MainFrame") -> None:
        super().__init__(parent)
        self.frame = frame
        self.history = NavigationHistory(ViewState("Search results", []))

        outer = wx.BoxSizer(wx.VERTICAL)
        query_label = wx.StaticText(self, label="Search query")
        self.query = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.categories = wx.RadioBox(
            self,
            label="Search for",
            choices=SEARCH_LABELS,
            majorDimension=1,
            style=wx.RA_SPECIFY_ROWS,
        )
        self.search_button = wx.Button(self, label="&Search")
        self.heading = wx.StaticText(self, label="Search results")
        self.results = ItemList(self)
        self.status = wx.StaticText(self, label="Enter a search query.")

        outer.Add(query_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        outer.Add(self.query, 0, wx.EXPAND | wx.ALL, 10)
        outer.Add(self.categories, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        outer.Add(self.search_button, 0, wx.ALL, 10)
        outer.Add(self.heading, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        outer.Add(self.results, 1, wx.EXPAND | wx.ALL, 10)
        outer.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(outer)

        self.query.Bind(wx.EVT_TEXT_ENTER, self.on_search)
        self.categories.Bind(wx.EVT_KEY_DOWN, self.on_category_key)
        self.search_button.Bind(wx.EVT_BUTTON, self.on_search)
        self.results.Bind(wx.EVT_LISTBOX_DCLICK, self.on_open)
        self.results.Bind(wx.EVT_KEY_DOWN, self.on_list_key)
        self.results.Bind(wx.EVT_CONTEXT_MENU, self.on_context_menu)
        self.results.Bind(wx.EVT_NAVIGATION_KEY, self.on_navigation)

    def focus_query(self) -> None:
        self.query.SetFocus()
        self.query.SelectAll()

    def on_category_key(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            logger.debug("Search submitted from category radio group")
            self.on_search()
        else:
            event.Skip()

    def on_search(self, event: wx.Event | None = None) -> None:
        query = self.query.GetValue().strip()
        if not query:
            self.frame.say("Enter a search query.")
            self.query.SetFocus()
            return
        category = SEARCH_TYPES[self.categories.GetSelection()]
        self.frame.run_task(
            "Searching Spotify",
            lambda: self.frame.spotify.search(query, category),
            lambda items: self.show_search(query, category, items),
        )

    def show_search(
        self, query: str, category: str, items: list[SpotifyItem]
    ) -> None:
        state = ViewState(
            f"Results for {query}",
            items,
            query=query,
            category=category,
        )
        self.history.reset(state)
        self.render(state, focus=True)
        self.frame.say(
            f"{len(items)} results." if items else f"No results for {query}."
        )
        if not items:
            self.query.SetFocus()

    def on_open(self, event: wx.Event | None = None) -> None:
        item = self.results.selected_item()
        if not item or item.kind == ItemKind.HEADING:
            return
        logger.info(
            "Opening search result kind=%s id=%s name=%r",
            item.kind,
            item.id,
            item.name,
        )
        self.history.remember_selection(self.results.GetSelection())
        if item.playable:
            self.frame.play(item)
        elif item.container:
            self.frame.run_task(
                f"Opening {item.name}",
                lambda: self.frame.spotify.children(item),
                lambda items: self.open_children(item, items),
            )

    def open_children(self, parent: SpotifyItem, items: list[SpotifyItem]) -> None:
        logger.info("Displaying %d children for %r", len(items), parent.name)
        self.history.push(ViewState(parent.name, items))
        self.render(self.history.current, focus=True)
        self.frame.say(f"{parent.name}. {len(items)} items.")

    def go_back(self) -> bool:
        if not self.history.can_go_back:
            return False
        state = self.history.back()
        self.render(state, focus=True)
        self.frame.say(f"Back to {state.title}.")
        return True

    def render(self, state: ViewState, *, focus: bool) -> None:
        self.heading.SetLabel(state.title)
        self.frame.update_title_for_page(self, state.title)
        self.results.set_items(state.items, state.selected)
        if focus and state.items:
            self.results.SetFocus()

    def refresh(self) -> None:
        if self.history.can_go_back:
            return
        if self.history.current.query:
            self.query.SetValue(self.history.current.query)
            self.categories.SetSelection(
                SEARCH_TYPES.index(self.history.current.category)
            )
            self.on_search()

    def on_list_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if key == wx.WXK_TAB and not event.ShiftDown():
            self.frame.focus_tab_bar()
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.on_open()
        elif key == wx.WXK_BACK:
            if not self.go_back():
                self.focus_query()
        elif physical_control_down(event) and key in (ord("Q"), ord("q")):
            self.frame.queue_selected(self.results.selected_item())
        elif physical_control_down(event) and key in (ord("L"), ord("l")):
            self.frame.toggle_like_selected()
        elif physical_control_down(event) and key in (ord("P"), ord("p")):
            self.frame.play_selected()
        elif key == wx.WXK_F5:
            self.refresh()
        elif (
            (key == wx.WXK_F10 and event.ShiftDown())
            or key in (wx.WXK_MENU, wx.WXK_WINDOWS_MENU)
        ):
            self.on_context_menu()
        else:
            event.Skip()

    def on_context_menu(self, event: wx.Event | None = None) -> None:
        item = self.results.selected_item()
        if not item or item.kind == ItemKind.HEADING:
            return
        self.frame.popup_item_menu(
            self.results,
            item,
            open_callback=self.on_open if item.container else None,
        )

    def on_navigation(self, event: wx.NavigationKeyEvent) -> None:
        if event.IsFromTab() and event.GetDirection():
            logger.debug("Forward navigation from search results to main tab bar")
            self.frame.focus_tab_bar()
        else:
            event.Skip()


class CollectionPanel(wx.Panel):
    def __init__(
        self,
        parent: wx.Window,
        frame: "MainFrame",
        title: str,
        loader: Callable[[], list[SpotifyItem]],
        *,
        removable: bool = False,
        silent_load: bool = False,
        load_on_first_focus: bool = False,
    ) -> None:
        super().__init__(parent)
        self.frame = frame
        self.title = title
        self.loader = loader
        self.removable = removable
        self.silent_load = silent_load
        self.load_on_first_focus = load_on_first_focus
        self.loaded_once = False
        self.loading = False
        outer = wx.BoxSizer(wx.VERTICAL)
        self.heading = wx.StaticText(self, label=title)
        self.items = ItemList(self)
        self.status = wx.StaticText(self, label=f"Press F5 to load {title}.")
        outer.Add(self.heading, 0, wx.ALL, 10)
        outer.Add(self.items, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        outer.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(outer)
        self.items.Bind(wx.EVT_LISTBOX_DCLICK, self.on_open)
        self.items.Bind(wx.EVT_KEY_DOWN, self.on_key)
        self.items.Bind(wx.EVT_CONTEXT_MENU, self.on_context_menu)
        self.items.Bind(wx.EVT_NAVIGATION_KEY, self.on_navigation)
        self.items.Bind(wx.EVT_SET_FOCUS, self.on_list_focus)

    def refresh(self) -> None:
        if self.loading:
            return
        self.loading = True
        self.frame.run_task(
            None if self.silent_load else f"Loading {self.title}",
            self.loader,
            self.show_items,
            failure=self.finish_load_error,
        )

    def show_items(self, items: list[SpotifyItem]) -> None:
        self.loading = False
        self.loaded_once = True
        self.frame.update_title_for_page(self, self.title)
        self.items.set_items(items)
        self.status.SetLabel(f"{len(items)} items.")
        if items:
            self.items.SetFocus()

    def on_list_focus(self, event: wx.FocusEvent) -> None:
        event.Skip()
        if self.load_on_first_focus and not self.loaded_once and not self.loading:
            wx.CallAfter(self.refresh)

    def finish_load_error(self) -> None:
        self.loading = False

    def on_open(self, event: wx.Event | None = None) -> None:
        item = self.items.selected_item()
        if item:
            self.frame.play(item)

    def on_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if key == wx.WXK_TAB and not event.ShiftDown():
            self.frame.focus_tab_bar()
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.on_open()
        elif key == wx.WXK_DELETE and self.removable:
            self.remove_selected()
        elif key == wx.WXK_F5:
            self.refresh()
        elif physical_control_down(event) and key in (ord("Q"), ord("q")):
            self.frame.queue_selected(self.items.selected_item())
        elif physical_control_down(event) and key in (ord("L"), ord("l")):
            self.frame.toggle_like_selected()
        elif physical_control_down(event) and key in (ord("P"), ord("p")):
            self.frame.play_selected()
        elif key == wx.WXK_F10 and event.ShiftDown():
            self.on_context_menu()
        else:
            event.Skip()

    def on_context_menu(self, event: wx.Event | None = None) -> None:
        item = self.items.selected_item()
        if not item:
            return
        self.frame.popup_item_menu(
            self.items,
            item,
            open_callback=self.on_open if item.container else None,
            remove_callback=self.remove_selected if self.removable else None,
        )

    def remove_selected(self) -> None:
        index = self.items.GetSelection()
        item = self.items.selected_item()
        if not item:
            return
        self.frame.run_task(
            None,
            lambda: self.frame.spotify.remove(item),
            lambda result: self.finish_remove(index),
        )

    def finish_remove(self, index: int) -> None:
        self.items.remove_at(index)
        self.status.SetLabel(f"{len(self.items.items)} items.")
        self.items.SetFocus()

    def on_navigation(self, event: wx.NavigationKeyEvent) -> None:
        if event.IsFromTab() and event.GetDirection():
            logger.debug(
                "Forward navigation from %s list to main tab bar",
                self.title,
            )
            self.frame.focus_tab_bar()
        else:
            event.Skip()


class BookmarksPanel(CollectionPanel):
    def __init__(self, parent: wx.Window, frame: "MainFrame") -> None:
        super().__init__(
            parent,
            frame,
            "Bookmarks",
            frame.load_bookmarks,
            removable=True,
            silent_load=True,
            load_on_first_focus=True,
        )

    def on_open(self, event: wx.Event | None = None) -> None:
        item = self.items.selected_item()
        if item:
            self.frame.resume_bookmark(item)

    def remove_selected(self) -> None:
        index = self.items.GetSelection()
        item = self.items.selected_item()
        if not item:
            return
        self.frame.delete_bookmark(item)
        self.items.remove_at(index)
        self.status.SetLabel(f"{len(self.items.items)} items.")
        if self.items.items:
            self.items.SetFocus()

    def on_context_menu(self, event: wx.Event | None = None) -> None:
        item = self.items.selected_item()
        if not item:
            return
        menu = wx.Menu()
        actions = [
            (
                menu.Append(wx.ID_ANY, "&Resume from bookmark"),
                lambda: self.frame.resume_bookmark(item),
            ),
            (
                menu.Append(wx.ID_ANY, "Open &album"),
                lambda: self.frame.open_album_for_track(item),
            ),
            (
                menu.Append(wx.ID_ANY, "Add to &queue"),
                lambda: self.frame.queue_selected(item),
            ),
            (
                menu.Append(wx.ID_ANY, "&Save to library"),
                lambda: self.frame.like_selected(item),
            ),
        ]
        menu.AppendSeparator()
        actions.append(
            (
                menu.Append(wx.ID_ANY, "&Delete bookmark"),
                self.remove_selected,
            )
        )
        for menu_item, callback in actions:
            menu.Bind(
                wx.EVT_MENU,
                lambda menu_event, action=callback: action(),
                menu_item,
            )
        self.items.PopupMenu(menu)
        menu.Destroy()


class PlaylistsPanel(wx.Panel):
    def __init__(self, parent: wx.Window, frame: "MainFrame") -> None:
        super().__init__(parent)
        self.frame = frame
        self.history = NavigationHistory(ViewState("Playlists", []))
        self.current_playlist: SpotifyItem | None = None
        self.loaded_once = False
        self.loading = False

        outer = wx.BoxSizer(wx.VERTICAL)
        self.heading = wx.StaticText(self, label="Playlists")
        self.items = ItemList(self)
        self.status = wx.StaticText(self, label="Move into the list to load playlists.")
        outer.Add(self.heading, 0, wx.ALL, 10)
        outer.Add(self.items, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        outer.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(outer)

        self.items.Bind(wx.EVT_SET_FOCUS, self.on_focus)
        self.items.Bind(wx.EVT_KEY_DOWN, self.on_key)
        self.items.Bind(wx.EVT_LISTBOX_DCLICK, self.on_open)
        self.items.Bind(wx.EVT_CONTEXT_MENU, self.on_context_menu)

    def on_focus(self, event: wx.FocusEvent) -> None:
        event.Skip()
        if not self.loaded_once and not self.loading:
            wx.CallAfter(self.refresh)

    def refresh(self) -> None:
        if self.loading:
            return
        if self.history.can_go_back and self.current_playlist:
            playlist = self.current_playlist
            self.loading = True
            self.frame.run_task(
                None,
                lambda: self.frame.spotify.children(playlist),
                lambda items: self.show_tracks(playlist, items, replace=True),
                failure=self.finish_load_error,
            )
            return
        self.loading = True
        self.frame.run_task(
            None,
            self.frame.spotify.user_playlists,
            self.show_playlists,
            failure=self.finish_load_error,
        )

    def finish_load_error(self) -> None:
        self.loading = False

    def show_playlists(self, playlists: list[SpotifyItem]) -> None:
        self.loading = False
        self.loaded_once = True
        state = ViewState("Playlists", playlists)
        self.history.reset(state)
        self.current_playlist = None
        self.render(state, focus=True)

    def on_open(self, event: wx.Event | None = None) -> None:
        item = self.items.selected_item()
        if not item:
            return
        if self.history.can_go_back:
            if self.current_playlist:
                self.frame.play_in_context(self.current_playlist, item)
            else:
                self.frame.play(item)
            return
        self.history.remember_selection(self.items.GetSelection())
        self.loading = True
        self.frame.run_task(
            None,
            lambda: self.frame.spotify.children(item),
            lambda tracks: self.show_tracks(item, tracks),
            failure=self.finish_load_error,
        )

    def show_tracks(
        self,
        playlist: SpotifyItem,
        tracks: list[SpotifyItem],
        *,
        replace: bool = False,
    ) -> None:
        self.loading = False
        self.current_playlist = playlist
        title = (
            f"{playlist.name}, read only"
            if playlist.raw.get("editable") is False
            else playlist.name
        )
        state = ViewState(title, tracks)
        if replace:
            selected = self.history.current.selected
            state.selected = selected
            self.history.replace(state)
        else:
            self.history.push(state)
        self.render(state, focus=True)

    def go_back(self) -> bool:
        if not self.history.can_go_back:
            return False
        state = self.history.back()
        self.current_playlist = None
        self.render(state, focus=True)
        return True

    def render(self, state: ViewState, *, focus: bool) -> None:
        self.heading.SetLabel(state.title)
        self.frame.update_title_for_page(self, state.title)
        self.items.set_items(state.items, state.selected)
        self.status.SetLabel(f"{len(state.items)} items.")
        if focus:
            self.items.SetFocus()

    def on_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.on_open()
        elif key == wx.WXK_BACK:
            self.go_back()
        elif key == wx.WXK_DELETE and self.history.can_go_back:
            self.remove_selected()
        elif key == wx.WXK_F5:
            self.refresh()
        elif key == wx.WXK_F10 and event.ShiftDown():
            self.on_context_menu()
        else:
            event.Skip()

    def remove_selected(self) -> None:
        playlist = self.current_playlist
        item = self.items.selected_item()
        if not playlist or not item:
            return
        if playlist.raw.get("editable") is False:
            self.frame.say("Read only.")
            return
        index = self.items.GetSelection()
        self.frame.run_task(
            None,
            lambda: self.frame.spotify.remove_from_playlist(playlist, item),
            lambda result: self.finish_remove(index),
        )

    def finish_remove(self, index: int) -> None:
        self.items.remove_at(index)
        self.history.current.items = list(self.items.items)
        self.history.current.selected = self.items.GetSelection()
        self.status.SetLabel(f"{len(self.items.items)} items.")
        self.items.SetFocus()

    def on_context_menu(self, event: wx.Event | None = None) -> None:
        item = self.items.selected_item()
        if not item:
            return
        if not self.history.can_go_back:
            self.popup_playlist_menu(item)
            return
        removable = bool(
            self.current_playlist
            and self.current_playlist.raw.get("editable") is not False
        )
        self.frame.popup_item_menu(
            self.items,
            item,
            play_callback=(
                lambda: self.frame.play_in_context(
                    self.current_playlist,
                    item,
                )
                if self.current_playlist
                else self.frame.play(item)
            ),
            remove_callback=self.remove_selected if removable else None,
        )

    def popup_playlist_menu(self, playlist: SpotifyItem) -> None:
        menu = wx.Menu()
        actions = [
            (menu.Append(wx.ID_ANY, "&Open"), self.on_open),
            (
                menu.Append(wx.ID_ANY, "&Play"),
                lambda: self.frame.play(playlist),
            ),
            (
                menu.Append(wx.ID_ANY, "&New playlist..."),
                self.frame.create_playlist,
            ),
        ]
        if playlist.raw.get("owned") is True:
            actions.append(
                (
                    menu.Append(wx.ID_ANY, "Re&name..."),
                    lambda: self.rename_playlist(playlist),
                )
            )
        menu.AppendSeparator()
        actions.append(
            (
                menu.Append(wx.ID_ANY, "Remove from &library..."),
                lambda: self.remove_playlist(playlist),
            )
        )
        for menu_item, callback in actions:
            menu.Bind(
                wx.EVT_MENU,
                lambda event, action=callback: action(),
                menu_item,
            )
        self.items.PopupMenu(menu)
        menu.Destroy()

    def rename_playlist(self, playlist: SpotifyItem) -> None:
        dialog = wx.TextEntryDialog(
            self,
            "Enter a new playlist name.",
            "Rename playlist",
            playlist.name,
        )
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        name = dialog.GetValue().strip()
        dialog.Destroy()
        if not name or name == playlist.name:
            return
        self.frame.run_task(
            None,
            lambda: self.frame.spotify.rename_playlist(playlist, name),
            lambda result: self.finish_rename_playlist(playlist, name),
        )

    def finish_rename_playlist(
        self,
        playlist: SpotifyItem,
        name: str,
    ) -> None:
        playlist.name = name
        index = self.items.items.index(playlist)
        self.items.SetString(index, playlist.accessible_label())
        self.items.SetSelection(index)
        self.frame.say("Renamed.")

    def remove_playlist(self, playlist: SpotifyItem) -> None:
        answer = wx.MessageBox(
            f"Remove {playlist.name} from your Spotify library?",
            "Remove playlist",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
            self,
        )
        if answer != wx.YES:
            return
        self.frame.run_task(
            None,
            lambda: self.frame.spotify.remove_playlist_from_library(playlist),
            lambda result: self.finish_remove_playlist(playlist),
        )

    def finish_remove_playlist(self, playlist: SpotifyItem) -> None:
        index = self.items.items.index(playlist)
        self.items.remove_at(index)
        self.history.current.items = list(self.items.items)
        self.history.current.selected = self.items.GetSelection()
        self.status.SetLabel(f"{len(self.items.items)} items.")
        self.frame.say("Removed from library.")

    def on_navigation(self, event: wx.NavigationKeyEvent) -> None:
        if event.IsFromTab() and event.GetDirection():
            logger.debug(
                "Forward navigation from %s list to main tab bar",
                self.title,
            )
            self.frame.focus_tab_bar()
        else:
            event.Skip()


class MainFrame(wx.Frame):
    def __init__(self, spotify: SpotifyClient, store: PortableStore) -> None:
        title = (
            "Demo Mode - BlindSpot"
            if getattr(spotify, "demo_mode", False)
            else "BlindSpot"
        )
        super().__init__(None, title=title, size=(820, 620))
        self.spotify = spotify
        self.store = store
        settings = self.store.read("settings.json", {}) or {}
        self.announce_track_changes = bool(
            settings.get("announce_track_changes", False)
        )
        self.resume_mode = resume_mode_from_settings(settings)
        self.global_seek_volume_hotkeys = bool(
            settings.get("global_seek_volume_hotkeys", False)
        )
        self.registered_hotkey_ids: list[int] = []
        self.last_player_item_id: str | None = None
        self.current_player_state: dict = {}
        self.playback_state_updated_at = time.monotonic()
        self.shuffle_enabled: bool | None = None
        self.repeat_state: str | None = None
        self.pending_resume: tuple[SpotifyItem, int, str] | None = None
        self.announcer = Auto()
        self.player: WebPlaybackController | None = None
        self.current_player_item: SpotifyItem | None = None
        self.pending_play_item: SpotifyItem | None = None
        self.pending_play_context: SpotifyItem | None = None
        self.lyrics = LRCLibClient()
        self.remote_device_id: str | None = None
        self.remote_device_name = ""
        self.remote_supports_volume: bool | None = None
        self.remote_refresh_pending = False
        self.remote_refresh_timer = wx.Timer(self)
        self.Bind(
            wx.EVT_TIMER,
            lambda event: self.refresh_remote_playback(),
            self.remote_refresh_timer,
        )
        self.sleep_timer = wx.Timer(self)
        self.Bind(
            wx.EVT_TIMER,
            lambda event: self.on_sleep_timer(),
            self.sleep_timer,
        )
        self.sleep_after_track_id: str | None = None
        self.authorization_in_progress = False
        self.recent_permission_authorization = False
        self.available_release = None
        self.update_progress = None
        self.CreateStatusBar()
        self._build_menu()
        self.notebook = wx.Notebook(self)
        self.search = SearchPanel(self.notebook, self)
        self.liked = CollectionPanel(
            self.notebook,
            self,
            "Liked Songs",
            spotify.liked_songs,
            removable=True,
            silent_load=True,
            load_on_first_focus=True,
        )
        self.queue = CollectionPanel(
            self.notebook,
            self,
            "Queue",
            spotify.queue,
            silent_load=True,
            load_on_first_focus=True,
        )
        self.playlists = PlaylistsPanel(self.notebook, self)
        self.recently_played = CollectionPanel(
            self.notebook,
            self,
            "Recently Played",
            spotify.recently_played,
            silent_load=True,
            load_on_first_focus=True,
        )
        self.bookmarks = BookmarksPanel(self.notebook, self)
        for panel, label in (
            (self.search, "Search"),
            (self.liked, "Liked Songs"),
            (self.queue, "Queue"),
            (self.playlists, "Playlists"),
            (self.recently_played, "Recently Played"),
            (self.bookmarks, "Bookmarks"),
        ):
            self.notebook.AddPage(panel, label)
        self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.on_tab_changed)
        self.set_view_title("Search")
        self.load_pending_resume()
        self.Bind(wx.EVT_CHAR_HOOK, self.on_global_key)
        for hotkey_id in (
            GLOBAL_HOTKEY_SEEK_BACKWARD,
            GLOBAL_HOTKEY_SEEK_FORWARD,
            GLOBAL_HOTKEY_VOLUME_DOWN,
            GLOBAL_HOTKEY_VOLUME_UP,
        ):
            self.Bind(wx.EVT_HOTKEY, self.on_global_hotkey, id=hotkey_id)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Centre()
        self._create_web_player()
        wx.CallAfter(self.apply_global_hotkey_setting)
        wx.CallAfter(self.initial_focus)
        wx.CallAfter(self.check_for_updates, False)

    def _create_web_player(self) -> None:
        if getattr(self.spotify, "demo_mode", False):
            logger.info("Demo mode: hidden Spotify player is disabled")
            return
        try:
            self.player = WebPlaybackController(
                self,
                self.spotify,
                on_ready=self.on_player_ready,
                on_error=self.on_player_error,
                on_playback_update=self.on_playback_update,
            )
        except Exception as error:
            logger.exception("Could not create BlindSpot web player")
            self.player = None
            self.say(str(error))

    def _build_menu(self) -> None:
        ctrl = "RawCtrl" if sys.platform == "darwin" else "Ctrl"
        menu_bar = wx.MenuBar()
        go = wx.Menu()
        play_selected = go.Append(wx.ID_ANY, f"&Play selected\t{ctrl}+P")
        play_pause = go.Append(wx.ID_ANY, f"Play or &pause\t{ctrl}+Space")
        play_on_device = go.Append(
            wx.ID_ANY,
            "Choose playback &device...",
        )
        sleep_menu = wx.Menu()
        sleep_after_track = sleep_menu.Append(
            wx.ID_ANY,
            "After current &track",
        )
        sleep_15 = sleep_menu.Append(wx.ID_ANY, "After &15 minutes")
        sleep_30 = sleep_menu.Append(wx.ID_ANY, "After &30 minutes")
        sleep_60 = sleep_menu.Append(wx.ID_ANY, "After &60 minutes")
        sleep_menu.AppendSeparator()
        cancel_sleep = sleep_menu.Append(wx.ID_ANY, "&Cancel sleep timer")
        go.AppendSubMenu(
            sleep_menu,
            f"Sleep ti&mer...\t{ctrl}+Shift+J",
        )
        bookmark_position = go.Append(
            wx.ID_ANY,
            f"Bookmark current &position\t{ctrl}+Shift+B",
        )
        go.AppendSeparator()
        previous_track = go.Append(
            wx.ID_ANY,
            f"Pre&vious track\t{ctrl}+Z",
        )
        next_track = go.Append(wx.ID_ANY, f"&Next track\t{ctrl}+B")
        seek_backward = go.Append(
            wx.ID_ANY,
            "Seek &backward 5 seconds (Ctrl+[)",
        )
        seek_forward = go.Append(
            wx.ID_ANY,
            "Seek &forward 5 seconds (Ctrl+])",
        )
        speak_total = go.Append(
            wx.ID_ANY,
            f"Speak &total time\t{ctrl}+Shift+T",
        )
        speak_elapsed = go.Append(
            wx.ID_ANY,
            f"Speak &elapsed time\t{ctrl}+Shift+E",
        )
        speak_remaining = go.Append(
            wx.ID_ANY,
            f"Speak &remaining time\t{ctrl}+Shift+R",
        )
        jump_to_time = go.Append(
            wx.ID_ANY,
            f"&Jump to time...\t{ctrl}+J",
        )
        speak_current = go.Append(
            wx.ID_ANY,
            f"Speak current track\t{ctrl}+Shift+N",
        )
        speak_up_next = go.Append(
            wx.ID_ANY,
            f"Speak &up next\t{ctrl}+Shift+U",
        )
        lyrics = go.Append(wx.ID_ANY, f"L&yrics...\t{ctrl}+Y")
        repeat = go.Append(wx.ID_ANY, f"&Repeat\t{ctrl}+R")
        shuffle = go.Append(wx.ID_ANY, f"&Shuffle\t{ctrl}+S")
        volume_down = go.Append(
            wx.ID_ANY,
            "Volume &down 5 percent (Ctrl+Semicolon)",
        )
        volume_up = go.Append(
            wx.ID_ANY,
            "Volume &up 5 percent (Ctrl+Apostrophe)",
        )
        go.AppendSeparator()
        queue_selected = go.Append(
            wx.ID_ANY,
            f"Add selected to &queue\t{ctrl}+Q",
        )
        like_selected = go.Append(
            wx.ID_ANY,
            f"&Like or unlike selected\t{ctrl}+L",
        )
        add_to_playlist = go.Append(
            wx.ID_ANY,
            f"Add selected to a pl&aylist...\t{ctrl}+Shift+A",
        )
        create_playlist = go.Append(
            wx.ID_ANY,
            f"&New playlist...\t{ctrl}+N",
        )
        go.AppendSeparator()
        open_queue = go.Append(wx.ID_ANY, f"Open &Queue\t{ctrl}+3")
        open_playlists = go.Append(wx.ID_ANY, f"Open Playlists\t{ctrl}+4")
        open_recent = go.Append(
            wx.ID_ANY,
            f"Open Recently Played\t{ctrl}+5",
        )
        open_bookmarks = go.Append(
            wx.ID_ANY,
            f"Open &Bookmarks\t{ctrl}+6",
        )
        menu_bar.Append(go, "&Go")

        options = wx.Menu()
        preferences = options.Append(
            wx.ID_PREFERENCES,
            f"&Preferences...\t{ctrl}+,",
        )
        account = wx.Menu()
        connect = account.Append(
            wx.ID_ANY,
            f"&Connect to Spotify...\t{ctrl}+Shift+C",
        )
        refresh_permissions = account.Append(
            wx.ID_ANY,
            "&Refresh Spotify permissions...",
        )
        sign_out = account.Append(wx.ID_ANY, "Sign &out and erase credentials")
        options.AppendSubMenu(account, "&Account")
        options.AppendSeparator()
        close = options.Append(wx.ID_EXIT, "E&xit\tAlt+F4")
        menu_bar.Append(options, "&Options")

        help_menu = wx.Menu()
        manual = help_menu.Append(wx.ID_HELP, "&Manual\tF1")
        check_updates = help_menu.Append(
            wx.ID_ANY,
            "Check for &updates...",
        )
        help_menu.AppendSeparator()
        about = help_menu.Append(wx.ID_ABOUT, "&About BlindSpot...")
        menu_bar.Append(help_menu, "&Help")
        self.SetMenuBar(menu_bar)
        self.Bind(wx.EVT_MENU, lambda event: self.play_selected(), play_selected)
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.toggle_playback(),
            play_pause,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.choose_playback_device(),
            play_on_device,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.set_sleep_after_current_track(),
            sleep_after_track,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.set_sleep_timer(15),
            sleep_15,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.set_sleep_timer(30),
            sleep_30,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.set_sleep_timer(60),
            sleep_60,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.cancel_sleep_timer(),
            cancel_sleep,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.save_current_bookmark(),
            bookmark_position,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.previous_track(),
            previous_track,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.next_track(),
            next_track,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.seek(-5000),
            seek_backward,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.seek(5000),
            seek_forward,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.announce_time("total"),
            speak_total,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.announce_time("elapsed"),
            speak_elapsed,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.announce_time("remaining"),
            speak_remaining,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.jump_to_time(),
            jump_to_time,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.speak_current_track(),
            speak_current,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.speak_up_next(),
            speak_up_next,
        )
        self.Bind(wx.EVT_MENU, lambda event: self.show_lyrics(), lyrics)
        self.Bind(wx.EVT_MENU, lambda event: self.cycle_repeat(), repeat)
        self.Bind(wx.EVT_MENU, lambda event: self.toggle_shuffle(), shuffle)
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.adjust_volume(-5),
            volume_down,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.adjust_volume(5),
            volume_up,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.queue_selected(self.current_selected_item()),
            queue_selected,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.toggle_like_selected(),
            like_selected,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.choose_playlist_for_selected(),
            add_to_playlist,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.create_playlist(),
            create_playlist,
        )
        self.Bind(wx.EVT_MENU, lambda event: self.open_tab(2), open_queue)
        self.Bind(wx.EVT_MENU, lambda event: self.open_tab(3), open_playlists)
        self.Bind(wx.EVT_MENU, lambda event: self.open_tab(4), open_recent)
        self.Bind(wx.EVT_MENU, lambda event: self.open_tab(5), open_bookmarks)
        self.Bind(wx.EVT_MENU, self.on_preferences, preferences)
        self.Bind(wx.EVT_MENU, self.on_connect, connect)
        self.Bind(
            wx.EVT_MENU,
            lambda event: self._start_authorization(force_dialog=True),
            refresh_permissions,
        )
        self.Bind(wx.EVT_MENU, self.on_sign_out, sign_out)
        self.Bind(wx.EVT_MENU, lambda event: self.Close(), close)
        self.Bind(wx.EVT_MENU, self.on_manual, manual)
        self.Bind(wx.EVT_MENU, self.on_check_updates, check_updates)
        self.Bind(wx.EVT_MENU, self.on_about, about)
        if getattr(self.spotify, "demo_mode", False):
            connect.Enable(False)
            refresh_permissions.Enable(False)
            sign_out.Enable(False)

    def initial_focus(self) -> None:
        if getattr(self.spotify, "demo_mode", False):
            self.say("Demo mode. No Spotify connection is being used.")
            self.search.focus_query()
            return
        if not self.spotify.connected:
            if self.spotify.client_id and self.spotify.token.get("refresh_token"):
                self.search.focus_query()
            elif self.spotify.client_id:
                self.say(
                    "Spotify authorization is required."
                )
                wx.CallAfter(self.on_connect, None)
            else:
                self.say("Not connected to Spotify. Use the Account menu to connect.")
                wx.CallAfter(self.on_connect, None)
        else:
            self.search.focus_query()
            if not self.spotify.web_playback_authorized:
                self.say(
                    "Browsing is connected. Refresh Spotify permissions from "
                    "the Account menu to enable BlindSpot's internal player."
                )

    def say(self, message: str) -> None:
        self.SetStatusText(message)
        try:
            self.announcer.speak(message, interrupt=False)
        except Exception:
            logger.exception(
                "Could not speak status through accessible-output2"
            )
        try:
            self.announcer.braille(message)
        except Exception:
            # The status text and speech remain available when a screen reader
            # does not expose a braille output channel.
            logger.exception(
                "Could not braille status through accessible-output2"
            )

    def set_view_title(self, title: str) -> None:
        if getattr(self.spotify, "demo_mode", False):
            title = f"{title} (Demo Mode)"
        self.SetTitle(f"{title} - BlindSpot")

    def update_title_for_page(self, page: wx.Window, title: str) -> None:
        if self.notebook.GetCurrentPage() is page:
            self.set_view_title(title)

    def focus_tab_bar(self) -> None:
        self.notebook.SetFocus()
        self.say("Main tabs.")

    def run_task(
        self,
        message: str | None,
        worker: Callable[[], object],
        success: Callable[[object], None],
        *,
        failure: Callable[[], None] | None = None,
    ) -> None:
        if not self.spotify.connected:
            if failure:
                failure()
            self.say("Connect BlindSpot to Spotify first.")
            return
        if message:
            self.say(message)

        def run() -> None:
            try:
                result = worker()
            except Exception as error:
                logger.exception("Background task failed: %s", message or "unnamed task")
                error_message = str(error)

                def report_error(
                    caught_error: Exception = error,
                    caught_message: str = error_message,
                ) -> None:
                    if failure:
                        failure()
                    if isinstance(caught_error, RecentlyPlayedPermissionRequired):
                        self.offer_permission_refresh()
                    elif isinstance(
                        caught_error,
                        (PlaylistContentsUnavailable, LyricsUnavailable),
                    ):
                        self.say(caught_message)
                    else:
                        self.show_error(caught_message)

                wx.CallAfter(report_error)
            else:
                wx.CallAfter(success, result)

        threading.Thread(target=run, daemon=True).start()

    def offer_permission_refresh(self) -> None:
        answer = wx.MessageBox(
            "Recently Played needs an additional Spotify permission. "
            "Authorize it now?",
            "Recently Played",
            wx.YES_NO | wx.YES_DEFAULT | wx.ICON_QUESTION,
            self,
        )
        if answer == wx.YES:
            self.recent_permission_authorization = True
            # Returning focus to the list must not trigger another automatic
            # load while browser authorization is still in progress.
            self.recently_played.loading = True
            if not self._start_authorization(force_dialog=True):
                self.recent_permission_authorization = False
                self.recently_played.loading = False
        else:
            self.recently_played.loaded_once = True
            self.say("Recently Played was not authorized.")

    def show_error(self, message: str) -> None:
        self.say(message)
        wx.MessageBox(message, "BlindSpot", wx.OK | wx.ICON_ERROR, self)

    def on_connect(self, event: wx.Event | None) -> None:
        dialog = SetupDialog(self, self.spotify.client_id)
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            self.search.focus_query()
            return
        client_id = dialog.get_client_id()
        dialog.Destroy()
        self.spotify.set_client_id(client_id)
        self._start_authorization()

    def _start_authorization(self, *, force_dialog: bool = False) -> bool:
        if self.authorization_in_progress:
            self.say("Spotify authorization is already in progress.")
            return False
        try:
            request = self.spotify.begin_authorization(
                force_dialog=force_dialog,
            )
        except SpotifyError as error:
            self.show_error(str(error))
            return False
        self.authorization_in_progress = True
        self.say("Complete the Spotify login in your browser.")

        def authorize() -> None:
            try:
                server = CallbackServer(request.state)
                webbrowser.open(request.url)
                code = server.wait()
                self.spotify.complete_authorization(code, request.verifier)
            except TimeoutError as error:
                wx.CallAfter(self.say, str(error))
            except Exception as error:
                wx.CallAfter(self.show_error, str(error))
            else:
                wx.CallAfter(self.on_connected)
            finally:
                wx.CallAfter(self._authorization_finished)

        threading.Thread(target=authorize, daemon=True).start()
        return True

    def _authorization_finished(self) -> None:
        self.authorization_in_progress = False
        if self.recent_permission_authorization:
            # on_connected clears this flag first on success. If it is still
            # set, authorization failed or timed out.
            self.recent_permission_authorization = False
            self.recently_played.loading = False
            self.recently_played.loaded_once = True
            self.recently_played.status.SetLabel(
                "Recently Played authorization was not completed."
            )

    def on_sign_out(self, event: wx.Event) -> None:
        answer = wx.MessageBox(
            "Erase the saved Spotify session from this portable folder?",
            "Sign out of BlindSpot",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
            self,
        )
        if answer == wx.YES:
            self.spotify.sign_out()
            self.say("Signed out and erased saved Spotify credentials.")

    def on_preferences(self, event: wx.Event | None = None) -> None:
        settings = self.store.read("settings.json", {}) or {}
        dialog = PreferencesDialog(
            self,
            settings.get("logging_level", "Off"),
            bool(settings.get("announce_track_changes", False)),
            resume_mode_from_settings(settings),
            bool(settings.get("global_seek_volume_hotkeys", False)),
        )
        if dialog.ShowModal() == wx.ID_OK:
            level = dialog.get_logging_level()
            settings["logging_level"] = level
            self.announce_track_changes = (
                dialog.get_announce_track_changes()
            )
            settings["announce_track_changes"] = (
                self.announce_track_changes
            )
            self.resume_mode = dialog.get_resume_mode()
            settings["resume_mode"] = self.resume_mode
            settings.pop("resume_last_track", None)
            self.global_seek_volume_hotkeys = (
                dialog.get_global_seek_volume_hotkeys()
            )
            settings["global_seek_volume_hotkeys"] = (
                self.global_seek_volume_hotkeys
            )
            self.store.write("settings.json", settings)
            self.apply_global_hotkey_setting()
            if self.resume_mode == "none":
                self.pending_resume = None
                self.store.remove("playback.json")
            elif self.current_player_state:
                self.store.write(
                    "playback.json",
                    playback_state_for_resume(
                        self.current_player_state,
                        self.resume_mode,
                    ),
                )
            configure_logging(self.store.root / "blindspot.log", level)
        dialog.Destroy()

    def on_manual(self, event: wx.Event | None = None) -> None:
        manual = resource_directory() / "manual.html"
        if not manual.exists():
            self.show_error("The BlindSpot manual could not be found.")
            return
        webbrowser.open(manual.resolve().as_uri())

    def on_check_updates(self, event: wx.Event) -> None:
        self.check_for_updates(True)

    def check_for_updates(self, report_current: bool) -> None:
        def run() -> None:
            try:
                release = latest_release()
            except Exception as error:
                logger.warning("Update check failed: %s", error)
                if report_current:
                    wx.CallAfter(
                        self.show_error,
                        "BlindSpot could not check for updates.",
                    )
                return
            wx.CallAfter(self._finish_update_check, release, report_current)

        threading.Thread(target=run, daemon=True).start()

    def _finish_update_check(self, release, report_current: bool) -> None:
        if newer_than(release.version, __version__):
            settings = self.store.read("settings.json", {}) or {}
            if (
                not report_current
                and settings.get("dismissed_update") == release.version
            ):
                return
            answer = wx.MessageBox(
                f"BlindSpot {release.version} is available.\n\n"
                "Open the download page now?",
                "BlindSpot update available",
                wx.YES_NO | wx.ICON_INFORMATION,
                self,
            )
            if answer == wx.YES:
                self.available_release = release
                self.update_progress = wx.ProgressDialog(
                    "Downloading update",
                    "Downloading BlindSpot update...",
                    maximum=100,
                    parent=self,
                    style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE,
                )
                threading.Thread(
                    target=self._download_update,
                    daemon=True,
                ).start()
            else:
                settings["dismissed_update"] = release.version
                self.store.write("settings.json", settings)
        elif report_current:
            wx.MessageBox(
                f"BlindSpot {__version__} is up to date.",
                "Check for updates",
                wx.OK | wx.ICON_INFORMATION,
                self,
            )

    def _download_update(self) -> None:
        def progress(percent: int) -> None:
            if self.update_progress:
                wx.CallAfter(self.update_progress.Update, percent)

        try:
            success = download_and_install(
                self.available_release,
                progress_callback=progress,
            )
        except Exception as error:
            logger.exception("Update download failed")
            success = False
            message = str(error)
        wx.CallAfter(self._finish_update_download, success, message if not success else "")

    def _finish_update_download(self, success: bool, message: str) -> None:
        if self.update_progress:
            self.update_progress.Destroy()
            self.update_progress = None
        if success and sys.platform == "win32" and getattr(sys, "frozen", False):
            self.Close()
        elif not success:
            self.show_error(
                message or "The BlindSpot update could not be downloaded."
            )

    def on_about(self, event: wx.Event) -> None:
        wx.MessageBox(
            "BlindSpot\n"
            f"Build {__version__}\n"
            "Copyright © 2026 Sam Taylor\n"
            "A portable, accessible Spotify client.",
            "About BlindSpot",
            wx.OK | wx.ICON_INFORMATION,
            self,
        )

    def on_connected(self) -> None:
        if self.recent_permission_authorization:
            self.recent_permission_authorization = False
            if self.spotify.has_scope("user-read-recently-played"):
                self.say("Recently Played authorized.")
                self.recently_played.loaded_once = False
                self.recently_played.loading = False
                wx.CallAfter(self.recently_played.refresh)
            else:
                self.recently_played.loading = False
                self.recently_played.loaded_once = True
                self.recently_played.status.SetLabel(
                    "Spotify did not grant access to Recently Played."
                )
                self.say(
                    "Spotify did not grant Recently Played access for this app. "
                    "The tab is unavailable."
                )
        else:
            self.say("Connected to Spotify. Starting BlindSpot's player.")
        if self.player:
            self.player.provide_token()

    def on_tab_changed(self, event: wx.BookCtrlEvent) -> None:
        page = self.notebook.GetPage(event.GetSelection())
        heading = getattr(page, "heading", None)
        title = heading.GetLabel() if heading else self.notebook.GetPageText(
            event.GetSelection()
        )
        self.set_view_title(title)
        event.Skip()

    def on_global_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        focused = wx.Window.FindFocus()
        if key == wx.WXK_F1:
            self.on_manual()
        elif physical_control_down(event) and key == wx.WXK_TAB:
            direction = -1 if event.ShiftDown() else 1
            selection = (
                self.notebook.GetSelection() + direction
            ) % self.notebook.GetPageCount()
            self.notebook.SetSelection(selection)
            self.notebook.SetFocus()
        elif key == wx.WXK_TAB:
            self.move_focus(backward=event.ShiftDown())
        elif physical_control_down(event) and key == ord(";"):
            self.adjust_volume(-5)
        elif physical_control_down(event) and key == ord("'"):
            self.adjust_volume(5)
        elif physical_control_down(event) and key == ord("["):
            self.seek(-5000)
        elif physical_control_down(event) and key == ord("]"):
            self.seek(5000)
        elif key == wx.WXK_F10 and event.ShiftDown():
            page = self.notebook.GetSelection()
            if page == 0:
                self.search.on_context_menu()
            elif page == 1:
                self.liked.on_context_menu()
            elif page == 2:
                self.queue.on_context_menu()
            elif page == 3:
                self.playlists.on_context_menu()
            elif page == 4:
                self.recently_played.on_context_menu()
            elif page == 5:
                self.bookmarks.on_context_menu()
        elif physical_control_down(event) and event.ShiftDown() and key in (ord("T"), ord("t")):
            self.announce_time("total")
        elif physical_control_down(event) and event.ShiftDown() and key in (ord("E"), ord("e")):
            self.announce_time("elapsed")
        elif physical_control_down(event) and event.ShiftDown() and key in (ord("R"), ord("r")):
            self.announce_time("remaining")
        elif physical_control_down(event) and event.ShiftDown() and key in (ord("N"), ord("n")):
            self.speak_current_track()
        elif physical_control_down(event) and event.ShiftDown() and key in (ord("U"), ord("u")):
            self.speak_up_next()
        elif (
            physical_control_down(event)
            and event.ShiftDown()
            and key in (ord("J"), ord("j"))
        ):
            self.choose_sleep_timer()
        elif physical_control_down(event) and key in (ord("J"), ord("j")):
            self.jump_to_time()
        elif physical_control_down(event) and key in (ord("Y"), ord("y")):
            self.show_lyrics()
        elif physical_control_down(event) and key in (ord("N"), ord("n")):
            self.create_playlist()
        elif physical_control_down(event) and key in (ord("R"), ord("r")):
            self.cycle_repeat()
        elif physical_control_down(event) and key in (ord("S"), ord("s")):
            self.toggle_shuffle()
        elif (
            physical_control_down(event)
            and key in (ord("P"), ord("p"))
            and isinstance(focused, ItemList)
        ):
            self.play_selected()
        elif (
            physical_control_down(event)
            and key in (ord("Q"), ord("q"))
            and isinstance(focused, ItemList)
        ):
            self.queue_selected(self.current_selected_item())
        elif (
            physical_control_down(event)
            and key in (ord("L"), ord("l"))
            and isinstance(focused, ItemList)
        ):
            self.toggle_like_selected()
        elif (
            physical_control_down(event)
            and event.ShiftDown()
            and key in (ord("A"), ord("a"))
            and isinstance(focused, ItemList)
        ):
            self.choose_playlist_for_selected()
        elif physical_control_down(event) and key in (ord("Z"), ord("z")):
            self.previous_track()
        elif (
            physical_control_down(event)
            and event.ShiftDown()
            and key in (ord("B"), ord("b"))
        ):
            self.save_current_bookmark()
        elif physical_control_down(event) and key in (ord("B"), ord("b")):
            self.next_track()
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            if focused is self.search.categories:
                logger.debug("Frame routed Enter from search category")
                self.search.on_search()
            elif focused is self.search.results:
                logger.debug("Frame routed Enter to search result action")
                self.search.on_open()
            elif focused is self.liked.items:
                self.liked.on_open()
            elif focused is self.queue.items:
                self.queue.on_open()
            elif focused is self.playlists.items:
                self.playlists.on_open()
            elif focused is self.recently_played.items:
                self.recently_played.on_open()
            elif focused is self.bookmarks.items:
                self.bookmarks.on_open()
            else:
                event.Skip()
        elif physical_control_down(event) and key in (ord("F"), ord("f")):
            self.notebook.SetSelection(0)
            self.search.focus_query()
        elif physical_control_down(event) and key == ord(","):
            self.on_preferences()
        elif physical_control_down(event) and ord("1") <= key <= ord("6"):
            self.notebook.SetSelection(key - ord("1"))
        elif event.AltDown() and key == wx.WXK_LEFT:
            if self.notebook.GetSelection() == 0 and self.search.go_back():
                return
            event.Skip()
        else:
            event.Skip()

    @staticmethod
    def global_hotkey_keycodes() -> dict[int, int]:
        if sys.platform == "win32":
            return {
                GLOBAL_HOTKEY_SEEK_BACKWARD: 0xDB,
                GLOBAL_HOTKEY_SEEK_FORWARD: 0xDD,
                GLOBAL_HOTKEY_VOLUME_DOWN: 0xBA,
                GLOBAL_HOTKEY_VOLUME_UP: 0xDE,
            }
        return {
            GLOBAL_HOTKEY_SEEK_BACKWARD: ord("["),
            GLOBAL_HOTKEY_SEEK_FORWARD: ord("]"),
            GLOBAL_HOTKEY_VOLUME_DOWN: ord(";"),
            GLOBAL_HOTKEY_VOLUME_UP: ord("'"),
        }

    def apply_global_hotkey_setting(self) -> None:
        self.unregister_global_hotkeys()
        if not self.global_seek_volume_hotkeys:
            return
        for hotkey_id, keycode in self.global_hotkey_keycodes().items():
            try:
                modifier = (
                    wx.MOD_RAW_CONTROL
                    if sys.platform == "darwin"
                    else wx.MOD_CONTROL
                )
                registered = self.RegisterHotKey(
                    hotkey_id,
                    modifier,
                    keycode,
                )
            except Exception:
                logger.exception("Could not register global hotkey %d", hotkey_id)
                registered = False
            if not registered:
                self.unregister_global_hotkeys()
                self.say(
                    "Global seek and volume shortcuts could not be registered. "
                    "Another application may already be using them."
                )
                return
            self.registered_hotkey_ids.append(hotkey_id)

    def unregister_global_hotkeys(self) -> None:
        for hotkey_id in self.registered_hotkey_ids:
            try:
                self.UnregisterHotKey(hotkey_id)
            except Exception:
                logger.exception("Could not unregister global hotkey %d", hotkey_id)
        self.registered_hotkey_ids.clear()

    def on_global_hotkey(self, event: wx.HotkeyEvent) -> None:
        actions = {
            GLOBAL_HOTKEY_SEEK_BACKWARD: lambda: self.seek(-5000),
            GLOBAL_HOTKEY_SEEK_FORWARD: lambda: self.seek(5000),
            GLOBAL_HOTKEY_VOLUME_DOWN: lambda: self.adjust_volume(-5),
            GLOBAL_HOTKEY_VOLUME_UP: lambda: self.adjust_volume(5),
        }
        action = actions.get(event.GetId())
        if action:
            action()

    def move_focus(self, *, backward: bool) -> None:
        """Move through every control in a predictable, wrapping tab loop."""
        page = self.notebook.GetSelection()
        if page == 0:
            controls: list[wx.Window] = [
                self.notebook,
                self.search.query,
                self.search.categories,
                self.search.search_button,
                self.search.results,
            ]
        elif page == 1:
            controls = [self.notebook, self.liked.items]
        elif page == 2:
            controls = [self.notebook, self.queue.items]
        elif page == 3:
            controls = [self.notebook, self.playlists.items]
        elif page == 4:
            controls = [self.notebook, self.recently_played.items]
        else:
            controls = [self.notebook, self.bookmarks.items]

        focused = wx.Window.FindFocus()
        try:
            index = controls.index(focused)
        except ValueError:
            index = 0 if backward else -1
        step = -1 if backward else 1
        target = controls[(index + step) % len(controls)]
        logger.debug(
            "%s Tab focus from %s to %s",
            "Backward" if backward else "Forward",
            type(focused).__name__ if focused else "none",
            type(target).__name__,
        )
        target.SetFocus()
        if isinstance(target, wx.TextCtrl):
            target.SelectAll()

    def using_local_player(self) -> bool:
        return bool(self.player and not self.remote_device_id)

    def playback_position_ms(self, track_id: str) -> int | None:
        item = self.current_player_item
        if not item or item.id != track_id:
            return None
        position_ms = int(self.current_player_state.get("progress_ms") or 0)
        if self.current_player_state.get("is_playing"):
            elapsed_ms = int(
                (time.monotonic() - self.playback_state_updated_at) * 1000
            )
            position_ms += max(0, elapsed_ms)
        if item.duration_ms:
            position_ms = min(position_ms, item.duration_ms)
        return max(0, position_ms)

    def choose_sleep_timer(self) -> None:
        choices = [
            "After current track",
            "After 15 minutes",
            "After 30 minutes",
            "After 60 minutes",
            "Cancel sleep timer",
        ]
        dialog = wx.SingleChoiceDialog(
            self,
            "Choose when playback should stop.",
            "Sleep timer",
            choices,
        )
        dialog.SetSelection(0)
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        selection = dialog.GetSelection()
        dialog.Destroy()
        if selection == 0:
            self.set_sleep_after_current_track()
        elif selection == 1:
            self.set_sleep_timer(15)
        elif selection == 2:
            self.set_sleep_timer(30)
        elif selection == 3:
            self.set_sleep_timer(60)
        else:
            self.cancel_sleep_timer()

    def set_sleep_after_current_track(self) -> None:
        if not self.current_player_item:
            self.say("No track is currently playing.")
            return
        self.sleep_timer.Stop()
        self.sleep_after_track_id = self.current_player_item.id
        self.synchronize_sleep_after_track(self.current_player_state)
        self.say("Sleep timer set for the end of the current track.")

    def synchronize_sleep_after_track(self, state: dict) -> None:
        if not self.sleep_after_track_id:
            return
        item = self.item_from_player_state(state)
        if not item or item.id != self.sleep_after_track_id:
            self.sleep_timer.Stop()
            return
        if not state.get("is_playing"):
            self.sleep_timer.Stop()
            return
        duration_ms = int((state.get("item") or {}).get("duration_ms") or 0)
        progress_ms = int(state.get("progress_ms") or 0)
        if duration_ms <= 0:
            self.sleep_timer.Stop()
            return
        self.sleep_timer.StartOnce(max(1, duration_ms - progress_ms))

    def on_sleep_timer(self) -> None:
        if not self.sleep_after_track_id:
            self.expire_sleep_timer()
            return
        if self.using_local_player():
            self.player.request_playback_state(self.finish_sleep_deadline)
            return
        self.run_task(
            None,
            self.spotify.playback_state,
            self.finish_sleep_deadline,
        )

    def finish_sleep_deadline(self, state: dict) -> None:
        item = self.item_from_player_state(state)
        if not item or item.id != self.sleep_after_track_id:
            self.expire_sleep_timer()
            return
        duration_ms = int((state.get("item") or {}).get("duration_ms") or 0)
        progress_ms = int(state.get("progress_ms") or 0)
        remaining_ms = max(0, duration_ms - progress_ms)
        if not state.get("is_playing"):
            self.sleep_timer.Stop()
        elif remaining_ms > 1_000:
            self.sleep_timer.StartOnce(remaining_ms)
        else:
            self.expire_sleep_timer()

    def set_sleep_timer(self, minutes: int) -> None:
        self.sleep_after_track_id = None
        if self.remote_device_id:
            self.remote_refresh_timer.Start(10_000)
        self.sleep_timer.StartOnce(minutes * 60 * 1000)
        self.say(f"Sleep timer set for {minutes} minutes.")

    def cancel_sleep_timer(self) -> None:
        active = self.sleep_timer.IsRunning() or bool(
            self.sleep_after_track_id
        )
        self.sleep_timer.Stop()
        self.sleep_after_track_id = None
        if self.remote_device_id:
            self.remote_refresh_timer.Start(10_000)
        self.say(
            "Sleep timer cancelled."
            if active
            else "No sleep timer is set."
        )

    def expire_sleep_timer(self) -> None:
        self.sleep_timer.Stop()
        self.sleep_after_track_id = None
        if self.remote_device_id:
            self.remote_refresh_timer.Start(10_000)
        device_id = self.player_device_id()
        if not device_id:
            return
        self.run_task(
            None,
            lambda: self.spotify.pause_playback(device_id),
            lambda result: self.say("Sleep timer. Playback stopped."),
        )

    def choose_playback_device(self) -> None:
        self.run_task(
            "Getting available devices.",
            self.spotify.available_devices,
            self.show_playback_devices,
        )

    def show_playback_devices(self, devices: list[dict]) -> None:
        if not devices:
            self.say(
                "No controllable Spotify devices are available. "
                "Open Spotify on the device and try again."
            )
            return
        labels = []
        selected = 0
        for index, device in enumerate(devices):
            parts = [
                str(device.get("name") or "Unnamed device"),
                str(device.get("type") or "device"),
            ]
            if device.get("is_active"):
                parts.append("active")
                selected = index
            volume = device.get("volume_percent")
            if volume is not None:
                parts.append(f"volume {volume} percent")
            labels.append(", ".join(parts))
        dialog = wx.SingleChoiceDialog(
            self,
            "Select the Spotify Connect device for playback.",
            "Choose playback device - BlindSpot",
            labels,
        )
        dialog.SetSelection(selected)
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        device = devices[dialog.GetSelection()]
        dialog.Destroy()
        device_id = str(device["id"])
        self.run_task(
            f"Transferring playback to {device.get('name', 'device')}.",
            lambda: self.spotify.transfer_playback(device_id, play=True),
            lambda result: self.finish_transfer_playback(device),
        )

    def finish_transfer_playback(self, device: dict) -> None:
        device_id = str(device["id"])
        self.shuffle_enabled = None
        self.repeat_state = None
        local_device_id = (
            "demo-device"
            if getattr(self.spotify, "demo_mode", False)
            else self.player.device_id if self.player else None
        )
        if local_device_id and device_id == local_device_id:
            self.remote_device_id = None
            self.remote_device_name = ""
            self.remote_supports_volume = None
            self.remote_refresh_timer.Stop()
        else:
            self.remote_device_id = device_id
            self.remote_device_name = str(device.get("name") or "device")
            self.remote_supports_volume = bool(
                device.get("supports_volume", True)
            )
            self.remote_refresh_timer.Start(10_000)
            wx.CallLater(750, self.refresh_remote_playback)
        self.say(f"Playing on {device.get('name', 'device')}.")

    def refresh_remote_playback(self) -> None:
        if not self.remote_device_id or self.remote_refresh_pending:
            return
        self.remote_refresh_pending = True

        def refresh() -> None:
            try:
                state = self.spotify.playback_state()
            except Exception:
                logger.exception("Could not refresh remote playback state")
                wx.CallAfter(self.finish_remote_refresh, None)
            else:
                wx.CallAfter(self.finish_remote_refresh, state)

        threading.Thread(
            target=refresh,
            name="BlindSpotRemotePlayback",
            daemon=True,
        ).start()

    def finish_remote_refresh(self, state: dict | None) -> None:
        self.remote_refresh_pending = False
        if state and self.remote_device_id:
            active_device = state.get("device") or {}
            active_id = active_device.get("id")
            local_id = self.player.device_id if self.player else None
            if active_id and local_id and active_id == local_id:
                self.remote_device_id = None
                self.remote_device_name = ""
                self.remote_supports_volume = None
                self.remote_refresh_timer.Stop()
                return
            if active_id:
                self.remote_device_id = str(active_id)
                self.remote_device_name = str(
                    active_device.get("name") or self.remote_device_name
                )
                self.remote_supports_volume = bool(
                    active_device.get("supports_volume", True)
                )
            self.apply_playback_update(state)

    def play(self, item: SpotifyItem) -> None:
        if self.remote_device_id:
            device_id = self.remote_device_id
        elif self.player:
            self.player.activate()
            if not self.player.ready:
                self.pending_play_item = item
                self.say(
                    f"BlindSpot's player is starting. "
                    f"{item.name} will play when it is ready."
                )
                self.player.provide_token()
                return
            device_id = self.player.device_id
        else:
            device_id = None
        self.run_task(
            f"Playing {item.name}",
            lambda: self.spotify.play(item, device_id=device_id),
            lambda result: self.on_play_started(item),
        )

    def play_in_context(
        self,
        context: SpotifyItem,
        item: SpotifyItem,
    ) -> None:
        if self.remote_device_id:
            device_id = self.remote_device_id
        elif self.player:
            self.player.activate()
            if not self.player.ready:
                self.pending_play_item = item
                self.pending_play_context = context
                self.say(
                    f"BlindSpot's player is starting. "
                    f"{item.name} will play when it is ready."
                )
                self.player.provide_token()
                return
            device_id = self.player.device_id
        else:
            device_id = "demo-device"
        self.run_task(
            f"Playing {item.name}",
            lambda: self.spotify.play_at(
                item,
                0,
                device_id,
                context.uri,
            ),
            lambda result: self.on_play_started(item),
        )

    def on_play_started(self, item: SpotifyItem) -> None:
        logger.info("Playback started kind=%s id=%s name=%r", item.kind, item.id, item.name)

    def current_selected_item(self) -> SpotifyItem | None:
        page = self.notebook.GetSelection()
        if page == 0:
            return self.search.results.selected_item()
        if page == 1:
            return self.liked.items.selected_item()
        if page == 2:
            return self.queue.items.selected_item()
        if page == 3:
            return self.playlists.items.selected_item()
        if page == 4:
            return self.recently_played.items.selected_item()
        if page == 5:
            return self.bookmarks.items.selected_item()
        return None

    def play_selected(self) -> None:
        item = self.current_selected_item()
        if not item:
            self.say("No item is selected.")
            return
        if item.kind == ItemKind.HEADING:
            self.say("Select a playable item.")
            return
        if self.notebook.GetSelection() == 5:
            self.resume_bookmark(item)
            return
        if item.container:
            self.play(item)
            return
        if (
            self.notebook.GetSelection() == 3
            and self.playlists.current_playlist
        ):
            self.play_in_context(self.playlists.current_playlist, item)
            return
        self.play(item)

    def player_device_id(self) -> str | None:
        if getattr(self.spotify, "demo_mode", False):
            return "demo-device"
        if self.remote_device_id:
            return self.remote_device_id
        if not self.player or not self.player.ready:
            self.say("BlindSpot's Spotify player is not ready.")
            return None
        self.player.activate()
        return self.player.device_id

    def toggle_playback(self) -> None:
        device_id = self.player_device_id()
        if not device_id:
            return
        if self.pending_resume:
            item, position_ms, context_uri = self.pending_resume
            self.pending_resume = None
            self.run_task(
                None,
                lambda: self.spotify.play_at(
                    item,
                    position_ms,
                    device_id,
                    context_uri,
                ),
                lambda result: logger.info(
                    "Resumed %r at %d ms",
                    item.name,
                    position_ms,
                ),
            )
            return
        if self.using_local_player():
            self.player.toggle_playback()
            return
        self.run_task(
            None,
            lambda: self.spotify.toggle_playback(device_id),
            lambda playing: logger.info(
                "Playback toggled; playing=%s",
                playing,
            ),
        )

    def seek(self, delta_ms: int) -> None:
        device_id = self.player_device_id()
        if not device_id:
            return
        if self.using_local_player():
            self.player.seek_relative(delta_ms)
            return
        self.run_task(
            None,
            lambda: self.spotify.seek_relative(delta_ms, device_id),
            lambda position: logger.info("Seeked to %d ms", position),
        )

    def adjust_volume(self, delta_percent: int) -> None:
        if self.remote_device_id and self.remote_supports_volume is False:
            self.say(
                f"{self.remote_device_name} does not support Spotify "
                "volume control."
            )
            return
        device_id = self.player_device_id()
        if not device_id:
            return
        if self.using_local_player():
            self.player.adjust_volume(
                delta_percent,
                lambda volume: self.say(f"{volume}%.")
                if volume is not None
                else None,
            )
            return
        self.run_task(
            None,
            lambda: self.spotify.adjust_volume(delta_percent, device_id),
            lambda volume: self.say(f"{volume}%."),
        )

    def announce_time(self, part: str) -> None:
        device_id = self.player_device_id()
        if not device_id:
            return
        if self.using_local_player():
            self.player.request_playback_state(
                lambda state: self.finish_announce_time(state, part)
            )
            return
        self.run_task(
            None,
            self.spotify.playback_state,
            lambda state: self.finish_announce_time(state, part),
        )

    def finish_announce_time(self, state: dict, part: str) -> None:
        item = state.get("item") or {}
        duration_ms = int(item.get("duration_ms") or 0)
        progress_ms = int(state.get("progress_ms") or 0)
        if not duration_ms:
            self.say("No track.")
            return
        values = {
            "total": duration_ms,
            "elapsed": progress_ms,
            "remaining": max(0, duration_ms - progress_ms),
        }
        self.say(f"{self.format_time(values[part])}.")

    def speak_current_track(self) -> None:
        if self.using_local_player():
            self.player.request_playback_state(self.finish_speak_current_track)
            return
        self.run_task(
            None,
            self.spotify.playback,
            lambda item: self.say(
                item.accessible_label()
                if item
                else "Nothing is currently playing."
            ),
        )

    def finish_speak_current_track(self, state: dict) -> None:
        item = self.item_from_player_state(state)
        self.say(
            item.accessible_label()
            if item
            else "Nothing is currently playing."
        )

    def speak_up_next(self) -> None:
        self.run_task(
            None,
            self.spotify.next_queued,
            lambda item: self.say(
                item.accessible_label()
                if item
                else "Queue empty."
            ),
        )

    def show_lyrics(self) -> None:
        item = self.current_player_item
        if not item:
            self.say("No track is currently playing.")
            return
        self.run_task(
            "Getting lyrics.",
            lambda: self.lyrics.lyrics_for(item),
            self.finish_show_lyrics,
        )

    def finish_show_lyrics(self, lyrics: Lyrics) -> None:
        if lyrics.instrumental:
            self.say("This track is instrumental.")
            return
        dialog = LyricsDialog(self, lyrics)
        dialog.ShowModal()
        dialog.Destroy()

    def toggle_shuffle(self) -> None:
        device_id = self.player_device_id()
        if not device_id:
            return
        if self.shuffle_enabled is None:
            operation = lambda: self.spotify.toggle_shuffle(device_id)
        else:
            enabled = not self.shuffle_enabled
            operation = lambda: self.spotify.set_shuffle(enabled, device_id)

        def completed(enabled: bool) -> None:
            self.shuffle_enabled = enabled
            self.say("Shuffle on." if enabled else "Shuffle off.")

        self.run_task(
            None,
            operation,
            completed,
        )

    def cycle_repeat(self) -> None:
        device_id = self.player_device_id()
        if not device_id:
            return
        labels = {
            "off": "Repeat off.",
            "context": "Repeat all.",
            "track": "Repeat one.",
        }
        if self.repeat_state is None:
            operation = lambda: self.spotify.cycle_repeat(device_id)
        else:
            state = {
                "off": "context",
                "context": "track",
                "track": "off",
            }[self.repeat_state]
            operation = lambda: self.spotify.set_repeat(state, device_id)

        def completed(state: str) -> None:
            self.repeat_state = state
            self.say(labels[state])

        self.run_task(
            None,
            operation,
            completed,
        )

    def jump_to_time(self) -> None:
        dialog = wx.TextEntryDialog(
            self,
            "Enter seconds, minutes and seconds, or hours, minutes and seconds.",
            "Jump to time",
        )
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        value = dialog.GetValue()
        dialog.Destroy()
        try:
            position_ms = self.parse_time(value)
        except ValueError:
            self.say("Enter a time such as 90, 1:30, or 1:02:30.")
            return
        device_id = self.player_device_id()
        if not device_id:
            return
        if self.using_local_player():
            self.player.seek_to(position_ms)
            return
        self.run_task(
            None,
            lambda: self.spotify.seek_to(position_ms, device_id),
            lambda position: logger.info("Jumped to %d ms", position),
        )

    @staticmethod
    def parse_time(value: str) -> int:
        parts = value.strip().split(":")
        if len(parts) in (2, 3) and parts[-1] == "":
            parts[-1] = "0"
        if not 1 <= len(parts) <= 3 or any(not part.isdigit() for part in parts):
            raise ValueError("Invalid time")
        numbers = [int(part) for part in parts]
        if len(numbers) > 1 and any(part >= 60 for part in numbers[1:]):
            raise ValueError("Invalid time")
        seconds = 0
        for number in numbers:
            seconds = seconds * 60 + number
        return seconds * 1000

    @staticmethod
    def format_time(milliseconds: int) -> str:
        minutes, seconds = divmod(max(0, milliseconds) // 1000, 60)
        return f"{minutes}:{seconds:02d}"

    @staticmethod
    def bookmark_position_label(milliseconds: int) -> str:
        minutes, seconds = divmod(max(0, milliseconds) // 1000, 60)
        minute_word = "minute" if minutes == 1 else "minutes"
        second_word = "second" if seconds == 1 else "seconds"
        return f"bookmarked at {minutes} {minute_word} {seconds} {second_word}"

    def bookmark_item_from_record(self, record: dict) -> SpotifyItem | None:
        if not record.get("bookmark_id") or not record.get("track_id"):
            return None
        position_ms = int(record.get("position_ms") or 0)
        raw = dict(record.get("track_raw") or {})
        raw["bookmark_id"] = str(record["bookmark_id"])
        raw["bookmark_position_ms"] = position_ms
        raw["bookmark_context_uri"] = str(record.get("context_uri") or "")
        raw["bookmark_position_label"] = self.bookmark_position_label(position_ms)
        return SpotifyItem(
            id=str(record["track_id"]),
            kind=ItemKind.TRACK,
            name=str(record.get("name") or "Untitled"),
            artist=str(record.get("artist") or ""),
            album=str(record.get("album") or ""),
            duration_ms=int(record.get("duration_ms") or 0),
            uri=str(record.get("uri") or ""),
            raw=raw,
        )

    def load_bookmarks(self) -> list[SpotifyItem]:
        records = self.store.read("bookmarks.json", []) or []
        if not isinstance(records, list):
            return []
        items = []
        for record in records:
            if not isinstance(record, dict):
                continue
            item = self.bookmark_item_from_record(record)
            if item:
                items.append(item)
        return items

    def save_current_bookmark(self) -> None:
        if self.using_local_player():
            self.player.request_playback_state(self.finish_save_current_bookmark)
            return
        self.run_task(
            None,
            self.spotify.playback_state,
            self.finish_save_current_bookmark,
        )

    def finish_save_current_bookmark(self, state: dict) -> None:
        item = self.item_from_player_state(state)
        if not item:
            self.say("No track is currently playing.")
            return
        position_ms = int(state.get("progress_ms") or 0)
        context_uri = str(state.get("context_uri") or "")
        if not context_uri:
            context_uri = str((state.get("context") or {}).get("uri") or "")
        record = {
            "bookmark_id": uuid.uuid4().hex,
            "track_id": item.id,
            "name": item.name,
            "artist": item.artist,
            "album": item.album,
            "duration_ms": item.duration_ms,
            "uri": item.uri,
            "position_ms": position_ms,
            "context_uri": context_uri,
            "track_raw": item.raw,
        }
        records = self.store.read("bookmarks.json", []) or []
        if not isinstance(records, list):
            records = []
        records.insert(0, record)
        self.store.write("bookmarks.json", records)
        bookmarked_item = self.bookmark_item_from_record(record)
        if self.bookmarks.loaded_once and bookmarked_item:
            items = [bookmarked_item, *self.bookmarks.items.items]
            self.bookmarks.items.set_items(items)
            self.bookmarks.status.SetLabel(f"{len(items)} items.")
        self.say(f"Bookmark saved at {self.format_time(position_ms)}.")

    def delete_bookmark(self, item: SpotifyItem) -> None:
        bookmark_id = str(item.raw.get("bookmark_id") or "")
        records = self.store.read("bookmarks.json", []) or []
        if isinstance(records, list):
            self.store.write(
                "bookmarks.json",
                [
                    record
                    for record in records
                    if not isinstance(record, dict)
                    or str(record.get("bookmark_id") or "") != bookmark_id
                ],
            )
        self.say("Bookmark deleted.")

    def resume_bookmark(self, item: SpotifyItem) -> None:
        device_id = self.player_device_id()
        if not device_id:
            return
        position_ms = int(item.raw.get("bookmark_position_ms") or 0)
        context_uri = str(item.raw.get("bookmark_context_uri") or "")
        self.run_task(
            None,
            lambda: self.spotify.play_at(
                item,
                position_ms,
                device_id,
                context_uri,
            ),
            lambda result: self.say(
                f"Resumed {item.name} at {self.format_time(position_ms)}."
            ),
        )

    def next_track(self) -> None:
        device_id = self.player_device_id()
        if not device_id:
            return
        if self.using_local_player():
            self.player.next_track()
            return
        self.run_task(
            None,
            lambda: self.spotify.next_track(device_id),
            lambda result: logger.info("Skipped to next track"),
        )

    def previous_track(self) -> None:
        device_id = self.player_device_id()
        if not device_id:
            return
        if self.using_local_player():
            self.player.previous_track()
            return
        self.run_task(
            None,
            lambda: self.spotify.previous_track(device_id),
            lambda result: logger.info("Returned to previous track"),
        )

    def open_tab(self, index: int) -> None:
        self.notebook.SetSelection(index)
        self.notebook.SetFocus()

    def toggle_like_selected(self) -> None:
        item = self.current_selected_item()
        if not item or not item.uri or item.container:
            item = self.current_player_item
        if not item or not item.uri:
            self.say("No item is selected.")
            return
        self.run_task(
            None,
            lambda: self.spotify.toggle_saved(item),
            lambda saved: self.finish_toggle_like(item, saved),
        )

    def finish_toggle_like(self, item: SpotifyItem, saved: bool) -> None:
        self.sync_liked_item(item, saved)
        self.say("Liked." if saved else "Unliked.")

    def choose_playlist_for_selected(self) -> None:
        item = self.current_selected_item()
        if not item or item.kind not in {ItemKind.TRACK, ItemKind.EPISODE}:
            self.say("Select a track or episode.")
            return
        self.run_task(
            None,
            self.spotify.user_playlists,
            lambda playlists: self.show_playlist_picker(
                item,
                [
                    playlist
                    for playlist in playlists
                    if playlist.raw.get("editable") is not False
                ],
            ),
        )

    def create_playlist(self) -> None:
        dialog = CreatePlaylistDialog(self)
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        name = dialog.name.GetValue().strip()
        public = dialog.public.GetValue()
        dialog.Destroy()
        self.run_task(
            None,
            lambda: self.spotify.create_playlist(name, public),
            self.finish_create_playlist,
        )

    def finish_create_playlist(self, playlist: SpotifyItem) -> None:
        if self.playlists.history.can_go_back:
            self.playlists.go_back()
        if self.playlists.loaded_once:
            items = self.playlists.history.current.items
            items.insert(0, playlist)
            self.playlists.history.current.selected = 0
            self.playlists.render(self.playlists.history.current, focus=False)
        self.notebook.SetSelection(3)
        self.playlists.items.SetFocus()

    def show_playlist_picker(
        self,
        item: SpotifyItem,
        playlists: list[SpotifyItem],
    ) -> None:
        if not playlists:
            self.say("No playlists.")
            return
        dialog = wx.SingleChoiceDialog(
            self,
            "Choose a playlist.",
            "Add to playlist",
            [playlist.accessible_label() for playlist in playlists],
        )
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        playlist = playlists[dialog.GetSelection()]
        dialog.Destroy()
        self.run_task(
            None,
            lambda: self.spotify.add_to_playlist(playlist, item),
            lambda result: self.say("Added."),
        )

    def sync_liked_item(self, item: SpotifyItem, saved: bool) -> None:
        if item.kind != ItemKind.TRACK:
            return
        matches = [
            index
            for index, existing in enumerate(self.liked.items.items)
            if existing.id == item.id
        ]
        if saved and not matches:
            self.liked.items.items.insert(0, item)
            self.liked.items.Insert(item.accessible_label(), 0)
        elif not saved:
            for index in reversed(matches):
                del self.liked.items.items[index]
                self.liked.items.Delete(index)
        self.liked.status.SetLabel(f"{len(self.liked.items.items)} items.")

    def on_player_ready(self, device_id: str) -> None:
        self.say("Ready.")
        if self.pending_play_item:
            item = self.pending_play_item
            context = self.pending_play_context
            self.pending_play_item = None
            self.pending_play_context = None
            if context:
                self.play_in_context(context, item)
            else:
                self.play(item)

    def on_playback_update(self, state: dict) -> None:
        if self.remote_device_id:
            return
        self.apply_playback_update(state)

    def apply_playback_update(self, state: dict) -> None:
        state = dict(state)
        if not state.get("context_uri"):
            context = state.get("context") or {}
            state["context_uri"] = context.get("uri", "")
        self.current_player_state = state
        self.playback_state_updated_at = time.monotonic()
        self.current_player_item = self.item_from_player_state(state)
        if (
            self.sleep_after_track_id
            and self.current_player_item
            and self.current_player_item.id != self.sleep_after_track_id
        ):
            wx.CallAfter(self.expire_sleep_timer)
        elif self.sleep_after_track_id:
            self.synchronize_sleep_after_track(state)
        if "shuffle_state" in state:
            self.shuffle_enabled = bool(state["shuffle_state"])
        if state.get("repeat_state") in {"off", "context", "track"}:
            self.repeat_state = state["repeat_state"]
        if self.current_player_item:
            self.pending_resume = None
            self.set_view_title(self.current_player_item.name)
            is_new_track = self.current_player_item.id != self.last_player_item_id
            self.last_player_item_id = self.current_player_item.id
            if self.announce_track_changes and is_new_track:
                announcement = self.current_player_item.name
                if self.current_player_item.artist:
                    announcement += f" by {self.current_player_item.artist}"
                self.say(announcement)
            if self.resume_mode != "none":
                self.store.write(
                    "playback.json",
                    playback_state_for_resume(state, self.resume_mode),
                )

    def load_pending_resume(self) -> None:
        if self.resume_mode == "none" or getattr(self.spotify, "demo_mode", False):
            return
        state = self.store.read("playback.json", {}) or {}
        item = self.item_from_player_state(state)
        if not item:
            return
        position_ms = (
            int(state.get("progress_ms") or 0)
            if self.resume_mode == "track_and_position"
            else 0
        )
        context_uri = str(state.get("context_uri") or "")
        self.current_player_item = item
        self.pending_resume = (item, position_ms, context_uri)
        self.last_player_item_id = item.id
        self.set_view_title(item.name)

    @staticmethod
    def item_from_player_state(state: dict) -> SpotifyItem | None:
        value = state.get("item") or {}
        if not value.get("id"):
            return None
        artists = ", ".join(
            artist.get("name", "")
            for artist in value.get("artists", [])
            if artist.get("name")
        )
        album = value.get("album") or {}
        return SpotifyItem(
            id=value["id"],
            kind=ItemKind.TRACK,
            name=value.get("name", "Untitled"),
            artist=artists,
            album=album.get("name", ""),
            duration_ms=int(value.get("duration_ms") or 0),
            uri=value.get("uri", ""),
            raw=value,
        )

    def on_player_error(self, message: str) -> None:
        self.say(message)
        logger.error("BlindSpot player: %s", message)

    def on_close(self, event: wx.CloseEvent) -> None:
        self.unregister_global_hotkeys()
        self.remote_refresh_timer.Stop()
        self.sleep_timer.Stop()
        if self.player:
            self.player.close()
            self.player = None
        event.Skip()

    def queue_selected(self, item: SpotifyItem | None) -> None:
        if not item or not item.uri or not item.playable:
            return
        self.run_task(
            None,
            lambda: self.spotify.add_to_queue(item),
            lambda result: self.finish_queue(item),
        )

    def finish_queue(self, item: SpotifyItem) -> None:
        if self.queue.loaded_once:
            self.queue.items.items.append(item)
            self.queue.items.Append(item.accessible_label())
            self.queue.status.SetLabel(f"{len(self.queue.items.items)} items.")
        self.say("Queued.")

    def like_selected(self, item: SpotifyItem | None) -> None:
        if not item or not item.uri:
            return
        self.run_task(
            None,
            lambda: self.spotify.save(item),
            lambda result: self.sync_liked_item(item, True),
        )

    def open_album_for_track(self, item: SpotifyItem) -> None:
        def load_album() -> tuple[SpotifyItem, list[SpotifyItem]]:
            album = self.spotify.album_for_track(item)
            return album, self.spotify.children(album)

        self.run_task(
            f"Opening album for {item.name}",
            load_album,
            lambda result: self.finish_open_album(*result),
        )

    def finish_open_album(
        self,
        album: SpotifyItem,
        tracks: list[SpotifyItem],
    ) -> None:
        self.notebook.SetSelection(0)
        self.search.history.push(ViewState(album.name, tracks))
        self.search.render(self.search.history.current, focus=True)
        self.say(f"{album.name}. {len(tracks)} items.")

    def popup_item_menu(
        self,
        owner: wx.Window,
        item: SpotifyItem,
        *,
        open_callback: Callable[[], None] | None = None,
        play_callback: Callable[[], None] | None = None,
        remove_callback: Callable[[], None] | None = None,
    ) -> None:
        menu = wx.Menu()
        actions: list[tuple[wx.MenuItem, Callable[[], None]]] = []
        if open_callback:
            actions.append((menu.Append(wx.ID_ANY, "&Open"), open_callback))
        if item.playable:
            actions.append(
                (
                    menu.Append(wx.ID_ANY, "&Play now"),
                    play_callback or (lambda: self.play(item)),
                )
            )
        if item.kind == ItemKind.TRACK:
            actions.append(
                (
                    menu.Append(wx.ID_ANY, "Open &album"),
                    lambda: self.open_album_for_track(item),
                )
            )
            if self.current_player_item and item.id == self.current_player_item.id:
                actions.append(
                    (
                        menu.Append(wx.ID_ANY, "Bookmark current &position"),
                        self.save_current_bookmark,
                    )
                )
        if item.playable and item.uri:
            actions.append(
                (
                    menu.Append(wx.ID_ANY, "Add to &queue"),
                    lambda: self.queue_selected(item),
                )
            )
            if remove_callback:
                menu.AppendSeparator()
                actions.append(
                    (
                        menu.Append(wx.ID_ANY, "&Remove from Liked Songs"),
                        remove_callback,
                    )
                )
            else:
                actions.append(
                    (
                        menu.Append(wx.ID_ANY, "&Save to library"),
                        lambda: self.like_selected(item),
                    )
                )
        for menu_item, callback in actions:
            menu.Bind(
                wx.EVT_MENU,
                lambda event, action=callback: action(),
                menu_item,
            )
        owner.PopupMenu(menu)
        menu.Destroy()
