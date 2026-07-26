import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from blindspot import ui
from blindspot.ui import (
    LyricsDialog,
    MainFrame,
    PlaylistsPanel,
    PodcastsPanel,
    SearchPanel,
    album_track_label,
    menu_function_shortcut,
    native_text_positions,
    playback_state_for_resume,
    radio_box_ancestor,
    resume_mode_from_settings,
)


class PlaybackMemorySettingsTests(unittest.TestCase):
    def test_radio_button_focus_resolves_to_parent_radio_box(self):
        class RadioBox:
            def GetParent(self):
                return None

        radio_box = RadioBox()
        radio_button = type(
            "RadioButton",
            (),
            {"GetParent": lambda self: radio_box},
        )()

        with patch("blindspot.ui.wx.RadioBox", RadioBox):
            self.assertIs(radio_box_ancestor(radio_button), radio_box)

    def test_tab_loop_uses_parent_radio_box_for_native_child_focus(self):
        focused_targets = []

        class Control:
            def SetFocus(self):
                focused_targets.append(self)

            def GetParent(self):
                return None

        class RadioBox(Control):
            pass

        notebook = Control()
        notebook.GetSelection = lambda: 0
        query = Control()
        categories = RadioBox()
        button = Control()
        results = Control()
        radio_button = type(
            "RadioButton",
            (),
            {"GetParent": lambda self: categories},
        )()
        frame = type(
            "Frame",
            (),
            {
                "notebook": notebook,
                "search": type(
                    "Search",
                    (),
                    {
                        "query": query,
                        "categories": categories,
                        "search_button": button,
                        "results": results,
                    },
                )(),
            },
        )()

        with (
            patch("blindspot.ui.wx.RadioBox", RadioBox),
            patch(
                "blindspot.ui.wx.Window.FindFocus",
                return_value=radio_button,
            ),
            patch("blindspot.ui.item_list_ancestor", return_value=None),
        ):
            MainFrame.move_focus(frame, backward=False)
            MainFrame.move_focus(frame, backward=True)

        self.assertEqual(focused_targets, [button, query])

    def test_mac_function_keys_are_not_menu_accelerators(self):
        self.assertEqual(menu_function_shortcut("F8", "darwin"), "")
        self.assertEqual(menu_function_shortcut("F8", "win32"), "\tF8")
        self.assertEqual(menu_function_shortcut("RAWCTRL+Y", "darwin"), "")
        self.assertEqual(menu_function_shortcut("Ctrl+Y", "win32"), "\tCtrl+Y")

    def test_control_y_still_routes_through_global_key_handler(self):
        shown = []
        frame = type(
            "Frame",
            (),
            {"show_lyrics": lambda self: shown.append(True)},
        )()
        event = type(
            "Event",
            (),
            {
                "GetKeyCode": lambda self: ord("Y"),
                "AltDown": lambda self: False,
                "ShiftDown": lambda self: False,
            },
        )()

        with (
            patch("blindspot.ui.physical_control_down", return_value=True),
            patch("blindspot.ui.wx.Window.FindFocus", return_value=None),
        ):
            MainFrame.on_global_key(frame, event)

        self.assertEqual(shown, [True])

    def test_mac_physical_control_uses_raw_modifier_bit(self):
        raw_event = type(
            "Event",
            (),
            {"GetModifiers": lambda self: ui.wx.MOD_RAW_CONTROL},
        )()
        command_event = type(
            "Event",
            (),
            {"GetModifiers": lambda self: ui.wx.MOD_CONTROL},
        )()

        with (
            patch("blindspot.ui.sys.platform", "darwin"),
            patch("blindspot.ui.wx.MOD_RAW_CONTROL", 2),
            patch("blindspot.ui.wx.MOD_CONTROL", 1),
            patch("blindspot.ui.wx.GetKeyState", return_value=False),
        ):
            self.assertTrue(ui.physical_control_down(raw_event))
            self.assertFalse(ui.physical_control_down(command_event))

    def test_windows_lyric_positions_account_for_crlf(self):
        positions = [0, 4, 8]

        self.assertEqual(
            native_text_positions("one\ntwo\nthree", positions, "win32"),
            [0, 5, 10],
        )
        self.assertEqual(
            native_text_positions("one\ntwo\nthree", positions, "darwin"),
            positions,
        )

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


class CollectionFocusTests(unittest.TestCase):
    def test_completed_load_does_not_move_focus_into_list(self):
        focused = []
        item_list = type(
            "Items",
            (),
            {
                "set_items": lambda self, items: None,
                "SetFocus": lambda self: focused.append(True),
            },
        )()
        status = type(
            "Status",
            (),
            {"SetLabel": lambda self, label: None},
        )()
        frame = type(
            "Frame",
            (),
            {"update_title_for_page": lambda self, page, title: None},
        )()
        panel = type(
            "Panel",
            (),
            {
                "title": "Recently Played",
                "items": item_list,
                "status": status,
                "frame": frame,
            },
        )()

        ui.CollectionPanel.show_items(
            panel,
            [ui.SpotifyItem("track", ui.ItemKind.TRACK, "Song")],
        )

        self.assertEqual(focused, [])

