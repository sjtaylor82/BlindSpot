import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from blindspot import ui
from blindspot.ui import (
    AlternateVersionsDialog,
    LyricsDialog,
    MainFrame,
    PlaylistsPanel,
    PodcastsPanel,
    SearchPanel,
    SetupDialog,
    album_track_label,
    filter_spotify_items,
    menu_function_shortcut,
    native_text_positions,
    playback_state_for_resume,
    podcast_language_codes,
    podcast_browse_query,
    podcast_listening_status,
    radio_box_ancestor,
    resume_mode_from_settings,
    sort_spotify_items,
    volume_percent_from_settings,
)


class LocalListFilterTests(unittest.TestCase):
    def test_filter_matches_title_artist_and_album(self):
        track = ui.SpotifyItem(
            "track",
            ui.ItemKind.TRACK,
            "Song title",
            artist="An Artist",
            album="An Album",
        )

        self.assertEqual(filter_spotify_items([track], "song artist album"), [track])

    def test_filter_is_case_and_diacritic_insensitive(self):
        track = ui.SpotifyItem(
            "track",
            ui.ItemKind.TRACK,
            "Zażółć gęślą",
            artist="Beyoncé",
        )

        self.assertEqual(
            filter_spotify_items([track], "ZAZOLC GESLA BEYONCE"),
            [track],
        )


class LocalListSortTests(unittest.TestCase):
    def test_title_sort_does_not_mutate_original_order(self):
        original = [
            ui.SpotifyItem("2", ui.ItemKind.TRACK, "Zulu"),
            ui.SpotifyItem("1", ui.ItemKind.TRACK, "Alpha"),
        ]

        result = sort_spotify_items(original, "title")

        self.assertEqual([item.name for item in result], ["Alpha", "Zulu"])
        self.assertEqual([item.name for item in original], ["Zulu", "Alpha"])

    def test_missing_sort_values_and_pagination_stay_at_end(self):
        missing = ui.SpotifyItem("1", ui.ItemKind.TRACK, "Missing")
        older = ui.SpotifyItem(
            "2",
            ui.ItemKind.TRACK,
            "Older",
            raw={"added_at": "2025-01-01"},
        )
        newer = ui.SpotifyItem(
            "3",
            ui.ItemKind.TRACK,
            "Newer",
            raw={"added_at": "2026-01-01"},
        )
        loader = ui.SpotifyItem("more", ui.ItemKind.HEADING, "Show more")

        result = sort_spotify_items(
            [missing, older, loader, newer],
            "date_added",
            descending=True,
        )

        self.assertEqual(result, [newer, older, missing, loader])

    def test_filtered_playlist_playback_starts_at_focused_match(self):
        tracks = [
            ui.SpotifyItem(
                str(number),
                ui.ItemKind.TRACK,
                f"ABBA {number}",
                uri=f"spotify:track:{number}",
            )
            for number in (1, 2, 3)
        ]
        panel = type(
            "Panel",
            (),
            {
                "filter": type(
                    "Filter", (), {"GetValue": lambda self: "abba"}
                )(),
                "items": type("Items", (), {"items": tracks})(),
            },
        )()

        self.assertEqual(
            PlaylistsPanel.filtered_playback_items(panel, tracks[1]),
            tracks[1:],
        )

    def test_f4_uses_filtered_playlist_sequence_instead_of_context(self):
        tracks = [
            ui.SpotifyItem(
                str(number),
                ui.ItemKind.TRACK,
                f"ABBA {number}",
                uri=f"spotify:track:{number}",
            )
            for number in (1, 2, 3)
        ]
        item_list = type(
            "Items",
            (),
            {"marked_items": lambda self: [], "items": tracks},
        )()
        played_sequences = []
        played_contexts = []
        playlists = type(
            "Playlists",
            (),
            {
                "current_playlist": ui.SpotifyItem(
                    "playlist",
                    ui.ItemKind.PLAYLIST,
                    "Playlist",
                ),
                "items": item_list,
                "filtered_playback_items": lambda self, item: tracks[1:],
            },
        )()
        frame = type(
            "Frame",
            (),
            {
                "resolve_then": lambda self, items, retry: False,
                "notebook": type(
                    "Notebook", (), {"GetSelection": lambda self: 3}
                )(),
                "playlists": playlists,
                "current_selected_item": lambda self: tracks[1],
                "current_item_list": lambda self: item_list,
                "play_items": lambda self, values: played_sequences.append(values),
                "play_in_context": lambda self, context, item: played_contexts.append(
                    (context, item)
                ),
            },
        )()

        MainFrame.play_selected(frame)

        self.assertEqual(played_sequences, [tracks[1:]])
        self.assertEqual(played_contexts, [])


class PodcastFilterMetadataTests(unittest.TestCase):
    def test_polish_browse_uses_polish_category_terms(self):
        self.assertEqual(
            podcast_browse_query(
                "Technology",
                "technology podcast",
                "pl",
            ),
            "technologia podcast po polsku",
        )

    def test_language_codes_are_normalised(self):
        episode = ui.SpotifyItem(
            "episode",
            ui.ItemKind.EPISODE,
            "Episode",
            raw={"languages": ["PL-pl", "en-AU", "en-US", "PL"]},
        )

        self.assertEqual(podcast_language_codes(episode), ("pl", "en"))

    def test_listening_status_preserves_unknown(self):
        unknown = ui.SpotifyItem("unknown", ui.ItemKind.EPISODE, "Unknown")
        new = ui.SpotifyItem(
            "new",
            ui.ItemKind.EPISODE,
            "New",
            raw={"resume_point": {"fully_played": False, "resume_position_ms": 0}},
        )
        progress = ui.SpotifyItem(
            "progress",
            ui.ItemKind.EPISODE,
            "Progress",
            raw={
                "resume_point": {
                    "fully_played": False,
                    "resume_position_ms": 1,
                }
            },
        )
        completed = ui.SpotifyItem(
            "completed",
            ui.ItemKind.EPISODE,
            "Completed",
            raw={"resume_point": {"fully_played": True}},
        )

        self.assertEqual(podcast_listening_status(unknown), "unknown")
        self.assertEqual(podcast_listening_status(new), "not_started")
        self.assertEqual(podcast_listening_status(progress), "in_progress")
        self.assertEqual(podcast_listening_status(completed), "completed")


class FirstRunSetupTests(unittest.TestCase):
    def test_developer_dashboard_is_the_initial_control(self):
        focused = []
        dialog = type(
            "Setup",
            (),
            {
                "open_dashboard": type(
                    "Button",
                    (),
                    {"SetFocus": lambda self: focused.append(self)},
                )(),
            },
        )()

        SetupDialog.focus_initial_control(dialog)

        self.assertEqual(focused, [dialog.open_dashboard])

    def test_web_player_is_deferred_until_spotify_is_connected(self):
        frame = type(
            "Frame",
            (),
            {
                "spotify": type("Spotify", (), {"connected": False})(),
                "player": None,
            },
        )()

        with patch("blindspot.ui.WebPlaybackController") as player:
            MainFrame._create_web_player(frame)

        player.assert_not_called()

    def test_web_player_is_created_after_first_connection(self):
        created = []
        frame = type(
            "Frame",
            (),
            {
                "recent_permission_authorization": False,
                "player": None,
                "say": lambda self, message: None,
                "_create_web_player": lambda self: created.append(True),
            },
        )()

        MainFrame.on_connected(frame)

        self.assertEqual(created, [True])


class AccountSessionTests(unittest.TestCase):
    def test_sign_out_closes_authenticated_player_and_clears_state(self):
        player = Mock()
        timer = Mock()
        spotify = Mock()
        frame = type(
            "Frame",
            (),
            {
                "spotify": spotify,
                "player": player,
                "remote_refresh_timer": timer,
                "remote_device_id": "remote",
                "remote_device_name": "Living room",
                "remote_supports_volume": True,
                "current_player_state": {"is_playing": True},
                "current_player_item": object(),
                "say": Mock(),
                "close_spotify_session": MainFrame.close_spotify_session,
            },
        )()

        with patch("blindspot.ui.wx.MessageBox", return_value=ui.wx.YES):
            MainFrame.on_sign_out(frame, None)

        spotify.sign_out.assert_called_once_with()
        player.close.assert_called_once_with()
        timer.Stop.assert_called_once_with()
        self.assertIsNone(frame.player)
        self.assertIsNone(frame.remote_device_id)
        self.assertEqual(frame.current_player_state, {})
        self.assertIsNone(frame.current_player_item)


