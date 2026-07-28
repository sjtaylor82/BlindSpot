from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

import wx


@dataclass(frozen=True)
class KeyAction:
    id: str
    label: str
    context: str
    windows: tuple[str, ...] = ()
    mac: tuple[str, ...] = ()

    def defaults(self, platform: str = sys.platform) -> tuple[str, ...]:
        return self.mac if platform == "darwin" else self.windows


KEY_ACTIONS = (
    KeyAction("show_manual", "Open manual", "Main", ("F1",), ("F1",)),
    KeyAction("play_focused", "Play focused item", "Main", ("F4",), ("F4",)),
    KeyAction("seek_backward", "Seek backward five seconds", "Main", ("F5",), ("F5",)),
    KeyAction("seek_forward", "Seek forward five seconds", "Main", ("F6",), ("F6",)),
    KeyAction(
        "previous_track",
        "Restart or previous track",
        "Main",
        ("F7",),
        ("F7",),
    ),
    KeyAction("pause_resume", "Pause or resume", "Main", ("F8", "Space"), ("F8", "Space")),
    KeyAction("next_track", "Next track", "Main", ("F9",), ("F9",)),
    KeyAction("toggle_mute", "Mute or unmute", "Main", ("Shift+F4",), ("Shift+F4",)),
    KeyAction("volume_down", "Volume down five percent", "Main", ("Shift+F5",), ("Shift+F5",)),
    KeyAction("volume_up", "Volume up five percent", "Main", ("Shift+F6",), ("Shift+F6",)),
    KeyAction("cycle_tabs", "Next main tab", "Main", ("Control+Tab",), ("Control+Tab",)),
    KeyAction(
        "cycle_tabs_backward",
        "Previous main tab",
        "Main",
        ("Control+Shift+Tab",),
        ("Control+Shift+Tab",),
    ),
    KeyAction("focus_search", "Focus Search", "Main", ("Control+F",), ("Control+F",)),
    KeyAction("preferences", "Open Preferences", "Main", ("Control+Comma",), ("Control+Comma",)),
    KeyAction("open_search", "Open Search tab", "Main", ("Control+1",), ("Control+1",)),
    KeyAction("open_liked", "Open Liked Songs tab", "Main", ("Control+2",), ("Control+2",)),
    KeyAction("open_queue", "Open Queue tab", "Main", ("Control+3",), ("Control+3",)),
    KeyAction("open_playlists", "Open Playlists tab", "Main", ("Control+4",), ("Control+4",)),
    KeyAction(
        "open_recent",
        "Open Recently Played tab",
        "Main",
        ("Control+5",),
        ("Control+5",),
    ),
    KeyAction("open_bookmarks", "Open Bookmarks tab", "Main", ("Control+6",), ("Control+6",)),
    KeyAction(
        "open_audiobooks",
        "Open Audiobooks tab",
        "Main",
        ("Control+7",),
        ("Control+7",),
    ),
    KeyAction("open_podcasts", "Open Podcasts tab", "Main", ("Control+8",), ("Control+8",)),
    KeyAction(
        "open_saved_albums",
        "Open Saved Albums tab",
        "Main",
        ("Control+9",),
        ("Control+9",),
    ),
    KeyAction("open_new_music", "Open New Music tab", "Main", ("Control+0",), ("Control+0",)),
    KeyAction("speak_total", "Speak total time", "Main", ("Control+Shift+T",), ("Control+Shift+T",)),
    KeyAction("speak_elapsed", "Speak elapsed time", "Main", ("Control+Shift+E",), ("Control+Shift+E",)),
    KeyAction(
        "speak_remaining",
        "Speak remaining time",
        "Main",
        ("Control+Shift+R",),
        ("Control+Shift+R",),
    ),
    KeyAction("refresh_view", "Refresh current view", "Main", ("Control+Shift+F",), ("Control+Shift+F",)),
    KeyAction(
        "choose_device",
        "Choose playback device",
        "Main",
        ("Control+Shift+D",),
        ("Control+Shift+D",),
    ),
    KeyAction(
        "speak_current",
        "Speak current track",
        "Main",
        ("Control+Shift+I",),
        ("Control+Shift+I",),
    ),
    KeyAction(
        "speak_up_next",
        "Speak upcoming track",
        "Main",
        ("Control+Shift+U",),
        ("Control+Shift+U",),
    ),
    KeyAction("jump_time", "Jump to playback time", "Main", ("Control+J",), ("Control+J",)),
    KeyAction(
        "sleep_timer",
        "Open sleep timer",
        "Main",
        ("Control+Shift+J",),
        ("Control+Shift+J",),
    ),
    KeyAction("show_lyrics", "Retrieve lyrics", "Main", ("Control+Y",), ("Control+Y",)),
    KeyAction("cycle_repeat", "Cycle repeat mode", "Main", ("Control+R",), ("Control+R",)),
    KeyAction("toggle_shuffle", "Toggle shuffle", "Main", ("Control+S",), ("Control+S",)),
    KeyAction("queue_marked", "Queue selected items", "Lists", ("Control+Q",), ("Control+Q",)),
    KeyAction("like_focused", "Like or unlike focused item", "Lists", ("Control+L",), ("Control+L",)),
    KeyAction(
        "like_current",
        "Like or unlike current track",
        "Main",
        ("Control+Shift+L",),
        ("Control+Shift+L",),
    ),
    KeyAction(
        "add_to_playlist",
        "Add focused item to playlist",
        "Lists",
        ("Control+Shift+A",),
        ("Control+Shift+A",),
    ),
    KeyAction(
        "bookmark_current",
        "Bookmark current position",
        "Main",
        ("Control+Shift+B",),
        ("Control+Shift+B",),
    ),
    KeyAction(
        "new_playlist",
        "Create playlist",
        "Main",
        ("Control+Shift+N",),
        ("Control+Shift+N",),
    ),
    KeyAction(
        "open_album",
        "Open focused track album",
        "Lists",
        ("Control+Enter",),
        ("Control+Enter",),
    ),
    KeyAction(
        "item_actions",
        "Open focused item actions",
        "Lists",
        ("Shift+F10",),
        ("Option+M",),
    ),
    KeyAction(
        "play_lyric_line",
        "Play from selected lyric line",
        "Lyrics",
        ("Shift+Space",),
        ("Shift+Space",),
    ),
    KeyAction(
        "previous_lyric_line",
        "Play previous lyric line",
        "Lyrics",
        ("Control+Up",),
        ("Option+Command+Up",),
    ),
    KeyAction(
        "next_lyric_line",
        "Play next lyric line",
        "Lyrics",
        ("Control+Down",),
        ("Option+Command+Down",),
    ),
    KeyAction(
        "lyrics_earlier",
        "Move lyrics earlier",
        "Lyrics",
        ("Control+Shift+Comma",),
        ("Control+Shift+Comma",),
    ),
    KeyAction(
        "lyrics_later",
        "Move lyrics later",
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
