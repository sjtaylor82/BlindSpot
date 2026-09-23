import json
import unittest

from blindspot.abcclassic import (
    ClassicCountdown,
    parse_archive,
    parse_current,
)


ARCHIVE_HTML = '''
<script>
var tracks = [
 {"position":2,"work":"Second Work","composer":"Composer, Ada",
  "pollname":"piano","pollyear":2025},
 {"position":1,"work":"First Work","composer":"Composer, Bea",
  "pollname":"piano","pollyear":2025},
 {"position":1,"work":"Other Poll","composer":"Someone",
  "pollname":"feelgood","pollyear":2024}
];
</script>
'''


class Classic100Tests(unittest.TestCase):
    def test_archive_filters_poll_and_orders_by_rank(self):
        countdown = ClassicCountdown(2025, "piano", "Piano (2025)")

        entries = parse_archive(ARCHIVE_HTML, countdown)

        self.assertEqual([entry.work for entry in entries], ["First Work", "Second Work"])
        self.assertEqual(entries[0].composer, "Composer, Bea")

    def test_current_page_reads_song_countdown_component(self):
        payload = {
            "props": {
                "pageProps": {
                    "data": {
                        "componentsContent": [
                            {"component": "Other", "componentProps": {}},
                            {
                                "component": "SongCountdown",
                                "componentProps": {
                                    "songsPrepared": [
                                        {
                                            "position": 1,
                                            "title": "A Symphony",
                                            "artist": "A Composer",
                                        }
                                    ]
                                },
                            },
                        ]
                    }
                }
            }
        }
        html = (
            '<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(payload)
            + "</script>"
        )

        entries = parse_current(html)

        self.assertEqual(entries[0].work, "A Symphony")
        self.assertEqual(entries[0].rank, 1)


if __name__ == "__main__":
    unittest.main()
