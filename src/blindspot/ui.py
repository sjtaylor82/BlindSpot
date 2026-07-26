from __future__ import annotations

import logging
import sys
import threading
import time
import uuid
import webbrowser
from collections.abc import Callable
from pathlib import Path

import wx
import wx.dataview as dv
from accessible_output2.outputs.auto import Auto

from . import __version__
from . import messages as msg
from .auth_callback import CallbackServer
from .logging_setup import LOG_LEVELS, configure_logging
from .lyrics import LRCLibClient, Lyrics, LyricsUnavailable
from .models import ItemKind, SpotifyItem, ViewState
from .navigation import NavigationHistory
from .portable import PortableStore, resource_directory
from .podcasts import PodcastDownload, download_episode, find_episode_download
from .spotify import (
    REDIRECT_URI,
    PlaylistContentsUnavailable,
    RecentlyPlayedPermissionRequired,
    SpotifyClient,
    SpotifyError,
)
from .updates import (
    download_and_install,
    latest_release,
    newer_than,
    supports_automatic_update,
)
from .web_player import WebPlaybackController

logger = logging.getLogger("blindspot.ui")

SEARCH_LABELS = [
    "Songs",
    "Albums",
    "Artists",
    "Playlists",
    "Podcasts",
    "Podcast episodes",
    "Audiobooks",
    "All",
]
SEARCH_TYPES = [
    "track",
    "album",
    "artist",
    "playlist",
    "show",
    "episode",
    "audiobook",
    "all",
]
BRAILLE_LYRICS_TIMER_MS = 100
BRAILLE_LYRIC_LEAD_MS = 1_000
PREVIOUS_DOUBLE_PRESS_SECONDS = 0.5
ENTER_KEY_CODES = (10, 13, wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
DEVELOPER_DASHBOARD_URL = "https://developer.spotify.com/dashboard"
PAYPAL_DONATE_URL = (
    "https://www.paypal.com/donate?"
    "business=samtaylor9%40me.com&currency_code=AUD&item_name=BlindSpot"
)
GLOBAL_SHORTCUT_ACTIONS = (
    ("previous_track", "Previous track", 3101),
    ("pause_resume", "Pause or resume", 3102),
    ("next_track", "Next track", 3103),
    ("seek_backward", "Seek backward five seconds", 3104),
    ("seek_forward", "Seek forward five seconds", 3105),
    ("volume_down", "Volume down five percent", 3106),
    ("volume_up", "Volume up five percent", 3107),
    ("toggle_mute", "Mute or unmute", 3108),
)
GLOBAL_SHORTCUT_IDS = {
    action: hotkey_id
    for action, _, hotkey_id in GLOBAL_SHORTCUT_ACTIONS
}
RESUME_MODES = ("none", "track", "track_and_position")
RESUME_MODE_LABELS = (
    "Do not remember the last played track",
    "Remember the last played track",
    "Remember the last played track and position",
)


def space_belongs_to_control(window: wx.Window | None) -> bool:
    """Return whether the focused control should handle bare Space itself."""
    return isinstance(
        window,
        (
            wx.Button,
            wx.BitmapButton,
            wx.ToggleButton,
            wx.CheckBox,
            wx.RadioButton,
            wx.RadioBox,
            wx.TextCtrl,
            wx.ComboBox,
            wx.SearchCtrl,
            wx.SpinCtrl,
        ),
    )


def album_track_label(
    item: SpotifyItem,
    index: int,
    state: ViewState,
    multi_disc: bool,
) -> str:
    track_number = int(item.raw.get("track_number") or index + 1)
    disc_number = int(item.raw.get("disc_number") or 1)
    if multi_disc:
        label = f"Disc {disc_number} track {track_number} {item.name}"
    else:
        label = f"{track_number} {item.name}"

    album_artist_ids = set(state.parent_artist_ids)
    album_artist_names = {
        name.casefold() for name in state.parent_artist_names
    }
    track_artists = item.raw.get("artists") or []
    featured = []
    for artist in track_artists:
        name = str(artist.get("name") or "")
        artist_id = str(artist.get("id") or "")
        if not name:
            continue
        if artist_id and album_artist_ids:
            additional = artist_id not in album_artist_ids
        else:
            additional = name.casefold() not in album_artist_names
        if additional and name not in featured:
            featured.append(name)
    if not track_artists and item.artist:
        if item.artist.casefold() not in album_artist_names:
            featured.append(item.artist)
    if featured:
        label += f" — featuring {', '.join(featured)}"
    return label


def normalized_global_shortcuts(value: object) -> dict[str, dict[str, int]]:
    if not isinstance(value, dict):
        return {}
    shortcuts = {}
    for action, _, _ in GLOBAL_SHORTCUT_ACTIONS:
        shortcut = value.get(action)
        if not isinstance(shortcut, dict):
            continue
        try:
            modifiers = int(shortcut.get("modifiers", 0))
            keycode = int(shortcut["keycode"])
        except (KeyError, TypeError, ValueError):
            continue
        if keycode > 0:
            shortcuts[action] = {
                "modifiers": modifiers,
                "keycode": keycode,
            }
    return shortcuts


def shortcut_label(shortcut: dict[str, int] | None) -> str:
    if not shortcut:
        return "Not assigned"
    modifiers = int(shortcut.get("modifiers", 0))
    keycode = int(shortcut.get("keycode", 0))
    special_keys = {
        wx.WXK_MEDIA_PREV_TRACK: "Media Previous",
        wx.WXK_MEDIA_PLAY_PAUSE: "Media Play/Pause",
        wx.WXK_MEDIA_NEXT_TRACK: "Media Next",
        wx.WXK_MEDIA_STOP: "Media Stop",
        wx.WXK_VOLUME_MUTE: "Volume Mute",
        wx.WXK_VOLUME_DOWN: "Volume Down",
        wx.WXK_VOLUME_UP: "Volume Up",
        wx.WXK_SPACE: "Space",
        wx.WXK_RETURN: "Enter",
        wx.WXK_TAB: "Tab",
        wx.WXK_DELETE: "Delete",
        wx.WXK_BACK: "Backspace",
        wx.WXK_LEFT: "Left",
        wx.WXK_RIGHT: "Right",
        wx.WXK_UP: "Up",
        wx.WXK_DOWN: "Down",
        wx.WXK_HOME: "Home",
        wx.WXK_END: "End",
        wx.WXK_PAGEUP: "Page Up",
        wx.WXK_PAGEDOWN: "Page Down",
    }
    if wx.WXK_F1 <= keycode <= wx.WXK_F24:
        key_name = f"F{keycode - wx.WXK_F1 + 1}"
    elif keycode in special_keys:
        key_name = special_keys[keycode]
    elif 32 <= keycode < 127:
        key_name = chr(keycode).upper()
    else:
        key_name = f"Key {keycode}"
    parts = []
    if modifiers & wx.MOD_CONTROL:
        parts.append("Control")
    if modifiers & wx.MOD_ALT:
        parts.append("Alt")
    if modifiers & wx.MOD_SHIFT:
        parts.append("Shift")
    if modifiers & wx.MOD_WIN:
        parts.append("Windows")
    parts.append(key_name)
    return "+".join(parts)


def captured_shortcut(event: wx.KeyEvent) -> dict[str, int]:
    modifiers = int(event.GetModifiers())
    windows_down = bool(event.MetaDown())
    if sys.platform == "win32":
        windows_down = windows_down or bool(
            wx.GetKeyState(wx.WXK_WINDOWS_LEFT)
            or wx.GetKeyState(wx.WXK_WINDOWS_RIGHT)
        )
    if windows_down:
        modifiers |= wx.MOD_WIN
    return {
        "modifiers": modifiers,
        "keycode": int(event.GetKeyCode()),
    }


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
    if sys.platform != "darwin":
        return event.ControlDown()
    get_modifiers = getattr(event, "GetModifiers", None)
    if get_modifiers and bool(int(get_modifiers()) & wx.MOD_RAW_CONTROL):
        return True
    raw_control_down = getattr(event, "RawControlDown", None)
    if raw_control_down:
        return bool(raw_control_down())
    return bool(wx.GetKeyState(wx.WXK_RAW_CONTROL))


def menu_function_shortcut(
    shortcut: str,
    platform: str = sys.platform,
) -> str:
    return "" if platform == "darwin" else f"\t{shortcut}"


def native_text_positions(
    text: str,
    positions: list[int],
    platform: str = sys.platform,
) -> list[int]:
    if platform != "win32":
        return positions
    return [
        position + text[:position].count("\n")
        for position in positions
    ]


def window_is_or_descendant(
    window: wx.Window | None,
    ancestor: wx.Window,
) -> bool:
    while window:
        if window is ancestor:
            return True
        try:
            window = window.GetParent()
        except (AttributeError, RuntimeError):
            return False
    return False


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
            label=msg.SETUP_WELCOME,
        )
        instructions_label = wx.StaticText(
            self,
            label="Setup instructions",
        )
        instructions = wx.TextCtrl(
            self,
            value=msg.SETUP_INSTRUCTIONS,
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
                msg.PASTE_CLIENT_ID,
                "BlindSpot setup",
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            self.client_id.SetFocus()
            return
        event.Skip()

    def get_client_id(self) -> str:
        return self.client_id.GetValue().strip()


class ShortcutCaptureDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, action_label: str) -> None:
        super().__init__(parent, title=f"Assign global shortcut: {action_label}")
        self.shortcut: dict[str, int] | None = None
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(
            wx.StaticText(
                self,
                label=msg.shortcut_capture(action_label),
            ),
            0,
            wx.EXPAND | wx.ALL,
            16,
        )
        cancel = self.CreateSeparatedButtonSizer(wx.CANCEL)
        if cancel:
            outer.Add(cancel, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizerAndFit(outer)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key)

    def on_key(self, event: wx.KeyEvent) -> None:
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        if keycode in (
            wx.WXK_CONTROL,
            wx.WXK_SHIFT,
            wx.WXK_ALT,
            wx.WXK_RAW_CONTROL,
            wx.WXK_WINDOWS_LEFT,
            wx.WXK_WINDOWS_RIGHT,
        ):
            return
        self.shortcut = captured_shortcut(event)
        self.EndModal(wx.ID_OK)