class PlaybackMemorySettingsTests(unittest.TestCase):
    @unittest.skipUnless(ui.sys.platform == "darwin", "macOS-only assertion")
    def test_macos_does_not_define_msaa_accessible_classes(self):
        self.assertIsNone(ui._NamedPageAccessible)
        self.assertIsNone(ui._NamedControlAccessible)

    def test_custom_accessible_is_not_constructed_off_windows(self):
        window = Mock()
        accessible_type = Mock()

        with (
            patch("blindspot.ui.sys.platform", "darwin"),
            patch("blindspot.ui.physical_control_down", return_value=False),
        ):
            ui.set_windows_accessible(window, accessible_type, "Country code")

        accessible_type.assert_not_called()
        window.SetAccessible.assert_not_called()

    def test_custom_accessible_is_attached_on_windows(self):
        window = Mock()
        accessible = object()
        accessible_type = Mock(return_value=accessible)

        with patch("blindspot.ui.sys.platform", "win32"):
            ui.set_windows_accessible(window, accessible_type, "Country code")

        accessible_type.assert_called_once_with(window, "Country code")
        window.SetAccessible.assert_called_once_with(accessible)

    @unittest.skipUnless(ui.sys.platform == "win32", "MSAA is Windows-only")
    def test_named_control_accessible_exposes_explicit_self_name(self):
        accessible = type("Accessible", (), {"_name": "Country code"})()

        with patch("blindspot.ui.wx.ACC_SELF", 0), patch(
            "blindspot.ui.wx.ACC_OK", "ok"
        ):
            result = ui._NamedControlAccessible.GetName(accessible, 0)

        self.assertEqual(result, ("ok", "Country code"))

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
            enabled = True

            def SetFocus(self):
                focused_targets.append(self)

            def GetParent(self):
                return None

            def IsEnabled(self):
                return self.enabled

            def IsShown(self):
                return True

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

    def test_tab_from_final_tab_bar_focuses_saved_albums_not_podcasts(self):
        focused_targets = []

        class Control:
            enabled = True

            def SetFocus(self):
                focused_targets.append(self)

            def GetParent(self):
                return None

            def IsEnabled(self):
                return self.enabled

            def IsShown(self):
                return True

        notebook = Control()
        notebook.GetSelection = lambda: 7
        podcasts = Control()
        saved_albums = Control()
        frame = type(
            "Frame",
            (),
            {
                "notebook": notebook,
                "podcasts": type(
                    "Podcasts",
                    (),
                    {"items": podcasts},
                )(),
                "saved_albums": type(
                    "SavedAlbums",
                    (),
                    {"items": saved_albums},
                )(),
            },
        )()

        with (
            patch(
                "blindspot.ui.wx.Window.FindFocus",
                return_value=notebook,
            ),
            patch("blindspot.ui.item_list_ancestor", return_value=None),
        ):
            MainFrame.move_focus(frame, backward=False)

        self.assertEqual(focused_targets, [saved_albums])

    def test_tab_from_podcasts_tab_bar_focuses_browse_category(self):
        focused_targets = []

        class Control:
            enabled = True

            def SetFocus(self):
                focused_targets.append(self)

            def GetParent(self):
                return None

            def IsEnabled(self):
                return self.enabled

            def IsShown(self):
                return True

        notebook = Control()
        notebook.GetSelection = lambda: 6
        controls = [Control() for _ in range(4)]
        frame = type(
            "Frame",
            (),
            {
                "notebook": notebook,
                "podcasts": type(
                    "Podcasts",
                    (),
                    dict(
                        zip(
                            (
                                "browse_category",
                                "browse_button",
                                "saved_button",
                                "items",
                            ),
                            controls,
                        )
                    ),
                )(),
            },
        )()

        with (
            patch("blindspot.ui.wx.Window.FindFocus", return_value=notebook),
            patch("blindspot.ui.item_list_ancestor", return_value=None),
        ):
            MainFrame.move_focus(frame, backward=False)

        self.assertEqual(focused_targets, [controls[0]])

    def test_tab_skips_a_disabled_control(self):
        focused_targets = []

        class Control:
            enabled = True

            def SetFocus(self):
                focused_targets.append(self)

            def GetParent(self):
                return None

            def IsEnabled(self):
                return self.enabled

            def IsShown(self):
                return True

        notebook = Control()
        notebook.GetSelection = lambda: 8
        names = (
            "discovery_source",
            "release_types",
            "chart_country",
            "search_button",
            "items",
            "filter",
        )
        controls = {name: Control() for name in names}
        # New releases is selected, so the chart country picker is greyed out.
        controls["chart_country"].enabled = False
        frame = type(
            "Frame",
            (),
            {
                "notebook": notebook,
                "new_music": type("NewMusic", (), controls)(),
            },
        )()

        with (
            patch(
                "blindspot.ui.wx.Window.FindFocus",
                return_value=controls["release_types"],
            ),
            patch("blindspot.ui.item_list_ancestor", return_value=None),
            patch("blindspot.ui.radio_box_ancestor", return_value=None),
        ):
            MainFrame.move_focus(frame, backward=False)

        self.assertEqual(focused_targets, [controls["search_button"]])

    def test_shift_tab_also_skips_a_disabled_control(self):
        focused_targets = []

        class Control:
            enabled = True

            def SetFocus(self):
                focused_targets.append(self)

            def GetParent(self):
                return None

            def IsEnabled(self):
                return self.enabled

            def IsShown(self):
                return True

        notebook = Control()
        notebook.GetSelection = lambda: 8
        names = (
            "discovery_source",
            "release_types",
            "chart_country",
            "search_button",
            "items",
            "filter",
        )
        controls = {name: Control() for name in names}
        controls["chart_country"].enabled = False
        frame = type(
            "Frame",
            (),
            {
                "notebook": notebook,
                "new_music": type("NewMusic", (), controls)(),
            },
        )()

        with (
            patch(
                "blindspot.ui.wx.Window.FindFocus",
                return_value=controls["search_button"],
            ),
            patch("blindspot.ui.item_list_ancestor", return_value=None),
            patch("blindspot.ui.radio_box_ancestor", return_value=None),
        ):
            MainFrame.move_focus(frame, backward=True)

        self.assertEqual(focused_targets, [controls["release_types"]])

    def test_hosted_window_keeps_playback_keys_working(self):
        calls = []
        frame = type(
            "Frame",
            (),
            {
                "keymap_action_for_event": lambda self, event, contexts: event.action,
                "seek": lambda self, delta: calls.append(("seek", delta)),
                "adjust_volume": lambda self, delta: calls.append(("volume", delta)),
                "toggle_mute": lambda self: calls.append(("mute",)),
            },
        )()
        dialog = type("Dialog", (), {"frame": frame})()
        panel_calls = []
        dialog.panel = type("Panel", (), {"on_open": lambda self: panel_calls.append(True)})()

        def handle(action):
            event = type(
                "Event",
                (),
                {
                    "action": action,
                    "GetKeyCode": lambda self: 0,
                    "GetEventObject": lambda self: None,
                },
            )()
            return ui.HostedPanelDialog.handle_key(dialog, event)

        self.assertTrue(handle("seek_forward"))
        self.assertTrue(handle("volume_up"))
        self.assertTrue(handle("toggle_mute"))
        self.assertTrue(handle("play_focused"))
        self.assertFalse(handle("open_queue"))
        self.assertFalse(handle(None))
        self.assertEqual(
            calls, [("seek", 5000), ("volume", 5), ("mute",)]
        )
        self.assertEqual(panel_calls, [True])

    def test_mac_function_keys_are_not_menu_accelerators(self):
        self.assertEqual(menu_function_shortcut("F8", "darwin"), "")
        self.assertEqual(menu_function_shortcut("F8", "win32"), "")
        self.assertEqual(menu_function_shortcut("RAWCTRL+Y", "darwin"), "")
        self.assertEqual(menu_function_shortcut("Ctrl+Y", "win32"), "")
        self.assertEqual(
            menu_function_shortcut("RAWCTRL+Shift+I", "darwin"),
            "",
        )
        self.assertEqual(
            menu_function_shortcut("Ctrl+Shift+I", "win32"),
            "",
        )

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

    def test_control_shift_r_speaks_remaining_time(self):
        announced = []
        frame = type(
            "Frame",
            (),
            {"announce_time": lambda self, part: announced.append(part)},
        )()
        event = type(
            "Event",
            (),
            {
                "GetKeyCode": lambda self: ord("R"),
                "AltDown": lambda self: False,
                "ShiftDown": lambda self: True,
            },
        )()

        with (
            patch("blindspot.ui.physical_control_down", return_value=True),
            patch("blindspot.ui.wx.Window.FindFocus", return_value=None),
        ):
            MainFrame.on_global_key(frame, event)

        self.assertEqual(announced, ["remaining"])

    def test_control_shift_f_refreshes_current_view(self):
        refreshed = []
        frame = type(
            "Frame",
            (),
            {"refresh_current_view": lambda self: refreshed.append(True)},
        )()
        event = type(
            "Event",
            (),
            {
                "GetKeyCode": lambda self: ord("F"),
                "AltDown": lambda self: False,
                "ShiftDown": lambda self: True,
            },
        )()

        with (
            patch("blindspot.ui.physical_control_down", return_value=True),
            patch("blindspot.ui.wx.Window.FindFocus", return_value=None),
        ):
            MainFrame.on_global_key(frame, event)

        self.assertEqual(refreshed, [True])

    def test_option_m_opens_selected_item_actions_on_mac(self):
        opened = []
        frame = type(
            "Frame",
            (),
            {"show_selected_actions": lambda self: opened.append(True)},
        )()
        event = type(
            "Event",
            (),
            {
                "GetKeyCode": lambda self: ord("M"),
                "AltDown": lambda self: True,
                "ShiftDown": lambda self: False,
            },
        )()

        with (
            patch("blindspot.ui.sys.platform", "darwin"),
            patch("blindspot.ui.physical_control_down", return_value=False),
            patch("blindspot.ui.wx.Window.FindFocus", return_value=None),
        ):
            MainFrame.on_global_key(frame, event)

        self.assertEqual(opened, [True])

    def test_control_shift_l_routes_to_current_track_command(self):
        toggled = []
        frame = type(
            "Frame",
            (),
            {
                "toggle_like_current_track": (
                    lambda self: toggled.append(True)
                )
            },
        )()
        event = type(
            "Event",
            (),
            {
                "GetKeyCode": lambda self: ord("L"),
                "AltDown": lambda self: False,
                "ShiftDown": lambda self: True,
            },
        )()

        with (
            patch("blindspot.ui.physical_control_down", return_value=True),
            patch("blindspot.ui.wx.Window.FindFocus", return_value=None),
        ):
            MainFrame.on_global_key(frame, event)

        self.assertEqual(toggled, [True])

    def test_control_shift_d_opens_playback_device_chooser(self):
        opened = []
        frame = type(
            "Frame",
            (),
            {
                "choose_playback_device": (
                    lambda self: opened.append(True)
                )
            },
        )()
        event = type(
            "Event",
            (),
            {
                "GetKeyCode": lambda self: ord("D"),
                "AltDown": lambda self: False,
                "ShiftDown": lambda self: True,
            },
        )()

        with (
            patch("blindspot.ui.physical_control_down", return_value=True),
            patch("blindspot.ui.wx.Window.FindFocus", return_value=None),
        ):
            MainFrame.on_global_key(frame, event)

        self.assertEqual(opened, [True])

    def test_control_nine_focuses_discover_source(self):
        selections = []
        focused = []
        notebook = type(
            "Notebook",
            (),
            {"SetSelection": lambda self, page: selections.append(page)},
        )()
        discovery_source = type(
            "DiscoverySource",
            (),
            {"SetFocus": lambda self: focused.append(True)},
        )()
        frame = type(
            "Frame",
            (),
            {
                "notebook": notebook,
                "new_music": type(
                    "NewMusic",
                    (),
                    {"discovery_source": discovery_source},
                )(),
            },
        )()
        event = type(
            "Event",
            (),
            {
                "GetKeyCode": lambda self: ord("9"),
                "AltDown": lambda self: False,
                "ShiftDown": lambda self: False,
            },
        )()

        with (
            patch("blindspot.ui.physical_control_down", return_value=True),
            patch("blindspot.ui.wx.Window.FindFocus", return_value=None),
        ):
            MainFrame.on_global_key(frame, event)

        self.assertEqual(selections, [8])
        self.assertEqual(focused, [True])

    def test_refresh_device_choice_reloads_device_picker(self):
        refreshed = []
        frame = type(
            "Frame",
            (),
            {
                "choose_playback_device": (
                    lambda self: refreshed.append(True)
                ),
                "choose_playback_device_action": (
                    lambda self, device: self.fail(
                        "Refresh must not select a device"
                    )
                ),
            },
        )()
        devices = [{"id": "phone"}]

        MainFrame.handle_playback_device_selection(
            frame,
            devices,
            len(devices),
        )

        self.assertEqual(refreshed, [True])

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

    def test_mac_lyric_navigation_uses_option_command(self):
        event = type(
            "Event",
            (),
            {
                "GetModifiers": lambda self: 5,
                "AltDown": lambda self: True,
                "ShiftDown": lambda self: False,
            },
        )()

        with (
            patch("blindspot.ui.sys.platform", "darwin"),
            patch("blindspot.ui.wx.MOD_CONTROL", 1),
            patch("blindspot.ui.wx.MOD_RAW_CONTROL", 2),
            patch("blindspot.ui.wx.MOD_ALT", 4),
        ):
            self.assertTrue(ui.lyric_navigation_modifier_down(event))

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

    def test_saved_volume_is_validated_and_clamped(self):
        self.assertEqual(volume_percent_from_settings({}), 80)
        self.assertEqual(
            volume_percent_from_settings({"playback_volume_percent": "67"}),
            67,
        )
        self.assertEqual(
            volume_percent_from_settings({"playback_volume_percent": 140}),
            100,
        )
        self.assertEqual(
            volume_percent_from_settings({"playback_volume_percent": "bad"}),
            80,
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

    def test_custom_keymap_binding_dispatches_command(self):
        spoken = []
        mapped = ui.KeyMap(platform="win32")
        mapped.set_binding("speak_current", "Alt+C")
        frame = type(
            "Frame",
            (),
            {
                "keymap": mapped,
                "speak_current_track": lambda self: spoken.append(True),
            },
        )()
        event = type(
            "Event",
            (),
            {
                "GetKeyCode": lambda self: ord("C"),
                "GetModifiers": lambda self: ui.wx.MOD_ALT,
                "ControlDown": lambda self: False,
                "AltDown": lambda self: True,
                "ShiftDown": lambda self: False,
            },
        )()

        with (
            patch("blindspot.ui.wx.Window.FindFocus", return_value=None),
            patch("blindspot.ui.item_list_ancestor", return_value=None),
        ):
            MainFrame.on_global_key(frame, event)

        self.assertEqual(spoken, [True])

    def test_cleared_keymap_binding_does_not_use_legacy_default(self):
        mapped = ui.KeyMap(platform="win32")
        mapped.clear("pause_resume")
        frame = type(
            "Frame",
            (),
            {
                "keymap": mapped,
                "toggle_pause_resume": lambda self: self.fail(
                    "Cleared F7 must not run"
                ),
            },
        )()
        event = type(
            "Event",
            (),
            {
                "GetKeyCode": lambda self: ui.wx.WXK_F7,
                "GetModifiers": lambda self: 0,
                "ControlDown": lambda self: False,
                "AltDown": lambda self: False,
                "ShiftDown": lambda self: False,
            },
        )()

        with (
            patch("blindspot.ui.wx.Window.FindFocus", return_value=None),
            patch("blindspot.ui.item_list_ancestor", return_value=None),
        ):
            MainFrame.on_global_key(frame, event)


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
        self.assertIn("Restart or previous track (F7)", messages[0])

    def test_new_current_track_global_action_dispatches(self):
        calls = []
        frame = type(
            "Frame",
            (),
            {
                "toggle_like_current_track": lambda self: calls.append("like"),
                "previous_track": lambda self: None,
                "toggle_pause_resume": lambda self: None,
                "next_track": lambda self: None,
                "seek": lambda self, amount: None,
                "adjust_volume": lambda self, amount: None,
                "toggle_mute": lambda self: None,
                "speak_current_track": lambda self: None,
                "speak_up_next": lambda self: None,
                "announce_time": lambda self, part: None,
                "save_current_bookmark": lambda self: None,
                "toggle_shuffle": lambda self: None,
                "cycle_repeat": lambda self: None,
            },
        )()
        event = type(
            "Event",
            (),
            {
                "GetId": lambda self: ui.GLOBAL_SHORTCUT_IDS["like_current"],
            },
        )()

        MainFrame.on_global_hotkey(frame, event)

        self.assertEqual(calls, ["like"])

    def test_keyboard_manager_assigns_opt_in_global_shortcut(self):
        action = ui.ACTIONS_BY_ID["like_current"]
        shortcut = {"modifiers": ui.wx.MOD_ALT, "keycode": ord("L")}
        refreshed = []
        manager = type(
            "Manager",
            (),
            {
                "actions": type(
                    "Actions",
                    (),
                    {"GetSelection": lambda self: 0},
                )(),
                "global_shortcuts": {},
                "seen_warnings": set(),
                "selected_action": lambda self: action,
                "refresh_choices": (
                    lambda self, selected=0: refreshed.append(selected)
                ),
            },
        )()
        capture = type(
            "Capture",
            (),
            {
                "shortcut": shortcut,
                "ShowModal": lambda self: ui.wx.ID_OK,
                "Destroy": lambda self: None,
            },
        )()

        with (
            patch("blindspot.ui.ShortcutCaptureDialog", return_value=capture),
            patch("blindspot.ui.wx.MessageBox", return_value=ui.wx.YES),
        ):
            ui.KeyboardManagerDialog.on_assign_global(manager, None)

        self.assertEqual(manager.global_shortcuts, {"like_current": shortcut})
        self.assertEqual(manager.seen_warnings, {"global"})
        self.assertEqual(refreshed, [0])

    def test_keyboard_manager_conflict_warning_is_once_only(self):
        action = ui.ACTIONS_BY_ID["speak_current"]
        keymap = ui.KeyMap(platform="darwin")
        refreshed = []
        manager = type(
            "Manager",
            (),
            {
                "actions": type(
                    "Actions",
                    (),
                    {"GetSelection": lambda self: 0},
                )(),
                "keymap": keymap,
                "seen_warnings": set(),
                "context_actions": lambda self: [action],
                "refresh_choices": (
                    lambda self, selected=0: refreshed.append(selected)
                ),
            },
        )()
        capture = type(
            "Capture",
            (),
            {
                "chord": "Control+F4",
                "ShowModal": lambda self: ui.wx.ID_OK,
                "Destroy": lambda self: None,
            },
        )()

        with (
            patch("blindspot.ui.KeymapCaptureDialog", return_value=capture),
            patch("blindspot.ui.wx.MessageBox", return_value=ui.wx.ID_OK) as box,
        ):
            ui.KeyboardManagerDialog.on_assign(manager, None)
            ui.KeyboardManagerDialog.on_assign(manager, None)

        self.assertEqual(box.call_count, 1)
        self.assertEqual(manager.seen_warnings, {"os"})
        self.assertEqual(refreshed, [0, 0])

    def test_keyboard_manager_can_reject_bare_navigation_key(self):
        action = ui.ACTIONS_BY_ID["speak_current"]
        keymap = ui.KeyMap(platform="win32")
        manager = type(
            "Manager",
            (),
            {
                "actions": type(
                    "Actions",
                    (),
                    {"GetSelection": lambda self: 0},
                )(),
                "keymap": keymap,
                "seen_warnings": set(),
                "context_actions": lambda self: [action],
                "refresh_choices": lambda self, selected=0: None,
            },
        )()
        capture = type(
            "Capture",
            (),
            {
                "chord": "Up",
                "ShowModal": lambda self: ui.wx.ID_OK,
                "Destroy": lambda self: None,
            },
        )()

        with (
            patch("blindspot.ui.KeymapCaptureDialog", return_value=capture),
            patch(
                "blindspot.ui.wx.MessageBox",
                return_value=ui.wx.NO,
            ) as box,
        ):
            ui.KeyboardManagerDialog.on_assign(manager, None)

        self.assertEqual(box.call_args.args[0], ui.msg.KEYMAP_NAVIGATION_WARNING)
        self.assertEqual(
            keymap.bindings("speak_current"),
            ("Control+Shift+I",),
        )
        self.assertEqual(manager.seen_warnings, set())

    def test_keyboard_manager_starts_with_all_contexts_visible(self):
        manager = type(
            "Manager",
            (),
            {
                "context": type(
                    "Context",
                    (),
                    {"GetSelection": lambda self: 0},
                )(),
                "keymap": ui.KeyMap(platform="win32"),
                "global_shortcuts": {},
            },
        )()
        manager.current_context = (
            lambda: ui.KeyboardManagerDialog.current_context(manager)
        )
        manager.context_actions = (
            lambda: ui.KeyboardManagerDialog.context_actions(manager)
        )

        choices = ui.KeyboardManagerDialog.action_choices(manager)

        self.assertEqual(len(choices), len(ui.KEY_ACTIONS))
        self.assertIn(
            "Lists: Like or unlike focused item: Control+L",
            choices,
        )

    def test_keyboard_manager_searches_command_names(self):
        manager = type(
            "Manager",
            (),
            {
                "context": type(
                    "Context",
                    (),
                    {"GetSelection": lambda self: 0},
                )(),
                "search": type(
                    "Search",
                    (),
                    {"GetValue": lambda self: "like"},
                )(),
                "keymap": ui.KeyMap(platform="win32"),
            },
        )()
        manager.current_context = (
            lambda: ui.KeyboardManagerDialog.current_context(manager)
        )

        actions = ui.KeyboardManagerDialog.context_actions(manager)

        self.assertEqual(
            [action.id for action in actions],
            ["open_liked", "like_focused", "like_current"],
        )

    def test_keyboard_warning_is_remembered_when_manager_is_cancelled(self):
        writes = []
        frame = type(
            "Frame",
            (),
            {
                "keymap": ui.KeyMap(platform="darwin"),
                "keymap_warnings_seen": set(),
                "global_shortcuts": {},
                "store": type(
                    "Store",
                    (),
                    {
                        "write": (
                            lambda self, name, value: writes.append(
                                (name, value)
                            )
                        )
                    },
                )(),
                "say": lambda self, message: self.fail(
                    "Cancel must not announce a saved map"
                ),
            },
        )()
        dialog = type(
            "Dialog",
            (),
            {
                "keymap": frame.keymap,
                "seen_warnings": {"os"},
                "ShowModal": lambda self: ui.wx.ID_CANCEL,
                "Destroy": lambda self: None,
            },
        )()

        with patch(
            "blindspot.ui.KeyboardManagerDialog",
            return_value=dialog,
        ):
            MainFrame.open_keyboard_manager(frame)

        self.assertEqual(frame.keymap_warnings_seen, {"os"})
        self.assertEqual(
            writes,
            [
                (
                    "keymap.json",
                    {"bindings": {}, "warnings_seen": ["os"]},
                )
            ],
        )

    def test_keyboard_manager_saves_and_applies_global_assignments(self):
        writes = []
        applied = []
        spoken = []
        shortcut = {"modifiers": ui.wx.MOD_ALT, "keycode": ord("L")}
        store = type(
            "Store",
            (),
            {
                "read": lambda self, name, default: {"logging_level": "Off"},
                "write": lambda self, name, value: writes.append((name, value)),
            },
        )()
        frame = type(
            "Frame",
            (),
            {
                "keymap": ui.KeyMap(platform="win32"),
                "keymap_warnings_seen": set(),
                "global_shortcuts": {},
                "store": store,
                "apply_global_hotkey_setting": (
                    lambda self: applied.append(True)
                ),
                "say": lambda self, message: spoken.append(message),
            },
        )()
        dialog = type(
            "Dialog",
            (),
            {
                "keymap": frame.keymap,
                "seen_warnings": {"global"},
                "global_shortcuts": {"like_current": shortcut},
                "ShowModal": lambda self: ui.wx.ID_OK,
                "Destroy": lambda self: None,
            },
        )()

        with patch(
            "blindspot.ui.KeyboardManagerDialog",
            return_value=dialog,
        ):
            MainFrame.open_keyboard_manager(frame)

        self.assertEqual(frame.global_shortcuts, {"like_current": shortcut})
        self.assertEqual(writes[0][0], "keymap.json")
        self.assertEqual(
            writes[1],
            (
                "settings.json",
                {
                    "logging_level": "Off",
                    "global_shortcuts": {"like_current": shortcut},
                },
            ),
        )
        self.assertEqual(applied, [True])
        self.assertEqual(spoken, ["Keyboard map saved."])


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
                "set_view_title": MainFrame.set_view_title,
                "title_for_page": MainFrame.title_for_page,
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
        self.assertEqual(titles, ["Recently Played - BlindSpot"])

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
                "resolve_then": lambda self, items, retry: False,
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

    def test_like_selected_does_not_fall_back_to_playing_track(self):
        playlist = ui.SpotifyItem(
            "playlist",
            ui.ItemKind.PLAYLIST,
            "Playlist",
            uri="spotify:playlist:playlist",
        )
        playing = ui.SpotifyItem(
            "playing",
            ui.ItemKind.TRACK,
            "Now playing",
            uri="spotify:track:playing",
        )
        toggled = []
        frame = type(
            "Frame",
            (),
            {
                "current_selected_item": lambda self: playlist,
                "current_player_item": playing,
                "toggle_like_item": (
                    lambda self, item: toggled.append(item)
                ),
            },
        )()

        MainFrame.toggle_like_selected(frame)

        self.assertEqual(toggled, [playlist])

    def test_like_current_track_ignores_selected_playlist(self):
        playing = ui.SpotifyItem(
            "playing",
            ui.ItemKind.TRACK,
            "Now playing",
            uri="spotify:track:playing",
        )
        toggled = []
        frame = type(
            "Frame",
            (),
            {
                "pending_resume": None,
                "current_player_item": playing,
                "toggle_like_item": (
                    lambda self, item: toggled.append(item)
                ),
            },
        )()

        MainFrame.toggle_like_current_track(frame)

        self.assertEqual(toggled, [playing])

    def test_open_similar_mix_announces_source_and_result_count(self):
        source = ui.SpotifyItem("source", ui.ItemKind.TRACK, "Source song")
        results = [
            ui.SpotifyItem("one", ui.ItemKind.TRACK, "Related one"),
            ui.SpotifyItem("two", ui.ItemKind.TRACK, "Related two"),
        ]
        shown = []
        spoken = []
        frame = type(
            "Frame",
            (),
            {
                "show_lastfm_results": (
                    lambda self, title, values: shown.append((title, values))
                ),
                "say": lambda self, message: spoken.append(message),
            },
        )()

        MainFrame.finish_open_similar_mix(frame, source, results)

        self.assertEqual(shown[0][1], results)
        self.assertIn("Source song", shown[0][0])
        self.assertEqual(
            spoken,
            ["Opened Last.fm similar-track mix for Source song, 2 tracks"],
        )

    def test_start_similar_mix_plays_results_and_announces_source(self):
        source = ui.SpotifyItem("source", ui.ItemKind.TRACK, "Source song")
        results = [ui.SpotifyItem("one", ui.ItemKind.TRACK, "Related one")]
        calls = []
        frame = type(
            "Frame",
            (),
            {
                "play_items": (
                    lambda self, values, **options: calls.append(
                        (values, options)
                    )
                )
            },
        )()

        MainFrame.finish_start_similar_mix(frame, source, results)

        self.assertEqual(calls[0][0], [results[0]])
        self.assertEqual(
            calls[0][1]["started_message"],
            "Started Last.fm similar-track mix for Source song, 1 track ready",
        )
        self.assertTrue(calls[0][1]["disable_repeat"])
        self.assertIsNotNone(calls[0][1]["after_started"])

    def test_started_similar_mix_creates_continuous_session(self):
        source = ui.SpotifyItem("source", ui.ItemKind.TRACK, "Source song")
        results = [
            ui.SpotifyItem("one", ui.ItemKind.TRACK, "Related one"),
            ui.SpotifyItem("two", ui.ItemKind.TRACK, "Related two"),
        ]
        frame = type(
            "Frame",
            (),
            {
                "continuous_mix_generation": 0,
                "continuous_mix": None,
                "play_items": lambda self, values, **options: None,
            },
        )()

        MainFrame.finish_start_similar_mix(frame, source, results)

        self.assertEqual(frame.continuous_mix_generation, 1)
        self.assertEqual(frame.continuous_mix["seen"], {"source", "one", "two"})
        self.assertEqual(frame.continuous_mix["queued"], {"one"})
        self.assertTrue(frame.continuous_mix["building"])

    def test_continuous_mix_replenishes_when_tracked_queue_runs_low(self):
        current = ui.SpotifyItem(
            "current",
            ui.ItemKind.TRACK,
            "Current",
            artist="Artist",
        )
        tasks = []
        frame = type(
            "Frame",
            (),
            {
                "continuous_mix": {
                    "generation": 3,
                    "seen": {"current", "next"},
                    "queued": {"current", "next"},
                    "building": False,
                },
                "lastfm": object(),
                "run_task": (
                    lambda self, message, operation, completed, failure=None: (
                        tasks.append((operation, completed))
                    )
                ),
            },
        )()

        MainFrame.update_continuous_similar_mix(frame, current)

        self.assertEqual(frame.continuous_mix["queued"], {"next"})
        self.assertTrue(frame.continuous_mix["building"])
        self.assertEqual(len(tasks), 1)

    def mix_frame(self, tasks, generation=3):
        return type(
            "Frame",
            (),
            {
                "continuous_mix": {
                    "generation": generation,
                    "seen": {"current", "other"},
                    "queued": set(),
                    "building": False,
                },
                "continuous_mix_generation": generation,
                "lastfm": object(),
                "run_task": (
                    lambda self, message, operation, completed, failure=None: (
                        tasks.append((operation, completed, failure))
                    )
                ),
                "player_device_id": lambda self: "device",
                "finish_queue_many": lambda self, items, **options: None,
                "abandon_continuous_mix_build": (
                    MainFrame.abandon_continuous_mix_build
                ),
            },
        )()

    def test_failed_replenish_lookup_lets_the_mix_try_again(self):
        current = ui.SpotifyItem("current", ui.ItemKind.TRACK, "Current")
        other = ui.SpotifyItem("other", ui.ItemKind.TRACK, "Other")
        tasks = []
        frame = self.mix_frame(tasks)

        MainFrame.update_continuous_similar_mix(frame, current)
        self.assertTrue(frame.continuous_mix["building"])
        tasks[0][2]()

        self.assertFalse(frame.continuous_mix["building"])
        MainFrame.update_continuous_similar_mix(frame, other)
        self.assertEqual(len(tasks), 2)

    def test_failed_queueing_of_mix_results_lets_the_mix_try_again(self):
        current = ui.SpotifyItem("current", ui.ItemKind.TRACK, "Current")
        track = ui.SpotifyItem(
            "new", ui.ItemKind.TRACK, "New", uri="spotify:track:new"
        )
        tasks = []
        frame = self.mix_frame(tasks)
        frame.continuous_mix["building"] = True

        MainFrame.queue_continuous_similar_results(frame, current, [track], 3)
        tasks[0][2]()

        self.assertFalse(frame.continuous_mix["building"])

    def test_partial_initial_mix_failure_records_only_accepted_tracks(self):
        source = ui.SpotifyItem("source", ui.ItemKind.TRACK, "Source")
        first = ui.SpotifyItem(
            "first", ui.ItemKind.TRACK, "First", uri="spotify:track:first"
        )
        second = ui.SpotifyItem(
            "second", ui.ItemKind.TRACK, "Second", uri="spotify:track:second"
        )

        def add_to_queue(self, item, device_id):
            if item is second:
                raise RuntimeError("Spotify said no")

        def run_task(self, message, worker, success, failure=None):
            try:
                worker()
            except RuntimeError:
                failure()
            else:
                success(None)

        frame = type(
            "Frame",
            (),
            {
                "continuous_mix": {
                    "generation": 3,
                    "seen": {"source", "first", "second"},
                    "queued": {"source"},
                    "building": True,
                },
                "continuous_mix_generation": 3,
                "spotify": type(
                    "Spotify", (), {"add_to_queue": add_to_queue}
                )(),
                "player_device_id": lambda self: "device",
                "run_task": run_task,
                "finish_queue_many": lambda self, items, **options: None,
                "finish_continuous_mix_build": lambda self: None,
                "abandon_continuous_mix_build": (
                    MainFrame.abandon_continuous_mix_build
                ),
            },
        )()

        MainFrame.queue_initial_similar_mix(
            frame,
            source,
            [first, second],
            [],
            {"source", "first", "second"},
        )

        self.assertEqual(frame.continuous_mix["queued"], {"source", "first"})
        self.assertFalse(frame.continuous_mix["building"])

    def test_a_late_failure_from_an_old_mix_does_not_touch_a_new_one(self):
        tasks = []
        frame = self.mix_frame(tasks, generation=5)
        frame.continuous_mix["building"] = True

        MainFrame.abandon_continuous_mix_build(frame, 4)

        self.assertTrue(frame.continuous_mix["building"])

    def test_unrelated_playback_ends_continuous_mix(self):
        unrelated = ui.SpotifyItem("other", ui.ItemKind.TRACK, "Other")
        frame = type(
            "Frame",
            (),
            {
                "continuous_mix": {
                    "generation": 1,
                    "seen": {"mix-track"},
                    "queued": set(),
                    "building": False,
                }
            },
        )()

        MainFrame.update_continuous_similar_mix(frame, unrelated)

        self.assertIsNone(frame.continuous_mix)

    def test_open_similar_mix_adds_load_more_marker_for_remaining_candidates(self):
        source = ui.SpotifyItem("source", ui.ItemKind.TRACK, "Source song")
        result = ui.SpotifyItem("one", ui.ItemKind.TRACK, "Related one")
        remaining = [ui.SimilarTrack("Later", "Artist")]
        shown = []
        frame = type(
            "Frame",
            (),
            {
                "show_lastfm_results": (
                    lambda self, title, values: shown.extend(values)
                ),
                "say": lambda self, message: None,
            },
        )()

        MainFrame.finish_open_similar_mix(
            frame,
            source,
            [result],
            remaining,
            {source.id, result.id},
        )

        self.assertEqual(shown[0], result)
        self.assertTrue(shown[1].raw["lastfm_load_more"])
        self.assertEqual(shown[1].raw["remaining"], remaining)

    def test_lastfm_matching_removes_duplicates_across_pages(self):
        duplicate = ui.SpotifyItem("same", ui.ItemKind.TRACK, "Same")
        unique = ui.SpotifyItem("unique", ui.ItemKind.TRACK, "Unique")
        spotify = type(
            "Spotify",
            (),
            {
                "find_track": lambda self, name, artist: (
                    duplicate if name in {"First", "Duplicate"} else unique
                )
            },
        )()
        frame = type("Frame", (), {"spotify": spotify})()
        seen = set()

        results = MainFrame.match_lastfm_tracks(
            frame,
            [
                ui.SimilarTrack("First", "Artist"),
                ui.SimilarTrack("Duplicate", "Artist"),
                ui.SimilarTrack("Unique", "Artist"),
            ],
            seen,
        )

        self.assertEqual(results, [duplicate, unique])
        self.assertEqual(seen, {"same", "unique"})

    def test_queue_similar_mix_defers_results_after_current_queue(self):
        source = ui.SpotifyItem("source", ui.ItemKind.TRACK, "Source song")
        results = [ui.SpotifyItem("one", ui.ItemKind.TRACK, "Related one")]
        finished = []
        frame = type(
            "Frame",
            (),
            {
                "deferred_queue_items": [],
                "queue_should_be_deferred": lambda self: True,
                "finish_queue_many": (
                    lambda self, values, **options: finished.append(
                        (values, options)
                    )
                ),
            },
        )()

        MainFrame.finish_queue_similar_mix(frame, source, results)

        self.assertEqual(frame.deferred_queue_items, results)
        self.assertEqual(finished[0][0], results)
        self.assertEqual(
            finished[0][1]["announcement"],
            "Added Last.fm similar-track mix for Source song "
            "after the current queue, 1 track",
        )

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
                "resolve_then": lambda self, items, retry: False,
                "open_album_for_track": (
                    lambda self, item: opened.append(item)
                )
            },
        )()

        MainFrame.open_selected_track_album(frame, track)

        self.assertEqual(opened, [track])

    def test_opening_track_album_remembers_exact_paginated_search_row(self):
        track = ui.SpotifyItem("track", ui.ItemKind.TRACK, "Track")
        state = ui.ViewState(
            "Results",
            [
                ui.SpotifyItem(str(index), ui.ItemKind.TRACK, str(index))
                for index in range(45)
            ],
            selected=20,
        )
        history = ui.NavigationHistory(state)
        tasks = []
        frame = type(
            "Frame",
            (),
            {
                "notebook": type(
                    "Notebook",
                    (),
                    {"GetSelection": lambda self: 0},
                )(),
                "search": type(
                    "Search",
                    (),
                    {
                        "history": history,
                        "results": type(
                            "Results",
                            (),
                            {"GetSelection": lambda self: 37},
                        )(),
                    },
                )(),
                "run_task": (
                    lambda self, message, task, callback: tasks.append(
                        (message, task, callback)
                    )
                ),
            },
        )()

        MainFrame.open_album_for_track(frame, track)

        self.assertEqual(state.selected, 37)
        self.assertEqual(len(tasks), 1)

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

    def test_dataview_item_list_letter_selects_next_matching_row(self):
        selected = []
        forwarded = []
        labels = ["Alpha", "Beta", "Bravo"]
        frame = type(
            "Frame",
            (),
            {"on_global_key": lambda self, event: forwarded.append(event)},
        )()
        panel = type("Panel", (), {"frame": frame})()
        item_list = type(
            "List",
            (),
            {
                "GetParent": lambda self: panel,
                "GetItemCount": lambda self: len(labels),
                "GetSelection": lambda self: 1,
                "GetTextValue": lambda self, row, column: labels[row],
                "SetSelection": lambda self, row: selected.append(row),
            },
        )()
        event = type(
            "Event",
            (),
            {
                "GetModifiers": lambda self: 0,
                "MetaDown": lambda self: False,
                "GetKeyCode": lambda self: ord("B"),
            },
        )()

        with patch("blindspot.ui.ITEM_LIST_USES_DATAVIEW", True):
            ui.ItemList.on_char_hook(item_list, event)

        self.assertEqual(selected, [2])
        self.assertEqual(forwarded, [])

    def test_item_list_rapid_letters_refine_the_current_match(self):
        selected = []
        labels = ["Charlie", "Chocolate", "Delta"]
        item_list = type(
            "List",
            (),
            {
                "_typeahead_text": "",
                "_typeahead_time": 0.0,
                "GetItemCount": lambda self: len(labels),
                "GetSelection": lambda self: selected[-1] if selected else 2,
                "GetItemText": lambda self, row, column: labels[row],
                "SetSelection": lambda self, row: selected.append(row),
            },
        )()

        def event(letter):
            return type(
                "Event",
                (),
                {
                    "GetModifiers": lambda self: 0,
                    "MetaDown": lambda self: False,
                    "GetKeyCode": lambda self: ord(letter),
                },
            )()

        with (
            patch("blindspot.ui.ITEM_LIST_USES_DATAVIEW", False),
            patch("blindspot.ui.time.monotonic", side_effect=[10.0, 10.2]),
        ):
            ui.ItemList.select_by_typed_letter(item_list, event("C"))
            ui.ItemList.select_by_typed_letter(item_list, event("H"))

        self.assertEqual(selected, [0, 0])
        self.assertEqual(item_list._typeahead_text, "ch")

    def test_item_list_routes_standard_playlist_clipboard_shortcuts(self):
        calls = []
        frame = type(
            "Frame",
            (),
            {
                "copy_items_to_playlist_clipboard": (
                    lambda self, owner, cut: calls.append(("copy", cut))
                ),
                "paste_playlist_clipboard": (
                    lambda self: calls.append(("paste", None))
                ),
            },
        )()
        panel = type("Panel", (), {"frame": frame})()
        item_list = type(
            "List", (), {"GetParent": lambda self: panel}
        )()

        def event(letter):
            return type(
                "Event",
                (),
                {
                    "GetKeyCode": lambda self: ord(letter),
                    "GetModifiers": lambda self: ui.wx.MOD_CONTROL,
                    "ControlDown": lambda self: True,
                    "RawControlDown": lambda self: False,
                    "AltDown": lambda self: False,
                    "ShiftDown": lambda self: False,
                    "MetaDown": lambda self: False,
                },
            )()

        ui.ItemList.on_char_hook(item_list, event("C"))
        ui.ItemList.on_char_hook(item_list, event("X"))
        ui.ItemList.on_char_hook(item_list, event("V"))

        self.assertEqual(
            calls, [("copy", False), ("copy", True), ("paste", None)]
        )

    def test_cut_requires_an_open_editable_playlist(self):
        spoken = []
        item = ui.SpotifyItem(
            "track", ui.ItemKind.TRACK, "Track", uri="spotify:track:track"
        )
        item_list = type(
            "Items",
            (),
            {
                "marked_items": lambda self: [item],
                "selected_item": lambda self: item,
            },
        )()
        frame = type(
            "Frame",
            (),
            {
                "playlists": type(
                    "Playlists",
                    (),
                    {
                        "items": object(),
                        "history": type(
                            "History", (), {"can_go_back": False}
                        )(),
                        "current_playlist": None,
                    },
                )(),
                "say": lambda self, message: spoken.append(message),
            },
        )()

        MainFrame.copy_items_to_playlist_clipboard(frame, item_list, cut=True)

        self.assertEqual(
            spoken, ["Cut is available only inside an editable playlist."]
        )

    def test_mac_item_list_control_letter_remains_a_shortcut(self):
        forwarded = []
        frame = type(
            "Frame",
            (),
            {"on_global_key": lambda self, event: forwarded.append(event)},
        )()
        panel = type("Panel", (), {"frame": frame})()
        item_list = type(
            "List",
            (),
            {
                "GetParent": lambda self: panel,
            },
        )()
        event = type(
            "Event",
            (),
            {
                "GetModifiers": lambda self: ui.wx.MOD_RAW_CONTROL,
                "MetaDown": lambda self: False,
                "GetKeyCode": lambda self: ord("B"),
            },
        )()

        with patch("blindspot.ui.sys.platform", "darwin"):
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
                            "audiobooks",
                            "podcasts",
                            "saved_albums",
                        ),
                        panels,
                    )
                ),
            ),
        )()

        MainFrame.show_selected_actions(frame)

        self.assertEqual(called, [6])


