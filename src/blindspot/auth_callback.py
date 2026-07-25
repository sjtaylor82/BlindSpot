from __future__ import annotations

import http.server
import logging
import queue
import urllib.parse

logger = logging.getLogger("blindspot.auth_callback")


class CallbackServer:
    """Receives one OAuth redirect on BlindSpot's loopback address."""

    def __init__(self, expected_state: str) -> None:
        self.expected_state = expected_state
        self.result: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=1)

    def wait(self, timeout: float = 180) -> str:
        owner = self
        logger.info("Waiting for Spotify callback on 127.0.0.1:43821")

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                state = query.get("state", [""])[0]
                error = query.get("error", [""])[0]
                code = query.get("code", [""])[0]
                if state != owner.expected_state:
                    logger.warning("Spotify callback state did not match")
                    owner.result.put(("", "The Spotify login state did not match."))
                elif error:
                    logger.warning("Spotify callback contained error: %s", error)
                    owner.result.put(("", f"Spotify login failed: {error}"))
                else:
                    logger.info("Spotify callback received an authorization code")
                    owner.result.put((code, ""))
                message = (
                    "BlindSpot received the Spotify response. "
                    "You may close this browser tab."
                )
                body = message.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        with http.server.ThreadingHTTPServer(("127.0.0.1", 43821), Handler) as server:
            server.timeout = timeout
            server.handle_request()
        try:
            code, error = self.result.get_nowait()
        except queue.Empty as error:
            logger.info("Spotify authorization timed out")
            raise TimeoutError(
                "Spotify authorization timed out. BlindSpot is still available; "
                "try again from the Account menu when ready."
            ) from error
        if error:
            raise RuntimeError(error)
        logger.info("Spotify callback completed")
        return code
