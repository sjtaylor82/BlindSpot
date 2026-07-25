from __future__ import annotations

import http.server
import json
import logging
import sys
import threading
from collections.abc import Callable

import wx
import wx.html2

from .spotify import SpotifyClient

logger = logging.getLogger("blindspot.web_player")

PLAYER_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>BlindSpot playback engine</title>
</head>
<body>
  <p>BlindSpot playback engine</p>
  <script src="https://sdk.scdn.co/spotify-player.js"></script>
  <script>
    (() => {
      let player = null;
      let sdkReady = false;
      let accessToken = "";
      let waitingForToken = null;
      let volumeCommands = Promise.resolve();
      let volumeBeforeMute = 0.8;
      let playbackSnapshotTimer = null;

      function send(type, detail = {}) {
        const message = JSON.stringify({type, ...detail});
        window.blindspot.postMessage(message);
      }

      function serializeState(state) {
        if (!state) {
          return null;
        }
        const track = state.track_window.current_track;
        return {
          progress_ms: state.position,
          is_playing: !state.paused,
          context_uri: state.context && state.context.uri
            ? state.context.uri
            : null,
          item: track ? {
            id: track.id,
            uri: track.uri,
            type: track.type || "track",
            name: track.name,
            duration_ms: state.duration,
            artists: track.artists || [],
            album: track.album || {}
          } : null
        };
      }

      function provideToken(token) {
        accessToken = token || "";
        if (waitingForToken && accessToken) {
          const callback = waitingForToken;
          waitingForToken = null;
          const token = accessToken;
          accessToken = "";
          callback(token);
        }
        connectIfReady();
      }

      function connectIfReady() {
        if (!sdkReady || !accessToken || player) {
          return;
        }
        player = new Spotify.Player({
          name: "BlindSpot",
          volume: 0.8,
          enableMediaSession: true,
          getOAuthToken: callback => {
            if (accessToken) {
              const token = accessToken;
              accessToken = "";
              callback(token);
            } else {
              waitingForToken = callback;
              send("token_required");
            }
          }
        });

        player.addListener("ready", ({device_id}) => {
          send("ready", {device_id});
        });
        player.addListener("not_ready", ({device_id}) => {
          send("not_ready", {device_id});
        });
        for (const eventName of [
          "initialization_error",
          "authentication_error",
          "account_error",
          "playback_error"
        ]) {
          player.addListener(eventName, ({message}) => {
            send("error", {source: eventName, message});
          });
        }
        player.addListener("autoplay_failed", () => {
          send("autoplay_failed");
        });
        player.addListener("player_state_changed", state => {
          send("playback_update", {state: serializeState(state)});
        });
        player.connect().then(success => {
          send("connection_result", {success});
          if (success && !playbackSnapshotTimer) {
            playbackSnapshotTimer = setInterval(() => {
              player.getCurrentState().then(state => {
                if (state) {
                  send("playback_update", {state: serializeState(state)});
                }
              });
            }, 10000);
          }
        });
      }

      window.blindSpotProvideToken = provideToken;
      window.blindSpotActivate = () => {
        if (!player) {
          return Promise.resolve(false);
        }
        return player.activateElement().then(() => true);
      };
      window.blindSpotRequestPlaybackState = () => {
        if (!player) {
          send("playback_state", {state: null});
          return;
        }
        player.getCurrentState().then(state => {
          if (!state) {
            send("playback_state", {state: null});
            return;
          }
          send("playback_state", {state: serializeState(state)});
        });
      };
      function reportCommandError(command, error) {
        send("error", {
          source: command,
          message: error && error.message ? error.message : String(error)
        });
      }
      window.blindSpotTogglePlayback = () => {
        if (player) {
          player.togglePlay().catch(error => reportCommandError("playback", error));
        }
      };
      window.blindSpotPreviousTrack = () => {
        if (player) {
          player.previousTrack()
            .catch(error => reportCommandError("previous track", error));
        }
      };
      window.blindSpotNextTrack = () => {
        if (player) {
          player.nextTrack()
            .catch(error => reportCommandError("next track", error));
        }
      };
      window.blindSpotSeekRelative = deltaMs => {
        if (!player) {
          return;
        }
        player.getCurrentState().then(state => {
          if (!state) {
            throw new Error("Nothing is currently playing.");
          }
          const maximum = Math.max(0, state.duration - 1);
          const target = Math.min(maximum, Math.max(0, state.position + deltaMs));
          return player.seek(target);
        }).catch(error => reportCommandError("seek", error));
      };
      window.blindSpotSeekTo = positionMs => {
        if (player) {
          player.seek(Math.max(0, positionMs))
            .catch(error => reportCommandError("seek", error));
        }
      };
      window.blindSpotAdjustVolume = deltaPercent => {
        volumeCommands = volumeCommands.then(() => {
          if (!player) {
            return;
          }
          return player.getVolume().then(volume => {
            const target = Math.min(1, Math.max(0, volume + deltaPercent / 100));
            return player.setVolume(target).then(() => {
              send("volume_result", {volume: Math.round(target * 100)});
            });
          });
        }).catch(error => {
          reportCommandError("volume", error);
          send("volume_result", {volume: null});
        });
      };
      window.blindSpotToggleMute = () => {
        volumeCommands = volumeCommands.then(() => {
          if (!player) {
            return;
          }
          return player.getVolume().then(volume => {
            let target;
            if (volume > 0.001) {
              volumeBeforeMute = volume;
              target = 0;
            } else {
              target = volumeBeforeMute > 0.001 ? volumeBeforeMute : 0.8;
            }
            return player.setVolume(target).then(() => {
              send("volume_result", {volume: Math.round(target * 100)});
            });
          });
        }).catch(error => {
          reportCommandError("volume", error);
          send("volume_result", {volume: null});
        });
      };
      window.onSpotifyWebPlaybackSDKReady = () => {
        sdkReady = true;
        send("sdk_ready");
        connectIfReady();
      };
      send("page_ready");
    })();
  </script>