class GlobalShortcutRegistrationTests(unittest.TestCase):
    def test_preferences_open_logs_button_uses_callback(self):
        opened = []
        preferences = type(
            "Preferences",
            (),
            {"open_logs_folder_callback": lambda self: opened.append(True)},
        )()

        ui.PreferencesDialog.on_open_logs_folder(preferences, None)

        self.assertEqual(opened, [True])

    def test_open_logs_folder_uses_running_store_location(self):
        errors = []
        root = Path("actual-data-location")
        frame = type(
            "Frame",
            (),
            {
                "store": type("Store", (), {"root": root})(),
                "show_error": lambda self, message: errors.append(message),
            },
        )()

        with patch(
            "blindspot.ui.wx.LaunchDefaultApplication",
            return_value=True,
        ) as launch:
            MainFrame.open_logs_folder(frame)

        launch.assert_called_once_with(str(root.resolve()))
        self.assertEqual(errors, [])

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
    def test_opening_recently_played_tab_waits_for_list_focus(self):
        refreshed = []
        titles = []
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
                "SetTitle": lambda self, title: titles.append(title),
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

        MainFrame.on_tab_changed(frame, event)

        self.assertEqual(refreshed, [])
        self.assertEqual(titles, ["BlindSpot"])

    def test_focusing_tab_bar_uses_static_window_title(self):
        titles = []
        focused = []
        notebook = type(
            "Notebook",
            (),
            {"SetFocus": lambda self: focused.append(True)},
        )()
        frame = type(
            "Frame",
            (),
            {
                "notebook": notebook,
                "SetTitle": lambda self, title: titles.append(title),
            },
        )()

        MainFrame.focus_tab_bar(frame)

        self.assertEqual(titles, ["BlindSpot"])
        self.assertEqual(focused, [True])

    def test_save_to_library_announces_liked(self):
        spoken = []
        synced = []
        track = ui.SpotifyItem("track", ui.ItemKind.TRACK, "Track")
        frame = type(
            "Frame",
            (),
            {
                "sync_liked_item": (
                    lambda self, item, saved: synced.append((item, saved))
                ),
                "say": lambda self, message: spoken.append(message),
            },
        )()

        MainFrame.finish_save_to_library(frame, track)

        self.assertEqual(synced, [(track, True)])
        self.assertEqual(spoken, [ui.msg.LIKED])

    def test_like_item_uses_selected_track_without_playback(self):
        toggled = []
        track = ui.SpotifyItem(
            "track",
            ui.ItemKind.TRACK,
            "Track",
            uri="spotify:track:track",
        )
        spotify = type(
            "Spotify",
            (),
            {
                "toggle_saved": (
                    lambda self, item: toggled.append(item) or True
                )
            },
        )()
        frame = type(
            "Frame",
            (),
            {
                "spotify": spotify,
                "run_task": (
                    lambda self, message, worker, success: success(worker())
                ),
                "finish_toggle_like": lambda self, item, saved: None,
                "say": lambda self, message: None,
            },
        )()

        MainFrame.toggle_like_item(frame, track)

        self.assertEqual(toggled, [track])

    def test_native_list_insert_adapter_adds_row_at_requested_position(self):
        inserted = []
        control = type(
            "Control",
            (),
            {
                "InsertItem": (
                    lambda self, index, label: inserted.append((index, label))
                )
            },
        )()

        with patch("blindspot.ui.ITEM_LIST_USES_DATAVIEW", False):
            ui.ItemList.Insert(control, "Track", 0)

        self.assertEqual(inserted, [(0, "Track")])

    def test_macos_dataview_adapters_manage_rows_and_selection(self):
        calls = []
        row_item = object()
        control = type(
            "Control",
            (),
            {
                "items": [object(), object()],
                "UnselectAll": lambda self: calls.append("unselect"),
                "RowToItem": lambda self, row: row_item,
                "SelectRow": lambda self, row: calls.append(("select", row)),
                "SetCurrentItem": (
                    lambda self, item: calls.append(("current", item))
                ),
                "EnsureVisible": (
                    lambda self, item: calls.append(("visible", item))
                ),
                "AppendItem": (
                    lambda self, values: calls.append(("append", values))
                ),
                "InsertItem": (
                    lambda self, row, values: calls.append(
                        ("insert", row, values)
                    )
                ),
                "SetValue": (
                    lambda self, value, row, column: calls.append(
                        ("set", value, row, column)
                    )
                ),
            },
        )()

        with patch("blindspot.ui.ITEM_LIST_USES_DATAVIEW", True):
            ui.ItemList.SetSelection(control, 1)
            ui.ItemList.Append(control, "Last")
            ui.ItemList.Insert(control, "First", 0)
            ui.ItemList.SetString(control, 1, "Renamed")

        self.assertEqual(
            calls,
            [
                "unselect",
                ("select", 1),
                ("current", row_item),
                ("visible", row_item),
                ("append", ["Last"]),
                ("insert", 0, ["First"]),
                ("set", "Renamed", 1, 0),
            ],
        )

    def test_refresh_current_view_refreshes_selected_page(self):
        refreshed = []
        page = type(
            "Page",
            (),
            {"refresh": lambda self: refreshed.append(True)},
        )()
        notebook = type(
            "Notebook",
            (),
            {"GetCurrentPage": lambda self: page},
        )()
        frame = type("Frame", (), {"notebook": notebook})()

        MainFrame.refresh_current_view(frame)

        self.assertEqual(refreshed, [True])

    def test_control_enter_action_opens_selected_tracks_album(self):
        opened = []
        track = ui.SpotifyItem("track", ui.ItemKind.TRACK, "Track")
        frame = type(
            "Frame",
            (),
            {
                "open_album_for_track": (
                    lambda self, item: opened.append(item)
                )
            },
        )()

        MainFrame.open_selected_track_album(frame, track)

        self.assertEqual(opened, [track])

    def test_search_list_handles_control_enter_before_plain_enter(self):
        opened = []
        played = []
        track = ui.SpotifyItem("track", ui.ItemKind.TRACK, "Track")
        frame = type(
            "Frame",
            (),
            {
                "focus_tab_bar": lambda self: None,
                "open_selected_track_album": (
                    lambda self, item: opened.append(item)
                ),
            },
        )()
        results = type(
            "Results",
            (),
            {"selected_item": lambda self: track},
        )()
        panel = type(
            "Panel",
            (),
            {
                "frame": frame,
                "results": results,
                "on_open": lambda self: played.append(True),
            },
        )()
        event = type(
            "Event",
            (),
            {
                "GetKeyCode": lambda self: ui.wx.WXK_RETURN,
                "ControlDown": lambda self: True,
                "RawControlDown": lambda self: True,
                "ShiftDown": lambda self: False,
            },
        )()

        SearchPanel.on_list_key(panel, event)

        self.assertEqual(opened, [track])
        self.assertEqual(played, [])

    def test_item_list_forwards_keyboard_to_global_dispatcher(self):
        forwarded = []
        frame = type(
            "Frame",
            (),
            {
                "on_global_key": (
                    lambda self, event: forwarded.append(event)
                )
            },
        )()
        panel = type("Panel", (), {"frame": frame})()
        item_list = type(
            "List",
            (),
            {
                "GetParent": lambda self: panel,
            },
        )()
        event = object()

        ui.ItemList.on_char_hook(item_list, event)

        self.assertEqual(forwarded, [event])

    def test_selected_actions_routes_to_current_tab(self):
        called = []
        panels = [
            type(
                "Panel",
                (),
                {
                    "on_context_menu": (
                        lambda self, index=index: called.append(index)
                    )
                },
            )()
            for index in range(8)
        ]
        notebook = type(
            "Notebook",
            (),
            {"GetSelection": lambda self: 6},
        )()
        frame = type(
            "Frame",
            (),
            dict(
                notebook=notebook,
                **dict(
                    zip(
                        (
                            "search",
                            "liked",
                            "queue",
                            "playlists",
                            "recently_played",
                            "bookmarks",
                            "audiobooks",
                            "podcasts",
                        ),
                        panels,
                    )
                ),
            ),
        )()

        MainFrame.show_selected_actions(frame)

        self.assertEqual(called, [6])