class NowPlayingTests(unittest.TestCase):
    def test_current_track_context_menu_exposes_direct_actions(self):
        calls = []
        track = ui.SpotifyItem(
            "track-1",
            ui.ItemKind.TRACK,
            "Song",
            raw={"artists": [{"id": "artist-1", "name": "Artist"}]},
        )
        frame = type(
            "Frame",
            (),
            {
                "popup_item_menu": (
                    lambda self, owner, item, **options: calls.append(options)
                ),
                "show_lyrics_for_item": lambda self, item: None,
                "choose_playlist_for_item": lambda self, item: None,
                "show_artist_albums": lambda self, artist_id, name: None,
            },
        )()
        panel = type(
            "Panel",
            (),
            {
                "frame": frame,
                "items": object(),
                "selected_item": lambda self: track,
            },
        )()

        ui.NowPlayingPanel.on_context_menu(panel)

        labels = [label for label, _callback in calls[0]["top_level_actions"]]
        self.assertEqual(
            labels,
            [
                "Show &lyrics",
                "Add to &playlist...",
                "Show albums by &Artist",
            ],
        )

    def test_now_playing_row_tracks_current_item(self):
        updates = []
        frame = type(
            "Frame",
            (),
            {
                "now_playing": type(
                    "Panel",
                    (),
                    {"set_item": lambda self, item: updates.append(item)},
                )()
            },
        )()
        track = ui.SpotifyItem("track-1", ui.ItemKind.TRACK, "Song")

        MainFrame.update_now_playing(frame, track)
        MainFrame.update_now_playing(frame, None)

        self.assertEqual(updates, [track, None])