class GlobalShortcutsDialog(wx.Dialog):
    def __init__(
        self,
        parent: wx.Window,
        shortcuts: dict[str, dict[str, int]],
    ) -> None:
        super().__init__(parent, title="Global keyboard shortcuts")
        self.shortcuts = {
            action: dict(shortcut)
            for action, shortcut in normalized_global_shortcuts(shortcuts).items()
        }
        outer = wx.BoxSizer(wx.VERTICAL)
        self.actions = wx.ListBox(self, choices=self.action_choices())
        if self.actions.GetCount():
            self.actions.SetSelection(0)
        outer.Add(
            self.actions,
            1,
            wx.EXPAND | wx.ALL,
            12,
        )
        action_buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.assign = wx.Button(self, label="&Assign shortcut...")
        self.clear = wx.Button(self, label="&Clear shortcut")
        action_buttons.Add(self.assign, 0, wx.RIGHT, 8)
        action_buttons.Add(self.clear)
        outer.Add(
            action_buttons,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        buttons = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        if buttons:
            outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizerAndFit(outer)
        self.SetMinSize((550, 400))
        self.assign.Bind(wx.EVT_BUTTON, self.on_assign)
        self.clear.Bind(wx.EVT_BUTTON, self.on_clear)
        self.actions.Bind(wx.EVT_LISTBOX_DCLICK, self.on_assign)
        self.actions.SetFocus()

    def action_choices(self) -> list[str]:
        return [
            f"{label}: {shortcut_label(self.shortcuts.get(action))}"
            for action, label, _ in GLOBAL_SHORTCUT_ACTIONS
        ]

    def refresh_choices(self, selected: int) -> None:
        self.actions.Set(self.action_choices())
        self.actions.SetSelection(selected)

    def on_assign(self, event: wx.Event) -> None:
        selected = self.actions.GetSelection()
        if selected == wx.NOT_FOUND:
            return
        action, label, _ = GLOBAL_SHORTCUT_ACTIONS[selected]
        capture = ShortcutCaptureDialog(self, label)
        if capture.ShowModal() == wx.ID_OK and capture.shortcut:
            duplicate = next(
                (
                    other_action
                    for other_action, shortcut in self.shortcuts.items()
                    if other_action != action and shortcut == capture.shortcut
                ),
                None,
            )
            if duplicate:
                other_label = next(
                    value
                    for value_action, value, _ in GLOBAL_SHORTCUT_ACTIONS
                    if value_action == duplicate
                )
                answer = wx.MessageBox(
                    msg.shortcut_replace(
                        shortcut_label(capture.shortcut),
                        other_label,
                    ),
                    "Global keyboard shortcuts",
                    wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
                    self,
                )
                if answer != wx.YES:
                    capture.Destroy()
                    return
                self.shortcuts.pop(duplicate, None)
            self.shortcuts[action] = dict(capture.shortcut)
            self.refresh_choices(selected)
        capture.Destroy()

    def on_clear(self, event: wx.Event) -> None:
        selected = self.actions.GetSelection()
        if selected == wx.NOT_FOUND:
            return
        action = GLOBAL_SHORTCUT_ACTIONS[selected][0]
        self.shortcuts.pop(action, None)
        self.refresh_choices(selected)


class PreferencesDialog(wx.Dialog):
    def __init__(
        self,
        parent: wx.Window,
        logging_level: str,
        announce_track_changes: bool,
        resume_mode: str,
        global_shortcuts: dict[str, dict[str, int]],
        save_global_shortcuts: (
            Callable[[dict[str, dict[str, int]]], None] | None
        ) = None,
        open_logs_folder: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, title="BlindSpot preferences")
        self.save_global_shortcuts = save_global_shortcuts
        self.open_logs_folder_callback = open_logs_folder
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
        self.global_shortcuts = normalized_global_shortcuts(global_shortcuts)
        self.configure_global_shortcuts = wx.Button(
            self,
            label="Configure &global keyboard shortcuts...",
        )
        outer.Add(
            self.configure_global_shortcuts,
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
        self.open_logs_folder = wx.Button(
            self,
            label="Open &logs folder",
        )
        outer.Add(
            self.open_logs_folder,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        buttons = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        if buttons:
            outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizerAndFit(outer)
        self.configure_global_shortcuts.Bind(
            wx.EVT_BUTTON,
            self.on_global_shortcuts,
        )
        self.open_logs_folder.Bind(
            wx.EVT_BUTTON,
            self.on_open_logs_folder,
        )
        self.announce_track_changes.SetFocus()

    def on_global_shortcuts(self, event: wx.Event) -> None:
        dialog = GlobalShortcutsDialog(self, self.global_shortcuts)
        if dialog.ShowModal() == wx.ID_OK:
            self.global_shortcuts = {
                action: dict(shortcut)
                for action, shortcut in dialog.shortcuts.items()
            }
            if self.save_global_shortcuts:
                self.save_global_shortcuts(self.get_global_shortcuts())
        dialog.Destroy()

    def get_logging_level(self) -> str:
        return self.logging_level.GetStringSelection()

    def on_open_logs_folder(self, event: wx.Event) -> None:
        if self.open_logs_folder_callback:
            self.open_logs_folder_callback()

    def get_announce_track_changes(self) -> bool:
        return self.announce_track_changes.GetValue()

    def get_resume_mode(self) -> str:
        return RESUME_MODES[self.resume_mode.GetSelection()]

    def get_global_shortcuts(self) -> dict[str, dict[str, int]]:
        return {
            action: dict(shortcut)
            for action, shortcut in self.global_shortcuts.items()
        }


class LyricsDialog(wx.Dialog):
    def __init__(
        self,
        parent: "MainFrame",
        lyrics: Lyrics,
        item: SpotifyItem,
    ) -> None:
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
            label="Follow playback on braille display",
        )
        self.follow_braille.Enable(bool(lyrics.synced_lines))
        self.follow_braille.SetValue(
            bool(
                lyrics.synced_lines
                and parent.follow_braille_lyrics
            )
        )
        outer.Add(
            self.follow_braille,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        self.text = wx.TextCtrl(
            self,
            value=lyrics.text,
            style=wx.TE_MULTILINE | wx.TE_READONLY,
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
        self.item = item
        self.track_id = lyrics.track_id
        self.synced_lines = lyrics.synced_lines
        self.synced_line_positions = self._synced_line_positions(
            lyrics.text,
            lyrics.synced_lines,
        )
        self.synced_line_positions = native_text_positions(
            lyrics.text,
            self.synced_line_positions,
        )
        self.lyric_adjustment_ms = parent.lyric_adjustment_ms(lyrics.track_id)
        self.last_braille_line = -1
        self.braille_timer = wx.Timer(self)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_dialog_key)
        self.Bind(wx.EVT_CHECKBOX, self.on_follow_braille, self.follow_braille)
        self.Bind(wx.EVT_TIMER, self.on_braille_timer, self.braille_timer)
        self.Bind(wx.EVT_BUTTON, self.on_close_button, id=wx.ID_CLOSE)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.text.Bind(wx.EVT_KEY_DOWN, self.on_text_key)
        self.text.SetInsertionPoint(0)
        self.text.SetFocus()
        if self.follow_braille.GetValue():
            self.braille_timer.Start(BRAILLE_LYRICS_TIMER_MS)
            self.update_braille_line()

    @staticmethod
    def _synced_line_positions(
        lyrics_text: str,
        synced_lines: list[tuple[int, str]],
    ) -> list[int]:
        display_lines = []
        position = 0
        for line in lyrics_text.splitlines(keepends=True):
            display_lines.append((position, " ".join(line.split()).casefold()))
            position += len(line)
        positions = []
        next_display_line = 0
        for index, (_, lyric) in enumerate(synced_lines):
            wanted = " ".join(lyric.split()).casefold()
            match = next(
                (
                    line_index
                    for line_index in range(next_display_line, len(display_lines))
                    if display_lines[line_index][1] == wanted
                ),
                None,
            )
            if match is not None:
                positions.append(display_lines[match][0])
                next_display_line = match + 1
            elif index < len(display_lines):
                positions.append(display_lines[index][0])
            else:
                positions.append(len(lyrics_text))
        return positions

    def on_follow_braille(self, event: wx.CommandEvent) -> None:
        enabled = self.follow_braille.GetValue()
        self.frame.set_follow_braille_lyrics(enabled)
        if enabled:
            self.last_braille_line = -1
            self.braille_timer.Start(BRAILLE_LYRICS_TIMER_MS)
            self.update_braille_line()
        else:
            self.braille_timer.Stop()

    def on_text_key(self, event: wx.KeyEvent) -> None:
        if (
            event.GetKeyCode() == wx.WXK_SPACE
            and not event.AltDown()
            and not event.ShiftDown()
            and physical_control_down(event)
        ):
            LyricsDialog.playback_from_selected_lyric(self)
            return
        if (
            event.GetKeyCode() == wx.WXK_SPACE
            and not event.AltDown()
            and not event.ShiftDown()
        ):
            self.frame.toggle_pause_resume()
            return
        if not physical_control_down(event):
            event.Skip()
            return
        key = event.GetKeyCode()
        if (
            key in (wx.WXK_UP, wx.WXK_DOWN)
            and not event.AltDown()
            and not event.ShiftDown()
        ):
            direction = -1 if key == wx.WXK_UP else 1
            LyricsDialog.playback_from_adjacent_lyric(self, direction)
            return
        if event.ShiftDown() and key in (ord(","), ord("<")):
            self.adjust_lyric_timing(500)
            return
        if event.ShiftDown() and key in (ord("."), ord(">")):
            self.adjust_lyric_timing(-500)
            return
        event.Skip()

    def on_dialog_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if (
            key in (wx.WXK_UP, wx.WXK_DOWN)
            and physical_control_down(event)
            and not event.AltDown()
            and not event.ShiftDown()
        ):
            direction = -1 if key == wx.WXK_UP else 1
            LyricsDialog.playback_from_adjacent_lyric(self, direction)
            return
        if (
            key == wx.WXK_SPACE
            and not event.AltDown()
            and not event.ShiftDown()
            and physical_control_down(event)
        ):
            LyricsDialog.playback_from_selected_lyric(self)
            return
        if (
            key == wx.WXK_SPACE
            and not event.AltDown()
            and not event.ShiftDown()
            and event.GetEventObject() is getattr(self, "text", None)
        ):
            self.frame.toggle_pause_resume()
            return
        if (
            key == wx.WXK_F4
            and physical_control_down(event)
            and not event.AltDown()
            and not event.ShiftDown()
        ):
            self.frame.toggle_mute()
            return
        if (
            key == wx.WXK_F4
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
        ):
            self.frame.play(self.item, announce=False)
            return
        if (
            key == wx.WXK_F5
            and physical_control_down(event)
            and not event.AltDown()
            and not event.ShiftDown()
        ):
            self.frame.adjust_volume(-5)
            return
        if (
            key == wx.WXK_F6
            and physical_control_down(event)
            and not event.AltDown()
            and not event.ShiftDown()
        ):
            self.frame.adjust_volume(5)
            return
        if (
            key == wx.WXK_F5
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
        ):
            self.frame.seek(-5000)
            return
        if (
            key == wx.WXK_F6
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
        ):
            self.frame.seek(5000)
            return
        if (
            key == wx.WXK_F7
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
        ):
            self.frame.previous_track()
            return
        if (
            key == wx.WXK_F8
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
        ):
            self.frame.toggle_pause_resume()
            return
        if (
            key == wx.WXK_F9
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
        ):
            self.frame.next_track()
            return
        event.Skip()

    def selected_synced_line_index(self) -> int | None:
        if not getattr(self, "synced_lines", None):
            return None
        insertion_point = self.text.GetInsertionPoint()
        selected = None
        for index, position in enumerate(self.synced_line_positions):
            if position > insertion_point:
                break
            selected = index
        return selected

    def playback_from_selected_lyric(self) -> None:
        if not getattr(self, "synced_lines", None):
            self.frame.say(msg.SYNCED_LYRICS_UNAVAILABLE)
            return
        line_index = LyricsDialog.selected_synced_line_index(self)
        if line_index is None:
            self.frame.say(msg.MOVE_TO_SYNCED_LINE)
            return
        timestamp_ms = self.synced_lines[line_index][0]
        if self.frame.current_track_is_paused(self.track_id):
            self.frame.resume_from_lyric(self.track_id, timestamp_ms)
        else:
            self.frame.play_from_lyric(self.item, timestamp_ms)

    def playback_from_adjacent_lyric(self, direction: int) -> None:
        if not getattr(self, "synced_lines", None):
            self.frame.say(msg.SYNCED_LYRICS_UNAVAILABLE)
            return
        selected = LyricsDialog.selected_synced_line_index(self)
        target = 0 if selected is None else selected + direction
        if not 0 <= target < len(self.synced_lines):
            boundary = "First" if direction < 0 else "Last"
            self.frame.say(msg.lyric_boundary(boundary))
            return
        position = self.synced_line_positions[target]
        self.text.SetInsertionPoint(position)
        self.text.ShowPosition(position)
        timestamp_ms = self.synced_lines[target][0]
        if self.frame.current_track_is_paused(self.track_id):
            self.frame.resume_from_lyric(self.track_id, timestamp_ms)
        else:
            self.frame.play_from_lyric(self.item, timestamp_ms)

    def adjust_lyric_timing(self, delta_ms: int) -> None:
        self.lyric_adjustment_ms += delta_ms
        self.frame.set_lyric_adjustment_ms(
            self.track_id,
            self.lyric_adjustment_ms,
        )
        effective_lead_ms = BRAILLE_LYRIC_LEAD_MS + self.lyric_adjustment_ms
        if effective_lead_ms >= 0:
            timing = f"{effective_lead_ms / 1000:g} seconds early"
        else:
            timing = f"{abs(effective_lead_ms) / 1000:g} seconds late"
        self.frame.say(msg.lyric_timing(timing))
        self.last_braille_line = -1
        self.update_braille_line()

    def on_braille_timer(self, event: wx.TimerEvent) -> None:
        self.update_braille_line()

    def update_braille_line(self) -> None:
        position_ms = self.frame.playback_position_ms(self.track_id)
        if position_ms is None:
            # Keep following armed while this song has not started yet. The
            # timer will pick up its playback position as soon as it begins.
            return
        position_ms += BRAILLE_LYRIC_LEAD_MS + self.lyric_adjustment_ms
        line_index = -1
        for index, (timestamp_ms, text) in enumerate(self.synced_lines):
            if timestamp_ms > position_ms:
                break
            line_index = index
        if line_index < 0:
            return
        if line_index == self.last_braille_line:
            return
        self.last_braille_line = line_index
        try:
            line = self.synced_lines[line_index][1]
            if sys.platform in ("win32", "darwin"):
                # Let the screen reader follow the caret instead of sending
                # transient output messages, which interrupt braille reading.
                position = self.synced_line_positions[line_index]
                self.text.SetInsertionPoint(position)
                self.text.ShowPosition(position)
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


ITEM_LIST_USES_DATAVIEW = sys.platform == "darwin"
ItemListBase = dv.DataViewListCtrl if ITEM_LIST_USES_DATAVIEW else wx.ListCtrl


class ItemList(ItemListBase):
    ACTIVATED_EVENT = (
        dv.EVT_DATAVIEW_ITEM_ACTIVATED
        if ITEM_LIST_USES_DATAVIEW
        else wx.EVT_LIST_ITEM_ACTIVATED
    )

    def __init__(self, parent: wx.Window) -> None:
        if ITEM_LIST_USES_DATAVIEW:
            super().__init__(
                parent,
                style=dv.DV_MULTIPLE | dv.DV_NO_HEADER,
            )
            self.AppendTextColumn("")
        else:
            super().__init__(
                parent,
                style=wx.LC_REPORT | wx.LC_NO_HEADER,
            )
            self.InsertColumn(0, "")
        self.SetName("Items")
        self.items: list[SpotifyItem] = []
        self.Bind(wx.EVT_SIZE, self.on_size)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)

    def on_char_hook(self, event: wx.KeyEvent) -> None:
        panel = self.GetParent()
        frame = getattr(panel, "frame", None)
        if frame:
            # macOS DataView controls consume keyboard chords before their
            # containing frame sees them. Route every key through the same
            # global dispatcher used by the rest of the interface.
            frame.on_global_key(event)
        else:
            event.Skip()

    def on_size(self, event: wx.SizeEvent) -> None:
        width = self.GetClientSize().width
        if width > 0:
            if ITEM_LIST_USES_DATAVIEW:
                self.GetColumn(0).SetWidth(width)
            else:
                self.SetColumnWidth(0, width)
        event.Skip()

    def set_items(
        self,
        items: list[SpotifyItem],
        selected: int = 0,
        *,
        labels: list[str] | None = None,
    ) -> None:
        self.items = items
        self.Freeze()
        try:
            self.DeleteAllItems()
            for index, item in enumerate(items):
                label = labels[index] if labels is not None else item.accessible_label()
                if ITEM_LIST_USES_DATAVIEW:
                    self.AppendItem([label])
                else:
                    self.InsertItem(index, label)
        finally:
            self.Thaw()
        if items:
            self.SetSelection(min(max(0, selected), len(items) - 1))

    def SetSelection(self, index: int) -> None:
        if ITEM_LIST_USES_DATAVIEW:
            self.UnselectAll()
            if 0 <= index < len(self.items):
                item = self.RowToItem(index)
                self.SelectRow(index)
                self.SetCurrentItem(item)
                self.EnsureVisible(item)
            return
        state_mask = wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED
        for row in range(self.GetItemCount()):
            self.SetItemState(row, 0, state_mask)
        if 0 <= index < len(self.items):
            self.SetItemState(index, state_mask, state_mask)
            self.EnsureVisible(index)

    def GetSelection(self) -> int:
        if ITEM_LIST_USES_DATAVIEW:
            current = self.ItemToRow(self.GetCurrentItem())
            return current if current >= 0 else self.GetSelectedRow()
        focused = self.GetNextItem(
            -1,
            wx.LIST_NEXT_ALL,
            wx.LIST_STATE_FOCUSED,
        )
        return focused if focused >= 0 else self.GetFirstSelected()

    def GetSelections(self) -> list[int]:
        if ITEM_LIST_USES_DATAVIEW:
            return [
                row
                for item in super().GetSelections()
                if (row := self.ItemToRow(item)) >= 0
            ]
        selected = []
        row = self.GetFirstSelected()
        while row >= 0:
            selected.append(row)
            row = self.GetNextSelected(row)
        return selected

    def Append(self, label: str) -> None:
        if ITEM_LIST_USES_DATAVIEW:
            self.AppendItem([label])
        else:
            self.InsertItem(self.GetItemCount(), label)

    def Insert(self, label: str, index: int) -> None:
        if ITEM_LIST_USES_DATAVIEW:
            self.InsertItem(index, [label])
        else:
            self.InsertItem(index, label)

    def Delete(self, index: int) -> None:
        super().DeleteItem(index)

    def SetString(self, index: int, label: str) -> None:
        if ITEM_LIST_USES_DATAVIEW:
            self.SetValue(label, index, 0)
        else:
            self.SetItem(index, 0, label)

    def selected_item(self) -> SpotifyItem | None:
        index = self.GetSelection()
        return self.items[index] if 0 <= index < len(self.items) else None

    def marked_items(self) -> list[SpotifyItem]:
        return [
            self.items[index]
            for index in self.GetSelections()
            if 0 <= index < len(self.items)
        ]

    def remove_at(self, index: int) -> None:
        if not 0 <= index < len(self.items):
            return
        del self.items[index]
        self.Delete(index)
        if self.items:
            self.SetSelection(min(index, len(self.items) - 1))


def item_list_ancestor(window: wx.Window | None) -> ItemList | None:
    while window:
        if isinstance(window, ItemList):
            return window
        try:
            window = window.GetParent()
        except (AttributeError, RuntimeError):
            return None
    return None


def radio_box_ancestor(window: wx.Window | None) -> wx.RadioBox | None:
    while window:
        if isinstance(window, wx.RadioBox):
            return window
        try:
            window = window.GetParent()
        except (AttributeError, RuntimeError):
            return None
    return None


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
        self.results.SetName("Search results")
        self.status = wx.StaticText(self, label=msg.ENTER_SEARCH_QUERY)

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
        self.results.Bind(self.results.ACTIVATED_EVENT, self.on_open)
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
            self.frame.say(msg.ENTER_SEARCH_QUERY)
            self.query.SetFocus()
            return
        category = SEARCH_TYPES[self.categories.GetSelection()]
        self.frame.run_task(
            msg.SEARCHING_SPOTIFY,
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
        result_count = sum(
            item.kind != ItemKind.HEADING for item in items
        )
        if not result_count:
            self.frame.say(msg.result_count(result_count, query))
            self.query.SetFocus()

    def on_open(self, event: wx.Event | None = None) -> None:
        item = self.results.selected_item()
        if not item:
            return
        if item.raw.get("load_more"):
            self.load_more(item)
            return
        if item.kind == ItemKind.HEADING:
            return
        logger.info(
            "Opening search result kind=%s id=%s name=%r",
            item.kind,
            item.id,
            item.name,
        )
        self.history.remember_selection(self.results.GetSelection())
        if item.playable:
            self.frame.play_playable_item(item)
        elif item.container:
            self.frame.run_task(
                msg.opening(item.name),
                lambda: self.frame.spotify.children(item),
                lambda items: self.open_children(item, items),
            )

    def load_more(self, item: SpotifyItem) -> None:
        state = self.history.current
        offset = int(item.raw.get("next_offset") or 0)
        self.frame.run_task(
            msg.LOADING_MORE_RESULTS,
            lambda: self.frame.spotify.search(
                state.query,
                state.category,
                offset,
            ),
            lambda items: (
                self.append_search_results(items)
                if self.history.current is state
                else None
            ),
        )

    def append_search_results(self, items: list[SpotifyItem]) -> None:
        state = self.history.current
        existing = [
            item for item in state.items if not item.raw.get("load_more")
        ]
        new_results = list(items)
        result_count = sum(
            item.kind != ItemKind.HEADING for item in new_results
        )
        first_new = len(existing)
        state.items[:] = existing + new_results
        state.selected = first_new if result_count else max(0, first_new - 1)
        self.render(state, focus=True)
        if not result_count:
            self.frame.say(msg.NO_MORE_RESULTS)

    def open_children(self, parent: SpotifyItem, items: list[SpotifyItem]) -> None:
        logger.info("Displaying %d children for %r", len(items), parent.name)
        parent_artists = parent.raw.get("artists") or []
        parent_artist_names = tuple(
            artist.get("name", "")
            for artist in parent_artists
            if artist.get("name")
        )
        parent_artist_ids = tuple(
            artist.get("id", "")
            for artist in parent_artists
            if artist.get("id")
        )
        if not parent_artist_names and parent.artist:
            parent_artist_names = (parent.artist,)
        self.history.push(
            ViewState(
                parent.name,
                items,
                parent_id=parent.id,
                parent_kind=parent.kind,
                parent_artist_names=parent_artist_names,
                parent_artist_ids=parent_artist_ids,
            )
        )
        self.render(self.history.current, focus=True)
        if not items:
            self.frame.say(msg.named_item_count(parent.name, 0))

    def go_back(self) -> bool:
        return_from_album = getattr(
            self.frame,
            "return_from_open_album",
            None,
        )
        if return_from_album and return_from_album(self.history.current):
            return True
        if not self.history.can_go_back:
            return False
        state = self.history.back()
        self.render(state, focus=True)
        return True

    def render(self, state: ViewState, *, focus: bool) -> None:
        self.heading.SetLabel(state.title)
        self.frame.update_title_for_page(self, state.title)
        if state.parent_kind == ItemKind.ALBUM:
            multi_disc = any(
                int(item.raw.get("disc_number") or 1) > 1
                for item in state.items
            )
            labels = [
                album_track_label(item, index, state, multi_disc)
                for index, item in enumerate(state.items)
            ]
            self.results.set_items(
                state.items,
                state.selected,
                labels=labels,
            )
        else:
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
        elif (
            key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
            and physical_control_down(event)
        ):
            self.frame.open_selected_track_album(
                self.results.selected_item()
            )
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.on_open()
        elif key == wx.WXK_BACK:
            if not self.go_back():
                self.focus_query()
        elif physical_control_down(event) and key in (ord("Q"), ord("q")):
            self.frame.queue_from_list(self.results)
        elif physical_control_down(event) and key in (ord("L"), ord("l")):
            self.frame.toggle_like_item(self.results.selected_item())
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
            include_album_action=(
                self.history.current.parent_kind != ItemKind.ALBUM
            ),
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
        self.items.SetName(title)
        self.status = wx.StaticText(self, label=msg.load_hint(title))
        outer.Add(self.heading, 0, wx.ALL, 10)
        outer.Add(self.items, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        outer.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(outer)
        self.items.Bind(self.items.ACTIVATED_EVENT, self.on_open)
        self.items.Bind(wx.EVT_KEY_DOWN, self.on_key)
        self.items.Bind(wx.EVT_CONTEXT_MENU, self.on_context_menu)
        self.items.Bind(wx.EVT_NAVIGATION_KEY, self.on_navigation)
        self.items.Bind(wx.EVT_SET_FOCUS, self.on_list_focus)

    def refresh(self) -> None:
        if self.loading:
            return
        self.loading = True
        self.frame.run_task(
            None if self.silent_load else msg.loading(self.title),
            self.loader,
            self.show_items,
            failure=self.finish_load_error,
        )

    def show_items(self, items: list[SpotifyItem]) -> None:
        self.loading = False
        self.loaded_once = True
        self.frame.update_title_for_page(self, self.title)
        self.items.set_items(items)
        self.status.SetLabel(msg.item_count(len(items)))

    def on_list_focus(self, event: wx.FocusEvent) -> None:
        event.Skip()
        if self.load_on_first_focus and not self.loaded_once and not self.loading:
            wx.CallAfter(self.refresh)

    def finish_load_error(self) -> None:
        self.loading = False

    def on_open(self, event: wx.Event | None = None) -> None:
        item = self.items.selected_item()
        if item:
            self.frame.play_playable_item(item)

    def on_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if key == wx.WXK_TAB and not event.ShiftDown():
            self.frame.focus_tab_bar()
        elif (
            key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
            and physical_control_down(event)
        ):
            self.frame.open_selected_track_album(
                self.items.selected_item()
            )
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.on_open()
        elif key == wx.WXK_DELETE and self.removable:
            self.remove_selected()
        elif physical_control_down(event) and key in (ord("Q"), ord("q")):
            self.frame.queue_from_list(self.items)
        elif physical_control_down(event) and key in (ord("L"), ord("l")):
            self.frame.toggle_like_item(self.items.selected_item())
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
        self.status.SetLabel(msg.item_count(len(self.items.items)))
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
        self.status.SetLabel(msg.item_count(len(self.items.items)))
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
    def __init__(
        self,
        parent: wx.Window,
        frame: "MainFrame",
        title: str = "Playlists",
    ) -> None:
        super().__init__(parent)
        self.frame = frame
        self.title = title
        self.history = NavigationHistory(ViewState(title, []))
        self.current_playlist: SpotifyItem | None = None
        self.pending_playlist_selection_id: str | None = None
        self.loaded_once = False
        self.loading = False

        outer = wx.BoxSizer(wx.VERTICAL)
        self.heading = wx.StaticText(self, label=title)
        self.items = ItemList(self)
        self.items.SetName(title)
        self.status = wx.StaticText(self, label=msg.PLAYLISTS_LOAD_HINT)
        outer.Add(self.heading, 0, wx.ALL, 10)
        outer.Add(self.items, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        outer.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(outer)

        self.items.Bind(wx.EVT_SET_FOCUS, self.on_focus)
        self.items.Bind(wx.EVT_KEY_DOWN, self.on_key)
        self.items.Bind(self.items.ACTIVATED_EVENT, self.on_open)
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
        if self.pending_playlist_selection_id:
            state.selected = next(
                (
                    index
                    for index, playlist in enumerate(playlists)
                    if playlist.id == self.pending_playlist_selection_id
                ),
                0,
            )
            self.pending_playlist_selection_id = None
        self.history.reset(state)
        self.current_playlist = None
        self.render(
            state,
            focus=window_is_or_descendant(wx.Window.FindFocus(), self.items),
        )

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
        self.render(
            state,
            focus=window_is_or_descendant(wx.Window.FindFocus(), self.items),
        )

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
        self.status.SetLabel(msg.item_count(len(state.items)))
        if focus:
            self.items.SetFocus()

    def on_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if (
            key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
            and physical_control_down(event)
        ):
            self.frame.open_selected_track_album(
                self.items.selected_item()
            )
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.on_open()
        elif key == wx.WXK_BACK:
            self.go_back()
        elif key == wx.WXK_DELETE:
            if self.history.can_go_back:
                self.remove_selected()
            else:
                playlist = self.items.selected_item()
                if playlist:
                    self.remove_playlist(playlist)
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
            self.frame.say(msg.READ_ONLY)
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
        self.status.SetLabel(msg.item_count(len(self.items.items)))
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
                menu.Append(wx.ID_ANY, "Playlist &information..."),
                lambda: self.frame.show_playlist_information(playlist),
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
            msg.ENTER_PLAYLIST_NAME,
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
        self.frame.say(msg.RENAMED)

    def remove_playlist(self, playlist: SpotifyItem) -> None:
        answer = wx.MessageBox(
            msg.remove_playlist(playlist.name),
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
        self.status.SetLabel(msg.item_count(len(self.items.items)))
        self.frame.say(msg.REMOVED_FROM_LIBRARY)

    def on_navigation(self, event: wx.NavigationKeyEvent) -> None:
        if event.IsFromTab() and event.GetDirection():
            logger.debug(
                "Forward navigation from %s list to main tab bar",
                self.title,
            )
            self.frame.focus_tab_bar()
        else:
            event.Skip()


class AudiobooksPanel(PlaylistsPanel):
    def __init__(self, parent: wx.Window, frame: "MainFrame") -> None:
        super().__init__(parent, frame, "Audiobooks")
        self.history.reset(ViewState("Audiobooks", []))
        self.heading.SetLabel("Audiobooks")
        self.status.SetLabel(msg.AUDIOBOOKS_LOAD_HINT)

    def refresh(self) -> None:
        if self.loading:
            return
        if self.history.can_go_back and self.current_playlist:
            audiobook = self.current_playlist
            self.loading = True
            self.frame.run_task(
                None,
                lambda: self.frame.spotify.audiobook_chapters(audiobook),
                lambda chapters: self.show_chapters(
                    audiobook,
                    chapters,
                    replace=True,
                ),
                failure=self.finish_load_error,
            )
            return
        self.loading = True
        self.frame.run_task(
            None,
            self.frame.spotify.saved_audiobooks,
            self.show_audiobooks,
            failure=self.finish_load_error,
        )

    def show_audiobooks(self, audiobooks: list[SpotifyItem]) -> None:
        self.loading = False
        self.loaded_once = True
        state = ViewState("Audiobooks", audiobooks)
        self.history.reset(state)
        self.current_playlist = None
        self.render(
            state,
            focus=window_is_or_descendant(wx.Window.FindFocus(), self.items),
        )
        if not self.frame.spotify.has_scope("user-read-playback-position"):
            self.status.SetLabel(
                msg.audiobook_resume_permission(len(audiobooks))
            )

    def on_open(self, event: wx.Event | None = None) -> None:
        item = self.items.selected_item()
        if not item:
            return
        if self.history.can_go_back:
            self.frame.play_audiobook_chapter(item)
            return
        self.history.remember_selection(self.items.GetSelection())
        self.loading = True
        self.frame.run_task(
            None,
            lambda: self.frame.spotify.audiobook_chapters(item),
            lambda chapters: self.show_chapters(item, chapters),
            failure=self.finish_load_error,
        )

    def show_chapters(
        self,
        audiobook: SpotifyItem,
        chapters: list[SpotifyItem],
        *,
        replace: bool = False,
    ) -> None:
        self.loading = False
        self.current_playlist = audiobook
        state = ViewState(audiobook.name, chapters)
        if replace:
            state.selected = self.history.current.selected
            self.history.replace(state)
        else:
            self.history.push(state)
        self.render(
            state,
            focus=window_is_or_descendant(wx.Window.FindFocus(), self.items),
        )

    def on_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if (
            key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
            and physical_control_down(event)
        ):
            self.frame.open_selected_track_album(
                self.items.selected_item()
            )
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.on_open()
        elif key == wx.WXK_BACK:
            self.go_back()
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
            open_callback=self.on_open,
        )


class PodcastsPanel(PlaylistsPanel):
    def __init__(self, parent: wx.Window, frame: "MainFrame") -> None:
        super().__init__(parent, frame, "Podcasts")
        self.history.reset(ViewState("Podcasts", []))
        self.heading.SetLabel("Podcasts")
        self.status.SetLabel(msg.PODCASTS_LOAD_HINT)

    def refresh(self) -> None:
        if self.loading:
            return
        if self.history.can_go_back and self.current_playlist:
            show = self.current_playlist
            self.loading = True
            self.frame.run_task(
                None,
                lambda: self.frame.spotify.children(show),
                lambda episodes: self.show_episodes(
                    show,
                    episodes,
                    replace=True,
                ),
                failure=self.finish_load_error,
            )
            return
        self.loading = True
        self.frame.run_task(
            None,
            lambda: (
                self.frame.spotify.saved_shows(),
                self.frame.spotify.saved_episodes(),
            ),
            lambda result: self.show_library(*result),
            failure=self.finish_load_error,
        )

    def show_library(
        self,
        shows: list[SpotifyItem],
        episodes: list[SpotifyItem],
    ) -> None:
        self.loading = False
        self.loaded_once = True
        items = [*shows, *episodes]
        state = ViewState("Podcasts", items)
        self.history.reset(state)
        self.current_playlist = None
        self.render(
            state,
            focus=window_is_or_descendant(wx.Window.FindFocus(), self.items),
        )
        self.status.SetLabel(
            msg.saved_podcasts(len(shows), len(episodes))
        )

    def on_open(self, event: wx.Event | None = None) -> None:
        item = self.items.selected_item()
        if not item or item.kind == ItemKind.HEADING:
            return
        if item.kind == ItemKind.EPISODE:
            self.frame.play_playable_item(item)
            return
        if item.kind != ItemKind.SHOW:
            return
        self.history.remember_selection(self.items.GetSelection())
        self.loading = True
        self.frame.run_task(
            None,
            lambda: self.frame.spotify.children(item),
            lambda episodes: self.show_episodes(item, episodes),
            failure=self.finish_load_error,
        )

    def show_episodes(
        self,
        show: SpotifyItem,
        episodes: list[SpotifyItem],
        *,
        replace: bool = False,
    ) -> None:
        self.loading = False
        self.current_playlist = show
        state = ViewState(show.name, episodes)
        if replace:
            state.selected = self.history.current.selected
            self.history.replace(state)
        else:
            self.history.push(state)
        self.render(
            state,
            focus=window_is_or_descendant(wx.Window.FindFocus(), self.items),
        )

    def on_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if (
            key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
            and physical_control_down(event)
        ):
            self.frame.open_selected_track_album(
                self.items.selected_item()
            )
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.on_open()
        elif key == wx.WXK_BACK:
            self.go_back()
        elif key == wx.WXK_DELETE and not self.history.can_go_back:
            item = self.items.selected_item()
            if item:
                self.remove_saved_item(item)
        elif key == wx.WXK_F10 and event.ShiftDown():
            self.on_context_menu()
        else:
            event.Skip()

    def on_context_menu(self, event: wx.Event | None = None) -> None:
        item = self.items.selected_item()
        if not item or item.kind == ItemKind.HEADING:
            return
        saved_library_item = not self.history.can_go_back
        remove_callback = None
        remove_label = None
        if saved_library_item and item.kind == ItemKind.SHOW:
            remove_callback = lambda: self.remove_saved_item(item)
            remove_label = "&Unsubscribe..."
        elif saved_library_item and item.kind == ItemKind.EPISODE:
            remove_callback = lambda: self.remove_saved_item(item)
            remove_label = "Remove saved &episode..."
        self.frame.popup_item_menu(
            self.items,
            item,
            open_callback=self.on_open if item.kind == ItemKind.SHOW else None,
            play_callback=(
                lambda: self.frame.play_playable_item(item)
                if item.kind == ItemKind.EPISODE
                else None
            ),
            remove_callback=remove_callback,
            remove_label=remove_label,
        )

    def remove_saved_item(self, item: SpotifyItem) -> None:
        prompt = (
            msg.unsubscribe_podcast(item.name)
            if item.kind == ItemKind.SHOW
            else msg.remove_saved_episode(item.name)
        )
        title = (
            "Unsubscribe"
            if item.kind == ItemKind.SHOW
            else "Remove saved episode"
        )
        answer = wx.MessageBox(
            prompt,
            title,
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
            self,
        )
        if answer != wx.YES:
            return
        self.frame.run_task(
            None,
            lambda: self.frame.spotify.remove(item),
            lambda result: self.finish_remove_saved_item(),
        )

    def finish_remove_saved_item(self) -> None:
        self.frame.say(msg.REMOVED_FROM_LIBRARY)
        self.refresh()


class MainFrame(wx.Frame):
    def __init__(self, spotify: SpotifyClient, store: PortableStore) -> None:
        super().__init__(None, title="BlindSpot", size=(820, 620))
        self.spotify = spotify
        self.store = store
        settings = self.store.read("settings.json", {}) or {}
        self.announce_track_changes = bool(
            settings.get("announce_track_changes", False)
        )
        self.resume_mode = resume_mode_from_settings(settings)
        self.global_shortcuts = normalized_global_shortcuts(
            settings.get("global_shortcuts", {})
        )
        self.follow_braille_lyrics = bool(
            settings.get("follow_braille_lyrics", False)
        )
        self.registered_hotkey_ids: list[int] = []
        self.last_player_item_id: str | None = None
        self.suppress_track_announcement_id: str | None = None
        self.current_player_state: dict = {}
        self.playback_state_updated_at = time.monotonic()
        self.pending_previous_restart: wx.CallLater | None = None
        self.shuffle_enabled: bool | None = None
        self.repeat_state: str | None = None
        self.pending_resume: tuple[SpotifyItem, int, str] | None = None
        self.deferred_queue_items: list[SpotifyItem] = []
        self.deferred_queue_flushing = False
        self.deferred_queue_start_item: SpotifyItem | None = None
        self.open_album_return_page: int | None = None
        self.open_album_return_state: ViewState | None = None
        self.announcer = Auto()
        self.player: WebPlaybackController | None = None
        self.current_player_item: SpotifyItem | None = None
        self.standalone_player_item_id: str | None = None
        self.lyric_start_item_id: str | None = None
        self.pending_lyric_seek: tuple[str, int] | None = None
        self.pending_play_item: SpotifyItem | None = None
        self.pending_play_context: SpotifyItem | None = None
        self.pending_play_position_ms = 0
        self.lyrics = LRCLibClient()
        self.remote_device_id: str | None = None
        self.remote_device_name = ""
        self.remote_supports_volume: bool | None = None
        self.volume_before_mute_percent = 50
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
        self.notebook.SetName("Main tabs")
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
            self.queue_items,
            silent_load=True,
            load_on_first_focus=True,
        )
        self.playlists = PlaylistsPanel(self.notebook, self)
        self.recently_played = CollectionPanel(
            self.notebook,
            self,
            "Recently Played",
            self.load_recently_played,
            silent_load=True,
            load_on_first_focus=True,
        )
        self.bookmarks = BookmarksPanel(self.notebook, self)
        self.audiobooks = AudiobooksPanel(self.notebook, self)
        self.podcasts = PodcastsPanel(self.notebook, self)
        for panel, label in (
            (self.search, "Search"),
            (self.liked, "Liked Songs"),
            (self.queue, "Queue"),
            (self.playlists, "Playlists"),
            (self.recently_played, "Recently Played"),
            (self.bookmarks, "Bookmarks"),
            (self.audiobooks, "Audiobooks"),
            (self.podcasts, "Podcasts"),
        ):
            self.notebook.AddPage(panel, label)
        self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.on_tab_changed)
        self.set_view_title("Search")
        self.load_pending_resume()
        self.Bind(wx.EVT_CHAR_HOOK, self.on_global_key)
        for _, _, hotkey_id in GLOBAL_SHORTCUT_ACTIONS:
            self.Bind(wx.EVT_HOTKEY, self.on_global_hotkey, id=hotkey_id)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Centre()
        self._create_web_player()
        wx.CallAfter(self.apply_global_hotkey_setting)
        wx.CallAfter(self.initial_focus)
        wx.CallAfter(self.check_for_updates, False)

    def set_follow_braille_lyrics(self, enabled: bool) -> None:
        self.follow_braille_lyrics = enabled
        settings = self.store.read("settings.json", {}) or {}
        settings["follow_braille_lyrics"] = enabled
        self.store.write("settings.json", settings)

    def lyric_adjustment_ms(self, track_id: str) -> int:
        records = self.store.read("lyrics.json", {}) or {}
        record = records.get(track_id) or {}
        return int(record.get("adjustment_ms") or 0)

    def set_lyric_adjustment_ms(
        self,
        track_id: str,
        adjustment_ms: int,
    ) -> None:
        records = self.store.read("lyrics.json", {}) or {}
        record = records.get(track_id) or {}
        record["adjustment_ms"] = adjustment_ms
        records[track_id] = record
        self.store.write("lyrics.json", records)

    def lyrics_for_item(self, item: SpotifyItem) -> Lyrics:
        records = self.store.read("lyrics.json", {}) or {}
        source = (records.get(item.id) or {}).get("source")
        if source:
            return Lyrics(
                track_name=str(source.get("track_name") or item.name),
                artist_name=str(source.get("artist_name") or ""),
                text=str(source.get("text") or ""),
                synced=bool(source.get("synced")),
                track_id=item.id,
                synced_lines=[
                    (int(line[0]), str(line[1]))
                    for line in source.get("synced_lines") or []
                ],
                substitute=True,
            )
        lyrics = self.lyrics.lyrics_for(item)
        if lyrics.substitute:
            record = records.get(item.id) or {}
            record["source"] = {
                "track_name": lyrics.track_name,
                "artist_name": lyrics.artist_name,
                "text": lyrics.text,
                "synced": lyrics.synced,
                "synced_lines": lyrics.synced_lines,
            }
            records[item.id] = record
            self.store.write("lyrics.json", records)
        return lyrics

    def _create_web_player(self) -> None:
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
        ctrl = "RAWCTRL" if sys.platform == "darwin" else "Ctrl"
        menu_bar = wx.MenuBar()
        go = wx.Menu()
        play_selected = go.Append(
            wx.ID_ANY,
            f"&Play focused item{menu_function_shortcut('F4')}",
        )
        play_pause = go.Append(
            wx.ID_ANY,
            f"&Pause or resume{menu_function_shortcut('F8')}",
        )
        mute = go.Append(
            wx.ID_ANY,
            f"&Mute or unmute\t{ctrl}+F4",
        )
        open_album = go.Append(
            wx.ID_ANY,
            f"Open focused track's &album\t{ctrl}+RETURN",
        )
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
            f"Pre&vious track{menu_function_shortcut('F7')}",
        )
        next_track = go.Append(
            wx.ID_ANY,
            f"&Next track{menu_function_shortcut('F9')}",
        )
        seek_backward = go.Append(
            wx.ID_ANY,
            "Seek &backward 5 seconds (F5)",
        )
        seek_forward = go.Append(
            wx.ID_ANY,
            "Seek &forward 5 seconds (F6)",
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
            "Speak &remaining time",
        )
        jump_to_time = go.Append(
            wx.ID_ANY,
            f"&Jump to time...\t{ctrl}+J",
        )
        speak_current = go.Append(
            wx.ID_ANY,
            f"Speak current track\t{ctrl}+Shift+I",
        )
        speak_up_next = go.Append(
            wx.ID_ANY,
            f"Speak &up next\t{ctrl}+Shift+U",
        )
        lyrics = go.Append(
            wx.ID_ANY,
            f"L&yrics...{menu_function_shortcut(f'{ctrl}+Y')}",
        )
        repeat = go.Append(wx.ID_ANY, f"&Repeat\t{ctrl}+R")
        shuffle = go.Append(wx.ID_ANY, f"&Shuffle\t{ctrl}+S")
        volume_down = go.Append(
            wx.ID_ANY,
            f"Volume &down 5 percent\t{ctrl}+F5",
        )
        volume_up = go.Append(
            wx.ID_ANY,
            f"Volume &up 5 percent\t{ctrl}+F6",
        )
        go.AppendSeparator()
        queue_selected = go.Append(
            wx.ID_ANY,
            f"Add marked items to &queue\t{ctrl}+Q",
        )
        like_selected = go.Append(
            wx.ID_ANY,
            f"&Like or unlike selected\t{ctrl}+L",
        )
        add_to_playlist = go.Append(
            wx.ID_ANY,
            f"Add selected to a pl&aylist...\t{ctrl}+Shift+A",
        )
        selected_actions = go.Append(
            wx.ID_ANY,
            (
                "Selected item &actions...\tAlt+M"
                if sys.platform == "darwin"
                else "Selected item &actions..."
            ),
        )
        create_playlist = go.Append(
            wx.ID_ANY,
            f"&New playlist...\t{ctrl}+Shift+N",
        )
        refresh_view = go.Append(
            wx.ID_REFRESH,
            f"Refresh current &view\t{ctrl}+Shift+R",
        )
        go.AppendSeparator()
        open_liked = go.Append(
            wx.ID_ANY,
            f"Open &Liked Songs\t{ctrl}+2",
        )
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
        open_audiobooks = go.Append(
            wx.ID_ANY,
            f"Open &Audiobooks\t{ctrl}+7",
        )
        open_podcasts = go.Append(
            wx.ID_ANY,
            f"Open Pod&casts\t{ctrl}+8",
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
        donate = help_menu.Append(wx.ID_ANY, "&Donate to Project")
        help_menu.AppendSeparator()
        about = help_menu.Append(wx.ID_ABOUT, "&About BlindSpot...")
        menu_bar.Append(help_menu, "&Help")
        self.SetMenuBar(menu_bar)
        self.Bind(wx.EVT_MENU, lambda event: self.play_selected(), play_selected)
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.toggle_pause_resume(),
            play_pause,
        )
        self.Bind(wx.EVT_MENU, lambda event: self.toggle_mute(), mute)
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.open_selected_track_album(
                self.current_selected_item()
            ),
            open_album,
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
            lambda event: self.queue_command(),
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
            lambda event: self.show_selected_actions(),
            selected_actions,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.create_playlist(),
            create_playlist,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.refresh_current_view(),
            refresh_view,
        )
        self.Bind(wx.EVT_MENU, lambda event: self.open_tab(1), open_liked)
        self.Bind(wx.EVT_MENU, lambda event: self.open_tab(2), open_queue)
        self.Bind(wx.EVT_MENU, lambda event: self.open_tab(3), open_playlists)
        self.Bind(wx.EVT_MENU, lambda event: self.open_tab(4), open_recent)
        self.Bind(wx.EVT_MENU, lambda event: self.open_tab(5), open_bookmarks)
        self.Bind(wx.EVT_MENU, lambda event: self.open_tab(6), open_audiobooks)
        self.Bind(wx.EVT_MENU, lambda event: self.open_tab(7), open_podcasts)
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
        self.Bind(
            wx.EVT_MENU,
            lambda event: webbrowser.open(PAYPAL_DONATE_URL),
            donate,
        )
        self.Bind(wx.EVT_MENU, self.on_about, about)
    def initial_focus(self) -> None:
        if not self.spotify.connected:
            if self.spotify.client_id and self.spotify.token.get("refresh_token"):
                self.search.focus_query()
            elif self.spotify.client_id:
                self.say(msg.AUTHORIZATION_REQUIRED)
                wx.CallAfter(self.on_connect, None)
            else:
                self.say(msg.NOT_CONNECTED)
                wx.CallAfter(self.on_connect, None)
        else:
            self.search.focus_query()
            if not self.spotify.web_playback_authorized:
                self.say(msg.PERMISSIONS_REQUIRED)

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
        self.SetTitle(f"{title} - BlindSpot")

    def update_title_for_page(self, page: wx.Window, title: str) -> None:
        if self.notebook.GetCurrentPage() is page:
            self.set_view_title(title)

    def focus_tab_bar(self) -> None:
        self.SetTitle("BlindSpot")
        self.notebook.SetFocus()

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
            self.say(msg.CONNECT_FIRST)
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
            msg.RECENT_PERMISSION_PROMPT,
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
            self.say(msg.RECENT_NOT_AUTHORIZED)

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
            self.say(msg.AUTHORIZATION_IN_PROGRESS)
            return False
        try:
            request = self.spotify.begin_authorization(
                force_dialog=force_dialog,
            )
        except SpotifyError as error:
            self.show_error(str(error))
            return False
        self.authorization_in_progress = True
        self.say(msg.COMPLETE_LOGIN)

        def authorize() -> None:
            try:
                server = CallbackServer(request.state)
                code = server.wait(
                    on_ready=lambda: wx.CallAfter(
                        webbrowser.open,
                        request.url,
                    ),
                )
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
                msg.RECENT_AUTH_NOT_COMPLETED
            )

    def on_sign_out(self, event: wx.Event) -> None:
        answer = wx.MessageBox(
            msg.SIGN_OUT_PROMPT,
            "Sign out of BlindSpot",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
            self,
        )
        if answer == wx.YES:
            self.spotify.sign_out()
            self.say(msg.SIGNED_OUT)

    def on_preferences(self, event: wx.Event | None = None) -> None:
        settings = self.store.read("settings.json", {}) or {}
        dialog = PreferencesDialog(
            self,
            settings.get("logging_level", "Off"),
            bool(settings.get("announce_track_changes", False)),
            resume_mode_from_settings(settings),
            normalized_global_shortcuts(
                settings.get("global_shortcuts", {})
            ),
            self.save_global_shortcuts,
            self.open_logs_folder,
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
            self.global_shortcuts = dialog.get_global_shortcuts()
            settings["global_shortcuts"] = self.global_shortcuts
            settings.pop("global_seek_volume_hotkeys", None)
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

    def open_logs_folder(self) -> None:
        if not wx.LaunchDefaultApplication(str(self.store.root.resolve())):
            self.show_error(msg.LOGS_FOLDER_OPEN_FAILED)

    def save_global_shortcuts(
        self,
        shortcuts: dict[str, dict[str, int]],
    ) -> None:
        self.global_shortcuts = normalized_global_shortcuts(shortcuts)
        settings = self.store.read("settings.json", {}) or {}
        settings["global_shortcuts"] = self.global_shortcuts
        settings.pop("global_seek_volume_hotkeys", None)
        self.store.write("settings.json", settings)
        self.apply_global_hotkey_setting()

    def on_manual(self, event: wx.Event | None = None) -> None:
        manual = resource_directory() / "manual.html"
        if not manual.exists():
            self.show_error(msg.MANUAL_NOT_FOUND)
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
                        msg.UPDATE_CHECK_FAILED,
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
            action = (
                msg.UPDATE_INSTALL_PROMPT
                if supports_automatic_update(release)
                else msg.UPDATE_PAGE_PROMPT
            )
            previous_focus = wx.Window.FindFocus()
            answer = wx.MessageBox(
                msg.update_available(release.version, action),
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
                wx.CallAfter(self._restore_focus_after_update_prompt, previous_focus)
        elif report_current:
            wx.MessageBox(
                msg.update_current(__version__),
                "Check for updates",
                wx.OK | wx.ICON_INFORMATION,
                self,
            )

    def _restore_focus_after_update_prompt(
        self,
        previous_focus: wx.Window | None,
    ) -> None:
        try:
            if (
                previous_focus
                and previous_focus.IsShown()
                and previous_focus.IsEnabled()
            ):
                previous_focus.SetFocus()
                return
        except RuntimeError:
            pass
        self.search.focus_query()

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
            # Let wx fully unwind the app-modal progress dialog before closing
            # the frame. Closing in the same callback can be ignored on Windows.
            wx.CallAfter(self.Close)
        elif not success:
            self.show_error(
                message or msg.UPDATE_DOWNLOAD_FAILED
            )

    def on_about(self, event: wx.Event) -> None:
        wx.MessageBox(
            msg.about(__version__),
            "About BlindSpot",
            wx.OK | wx.ICON_INFORMATION,
            self,
        )

    def on_connected(self) -> None:
        if self.recent_permission_authorization:
            self.recent_permission_authorization = False
            if self.spotify.has_scope("user-read-recently-played"):
                self.say(msg.RECENT_AUTHORIZED)
                self.recently_played.loaded_once = False
                self.recently_played.loading = False
                wx.CallAfter(self.recently_played.refresh)
            else:
                self.recently_played.loading = False
                self.recently_played.loaded_once = True
                self.recently_played.status.SetLabel(
                    msg.RECENT_ACCESS_NOT_GRANTED_STATUS
                )
                self.say(msg.RECENT_ACCESS_NOT_GRANTED)
        else:
            self.say(msg.CONNECTED)
        if self.player:
            self.player.provide_token()

    def on_tab_changed(self, event: wx.BookCtrlEvent) -> None:
        old_selection = getattr(event, "GetOldSelection", lambda: -1)()
        selection = getattr(event, "GetSelection", lambda: -1)()
        if old_selection == 0 and selection != 0:
            self.discard_transient_open_album()
        self.SetTitle("BlindSpot")
        event.Skip()

    def on_global_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        focused = wx.Window.FindFocus()
        focused_list = item_list_ancestor(focused)
        if key == wx.WXK_F1:
            self.on_manual()
        elif (
            key == wx.WXK_F4
            and physical_control_down(event)
            and not event.AltDown()
            and not event.ShiftDown()
        ):
            self.toggle_mute()
        elif (
            key == wx.WXK_F4
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
        ):
            if focused_list:
                self.play_selected()
            else:
                self.say(msg.NO_SONG_SELECTED)
        elif (
            key == wx.WXK_F5
            and physical_control_down(event)
            and not event.AltDown()
            and not event.ShiftDown()
        ):
            self.adjust_volume(-5)
        elif (
            key == wx.WXK_F6
            and physical_control_down(event)
            and not event.AltDown()
            and not event.ShiftDown()
        ):
            self.adjust_volume(5)
        elif (
            key == wx.WXK_F5
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
        ):
            self.seek(-5000)
        elif (
            key == wx.WXK_F6
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
        ):
            self.seek(5000)
        elif (
            key == wx.WXK_F7
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
        ):
            self.previous_track()
        elif (
            key == wx.WXK_F8
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
        ):
            self.toggle_pause_resume()
        elif (
            key == wx.WXK_F9
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
        ):
            self.next_track()
        elif (
            key == wx.WXK_SPACE
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
            and not space_belongs_to_control(focused)
        ):
            self.toggle_pause_resume()
            return
        elif physical_control_down(event) and key == wx.WXK_TAB:
            direction = -1 if event.ShiftDown() else 1
            selection = (
                self.notebook.GetSelection() + direction
            ) % self.notebook.GetPageCount()
            self.notebook.SetSelection(selection)
            self.notebook.SetFocus()
        elif key == wx.WXK_TAB:
            self.move_focus(backward=event.ShiftDown())
        elif key == wx.WXK_F10 and event.ShiftDown():
            self.show_selected_actions()
        elif physical_control_down(event) and event.ShiftDown() and key in (ord("T"), ord("t")):
            self.announce_time("total")
        elif physical_control_down(event) and event.ShiftDown() and key in (ord("E"), ord("e")):
            self.announce_time("elapsed")
        elif physical_control_down(event) and event.ShiftDown() and key in (ord("R"), ord("r")):
            self.refresh_current_view()
        elif physical_control_down(event) and event.ShiftDown() and key in (ord("I"), ord("i")):
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
        elif (
            physical_control_down(event)
            and event.ShiftDown()
            and key in (ord("N"), ord("n"))
        ):
            self.create_playlist()
        elif physical_control_down(event) and key in (ord("R"), ord("r")):
            self.cycle_repeat()
        elif physical_control_down(event) and key in (ord("S"), ord("s")):
            self.toggle_shuffle()
        elif (
            physical_control_down(event)
            and key in (ord("Q"), ord("q"))
            and focused_list
        ):
            self.queue_from_list(focused_list)
        elif (
            physical_control_down(event)
            and key in (ord("L"), ord("l"))
            and focused_list
        ):
            self.toggle_like_item(focused_list.selected_item())
        elif (
            physical_control_down(event)
            and event.ShiftDown()
            and key in (ord("A"), ord("a"))
            and focused_list
        ):
            self.choose_playlist_for_selected()
        elif (
            physical_control_down(event)
            and event.ShiftDown()
            and key in (ord("B"), ord("b"))
        ):
            self.save_current_bookmark()
        elif (
            physical_control_down(event)
            and key in ENTER_KEY_CODES
            and focused_list
        ):
            self.open_selected_track_album(focused_list.selected_item())
        elif key in ENTER_KEY_CODES:
            if focused is self.search.categories:
                logger.debug("Frame routed Enter from search category")
                self.search.on_search()
            elif focused_list is self.search.results:
                logger.debug("Frame routed Enter to search result action")
                self.search.on_open()
            elif focused_list is self.liked.items:
                self.liked.on_open()
            elif focused_list is self.queue.items:
                self.queue.on_open()
            elif focused_list is self.playlists.items:
                self.playlists.on_open()
            elif focused_list is self.recently_played.items:
                self.recently_played.on_open()
            elif focused_list is self.bookmarks.items:
                self.bookmarks.on_open()
            elif focused_list is self.audiobooks.items:
                self.audiobooks.on_open()
            elif focused_list is self.podcasts.items:
                self.podcasts.on_open()
            else:
                event.Skip()
        elif physical_control_down(event) and key in (ord("F"), ord("f")):
            self.discard_transient_open_album()
            self.notebook.SetSelection(0)
            self.search.focus_query()
        elif physical_control_down(event) and key == ord(","):
            self.on_preferences()
        elif physical_control_down(event) and ord("1") <= key <= ord("8"):
            page = key - ord("1")
            if page == 0:
                self.discard_transient_open_album()
            self.notebook.SetSelection(page)
            if page == 0:
                self.search.focus_query()
        elif event.AltDown() and key == wx.WXK_LEFT:
            if self.notebook.GetSelection() == 0 and self.search.go_back():
                return
            event.Skip()
        else:
            event.Skip()

    def apply_global_hotkey_setting(self) -> None:
        self.unregister_global_hotkeys()
        failed = []
        labels = {
            action: label
            for action, label, _ in GLOBAL_SHORTCUT_ACTIONS
        }
        for action, shortcut in self.global_shortcuts.items():
            hotkey_id = GLOBAL_SHORTCUT_IDS[action]
            try:
                registered = self.RegisterHotKey(
                    hotkey_id,
                    int(shortcut["modifiers"]),
                    int(shortcut["keycode"]),
                )
            except Exception:
                logger.exception("Could not register global hotkey %d", hotkey_id)
                registered = False
            if not registered:
                failed.append(
                    f"{labels[action]} ({shortcut_label(shortcut)})"
                )
            else:
                self.registered_hotkey_ids.append(hotkey_id)
        if failed:
            self.say(msg.shortcut_registration_failed(failed))

    def unregister_global_hotkeys(self) -> None:
        for hotkey_id in self.registered_hotkey_ids:
            try:
                self.UnregisterHotKey(hotkey_id)
            except Exception:
                logger.exception("Could not unregister global hotkey %d", hotkey_id)
        self.registered_hotkey_ids.clear()

    def on_global_hotkey(self, event: wx.HotkeyEvent) -> None:
        actions = {
            GLOBAL_SHORTCUT_IDS["previous_track"]: self.previous_track,
            GLOBAL_SHORTCUT_IDS["pause_resume"]: self.toggle_pause_resume,
            GLOBAL_SHORTCUT_IDS["next_track"]: self.next_track,
            GLOBAL_SHORTCUT_IDS["seek_backward"]: lambda: self.seek(-5000),
            GLOBAL_SHORTCUT_IDS["seek_forward"]: lambda: self.seek(5000),
            GLOBAL_SHORTCUT_IDS["volume_down"]: (
                lambda: self.adjust_volume(-5)
            ),
            GLOBAL_SHORTCUT_IDS["volume_up"]: (
                lambda: self.adjust_volume(5)
            ),
            GLOBAL_SHORTCUT_IDS["toggle_mute"]: self.toggle_mute,
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
        elif page == 5:
            controls = [self.notebook, self.bookmarks.items]
        elif page == 6:
            controls = [self.notebook, self.audiobooks.items]
        else:
            controls = [self.notebook, self.podcasts.items]

        focused = wx.Window.FindFocus()
        focused_list = item_list_ancestor(focused)
        if focused_list:
            focused = focused_list
        else:
            focused_radio_box = radio_box_ancestor(focused)
            if focused_radio_box:
                focused = focused_radio_box
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

    def current_track_is_paused(self, track_id: str) -> bool:
        live_item = self.current_player_state.get("item") or {}
        return bool(
            live_item.get("id") == track_id
            and not self.current_player_state.get("is_playing")
        )

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
            msg.SLEEP_TIMER_PROMPT,
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
            self.say(msg.NO_CURRENT_TRACK)
            return
        self.sleep_timer.Stop()
        self.sleep_after_track_id = self.current_player_item.id
        self.synchronize_sleep_after_track(self.current_player_state)
        self.say(msg.SLEEP_END_OF_TRACK)

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
        self.say(msg.sleep_minutes(minutes))

    def cancel_sleep_timer(self) -> None:
        active = self.sleep_timer.IsRunning() or bool(
            self.sleep_after_track_id
        )
        self.sleep_timer.Stop()
        self.sleep_after_track_id = None
        if self.remote_device_id:
            self.remote_refresh_timer.Start(10_000)
        self.say(
            msg.SLEEP_CANCELLED
            if active
            else msg.NO_SLEEP_TIMER
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
            lambda result: self.say(msg.SLEEP_STOPPED),
        )

    def choose_playback_device(self) -> None:
        self.run_task(
            msg.GETTING_DEVICES,
            self.spotify.available_devices,
            self.show_playback_devices,
        )

    def show_playback_devices(self, devices: list[dict]) -> None:
        if not devices:
            self.say(msg.NO_DEVICES)
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
            msg.DEVICE_SELECTION_PROMPT,
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
            msg.transferring_to(str(device.get("name") or "device")),
            lambda: self.spotify.transfer_playback(device_id, play=True),
            lambda result: self.finish_transfer_playback(device),
        )

    def finish_transfer_playback(self, device: dict) -> None:
        device_id = str(device["id"])
        self.shuffle_enabled = None
        self.repeat_state = None
        local_device_id = self.player.device_id if self.player else None
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
        self.say(msg.playing_on(str(device.get("name") or "device")))

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

    def play(
        self,
        item: SpotifyItem,
        *,
        announce: bool = False,
    ) -> None:
        self.suppress_track_announcement_id = item.id
        if self.remote_device_id:
            device_id = self.remote_device_id
        elif self.player:
            self.player.activate()
            if not self.player.ready:
                self.pending_play_item = item
                message = (
                    msg.player_starting(item.name)
                    if announce
                    else msg.PLAYER_STARTING
                )
                self.say(message)
                self.player.provide_token()
                return
            device_id = self.player.device_id
        else:
            device_id = None
        self.run_task(
            msg.playing(item.name) if announce else None,
            lambda: self.spotify.play(item, device_id=device_id),
            lambda result: self.on_play_started(
                item,
                standalone=item.playable,
            ),
        )

    def play_from_lyric(
        self,
        item: SpotifyItem,
        position_ms: int,
    ) -> None:
        self.suppress_track_announcement_id = item.id
        if self.remote_device_id:
            device_id = self.remote_device_id
        elif self.player:
            self.player.activate()
            if not self.player.ready:
                self.pending_play_item = item
                self.pending_play_context = None
                self.pending_play_position_ms = position_ms
                self.say(msg.player_starting(item.name))
                self.player.provide_token()
                return
            device_id = self.player.device_id
        else:
            self.say(msg.PLAYER_NOT_READY)
            return
        self.lyric_start_item_id = item.id
        self.pending_lyric_seek = (item.id, position_ms)
        self.run_task(
            None,
            lambda: self.play_at_with_entitlement_message(
                item,
                position_ms,
                device_id,
            ),
            lambda result: self.finish_lyric_start(item),
            failure=self.cancel_lyric_start,
        )

    def play_at_with_entitlement_message(
        self,
        item: SpotifyItem,
        position_ms: int,
        device_id: str,
    ) -> None:
        try:
            self.spotify.play_at(item, position_ms, device_id)
        except SpotifyError as error:
            message = str(error)
            if (
                item.kind == ItemKind.CHAPTER
                and ("403" in message or "payment" in message.lower())
            ):
                raise SpotifyError(msg.AUDIOBOOK_PLAYBACK_UNAVAILABLE) from error
            raise

    def finish_lyric_start(self, item: SpotifyItem) -> None:
        self.on_play_started(item, standalone=True)

    def cancel_lyric_start(self) -> None:
        self.lyric_start_item_id = None
        self.pending_lyric_seek = None

    def play_in_context(
        self,
        context: SpotifyItem,
        item: SpotifyItem,
    ) -> None:
        self.suppress_track_announcement_id = item.id
        if self.remote_device_id:
            device_id = self.remote_device_id
        elif self.player:
            self.player.activate()
            if not self.player.ready:
                self.pending_play_item = item
                self.pending_play_context = context
                self.say(msg.player_starting(item.name))
                self.player.provide_token()
                return
            device_id = self.player.device_id
        else:
            self.say(msg.PLAYER_NOT_READY)
            return
        self.run_task(
            msg.playing(item.name),
            lambda: self.spotify.play_at(
                item,
                0,
                device_id,
                context.uri,
            ),
            lambda result: self.on_play_started(item, standalone=False),
        )

    def on_play_started(
        self,
        item: SpotifyItem,
        *,
        standalone: bool,
    ) -> None:
        self.standalone_player_item_id = item.id if standalone else None
        current = self.current_player_item
        if current and current.id == item.id:
            self.current_player_state["standalone"] = standalone
            if self.resume_mode != "none":
                self.store.write(
                    "playback.json",
                    playback_state_for_resume(
                        self.current_player_state,
                        self.resume_mode,
                    ),
                )
        logger.info("Playback started kind=%s id=%s name=%r", item.kind, item.id, item.name)
        if self.deferred_queue_start_item is item:
            index = next(
                (
                    index
                    for index, queued_item in enumerate(
                        self.deferred_queue_items
                    )
                    if queued_item is item
                ),
                None,
            )
            if index is not None:
                del self.deferred_queue_items[index]
            self.deferred_queue_start_item = None
        self.flush_deferred_queue()

    def play_audiobook_chapter(self, item: SpotifyItem) -> None:
        position_ms = int(item.raw.get("resume_position_ms") or 0)
        if item.raw.get("resume_point", {}).get("fully_played"):
            position_ms = 0
        self.play_from_lyric(item, position_ms)

    def play_playable_item(self, item: SpotifyItem) -> None:
        if item.kind in {ItemKind.EPISODE, ItemKind.CHAPTER}:
            position_ms = int(item.raw.get("resume_position_ms") or 0)
            if item.raw.get("resume_point", {}).get("fully_played"):
                position_ms = 0
            if position_ms or item.kind == ItemKind.CHAPTER:
                self.play_from_lyric(item, position_ms)
                return
        self.play(item)

    def show_item_description(self, item: SpotifyItem) -> None:
        description = str(item.raw.get("description") or "").strip()
        if not description:
            self.say(msg.NO_DESCRIPTION)
            return
        wx.MessageBox(
            description,
            f"{item.name} description",
            wx.OK | wx.ICON_INFORMATION,
            self,
        )

    def show_playlist_information(self, item: SpotifyItem) -> None:
        owner = item.raw.get("owner") or {}
        owner_name = str(
            owner.get("display_name")
            or owner.get("name")
            or owner.get("id")
            or ""
        )
        wx.MessageBox(
            msg.playlist_information(
                owner_name,
                item.total,
                item.raw.get("public"),
                bool(item.raw.get("collaborative")),
                str(item.raw.get("description") or "").strip(),
            ),
            f"{item.name} information",
            wx.OK | wx.ICON_INFORMATION,
            self,
        )

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
        if page == 6:
            return self.audiobooks.items.selected_item()
        if page == 7:
            return self.podcasts.items.selected_item()
        return None

    def play_selected(self) -> None:
        item = self.current_selected_item()
        if not item:
            self.say(msg.NO_ITEM_SELECTED)
            return
        if item.kind == ItemKind.HEADING:
            self.say(msg.SELECT_PLAYABLE_ITEM)
            return
        if (
            self.notebook.GetSelection() == 2
            and any(
                queued_item is item
                for queued_item in self.deferred_queue_items
            )
        ):
            self.deferred_queue_start_item = item
        if self.notebook.GetSelection() == 5:
            self.resume_bookmark(item)
            return
        if (
            self.notebook.GetSelection() == 6
            and item.kind == ItemKind.CHAPTER
        ):
            self.play_audiobook_chapter(item)
            return
        if (
            self.notebook.GetSelection() == 7
            and item.kind == ItemKind.EPISODE
        ):
            self.play_playable_item(item)
            return
        if item.container:
            self.play(item, announce=False)
            return
        if self.notebook.GetSelection() == 0:
            state = self.search.history.current
            if (
                item.kind == ItemKind.TRACK
                and state.parent_kind == ItemKind.ALBUM
                and state.parent_id
            ):
                album = SpotifyItem(
                    state.parent_id,
                    ItemKind.ALBUM,
                    state.title,
                    uri=f"spotify:album:{state.parent_id}",
                )
                self.play_in_context(album, item)
                return
        if (
            self.notebook.GetSelection() == 3
            and self.playlists.current_playlist
        ):
            self.play_in_context(self.playlists.current_playlist, item)
            return
        self.play_playable_item(item)

    def player_device_id(self) -> str | None:
        if self.remote_device_id:
            return self.remote_device_id
        if not self.player or not self.player.ready:
            self.say(msg.PLAYER_NOT_READY)
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
                lambda result: self.on_play_started(
                    item,
                    standalone=not bool(context_uri),
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

    def toggle_pause_resume(self) -> None:
        if not self.current_player_item:
            self.say(msg.NOTHING_PLAYING)
            return
        self.toggle_playback()

    def resume_from_lyric(self, track_id: str, position_ms: int) -> None:
        if not self.current_track_is_paused(track_id):
            self.toggle_pause_resume()
            return
        device_id = self.player_device_id()
        if not device_id:
            return
        if self.using_local_player():
            self.player.seek_to(position_ms)
            self.toggle_playback()
            return
        self.run_task(
            None,
            lambda: self.spotify.seek_to(position_ms, device_id),
            lambda position: self.toggle_playback(),
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
            self.say(msg.unsupported_volume(self.remote_device_name))
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

    def toggle_mute(self) -> None:
        if self.remote_device_id and self.remote_supports_volume is False:
            self.say(msg.unsupported_volume(self.remote_device_name))
            return
        device_id = self.player_device_id()
        if not device_id:
            return
        if self.using_local_player():
            self.player.toggle_mute(self.finish_toggle_mute)
            return
        restore_volume = self.volume_before_mute_percent

        def change_volume() -> tuple[int, int]:
            state = self.spotify.playback_state()
            device = state.get("device") if state else None
            current = device.get("volume_percent") if device else None
            if current is None:
                raise SpotifyError(msg.CURRENT_VOLUME_UNAVAILABLE)
            current = int(current)
            target = 0 if current > 0 else restore_volume
            self.spotify.set_volume(target, device_id)
            return current, target

        self.run_task(None, change_volume, self.finish_remote_toggle_mute)

    def finish_remote_toggle_mute(self, result: tuple[int, int]) -> None:
        previous, volume = result
        if volume == 0 and previous > 0:
            self.volume_before_mute_percent = previous
        self.finish_toggle_mute(volume)

    def finish_toggle_mute(self, volume: int | None) -> None:
        if volume is None:
            return
        if volume == 0:
            self.say(msg.MUTED)
        else:
            self.say(msg.UNMUTED)

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
            self.say(msg.NO_TRACK)
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
                else msg.NOTHING_CURRENTLY_PLAYING
            ),
        )

    def finish_speak_current_track(self, state: dict) -> None:
        item = self.item_from_player_state(state)
        self.say(
            item.accessible_label()
            if item
            else msg.NOTHING_CURRENTLY_PLAYING
        )

    def speak_up_next(self) -> None:
        self.run_task(
            None,
            self.spotify.next_queued,
            lambda item: self.say(
                item.accessible_label()
                if item
                else msg.QUEUE_EMPTY
            ),
        )

    def show_lyrics(self) -> None:
        focused = wx.Window.FindFocus()
        focused_list = item_list_ancestor(focused)
        focused_item = (
            focused_list.selected_item()
            if focused_list
            else None
        )
        item = (
            focused_item
            if focused_item and focused_item.playable
            else self.current_player_item
        )
        if not item:
            self.say(msg.NOTHING_PLAYING)
            return
        self.run_task(
            msg.GETTING_LYRICS,
            lambda: self.lyrics_for_item(item),
            lambda lyrics: self.finish_show_lyrics(lyrics, item),
        )

    def finish_show_lyrics(
        self,
        lyrics: Lyrics,
        item: SpotifyItem,
    ) -> None:
        if lyrics.instrumental:
            self.say(msg.INSTRUMENTAL_TRACK)
            return
        dialog = LyricsDialog(self, lyrics, item)
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
            self.say(msg.SHUFFLE_ON if enabled else msg.SHUFFLE_OFF)

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
            "off": msg.REPEAT_OFF,
            "context": msg.REPEAT_ALL,
            "track": msg.REPEAT_ONE,
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
            msg.JUMP_TIME_PROMPT,
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
            self.say(msg.JUMP_TIME_INVALID)
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

    def load_recently_played(self) -> list[SpotifyItem]:
        spotify_items = self.spotify.recently_played()
        records = self.store.read("recently_played.json", []) or []
        local_items = []
        if isinstance(records, list):
            for record in records:
                if not isinstance(record, dict) or not record.get("id"):
                    continue
                try:
                    kind = ItemKind(record.get("kind", ItemKind.TRACK))
                except ValueError:
                    kind = ItemKind.TRACK
                raw = dict(record.get("raw") or {})
                raw["played_at_label"] = "played recently in BlindSpot"
                local_items.append(
                    SpotifyItem(
                        id=str(record["id"]),
                        kind=kind,
                        name=str(record.get("name") or "Untitled"),
                        artist=str(record.get("artist") or ""),
                        album=str(record.get("album") or ""),
                        duration_ms=int(record.get("duration_ms") or 0),
                        uri=str(record.get("uri") or ""),
                        raw=raw,
                    )
                )
        merged = []
        seen = set()
        for item in [*local_items, *spotify_items]:
            key = item.uri or f"{item.kind}:{item.id}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
        return merged[:50]

    def remember_recently_played(self, item: SpotifyItem) -> None:
        record = {
            "id": item.id,
            "kind": item.kind.value,
            "name": item.name,
            "artist": item.artist,
            "album": item.album,
            "duration_ms": item.duration_ms,
            "uri": item.uri,
            "raw": item.raw,
        }
        records = self.store.read("recently_played.json", []) or []
        if not isinstance(records, list):
            records = []
        records = [
            existing
            for existing in records
            if not isinstance(existing, dict)
            or str(existing.get("uri") or "") != item.uri
        ]
        records.insert(0, record)
        self.store.write("recently_played.json", records[:50])

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
            self.say(msg.NO_CURRENT_TRACK)
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
            self.bookmarks.status.SetLabel(msg.item_count(len(items)))
        self.say(msg.bookmark_saved(self.format_time(position_ms)))

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
        self.say(msg.BOOKMARK_DELETED)

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
            lambda result: self.finish_resume_bookmark(
                item,
                position_ms,
                context_uri,
            ),
        )

    def finish_resume_bookmark(
        self,
        item: SpotifyItem,
        position_ms: int,
        context_uri: str,
    ) -> None:
        self.on_play_started(item, standalone=not bool(context_uri))
        self.say(msg.resumed(item.name, self.format_time(position_ms)))

    def next_track(self) -> None:
        device_id = self.player_device_id()
        if not device_id:
            return
        self.send_next_track(device_id)

    def send_next_track(self, device_id: str) -> None:
        self.run_task(
            None,
            lambda: self.spotify.next_track(device_id),
            lambda result: logger.info("Skipped to next track"),
        )

    def previous_track(self) -> None:
        device_id = self.player_device_id()
        if not device_id:
            return
        pending = getattr(self, "pending_previous_restart", None)
        if pending and pending.IsRunning():
            pending.Stop()
            self.pending_previous_restart = None
            self.run_task(
                None,
                lambda: self.spotify.previous_track(device_id),
                lambda result: logger.info("Returned to previous track"),
            )
            return
        item = self.current_player_item
        if item:
            self.pending_previous_restart = wx.CallLater(
                int(PREVIOUS_DOUBLE_PRESS_SECONDS * 1000),
                self.restart_current_track,
                item.id,
            )
            return
        self.run_task(
            None,
            lambda: self.spotify.previous_track(device_id),
            lambda result: logger.info("Returned to previous track"),
        )

    def restart_current_track(self, item_id: str) -> None:
        self.pending_previous_restart = None
        item = self.current_player_item
        if not item or item.id != item_id:
            return
        device_id = self.player_device_id()
        if not device_id:
            return
        if self.using_local_player():
            self.player.seek_to(0)
            logger.info("Restarted current track")
            return
        self.run_task(
            None,
            lambda: self.spotify.seek_to(0, device_id),
            lambda position: logger.info("Restarted current track"),
        )

    def open_tab(self, index: int) -> None:
        self.notebook.SetSelection(index)
        self.notebook.SetFocus()

    def show_selected_actions(self) -> None:
        page = self.notebook.GetSelection()
        panels = (
            self.search,
            self.liked,
            self.queue,
            self.playlists,
            self.recently_played,
            self.bookmarks,
            self.audiobooks,
            self.podcasts,
        )
        if 0 <= page < len(panels):
            panels[page].on_context_menu()

    def open_selected_track_album(self, item: SpotifyItem | None) -> None:
        if item and item.kind == ItemKind.TRACK:
            self.open_album_for_track(item)

    def refresh_current_view(self) -> None:
        page = self.notebook.GetCurrentPage()
        refresh = getattr(page, "refresh", None)
        if refresh:
            refresh()

    def toggle_like_selected(self) -> None:
        item = self.current_selected_item()
        if not item or not item.uri or item.container:
            item = self.current_player_item
        self.toggle_like_item(item)

    def toggle_like_item(self, item: SpotifyItem | None) -> None:
        if not item or not item.uri:
            self.say(msg.NO_ITEM_SELECTED)
            return
        self.run_task(
            None,
            lambda: self.spotify.toggle_saved(item),
            lambda saved: self.finish_toggle_like(item, saved),
        )

    def finish_toggle_like(self, item: SpotifyItem, saved: bool) -> None:
        self.sync_liked_item(item, saved)
        self.say(msg.LIKED if saved else msg.UNLIKED)

    def choose_playlist_for_selected(self) -> None:
        item = self.current_selected_item()
        if not item or item.kind not in {ItemKind.TRACK, ItemKind.EPISODE}:
            self.say(msg.SELECT_TRACK_OR_EPISODE)
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
        self.notebook.SetSelection(3)
        self.playlists.pending_playlist_selection_id = playlist.id
        self.playlists.items.SetFocus()
        self.playlists.refresh()

    def show_playlist_picker(
        self,
        item: SpotifyItem,
        playlists: list[SpotifyItem],
    ) -> None:
        if not playlists:
            self.say(msg.NO_PLAYLISTS)
            return
        dialog = wx.SingleChoiceDialog(
            self,
            msg.CHOOSE_PLAYLIST,
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
            lambda result: self.finish_add_to_playlist(playlist, item),
        )

    def finish_add_to_playlist(
        self,
        playlist: SpotifyItem,
        item: SpotifyItem,
    ) -> None:
        self.say(msg.ADDED)
        current = self.playlists.current_playlist
        if not current or current.id != playlist.id:
            return
        self.playlists.history.current.items.append(item)
        self.playlists.render(
            self.playlists.history.current,
            focus=False,
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
        self.liked.status.SetLabel(
            msg.item_count(len(self.liked.items.items))
        )

    def on_player_ready(self, device_id: str) -> None:
        self.say(msg.READY)
        if self.pending_play_item:
            item = self.pending_play_item
            context = self.pending_play_context
            position_ms = self.pending_play_position_ms
            self.pending_play_item = None
            self.pending_play_context = None
            self.pending_play_position_ms = 0
            if context:
                self.play_in_context(context, item)
            elif position_ms or item.kind == ItemKind.CHAPTER:
                self.play_from_lyric(item, position_ms)
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
        self.apply_pending_lyric_seek()
        state["standalone"] = bool(
            self.current_player_item
            and self.standalone_player_item_id
            == self.current_player_item.id
        )
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
            if is_new_track and state.get("is_playing"):
                self.remember_recently_played(self.current_player_item)
            suppress_announcement = (
                self.current_player_item.id
                == self.suppress_track_announcement_id
            )
            if suppress_announcement:
                self.suppress_track_announcement_id = None
            if (
                self.announce_track_changes
                and is_new_track
                and not suppress_announcement
            ):
                announcement = self.current_player_item.name
                if self.current_player_item.artist:
                    announcement += f" by {self.current_player_item.artist}"
                self.say(announcement)
            if self.resume_mode != "none":
                self.store.write(
                    "playback.json",
                    playback_state_for_resume(state, self.resume_mode),
                )

    def apply_pending_lyric_seek(self) -> None:
        pending = self.pending_lyric_seek
        item = self.current_player_item
        if not pending or not item or item.id != pending[0]:
            return
        _, position_ms = pending
        self.pending_lyric_seek = None
        self.lyric_start_item_id = None
        if not position_ms:
            return
        progress_ms = int(self.current_player_state.get("progress_ms") or 0)
        if abs(progress_ms - position_ms) <= 1_500:
            logger.info(
                "Confirmed lyric start position item=%s position_ms=%s",
                item.id,
                position_ms,
            )
            return
        device_id = self.player_device_id()
        if not device_id:
            return
        self.run_task(
            None,
            lambda: self.spotify.seek_to(position_ms, device_id),
            lambda position: logger.info(
                "Applied lyric start position item=%s position_ms=%s",
                item.id,
                position_ms,
            ),
        )

    def load_pending_resume(self) -> None:
        if self.resume_mode == "none":
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
        standalone = bool(
            state.get("standalone", not bool(context_uri))
        )
        self.standalone_player_item_id = item.id if standalone else None
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
        kind = ItemKind.TRACK
        if value.get("type") == "episode":
            kind = ItemKind.EPISODE
        if value.get("type") == "chapter" or str(value.get("uri", "")).startswith(
            "spotify:chapter:"
        ):
            kind = ItemKind.CHAPTER
            audiobook = value.get("audiobook") or {}
            album = audiobook
            artists = ", ".join(
                author.get("name", "")
                for author in audiobook.get("authors", [])
                if author.get("name")
            )
        return SpotifyItem(
            id=value["id"],
            kind=kind,
            name=value.get("name", "Untitled"),
            artist=artists,
            album=album.get("name", ""),
            duration_ms=int(value.get("duration_ms") or 0),
            uri=value.get("uri", ""),
            raw=value,
        )

    def on_player_error(self, message: str) -> None:
        if message == msg.NO_TRACKS and self.lyric_start_item_id:
            logger.info(
                "Ignored transient empty-player error while starting lyric item=%s",
                self.lyric_start_item_id,
            )
            return
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
        if self.queue_should_be_deferred():
            self.deferred_queue_items.append(item)
            self.finish_queue(item)
            logger.info("Deferred queue item id=%s name=%r", item.id, item.name)
            return
        device_id = self.player_device_id()
        if not device_id:
            return
        self.run_task(
            None,
            lambda: self.spotify.add_to_queue(item, device_id),
            lambda result: self.finish_queue(item),
        )

    def queue_command(self) -> None:
        focused = wx.Window.FindFocus()
        focused_list = item_list_ancestor(focused)
        if focused_list:
            self.queue_from_list(focused_list)
        else:
            self.queue_selected(self.current_selected_item())

    def queue_from_list(self, item_list: ItemList) -> None:
        marked = [
            item
            for item in item_list.marked_items()
            if item.uri and item.playable
        ]
        if not marked:
            focused = item_list.selected_item()
            marked = (
                [focused]
                if focused and focused.uri and focused.playable
                else []
            )
        if not marked:
            self.say(msg.NO_PLAYABLE_TRACKS)
            return
        if self.queue_should_be_deferred():
            self.deferred_queue_items.extend(marked)
            self.finish_queue_many(marked)
            logger.info("Deferred %s queue items", len(marked))
            return
        device_id = self.player_device_id()
        if not device_id:
            return

        def add_all() -> None:
            for item in marked:
                self.spotify.add_to_queue(item, device_id)

        self.run_task(
            None,
            add_all,
            lambda result: self.finish_queue_many(marked),
        )

    def queue_should_be_deferred(self) -> bool:
        return bool(getattr(self, "pending_resume", None)) or (
            getattr(self, "current_player_item", None) is None
        )

    def queue_items(self) -> list[SpotifyItem]:
        try:
            spotify_items = self.spotify.queue()
        except SpotifyError:
            if not self.deferred_queue_items:
                raise
            logger.info(
                "Spotify queue unavailable; showing %s deferred items",
                len(self.deferred_queue_items),
            )
            return list(self.deferred_queue_items)
        return spotify_items + list(self.deferred_queue_items)

    def flush_deferred_queue(self) -> None:
        if self.deferred_queue_flushing or not self.deferred_queue_items:
            return
        device_id = self.player_device_id()
        if not device_id:
            return
        items = list(self.deferred_queue_items)
        self.deferred_queue_flushing = True

        def add_all() -> None:
            for queued_item in items:
                self.spotify.add_to_queue(queued_item, device_id)

        def finished(result: object) -> None:
            del self.deferred_queue_items[:len(items)]
            self.deferred_queue_flushing = False
            logger.info("Flushed %s deferred queue items", len(items))

        def failed() -> None:
            self.deferred_queue_flushing = False

        self.run_task(None, add_all, finished, failure=failed)

    def finish_queue_many(self, items: list[SpotifyItem]) -> None:
        if self.queue.loaded_once:
            for item in items:
                self.queue.items.items.append(item)
                self.queue.items.Append(item.accessible_label())
            self.queue.status.SetLabel(
                msg.item_count(len(self.queue.items.items))
            )
        count = len(items)
        self.say(msg.queued_count(count))

    def finish_queue(self, item: SpotifyItem) -> None:
        if self.queue.loaded_once:
            self.queue.items.items.append(item)
            self.queue.items.Append(item.accessible_label())
            self.queue.status.SetLabel(
                msg.item_count(len(self.queue.items.items))
            )
        self.say(msg.QUEUED)

    def like_selected(self, item: SpotifyItem | None) -> None:
        if not item or not item.uri:
            return
        self.run_task(
            None,
            lambda: self.spotify.save(item),
            lambda result: self.finish_save_to_library(item),
        )

    def finish_save_to_library(self, item: SpotifyItem) -> None:
        self.sync_liked_item(item, True)
        self.say(msg.LIKED)

    def open_album_for_track(self, item: SpotifyItem) -> None:
        def load_album() -> tuple[SpotifyItem, list[SpotifyItem]]:
            album = self.spotify.album_for_track(item)
            return album, self.spotify.children(album)

        self.run_task(
            msg.opening_album(item.name),
            load_album,
            lambda result: self.finish_open_album(*result),
        )

    def finish_open_album(
        self,
        album: SpotifyItem,
        tracks: list[SpotifyItem],
    ) -> None:
        origin_page = self.notebook.GetSelection()
        state = ViewState(
            album.name,
            tracks,
            parent_id=album.id,
            parent_kind=ItemKind.ALBUM,
            parent_artist_names=tuple(
                artist.get("name", "")
                for artist in album.raw.get("artists") or []
                if artist.get("name")
            )
            or ((album.artist,) if album.artist else ()),
            parent_artist_ids=tuple(
                artist.get("id", "")
                for artist in album.raw.get("artists") or []
                if artist.get("id")
            ),
        )
        if origin_page != 0:
            self.open_album_return_page = origin_page
            self.open_album_return_state = state
        self.notebook.SetSelection(0)
        self.search.history.push(state)
        self.search.render(self.search.history.current, focus=True)
        # Cocoa can restore focus to the contextual-menu owner after its
        # command callback returns.  When that owner belongs to the page we
        # just hid, VoiceOver is left on an inaccessible object.  Reassert
        # focus on the next event-loop turn, after the menu and DataView's
        # accessibility tree have both settled.
        wx.CallAfter(self.focus_open_album)
        if not tracks:
            self.say(msg.named_item_count(album.name, 0))

    def return_from_open_album(self, state: ViewState) -> bool:
        if (
            state is not self.open_album_return_state
            or self.open_album_return_page is None
        ):
            return False
        page = self.open_album_return_page
        self.discard_transient_open_album()
        self.notebook.SetSelection(page)
        panels = (
            self.search,
            self.liked,
            self.queue,
            self.playlists,
            self.recently_played,
            self.bookmarks,
            self.audiobooks,
            self.podcasts,
        )
        panels[page].items.SetFocus()
        return True

    def discard_transient_open_album(self) -> bool:
        state = self.open_album_return_state
        if state is None or self.search.history.current is not state:
            return False
        self.open_album_return_page = None
        self.open_album_return_state = None
        restored = self.search.history.back()
        self.search.render(restored, focus=False)
        return True

    def focus_open_album(self) -> None:
        if self.notebook.GetCurrentPage() is not self.search:
            return
        if self.search.results.items:
            self.search.results.SetFocus()
        else:
            self.search.query.SetFocus()

    def popup_item_menu(
        self,
        owner: wx.Window,
        item: SpotifyItem,
        *,
        open_callback: Callable[[], None] | None = None,
        play_callback: Callable[[], None] | None = None,
        remove_callback: Callable[[], None] | None = None,
        remove_label: str = "&Remove from Liked Songs",
        include_album_action: bool = True,
    ) -> None:
        menu = wx.Menu()
        actions: list[tuple[wx.MenuItem, Callable[[], None]]] = []
        if open_callback:
            actions.append((menu.Append(wx.ID_ANY, "&Open"), open_callback))
        if item.playable:
            actions.append(
                (
                    menu.Append(wx.ID_ANY, "&Play now"),
                    play_callback or (lambda: self.play_playable_item(item)),
                )
            )
        if item.kind == ItemKind.PLAYLIST:
            actions.append(
                (
                    menu.Append(wx.ID_ANY, "Playlist &information..."),
                    lambda: self.show_playlist_information(item),
                )
            )
        elif item.raw.get("description"):
            actions.append(
                (
                    menu.Append(wx.ID_ANY, "&Description..."),
                    lambda: self.show_item_description(item),
                )
            )
        if item.kind == ItemKind.EPISODE:
            actions.append(
                (
                    menu.Append(wx.ID_ANY, "&Download episode..."),
                    lambda: self.find_episode_download(item),
                )
            )
        if item.kind == ItemKind.TRACK:
            if include_album_action:
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
            if not remove_callback:
                actions.append(
                    (
                        menu.Append(wx.ID_ANY, "&Save to library"),
                        lambda: self.like_selected(item),
                    )
                )
        if remove_callback:
            menu.AppendSeparator()
            actions.append(
                (
                    menu.Append(wx.ID_ANY, remove_label),
                    remove_callback,
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

    def find_episode_download(self, item: SpotifyItem) -> None:
        self.run_task(
            msg.FINDING_EPISODE_DOWNLOAD,
            lambda: find_episode_download(item),
            self.choose_episode_destination,
        )

    def choose_episode_destination(self, download: PodcastDownload) -> None:
        dialog = wx.FileDialog(
            self,
            "Download podcast episode",
            defaultFile=download.filename,
            wildcard="Audio files|*.mp3;*.m4a;*.aac;*.ogg;*.opus;*.wav;*.flac;*.mp4;*.m4v;*.webm|All files|*.*",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        )
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        destination = Path(dialog.GetPath())
        dialog.Destroy()
        self.run_task(
            msg.DOWNLOADING_EPISODE,
            lambda: download_episode(download, destination),
            lambda result: self.say(msg.EPISODE_DOWNLOADED),
        )