class SearchContextMenuTests(unittest.TestCase):
    def test_back_from_album_opened_in_playlist_returns_to_playlist(self):
        initial = ui.ViewState("Search results", [])
        album_state = ui.ViewState(
            "Album",
            [],
            parent_kind=ui.ItemKind.ALBUM,
        )
        history = ui.NavigationHistory(initial)
        history.push(album_state)
        focused = []
        selections = []
        items = type(
            "Items",
            (),
            {"SetFocus": lambda self: focused.append(True)},
        )()
        panel = type("Panel", (), {"items": items})()
        rendered = []
        search = type(
            "Search",
            (),
            {
                "history": history,
                "render": (
                    lambda self, state, focus: rendered.append(
                        (state, focus)
                    )
                ),
            },
        )()
        frame = type(
            "Frame",
            (),
            {
                "open_album_return_page": 3,
                "open_album_return_state": album_state,
                "discard_transient_open_album": (
                    MainFrame.discard_transient_open_album
                ),
                "notebook": type(
                    "Notebook",
                    (),
                    {
                        "SetSelection": (
                            lambda self, page: selections.append(page)
                        )
                    },
                )(),
                "search": search,
                "liked": panel,
                "queue": panel,
                "playlists": panel,
                "recently_played": panel,
                "bookmarks": panel,
                "audiobooks": panel,
                "podcasts": panel,
            },
        )()

        self.assertTrue(
            MainFrame.return_from_open_album(frame, album_state)
        )
        self.assertIs(history.current, initial)
        self.assertEqual(selections, [3])
        self.assertEqual(focused, [True])
        self.assertEqual(rendered, [(initial, False)])

    def test_control_one_opens_search_and_focuses_query(self):
        selections = []
        focused = []
        frame = type(
            "Frame",
            (),
            {
                "notebook": type(
                    "Notebook",
                    (),
                    {
                        "SetSelection": (
                            lambda self, page: selections.append(page)
                        )
                    },
                )(),
                "search": type(
                    "Search",
                    (),
                    {"focus_query": lambda self: focused.append(True)},
                )(),
                "discard_transient_open_album": lambda self: False,
            },
        )()
        event = type(
            "Event",
            (),
            {
                "GetKeyCode": lambda self: ord("1"),
                "AltDown": lambda self: False,
                "ShiftDown": lambda self: False,
            },
        )()

        with (
            patch("blindspot.ui.physical_control_down", return_value=True),
            patch("blindspot.ui.wx.Window.FindFocus", return_value=None),
        ):
            MainFrame.on_global_key(frame, event)

        self.assertEqual(selections, [0])
        self.assertEqual(focused, [True])

    def test_search_back_delegates_cross_page_album_return(self):
        state = ui.ViewState("Album", [])
        returned = []
        panel = type(
            "Search",
            (),
            {
                "history": ui.NavigationHistory(state),
                "frame": type(
                    "Frame",
                    (),
                    {
                        "return_from_open_album": (
                            lambda self, current: returned.append(current)
                            or True
                        )
                    },
                )(),
            },
        )()

        self.assertTrue(SearchPanel.go_back(panel))
        self.assertEqual(returned, [state])

    def test_playlist_page_menu_contains_information_command(self):
        labels = []

        class Menu:
            def Append(self, item_id, label):
                labels.append(label)
                return object()

            def AppendSeparator(self):
                pass

            def Bind(self, event, callback, item):
                pass

            def Destroy(self):
                pass

        playlist = ui.SpotifyItem(
            "playlist",
            ui.ItemKind.PLAYLIST,
            "Playlist",
        )
        frame = type(
            "Frame",
            (),
            {
                "play": lambda self, item: None,
                "show_playlist_information": lambda self, item: None,
                "create_playlist": lambda self: None,
            },
        )()
        panel = type(
            "Playlists",
            (),
            {
                "frame": frame,
                "items": type(
                    "Items",
                    (),
                    {"PopupMenu": lambda self, menu: None},
                )(),
                "on_open": lambda self: None,
                "remove_playlist": lambda self, item: None,
            },
        )()

        with patch("blindspot.ui.wx.Menu", return_value=Menu()):
            PlaylistsPanel.popup_playlist_menu(panel, playlist)

        self.assertIn("Playlist &information...", labels)

    def test_f4_on_open_album_track_plays_in_album_context(self):
        track = ui.SpotifyItem(
            "track",
            ui.ItemKind.TRACK,
            "Track 1",
            uri="spotify:track:track",
        )
        played = []
        notebook = type(
            "Notebook",
            (),
            {"GetSelection": lambda self: 0},
        )()
        search = type(
            "Search",
            (),
            {
                "history": ui.NavigationHistory(
                    ui.ViewState(
                        "The Album",
                        [track],
                        parent_id="album",
                        parent_kind=ui.ItemKind.ALBUM,
                    )
                )
            },
        )()
        frame = type(
            "Frame",
            (),
            {
                "notebook": notebook,
                "search": search,
                "current_selected_item": lambda self: track,
                "play_in_context": (
                    lambda self, context, item: played.append(
                        (context, item)
                    )
                ),
            },
        )()

        MainFrame.play_selected(frame)

        self.assertEqual(played[0][0].uri, "spotify:album:album")
        self.assertEqual(played[0][1], track)

    def test_album_track_label_keeps_only_number_name_and_guest_artist(self):
        state = ui.ViewState(
            "Album",
            [],
            parent_kind=ui.ItemKind.ALBUM,
            parent_artist_names=("Main Artist",),
            parent_artist_ids=("main",),
        )
        track = ui.SpotifyItem(
            id="track",
            kind=ui.ItemKind.TRACK,
            name="The Song",
            artist="Main Artist, Guest Artist",
            album="Album",
            duration_ms=240_000,
            raw={
                "track_number": 3,
                "disc_number": 1,
                "artists": [
                    {"id": "main", "name": "Main Artist"},
                    {"id": "guest", "name": "Guest Artist"},
                ],
            },
        )

        self.assertEqual(
            album_track_label(track, 2, state, False),
            "3 The Song — featuring Guest Artist",
        )

    def test_multi_disc_album_label_includes_disc_number(self):
        state = ui.ViewState(
            "Album",
            [],
            parent_kind=ui.ItemKind.ALBUM,
            parent_artist_names=("Artist",),
        )
        track = ui.SpotifyItem(
            id="track",
            kind=ui.ItemKind.TRACK,
            name="Finale",
            raw={"track_number": 1, "disc_number": 2},
        )

        self.assertEqual(
            album_track_label(track, 0, state, True),
            "Disc 2 track 1 Finale",
        )

    def test_album_track_does_not_offer_to_open_current_album(self):
        calls = []
        track = ui.SpotifyItem(
            id="track",
            kind=ui.ItemKind.TRACK,
            name="Song",
        )
        frame = type(
            "Frame",
            (),
            {
                "popup_item_menu": (
                    lambda self, owner, item, **options: calls.append(options)
                )
            },
        )()
        results = type(
            "Results",
            (),
            {"selected_item": lambda self: track},
        )()
        panel = type(
            "Panel",
            (),
            {
                "frame": frame,
                "results": results,
                "history": ui.NavigationHistory(
                    ui.ViewState(
                        "Album",
                        [track],
                        parent_id="album",
                        parent_kind=ui.ItemKind.ALBUM,
                    )
                ),
                "on_open": lambda self: None,
            },
        )()

        SearchPanel.on_context_menu(panel)

        self.assertFalse(calls[0]["include_album_action"])


