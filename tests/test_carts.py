import unittest

from blindspot.carts import (
    Cart,
    cart_cutoff_state,
    dump_carts,
    load_carts,
    next_cart_number,
)


def cart(number=1):
    return Cart(number, "track", "spotify:track:track", "Song", "Artist", "Album", 100_000, 1_000, 2_000)


class CartTests(unittest.TestCase):
    def test_carts_round_trip_in_number_order(self):
        carts = {3: cart(3), 1: cart(1)}
        self.assertEqual(list(load_carts(dump_carts(carts))), [1, 3])

    def test_invalid_records_are_ignored(self):
        self.assertEqual(load_carts([{"number": 1}, "bad"]), {})

    def test_end_must_follow_start(self):
        with self.assertRaises(ValueError):
            Cart(1, "track", "uri", "Song", "", "", 10, 5, 5)

    def test_cutoff_waits_for_seek_to_enter_cart_range(self):
        value = Cart(1, "track", "uri", "Song", "", "", 20_000, 5_000, 8_000)
        self.assertEqual(cart_cutoff_state(value, 12_000, False), (False, False))
        self.assertEqual(cart_cutoff_state(value, 5_050, False), (True, False))
        self.assertEqual(cart_cutoff_state(value, 8_000, True), (True, True))

    def test_cutoff_fires_early_to_offset_pause_delay(self):
        value = Cart(1, "track", "uri", "Song", "", "", 20_000, 5_000, 8_000)
        self.assertEqual(cart_cutoff_state(value, 7_700, True), (True, False))
        self.assertEqual(cart_cutoff_state(value, 7_750, True), (True, True))
        short = Cart(1, "track", "uri", "Song", "", "", 20_000, 5_000, 5_200)
        self.assertEqual(cart_cutoff_state(short, 5_050, True), (True, False))

    def test_next_cart_uses_populated_slots_and_wraps(self):
        carts = {2: cart(2), 7: cart(7)}
        self.assertEqual(next_cart_number(carts, 2), 7)
        self.assertEqual(next_cart_number(carts, 7), 2)
        self.assertIsNone(next_cart_number({}, 2))


class CartMarkingTests(unittest.TestCase):
    def test_report_transit_uses_sample_time_and_ignores_bad_values(self):
        from unittest.mock import patch

        from blindspot.ui import MainFrame

        with patch("blindspot.ui.time.time", return_value=100.0):
            self.assertAlmostEqual(
                MainFrame.report_transit_seconds({"sent_at_ms": 99_600}), 0.4
            )
            self.assertEqual(MainFrame.report_transit_seconds({}), 0.0)
            self.assertEqual(
                MainFrame.report_transit_seconds({"sent_at_ms": 101_000}), 0.0
            )
            self.assertEqual(
                MainFrame.report_transit_seconds({"sent_at_ms": 0}), 2.0
            )


class LyricSectionTests(unittest.TestCase):
    def test_marked_silence_starts_a_new_section(self):
        from blindspot.lyrics import section_starts

        lines = [(10_000, "a"), (14_000, "b"), (30_000, "c"), (34_000, "d")]
        self.assertEqual(section_starts(lines, [17_000]), [10_000, 30_000])
        self.assertEqual(section_starts(lines, [17_000, 32_000]), [10_000, 30_000])
        self.assertEqual(section_starts(lines, [13_000]), [10_000, 30_000])
        self.assertEqual(section_starts(lines, [13_000, 27_000]), [10_000])

    def test_unmarked_gaps_use_line_spacing(self):
        from blindspot.lyrics import section_starts

        lines = [(0, "a"), (4_000, "b"), (8_000, "c"), (24_000, "d"), (28_000, "e")]
        self.assertEqual(section_starts(lines), [0, 24_000])
        self.assertEqual(section_starts([]), [])

    def test_jump_targets(self):
        from blindspot.lyrics import section_target

        starts = [10_000, 30_000, 60_000]
        self.assertEqual(section_target(starts, 5_000, 1), 0)
        self.assertEqual(section_target(starts, 30_000, 1), 2)
        self.assertIsNone(section_target(starts, 60_000, 1))
        self.assertEqual(section_target(starts, 31_000, -1), 0)
        self.assertEqual(section_target(starts, 45_000, -1), 1)
        self.assertIsNone(section_target(starts, 11_000, -1))

    def test_default_keys_do_not_collide(self):
        from blindspot.keymap import ACTIONS_BY_ID

        self.assertEqual(ACTIONS_BY_ID["next_verse"].windows, ("Shift+F8",))
        self.assertEqual(ACTIONS_BY_ID["previous_verse"].windows, ("Shift+F6",))


