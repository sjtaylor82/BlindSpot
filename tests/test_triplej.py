import unittest
from unittest.mock import Mock

from blindspot.triplej import Countdown, Hottest100Client, parse_countdown
from blindspot import ui


HTML = '''
<script>
var tracks = [
  {"artist":"Artist One","track":"First Song","pollyear":2024,
   "position":1,"releaseyear":"2024","alltime":false},
  {"artist":"Artist Two","track":"Special Song","pollyear":2024,
   "position":2,"releaseyear":"1999","alltime":true},
  {"artist":"Artist Three","track":"Third Song","pollyear":2024,
   "position":3,"releaseyear":"2023","alltime":false}
];
var albums = [];
</script>
'''


class Hottest100Tests(unittest.TestCase):
    def test_regular_and_special_countdowns_are_distinct(self):
        regular = parse_countdown(HTML, Countdown(2024, False, "2024"))
        special = parse_countdown(HTML, Countdown(2024, True, "Special"))

        self.assertEqual([entry.rank for entry in regular], [1, 3])
        self.assertEqual(special[0].name, "Special Song")
        self.assertEqual(regular[0].release_year, "2024")

    def test_archive_page_is_cached(self):
        class StubClient(Hottest100Client):
            def __init__(self):
                super().__init__()
                self.reads = 0

            def _archive_html(self):
                self.reads += 1
                return HTML

        client = StubClient()
        client.countdown(Countdown(2024, False, "2024"))

        self.assertEqual(client.reads, 1)


class Hottest100InputTests(unittest.TestCase):
    def panel(self, selection):
        panel = Mock()
        panel.loading = False
        panel.source.return_value = "historical"
        panel.history_chart.GetSelection.return_value = 2
        panel.triple_j_countdown.GetSelection.return_value = selection
        panel.frame.run_task = Mock()
        return panel

    def test_search_requires_an_explicit_countdown(self):
        panel = self.panel(0)

        ui.NewMusicPanel.on_search(panel)

        panel.frame.run_task.assert_not_called()
        panel.frame.say.assert_called_once()
        panel.triple_j_countdown.SetFocus.assert_called_once()
        self.assertFalse(panel.loading)

    def test_selected_countdown_accounts_for_the_prompt_row(self):
        panel = self.panel(1)

        ui.NewMusicPanel.on_search(panel)

        worker = panel.frame.run_task.call_args.args[1]
        worker()
        panel.frame.triple_j_results.assert_called_once_with(ui.TRIPLE_J_COUNTDOWNS[0])


if __name__ == "__main__":
    unittest.main()