class SearchContextMenuTests(unittest.TestCase):
    def test_shared_list_context_menu_queues_the_marked_selection(self):
        callbacks = {}

        class Menu:
            def Append(self, item_id, label):
                return label

            def AppendSubMenu(self, menu, label):
                pass

            def AppendSeparator(self):
                pass

            def Bind(self, event, callback, item):
                callbacks[item] = callback

            def Destroy(self):
                pass

        track = ui.SpotifyItem(
            "track",
            ui.ItemKind.TRACK,
            "Track",
            uri="spotify:track:track",
        )
        queued = []
        owner = type(
            "Items",
            (),
            {"PopupMenu": lambda self, menu: None},
        )()
        frame = type(
            "Frame",
            (),
            {
                "current_player_item": None,
                "resolve_then": lambda self, items, retry: False,
                "queue_from_list": lambda self, items: queued.append(items),
                "queue_selected": lambda self, item: self.fail(
                    "A list menu must preserve the marked selection"
                ),
            },
        )()

        with (
            patch("blindspot.ui.wx.Menu", side_effect=lambda: Menu()),
            patch("blindspot.ui.ItemList", type(owner)),
        ):
            MainFrame.popup_item_menu(frame, owner, track)
            callbacks["Add to &queue"](None)

        self.assertEqual(queued, [owner])

    def test_shared_non_list_context_menu_queues_the_item(self):
        callbacks = {}

        class Menu:
            def Append(self, item_id, label):
                return label

            def AppendSubMenu(self, menu, label):
                pass

            def AppendSeparator(self):
                pass

            def Bind(self, event, callback, item):
                callbacks[item] = callback

            def Destroy(self):
                pass

        track = ui.SpotifyItem(
            "track",
            ui.ItemKind.TRACK,
            "Track",
            uri="spotify:track:track",
        )
        queued = []
        owner = type(
            "Owner",
            (),
            {"PopupMenu": lambda self, menu: None},
        )()
        frame = type(
            "Frame",
            (),
            {
                "current_player_item": None,
                "resolve_then": lambda self, items, retry: False,
                "queue_from_list": lambda self, items: None,
                "queue_selected": lambda self, item: queued.append(item),
            },
        )()

        with patch("blindspot.ui.wx.Menu", side_effect=lambda: Menu()):
            MainFrame.popup_item_menu(frame, owner, track)
            callbacks["Add to &queue"](None)

        self.assertEqual(queued, [track])

    def test_shared_track_context_menu_contains_show_lyrics(self):
        labels = []

        class Menu:
            def Append(self, item_id, label):
                labels.append(label)
                return object()

            def AppendSubMenu(self, menu, label):
                labels.append(label)

            def AppendSeparator(self):
                pass

            def Bind(self, event, callback, item):
                pass

            def Destroy(self):
                pass

        track = ui.SpotifyItem(
            "track",
            ui.ItemKind.TRACK,
            "Track",
            uri="spotify:track:track",
        )
        owner = type(
            "Items",
            (),
            {"PopupMenu": lambda self, menu: None},
        )()
        frame = type(
            "Frame",
            (),
            {
                "current_player_item": None,
                "resolve_then": lambda self, items, retry: False,
            },
        )()

        with patch("blindspot.ui.wx.Menu", side_effect=lambda: Menu()):
            MainFrame.popup_item_menu(frame, owner, track)

        self.assertIn("Show &lyrics", labels)

    def test_shared_album_open_route_retains_album_for_artwork_button(self):
        album = ui.SpotifyItem(
            "album",
            ui.ItemKind.ALBUM,
            "Album",
            raw={"images": [{"url": "art"}]},
        )
        track = ui.SpotifyItem("track", ui.ItemKind.TRACK, "Track")
        history = ui.NavigationHistory(ui.ViewState("Search", []))
        rendered = []
        selections = []
        frame = type(
            "Frame",
            (),
            {
                "notebook": type(
                    "Notebook",
                    (),
                    {
                        "GetSelection": lambda self: 8,
                        "SetSelection": (
                            lambda self, page: selections.append(page)
                        ),
                    },
                )(),
                "search": type(
                    "Search",
                    (),
                    {
                        "history": history,
                        "render": (
                            lambda self, state, focus: rendered.append(state)
                        ),
                    },
                )(),
                "open_album_return_page": None,
                "open_album_return_state": None,
                "focus_open_album": lambda self: None,
                "say": lambda self, message: None,
            },
        )()

        with patch("blindspot.ui.wx.CallAfter"):
            MainFrame.finish_open_album(frame, album, [track])

        self.assertIs(rendered[0].parent_item, album)
        self.assertEqual(selections, [0])

    def test_artist_albums_from_new_music_remember_return_page(self):
        artist = ui.SpotifyItem("artist", ui.ItemKind.ARTIST, "Artist")
        albums = [ui.SpotifyItem("album", ui.ItemKind.ALBUM, "Album")]
        history = ui.NavigationHistory(ui.ViewState("Search", []))
        selections = []

        def open_children(search, parent, children):
            history.push(
                ui.ViewState(
                    parent.name,
                    children,
                    parent_id=parent.id,
                    parent_kind=parent.kind,
                    parent_item=parent,
                )
            )

        frame = type(
            "Frame",
            (),
            {
                "notebook": type(
                    "Notebook",
                    (),
                    {"SetSelection": lambda self, page: selections.append(page)},
                )(),
                "search": type(
                    "Search",
                    (),
                    {"history": history, "open_children": open_children},
                )(),
                "open_album_return_page": None,
                "open_album_return_state": None,
                "focus_open_album": lambda self: None,
            },
        )()

        with patch("blindspot.ui.wx.CallAfter"):
            MainFrame.finish_show_artist_albums(frame, 9, artist, albums)

        self.assertEqual(selections, [0])
        self.assertEqual(frame.open_album_return_page, 9)
        self.assertIs(frame.open_album_return_state, history.current)
        self.assertIs(history.current.parent_item, artist)

    def test_related_albums_are_grouped_ranked_and_exclude_source(self):
        source = ui.SpotifyItem(
            "source",
            ui.ItemKind.ALBUM,
            "Source Album",
            artist="Source Artist",
            total=3,
        )
        seeds = [
            ui.SpotifyItem(
                str(number),
                ui.ItemKind.TRACK,
                f"Seed {number}",
                artist="Source Artist",
            )
            for number in range(3)
        ]
        album_a = ui.SpotifyItem(
            "album-a",
            ui.ItemKind.ALBUM,
            "Related A",
            artist="Artist A",
            total=10,
        )
        album_b = ui.SpotifyItem(
            "album-b",
            ui.ItemKind.ALBUM,
            "Related B",
            artist="Artist B",
            total=8,
        )
        candidates = [
            ui.SimilarTrack("A one", "Artist A"),
            ui.SimilarTrack("B one", "Artist B"),
            ui.SimilarTrack("A two", "Artist A"),
            ui.SimilarTrack("Source song", "Source Artist"),
        ]
        tracks = {
            "A one": ui.SpotifyItem("a1", ui.ItemKind.TRACK, "A one"),
            "A two": ui.SpotifyItem("a2", ui.ItemKind.TRACK, "A two"),
            "B one": ui.SpotifyItem("b1", ui.ItemKind.TRACK, "B one"),
            "Source song": ui.SpotifyItem(
                "source-track", ui.ItemKind.TRACK, "Source song"
            ),
        }
        album_for_track = {
            "a1": album_a,
            "a2": album_a,
            "b1": album_b,
            "source-track": source,
        }
        spotify = type(
            "Spotify",
            (),
            {
                "children": lambda self, album: seeds,
                "find_track": lambda self, name, artist: tracks.get(name),
                "album_for_track": (
                    lambda self, track: album_for_track[track.id]
                ),
            },
        )()
        lastfm = type(
            "Lastfm",
            (),
            {"similar_tracks": lambda self, *args, **kwargs: candidates},
        )()
        frame = type("Frame", (), {"spotify": spotify, "lastfm": lastfm})()

        result = MainFrame.related_albums_for(frame, source)

        self.assertEqual(result, [album_a, album_b])

    def test_album_artwork_button_uses_open_album_not_selected_track(self):
        album = ui.SpotifyItem(
            "album",
            ui.ItemKind.ALBUM,
            "Album",
            raw={"images": [{"url": "art"}]},
        )
        track = ui.SpotifyItem("track", ui.ItemKind.TRACK, "Track")
        shown = []
        panel = type(
            "Panel",
            (),
            {
                "history": ui.NavigationHistory(
                    ui.ViewState(
                        "Album",
                        [track],
                        parent_id=album.id,
                        parent_kind=album.kind,
                        parent_item=album,
                    )
                ),
                "frame": type(
                    "Frame",
                    (),
                    {
                        "show_album_artwork": (
                            lambda self, item: shown.append(item)
                        )
                    },
                )(),
            },
        )()

        SearchPanel.on_display_album_artwork(panel)

        self.assertEqual(shown, [album])

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
                "saved_albums": panel,
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
                "resolve_then": lambda self, items, retry: False,
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

    def test_f4_plays_multiple_selected_tracks_as_one_sequence(self):
        tracks = [
            ui.SpotifyItem(
                f"track-{number}",
                ui.ItemKind.TRACK,
                f"Track {number}",
                uri=f"spotify:track:track-{number}",
            )
            for number in (1, 2, 3)
        ]
        played = []
        item_list = type(
            "Items",
            (),
            {"marked_items": lambda self: tracks},
        )()
        frame = type(
            "Frame",
            (),
            {
                "resolve_then": lambda self, items, retry: False,
                "notebook": type(
                    "Notebook", (), {"GetSelection": lambda self: 1}
                )(),
                "liked": type("Liked", (), {"items": item_list})(),
                "search": type("Search", (), {"results": item_list})(),
                "queue": type("Queue", (), {"items": item_list})(),
                "playlists": type("Playlists", (), {"items": item_list})(),
                "recently_played": type("Recent", (), {"items": item_list})(),
                "bookmarks": type("Bookmarks", (), {"items": item_list})(),
                "audiobooks": type("Audiobooks", (), {"items": item_list})(),
                "podcasts": type("Podcasts", (), {"items": item_list})(),
                "saved_albums": type("Albums", (), {"items": item_list})(),
                "new_music": type("NewMusic", (), {"items": item_list})(),
                "current_selected_item": lambda self: tracks[0],
                "current_item_list": lambda self: item_list,
                "play_items": lambda self, values: played.extend(values),
            },
        )()

        MainFrame.play_selected(frame)

        self.assertEqual(played, tracks)

    def test_context_play_now_plays_marked_tracks_as_one_sequence(self):
        tracks = [
            ui.SpotifyItem(
                f"track-{number}",
                ui.ItemKind.TRACK,
                f"Track {number}",
                uri=f"spotify:track:track-{number}",
            )
            for number in (1, 2, 3)
        ]
        played = []
        focused_only = []
        owner = type(
            "Items",
            (),
            {"marked_items": lambda self: tracks},
        )()
        frame = type(
            "Frame",
            (),
            {"play_items": lambda self, values: played.extend(values)},
        )()

        MainFrame.play_now_from_menu(
            frame,
            owner,
            tracks[0],
            lambda: focused_only.append(tracks[0]),
        )

        self.assertEqual(played, tracks)
        self.assertEqual(focused_only, [])

    def test_context_play_now_preserves_single_item_callback(self):
        track = ui.SpotifyItem(
            "track-1",
            ui.ItemKind.TRACK,
            "Track 1",
            uri="spotify:track:track-1",
        )
        called = []
        owner = type(
            "Items",
            (),
            {"marked_items": lambda self: [track]},
        )()
        frame = object()

        MainFrame.play_now_from_menu(
            frame,
            owner,
            track,
            lambda: called.append(track),
        )

        self.assertEqual(called, [track])

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

    def test_album_track_offers_to_open_primary_artists_albums(self):
        calls = []
        track = ui.SpotifyItem("track", ui.ItemKind.TRACK, "Song")
        frame = type(
            "Frame",
            (),
            {
                "popup_item_menu": (
                    lambda self, owner, item, **options: calls.append(options)
                )
            },
        )()
        panel = type(
            "Panel",
            (),
            {
                "frame": frame,
                "results": type(
                    "Results", (), {"selected_item": lambda self: track}
                )(),
                "history": ui.NavigationHistory(
                    ui.ViewState(
                        "Album",
                        [track],
                        parent_id="album",
                        parent_kind=ui.ItemKind.ALBUM,
                        parent_artist_names=("Main Artist",),
                        parent_artist_ids=("artist-id",),
                    )
                ),
                "on_open": lambda self: None,
                "artist_for_album_view": SearchPanel.artist_for_album_view,
                "open_artist_albums": lambda self, artist_id, name: None,
            },
        )()

        SearchPanel.on_context_menu(panel)

        label, _callback = calls[0]["top_level_actions"][0]
        self.assertEqual(label, "Show albums by &Main Artist")

    def test_album_result_offers_to_open_primary_artists_albums(self):
        album = ui.SpotifyItem(
            "album",
            ui.ItemKind.ALBUM,
            "Album",
            raw={"artists": [{"id": "artist-id", "name": "Main Artist"}]},
        )
        panel = type(
            "Panel",
            (),
            {
                "history": ui.NavigationHistory(
                    ui.ViewState("Results", [album])
                )
            },
        )()

        self.assertEqual(
            SearchPanel.artist_for_album_view(panel, album),
            ("artist-id", "Main Artist"),
        )

    def test_track_search_result_offers_primary_artists_albums(self):
        track = ui.SpotifyItem(
            "track",
            ui.ItemKind.TRACK,
            "Song",
            raw={"artists": [{"id": "artist-id", "name": "Main Artist"}]},
        )
        panel = type(
            "Panel",
            (),
            {
                "history": ui.NavigationHistory(
                    ui.ViewState("Results", [track])
                )
            },
        )()

        self.assertEqual(
            SearchPanel.artist_for_album_view(panel, track),
            ("artist-id", "Main Artist"),
        )


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
        self.assertEqual(spoken, ["Loaded 1 additional result."])
        self.assertTrue(rendered[0][1])


class DiscoverPanelStub:
    """Drive NewMusicPanel rendering without constructing wx widgets."""

    apply_filter = ui.NewMusicPanel.apply_filter
    render_results = ui.NewMusicPanel.render_results
    result_status = ui.NewMusicPanel.result_status
    show_chart_items = ui.NewMusicPanel.show_chart_items

    def __init__(
        self,
        all_items: list | None = None,
        result_mode: str = "releases",
        pending_marker=None,
        filter_text: str = "",
    ) -> None:
        panel = self
        self.loading = True
        self.loaded_once = False
        self.title = "Discover"
        self.result_mode = result_mode
        self.chart_note = ""
        self.all_items = list(all_items or [])
        self.pending_marker = pending_marker
        self.sort_key = "original"
        self.sort_descending = False
        self.rendered: list = []
        self.selections: list[int] = []
        self.labels: list = []
        self.statuses: list[str] = []
        self.spoken: list[str] = []
        self.focused: list[bool] = []
        self.filter = type(
            "Filter",
            (),
            {"GetValue": lambda self: filter_text},
        )()
        self.items = type(
            "Items",
            (),
            {
                "items": list(self.all_items),
                "selected_item": lambda self: None,
                "set_items": lambda self, items, selected=0, labels=None: (
                    setattr(self, "items", list(items)),
                    panel.rendered.append(list(items)),
                    panel.selections.append(selected),
                    panel.labels.append(labels),
                ),
                "SetFocus": lambda self: panel.focused.append(True),
            },
        )()
        self.status = type(
            "Status",
            (),
            {"SetLabel": lambda self, label: panel.statuses.append(label)},
        )()
        self.frame = type(
            "Frame",
            (),
            {
                "update_title_for_page": lambda self, page, title: None,
                "say": lambda self, message: panel.spoken.append(message),
            },
        )()

    def last_rendered_ids(self) -> list[str]:
        return [item.id for item in self.rendered[-1]]


