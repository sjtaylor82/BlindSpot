from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

import wx

from .i18n import tr, tr_noop


CONTEXT_LABELS = {
    "Main": tr_noop("Main"),
    "Lists": tr_noop("Lists"),
    "Lyrics": tr_noop("Lyrics"),
}


@dataclass(frozen=True)
class KeyAction:
    id: str
    label: str
    context: str
    windows: tuple[str, ...] = ()
    mac: tuple[str, ...] = ()

    @property
    def title(self) -> str:
        """The label in the active language (``label`` is the English id)."""
        return tr(self.label)

    @property
    def context_title(self) -> str:
        return tr(CONTEXT_LABELS.get(self.context, self.context))

    def defaults(self, platform: str = sys.platform) -> tuple[str, ...]:
        return self.mac if platform == "darwin" else self.windows


KEY_ACTIONS = (
    KeyAction("show_manual", tr_noop("Open manual"), "Main", ("F1",), ("F1",)),
    KeyAction("play_focused", tr_noop("Play focused item"), "Main", ("F4",), ("F4",)),
    KeyAction("seek_backward", tr_noop("Seek backward five seconds"), "Main", ("F6",), ("F6",)),
    KeyAction("seek_forward", tr_noop("Seek forward five seconds"), "Main", ("F8",), ("F8",)),
    KeyAction(
        "previous_track",
        tr_noop("Restart or previous track"),
        "Main",
        ("F5",),
        ("F5",),
    ),
    KeyAction("pause_resume", tr_noop("Pause or resume"), "Main", ("F7", "Space"), ("F7", "Space")),
    KeyAction("next_track", tr_noop("Next track"), "Main", ("F9",), ("F9",)),
    KeyAction("next_verse", tr_noop("Jump to next lyric section"), "Main", ("Shift+F8",), ("Shift+F8",)),
    KeyAction(
        "previous_verse",
        tr_noop("Jump to previous lyric section"),
        "Main",
        ("Shift+F6",),
        ("Shift+F6",),
    ),
    KeyAction("toggle_mute", tr_noop("Mute or unmute"), "Main", ("Shift+F7",), ("Shift+F7",)),
    KeyAction("volume_down", tr_noop("Volume down five percent"), "Main", ("Shift+F4",), ("Shift+F4",)),
    KeyAction("volume_up", tr_noop("Volume up five percent"), "Main", ("Shift+F5",), ("Shift+F5",)),
    KeyAction("cycle_tabs", tr_noop("Next main tab"), "Main", ("Control+Tab",), ("Control+Tab",)),
    KeyAction(
        "cycle_tabs_backward",
        tr_noop("Previous main tab"),
        "Main",
        ("Control+Shift+Tab",),
        ("Control+Shift+Tab",),
    ),
    KeyAction("focus_search", tr_noop("Focus Search"), "Main", ("Control+F",), ("Control+F",)),
    KeyAction("preferences", tr_noop("Open Preferences"), "Main", ("Control+Comma",), ("Control+Comma",)),
    KeyAction("open_search", tr_noop("Open Search tab"), "Main", ("Control+1",), ("Control+1",)),
    KeyAction("open_liked", tr_noop("Open Liked Songs tab"), "Main", ("Control+2",), ("Control+2",)),
    KeyAction("open_queue", tr_noop("Open Queue tab"), "Main", ("Control+3",), ("Control+3",)),
    KeyAction("open_playlists", tr_noop("Open Playlists tab"), "Main", ("Control+4",), ("Control+4",)),
    KeyAction(
        "open_recent",
        tr_noop("Open Recently Played tab"),
        "Main",
        ("Control+5",),
        ("Control+5",),
    ),
    KeyAction("open_bookmarks", tr_noop("Open Bookmarks"), "Main", ("Control+B",), ("Control+B",)),
    KeyAction(
        "open_audiobooks",
        tr_noop("Open Audiobooks tab"),
        "Main",
        ("Control+6",),
        ("Control+6",),
    ),
    KeyAction("open_podcasts", tr_noop("Open Podcasts tab"), "Main", ("Control+7",), ("Control+7",)),
    KeyAction(
        "open_saved_albums",
        tr_noop("Open Saved Albums tab"),
        "Main",
        ("Control+8",),
        ("Control+8",),
    ),
    KeyAction("open_new_music", tr_noop("Open Discover tab"), "Main", ("Control+9",), ("Control+9",)),
    KeyAction(
        "open_concerts",
        tr_noop("Search for concerts"),
        "Main",
        ("Control+Shift+G",),
        ("Control+Shift+G",),
    ),
    KeyAction("speak_total", tr_noop("Speak total time"), "Main", ("Control+Shift+T",), ("Control+Shift+T",)),
    KeyAction("speak_elapsed", tr_noop("Speak elapsed time"), "Main", ("Control+Shift+E",), ("Control+Shift+E",)),
    KeyAction(
        "speak_remaining",
        tr_noop("Speak remaining time"),
        "Main",
        ("Control+Shift+R",),
        ("Control+Shift+R",),
    ),
    KeyAction("refresh_view", tr_noop("Refresh current view"), "Main", ("Control+Shift+F",), ("Control+Shift+F",)),
    KeyAction(
        "choose_device",
        tr_noop("Choose playback device"),
        "Main",
        ("Control+Shift+D",),
        ("Control+Shift+D",),
    ),
    KeyAction(
        "speak_current",
        tr_noop("Speak current track"),
        "Main",
        ("Control+Shift+I",),
        ("Control+Shift+I",),
    ),
    KeyAction(
        "speak_up_next",
        tr_noop("Speak upcoming track"),
        "Main",
        ("Control+Shift+U",),
        ("Control+Shift+U",),
    ),
    KeyAction("jump_time", tr_noop("Jump to playback time"), "Main", ("Control+J",), ("Control+J",)),
    KeyAction(
        "sleep_timer",
        tr_noop("Open sleep timer"),
        "Main",
        ("Control+Shift+J",),
        ("Control+Shift+J",),
    ),
    KeyAction(
        "song_story",
        tr_noop("What's this song about?"),
        "Main",
        ("Control+Shift+W",),
        ("Control+Shift+W",),
    ),
    KeyAction(
        "open_current_album",
        tr_noop("Open album of focused or current track"),
        "Main",
        ("Control+Shift+O",),
        ("Control+Shift+O",),
    ),
    KeyAction("show_lyrics", tr_noop("Retrieve lyrics"), "Main", ("Control+Y",), ("Control+Y",)),
    KeyAction("cycle_repeat", tr_noop("Cycle repeat mode"), "Main", ("Control+R",), ("Control+R",)),
    KeyAction("toggle_shuffle", tr_noop("Toggle shuffle"), "Main", ("Control+S",), ("Control+S",)),
    KeyAction("select_all", tr_noop("Select all items"), "Lists", ("Control+A",), ("Command+A",)),
    KeyAction(
        "open_similar_focused",
        tr_noop("Open Last.fm mix for focused track"),
        "Lists",
        ("Control+Shift+M",),
        ("Command+Shift+M",),
    ),
    KeyAction(
        "start_similar_focused",
        tr_noop("Start Last.fm mix for focused track"),
        "Lists",
        ("Control+Shift+P",),
        ("Command+Shift+P",),
    ),
    KeyAction(
        "open_similar_current",
        tr_noop("Open Last.fm mix for current track"),
        "Main",
        ("Control+Alt+M",),
        ("Option+Command+M",),
    ),
    KeyAction(
        "start_similar_current",
        tr_noop("Start Last.fm mix for current track"),
        "Main",
        ("Control+Alt+P",),
        ("Option+Command+P",),
    ),
    KeyAction("queue_marked", tr_noop("Queue selected items"), "Lists", ("Control+Q",), ("Control+Q",)),
    KeyAction("like_focused", tr_noop("Like or unlike focused item"), "Lists", ("Control+L",), ("Control+L",)),
    KeyAction(
        "like_current",
        tr_noop("Like or unlike current track"),
        "Main",
        ("Control+Shift+L",),
        ("Control+Shift+L",),
    ),
    KeyAction(
        "add_to_playlist",
        tr_noop("Add focused item to playlist"),
        "Lists",
        ("Control+Shift+A",),
        ("Control+Shift+A",),
    ),
    KeyAction(
        "bookmark_current",
        tr_noop("Bookmark current position"),
        "Main",
        ("Control+Shift+B",),
        ("Control+Shift+B",),
    ),
    KeyAction(
        "new_playlist",
        tr_noop("Create playlist"),
        "Main",
        ("Control+Shift+N",),
        ("Control+Shift+N",),
    ),
    KeyAction(
        "open_album",
        tr_noop("Open focused track album"),
        "Lists",
        ("Control+Enter",),
        ("Control+Enter",),
    ),
    KeyAction(
        "item_actions",
        tr_noop("Open focused item actions"),
        "Lists",
        ("Shift+F10",),
        ("Option+M",),
    ),
    KeyAction(
        "play_lyric_line",
        tr_noop("Play from selected lyric line"),
        "Lyrics",
        ("Shift+Space",),
        ("Shift+Space",),
    ),
    KeyAction(
        "previous_lyric_line",
        tr_noop("Play previous lyric line"),
        "Lyrics",
        ("Alt+Up",),
        ("Option+Command+Up",),
    ),
    KeyAction(
        "next_lyric_line",
        tr_noop("Play next lyric line"),
        "Lyrics",
        ("Alt+Down",),
        ("Option+Command+Down",),
    ),
    KeyAction(
        "lyrics_earlier",
        tr_noop("Move lyrics earlier"),
        "Lyrics",
        ("Control+Shift+Comma",),
        ("Control+Shift+Comma",),
    ),
    KeyAction(
        "lyrics_later",
        tr_noop("Move lyrics later"),
        "Lyrics",
        ("Control+Shift+Period",),
        ("Control+Shift+Period",),
    ),
)

