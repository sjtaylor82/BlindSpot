from __future__ import annotations

import http.server
import logging
import queue
import time
import urllib.parse
from collections.abc import Callable

from . import messages as msg

logger = logging.getLogger("blindspot.auth_callback")
AUTHORIZATION_TIMEOUT_SECONDS = 600


class CallbackServer:
    """Receives one OAuth redirect on BlindSpot's loopback address."""

    def __init__(self, expected_state: str) -> None:
        self.expected_state = expected_state
        self.result: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=1)

    def wait(
        self,
        timeout: float = AUTHORIZATION_TIMEOUT_SECONDS,
        *,
        on_ready: Callable[[], None] | None = None,
    ) -> str:
        owner = self
        logger.info("Waiting for Spotify callback on 127.0.0.1:43821")

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != "/callback":
                    self.send_error(404)
                    return
                query = urllib.parse.parse_qs(parsed.query)
                state = query.get("state", [""])[0]
                error = query.get("error", [""])[0]
                code = query.get("code", [""])[0]
                if state != owner.expected_state:
                    logger.warning("Spotify callback state did not match")
                    self.send_error(400, msg.AUTH_STATE_MISMATCH)
                    return
                elif error:
                    logger.warning("Spotify callback contained error: %s", error)
                    owner.result.put(("", msg.spotify_login_failed(error)))
                elif not code:
                    logger.warning("Spotify callback did not contain a code")
                    self.send_error(400, msg.AUTH_CODE_MISSING)
                    return
                else:
                    logger.info("Spotify callback received an authorization code")
                    owner.result.put((code, ""))
                message = msg.CALLBACK_RECEIVED
                body = message.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        with http.server.HTTPServer(("127.0.0.1", 43821), Handler) as server:
            if on_ready:
                on_ready()
            deadline = time.monotonic() + timeout
            while self.result.empty():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                server.timeout = remaining
                server.handle_request()
        try:
            code, error = self.result.get_nowait()
        except queue.Empty as error:
            logger.info("Spotify authorization timed out")
            raise TimeoutError(
                msg.AUTHORIZATION_TIMEOUT
            ) from error
        if error:
            raise RuntimeError(error)
        logger.info("Spotify callback completed")
        return code