class SearchPaginationTests(unittest.TestCase):
    def test_more_results_replace_loader_and_append_to_current_search(self):
        first = ui.SpotifyItem("first", ui.ItemKind.TRACK, "First")
        second = ui.SpotifyItem("second", ui.ItemKind.TRACK, "Second")
        loader = ui.SpotifyItem(
            "__load_more__",
            ui.ItemKind.HEADING,
            "Load more results",
            raw={"load_more": True, "next_offset": 20},
        )
        next_loader = ui.SpotifyItem(
            "__load_more__",
            ui.ItemKind.HEADING,
            "Load more results",
            raw={"load_more": True, "next_offset": 40},
        )
        state = ui.ViewState(
            "Results",
            [first, loader],
            query="query",
            category="track",
        )
        spoken = []
        rendered = []
        panel = type(
            "Panel",
            (),
            {
                "history": ui.NavigationHistory(state),
                "frame": type(
                    "Frame",
                    (),
                    {"say": lambda self, message: spoken.append(message)},
                )(),
                "render": (
                    lambda self, value, focus: rendered.append((value, focus))
                ),
            },
        )()

        SearchPanel.append_search_results(panel, [second, next_loader])

        self.assertEqual(
            [item.id for item in state.items],
            ["first", "second", "__load_more__"],
        )
        self.assertEqual(state.selected, 1)
        self.assertEqual(spoken, [])
        self.assertTrue(rendered[0][1])

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


