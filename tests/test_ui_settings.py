import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from blindspot import ui
from blindspot.ui import (
    LyricsDialog,
    MainFrame,
    PlaylistsPanel,
    playback_state_for_resume,
    resume_mode_from_settings,
)


class PlaybackMemorySettingsTests(unittest.TestCase):
    def test_legacy_enabled_setting_migrates_to_track_and_position(self):
        self.assertEqual(
            resume_mode_from_settings({"resume_last_track": True}),
            "track_and_position",
        )

    def test_explicit_mode_takes_precedence_over_legacy_setting(self):
        self.assertEqual(
            resume_mode_from_settings(
                {"resume_mode": "track", "resume_last_track": True}
            ),
            "track",
        )

    def test_track_only_storage_resets_position_without_mutating_state(self):
        state = {"progress_ms": 42_000, "item": {"id": "track"}}

        stored = playback_state_for_resume(state, "track")

        self.assertEqual(stored["progress_ms"], 0)
        self.assertEqual(state["progress_ms"], 42_000)

    def test_global_shortcut_settings_are_validated_and_labelled(self):
        shortcuts = ui.normalized_global_shortcuts(
            {
                "previous_track": {
                    "modifiers": ui.wx.MOD_CONTROL,
                    "keycode": ui.wx.WXK_F7,
                },
                "unknown": {"modifiers": 0, "keycode": 1},
                "next_track": {"keycode": "invalid"},
            }
        )
        self.assertEqual(
            shortcuts,
            {
                "previous_track": {
                    "modifiers": ui.wx.MOD_CONTROL,
                    "keycode": ui.wx.WXK_F7,
                }
            },
        )
        self.assertEqual(
            ui.shortcut_label(shortcuts["previous_track"]),
            "Control+F7",
        )


class GlobalShortcutRegistrationTests(unittest.TestCase):
    def test_shortcut_dialog_ok_saves_immediately(self):
        saved = []
        preferences = type(
            "Preferences",
            (),
            {
                "global_shortcuts": {},
                "save_global_shortcuts": lambda self, value: saved.append(value),
                "get_global_shortcuts": (
                    ui.PreferencesDialog.get_global_shortcuts
                ),
            },
        )()
        shortcut = {"modifiers": 0, "keycode": ui.wx.WXK_F9}
        dialog = type(
            "Dialog",
            (),
            {
                "shortcuts": {"next_track": shortcut},
                "ShowModal": lambda self: ui.wx.ID_OK,
                "Destroy": lambda self: None,
            },
        )()

        with patch(
            "blindspot.ui.GlobalShortcutsDialog",
            return_value=dialog,
        ):
            ui.PreferencesDialog.on_global_shortcuts(preferences, None)

        self.assertEqual(saved, [{"next_track": shortcut}])

    def test_immediate_shortcut_save_writes_and_applies_hotkeys(self):
        writes = []
        applied = []
        store = type(
            "Store",
            (),
            {
                "read": lambda self, name, default: {"logging_level": "Off"},
                "write": lambda self, name, value: writes.append(
                    (name, value.copy())
                ),
            },
        )()
        frame = type(
            "Frame",
            (),
            {
                "store": store,
                "apply_global_hotkey_setting": (
                    lambda self: applied.append(True)
                ),
            },
        )()
        shortcut = {"modifiers": 0, "keycode": ui.wx.WXK_F9}

        MainFrame.save_global_shortcuts(
            frame,
            {"next_track": shortcut},
        )

        self.assertEqual(frame.global_shortcuts, {"next_track": shortcut})
        self.assertEqual(
            writes,
            [
                (
                    "settings.json",
                    {
                        "logging_level": "Off",
                        "global_shortcuts": {"next_track": shortcut},
                    },
                )
            ],
        )
        self.assertEqual(applied, [True])

    def test_windows_key_is_added_to_captured_modifiers(self):
        event = type(
            "Event",
            (),
            {
                "GetModifiers": lambda self: ui.wx.MOD_ALT,
                "MetaDown": lambda self: False,
                "GetKeyCode": lambda self: ord("N"),
            },
        )()

        with (
            patch("blindspot.ui.sys.platform", "win32"),
            patch("blindspot.ui.wx.GetKeyState", return_value=True),
        ):
            shortcut = ui.captured_shortcut(event)

        self.assertEqual(
            shortcut,
            {
                "modifiers": ui.wx.MOD_ALT | ui.wx.MOD_WIN,
                "keycode": ord("N"),
            },
        )
        self.assertEqual(ui.shortcut_label(shortcut), "Alt+Windows+N")

    def test_failed_assignment_does_not_disable_other_shortcuts(self):
        calls = []
        messages = []
        previous_id = ui.GLOBAL_SHORTCUT_IDS["previous_track"]
        next_id = ui.GLOBAL_SHORTCUT_IDS["next_track"]
        frame = type(
            "Frame",
            (),
            {
                "global_shortcuts": {
                    "previous_track": {
                        "modifiers": 0,
                        "keycode": ui.wx.WXK_F7,
                    },
                    "next_track": {
                        "modifiers": 0,
                        "keycode": ui.wx.WXK_F9,
                    },
                },
                "registered_hotkey_ids": [],
                "unregister_global_hotkeys": (
                    lambda self: self.registered_hotkey_ids.clear()
                ),
                "RegisterHotKey": (
                    lambda self, hotkey_id, modifiers, keycode: (
                        calls.append((hotkey_id, modifiers, keycode))
                        or hotkey_id != previous_id
                    )
                ),
                "say": lambda self, message: messages.append(message),
            },
        )()

        MainFrame.apply_global_hotkey_setting(frame)

        self.assertEqual([call[0] for call in calls], [previous_id, next_id])
        self.assertEqual(frame.registered_hotkey_ids, [next_id])
        self.assertIn("Previous track (F7)", messages[0])


