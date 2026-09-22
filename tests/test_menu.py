import unittest
from collections import Counter
from unittest.mock import Mock

import wx

from blindspot import ui
from blindspot.ui import MainFrame


class MenuBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = wx.App(False)

        class Stub(wx.Frame):
            def __getattr__(self, name):
                if name.startswith("_") or name in (
                    "sort_menu_items",
                    "keymap",
                    "keyed_menu_items",
                ):
                    raise AttributeError(name)
                return lambda *args, **kwargs: None

        cls.frame = Stub(None)
        cls.frame.keymap = ui.KeyMap({})
        MainFrame._build_menu(cls.frame)
        cls.bar = cls.frame.GetMenuBar()

    @classmethod
    def tearDownClass(cls):
        cls.frame.Destroy()

    def menus(self):
        def walk(menu, path):
            yield path, menu
            for item in menu.GetMenuItems():
                if item.GetSubMenu():
                    yield from walk(
                        item.GetSubMenu(), f"{path} > {item.GetItemLabelText()}"
                    )

        for index in range(self.bar.GetMenuCount()):
            yield from walk(
                self.bar.GetMenu(index), self.bar.GetMenuLabelText(index)
            )

    def test_no_menu_reuses_a_mnemonic(self):
        for path, menu in self.menus():
            letters = Counter()
            for item in menu.GetMenuItems():
                label = item.GetItemLabel()
                position = label.find("&")
                if position >= 0:
                    letters[label[position + 1].casefold()] += 1
            repeated = [letter for letter, count in letters.items() if count > 1]
            self.assertEqual([], repeated, f"repeated mnemonic in {path}")

    def test_playback_menu_groups_controls_and_current_track_actions(self):
        titles = {
            self.bar.GetMenuLabelText(i): self.bar.GetMenu(i)
            for i in range(self.bar.GetMenuCount())
        }
        playback = titles["Playback"]
        top = [item.GetItemLabelText() for item in playback.GetMenuItems() if not item.IsSeparator()]
        for group in ("Seek and jump", "Volume", "Speak", "Now playing"):
            self.assertIn(group, top)
        for gone in (
            "Add marked items to queue",
            "Like/unlike selected item",
            "Add selected to a playlist...",
        ):
            self.assertNotIn(gone, top)
        now_playing = next(
            item.GetSubMenu()
            for item in playback.GetMenuItems()
            if item.GetItemLabelText() == "Now playing"
        )
        labels = [item.GetItemLabelText() for item in now_playing.GetMenuItems()]
        self.assertTrue(any(label.startswith("What's this song about?") for label in labels))
        self.assertTrue(any(label.startswith("Open album") for label in labels))

    def test_file_menu_contains_settings_and_exit_without_options_menu(self):
        titles = {
            self.bar.GetMenuLabelText(i): self.bar.GetMenu(i)
            for i in range(self.bar.GetMenuCount())
        }
        self.assertNotIn("Options", titles)
        file_labels = [
            item.GetItemLabelText()
            for item in titles["File"].GetMenuItems()
            if not item.IsSeparator()
        ]
        self.assertIn("Preferences...", file_labels)
        self.assertIn("Account", file_labels)
        exit_items = [
            item
            for item in titles["File"].GetMenuItems()
            if item.GetId() == wx.ID_EXIT
        ]
        self.assertEqual(len(exit_items), 1)
        # wx follows the native macOS convention and displays ID_EXIT as Quit.
        self.assertIn(exit_items[0].GetItemLabelText(), {"Exit", "Quit"})

    def test_keys_are_shown_from_the_keymap(self):
        self.assertEqual(
            MainFrame.menu_label(self.frame, "Pause", "pause_resume"),
            "Pause (F7 or Space)",
        )
        self.assertEqual(MainFrame.menu_label(self.frame, "Repeat"), "Repeat")
        self.assertEqual(ui.chord_display("Control+Shift+T", "win32"), "Ctrl+Shift+T")
        self.assertEqual(ui.chord_display("Control+Shift+T", "darwin"), "Control+Shift+T")


class CurrentTrackActionTests(unittest.TestCase):
    def frame(self, item):
        frame = Mock()
        frame.current_player_item = item
        frame.current_track = lambda: MainFrame.current_track(frame)
        return frame

    def track(self, artists=None):
        return ui.SpotifyItem(
            "t1",
            ui.ItemKind.TRACK,
            "Song",
            raw={"artists": artists if artists is not None else [{"id": "a1", "name": "Artist"}]},
        )

    def test_actions_use_the_playing_track(self):
        item = self.track()
        frame = self.frame(item)
        MainFrame.show_current_song_story(frame)
        frame.show_song_story.assert_called_once_with(item)
        MainFrame.open_current_album(frame)
        frame.open_album_for_track.assert_called_once_with(item)
        MainFrame.show_current_artist_albums(frame)
        frame.show_artist_albums.assert_called_once_with("a1", "Artist")
        MainFrame.find_covers_for_current(frame)
        frame.find_covers_for.assert_called_once_with(item)
        MainFrame.browse_genres_for_current(frame)
        frame.browse_genres_for.assert_called_once_with(item)
        MainFrame.add_current_to_playlist(frame)
        frame.choose_playlist_for_item.assert_called_once_with(item)

    def test_nothing_playing_is_reported_instead_of_acting(self):
        frame = self.frame(None)
        MainFrame.show_current_song_story(frame)
        MainFrame.open_current_album(frame)
        frame.show_song_story.assert_not_called()
        frame.open_album_for_track.assert_not_called()
        self.assertEqual(frame.say.call_count, 2)

    def test_track_without_an_artist_says_so(self):
        frame = self.frame(self.track(artists=[]))
        MainFrame.show_current_artist_albums(frame)
        frame.show_artist_albums.assert_not_called()
        frame.say.assert_called_once()


if __name__ == "__main__":
    unittest.main()


class PlayFocusedTests(unittest.TestCase):
    def frame(self, pending_resume):
        frame = Mock()
        frame.pending_resume = pending_resume
        return frame

    def test_a_focused_list_plays_its_selection(self):
        frame = self.frame(("song", 0, ""))
        MainFrame.play_focused_or_remembered(frame, object())
        frame.play_selected.assert_called_once()
        frame.toggle_playback.assert_not_called()

    def test_without_a_list_the_remembered_song_plays(self):
        frame = self.frame(("song", 0, ""))
        MainFrame.play_focused_or_remembered(frame, None)
        frame.toggle_playback.assert_called_once()
        frame.play_selected.assert_not_called()

    def test_nothing_remembered_still_says_no_song_selected(self):
        frame = self.frame(None)
        MainFrame.play_focused_or_remembered(frame, None)
        frame.toggle_playback.assert_not_called()
        frame.say.assert_called_once()