class NewMusicTests(unittest.TestCase):
    def test_successful_new_releases_search_focuses_results(self):
        panel = DiscoverPanelStub()
        album = ui.SpotifyItem(
            "apple:1",
            ui.ItemKind.ALBUM,
            "Album",
            raw={"unresolved": True},
        )

        panel.show_chart_items(
            ui.ChartResults([album], "au", 0.0, "new_releases", detail="Detail")
        )

        self.assertEqual(panel.focused, [True])
        self.assertEqual(panel.last_rendered_ids(), ["apple:1"])
        self.assertEqual(panel.all_items, [album])
        self.assertIn("Detail", panel.statuses[-1])

    def test_an_empty_new_releases_search_says_so_instead_of_focusing(self):
        panel = DiscoverPanelStub()

        panel.show_chart_items(
            ui.ChartResults([], "au", 0.0, "new_releases", detail="Detail")
        )

        self.assertEqual(panel.focused, [])
        self.assertEqual(panel.spoken, ["No matching releases were found."])

    def test_new_release_provenance_names_the_source_and_lookup_rule(self):
        note = ui.chart_provenance(
            ui.ChartResults(
                [],
                "au",
                1_790_000_000.0,
                "new_releases",
                detail="Country songs in Australia",
            )
        )

        self.assertTrue(note.startswith("Country songs in Australia, loaded "))
        self.assertIn("only when you play, queue or save them", note)

    def test_new_release_rows_come_from_apple_data_with_no_spotify_lookup(self):
        from blindspot.applemusic import ChartEntry, ChartFeed

        feed = ChartFeed(
            [
                ChartEntry(
                    "September Wind",
                    "John Williamson",
                    apple_id="6813307339",
                    url="https://music.apple.com/x",
                    release_date="2026-09-21T00:00:00Z",
                )
            ],
            "au",
            fetched_at=1_790_000_000.0,
        )
        calls = []
        frame = type(
            "Frame",
            (),
            {
                "applemusic": type(
                    "AppleMusic",
                    (),
                    {
                        "new_releases": lambda self, country, **kw: (
                            calls.append((country, kw)),
                            feed,
                        )[1]
                    },
                )(),
                "spotify": type("Spotify", (), {})(),
                "apple_release_rows": staticmethod(MainFrame.apple_release_rows),
            },
        )()

        by_keyword = MainFrame.new_release_results(
            frame, "AU", "songs", "", 30, "williamson"
        )
        by_genre = MainFrame.new_release_results(
            frame, "AU", "songs", "6", 30, ""
        )

        (row,) = by_keyword.items
        self.assertEqual(row.kind, ui.ItemKind.ALBUM)
        self.assertEqual(row.artist, "John Williamson")
        self.assertTrue(row.raw["unresolved"])
        self.assertEqual(row.raw["list_note"], "released 21 September 2026")
        self.assertEqual(by_genre.items[0].kind, ui.ItemKind.TRACK)
        self.assertIn("Country music songs in Australia", by_genre.detail)
        self.assertIn("released in the last 30 days", by_genre.detail)
        self.assertIn("matching williamson", by_keyword.detail)
        self.assertIn("released in the last 30 days", by_keyword.detail)
        self.assertEqual(calls[0][1]["keyword"], "williamson")
        self.assertEqual(calls[1][1]["genre"], "6")

    def test_chart_rows_are_built_from_apple_data_with_no_spotify_lookup(self):
        from blindspot.applemusic import ChartEntry, ChartFeed

        feed = ChartFeed(
            [
                ChartEntry(
                    "First",
                    "Artist One",
                    apple_id="111",
                    url="https://music.apple.com/1",
                    release_date="2025-10-17",
                ),
                ChartEntry("Second", "Artist Two"),
            ],
            "au",
            fetched_at=1_790_000_000.0,
        )
        requests = []
        spotify_calls = []
        frame = type(
            "Frame",
            (),
            {
                "applemusic": type(
                    "AppleMusic",
                    (),
                    {
                        "top_songs": lambda self, country, **kwargs: (
                            requests.append((country, kwargs)),
                            feed,
                        )[1],
                    },
                )(),
                "spotify": type(
                    "Spotify",
                    (),
                    {
                        "find_track": lambda self, *a: spotify_calls.append(a),
                    },
                )(),
            },
        )()

        result = MainFrame.chart_results(frame, "AU")

        self.assertEqual(requests, [("AU", {"limit": ui.CHART_SIZE})])
        self.assertEqual(ui.CHART_SIZE, 100)
        self.assertEqual(spotify_calls, [])
        self.assertEqual(result.country, "au")
        self.assertEqual(result.loaded_at, 1_790_000_000.0)
        first, second = result.items
        self.assertEqual((first.name, first.artist), ("First", "Artist One"))
        self.assertEqual(first.year, "2025")
        self.assertEqual(first.uri, "")
        self.assertTrue(first.raw["unresolved"])
        self.assertEqual(first.raw["list_note"], "chart rank 1")
        self.assertEqual(second.raw["list_note"], "chart rank 2")
        self.assertEqual(first.raw["chart_url"], "https://music.apple.com/1")
        self.assertNotEqual(first.id, second.id)
        self.assertIn("chart rank 1", first.accessible_label())

    def _chart_row(self, name="Song", artist="Artist", rank=1):
        return ui.SpotifyItem(
            f"apple:{rank}",
            ui.ItemKind.TRACK,
            name,
            artist=artist,
            raw={
                "unresolved": True,
                "list_note": f"chart rank {rank}",
                "chart_url": "https://music.apple.com/x",
            },
        )

    def _resolver_frame(self, results):
        """A frame whose run_task runs the worker inline, like a finished task."""
        said = []
        looked_up = []
        labels = []

        def find_track(self, name, artist):
            looked_up.append((name, artist))
            return results.get(name)

        def run_task(self, message, worker, success, **kwargs):
            labels.append(message)
            success(worker())

        frame = type(
            "Frame",
            (),
            {
                "spotify": type("Spotify", (), {"find_track": find_track})(),
                "run_task": run_task,
                "say": lambda self, message: said.append(message),
                "resolve_track_row": lambda self, row: MainFrame.resolve_track_row(
                    self, row
                ),
                "finish_resolve": lambda self, *args: MainFrame.finish_resolve(
                    self, *args
                ),
            },
        )()
        return frame, said, looked_up, labels

    def test_ordinary_items_pass_straight_through_without_a_lookup(self):
        frame, said, looked_up, _labels = self._resolver_frame({})
        real = ui.SpotifyItem("t", ui.ItemKind.TRACK, "T", uri="spotify:track:t")
        retried = []

        stopped = MainFrame.resolve_then(frame, [real], lambda: retried.append(1))

        self.assertFalse(stopped)
        self.assertEqual((looked_up, retried, said), ([], [], []))

    def test_acting_on_a_chart_row_looks_it_up_fills_it_in_place_and_retries(self):
        real = ui.SpotifyItem(
            "spotify-id",
            ui.ItemKind.TRACK,
            "Song",
            artist="Artist",
            album="Album",
            duration_ms=200_000,
            year="2025",
            uri="spotify:track:spotify-id",
            raw={"images": ["x"]},
        )
        frame, said, looked_up, labels = self._resolver_frame({"Song": real})
        row = self._chart_row()
        retried = []

        stopped = MainFrame.resolve_then(
            frame, [row], lambda: retried.append(row.uri)
        )

        self.assertTrue(stopped)
        self.assertEqual(looked_up, [("Song", "Artist")])
        self.assertEqual(labels, ["Finding Song on Spotify"])
        # The very same object now carries the Spotify details.
        self.assertEqual(row.uri, "spotify:track:spotify-id")
        self.assertEqual(row.duration_ms, 200_000)
        self.assertEqual(row.album, "Album")
        self.assertNotIn("unresolved", row.raw)
        self.assertEqual(row.raw["list_note"], "chart rank 1")
        self.assertEqual(row.raw["images"], ["x"])
        self.assertEqual(retried, ["spotify:track:spotify-id"])
        self.assertEqual(said, [])
        # A second action needs no further lookup.
        self.assertFalse(MainFrame.resolve_then(frame, [row], lambda: None))
        self.assertEqual(len(looked_up), 1)

    def test_a_resolved_row_keeps_its_artist_first_wording(self):
        row = ui.SpotifyItem(
            "musicbrainz:1",
            ui.ItemKind.TRACK,
            "Song",
            artist="Cover Artist",
            raw={"unresolved": True, "artist_first": True, "list_note": "cover"},
        )
        real = ui.SpotifyItem(
            "r",
            ui.ItemKind.TRACK,
            "Song",
            artist="Cover Artist",
            duration_ms=200_000,
            uri="spotify:track:r",
        )

        ui.apply_resolved_row(row, real)

        self.assertTrue(row.raw["artist_first"])
        self.assertTrue(row.accessible_label().startswith("Cover Artist — Song"))

    def test_a_song_spotify_lacks_is_announced_once_and_not_retried(self):
        frame, said, looked_up, _labels = self._resolver_frame({})
        row = self._chart_row("Ghost", "Nobody")
        retried = []

        first = MainFrame.resolve_then(frame, [row], lambda: retried.append(1))
        second = MainFrame.resolve_then(frame, [row], lambda: retried.append(1))

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertEqual(retried, [])
        self.assertEqual(looked_up, [("Ghost", "Nobody")])
        self.assertEqual(
            said,
            ["Ghost by Nobody was not found on Spotify."] * 2,
        )
        self.assertTrue(row.raw["spotify_missing"])

    def test_a_multi_selection_resolves_each_row_and_reports_the_missing_ones(self):
        good = ui.SpotifyItem("g", ui.ItemKind.TRACK, "Good", uri="spotify:track:g")
        frame, said, looked_up, labels = self._resolver_frame({"Good": good})
        rows = [self._chart_row("Good", rank=1), self._chart_row("Gone", rank=2)]
        retried = []

        MainFrame.resolve_then(frame, rows, lambda: retried.append(1))

        self.assertEqual(labels, ["Finding 2 songs on Spotify"])
        self.assertEqual([name for name, _artist in looked_up], ["Good", "Gone"])
        self.assertEqual(rows[0].uri, "spotify:track:g")
        self.assertEqual(rows[1].uri, "")
        self.assertEqual(said, ["Gone by Artist was not found on Spotify."])
        self.assertEqual(retried, [1])

    def test_a_lookup_failure_propagates_so_a_rate_limit_is_shown_not_hidden(self):
        from blindspot.spotify import SpotifyError

        def find_track(self, name, artist):
            raise SpotifyError("limited", status=429, retry_after=600)

        frame = type(
            "Frame",
            (),
            {"spotify": type("Spotify", (), {"find_track": find_track})()},
        )()

        with self.assertRaises(SpotifyError):
            MainFrame.resolve_track_row(frame, self._chart_row())

    def _acting_frame(self, real):
        looked_up = []
        acted = []
        frame = type(
            "Frame",
            (),
            {
                "resolve_then": lambda self, items, retry: MainFrame.resolve_then(
                    self, items, retry
                ),
                "spotify": type(
                    "Spotify",
                    (),
                    {"find_track": lambda self, n, a: looked_up.append(n) or real},
                )(),
                "run_task": lambda self, message, worker, success, **kw: success(
                    worker()
                ),
                "say": lambda self, message: None,
                "resolve_track_row": lambda self, row: MainFrame.resolve_track_row(
                    self, row
                ),
                "finish_resolve": lambda self, *args: MainFrame.finish_resolve(
                    self, *args
                ),
                "toggle_like_item": lambda self, item: MainFrame.toggle_like_item(
                    self, item
                ),
                "queue_selected": lambda self, item: MainFrame.queue_selected(
                    self, item
                ),
                "queue_should_be_deferred": lambda self: True,
                "deferred_queue_items": acted,
                "finish_queue": lambda self, item: None,
            },
        )()
        return frame, looked_up, acted

    def test_queueing_a_chart_row_resolves_it_then_queues_the_spotify_track(self):
        real = ui.SpotifyItem(
            "r", ui.ItemKind.TRACK, "Song", uri="spotify:track:r"
        )
        frame, looked_up, acted = self._acting_frame(real)
        row = self._chart_row()

        MainFrame.queue_selected(frame, row)

        self.assertEqual(looked_up, ["Song"])
        self.assertEqual(acted, [row])
        self.assertEqual(row.uri, "spotify:track:r")

    def test_liking_a_chart_row_resolves_it_first(self):
        real = ui.SpotifyItem("r", ui.ItemKind.TRACK, "Song", uri="spotify:track:r")
        frame, looked_up, _acted = self._acting_frame(real)
        saved = []
        frame.spotify.toggle_saved = lambda item: saved.append(item.uri) or True
        frame.finish_toggle_like = lambda item, state: None
        row = self._chart_row()

        MainFrame.toggle_like_item(frame, row)

        self.assertEqual(looked_up, ["Song"])
        self.assertEqual(saved, ["spotify:track:r"])

    def test_opening_a_chart_row_from_the_list_resolves_before_playing(self):
        row = self._chart_row()
        seen = []
        panel = type(
            "Panel",
            (),
            {
                "on_open": lambda self: None,
                "items": type(
                    "Items", (), {"selected_item": lambda self: row}
                )(),
                "frame": type(
                    "Frame",
                    (),
                    {
                        "resolve_then": lambda self, items, retry: (
                            seen.append(items),
                            True,
                        )[1],
                    },
                )(),
            },
        )()

        ui.NewMusicPanel.on_open(panel)

        self.assertEqual(seen, [[row]])

    def test_chart_view_reports_entries_and_uses_default_labels(self):
        panel = DiscoverPanelStub()
        track = ui.SpotifyItem(
            "track",
            ui.ItemKind.TRACK,
            "Track",
            artist="Artist",
            raw={"list_note": "chart rank 1"},
        )

        panel.show_chart_items(ui.ChartResults([track], "au", 0.0))

        self.assertEqual(panel.result_mode, "chart")
        self.assertIsNone(panel.pending_marker)
        self.assertIsNone(panel.labels[-1])
        self.assertTrue(panel.statuses[-1].startswith("1 chart entry."))
        self.assertIn("Australia", panel.statuses[-1])

    def test_chart_provenance_names_source_country_and_limits(self):
        note = ui.chart_provenance(
            ui.ChartResults([], "pl", 1_790_000_000.0)
        )

        self.assertIn("Most played on Apple Music in Poland", note)
        self.assertIn(", loaded ", note)
        self.assertIn("2026", note)
        self.assertIn("rank only", note)
        self.assertIn(
            "no play counts, reporting period or measurement time",
            note,
        )
        # Apple's own timestamp must never be presented as data freshness.
        self.assertNotIn("updated", note)
        self.assertIn("only when you play, queue or save them", note)

    def _country_panel(self, *, touched=False, resolved=False, connected=True):
        chosen = []
        tasks = []
        panel = type(
            "Panel",
            (),
            {
                "country_touched": touched,
                "country_resolved": resolved,
                "chart_country": type(
                    "Country",
                    (),
                    {"SetSelection": lambda self, index: chosen.append(index)},
                )(),
                "frame": type(
                    "Frame",
                    (),
                    {
                        "spotify": type(
                            "Spotify",
                            (),
                            {"account_country": lambda self: "PL"},
                        )(),
                        "run_task": lambda self, message, worker, success, **kw: (
                            tasks.append((message, worker, success, kw))
                        ),
                    },
                )(),
            },
        )()
        panel.apply_account_country = (
            lambda code: ui.NewMusicPanel.apply_account_country(panel, code)
        )
        panel.forget_country_resolution = (
            lambda: ui.NewMusicPanel.forget_country_resolution(panel)
        )
        return panel, chosen, tasks

    def test_account_country_preselects_the_matching_storefront(self):
        panel, chosen, _tasks = self._country_panel()

        ui.NewMusicPanel.apply_account_country(panel, "pl")

        self.assertEqual(
            ui.CHART_COUNTRIES[chosen[0]][0],
            "PL",
        )

    def test_account_country_never_overrides_an_explicit_choice(self):
        panel, chosen, _tasks = self._country_panel(touched=True)

        ui.NewMusicPanel.apply_account_country(panel, "PL")

        self.assertEqual(chosen, [])

    def test_unsupported_account_country_leaves_the_default_alone(self):
        panel, chosen, _tasks = self._country_panel()

        ui.NewMusicPanel.apply_account_country(panel, "EE")
        ui.NewMusicPanel.apply_account_country(panel, "")

        self.assertEqual(chosen, [])

    def test_account_country_is_looked_up_once_and_silently(self):
        panel, _chosen, tasks = self._country_panel()

        ui.NewMusicPanel.resolve_account_country(panel)
        ui.NewMusicPanel.resolve_account_country(panel)

        self.assertEqual(len(tasks), 1)
        self.assertIsNone(tasks[0][0])

    def test_account_country_lookup_is_retried_after_a_failure(self):
        panel, _chosen, tasks = self._country_panel()

        ui.NewMusicPanel.resolve_account_country(panel)
        tasks[0][3]["failure"]()
        ui.NewMusicPanel.resolve_account_country(panel)

        self.assertEqual(len(tasks), 2)

    def test_choosing_a_country_marks_it_as_an_explicit_choice(self):
        panel = type("Panel", (), {"country_touched": False})()

        ui.NewMusicPanel.on_country_chosen(panel)

        self.assertTrue(panel.country_touched)

    def _genre_frame(self):
        calls = {"tasks": [], "said": [], "tag_search": []}
        selections = []
        values = {}
        frame = type(
            "Frame",
            (),
            {
                "lastfm": type(
                    "Lastfm",
                    (),
                    {
                        "top_genre_tags": lambda self, kind, name, artist="": (
                            calls.setdefault("tag_call", (kind, name, artist))
                        ),
                    },
                )(),
                "run_task": lambda self, message, worker, success, **kw: (
                    calls["tasks"].append((message, worker, success))
                ),
                "say": lambda self, message: calls["said"].append(message),
                "notebook": type(
                    "Notebook",
                    (),
                    {"SetSelection": lambda self, page: selections.append(page)},
                )(),
                "search": type(
                    "Search",
                    (),
                    {
                        "query": type(
                            "Query",
                            (),
                            {"SetValue": lambda self, v: values.update(query=v)},
                        )(),
                        "tag": type(
                            "Tag",
                            (),
                            {"SetValue": lambda self, v: values.update(tag=v)},
                        )(),
                        "categories": type(
                            "Categories",
                            (),
                            {
                                "SetSelection": lambda self, i: values.update(
                                    category=i
                                )
                            },
                        )(),
                        "show_tag_search": lambda self, *args: (
                            calls["tag_search"].append(args)
                        ),
                    },
                )(),
            },
        )()
        return frame, calls, selections, values

    def test_browse_genres_asks_for_the_primary_artist_of_a_track(self):
        frame, calls, _selections, _values = self._genre_frame()
        track = ui.SpotifyItem(
            "t", ui.ItemKind.TRACK, "Creep", artist="Radiohead, Guest"
        )

        MainFrame.browse_genres_for(frame, track)
        message, worker, _success = calls["tasks"][0]
        worker()

        self.assertIn("Creep", message)
        self.assertEqual(calls["tag_call"], ("track", "Creep", "Radiohead"))

    def test_browse_genres_for_an_artist_sends_no_track_artist(self):
        frame, calls, _selections, _values = self._genre_frame()
        artist = ui.SpotifyItem("a", ui.ItemKind.ARTIST, "Olivia Dean")

        MainFrame.browse_genres_for(frame, artist)
        calls["tasks"][0][1]()

        self.assertEqual(calls["tag_call"], ("artist", "Olivia Dean", ""))

    def test_no_genre_tags_is_announced_rather_than_showing_an_empty_dialog(self):
        frame, calls, _selections, _values = self._genre_frame()
        track = ui.SpotifyItem("t", ui.ItemKind.TRACK, "Obscure")

        MainFrame.choose_genre(frame, track, "track", [])

        self.assertEqual(calls["said"], ["Last.fm has no genre tags for Obscure."])
        self.assertEqual(calls["tasks"], [])

    def test_chosen_genre_opens_as_the_search_tabs_own_genre_view(self):
        frame, calls, selections, values = self._genre_frame()
        items = [ui.SpotifyItem("x", ui.ItemKind.ARTIST, "X")]

        MainFrame.finish_browse_genre(frame, "polish jazz", "artist", items)

        self.assertEqual(selections, [0])
        self.assertEqual(values["tag"], "polish jazz")
        self.assertEqual(values["query"], "")
        self.assertEqual(values["category"], ui.SEARCH_TYPES.index("artist"))
        self.assertEqual(
            calls["tag_search"],
            [("", "polish jazz", "artist", items)],
        )

    def test_discover_source_enables_only_the_relevant_control(self):
        enabled = {
            "release_types": [],
            "genre": [],
            "release_window": [],
            "keyword": [],
            "chart_country": [],
            "chart_date": [],
        }

        def control(name):
            return type(
                "Control",
                (),
                {"Enable": lambda self, value: enabled[name].append(value)},
            )()

        panel = type(
            "Panel",
            (),
            {
                "discovery_source": type(
                    "Source",
                    (),
                    {"GetSelection": lambda self: self.selection},
                )(),
                "release_types": control("release_types"),
                "genre": control("genre"),
                "release_window": control("release_window"),
                "keyword": control("keyword"),
                "chart_country": control("chart_country"),
                "chart_date": control("chart_date"),
                "source": lambda self: ui.NewMusicPanel.source(self),
            },
        )()

        for selection in range(4):
            panel.discovery_source.selection = selection
            ui.NewMusicPanel.update_source_controls(panel)

        # New releases, Followed artists and authors, Top charts, Historical.
        for name in ("genre", "keyword"):
            self.assertEqual(enabled[name], [True, False, False, False])
        self.assertEqual(enabled["release_types"], [True, False, True, False])
        self.assertEqual(enabled["release_window"], [True, True, False, False])
        self.assertEqual(enabled["chart_country"], [True, True, True, False])
        self.assertEqual(enabled["chart_date"], [False, False, False, True])

    def test_chart_country_choice_maps_back_to_a_storefront_code(self):
        panel = type(
            "Panel",
            (),
            {
                "chart_country": type(
                    "Country",
                    (),
                    {
                        "GetSelection": lambda self: next(
                            index
                            for index, (code, _name) in enumerate(
                                ui.CHART_COUNTRIES
                            )
                            if code == "GB"
                        )
                    },
                )(),
            },
        )()

        self.assertEqual(ui.NewMusicPanel.chart_country_code(panel), "GB")

    def test_historical_chart_date_accepts_compact_and_iso_formats(self):
        self.assertEqual(ui.parse_chart_date("19800105"), ui.date(1980, 1, 5))
        self.assertEqual(ui.parse_chart_date("1980-01-05"), ui.date(1980, 1, 5))

    def test_recently_played_preserves_spotify_order(self):
        spotify_items = [
            ui.SpotifyItem("newest", ui.ItemKind.TRACK, "Newest"),
            ui.SpotifyItem("older", ui.ItemKind.TRACK, "Older"),
        ]
        frame = type(
            "Frame",
            (),
            {
                "spotify": type(
                    "Spotify",
                    (),
                    {"recently_played": lambda self: spotify_items},
                )(),
            },
        )()

        items = MainFrame.load_recently_played(frame)

        self.assertIs(items, spotify_items)