class PodcastSupportTests(unittest.TestCase):
    def test_saved_library_lists_shows_and_episodes_without_section_rows(self):
        rendered = []
        status_labels = []
        items = object()
        panel = type(
            "Panel",
            (),
            {
                "loading": True,
                "loaded_once": False,
                "history": ui.NavigationHistory(ui.ViewState("Podcasts", [])),
                "current_playlist": None,
                "items": items,
                "status": type(
                    "Status",
                    (),
                    {"SetLabel": lambda self, label: status_labels.append(label)},
                )(),
                "render": (
                    lambda self, state, *, focus: rendered.append(state)
                ),
            },
        )()
        show = ui.SpotifyItem("show", ui.ItemKind.SHOW, "Show")
        episode = ui.SpotifyItem(
            "episode",
            ui.ItemKind.EPISODE,
            "Episode",
        )

        with patch("blindspot.ui.wx.Window.FindFocus", return_value=items):
            PodcastsPanel.show_library(panel, [show], [episode])

        self.assertEqual(
            [item.name for item in rendered[0].items],
            ["Show", "Episode"],
        )
        self.assertEqual(
            status_labels,
            ["1 podcast and 1 saved episode."],
        )

    def test_saved_show_context_menu_offers_unsubscribe(self):
        calls = []
        show = ui.SpotifyItem(
            "show",
            ui.ItemKind.SHOW,
            "Show",
            uri="spotify:show:show",
        )
        panel = type(
            "Panel",
            (),
            {
                "items": type(
                    "Items",
                    (),
                    {"selected_item": lambda self: show},
                )(),
                "history": ui.NavigationHistory(
                    ui.ViewState("Podcasts", [show])
                ),
                "frame": type(
                    "Frame",
                    (),
                    {
                        "popup_item_menu": (
                            lambda self, owner, item, **options: calls.append(
                                options
                            )
                        )
                    },
                )(),
                "on_open": lambda self: None,
                "remove_saved_item": lambda self, item: None,
            },
        )()

        PodcastsPanel.on_context_menu(panel)

        self.assertEqual(calls[0]["remove_label"], "&Unsubscribe...")
        self.assertIsNotNone(calls[0]["remove_callback"])

    def test_unsubscribe_removes_show_and_refreshes_library(self):
        removed = []
        spoken = []
        refreshed = []
        show = ui.SpotifyItem(
            "show",
            ui.ItemKind.SHOW,
            "Show",
            uri="spotify:show:show",
        )
        spotify = type(
            "Spotify",
            (),
            {"remove": lambda self, item: removed.append(item)},
        )()
        frame = type(
            "Frame",
            (),
            {
                "spotify": spotify,
                "run_task": (
                    lambda self, message, worker, success: success(worker())
                ),
                "say": lambda self, message: spoken.append(message),
            },
        )()
        panel = type(
            "Panel",
            (),
            {
                "frame": frame,
                "refresh": lambda self: refreshed.append(True),
                "finish_remove_saved_item": (
                    lambda self: PodcastsPanel.finish_remove_saved_item(self)
                ),
            },
        )()

        with patch("blindspot.ui.wx.MessageBox", return_value=ui.wx.YES):
            PodcastsPanel.remove_saved_item(panel, show)

        self.assertEqual(removed, [show])
        self.assertEqual(spoken, [ui.msg.REMOVED_FROM_LIBRARY])
        self.assertEqual(refreshed, [True])

    def test_delete_unsubscribes_selected_show_from_library(self):
        removed = []
        show = ui.SpotifyItem("show", ui.ItemKind.SHOW, "Show")
        panel = type(
            "Panel",
            (),
            {
                "history": ui.NavigationHistory(
                    ui.ViewState("Podcasts", [show])
                ),
                "items": type(
                    "Items",
                    (),
                    {"selected_item": lambda self: show},
                )(),
                "remove_saved_item": (
                    lambda self, item: removed.append(item)
                ),
            },
        )()
        event = type(
            "Event",
            (),
            {"GetKeyCode": lambda self: ui.wx.WXK_DELETE},
        )()

        PodcastsPanel.on_key(panel, event)

        self.assertEqual(removed, [show])

    def test_saved_episode_uses_resume_aware_playback(self):
        played = []
        episode = ui.SpotifyItem(
            "episode",
            ui.ItemKind.EPISODE,
            "Episode",
            raw={"resume_position_ms": 90_000},
        )
        panel = type(
            "Panel",
            (),
            {
                "items": type(
                    "Items",
                    (),
                    {"selected_item": lambda self: episode},
                )(),
                "frame": type(
                    "Frame",
                    (),
                    {
                        "play_playable_item": (
                            lambda self, item: played.append(item)
                        )
                    },
                )(),
            },
        )()

        PodcastsPanel.on_open(panel)

        self.assertEqual(played, [episode])


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
                "synced_line_positions": [0, 15],
                "text": text,
            },
        )()
        return dialog, announcer, text

    def test_windows_advances_one_second_before_next_timestamp(self):
        dialog, announcer, text = self.make_dialog(position_ms=1_000)

        with patch("blindspot.ui.sys.platform", "win32"):
            LyricsDialog.update_braille_line(dialog)

        self.assertEqual(text.insertion_points, [15])
        self.assertEqual(text.shown_positions, [15])
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

    def test_macos_follows_lyrics_by_moving_caret_without_flash_message(self):
        dialog, announcer, text = self.make_dialog(position_ms=1_000)

        with patch("blindspot.ui.sys.platform", "darwin"):
            LyricsDialog.update_braille_line(dialog)
            LyricsDialog.update_braille_line(dialog)

        self.assertEqual(text.insertion_points, [15])
        self.assertEqual(text.shown_positions, [15])
        self.assertEqual(announcer.output_messages, [])

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


