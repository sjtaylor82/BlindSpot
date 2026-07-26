import unittest
from unittest.mock import patch

from blindspot.auth_callback import CallbackServer


class CallbackOrderingTests(unittest.TestCase):
    def test_listener_is_bound_before_browser_is_opened(self):
        events = []

        class Server:
            timeout = None

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def handle_request(self):
                events.append("listen")

        def create_server(address, handler):
            events.append("bound")
            return Server()

        callback = CallbackServer("state")
        with (
            patch(
                "blindspot.auth_callback.http.server.HTTPServer",
                side_effect=create_server,
            ),
            self.assertRaises(TimeoutError),
        ):
            callback.wait(
                timeout=0.01,
                on_ready=lambda: events.append("browser"),
            )

        self.assertEqual(events[:3], ["bound", "browser", "listen"])