class StanzaSectionTests(unittest.TestCase):
    def test_blank_lines_in_the_text_mark_sections(self):
        from blindspot.lyrics import section_starts

        lines = [(1_000, "One"), (3_000, "Two"), (5_000, "Three"), (7_000, "Four"), (9_000, "Five")]
        text = "One\nTwo\n\nThree\nFour\n\nFive"
        self.assertEqual(section_starts(lines, [], text), [1_000, 5_000, 9_000])

    def test_mismatched_text_falls_back_to_gaps(self):
        from blindspot.lyrics import section_starts

        lines = [(0, "a"), (4_000, "b"), (8_000, "c"), (24_000, "d")]
        self.assertEqual(section_starts(lines, [], "x\n\ny\nz"), [0, 24_000])


class SectionAnnouncementTests(unittest.TestCase):
    def frame(self, announce):
        from unittest.mock import Mock

        from blindspot.ui import MainFrame

        frame = Mock()
        frame.announce_lyric_sections = announce
        frame.playback_position_ms.return_value = 5_000
        frame.lyric_adjustment_ms.return_value = 0
        return MainFrame, frame

    def test_section_number_is_spoken_only_when_enabled(self):
        for announce, spoken in ((False, False), (True, True)):
            main_frame, frame = self.frame(announce)
            item = Mock_item = type("Item", (), {"id": "t"})()
            main_frame.finish_jump_lyric_section(frame, item, [10_000, 30_000], 1)
            frame.seek_to_position.assert_called_once_with(10_000)
            self.assertEqual(frame.say.called, spoken)


class CartNameAnnouncementTests(unittest.TestCase):
    def test_cart_name_is_spoken_only_when_enabled(self):
        from unittest.mock import Mock

        from blindspot.ui import MainFrame

        for enabled in (True, False):
            frame = Mock()
            frame.announce_cart_names = enabled
            frame.carts = {3: cart(3)}
            frame.using_local_player.return_value = False
            frame.pending_resume = None
            MainFrame.play_cart(frame, 3)
            self.assertEqual(frame.say.called, enabled)
            frame.play_from_lyric.assert_called_once()


class CartFastPathTests(unittest.TestCase):
    def frame(self, pending_resume=None):
        from unittest.mock import Mock

        frame = Mock()
        frame.announce_cart_names = False
        frame.carts = {1: cart(1)}
        frame.using_local_player.return_value = True
        frame.player.ready = True
        frame.pending_transfer_device = None
        frame.pending_resume = pending_resume
        from blindspot.ui import MainFrame

        frame.start_cart_playback = (
            lambda cart, state: MainFrame.start_cart_playback(frame, cart, state)
        )
        return frame

    def test_loaded_song_is_seeked_in_place(self):
        from blindspot.ui import MainFrame

        frame = self.frame()
        MainFrame.play_cart(frame, 1)
        (callback,) = frame.player.request_playback_state.call_args.args
        frame.playing_cart = frame.carts[1]
        callback({"item": {"id": "track"}})
        frame.player.seek_and_play.assert_called_once_with(1_000)
        frame.play_from_lyric.assert_not_called()

    def test_nothing_loaded_falls_back_to_a_normal_play(self):
        from blindspot.ui import MainFrame

        frame = self.frame()
        MainFrame.play_cart(frame, 1)
        (callback,) = frame.player.request_playback_state.call_args.args
        frame.playing_cart = frame.carts[1]
        callback({})
        frame.player.seek_and_play.assert_not_called()
        frame.play_from_lyric.assert_called_once()

    def test_a_remembered_song_is_never_seeked(self):
        from blindspot.ui import MainFrame

        frame = self.frame(pending_resume=("item", 0, ""))
        MainFrame.play_cart(frame, 1)
        frame.player.request_playback_state.assert_not_called()
        frame.play_from_lyric.assert_called_once()