class StandaloneTrackNavigationTests(unittest.TestCase):
    def test_legacy_standalone_playback_memory_restores_marker(self):
        state = {
            "progress_ms": 0,
            "context_uri": "",
            "item": {
                "id": "track",
                "name": "Track",
                "type": "track",
                "uri": "spotify:track:track",
            },
        }
        store = type(
            "Store",
            (),
            {"read": lambda self, name, default=None: state},
        )()
        frame = type(
            "Frame",
            (),
            {
                "resume_mode": "track_and_position",
                "store": store,
                "item_from_player_state": staticmethod(
                    MainFrame.item_from_player_state
                ),
                "set_view_title": lambda self, title: None,
            },
        )()

        MainFrame.load_pending_resume(frame)

        self.assertEqual(frame.standalone_player_item_id, "track")
        self.assertEqual(frame.pending_resume[0].id, "track")

    def test_previous_uses_spotify_for_standalone_item(self):
        sent = []
        frame = type(
            "Frame",
            (),
            {
                "current_player_item": None,
                "player_device_id": lambda self: "device",
                "using_local_player": lambda self: False,
                "spotify": type(
                    "Spotify",
                    (),
                    {
                        "previous_track": lambda self, device_id: sent.append(
                            device_id
                        )
                    },
                )(),
                "run_task": lambda self, message, work, done: (
                    done(work())
                ),
            },
        )()

        MainFrame.previous_track(frame)

        self.assertEqual(sent, ["device"])

    def test_previous_always_restarts_current_track(self):
        item = ui.SpotifyItem("track", ui.ItemKind.TRACK, "Track")
        seeks = []
        previous = []
        scheduled = []
        player = type(
            "Player",
            (),
            {"seek_to": lambda self, position: seeks.append(position)},
        )()
        frame = type(
            "Frame",
            (),
            {
                "current_player_item": item,
                "pending_previous_restart": None,
                "player": player,
                "player_device_id": lambda self: "device",
                "using_local_player": lambda self: True,
                "restart_current_track": MainFrame.restart_current_track,
                "spotify": type(
                    "Spotify",
                    (),
                    {
                        "previous_track": (
                            lambda self, device_id: previous.append(device_id)
                        )
                    },
                )(),
            },
        )()

        timer = type("Timer", (), {})()

        def schedule(delay, callback, *args):
            scheduled.append((delay, callback, args))
            return timer

        with patch("blindspot.ui.wx.CallLater", side_effect=schedule):
            MainFrame.previous_track(frame)

        self.assertEqual(seeks, [])
        self.assertEqual(scheduled[0][0], 500)
        scheduled[0][1](*scheduled[0][2])
        self.assertEqual(seeks, [0])
        self.assertEqual(previous, [])

    def test_previous_restarts_near_start(self):
        item = ui.SpotifyItem("track", ui.ItemKind.TRACK, "Track")
        seeks = []
        scheduled = []
        frame = type(
            "Frame",
            (),
            {
                "current_player_item": item,
                "pending_previous_restart": None,
                "player_device_id": lambda self: "device",
                "using_local_player": lambda self: False,
                "restart_current_track": MainFrame.restart_current_track,
                "spotify": type(
                    "Spotify",
                    (),
                    {
                        "seek_to": (
                            lambda self, position, device_id: seeks.append(
                                (position, device_id)
                            )
                        )
                    },
                )(),
                "run_task": lambda self, message, work, done: done(work()),
            },
        )()

        timer = type("Timer", (), {})()

        def schedule(delay, callback, *args):
            scheduled.append((delay, callback, args))
            return timer

        with patch("blindspot.ui.wx.CallLater", side_effect=schedule):
            MainFrame.previous_track(frame)

        scheduled[0][1](*scheduled[0][2])
        self.assertEqual(seeks, [(0, "device")])

    def test_second_previous_within_half_second_moves_back(self):
        item = ui.SpotifyItem("track", ui.ItemKind.TRACK, "Track")
        previous = []
        stopped = []
        timer = type(
            "Timer",
            (),
            {
                "IsRunning": lambda self: True,
                "Stop": lambda self: stopped.append(True),
            },
        )()
        frame = type(
            "Frame",
            (),
            {
                "current_player_item": item,
                "pending_previous_restart": timer,
                "player_device_id": lambda self: "device",
                "using_local_player": lambda self: False,
                "spotify": type(
                    "Spotify",
                    (),
                    {
                        "previous_track": (
                            lambda self, device_id: previous.append(device_id)
                        )
                    },
                )(),
                "run_task": lambda self, message, work, done: done(work()),
            },
        )()

        MainFrame.previous_track(frame)

        self.assertEqual(previous, ["device"])
        self.assertEqual(stopped, [True])
        self.assertIsNone(frame.pending_previous_restart)

    def test_next_always_uses_spotify(self):
        sent = []
        frame = type(
            "Frame",
            (),
            {
                "player_device_id": lambda self: "device",
                "current_player_item": None,
                "send_next_track": (
                    lambda self, device_id: sent.append(device_id)
                ),
            },
        )()

        MainFrame.next_track(frame)

        self.assertEqual(sent, ["device"])

    def test_lyric_start_does_not_seek_before_track_is_loaded(self):
        item = ui.SpotifyItem("track", ui.ItemKind.TRACK, "Track")
        calls = []
        spotify = type(
            "Spotify",
            (),
            {
                "play_at": (
                    lambda self, value, position, device: calls.append(
                        ("play", position, device)
                    )
                ),
            },
        )()
        frame = type("Frame", (), {"spotify": spotify})()

        MainFrame.play_at_with_entitlement_message(
            frame,
            item,
            42_000,
            "device",
        )

        self.assertEqual(calls, [("play", 42_000, "device")])

    def test_remembered_item_is_not_treated_as_loaded_player_item(self):
        item = ui.SpotifyItem("track", ui.ItemKind.TRACK, "Track")
        calls = []
        spotify = type(
            "Spotify",
            (),
            {
                "play_at": (
                    lambda self, value, position, device: calls.append("play")
                ),
                "seek_to": (
                    lambda self, position, device: calls.append("seek")
                ),
            },
        )()
        frame = type(
            "Frame",
            (),
            {
                "spotify": spotify,
                "current_player_item": item,
                "current_player_state": {},
                "remote_device_id": "device",
                "suppress_track_announcement_id": None,
                "lyric_start_item_id": None,
                "play_at_with_entitlement_message": (
                    MainFrame.play_at_with_entitlement_message
                ),
                "finish_lyric_start": lambda self, value: None,
                "cancel_lyric_start": lambda self: None,
                "run_task": lambda self, message, work, done, **options: (
                    done(work())
                ),
            },
        )()

        MainFrame.play_from_lyric(frame, item, 42_000)

        self.assertEqual(calls, ["play"])
        self.assertEqual(frame.pending_lyric_seek, ("track", 42_000))

    def test_remembered_item_is_not_treated_as_live_paused_item(self):
        item = ui.SpotifyItem("track", ui.ItemKind.TRACK, "Track")
        frame = type(
            "Frame",
            (),
            {
                "current_player_item": item,
                "current_player_state": {},
            },
        )()

        self.assertFalse(MainFrame.current_track_is_paused(frame, "track"))

    def test_lyric_position_is_applied_after_track_is_loaded(self):
        item = ui.SpotifyItem("track", ui.ItemKind.TRACK, "Track")
        seeks = []
        spotify = type(
            "Spotify",
            (),
            {
                "seek_to": lambda self, position, device: seeks.append(
                    (position, device)
                )
            },
        )()
        frame = type(
            "Frame",
            (),
            {
                "pending_lyric_seek": ("track", 42_000),
                "lyric_start_item_id": "track",
                "current_player_item": item,
                "current_player_state": {"progress_ms": 0},
                "spotify": spotify,
                "player_device_id": lambda self: "device",
                "run_task": lambda self, message, work, done: done(work()),
            },
        )()

        MainFrame.apply_pending_lyric_seek(frame)

        self.assertEqual(seeks, [(42_000, "device")])
        self.assertIsNone(frame.pending_lyric_seek)
        self.assertIsNone(frame.lyric_start_item_id)

    def test_matching_lyric_start_position_is_not_sought_again(self):
        item = ui.SpotifyItem("track", ui.ItemKind.TRACK, "Track")
        seeks = []
        frame = type(
            "Frame",
            (),
            {
                "pending_lyric_seek": ("track", 42_000),
                "lyric_start_item_id": "track",
                "current_player_item": item,
                "current_player_state": {"progress_ms": 42_250},
                "player_device_id": lambda self: seeks.append("device"),
            },
        )()

        MainFrame.apply_pending_lyric_seek(frame)

        self.assertEqual(seeks, [])

    def test_empty_player_error_is_hidden_during_first_lyric_start(self):
        messages = []
        frame = type(
            "Frame",
            (),
            {
                "lyric_start_item_id": "track",
                "say": lambda self, message: messages.append(message),
            },
        )()

        MainFrame.on_player_error(frame, ui.msg.NO_TRACKS)

        self.assertEqual(messages, [])


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
                "pending_resume": None,
                "current_player_item": first,
                "deferred_queue_items": [],
                "queue_should_be_deferred": (
                    MainFrame.queue_should_be_deferred
                ),
                "spotify": type(
                    "Spotify",
                    (),
                    {
                        "add_to_queue": (
                            lambda self, item, device_id: queued.append(
                                (item, device_id)
                            )
                        )
                    },
                )(),
                "player_device_id": lambda self: "device",
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

        self.assertEqual(queued, [(first, "device"), (second, "device")])
        self.assertEqual(messages, [2])

    def test_queue_is_deferred_without_resuming_remembered_track(self):
        track = ui.SpotifyItem(
            "queued",
            ui.ItemKind.TRACK,
            "Queued song",
            uri="spotify:track:queued",
        )
        remembered = ui.SpotifyItem(
            "remembered",
            ui.ItemKind.TRACK,
            "Remembered song",
            uri="spotify:track:remembered",
        )
        queued_remotely = []
        messages = []
        item_list = type(
            "List",
            (),
            {
                "marked_items": lambda self: [],
                "selected_item": lambda self: track,
            },
        )()
        frame = type(
            "Frame",
            (),
            {
                "pending_resume": (remembered, 0, ""),
                "current_player_item": remembered,
                "deferred_queue_items": [],
                "spotify": type(
                    "Spotify",
                    (),
                    {
                        "add_to_queue": (
                            lambda self, item, device_id: queued_remotely.append(
                                item
                            )
                        )
                    },
                )(),
                "player_device_id": lambda self: self.fail(
                    "Deferred queue must not activate a device"
                ),
                "finish_queue_many": (
                    lambda self, items: messages.append(len(items))
                ),
                "say": lambda self, message: messages.append(message),
                "queue_should_be_deferred": (
                    MainFrame.queue_should_be_deferred
                ),
            },
        )()

        MainFrame.queue_from_list(frame, item_list)

        self.assertEqual(frame.deferred_queue_items, [track])
        self.assertEqual(queued_remotely, [])
        self.assertEqual(messages, [1])

    def test_deferred_queue_flushes_after_explicit_playback(self):
        first = ui.SpotifyItem(
            "first",
            ui.ItemKind.TRACK,
            "First",
            uri="spotify:track:first",
        )
        second = ui.SpotifyItem(
            "second",
            ui.ItemKind.TRACK,
            "Second",
            uri="spotify:track:second",
        )
        queued = []
        frame = type(
            "Frame",
            (),
            {
                "deferred_queue_items": [first, second],
                "deferred_queue_flushing": False,
                "player_device_id": lambda self: "device",
                "spotify": type(
                    "Spotify",
                    (),
                    {
                        "add_to_queue": (
                            lambda self, item, device_id: queued.append(
                                (item, device_id)
                            )
                        )
                    },
                )(),
                "run_task": (
                    lambda self, message, worker, success, **options: (
                        worker(),
                        success(None),
                    )
                ),
            },
        )()

        MainFrame.flush_deferred_queue(frame)

        self.assertEqual(queued, [(first, "device"), (second, "device")])
        self.assertEqual(frame.deferred_queue_items, [])
        self.assertFalse(frame.deferred_queue_flushing)

    def test_queue_view_includes_deferred_items(self):
        server_item = ui.SpotifyItem(
            "server",
            ui.ItemKind.TRACK,
            "Server item",
            uri="spotify:track:server",
        )
        deferred_item = ui.SpotifyItem(
            "deferred",
            ui.ItemKind.TRACK,
            "Deferred item",
            uri="spotify:track:deferred",
        )
        frame = type(
            "Frame",
            (),
            {
                "spotify": type(
                    "Spotify",
                    (),
                    {"queue": lambda self: [server_item]},
                )(),
                "deferred_queue_items": [deferred_item],
            },
        )()

        self.assertEqual(
            MainFrame.queue_items(frame),
            [server_item, deferred_item],
        )

    def test_queue_view_shows_deferred_items_without_active_device(self):
        deferred_item = ui.SpotifyItem(
            "deferred",
            ui.ItemKind.TRACK,
            "Deferred item",
            uri="spotify:track:deferred",
        )

        def unavailable():
            raise ui.SpotifyError("No active device")

        frame = type(
            "Frame",
            (),
            {
                "spotify": type(
                    "Spotify",
                    (),
                    {"queue": lambda self: unavailable()},
                )(),
                "deferred_queue_items": [deferred_item],
            },
        )()

        self.assertEqual(MainFrame.queue_items(frame), [deferred_item])