class ExportAndDiagnosticsWiringTests(unittest.TestCase):
    def _frame(self, **attributes):
        said = []
        errors = []
        base = {
            "say": lambda self, message: said.append(message),
            "show_error": lambda self, message: errors.append(message),
        }
        base.update(attributes)
        frame = type("Frame", (), base)()
        return frame, said, errors

    def _track(self, number=1):
        return ui.SpotifyItem(
            f"t{number}",
            ui.ItemKind.TRACK,
            f"Song {number}",
            artist="Artist",
            uri=f"spotify:track:t{number}",
        )

    def _item_list(self, items, selected=None):
        return type(
            "ItemList",
            (),
            {
                "items": items,
                "selected_item": lambda self: selected,
            },
        )()

    # ---------------------------------------------------------- export command
    def test_export_command_exports_the_tracks_in_the_current_list(self):
        exported = []
        tracks = [self._track(1), self._track(2)]
        frame, _said, _errors = self._frame(
            current_item_list=lambda self: self._list,
            current_view_name=lambda self: "Liked Songs",
            export_items=lambda self, name, items: exported.append((name, items)),
        )
        frame._list = self._item_list(tracks)

        MainFrame.export_list_command(frame)

        self.assertEqual(exported, [("Liked Songs", tracks)])

    def test_export_command_loads_a_selected_playlist_when_the_list_has_no_tracks(self):
        playlist = ui.SpotifyItem("p", ui.ItemKind.PLAYLIST, "Road trip", uri="spotify:playlist:p")
        exported = []
        loaded = []
        tasks = []
        frame, _said, _errors = self._frame(
            current_item_list=lambda self: self._list,
            current_view_name=lambda self: "Playlists",
            export_items=lambda self, name, items: exported.append((name, items)),
            spotify=type(
                "Spotify",
                (),
                {"children": lambda self, item: loaded.append(item) or [self._t]},
            )(),
            run_task=lambda self, message, worker, success, **kw: (
                tasks.append(message),
                success(worker()),
            ),
        )
        frame._list = self._item_list([playlist], selected=playlist)
        frame.spotify._t = self._track()

        MainFrame.export_list_command(frame)

        self.assertEqual(loaded, [playlist])
        self.assertEqual(tasks, ["Loading Road trip to export"])
        self.assertEqual(exported[0][0], "Road trip")

    def test_export_command_explains_when_there_is_nothing_to_export(self):
        artist = ui.SpotifyItem("a", ui.ItemKind.ARTIST, "Someone")
        frame, said, _errors = self._frame(
            current_item_list=lambda self: self._list,
            current_view_name=lambda self: "Search",
        )
        frame._list = self._item_list([artist], selected=artist)

        MainFrame.export_list_command(frame)

        self.assertEqual(said, [ui.msg.NOTHING_TO_EXPORT])

    def test_export_command_without_a_list_says_so(self):
        frame, said, _errors = self._frame(current_item_list=lambda self: None)

        MainFrame.export_list_command(frame)

        self.assertEqual(said, [ui.msg.NOTHING_TO_EXPORT])

    # ------------------------------------------------------------ export_items
    def _dialog(self, path, result=None, filter_index=0):
        result = ui.wx.ID_OK if result is None else result

        class FakeDialog:
            def __init__(self, *args, **kwargs):
                self.kwargs = kwargs

            def ShowModal(self):
                return result

            def GetPath(self):
                return str(path)

            def GetFilterIndex(self):
                return filter_index

            def Destroy(self):
                pass

        return FakeDialog

    def test_export_items_writes_the_chosen_file_and_announces_the_count(self):
        import tempfile
        from pathlib import Path

        frame, said, errors = self._frame()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "out.csv"
            with patch("blindspot.ui.wx.FileDialog", self._dialog(target)):
                MainFrame.export_items(frame, "My list", [self._track(1), self._track(2)])

            self.assertTrue(target.exists())
            self.assertIn("Song 2", target.read_text(encoding="utf-8-sig"))

        self.assertEqual(errors, [])
        self.assertEqual(said, ["Exported 2 items to out.csv."])

    def test_export_items_adds_the_extension_from_the_chosen_filter(self):
        import tempfile
        from pathlib import Path

        frame, said, _errors = self._frame()
        with tempfile.TemporaryDirectory() as folder:
            bare = Path(folder) / "bare"
            with patch("blindspot.ui.wx.FileDialog", self._dialog(bare, filter_index=1)):
                MainFrame.export_items(frame, "L", [self._track(1)])

            self.assertTrue((Path(folder) / "bare.csv").exists())

        self.assertIn("bare.csv", said[0])

    def test_export_items_warns_when_the_list_was_only_partly_loaded(self):
        import tempfile
        from pathlib import Path

        more = ui.SpotifyItem("m", ui.ItemKind.HEADING, "Load more", raw={"load_more": True})
        frame, said, _errors = self._frame()
        with tempfile.TemporaryDirectory() as folder:
            with patch(
                "blindspot.ui.wx.FileDialog",
                self._dialog(Path(folder) / "p.txt"),
            ):
                MainFrame.export_items(frame, "L", [self._track(1), more])

        self.assertIn("partial list", said[0])

    def test_cancelling_the_file_dialog_writes_nothing(self):
        import tempfile
        from pathlib import Path

        frame, said, errors = self._frame()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "never.txt"
            with patch(
                "blindspot.ui.wx.FileDialog",
                self._dialog(target, result=ui.wx.ID_CANCEL),
            ):
                MainFrame.export_items(frame, "L", [self._track(1)])

            self.assertFalse(target.exists())

        self.assertEqual((said, errors), ([], []))

    def test_a_write_failure_is_reported_as_an_error(self):
        frame, said, errors = self._frame()
        with patch(
            "blindspot.ui.wx.FileDialog",
            self._dialog("/no/such/folder/x.txt"),
        ):
            MainFrame.export_items(frame, "L", [self._track(1)])

        self.assertEqual(said, [])
        self.assertTrue(errors[0].startswith("The file could not be saved"))

    def test_nothing_exportable_never_opens_a_file_dialog(self):
        frame, said, _errors = self._frame()
        artist = ui.SpotifyItem("a", ui.ItemKind.ARTIST, "Someone")

        with patch("blindspot.ui.wx.FileDialog") as dialog:
            MainFrame.export_items(frame, "L", [artist])

        dialog.assert_not_called()
        self.assertEqual(said, [ui.msg.NOTHING_TO_EXPORT])

    # ----------------------------------------------------------- error details
    def test_show_error_records_a_message_only_error_and_offers_copying(self):
        shown = []

        class FakeErrorDialog:
            def __init__(self, parent, message, on_copy):
                shown.append((message, on_copy))

            def ShowModal(self):
                pass

            def Destroy(self):
                pass

        frame, said, _errors = self._frame(
            last_error=None,
            copy_error_details=lambda self: None,
        )
        with patch("blindspot.ui.ErrorDialog", FakeErrorDialog):
            MainFrame.show_error(frame, "Something went wrong")

        self.assertEqual(said, ["Something went wrong"])
        self.assertEqual(frame.last_error.message, "Something went wrong")
        self.assertEqual(shown[0][0], "Something went wrong")

    def test_show_error_keeps_the_richer_record_when_the_message_matches(self):
        from blindspot.diagnostics import ErrorDetails

        richer = ErrorDetails("Same", error_type="x.Error", traceback="Traceback...")

        class FakeErrorDialog:
            def __init__(self, *args):
                pass

            def ShowModal(self):
                pass

            def Destroy(self):
                pass

        frame, _said, _errors = self._frame(
            last_error=richer,
            copy_error_details=lambda self: None,
        )
        with patch("blindspot.ui.ErrorDialog", FakeErrorDialog):
            MainFrame.show_error(frame, "Same")

        self.assertIs(frame.last_error, richer)

    def test_copy_error_details_with_no_error_says_so(self):
        frame, said, _errors = self._frame(last_error=None)

        MainFrame.copy_error_details(frame)

        self.assertEqual(said, [ui.msg.NO_ERROR_TO_COPY])

    def test_copy_error_details_copies_a_redacted_report(self):
        from blindspot.diagnostics import ErrorDetails

        secret = "TOPSECRETKEY123456"
        frame, said, _errors = self._frame(
            last_error=ErrorDetails(f"failed using {secret}", task="Loading chart"),
            known_secrets=lambda self: [secret],
            copy_text=lambda self, text, done: (
                copied.append(text),
                said.append(done),
            ),
        )
        copied = []

        MainFrame.copy_error_details(frame)

        self.assertIn("Loading chart", copied[0])
        self.assertNotIn(secret, copied[0])
        self.assertEqual(said, [ui.msg.ERROR_DETAILS_COPIED])

    def test_copy_text_reports_an_unavailable_clipboard(self):
        frame, said, _errors = self._frame()

        with patch("blindspot.ui.copy_to_clipboard", return_value=False):
            MainFrame.copy_text(frame, "text", "done")
        with patch("blindspot.ui.copy_to_clipboard", return_value=True):
            MainFrame.copy_text(frame, "text", "done")

        self.assertEqual(said, [ui.msg.CLIPBOARD_UNAVAILABLE, "done"])

    def test_known_secrets_gathers_every_credential(self):
        store = type(
            "Store",
            (),
            {
                "read": lambda self, name, default=None: {
                    "ticketmaster_api_key": "TM-KEY-1",
                    "lastfm_api_key": "LFM-KEY-2",
                }
            },
        )()
        spotify = type(
            "Spotify",
            (),
            {
                "token": {
                    "access_token": "ACCESS-3",
                    "refresh_token": "REFRESH-4",
                    "client_id": "CLIENT-5",
                }
            },
        )()
        frame, _said, _errors = self._frame(store=store, spotify=spotify)

        secrets = MainFrame.known_secrets(frame)

        self.assertEqual(
            sorted(secrets),
            ["ACCESS-3", "CLIENT-5", "LFM-KEY-2", "REFRESH-4", "TM-KEY-1"],
        )

    # ------------------------------------------------------ diagnostic report
    def _diagnostic_frame(self, folder, settings, token=None, connected=True):
        from pathlib import Path

        store = type(
            "Store",
            (),
            {
                "root": Path(folder),
                "read": lambda self, name, default=None: settings,
            },
        )()
        spotify = type(
            "Spotify",
            (),
            {"token": token or {}, "connected": connected},
        )()
        frame, _said, _errors = self._frame(
            store=store,
            spotify=spotify,
            last_error=None,
            known_secrets=lambda self: MainFrame.known_secrets(self),
        )
        return frame

    def test_diagnostic_text_leaves_the_log_out_by_default(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "blindspot.log").write_text(
                "Opening kind=album id=abc name='Private Album'\n",
                encoding="utf-8",
            )
            frame = self._diagnostic_frame(folder, {"logging_level": "Debug"})

            report = MainFrame.diagnostic_text(frame, False, False)

        self.assertIn("Log: not included.", report)
        self.assertNotIn("Private Album", report)

    def test_diagnostic_text_includes_the_log_with_names_hidden_on_request(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "blindspot.log").write_text(
                "Opening kind=album id=abc name='Private Album'\n",
                encoding="utf-8",
            )
            frame = self._diagnostic_frame(folder, {"logging_level": "Debug"})

            hidden = MainFrame.diagnostic_text(frame, True, False)
            shown = MainFrame.diagnostic_text(frame, True, True)

        self.assertIn("id=abc", hidden)
        self.assertNotIn("Private Album", hidden)
        self.assertIn("Private Album", shown)

    def test_diagnostic_text_never_contains_a_stored_credential(self):
        import tempfile
        from pathlib import Path

        settings = {
            "logging_level": "Debug",
            "ticketmaster_api_key": "TM-KEY-VALUE-123",
            "lastfm_api_key": "LFM-KEY-VALUE-456",
        }
        token = {
            "access_token": "ACCESS-VALUE-789",
            "refresh_token": "REFRESH-VALUE-000",
            "client_id": "CLIENT-VALUE-111",
        }
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "blindspot.log").write_text(
                "\n".join(f"used {value}" for value in [*settings.values(), *token.values()]),
                encoding="utf-8",
            )
            frame = self._diagnostic_frame(folder, settings, token)

            report = MainFrame.diagnostic_text(frame, True, True)

        for secret in ("TM-KEY-VALUE-123", "LFM-KEY-VALUE-456", "ACCESS-VALUE-789",
                       "REFRESH-VALUE-000", "CLIENT-VALUE-111"):
            self.assertNotIn(secret, report)
        self.assertIn("Ticketmaster key: set", report)
        self.assertIn("Last.fm key: custom", report)
        self.assertIn("Spotify client ID: set", report)

    def test_diagnostic_text_explains_logging_that_is_switched_off(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            frame = self._diagnostic_frame(folder, {}, connected=False)

            report = MainFrame.diagnostic_text(frame, True, False)

        self.assertIn("logging is switched off", report)
        self.assertIn("Spotify connected: no", report)
        self.assertIn("Last.fm key: built-in default", report)

    # ------------------------------------------------------------------ covers
    def _cover_results(self, count=2, examined=300, total=300):
        from blindspot.musicbrainz import Cover, CoverResults

        covers = [
            Cover(f"Hallelujah", f"Artist {n}", "2010", n % 2 == 0, f"id{n}")
            for n in range(count)
        ]
        return CoverResults(covers, "Hallelujah", total, examined)

    def test_find_covers_searches_with_a_clean_title_and_the_primary_artist(self):
        tasks = []
        searched = []
        frame, _said, _errors = self._frame(
            musicbrainz=type(
                "MusicBrainz",
                (),
                {
                    "find_covers": lambda self, t, a, d=0: searched.append(
                        (t, a, d)
                    )
                },
            )(),
            run_task=lambda self, message, worker, success, **kw: tasks.append(
                (message, worker)
            ),
        )
        track = ui.SpotifyItem(
            "t",
            ui.ItemKind.TRACK,
            "Hurt - Remastered 2011",
            artist="Nine Inch Nails, Guest",
            duration_ms=134_000,
        )

        MainFrame.find_covers_for(frame, track)
        tasks[0][1]()

        # The track's own length rides along to sanity-check same-title matches.
        self.assertEqual(searched, [("Hurt", "Nine Inch Nails", 134_000)])
        self.assertIn("MusicBrainz", tasks[0][0])
        self.assertIn("20 seconds", tasks[0][0])

    def test_covers_appear_as_unresolved_rows_with_a_note_and_a_summary(self):
        shown = []
        statuses = []
        frame, said, _errors = self._frame(
            show_lastfm_results=lambda self, title, rows: shown.append((title, rows)),
            search=type(
                "Search",
                (),
                {
                    "status": type(
                        "Status",
                        (),
                        {"SetLabel": lambda self, text: statuses.append(text)},
                    )()
                },
            )(),
        )
        source = ui.SpotifyItem(
            "t", ui.ItemKind.TRACK, "Hallelujah", artist="Leonard Cohen"
        )

        MainFrame.show_covers(frame, source, self._cover_results(2, 300, 514))

        title, rows = shown[0]
        self.assertEqual(title, "Covers of Hallelujah, provided by MusicBrainz")
        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertEqual((first.name, first.artist, first.year), ("Hallelujah", "Artist 0", "2010"))
        self.assertTrue(first.raw["unresolved"])
        self.assertEqual(first.uri, "")
        self.assertEqual(rows[0].raw["list_note"], "cover")
        # Versions of one song are told apart by the performer, so lead with it.
        self.assertEqual(rows[0].accessible_label(), "Artist 0 — Hallelujah — 2010 — cover")
        # Rows MusicBrainz does not mark as covers carry no commentary at all.
        self.assertNotIn("list_note", rows[1].raw)
        self.assertNotIn("cover", rows[1].accessible_label().casefold())
        self.assertNotIn("confirm", rows[1].accessible_label().casefold())
        self.assertIn("2 versions by 2 artists, from MusicBrainz.", statuses[0])
        self.assertIn("recordings by Leonard Cohen are left out", statuses[0])
        self.assertIn("Checked the first 300 of 514 recordings.", statuses[0])
        self.assertEqual(said, [])

    def test_a_complete_check_does_not_claim_it_was_cut_short(self):
        summary = ui.cover_summary(
            ui.SpotifyItem("t", ui.ItemKind.TRACK, "S", artist="A"),
            self._cover_results(1, 177, 177),
        )

        self.assertNotIn("Checked the first", summary)
        self.assertIn("1 version by 1 artist", summary)
        self.assertIn("looked up on Spotify only when you play", summary)

    def test_no_covers_is_announced_and_no_list_is_opened(self):
        shown = []
        frame, said, _errors = self._frame(
            show_lastfm_results=lambda self, title, rows: shown.append(title),
        )
        source = ui.SpotifyItem("t", ui.ItemKind.TRACK, "Obscure", artist="A")

        MainFrame.show_covers(frame, source, self._cover_results(0))

        self.assertEqual(shown, [])
        self.assertEqual(said, ["MusicBrainz lists no other studio versions of Obscure."])

    def test_a_song_musicbrainz_lacks_is_a_notice_not_an_error_report(self):
        from blindspot.musicbrainz import CoversUnavailable

        frame, errors = self._run_task_frame()
        said = []
        frame.say = lambda message: said.append(message)

        def worker():
            raise CoversUnavailable("MusicBrainz could not find X by Y.")

        with self.assertLogs("blindspot.ui", level="INFO"):
            self._run_inline(frame, worker, "Finding covers")

        self.assertEqual(errors, [])
        self.assertIsNone(frame.last_error)
        self.assertIn("MusicBrainz could not find X by Y.", said)

    def test_playing_a_cover_row_looks_it_up_on_spotify_first(self):
        real = ui.SpotifyItem("r", ui.ItemKind.TRACK, "Song", uri="spotify:track:r")
        row = ui.SpotifyItem(
            "musicbrainz:1",
            ui.ItemKind.TRACK,
            "Song",
            artist="Cover Artist",
            raw={"unresolved": True, "list_note": "cover"},
        )
        looked_up = []
        played = []
        frame, _said, _errors = self._frame(
            resolve_then=lambda self, items, retry: MainFrame.resolve_then(
                self, items, retry
            ),
            spotify=type(
                "Spotify",
                (),
                {"find_track": lambda self, n, a: looked_up.append((n, a)) or real},
            )(),
            run_task=lambda self, message, worker, success, **kw: success(worker()),
            resolve_track_row=lambda self, r: MainFrame.resolve_track_row(self, r),
            finish_resolve=lambda self, *args: MainFrame.finish_resolve(self, *args),
            play=lambda self, item: played.append(item.uri),
            play_playable_item=lambda self, item: MainFrame.play_playable_item(
                self, item
            ),
        )

        MainFrame.play_playable_item(frame, row)

        self.assertEqual(looked_up, [("Song", "Cover Artist")])
        self.assertEqual(played, ["spotify:track:r"])

    # ------------------------------------------- focus return from save dialogs
    def _capturing_file_dialog(self, result, path=""):
        parents = []

        class FakeDialog:
            def __init__(self, parent, *args, **kwargs):
                parents.append(parent)

            def ShowModal(self):
                return result

            def GetPath(self):
                return str(path)

            def Destroy(self):
                pass

        return FakeDialog, parents

    def test_the_save_dialog_is_a_child_of_the_diagnostic_dialog_that_opened_it(self):
        frame, _said, _errors = self._frame()
        diagnostic_dialog = object()
        fake, parents = self._capturing_file_dialog(ui.wx.ID_CANCEL)

        with patch("blindspot.ui.wx.FileDialog", fake):
            MainFrame.save_text_report(frame, "text", "name", diagnostic_dialog)

        self.assertEqual(parents, [diagnostic_dialog])

    def test_the_save_dialog_falls_back_to_the_main_window_without_a_parent(self):
        frame, _said, _errors = self._frame()
        fake, parents = self._capturing_file_dialog(ui.wx.ID_CANCEL)

        with patch("blindspot.ui.wx.FileDialog", fake):
            MainFrame.save_text_report(frame, "text", "name")

        self.assertEqual(parents, [frame])

    def test_a_save_failure_error_is_parented_to_the_diagnostic_dialog_too(self):
        parents = []
        frame, _said, _errors = self._frame()
        frame.show_error = lambda message, parent=None: parents.append(parent)
        diagnostic_dialog = object()
        fake, _ = self._capturing_file_dialog(
            ui.wx.ID_OK,
            "/no/such/folder/report.txt",
        )

        with patch("blindspot.ui.wx.FileDialog", fake):
            MainFrame.save_text_report(frame, "text", "name", diagnostic_dialog)

        self.assertEqual(parents, [diagnostic_dialog])

    def test_show_error_parents_its_dialog_to_the_window_that_asked(self):
        parents = []

        class FakeErrorDialog:
            def __init__(self, parent, message, on_copy):
                parents.append(parent)

            def ShowModal(self):
                pass

            def Destroy(self):
                pass

        frame, _said, _errors = self._frame(
            last_error=None,
            copy_error_details=lambda self: None,
        )
        asker = object()
        with patch("blindspot.ui.ErrorDialog", FakeErrorDialog):
            MainFrame.show_error(frame, "one", parent=asker)
            MainFrame.show_error(frame, "two")

        self.assertEqual(parents, [asker, frame])

    def test_the_diagnostic_dialog_passes_itself_to_save_and_refocuses_afterwards(self):
        events = []
        dialog = type(
            "Dialog",
            (),
            {
                "report": type(
                    "Report", (), {"GetValue": lambda self: "report text"}
                )(),
                "save_button": type(
                    "Button",
                    (),
                    {"SetFocus": lambda self: events.append("focus save button")},
                )(),
                "on_save": lambda self, parent, text: events.append(
                    ("save", parent is self, text)
                ),
            },
        )()

        ui.DiagnosticDialog.on_save_clicked(dialog)

        self.assertEqual(
            events,
            [("save", True, "report text"), "focus save button"],
        )

    # ---------------------------------------------------- run_task recording
    def _run_task_frame(self, connected=True):
        errors = []
        frame, said, _ = self._frame(
            spotify=type("Spotify", (), {"connected": connected})(),
            last_error=None,
            offer_permission_refresh=lambda self: None,
        )
        frame.show_error = lambda message: errors.append(message)
        return frame, errors

    def _run_inline(self, frame, worker, message="Doing a thing"):
        class InlineThread:
            def __init__(self, target, daemon=None):
                self.target = target

            def start(self):
                self.target()

        with (
            patch("blindspot.ui.threading.Thread", InlineThread),
            patch("blindspot.ui.wx.CallAfter", lambda function, *a: function(*a)),
        ):
            MainFrame.run_task(frame, message, worker, lambda result: None)

    def test_a_failed_task_records_type_traceback_and_what_it_was_doing(self):
        from blindspot.spotify import SpotifyError

        frame, errors = self._run_task_frame()

        def worker():
            raise SpotifyError("limited", status=429, retry_after=90)

        with self.assertLogs("blindspot.ui", level="ERROR"):
            self._run_inline(frame, worker, "Finding Song on Spotify")

        self.assertEqual(errors, ["limited"])
        self.assertEqual(frame.last_error.task, "Finding Song on Spotify")
        self.assertEqual(frame.last_error.status, 429)
        self.assertIn("Traceback", frame.last_error.traceback)

    def test_expected_unavailable_notices_are_not_recorded_as_errors(self):
        from blindspot.spotify import PlaylistContentsUnavailable

        frame, _errors = self._run_task_frame()

        def worker():
            raise PlaylistContentsUnavailable("not yours")

        self._run_inline(frame, worker)

        self.assertIsNone(frame.last_error)


class PodcastSupportTests(unittest.TestCase):
    def test_browse_category_displays_scoped_podcast_results(self):
        rendered = []
        status_labels = []
        show = ui.SpotifyItem("show", ui.ItemKind.SHOW, "Show")
        loader = ui.SpotifyItem(
            "__load_more__",
            ui.ItemKind.HEADING,
            "Show more podcasts",
            raw={"load_more": True, "next_offset": 50},
        )
        panel = type(
            "Panel",
            (),
            {
                "loading": True,
                "loaded_once": False,
                "history": ui.NavigationHistory(ui.ViewState("Podcasts", [])),
                "current_playlist": None,
                "status": type(
                    "Status",
                    (),
                    {"SetLabel": lambda self, label: status_labels.append(label)},
                )(),
                "render": lambda self, state, *, focus: rendered.append(state),
                "frame": type("Frame", (), {"say": lambda self, message: None})(),
            },
        )()

        PodcastsPanel.show_browse_results(
            panel,
            "Comedy",
            "comedy podcast",
            [show, loader],
        )

        self.assertEqual(rendered[0].title, "Browse podcasts: Comedy")
        self.assertEqual(rendered[0].query, "comedy podcast")
        self.assertEqual(rendered[0].category, "show")
        self.assertIn("Not a complete Spotify catalogue", status_labels[0])

    def test_more_browse_results_append_without_duplicates(self):
        first = ui.SpotifyItem("first", ui.ItemKind.SHOW, "First")
        duplicate = ui.SpotifyItem("first", ui.ItemKind.SHOW, "First")
        second = ui.SpotifyItem("second", ui.ItemKind.SHOW, "Second")
        loader = ui.SpotifyItem(
            "__load_more__",
            ui.ItemKind.HEADING,
            "Show more podcasts",
            raw={"load_more": True, "next_offset": 100},
        )
        state = ui.ViewState(
            "Browse podcasts: Comedy",
            [first],
            query="comedy podcast",
            category="show",
        )
        spoken = []
        panel = type(
            "Panel",
            (),
            {
                "loading": True,
                "history": ui.NavigationHistory(state),
                "status": type("Status", (), {"SetLabel": lambda self, label: None})(),
                "render": lambda self, value, *, focus: None,
                "frame": type(
                    "Frame",
                    (),
                    {"say": lambda self, message: spoken.append(message)},
                )(),
            },
        )()

        PodcastsPanel.append_browse_results(
            panel,
            state,
            [duplicate, second, loader],
        )

        self.assertEqual(
            [item.id for item in state.items],
            ["first", "second", "__load_more__"],
        )
        self.assertEqual(state.selected, 1)
        self.assertEqual(spoken, ["Loaded 1 additional podcast."])

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

    def test_discovered_show_context_menu_does_not_offer_unsubscribe(self):
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
                    ui.ViewState(
                        "Browse podcasts",
                        [show],
                        query="podcast",
                        category="show",
                    )
                ),
                "frame": type(
                    "Frame",
                    (),
                    {
                        "popup_item_menu": (
                            lambda self, owner, item, **options: calls.append(options)
                        )
                    },
                )(),
                "on_open": lambda self: None,
                "remove_saved_item": lambda self, item: None,
            },
        )()

        PodcastsPanel.on_context_menu(panel)

        self.assertIsNone(calls[0]["remove_callback"])

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

    def test_next_logs_cached_playback_diagnostics_without_extra_requests(self):
        current = ui.SpotifyItem("track", ui.ItemKind.TRACK, "Current song")
        calls = []
        spotify = type(
            "Spotify",
            (),
            {
                "next_track": lambda self, device_id: calls.append(device_id),
            },
        )()
        frame = type(
            "Frame",
            (),
            {
                "spotify": spotify,
                "current_player_item": current,
                "current_player_state": {
                    "context_uri": "spotify:playlist:list-1"
                },
                "repeat_state": "off",
                "shuffle_enabled": False,
                "run_task": lambda self, message, work, done: done(work()),
            },
        )()

        with self.assertLogs("blindspot.ui", level="INFO") as captured:
            MainFrame.send_next_track(frame, "device")

        self.assertEqual(calls, ["device"])
        diagnostic = captured.output[0]
        self.assertIn("current_id=track", diagnostic)
        self.assertIn("context=spotify:playlist:list-1", diagnostic)
        self.assertIn("repeat=off", diagnostic)
        self.assertIn("shuffle=False", diagnostic)

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

    def test_stale_player_update_does_not_trigger_redundant_lyric_seek(self):
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

        self.assertEqual(seeks, [])
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

    def test_manual_volume_adjustment_is_saved(self):
        messages = []
        with tempfile.TemporaryDirectory() as folder:
            store = ui.PortableStore(Path(folder))
            store.write("settings.json", {"unrelated": True})
            frame = type(
                "Frame",
                (),
                {
                    "store": store,
                    "playback_volume_percent": 80,
                    "volume_before_mute_percent": 80,
                    "say": lambda self, message: messages.append(message),
                },
            )()

            MainFrame.finish_adjust_volume(frame, 67)

            self.assertEqual(frame.playback_volume_percent, 67)
            self.assertEqual(frame.volume_before_mute_percent, 67)
            self.assertEqual(
                store.read("settings.json"),
                {"unrelated": True, "playback_volume_percent": 67},
            )
        self.assertEqual(messages, ["67%."])