ACTIONS_BY_ID = {action.id: action for action in KEY_ACTIONS}
CONTEXTS = tuple(dict.fromkeys(action.context for action in KEY_ACTIONS))

KEY_ALIASES = {
    "RETURN": "Enter",
    "COMMA": "Comma",
    ",": "Comma",
    "PERIOD": "Period",
    ".": "Period",
    "SPACE": "Space",
    "TAB": "Tab",
    "UP": "Up",
    "DOWN": "Down",
    "LEFT": "Left",
    "RIGHT": "Right",
    "BACKSPACE": "Backspace",
    "DELETE": "Delete",
    "HOME": "Home",
    "END": "End",
    "PAGEUP": "PageUp",
    "PAGEDOWN": "PageDown",
    "APPLICATIONS": "Applications",
}
MODIFIER_ORDER = ("Control", "Option", "Alt", "Shift", "Command", "Windows")


def normalized_chord(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parts = [part.strip() for part in value.split("+") if part.strip()]
    if not parts:
        return None
    modifiers: set[str] = set()
    for part in parts[:-1]:
        name = part.casefold()
        aliases = {
            "ctrl": "Control",
            "control": "Control",
            "rawctrl": "Control",
            "alt": "Alt",
            "option": "Option",
            "shift": "Shift",
            "cmd": "Command",
            "command": "Command",
            "win": "Windows",
            "windows": "Windows",
        }
        if name not in aliases:
            return None
        modifiers.add(aliases[name])
    key = parts[-1]
    upper = key.upper()
    if upper in KEY_ALIASES:
        key = KEY_ALIASES[upper]
    elif re_full_function_key(upper):
        key = upper
    elif len(key) == 1 and key.isprintable():
        key = key.upper()
    else:
        return None
    ordered = [name for name in MODIFIER_ORDER if name in modifiers]
    return "+".join(ordered + [key])


def re_full_function_key(value: str) -> bool:
    if not value.startswith("F"):
        return False
    try:
        number = int(value[1:])
    except ValueError:
        return False
    return 1 <= number <= 24


def normalized_keymap(value: object) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    bindings = value.get("bindings", value)
    if not isinstance(bindings, dict):
        return {}
    result: dict[str, list[str]] = {}
    for action_id, raw_chords in bindings.items():
        if action_id not in ACTIONS_BY_ID or not isinstance(raw_chords, list):
            continue
        chords = []
        for raw_chord in raw_chords:
            chord = normalized_chord(raw_chord)
            if chord and chord not in chords:
                chords.append(chord)
        result[action_id] = chords
    return result


class KeyMap:
    def __init__(
        self,
        custom: object = None,
        *,
        platform: str = sys.platform,
    ) -> None:
        self.platform = platform
        self.custom = normalized_keymap(custom)

    def bindings(self, action_id: str) -> tuple[str, ...]:
        if action_id in self.custom:
            return tuple(self.custom[action_id])
        return ACTIONS_BY_ID[action_id].defaults(self.platform)

    def set_binding(self, action_id: str, chord: str) -> None:
        normalized = normalized_chord(chord)
        if action_id not in ACTIONS_BY_ID or not normalized:
            raise ValueError("Invalid key assignment")
        context = ACTIONS_BY_ID[action_id].context
        for other in KEY_ACTIONS:
            if other.context != context or other.id == action_id:
                continue
            existing = list(self.bindings(other.id))
            if normalized in existing:
                self.custom[other.id] = [
                    value for value in existing if value != normalized
                ]
        self.custom[action_id] = [normalized]

    def clear(self, action_id: str) -> None:
        self.custom[action_id] = []

    def restore_defaults(self, context: str | None = None) -> None:
        if context is None:
            self.custom.clear()
            return
        for action in KEY_ACTIONS:
            if action.context == context:
                self.custom.pop(action.id, None)

    def owner(self, chord: str, context: str) -> KeyAction | None:
        normalized = normalized_chord(chord)
        for action in KEY_ACTIONS:
            if action.context == context and normalized in self.bindings(action.id):
                return action
        return None

    def disabled_default(self, chord: str, contexts: tuple[str, ...]) -> bool:
        normalized = normalized_chord(chord)
        return any(
            action.context in contexts
            and normalized in action.defaults(self.platform)
            and normalized not in self.bindings(action.id)
            for action in KEY_ACTIONS
        )

    def to_json(self, warnings_seen: set[str] | None = None) -> dict[str, Any]:
        return {
            "bindings": self.custom,
            "warnings_seen": sorted(warnings_seen or ()),
        }


def warnings_seen(value: object) -> set[str]:
    if not isinstance(value, dict) or not isinstance(value.get("warnings_seen"), list):
        return set()
    return {
        warning
        for warning in value["warnings_seen"]
        if warning in {"global", "navigation", "os", "typing", "voiceover"}
    }


def conflict_warning(chord: str, platform: str = sys.platform) -> str | None:
    normalized = normalized_chord(chord)
    if not normalized:
        return None
    if len(normalized) == 1 and normalized.isprintable():
        return "typing"
    if normalized in {"Comma", "Period"}:
        return "typing"
    if normalized in {
        "Up",
        "Down",
        "Left",
        "Right",
        "Home",
        "End",
        "PageUp",
        "PageDown",
        "Tab",
    }:
        return "navigation"
    if platform == "darwin":
        if normalized.startswith("Control+Option+"):
            return "voiceover"
        if normalized in {
            "Control+F4",
            "Control+F5",
            "Control+F6",
            "Control+Space",
            "Control+Up",
            "Control+Down",
            "Command+Space",
            "Command+F5",
        }:
            return "os"
    elif normalized in {"Alt+F4", "Windows+L", "Windows+D"}:
        return "os"
    return None


SPECIAL_KEY_NAMES = {
    wx.WXK_SPACE: "Space",
    wx.WXK_RETURN: "Enter",
    wx.WXK_NUMPAD_ENTER: "Enter",
    wx.WXK_TAB: "Tab",
    wx.WXK_DELETE: "Delete",
    wx.WXK_BACK: "Backspace",
    wx.WXK_LEFT: "Left",
    wx.WXK_RIGHT: "Right",
    wx.WXK_UP: "Up",
    wx.WXK_DOWN: "Down",
    wx.WXK_HOME: "Home",
    wx.WXK_END: "End",
    wx.WXK_PAGEUP: "PageUp",
    wx.WXK_PAGEDOWN: "PageDown",
    wx.WXK_MENU: "Applications",
    wx.WXK_WINDOWS_MENU: "Applications",
    ord(","): "Comma",
    ord("."): "Period",
}


def chord_from_event(event: wx.KeyEvent, platform: str = sys.platform) -> str | None:
    keycode = int(event.GetKeyCode())
    if wx.WXK_F1 <= keycode <= wx.WXK_F24:
        key = f"F{keycode - wx.WXK_F1 + 1}"
    elif keycode in SPECIAL_KEY_NAMES:
        key = SPECIAL_KEY_NAMES[keycode]
    elif 32 <= keycode < 127:
        key = chr(keycode).upper()
    else:
        return None
    get_modifiers = getattr(event, "GetModifiers", None)
    modifiers = int(get_modifiers()) if get_modifiers else 0
    parts = []
    if platform == "darwin":
        raw_control = bool(modifiers & wx.MOD_RAW_CONTROL)
        command = bool(modifiers & wx.MOD_CONTROL)
        if not get_modifiers:
            raw_control = bool(getattr(event, "RawControlDown", lambda: False)())
            command = bool(event.ControlDown()) and not raw_control
        if raw_control:
            parts.append("Control")
        if bool(modifiers & wx.MOD_ALT) or event.AltDown():
            parts.append("Option")
        if event.ShiftDown():
            parts.append("Shift")
        if command:
            parts.append("Command")
    else:
        if bool(modifiers & wx.MOD_CONTROL) or event.ControlDown():
            parts.append("Control")
        if bool(modifiers & wx.MOD_ALT) or event.AltDown():
            parts.append("Alt")
        if event.ShiftDown():
            parts.append("Shift")
        if bool(modifiers & wx.MOD_WIN):
            parts.append("Windows")
    return normalized_chord("+".join(parts + [key]))