class PlaylistInformationTests(unittest.TestCase):
    def test_playlist_information_shows_owner_and_details(self):
        playlist = ui.SpotifyItem(
            "playlist",
            ui.ItemKind.PLAYLIST,
            "Shared songs",
            total=42,
            raw={
                "owner": {
                    "id": "owner-id",
                    "display_name": "Playlist Owner",
                },
                "public": True,
                "collaborative": True,
                "description": "Songs for everyone.",
            },
        )

        with patch("blindspot.ui.wx.MessageBox") as message_box:
            MainFrame.show_playlist_information(object(), playlist)

        text = message_box.call_args.args[0]
        self.assertIn("Owner: Playlist Owner", text)
        self.assertIn("Tracks: 42", text)
        self.assertIn("Visibility: Public", text)
        self.assertIn("Collaborative: Yes", text)
        self.assertIn("Description: Songs for everyone.", text)


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

    def test_control_space_resumes_paused_track_from_selected_synced_lyric(self):
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

        LyricsDialog.on_text_key(
            dialog,
            self.Event(ui.wx.WXK_SPACE, control=True),
        )

        self.assertEqual(resumed, [("track", 5_000)])

    def test_control_space_starts_unplayed_track_from_selected_lyric(self):
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

        LyricsDialog.on_text_key(
            dialog,
            self.Event(ui.wx.WXK_SPACE, control=True),
        )

        self.assertEqual(started, [(item, 5_000)])

    def test_control_space_reports_when_synced_lyrics_are_unavailable(self):
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

        LyricsDialog.on_text_key(
            dialog,
            self.Event(ui.wx.WXK_SPACE, control=True),
        )

        self.assertEqual(
            messages,
            [ui.msg.SYNCED_LYRICS_UNAVAILABLE],
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

    def test_control_space_restarts_playing_track_from_selected_lyric(self):
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

        LyricsDialog.on_text_key(
            dialog,
            self.Event(ui.wx.WXK_SPACE, control=True),
        )

        self.assertEqual(started, [(item, 5_000)])

    def test_bare_space_is_left_available_for_checkbox_toggle(self):
        checkbox_type = type("Checkbox", (), {})
        checkbox = checkbox_type()
        event = self.Event(ui.wx.WXK_SPACE, event_object=checkbox)

        with patch("blindspot.ui.wx.CheckBox", checkbox_type):
            LyricsDialog.on_dialog_key(type("Dialog", (), {})(), event)

        self.assertTrue(event.skipped)

    def test_bare_space_pauses_or_resumes_in_lyrics_text(self):
        event = self.Event(ui.wx.WXK_SPACE)
        toggled = []
        dialog = type(
            "Dialog",
            (),
            {
                "frame": type(
                    "Frame",
                    (),
                    {
                        "toggle_pause_resume": (
                            lambda self: toggled.append(True)
                        )
                    },
                )()
            },
        )()

        LyricsDialog.on_text_key(dialog, event)

        self.assertEqual(toggled, [True])
        self.assertFalse(event.skipped)

    def test_dialog_routes_bare_space_from_lyrics_text(self):
        toggled = []
        text = object()
        dialog = type(
            "Dialog",
            (),
            {
                "text": text,
                "frame": type(
                    "Frame",
                    (),
                    {
                        "toggle_pause_resume": (
                            lambda self: toggled.append(True)
                        )
                    },
                )(),
            },
        )()

        LyricsDialog.on_dialog_key(
            dialog,
            self.Event(ui.wx.WXK_SPACE, event_object=text),
        )

        self.assertEqual(toggled, [True])

    def test_dialog_routes_control_space_with_internal_native_focus(self):
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
            self.Event(
                ui.wx.WXK_SPACE,
                control=True,
                event_object=text,
            ),
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

    def test_f4_recognizes_native_list_child_focus(self):
        class ListControl:
            pass

        list_control = ListControl()
        focused_child = type(
            "FocusedChild",
            (),
            {"GetParent": lambda self: list_control},
        )()
        played = []
        messages = []
        frame = type(
            "Frame",
            (),
            {
                "play_selected": lambda self: played.append(True),
                "say": lambda self, message: messages.append(message),
            },
        )()

        with (
            patch("blindspot.ui.ItemList", ListControl),
            patch(
                "blindspot.ui.wx.Window.FindFocus",
                return_value=focused_child,
            ),
        ):
            MainFrame.on_global_key(frame, self.Event(343))

        self.assertEqual(played, [True])
        self.assertEqual(messages, [])

    def test_bare_space_toggles_playback_in_item_lists(self):
        event = self.Event(32)
        focused = object()
        toggled = []
        frame = type(
            "Frame",
            (),
            {"toggle_pause_resume": lambda self: toggled.append(True)},
        )()

        with (
            patch("blindspot.ui.wx.WXK_SPACE", 32),
            patch("blindspot.ui.wx.Window.FindFocus", return_value=focused),
            patch("blindspot.ui.space_belongs_to_control", return_value=False),
        ):
            MainFrame.on_global_key(frame, event)

        self.assertEqual(toggled, [True])
        self.assertFalse(event.skipped)

    def test_control_space_keeps_native_item_list_selection(self):
        event = self.Event(32, control=True)
        focused = object()
        frame = type(
            "Frame",
            (),
            {"toggle_pause_resume": lambda self: self.fail()},
        )()

        with (
            patch("blindspot.ui.wx.WXK_SPACE", 32),
            patch("blindspot.ui.ItemList", type(focused)),
            patch("blindspot.ui.wx.Window.FindFocus", return_value=focused),
        ):
            MainFrame.on_global_key(frame, event)

        self.assertTrue(event.skipped)

    def test_bare_space_is_left_to_native_controls(self):
        event = self.Event(32)
        focused = object()
        frame = type(
            "Frame",
            (),
            {"toggle_pause_resume": lambda self: self.fail()},
        )()

        with (
            patch("blindspot.ui.wx.WXK_SPACE", 32),
            patch("blindspot.ui.wx.Window.FindFocus", return_value=focused),
            patch("blindspot.ui.space_belongs_to_control", return_value=True),
        ):
            MainFrame.on_global_key(frame, event)

        self.assertTrue(event.skipped)

if __name__ == "__main__":
    unittest.main()