class PlaybackFeedbackTests(unittest.TestCase):
    def test_pending_forced_transfer_does_not_retarget_transport_controls(self):
        frame = type(
            "Frame",
            (),
            {
                "pending_transfer_device": {
                    "id": "phone",
                    "name": "Phone",
                },
                "remote_device_id": "currently-active-device",
            },
        )()

        self.assertEqual(
            MainFrame.player_device_id(frame),
            "currently-active-device",
        )

    def test_pending_forced_transfer_targets_next_explicit_play(self):
        played_on = []
        item = type(
            "Item",
            (),
            {
                "id": "track",
                "name": "Song",
                "playable": True,
            },
        )()
        spotify = type(
            "Spotify",
            (),
            {
                "play": (
                    lambda self, value, device_id=None: played_on.append(
                        device_id
                    )
                ),
            },
        )()
        frame = type(
            "Frame",
            (),
            {
                "pending_transfer_device": {
                    "id": "phone",
                    "name": "Phone",
                },
                "remote_device_id": "currently-active-device",
                "spotify": spotify,
                "suppress_track_announcement_id": None,
                "run_task": (
                    lambda self, message, worker, success: success(worker())
                ),
                "on_play_started": (
                    lambda self, value, **options: None
                ),
            },
        )()

        MainFrame.play(frame, item)

        self.assertEqual(played_on, ["phone"])

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
                "resolve_then": lambda self, items, retry: False,
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
                "run_task": lambda self, message, worker, completed, **options: (
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
                "resolve_then": lambda self, items, retry: False,
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

    def test_failed_flush_does_not_requeue_items_spotify_already_accepted(self):
        items = [
            ui.SpotifyItem(
                name,
                ui.ItemKind.TRACK,
                name,
                uri=f"spotify:track:{name}",
            )
            for name in ("first", "second", "third")
        ]
        queued = []

        def add_to_queue(self, item, device_id):
            if item is items[2]:
                raise RuntimeError("Spotify said no")
            queued.append(item)

        def run_task(self, message, worker, success, failure=None, **options):
            try:
                worker()
            except RuntimeError:
                failure()
                return
            success(None)

        frame = type(
            "Frame",
            (),
            {
                "deferred_queue_items": list(items),
                "deferred_queue_flushing": False,
                "player_device_id": lambda self: "device",
                "spotify": type(
                    "Spotify", (), {"add_to_queue": add_to_queue}
                )(),
                "run_task": run_task,
            },
        )()

        MainFrame.flush_deferred_queue(frame)

        self.assertEqual(queued, [items[0], items[1]])
        self.assertEqual(frame.deferred_queue_items, [items[2]])
        self.assertFalse(frame.deferred_queue_flushing)

    def test_failed_flush_preserves_an_unaccepted_duplicate_occurrence(self):
        repeated = ui.SpotifyItem(
            "track",
            ui.ItemKind.TRACK,
            "Track",
            uri="spotify:track:track",
        )
        attempts = 0

        def add_to_queue(self, item, device_id):
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                raise RuntimeError("Spotify said no")

        def run_task(self, message, worker, success, failure=None, **options):
            try:
                worker()
            except RuntimeError:
                failure()
            else:
                success(None)

        frame = type(
            "Frame",
            (),
            {
                "deferred_queue_items": [repeated, repeated],
                "deferred_queue_flushing": False,
                "player_device_id": lambda self: "device",
                "spotify": type(
                    "Spotify", (), {"add_to_queue": add_to_queue}
                )(),
                "run_task": run_task,
            },
        )()

        MainFrame.flush_deferred_queue(frame)

        self.assertEqual(frame.deferred_queue_items, [repeated])
        self.assertFalse(frame.deferred_queue_flushing)

    def test_flush_keeps_items_queued_while_it_was_running(self):
        first = ui.SpotifyItem(
            "first", ui.ItemKind.TRACK, "First", uri="spotify:track:first"
        )
        late = ui.SpotifyItem(
            "late", ui.ItemKind.TRACK, "Late", uri="spotify:track:late"
        )
        deferred = [first]

        def add_to_queue(self, item, device_id):
            deferred.insert(0, late)  # user queues something mid-flush

        frame = type(
            "Frame",
            (),
            {
                "deferred_queue_items": deferred,
                "deferred_queue_flushing": False,
                "player_device_id": lambda self: "device",
                "spotify": type(
                    "Spotify", (), {"add_to_queue": add_to_queue}
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

        self.assertEqual(frame.deferred_queue_items, [late])

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
    def test_album_artwork_download_uses_bundled_certificate_store(self):
        response = Mock()
        response.read.return_value = b"image"
        response_context = Mock()
        response_context.__enter__ = Mock(return_value=response)
        response_context.__exit__ = Mock(return_value=False)

        with patch(
            "blindspot.ui.urllib.request.urlopen",
            return_value=response_context,
        ) as urlopen:
            result = ui.download_album_artwork("https://example.com/art.jpg")

        self.assertEqual(result, b"image")
        self.assertIs(urlopen.call_args.kwargs["context"], ui.TLS_CONTEXT)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 20)

    def test_album_artwork_url_selects_largest_available_image(self):
        album = ui.SpotifyItem(
            "album",
            ui.ItemKind.ALBUM,
            "Album",
            raw={
                "images": [
                    {"url": "small", "width": 64, "height": 64},
                    {"url": "large", "width": 640, "height": 640},
                    {"url": "medium", "width": 300, "height": 300},
                ]
            },
        )

        self.assertEqual(ui.album_artwork_url(album), "large")

    def test_album_artwork_url_is_empty_when_spotify_has_no_image(self):
        album = ui.SpotifyItem(
            "album",
            ui.ItemKind.ALBUM,
            "Album",
            raw={},
        )

        self.assertEqual(ui.album_artwork_url(album), "")

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
    def test_item_list_handles_select_all_before_panel_key_routing(self):
        selected = []
        announcements = []
        frame = type(
            "Frame",
            (),
            {"say": lambda self, value: announcements.append(value)},
        )()
        panel = type(
            "Panel",
            (),
            {
                "frame": frame,
                "on_item_list_char_hook": (
                    lambda self, event: self.fail(
                        "Select all must be handled by the list"
                    )
                ),
            },
        )()
        item_list = type(
            "ItemList",
            (),
            {
                "GetParent": lambda self: panel,
                "select_all_items": lambda self: selected.append(True),
                "GetSelections": lambda self: [0, 1, 2],
            },
        )()
        event = type(
            "Event",
            (),
            {
                "GetKeyCode": lambda self: ord("A"),
                "GetModifiers": lambda self: ui.wx.MOD_CONTROL,
                "ControlDown": lambda self: True,
                "AltDown": lambda self: False,
                "ShiftDown": lambda self: False,
            },
        )()

        with patch("blindspot.ui.sys.platform", "win32"):
            ui.ItemList.on_char_hook(item_list, event)

        self.assertEqual(selected, [True])
        self.assertEqual(announcements, ["3 items selected"])

    def test_item_list_routes_keys_to_alternate_dialog_before_main_frame(self):
        routed = []
        event = object()
        panel = type(
            "Panel",
            (),
            {
                "on_item_list_char_hook": (
                    lambda self, value: routed.append(value)
                ),
                "frame": type(
                    "Frame",
                    (),
                    {
                        "on_global_key": lambda self, value: self.fail(
                            "Main frame must not receive dialog keys"
                        )
                    },
                )(),
            },
        )()
        item_list = type(
            "ItemList",
            (),
            {"GetParent": lambda self: panel},
        )()

        ui.ItemList.on_char_hook(item_list, event)

        self.assertEqual(routed, [event])

    def test_alternate_versions_tab_moves_from_results_to_replace(self):
        focused = []

        class Control:
            def SetFocus(self):
                focused.append(self)

        items = Control()
        replace = Control()
        close = Control()
        dialog = type(
            "Dialog",
            (),
            {
                "items": items,
                "replace_button": replace,
                "close_button": close,
            },
        )()
        event = type(
            "Event",
            (),
            {
                "GetKeyCode": lambda self: ui.wx.WXK_TAB,
                "ControlDown": lambda self: False,
                "RawControlDown": lambda self: False,
                "AltDown": lambda self: False,
                "ShiftDown": lambda self: False,
            },
        )()

        with (
            patch("blindspot.ui.wx.Window.FindFocus", return_value=items),
            patch(
                "blindspot.ui.item_list_ancestor",
                return_value=items,
            ),
        ):
            AlternateVersionsDialog.on_key(dialog, event)

        self.assertEqual(focused, [replace])

    def test_backspace_closes_alternate_versions_dialog(self):
        closed = []
        dialog = type(
            "Dialog",
            (),
            {
                "IsModal": lambda self: True,
                "EndModal": lambda self, result: closed.append(result),
            },
        )()
        event = type(
            "Event",
            (),
            {
                "GetKeyCode": lambda self: ui.wx.WXK_BACK,
                "ControlDown": lambda self: False,
                "RawControlDown": lambda self: False,
                "AltDown": lambda self: False,
                "ShiftDown": lambda self: False,
            },
        )()

        AlternateVersionsDialog.on_key(dialog, event)

        self.assertEqual(closed, [ui.wx.ID_CLOSE])

    def test_alternate_replacement_refuses_duplicate_source_uri(self):
        messages = []
        original = ui.SpotifyItem(
            "source",
            ui.ItemKind.TRACK,
            "Song - Live",
            uri="spotify:track:source",
        )
        playlist = ui.SpotifyItem(
            "playlist",
            ui.ItemKind.PLAYLIST,
            "List",
            raw={"owned": True},
        )
        state = ui.ViewState("List", [original, original])
        panel = type(
            "Panel",
            (),
            {
                "current_playlist": playlist,
                "history": ui.NavigationHistory(state),
                "items": type(
                    "Items",
                    (),
                    {
                        "selected_item": lambda self: original,
                        "GetSelection": lambda self: 0,
                    },
                )(),
                "frame": type(
                    "Frame",
                    (),
                    {
                        "say": lambda self, message: messages.append(message),
                        "run_task": lambda *args, **kwargs: self.fail(
                            "Duplicate URI must not be searched"
                        ),
                    },
                )(),
            },
        )()

        PlaylistsPanel.find_alternate_versions(panel)

        self.assertEqual(
            messages,
            [ui.msg.DUPLICATE_PLAYLIST_REPLACEMENT],
        )

    def test_finished_alternate_replacement_keeps_playlist_position(self):
        original = ui.SpotifyItem(
            "source",
            ui.ItemKind.TRACK,
            "Song - Live",
            uri="spotify:track:source",
        )
        replacement = ui.SpotifyItem(
            "studio",
            ui.ItemKind.TRACK,
            "Song",
            uri="spotify:track:studio",
        )
        other = ui.SpotifyItem(
            "other",
            ui.ItemKind.TRACK,
            "Other",
        )
        messages = []
        closed = []

        class Items:
            def __init__(self):
                self.items = [other, original]

            def set_items(self, tracks, selected=0):
                self.items = list(tracks)
                self.selected = selected

            def SetFocus(self):
                pass

        state = ui.ViewState("List", [other, original])
        panel = type(
            "Panel",
            (),
            {
                "items": Items(),
                "history": ui.NavigationHistory(state),
                "frame": type(
                    "Frame",
                    (),
                    {"say": lambda self, message: messages.append(message)},
                )(),
            },
        )()
        dialog = type(
            "Dialog",
            (),
            {"finish_replace": lambda self: closed.append(True)},
        )()

        PlaylistsPanel.finish_replace_playlist_track(
            panel,
            1,
            replacement,
            dialog,
        )

        self.assertIs(state.items[1], replacement)
        self.assertEqual(state.selected, 1)
        self.assertEqual(panel.items.selected, 1)
        self.assertEqual(closed, [True])
        self.assertEqual(messages, [ui.msg.PLAYLIST_TRACK_REPLACED])

    def test_alternate_dialog_returns_focus_after_it_is_destroyed(self):
        original = ui.SpotifyItem(
            "source",
            ui.ItemKind.TRACK,
            "Song - Live",
        )
        candidate = ui.SpotifyItem(
            "studio",
            ui.ItemKind.TRACK,
            "Song",
        )
        playlist = ui.SpotifyItem(
            "playlist",
            ui.ItemKind.PLAYLIST,
            "List",
        )
        calls = []
        dialog = type(
            "Dialog",
            (),
            {
                "ShowModal": lambda self: calls.append("modal"),
                "Destroy": lambda self: calls.append("destroy"),
            },
        )()
        panel = type(
            "Panel",
            (),
            {
                "frame": object(),
                "current_playlist": playlist,
                "restore_playlist_item_focus": (
                    lambda self, source: calls.append(("focus", source))
                ),
                "replace_playlist_track": lambda *args: None,
            },
        )()

        with (
            patch(
                "blindspot.ui.AlternateVersionsDialog",
                return_value=dialog,
            ),
            patch(
                "blindspot.ui.wx.CallAfter",
                side_effect=lambda callback, *args: callback(*args),
            ),
        ):
            PlaylistsPanel.show_alternate_versions(
                panel,
                playlist,
                original,
                12,
                [candidate],
            )

        self.assertEqual(
            calls,
            ["modal", "destroy", ("focus", 12)],
        )

    def test_owned_playlist_move_menu_offers_accessible_destinations(self):
        tracks = [object(), object(), object()]
        panel = type(
            "Panel",
            (),
            {
                "items": type(
                    "Items",
                    (),
                    {
                        "items": tracks,
                        "GetSelection": lambda self: 1,
                    },
                )(),
                "move_selected_to_position": lambda self: None,
            },
        )()

        actions = PlaylistsPanel.playlist_move_actions(panel)

        self.assertEqual(
            [label for label, callback in actions],
            [
                "Move &up",
                "Move to &top",
                "Move &down",
                "Move to &bottom",
                "Move to &position...",
            ],
        )

    def test_finished_playlist_move_retains_track_focus_and_position(self):
        first = ui.SpotifyItem("first", ui.ItemKind.TRACK, "First")
        second = ui.SpotifyItem("second", ui.ItemKind.TRACK, "Second")
        third = ui.SpotifyItem("third", ui.ItemKind.TRACK, "Third")
        focused = []
        rendered = []
        messages = []

        class Items:
            def __init__(self):
                self.items = [first, second, third]

            def set_items(self, tracks, selected=0):
                self.items = list(tracks)
                rendered.append((list(tracks), selected))

            def SetFocus(self):
                focused.append(True)

        state = ui.ViewState("Playlist", [first, second, third])
        panel = type(
            "Panel",
            (),
            {
                "items": Items(),
                "history": ui.NavigationHistory(state),
                "frame": type(
                    "Frame",
                    (),
                    {"say": lambda self, message: messages.append(message)},
                )(),
            },
        )()

        PlaylistsPanel.finish_move(panel, 0, 2)

        self.assertEqual(
            [track.id for track in state.items],
            ["second", "third", "first"],
        )
        self.assertEqual(state.selected, 2)
        self.assertEqual(rendered[0][1], 2)
        self.assertEqual(focused, [True])
        self.assertEqual(messages, ["Moved to position 3 of 3."])

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
        track = ui.SpotifyItem(
            "track",
            ui.ItemKind.TRACK,
            "Track",
            uri="spotify:track:track",
        )
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
        self.assertEqual(messages, ["Added 1 item to the playlist."])

    def test_added_tracks_update_open_playlist_in_displayed_order(self):
        tracks = [
            ui.SpotifyItem(
                str(number),
                ui.ItemKind.TRACK,
                f"Track {number}",
                uri=f"spotify:track:{number}",
            )
            for number in (2, 1)
        ]
        state = type("State", (), {"items": []})()
        messages = []
        playlists = type(
            "Playlists",
            (),
            {
                "current_playlist": type("Playlist", (), {"id": "list"})(),
                "history": type("History", (), {"current": state})(),
                "render": lambda self, state, focus: None,
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

        MainFrame.finish_add_to_playlist(
            frame,
            playlists.current_playlist,
            tracks,
        )

        self.assertEqual(state.items, tracks)
        self.assertEqual(messages, ["Added 2 items to the playlist."])

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

    def test_playlist_track_removal_requires_confirmation(self):
        track = ui.SpotifyItem(
            "track", ui.ItemKind.TRACK, "Track", uri="spotify:track:track"
        )
        playlist = ui.SpotifyItem(
            "playlist",
            ui.ItemKind.PLAYLIST,
            "Playlist",
            raw={"editable": True},
        )
        tasks = []
        panel = type(
            "Panel",
            (),
            {
                "current_playlist": playlist,
                "items": type(
                    "Items",
                    (),
                    {
                        "selected_item": lambda self: track,
                        "GetSelection": lambda self: 3,
                    },
                )(),
                "frame": type(
                    "Frame",
                    (),
                    {
                        "spotify": object(),
                        "run_task": lambda self, *args: tasks.append(args),
                        "say": lambda self, message: None,
                    },
                )(),
            },
        )()

        with patch("blindspot.ui.wx.MessageBox", return_value=ui.wx.NO):
            PlaylistsPanel.remove_selected(panel)
        self.assertEqual(tasks, [])

        with patch("blindspot.ui.wx.MessageBox", return_value=ui.wx.YES):
            PlaylistsPanel.remove_selected(panel)
        self.assertEqual(len(tasks), 1)


class LyricsKeyboardTests(unittest.TestCase):
    class SearchText:
        def __init__(self, value, selection=(0, 0)):
            self.value = value
            self.selection = selection
            self.insertion_points = []
            self.shown = []
            self.focused = False

        def GetValue(self):
            return self.value

        def GetSelection(self):
            return self.selection

        def SetSelection(self, start, end):
            self.selection = (start, end)

        def SetInsertionPoint(self, position):
            self.selection = (position, position)
            self.insertion_points.append(position)

        def ShowPosition(self, position):
            self.shown.append(position)

        def SetFocus(self):
            self.focused = True

    class Timer:
        def __init__(self):
            self.starts = []
            self.stops = 0

        def Start(self, milliseconds):
            self.starts.append(milliseconds)

        def Stop(self):
            self.stops += 1

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

    def test_alt_f4_closes_lyrics_before_keymap_dispatch(self):
        dialog = type("Dialog", (), {"on_close_button": Mock()})()

        LyricsDialog.on_dialog_key(
            dialog,
            self.Event(ui.wx.WXK_F4, alt=True),
        )

        dialog.on_close_button.assert_called_once()

    def test_tab_and_shift_tab_use_explicit_lyrics_focus_order(self):
        dialog = type("Dialog", (), {"move_tab_focus": Mock()})()

        LyricsDialog.on_dialog_key(dialog, self.Event(ui.wx.WXK_TAB))
        LyricsDialog.on_dialog_key(
            dialog,
            self.Event(ui.wx.WXK_TAB, shift=True),
        )

        self.assertEqual(
            dialog.move_tab_focus.call_args_list,
            [call(1), call(-1)],
        )

    def test_find_moves_caret_through_matches_without_wrapping(self):
        text = self.SearchText("First chorus\nVerse\nSecond chorus")
        dialog = type(
            "Dialog",
            (),
            {
                "find_text": self.SearchText("chorus"),
                "text": text,
                "frame": Mock(),
            },
        )()

        with patch("blindspot.ui.sys.platform", "win32"):
            LyricsDialog.find_lyrics(dialog, 1)
            self.assertEqual(text.selection, (6, 6))
            LyricsDialog.find_lyrics(dialog, 1)
            self.assertEqual(text.selection, (28, 28))
            LyricsDialog.find_lyrics(dialog, 1)
            self.assertEqual(text.selection, (28, 28))
            LyricsDialog.find_lyrics(dialog, -1)
            self.assertEqual(text.selection, (6, 6))
            LyricsDialog.find_lyrics(dialog, -1)
            self.assertEqual(text.selection, (6, 6))
        self.assertEqual(text.insertion_points, [6, 28, 6])
        self.assertEqual(
            [entry.args[0] for entry in dialog.frame.say.call_args_list],
            [
                "First chorus",
                "Second chorus",
                "Not found.",
                "First chorus",
                "Not found.",
            ],
        )

    def test_n_and_p_repeat_search_in_read_only_lyrics(self):
        dialog = type(
            "Dialog",
            (),
            {
                "find_panel": type(
                    "Panel", (), {"IsShown": lambda self: True}
                )(),
                "find_text": self.SearchText("word"),
                "find_lyrics": Mock(),
            },
        )()

        LyricsDialog.on_text_key(dialog, self.Event(ord("N")))
        LyricsDialog.on_text_key(dialog, self.Event(ord("P")))

        self.assertEqual(
            dialog.find_lyrics.call_args_list,
            [call(1), call(-1)],
        )

    def test_control_f_opens_find_on_windows(self):
        dialog = type("Dialog", (), {"show_find": Mock()})()

        with patch("blindspot.ui.sys.platform", "win32"):
            LyricsDialog.on_dialog_key(
                dialog,
                self.Event(ord("F"), control=True),
            )

        dialog.show_find.assert_called_once_with()

    def test_command_f_opens_find_on_macos(self):
        class CommandEvent(self.Event):
            def GetModifiers(self):
                return ui.wx.MOD_CONTROL

            def RawControlDown(self):
                return False

        dialog = type("Dialog", (), {"show_find": Mock()})()

        with (
            patch("blindspot.ui.sys.platform", "darwin"),
            patch("blindspot.ui.physical_control_down", return_value=False),
        ):
            LyricsDialog.on_dialog_key(
                dialog,
                CommandEvent(ord("F"), control=True),
            )

        dialog.show_find.assert_called_once_with()

    def test_find_temporarily_pauses_braille_caret_following(self):
        panel = Mock()
        panel.IsShown.return_value = False
        follow = Mock()
        follow.GetValue.return_value = True
        dialog = type(
            "Dialog",
            (),
            {
                "find_panel": panel,
                "find_text": Mock(),
                "follow_braille": follow,
                "braille_timer": Mock(),
                "text": Mock(),
                "Layout": Mock(),
                "last_braille_line": 4,
            },
        )()

        LyricsDialog.show_find(dialog)
        dialog.braille_timer.Stop.assert_called_once_with()
        LyricsDialog.close_find(dialog)

        dialog.braille_timer.Start.assert_called_once_with(
            ui.BRAILLE_LYRICS_TIMER_MS
        )
        self.assertEqual(dialog.last_braille_line, -1)

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
            LyricsDialog.on_dialog_key(dialog, self.Event(343, shift=True))
            LyricsDialog.on_dialog_key(dialog, self.Event(344, shift=True))
            LyricsDialog.on_dialog_key(dialog, self.Event(346, shift=True))

        self.assertEqual(
            frame.commands,
            [
                ("play", item),
                ("previous",),
                ("seek", -5000),
                ("pause_resume",),
                ("seek", 5000),
                ("next",),
                ("volume", -5),
                ("volume", 5),
                ("mute",),
            ],
        )

    def test_lyric_section_shortcuts_work_in_lyrics_dialog(self):
        jumps = []
        frame = type(
            "Frame",
            (),
            {
                "keymap": ui.KeyMap(platform="win32"),
                "keymap_action_for_event": MainFrame.keymap_action_for_event,
                "jump_lyric_section": (
                    lambda self, direction: jumps.append(direction)
                ),
            },
        )()
        dialog = type(
            "Dialog",
            (),
            {
                "frame": frame,
                "phrase_timer": self.Timer(),
                "phrase_start_ms": None,
                "phrase_end_ms": None,
                "phrase_started": False,
            },
        )()

        LyricsDialog.on_dialog_key(
            dialog,
            self.Event(ui.wx.WXK_F6, shift=True),
        )
        LyricsDialog.on_dialog_key(
            dialog,
            self.Event(ui.wx.WXK_F8, shift=True),
        )

        self.assertEqual(jumps, [-1, 1])

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
            MainFrame.on_global_key(frame, self.Event(343, shift=True))
            MainFrame.on_global_key(frame, self.Event(344, shift=True))
            MainFrame.on_global_key(frame, self.Event(346, shift=True))
            MainFrame.on_global_key(frame, self.Event(344))
            MainFrame.on_global_key(frame, self.Event(345))
            MainFrame.on_global_key(frame, self.Event(346))
            MainFrame.on_global_key(frame, self.Event(347))
            MainFrame.on_global_key(frame, self.Event(348))

        self.assertEqual(
            frame.commands,
            [
                ("volume", -5),
                ("volume", 5),
                ("mute",),
                ("previous",),
                ("seek", -5000),
                ("pause_resume",),
                ("seek", 5000),
                ("next",),
            ],
        )

    def test_f7_retains_normal_pause_resume_behavior_in_lyrics(self):
        toggled = []
        frame = type(
            "Frame",
            (),
            {
                "toggle_pause_resume": lambda self: toggled.append(True),
            },
        )()
        dialog = type("Dialog", (), {"frame": frame})()

        LyricsDialog.on_dialog_key(dialog, self.Event(ui.wx.WXK_F7))

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

    def test_shift_space_resumes_paused_track_from_selected_synced_lyric(self):
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
            self.Event(ui.wx.WXK_SPACE, shift=True),
        )

        self.assertEqual(resumed, [("track", 5_000)])

    def test_shift_space_starts_unplayed_track_from_selected_lyric(self):
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
            self.Event(ui.wx.WXK_SPACE, shift=True),
        )

        self.assertEqual(started, [(item, 5_000)])

    def test_shift_space_reports_when_synced_lyrics_are_unavailable(self):
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
            self.Event(ui.wx.WXK_SPACE, shift=True),
        )

        self.assertEqual(
            messages,
            [ui.msg.SYNCED_LYRICS_UNAVAILABLE],
        )

    def test_alt_down_moves_to_and_plays_next_synced_lyric(self):
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
            self.Event(ui.wx.WXK_DOWN, alt=True),
        )

        self.assertEqual(moved, [("caret", 10), ("show", 10)])
        self.assertEqual(started, [(item, 5_000)])

    def test_alt_up_moves_to_and_plays_previous_synced_lyric(self):
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
            self.Event(ui.wx.WXK_UP, alt=True),
        )

        self.assertEqual(moved, [("caret", 0), ("show", 0)])
        self.assertEqual(started, [(item, 1_000)])

    def test_shift_space_restarts_playing_track_from_selected_lyric(self):
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
            self.Event(ui.wx.WXK_SPACE, shift=True),
        )

        self.assertEqual(started, [(item, 5_000)])

    def test_phrase_mode_stops_at_the_next_synced_line(self):
        started = []
        paused = []
        positions = iter([1_000, 4_999, 5_000])
        timer = self.Timer()
        item = type("Item", (), {"duration_ms": 10_000})()
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
                "playback_position_ms": (
                    lambda self, track_id: next(positions)
                ),
                "pause_phrase_playback": (
                    lambda self, track_id: paused.append(track_id)
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
                "phrase_mode": type(
                    "PhraseMode",
                    (),
                    {"GetValue": lambda self: True},
                )(),
                "phrase_timer": timer,
            },
        )()

        LyricsDialog.play_synced_line(dialog, 0)
        LyricsDialog.on_phrase_timer(dialog, None)
        LyricsDialog.on_phrase_timer(dialog, None)
        LyricsDialog.on_phrase_timer(dialog, None)

        self.assertEqual(started, [(item, 1_000)])
        self.assertEqual(timer.starts, [ui.PHRASE_MODE_TIMER_MS])
        self.assertEqual(paused, ["track"])
        self.assertIsNone(dialog.phrase_start_ms)
        self.assertIsNone(dialog.phrase_end_ms)

    def test_phrase_mode_uses_track_end_for_the_last_line(self):
        timer = self.Timer()
        item = type("Item", (), {"duration_ms": 9_000})()
        frame = type(
            "Frame",
            (),
            {
                "current_track_is_paused": lambda self, track_id: False,
                "play_from_lyric": lambda self, item, position_ms: None,
            },
        )()
        dialog = type(
            "Dialog",
            (),
            {
                "frame": frame,
                "item": item,
                "track_id": "track",
                "synced_lines": [(1_000, "First"), (5_000, "Last")],
                "phrase_mode": type(
                    "PhraseMode",
                    (),
                    {"GetValue": lambda self: True},
                )(),
                "phrase_timer": timer,
            },
        )()

        LyricsDialog.play_synced_line(dialog, 1)

        self.assertEqual(dialog.phrase_start_ms, 5_000)
        self.assertEqual(dialog.phrase_end_ms, 9_000)

    def test_disabling_phrase_mode_cancels_the_boundary(self):
        timer = self.Timer()
        dialog = type(
            "Dialog",
            (),
            {
                "phrase_mode": type(
                    "PhraseMode",
                    (),
                    {"GetValue": lambda self: False},
                )(),
                "phrase_timer": timer,
                "phrase_start_ms": 1_000,
                "phrase_end_ms": 5_000,
                "phrase_started": True,
            },
        )()

        LyricsDialog.on_phrase_mode(dialog, None)

        self.assertEqual(timer.stops, 1)
        self.assertIsNone(dialog.phrase_start_ms)
        self.assertIsNone(dialog.phrase_end_ms)

    def test_bare_space_is_left_available_for_checkbox_toggle(self):
        checkbox_type = type("Checkbox", (), {})
        checkbox = checkbox_type()
        event = self.Event(ui.wx.WXK_SPACE, event_object=checkbox)

        with patch("blindspot.ui.wx.CheckBox", checkbox_type):
            LyricsDialog.on_dialog_key(type("Dialog", (), {})(), event)

        self.assertTrue(event.skipped)

    def test_mapped_space_does_not_pause_from_phrase_mode_checkbox(self):
        toggled = []
        checkbox_type = type("Checkbox", (), {})
        checkbox = checkbox_type()
        frame = type(
            "Frame",
            (),
            {
                "keymap": ui.KeyMap(platform="win32"),
                "keymap_action_for_event": (
                    lambda self, event, contexts: (
                        MainFrame.keymap_action_for_event(
                            self,
                            event,
                            contexts,
                        )
                    )
                ),
                "toggle_pause_resume": lambda self: toggled.append(True),
            },
        )()
        dialog = type(
            "Dialog",
            (),
            {"frame": frame, "phrase_mode": checkbox},
        )()
        event = self.Event(ui.wx.WXK_SPACE, event_object=checkbox)

        with patch("blindspot.ui.wx.CheckBox", checkbox_type):
            LyricsDialog.on_dialog_key(dialog, event)

        self.assertEqual(toggled, [])
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

    def test_dialog_routes_shift_space_with_internal_native_focus(self):
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
                shift=True,
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

    def test_alt_f4_closes_lyrics_instead_of_running_transport(self):
        frame = self.Frame()
        dialog = type(
            "Dialog",
            (),
            {
                "frame": frame,
                "item": object(),
                "on_close_button": Mock(),
            },
        )()
        event = self.Event(343, alt=True)

        with patch("blindspot.ui.sys.platform", "win32"):
            LyricsDialog.on_dialog_key(dialog, event)

        dialog.on_close_button.assert_called_once()
        self.assertFalse(event.skipped)
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
                "play_focused_or_remembered": (
                    lambda self, focused_list: MainFrame.play_focused_or_remembered(
                        self, focused_list
                    )
                ),
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

    def test_select_all_action_selects_every_item_in_focused_list(self):
        selected = []
        focused_list = type(
            "FocusedList",
            (),
            {"select_all_items": lambda self: selected.append(True)},
        )()
        frame = object()

        with patch.object(
            MainFrame,
            "keymap_action_for_event",
            return_value="select_all",
        ):
            handled = MainFrame.dispatch_mapped_key(
                frame,
                self.Event(ord("A"), control=True),
                focused_list,
                focused_list,
            )

        self.assertTrue(handled)
        self.assertEqual(selected, [True])

    def test_select_all_is_available_for_discover_chart_results(self):
        selected = []
        target = type(
            "Target",
            (),
            {
                "select_all_items": lambda self: selected.append(True),
                "GetSelections": lambda self: [0, 1],
            },
        )()
        spoken = []
        frame = type(
            "Frame",
            (),
            {
                "notebook": type(
                    "Notebook", (), {"GetSelection": lambda self: 8}
                )(),
                "new_music": type(
                    "Discover", (), {"result_mode": "chart"}
                )(),
                "say": lambda self, message: spoken.append(message),
            },
        )()

        MainFrame.select_all_in_current_list(frame, target)

        self.assertEqual(selected, [True])
        self.assertEqual(spoken, ["2 items selected"])

    def test_select_all_remains_unavailable_for_discover_releases(self):
        selected = []
        target = type(
            "Target",
            (),
            {"select_all_items": lambda self: selected.append(True)},
        )()
        frame = type(
            "Frame",
            (),
            {
                "notebook": type(
                    "Notebook", (), {"GetSelection": lambda self: 8}
                )(),
                "new_music": type(
                    "Discover", (), {"result_mode": "releases"}
                )(),
            },
        )()

        MainFrame.select_all_in_current_list(frame, target)

        self.assertEqual(selected, [])

    def test_discover_is_the_sort_panel_on_its_tab(self):
        discover = object()
        frame = type(
            "Frame",
            (),
            {
                "notebook": type(
                    "Notebook", (), {"GetSelection": lambda self: 8}
                )(),
                "new_music": discover,
            },
        )()

        self.assertIs(MainFrame.current_sort_panel(frame), discover)

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


class LyricSectionCacheTests(unittest.TestCase):
    def test_jump_reuses_loaded_lyrics_without_starting_a_task(self):
        item = ui.SpotifyItem(
            "track",
            ui.ItemKind.TRACK,
            "Song",
            artist="Artist",
        )
        lyrics = ui.Lyrics(
            "Song",
            "Artist",
            "First\n\nSecond",
            True,
            synced_lines=[(1_000, "First"), (10_000, "Second")],
        )
        frame = Mock(
            current_player_item=item,
            lyric_sections=None,
            recent_lyrics=(item.id, lyrics),
        )

        MainFrame.jump_lyric_section(frame, 1)

        frame.run_task.assert_not_called()
        frame.finish_jump_lyric_section.assert_called_once_with(
            item,
            [1_000, 10_000],
            1,
        )
        self.assertEqual(frame.lyric_sections, (item.id, [1_000, 10_000]))

if __name__ == "__main__":
    unittest.main()