</body>
</html>
"""


class PlayerPageServer:
    def __init__(self) -> None:
        html = PLAYER_HTML.encode("utf-8")

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path not in ("/", "/player"):
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)

            def log_message(self, format: str, *args: object) -> None:
                return

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            name="BlindSpotPlayerHost",
            daemon=True,
        )

    @property
    def url(self) -> str:
        port = self.server.server_address[1]
        return f"http://127.0.0.1:{port}/player"

    def start(self) -> None:
        self.thread.start()
        logger.info("Local player page started on 127.0.0.1")

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        logger.info("Local player page stopped")


class WebPlaybackController:
    def __init__(
        self,
        parent: wx.Window,
        spotify: SpotifyClient,
        *,
        on_ready: Callable[[str], None],
        on_error: Callable[[str], None],
        on_playback_update: Callable[[dict], None],
    ) -> None:
        self.spotify = spotify
        self.on_ready = on_ready
        self.on_error = on_error
        self.on_playback_update = on_playback_update
        self.device_id: str | None = None
        self.page_ready = False
        self.closed = False
        self.playback_state_callbacks: list[Callable[[dict], None]] = []
        self.volume_callbacks: list[Callable[[int | None], None]] = []
        self.server: PlayerPageServer | None = None
        self.webview: wx.html2.WebView | None = None

        backend = (
            wx.html2.WebViewBackendEdge
            if sys.platform == "win32"
            else wx.html2.WebViewBackendDefault
        )
        if not wx.html2.WebView.IsBackendAvailable(backend):
            if sys.platform == "win32":
                raise RuntimeError(
                    "BlindSpot's player requires Microsoft WebView2. "
                    "Install the Evergreen WebView2 Runtime and restart BlindSpot."
                )
            raise RuntimeError(
                "BlindSpot could not start the system web browser component."
            )

        self.server = PlayerPageServer()
        self.server.start()
        self.webview = wx.html2.WebView.New(
            parent,
            size=(1, 1),
            backend=backend,
        )
        self.webview.SetPosition((-10000, -10000))
        self.webview.AddScriptMessageHandler("blindspot")
        self.webview.Bind(
            wx.html2.EVT_WEBVIEW_SCRIPT_MESSAGE_RECEIVED,
            self._on_message,
        )
        self.webview.Bind(wx.html2.EVT_WEBVIEW_LOADED, self._on_loaded)
        self.webview.Bind(wx.html2.EVT_WEBVIEW_ERROR, self._on_webview_error)
        self.webview.LoadURL(self.server.url)
        logger.info("Hidden web player created backend=%s", backend)

    @property
    def ready(self) -> bool:
        return bool(self.device_id)

    def provide_token(self) -> None:
        def obtain() -> None:
            try:
                token = self.spotify.access_token()
            except Exception as error:
                logger.exception("Could not obtain token for web player")
                wx.CallAfter(self.on_error, str(error))
                return
            script = f"window.blindSpotProvideToken({json.dumps(token)});"
            wx.CallAfter(self._run_script, script)

        threading.Thread(
            target=obtain,
            name="BlindSpotPlayerToken",
            daemon=True,
        ).start()

    def activate(self) -> None:
        self._run_script("window.blindSpotActivate();")

    def request_playback_state(self, callback: Callable[[dict], None]) -> None:
        self.playback_state_callbacks.append(callback)
        self._run_script("window.blindSpotRequestPlaybackState();")

    def toggle_playback(self) -> None:
        self._run_script("window.blindSpotTogglePlayback();")

    def previous_track(self) -> None:
        self._run_script("window.blindSpotPreviousTrack();")

    def next_track(self) -> None:
        self._run_script("window.blindSpotNextTrack();")

    def seek_relative(self, delta_ms: int) -> None:
        self._run_script(f"window.blindSpotSeekRelative({int(delta_ms)});")

    def seek_to(self, position_ms: int) -> None:
        self._run_script(f"window.blindSpotSeekTo({int(position_ms)});")

    def adjust_volume(
        self,
        delta_percent: int,
        callback: Callable[[int | None], None],
    ) -> None:
        self.volume_callbacks.append(callback)
        self._run_script(f"window.blindSpotAdjustVolume({int(delta_percent)});")

    def toggle_mute(self, callback: Callable[[int | None], None]) -> None:
        self.volume_callbacks.append(callback)
        self._run_script("window.blindSpotToggleMute();")

    def _run_script(self, script: str) -> None:
        if not self.closed and self.webview:
            self.webview.RunScriptAsync(script)

    def _on_message(self, event: wx.html2.WebViewEvent) -> None:
        try:
            message = json.loads(event.GetString())
        except (TypeError, ValueError):
            logger.warning("Ignoring malformed player message")
            return
        message_type = message.get("type")
        if message_type != "playback_update":
            logger.info("Web player message type=%s", message_type)
        if message_type in {"page_ready", "sdk_ready", "token_required"}:
            self.page_ready = True
            self.provide_token()
        elif message_type == "ready":
            self.device_id = message.get("device_id")
            if self.device_id:
                logger.info("BlindSpot Spotify device is ready")
                self.on_ready(self.device_id)
        elif message_type == "not_ready":
            self.device_id = None
            self.on_error("BlindSpot's Spotify playback device went offline.")
        elif message_type == "autoplay_failed":
            self.on_error(
                "The browser blocked automatic playback. "
                "Press Play again to activate BlindSpot's player."
            )
        elif message_type == "playback_state":
            if self.playback_state_callbacks:
                callback = self.playback_state_callbacks.pop(0)
                callback(message.get("state") or {})
        elif message_type == "playback_update":
            self.on_playback_update(message.get("state") or {})
        elif message_type == "volume_result":
            if self.volume_callbacks:
                callback = self.volume_callbacks.pop(0)
                volume = message.get("volume")
                callback(int(volume) if volume is not None else None)
        elif message_type == "error":
            source = message.get("source", "player")
            detail = message.get("message", "Unknown Spotify player error")
            logger.error("Web player error source=%s message=%s", source, detail)
            if (
                source == "playback_error"
                and "no list was loaded" in detail.casefold()
            ):
                self.on_error("No tracks.")
            else:
                self.on_error(f"Spotify {source}: {detail}")

    def _on_webview_error(self, event: wx.html2.WebViewEvent) -> None:
        message = event.GetString() or "The web player page could not load."
        logger.error("Web player load error: %s", message)
        self.on_error(message)

    def _on_loaded(self, event: wx.html2.WebViewEvent) -> None:
        logger.info("Web player loaded URL=%s", event.GetURL())

    def close(self) -> None:
        self.closed = True
        if self.webview:
            self.webview.Destroy()
            self.webview = None
        if self.server:
            self.server.close()
            self.server = None
