import unittest
from unittest.mock import Mock, patch

from blindspot.wikipedia import (
    SongStoryUnavailable,
    WikipediaClient,
    choose_story,
    format_article,
)


def page(title, extract, description="", index=1):
    return {
        "title": title,
        "extract": extract,
        "description": description,
        "index": index,
        "fullurl": "https://en.wikipedia.org/wiki/" + title.replace(" ", "_"),
    }


BEATLES = "\"Yesterday\" is a song by the English rock band the Beatles."


class ChooseStoryTests(unittest.TestCase):
    def test_accepts_the_matching_song_article(self):
        pages = [
            page("Yesterday (film)", "A 2019 film.", "2019 film", 1),
            page("Yesterday (Beatles song)", BEATLES, "1965 song by the Beatles", 2),
        ]
        story = choose_story(pages, "Yesterday", "The Beatles")
        self.assertEqual(story.title, "Yesterday (Beatles song)")
        self.assertIn("Beatles", story.summary)

    def test_rejects_disambiguation_wrong_artist_and_non_songs(self):
        self.assertIsNone(
            choose_story(
                [page("Yesterday", "Yesterday may refer to: a song, a film.", "")],
                "Yesterday",
                "The Beatles",
            )
        )
        self.assertIsNone(
            choose_story(
                [page("Yesterday (Other song)", "A song by another band.", "song")],
                "Yesterday",
                "The Beatles",
            )
        )
        self.assertIsNone(
            choose_story(
                [page("Yesterday (Beatles album)", "The Beatles released this.", "album")],
                "Yesterday",
                "The Beatles",
            )
        )

    def test_song_title_must_appear_in_the_article_title(self):
        self.assertIsNone(
            choose_story(
                [page("The Beatles", "The Beatles were a band. Their song Yesterday.", "band")],
                "Yesterday",
                "The Beatles",
            )
        )



class FormatArticleTests(unittest.TestCase):
    def test_drops_list_sections_and_keeps_the_story(self):
        text = (
            "Intro sentence."
            "NN== Background ==NNWritten in 1965."
            "NN=== Recording ===NNRecorded at Abbey Road."
            "NN== Personnel ==NNSomeone on drums."
            "NN=== Extra ===NNNested under personnel."
            "NN== Legacy ==NNStill covered."
            "NN== References ==NNA citation."
        ).replace("NN", chr(10) * 2)
        article = format_article(text)
        self.assertIn("Intro sentence.", article)
        self.assertIn("Background" + chr(10) * 2 + "Written in 1965.", article)
        self.assertIn("Recorded at Abbey Road.", article)
        self.assertIn("Still covered.", article)
        self.assertNotIn("Someone on drums", article)
        self.assertNotIn("Nested under personnel", article)
        self.assertNotIn("citation", article)
        self.assertNotIn("==", article)


class ClientTests(unittest.TestCase):
    def test_lookup_uses_one_request_and_caches_answers(self):
        client = WikipediaClient()
        pages = [page("Yesterday (Beatles song)", BEATLES, "song")]
        with patch.object(client, "_search", return_value=pages) as search:
            first = client.song_story("Yesterday - Remastered 2009", "The Beatles, X")
            second = client.song_story("Yesterday - Remastered 2009", "The Beatles, X")
        self.assertEqual(first, second)
        search.assert_called_once_with("Yesterday", "The Beatles")

    def test_missing_article_is_reported_and_remembered(self):
        client = WikipediaClient()
        with patch.object(client, "_search", return_value=[]) as search:
            for _ in range(2):
                with self.assertRaises(SongStoryUnavailable):
                    client.song_story("Obscure", "Nobody")
        search.assert_called_once()


class VolumeAnnouncementTests(unittest.TestCase):
    def test_volume_is_spoken_only_when_enabled(self):
        from blindspot.ui import MainFrame

        for enabled in (True, False):
            frame = Mock()
            frame.announce_volume_changes = enabled
            frame.store.read.return_value = {}
            MainFrame.finish_adjust_volume(frame, 55)
            self.assertEqual(frame.say.called, enabled)
            self.assertEqual(frame.playback_volume_percent, 55)


if __name__ == "__main__":
    unittest.main()