class RecentlyPlayedRefreshTests(unittest.TestCase):
    def test_opening_recently_played_tab_requests_fresh_items(self):
        refreshed = []
        recent = type(
            "Recent",
            (),
            {
                "heading": type(
                    "Heading",
                    (),
                    {"GetLabel": lambda self: "Recently Played"},
                )(),
                "refresh": lambda self: refreshed.append(True),
            },
        )()
        notebook = type(
            "Notebook",
            (),
            {
                "GetPage": lambda self, selection: recent,
                "GetPageText": lambda self, selection: "Recently Played",
            },
        )()
        frame = type(
            "Frame",
            (),
            {
                "notebook": notebook,
                "recently_played": recent,
                "set_view_title": lambda self, title: None,
            },
        )()
        event = type(
            "Event",
            (),
            {
                "GetSelection": lambda self: 4,
                "Skip": lambda self: None,
            },
        )()

        with patch(
            "blindspot.ui.wx.CallAfter",
            side_effect=lambda callback, *args: callback(*args),
        ):
            MainFrame.on_tab_changed(frame, event)

        self.assertEqual(refreshed, [True])

    def test_local_playlist_play_is_kept_and_merged_ahead_of_spotify(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ui.PortableStore(Path(folder))
            playlist_track = ui.SpotifyItem(
                id="playlist-track",
                kind=ui.ItemKind.TRACK,
                name="Playlist Song",
                uri="spotify:track:playlist-track",
            )
            spotify_track = ui.SpotifyItem(
                id="spotify-track",
                kind=ui.ItemKind.TRACK,
                name="Spotify Song",
                uri="spotify:track:spotify-track",
            )
            frame = type(
                "Frame",
                (),
                {
                    "store": store,
                    "spotify": type(
                        "Spotify",
                        (),
                        {"recently_played": lambda self: [spotify_track]},
                    )(),
                },
            )()

            MainFrame.remember_recently_played(frame, playlist_track)
            items = MainFrame.load_recently_played(frame)

            self.assertEqual(
                [item.id for item in items],
                ["playlist-track", "spotify-track"],
            )
            self.assertIn("in BlindSpot", items[0].accessible_label())


class UpdatePromptFocusTests(unittest.TestCase):
    class FocusTarget:
        def __init__(self, shown=True, enabled=True):
            self.shown = shown
            self.enabled = enabled
            self.focused = False

        def IsShown(self):
            return self.shown

        def IsEnabled(self):
            return self.enabled

        def SetFocus(self):
            self.focused = True

    class Search:
        def __init__(self):
            self.focused = False

        def focus_query(self):
            self.focused = True

    def test_restores_control_that_had_focus_before_update_prompt(self):
        target = self.FocusTarget()
        frame = type("Frame", (), {"search": self.Search()})()

        MainFrame._restore_focus_after_update_prompt(frame, target)

        self.assertTrue(target.focused)
        self.assertFalse(frame.search.focused)

    def test_falls_back_to_search_when_previous_control_is_unavailable(self):
        target = self.FocusTarget(shown=False)
        frame = type("Frame", (), {"search": self.Search()})()

        MainFrame._restore_focus_after_update_prompt(frame, target)

        self.assertFalse(target.focused)
        self.assertTrue(frame.search.focused)


class BrailleLyricsTests(unittest.TestCase):
    class Text:
        def __init__(self):
            self.insertion_points = []
            self.shown_positions = []

        def SetInsertionPoint(self, position):
            self.insertion_points.append(position)

        def ShowPosition(self, position):
            self.shown_positions.append(position)

    class Announcer:
        def __init__(self):
            self.braille_messages = []
            self.output_messages = []

        def braille(self, message):
            self.braille_messages.append(message)

        def output(self, message):
            self.output_messages.append(message)

    def make_dialog(self, position_ms=2_500):
        announcer = self.Announcer()
        text = self.Text()
        frame = type(
            "Frame",
            (),
            {
                "announcer": announcer,
                "playback_position_ms": lambda self, track_id: position_ms,
            },
        )()
        dialog = type(
            "Dialog",
            (),
            {
                "frame": frame,
                "track_id": "track",
                "synced_lines": [
                    (1_000, "Current lyric"),
                    (2_000, "Next lyric"),
                ],
                "lyric_adjustment_ms": 0,
                "last_braille_line": -1,
                "synced_line_positions": [0, 14],
                "text": text,
            },
        )()
        return dialog, announcer, text

    def test_windows_advances_one_second_before_next_timestamp(self):
        dialog, announcer, text = self.make_dialog(position_ms=1_000)

        with patch("blindspot.ui.sys.platform", "win32"):
            LyricsDialog.update_braille_line(dialog)

        self.assertEqual(text.insertion_points, [14])
        self.assertEqual(text.shown_positions, [14])
        self.assertEqual(announcer.braille_messages, [])

    def test_windows_keeps_current_lyric_until_lead_window(self):
        dialog, announcer, text = self.make_dialog(position_ms=999)

        with patch("blindspot.ui.sys.platform", "win32"):
            LyricsDialog.update_braille_line(dialog)

        self.assertEqual(text.insertion_points, [0])
        self.assertEqual(announcer.braille_messages, [])

    def test_windows_moves_caret_only_once_per_lyric(self):
        dialog, announcer, text = self.make_dialog(position_ms=400)

        with patch("blindspot.ui.sys.platform", "win32"):
            LyricsDialog.update_braille_line(dialog)
            LyricsDialog.update_braille_line(dialog)
            LyricsDialog.update_braille_line(dialog)

        self.assertEqual(text.insertion_points, [0])
        self.assertEqual(announcer.braille_messages, [])

    def test_following_waits_for_an_unplayed_song_to_start(self):
        dialog, announcer, text = self.make_dialog(position_ms=None)

        LyricsDialog.update_braille_line(dialog)

        self.assertEqual(dialog.last_braille_line, -1)
        self.assertEqual(text.insertion_points, [])
        self.assertEqual(announcer.braille_messages, [])

    def test_macos_uses_same_one_second_lead(self):
        dialog, announcer, text = self.make_dialog(position_ms=1_000)

        with patch("blindspot.ui.sys.platform", "darwin"):
            LyricsDialog.update_braille_line(dialog)
            LyricsDialog.update_braille_line(dialog)

        self.assertEqual(announcer.output_messages, ["Next lyric"])

    def test_maps_synced_lines_to_matching_read_only_text_lines(self):
        positions = LyricsDialog._synced_line_positions(
            "Repeated line\nDifferent line\nRepeated line",
            [
                (1_000, "Repeated line"),
                (2_000, "Different   line"),
                (3_000, "Repeated line"),
            ],
        )

        self.assertEqual(positions, [0, 14, 29])


class LyricsPreferenceTests(unittest.TestCase):
    class Store:
        def __init__(self):
            self.settings = {"unrelated": True}

        def read(self, name, default=None):
            return dict(self.settings)

        def write(self, name, value):
            self.settings = value

    def test_follow_braille_choice_is_saved_without_losing_other_settings(self):
        store = self.Store()
        frame = type(
            "Frame",
            (),
            {
                "store": store,
                "follow_braille_lyrics": False,
            },
        )()

        MainFrame.set_follow_braille_lyrics(frame, True)

        self.assertTrue(frame.follow_braille_lyrics)
        self.assertEqual(
            store.settings,
            {"unrelated": True, "follow_braille_lyrics": True},
        )

    def test_track_timing_adjustment_is_saved_in_lyrics_file(self):
        class LyricsStore:
            def __init__(self):
                self.value = {"track": {"source": {"track_name": "Song"}}}

            def read(self, name, default=None):
                return self.value

            def write(self, name, value):
                self.name = name
                self.value = value

        store = LyricsStore()
        frame = type("Frame", (), {"store": store})()

        MainFrame.set_lyric_adjustment_ms(frame, "track", 500)

        self.assertEqual(store.name, "lyrics.json")
        self.assertEqual(store.value["track"]["adjustment_ms"], 500)
        self.assertEqual(
            store.value["track"]["source"],
            {"track_name": "Song"},
        )


class PauseResumeTests(unittest.TestCase):
    def test_pause_resume_says_nothing_playing_without_current_track(self):
        messages = []
        frame = type(
            "Frame",
            (),
            {
                "current_player_item": None,
                "say": lambda self, message: messages.append(message),
            },
        )()

        MainFrame.toggle_pause_resume(frame)

        self.assertEqual(messages, ["Nothing playing."])


class MuteTests(unittest.TestCase):
    class Spotify:
        def __init__(self):
            self.volumes = iter((37, 0))
            self.targets = []

        def playback_state(self):
            return {"device": {"volume_percent": next(self.volumes)}}

        def set_volume(self, volume, device_id):
            self.targets.append((volume, device_id))

    def test_remote_mute_restores_volume_from_before_mute(self):
        messages = []
        spotify = self.Spotify()
        frame = type(
            "Frame",
            (),
            {
                "spotify": spotify,
                "remote_device_id": "device",
                "remote_supports_volume": True,
                "remote_device_name": "Speaker",
                "volume_before_mute_percent": 50,
                "player_device_id": lambda self: "device",
                "using_local_player": lambda self: False,
                "run_task": lambda self, message, worker, success: success(
                    worker()
                ),
                "finish_remote_toggle_mute": (
                    MainFrame.finish_remote_toggle_mute
                ),
                "finish_toggle_mute": MainFrame.finish_toggle_mute,
                "say": lambda self, message: messages.append(message),
            },
        )()

        MainFrame.toggle_mute(frame)
        MainFrame.toggle_mute(frame)

        self.assertEqual(
            spotify.targets,
            [(0, "device"), (37, "device")],
        )
        self.assertEqual(messages, ["Muted.", "Unmuted."])


class PlaybackFeedbackTests(unittest.TestCase):
    def test_ordinary_play_is_silent_but_playlist_track_is_announced(self):
        messages = []
        frame = type(
            "Frame",
            (),
            {
                "remote_device_id": "device",
                "run_task": lambda self, message, worker, success: (
                    messages.append(message)
                ),
                "spotify": object(),
                "on_play_started": lambda self, item: None,
            },
        )()
        item = type("Item", (), {"id": "track", "name": "Song"})()
        playlist = type(
            "Playlist",
            (),
            {"uri": "spotify:playlist:1"},
        )()

        MainFrame.play(frame, item)
        MainFrame.play_in_context(frame, playlist, item)

        self.assertEqual(messages, [None, "Playing Song"])


class MultipleQueueTests(unittest.TestCase):
    def test_marked_tracks_are_queued_in_list_order(self):
        first = type(
            "Item",
            (),
            {"uri": "spotify:track:1", "playable": True},
        )()
        second = type(
            "Item",
            (),
            {"uri": "spotify:track:2", "playable": True},
        )()
        queued = []
        messages = []
        item_list = type(
            "List",
            (),
            {
                "marked_items": lambda self: [first, second],
                "selected_item": lambda self: first,
            },
        )()
        frame = type(
            "Frame",
            (),
            {
                "spotify": type(
                    "Spotify",
                    (),
                    {"add_to_queue": lambda self, item: queued.append(item)},
                )(),
                "run_task": lambda self, message, worker, completed: (
                    worker(),
                    completed(None),
                ),
                "finish_queue_many": lambda self, items: messages.append(
                    len(items)
                ),
                "say": lambda self, message: messages.append(message),
            },
        )()

        MainFrame.queue_from_list(frame, item_list)

        self.assertEqual(queued, [first, second])
        self.assertEqual(messages, [2])


class PlaylistRefreshTests(unittest.TestCase):
    def test_completed_playlist_load_does_not_leave_the_tab_bar(self):
        focus_calls = []
        items = object()
        panel = type(
            "Panel",
            (),
            {
                "loading": True,
                "loaded_once": False,
                "pending_playlist_selection_id": None,
                "history": ui.NavigationHistory(ui.ViewState("Playlists", [])),
                "current_playlist": None,
                "items": items,
                "render": (
                    lambda self, state, *, focus: focus_calls.append(focus)
                ),
            },
        )()
        tab_bar = object()

        with patch("blindspot.ui.wx.Window.FindFocus", return_value=tab_bar):
            PlaylistsPanel.show_playlists(panel, [])

        self.assertEqual(focus_calls, [False])

    def test_added_track_updates_open_playlist_without_taking_focus(self):
        track = object()
        state = type("State", (), {"items": []})()
        rendered = []
        messages = []
        playlists = type(
            "Playlists",
            (),
            {
                "current_playlist": type("Playlist", (), {"id": "list"})(),
                "history": type("History", (), {"current": state})(),
                "render": lambda self, value, *, focus: rendered.append(
                    (value, focus)
                ),
            },
        )()
        frame = type(
            "Frame",
            (),
            {
                "playlists": playlists,
                "say": lambda self, message: messages.append(message),
            },
        )()
        selected_playlist = type("Playlist", (), {"id": "list"})()

        MainFrame.finish_add_to_playlist(frame, selected_playlist, track)

        self.assertEqual(state.items, [track])
        self.assertEqual(rendered, [(state, False)])
        self.assertEqual(messages, ["Added."])

    def test_delete_on_playlist_list_removes_focused_playlist(self):
        playlist = object()
        removed = []
        panel = type(
            "Panel",
            (),
            {
                "history": type("History", (), {"can_go_back": False})(),
                "items": type(
                    "Items",
                    (),
                    {"selected_item": lambda self: playlist},
                )(),
                "remove_playlist": lambda self, item: removed.append(item),
            },
        )()
        event = type(
            "Event",
            (),
            {"GetKeyCode": lambda self: 127},
        )()

        with patch("blindspot.ui.wx.WXK_DELETE", 127):
            PlaylistsPanel.on_key(panel, event)

        self.assertEqual(removed, [playlist])


class LyricsKeyboardTests(unittest.TestCase):
    class Event:
        def __init__(
            self,
            key,
            *,
            shift=False,
            alt=False,
            control=False,
            event_object=None,
        ):
            self.key = key
            self.shift = shift
            self.alt = alt
            self.control = control
            self.event_object = event_object
            self.skipped = False

        def GetKeyCode(self):
            return self.key

        def ControlDown(self):
            return self.control

        def RawControlDown(self):
            return self.control

        def ShiftDown(self):
            return self.shift

        def AltDown(self):
            return self.alt

        def GetEventObject(self):
            return self.event_object

        def Skip(self):
            self.skipped = True

    class Frame:
        def __init__(self):
            self.commands = []

        def play(self, item, *, announce=False):
            self.commands.append(("play", item))

        def toggle_pause_resume(self):
            self.commands.append(("pause_resume",))

        def toggle_mute(self):
            self.commands.append(("mute",))

        def seek(self, amount):
            self.commands.append(("seek", amount))

        def adjust_volume(self, amount):
            self.commands.append(("volume", amount))

        def previous_track(self):
            self.commands.append(("previous",))

        def next_track(self):
            self.commands.append(("next",))

    def test_transport_shortcuts_work_in_lyrics_text(self):
        frame = self.Frame()
        item = object()
        dialog = type("Dialog", (), {"frame": frame, "item": item})()

        with patch("blindspot.ui.sys.platform", "win32"):
            LyricsDialog.on_dialog_key(dialog, self.Event(343))
            LyricsDialog.on_dialog_key(dialog, self.Event(344))
            LyricsDialog.on_dialog_key(dialog, self.Event(345))
            LyricsDialog.on_dialog_key(dialog, self.Event(346))
            LyricsDialog.on_dialog_key(dialog, self.Event(347))
            LyricsDialog.on_dialog_key(dialog, self.Event(348))
            LyricsDialog.on_dialog_key(dialog, self.Event(343, control=True))
            LyricsDialog.on_dialog_key(dialog, self.Event(344, control=True))
            LyricsDialog.on_dialog_key(dialog, self.Event(345, control=True))

        self.assertEqual(
            frame.commands,
            [
                ("play", item),
                ("seek", -5000),
                ("seek", 5000),
                ("previous",),
                ("pause_resume",),
                ("next",),
                ("mute",),
                ("volume", -5),
                ("volume", 5),
            ],
        )

    def test_removed_control_p_and_n_are_left_to_text_control(self):
        frame = self.Frame()
        dialog = type(
            "Dialog",
            (),
            {"frame": frame, "item": object()},
        )()

        previous = self.Event(ord("P"), control=True)
        next_event = self.Event(ord("N"), control=True)
        LyricsDialog.on_text_key(dialog, previous)
        LyricsDialog.on_text_key(dialog, next_event)

        self.assertEqual(frame.commands, [])
        self.assertTrue(previous.skipped)
        self.assertTrue(next_event.skipped)

    def test_media_style_transport_keys_work_in_main_frame(self):
        frame = self.Frame()

        with (
            patch("blindspot.ui.sys.platform", "win32"),
            patch("blindspot.ui.wx.Window.FindFocus", return_value=None),
        ):
            MainFrame.on_global_key(frame, self.Event(343, control=True))
            MainFrame.on_global_key(frame, self.Event(344, control=True))
            MainFrame.on_global_key(frame, self.Event(345, control=True))
            MainFrame.on_global_key(frame, self.Event(344))
            MainFrame.on_global_key(frame, self.Event(345))
            MainFrame.on_global_key(frame, self.Event(346))
            MainFrame.on_global_key(frame, self.Event(347))
            MainFrame.on_global_key(frame, self.Event(348))

        self.assertEqual(
            frame.commands,
            [
                ("mute",),
                ("volume", -5),
                ("volume", 5),
                ("seek", -5000),
                ("seek", 5000),
                ("previous",),
                ("pause_resume",),
                ("next",),
            ],
        )

    def test_f8_retains_normal_pause_resume_behavior_in_lyrics(self):
        toggled = []
        frame = type(
            "Frame",
            (),
            {
                "toggle_pause_resume": lambda self: toggled.append(True),
            },
        )()
        dialog = type("Dialog", (), {"frame": frame})()

        LyricsDialog.on_dialog_key(dialog, self.Event(ui.wx.WXK_F8))

        self.assertEqual(toggled, [True])

    def test_f4_retains_normal_play_behavior_in_lyrics(self):
        played = []
        item = object()
        frame = type(
            "Frame",
            (),
            {
                "play": lambda self, value, announce=False: played.append(value),
            },
        )()
        dialog = type("Dialog", (), {"frame": frame, "item": item})()

        LyricsDialog.on_dialog_key(dialog, self.Event(ui.wx.WXK_F4))

        self.assertEqual(played, [item])

    def test_space_resumes_paused_track_from_selected_synced_lyric(self):
        resumed = []
        frame = type(
            "Frame",
            (),
            {
                "current_track_is_paused": lambda self, track_id: True,
                "resume_from_lyric": (
                    lambda self, track_id, position_ms: resumed.append(
                        (track_id, position_ms)
                    )
                ),
            },
        )()
        text = type(
            "Text",
            (),
            {"GetInsertionPoint": lambda self: 12},
        )()
        dialog = type(
            "Dialog",
            (),
            {
                "frame": frame,
                "item": object(),
                "track_id": "track",
                "synced_lines": [
                    (1_000, "First"),
                    (5_000, "Second"),
                ],
                "synced_line_positions": [0, 10],
                "text": text,
            },
        )()

        LyricsDialog.on_text_key(dialog, self.Event(ui.wx.WXK_SPACE))

        self.assertEqual(resumed, [("track", 5_000)])

    def test_space_starts_unplayed_track_from_selected_lyric(self):
        started = []
        item = object()
        frame = type(
            "Frame",
            (),
            {
                "current_track_is_paused": lambda self, track_id: False,
                "play_from_lyric": (
                    lambda self, value, position_ms: started.append(
                        (value, position_ms)
                    )
                ),
            },
        )()
        text = type(
            "Text",
            (),
            {"GetInsertionPoint": lambda self: 12},
        )()
        dialog = type(
            "Dialog",
            (),
            {
                "frame": frame,
                "item": item,
                "track_id": "track",
                "synced_lines": [
                    (1_000, "First"),
                    (5_000, "Second"),
                ],
                "synced_line_positions": [0, 10],
                "text": text,
            },
        )()

        LyricsDialog.on_text_key(dialog, self.Event(ui.wx.WXK_SPACE))

        self.assertEqual(started, [(item, 5_000)])

    def test_space_reports_when_synced_lyrics_are_unavailable(self):
        messages = []
        frame = type(
            "Frame",
            (),
            {"say": lambda self, message: messages.append(message)},
        )()
        dialog = type(
            "Dialog",
            (),
            {"frame": frame, "synced_lines": []},
        )()

        LyricsDialog.on_text_key(dialog, self.Event(ui.wx.WXK_SPACE))

        self.assertEqual(
            messages,
            ["Synced lyrics are unavailable for this song."],
        )

    def test_control_down_moves_to_and_plays_next_synced_lyric(self):
        started = []
        moved = []
        item = object()
        frame = type(
            "Frame",
            (),
            {
                "current_track_is_paused": lambda self, track_id: False,
                "play_from_lyric": (
                    lambda self, value, position_ms: started.append(
                        (value, position_ms)
                    )
                ),
            },
        )()
        text = type(
            "Text",
            (),
            {
                "GetInsertionPoint": lambda self: 2,
                "SetInsertionPoint": lambda self, position: moved.append(
                    ("caret", position)
                ),
                "ShowPosition": lambda self, position: moved.append(
                    ("show", position)
                ),
            },
        )()
        dialog = type(
            "Dialog",
            (),
            {
                "frame": frame,
                "item": item,
                "track_id": "track",
                "synced_lines": [(1_000, "First"), (5_000, "Second")],
                "synced_line_positions": [0, 10],
                "text": text,
            },
        )()

        LyricsDialog.on_text_key(
            dialog,
            self.Event(ui.wx.WXK_DOWN, control=True),
        )

        self.assertEqual(moved, [("caret", 10), ("show", 10)])
        self.assertEqual(started, [(item, 5_000)])

    def test_control_up_moves_to_and_plays_previous_synced_lyric(self):
        started = []
        moved = []
        item = object()
        frame = type(
            "Frame",
            (),
            {
                "current_track_is_paused": lambda self, track_id: False,
                "play_from_lyric": (
                    lambda self, value, position_ms: started.append(
                        (value, position_ms)
                    )
                ),
            },
        )()
        text = type(
            "Text",
            (),
            {
                "GetInsertionPoint": lambda self: 12,
                "SetInsertionPoint": lambda self, position: moved.append(
                    ("caret", position)
                ),
                "ShowPosition": lambda self, position: moved.append(
                    ("show", position)
                ),
            },
        )()
        dialog = type(
            "Dialog",
            (),
            {
                "frame": frame,
                "item": item,
                "track_id": "track",
                "synced_lines": [(1_000, "First"), (5_000, "Second")],
                "synced_line_positions": [0, 10],
                "text": text,
            },
        )()

        LyricsDialog.on_text_key(
            dialog,
            self.Event(ui.wx.WXK_UP, control=True),
        )

        self.assertEqual(moved, [("caret", 0), ("show", 0)])
        self.assertEqual(started, [(item, 1_000)])

    def test_space_restarts_playing_track_from_selected_lyric(self):
        started = []
        item = object()
        frame = type(
            "Frame",
            (),
            {
                "current_track_is_paused": lambda self, track_id: False,
                "play_from_lyric": (
                    lambda self, value, position_ms: started.append(
                        (value, position_ms)
                    )
                ),
            },
        )()
        text = type(
            "Text",
            (),
            {"GetInsertionPoint": lambda self: 12},
        )()
        dialog = type(
            "Dialog",
            (),
            {
                "frame": frame,
                "item": item,
                "track_id": "track",
                "synced_lines": [
                    (1_000, "First"),
                    (5_000, "Second"),
                ],
                "synced_line_positions": [0, 10],
                "text": text,
            },
        )()

        LyricsDialog.on_text_key(dialog, self.Event(ui.wx.WXK_SPACE))

        self.assertEqual(started, [(item, 5_000)])

    def test_bare_space_is_left_available_for_checkbox_toggle(self):
        checkbox_type = type("Checkbox", (), {})
        checkbox = checkbox_type()
        event = self.Event(ui.wx.WXK_SPACE, event_object=checkbox)

        with patch("blindspot.ui.wx.CheckBox", checkbox_type):
            LyricsDialog.on_dialog_key(type("Dialog", (), {})(), event)

        self.assertTrue(event.skipped)

    def test_dialog_routes_space_when_text_has_internal_native_focus(self):
        started = []
        item = object()
        frame = type(
            "Frame",
            (),
            {
                "current_track_is_paused": lambda self, track_id: False,
                "play_from_lyric": (
                    lambda self, value, position_ms: started.append(
                        (value, position_ms)
                    )
                ),
            },
        )()
        text = type(
            "Text",
            (),
            {"GetInsertionPoint": lambda self: 12},
        )()
        dialog = type(
            "Dialog",
            (),
            {
                "frame": frame,
                "item": item,
                "track_id": "track",
                "synced_lines": [(1_000, "First"), (5_000, "Second")],
                "synced_line_positions": [0, 10],
                "text": text,
            },
        )()

        LyricsDialog.on_dialog_key(
            dialog,
            self.Event(ui.wx.WXK_SPACE, event_object=text),
        )

        self.assertEqual(started, [(item, 5_000)])

    def test_angle_brackets_adjust_lyrics_by_half_a_second(self):
        adjustments = []
        dialog = type(
            "Dialog",
            (),
            {
                "frame": self.Frame(),
                "adjust_lyric_timing": lambda self, amount: adjustments.append(
                    amount
                ),
            },
        )()

        with patch("blindspot.ui.sys.platform", "win32"):
            LyricsDialog.on_text_key(
                dialog,
                self.Event(ord(","), shift=True, control=True),
            )
            LyricsDialog.on_text_key(
                dialog,
                self.Event(ord("."), shift=True, control=True),
            )

        self.assertEqual(adjustments, [500, -500])

    def test_alt_f4_is_not_intercepted_by_lyrics_transport(self):
        frame = self.Frame()
        dialog = type(
            "Dialog",
            (),
            {"frame": frame, "item": object()},
        )()
        event = self.Event(343, alt=True)

        with patch("blindspot.ui.sys.platform", "win32"):
            LyricsDialog.on_dialog_key(dialog, event)

        self.assertTrue(event.skipped)
        self.assertEqual(frame.commands, [])

    def test_alt_f4_is_not_intercepted_by_main_transport(self):
        event = self.Event(343, alt=True)

        with (
            patch("blindspot.ui.sys.platform", "win32"),
            patch("blindspot.ui.wx.Window.FindFocus", return_value=None),
        ):
            MainFrame.on_global_key(object(), event)

        self.assertTrue(event.skipped)

    def test_bare_space_is_consumed_in_item_lists(self):
        event = self.Event(32)
        focused = object()

        with (
            patch("blindspot.ui.wx.WXK_SPACE", 32),
            patch("blindspot.ui.ItemList", type(focused)),
            patch("blindspot.ui.wx.Window.FindFocus", return_value=focused),
        ):
            MainFrame.on_global_key(object(), event)

        self.assertFalse(event.skipped)

if __name__ == "__main__":
    unittest.main()
