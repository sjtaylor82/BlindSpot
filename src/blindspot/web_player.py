from __future__ import annotations

import http.server
import json
import logging
import mimetypes
import sys
import threading
import urllib.parse
from pathlib import Path
from collections.abc import Callable

import wx
import wx.html2

from . import messages as msg
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
      const directAudio = new Audio();
      directAudio.preload = "metadata";
      let directItem = null;
      let directActive = false;
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
          sent_at_ms: Date.now(),
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

      function serializeDirectState() {
        if (!directItem || !directActive) {
          return null;
        }
        const duration = Number.isFinite(directAudio.duration)
          ? Math.round(directAudio.duration * 1000)
          : Number(directItem.duration_ms || 0);
        return {
          progress_ms: Math.round(directAudio.currentTime * 1000),
          sent_at_ms: Date.now(),
          is_playing: !directAudio.paused && !directAudio.ended,
          context_uri: null,
          direct_audio: true,
          item: {...directItem, duration_ms: duration}
        };
      }

      function sendDirectState() {
        const state = serializeDirectState();
        if (state) {
          send("playback_update", {state});
        }
      }

      for (const eventName of [
        "loadedmetadata", "play", "pause", "seeked", "ended", "durationchange"
      ]) {
        directAudio.addEventListener(eventName, sendDirectState);
      }
      directAudio.addEventListener("error", () => {
        const detail = directAudio.error
          ? `Media error ${directAudio.error.code}`
          : "The audio stream could not be played.";
        send("error", {source: "direct audio", message: detail});
      });
      setInterval(() => {
        if (directActive && !directAudio.paused) {
          sendDirectState();
        }
      }, 1000);

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
            if (directActive && eventName === "playback_error") {
              return;
            }
            send("error", {source: eventName, message});
          });
        }
        player.addListener("autoplay_failed", () => {
          send("autoplay_failed");
        });
        player.addListener("player_state_changed", state => {
          if (state && !state.paused && directActive) {
            directAudio.pause();
            directActive = false;
          }
          if (directActive) {
            return;
          }
          send("playback_update", {state: serializeState(state)});
        });
        player.connect().then(success => {
          send("connection_result", {success});
          if (success && !playbackSnapshotTimer) {
            playbackSnapshotTimer = setInterval(() => {
              if (directActive) {
                return;
              }
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
        if (directActive) {
          send("playback_state", {state: serializeDirectState()});
          return;
        }
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
        if (directActive) {
          if (directAudio.paused) {
            directAudio.play().catch(error => reportCommandError("playback", error));
          } else {
            directAudio.pause();
          }
          return;
        }
        if (player) {
          player.togglePlay().catch(error => reportCommandError("playback", error));
        }
      };
      window.blindSpotPause = () => {
        if (directActive) {
          directAudio.pause();
          return;
        }
        if (player) {
          player.pause().catch(error => reportCommandError("pause", error));
        }
      };
      window.blindSpotPreviousTrack = () => {
        if (directActive) {
          return;
        }
        if (player) {
          player.previousTrack()
            .catch(error => reportCommandError("previous track", error));
        }
      };
      window.blindSpotNextTrack = () => {
        if (directActive) {
          return;
        }
        if (player) {
          player.nextTrack()
            .catch(error => reportCommandError("next track", error));
        }
      };
      window.blindSpotSeekRelative = deltaMs => {
        if (directActive) {
          const maximum = Number.isFinite(directAudio.duration)
            ? Math.max(0, directAudio.duration - 0.01)
            : Number.MAX_SAFE_INTEGER;
          directAudio.currentTime = Math.min(
            maximum, Math.max(0, directAudio.currentTime + deltaMs / 1000)
          );
          return;
        }
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
        if (directActive) {
          directAudio.currentTime = Math.max(0, positionMs / 1000);
          return;
        }
        if (player) {
          player.seek(Math.max(0, positionMs))
            .catch(error => reportCommandError("seek", error));
        }
      };
      window.blindSpotSeekAndPlay = positionMs => {
        if (directActive) {
          directAudio.currentTime = Math.max(0, positionMs / 1000);
          directAudio.play().catch(error => reportCommandError("seek", error));
          return;
        }
        if (player) {
          player.seek(Math.max(0, positionMs))
            .then(() => player.resume())
            .catch(error => reportCommandError("seek", error));
        }
      };
      window.blindSpotAdjustVolume = deltaPercent => {
        volumeCommands = volumeCommands.then(() => {
          if (directActive) {
            const target = Math.min(1, Math.max(0, directAudio.volume + deltaPercent / 100));
            directAudio.volume = target;
            send("volume_result", {volume: Math.round(target * 100)});
            return;
          }
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
      window.blindSpotSetVolume = volumePercent => {
        volumeCommands = volumeCommands.then(() => {
          if (directActive) {
            directAudio.volume = Math.min(1, Math.max(0, volumePercent / 100));
            return;
          }
          if (!player) {
            return;
          }
          const target = Math.min(1, Math.max(0, volumePercent / 100));
          return player.setVolume(target);
        }).catch(error => reportCommandError("volume", error));
      };
      window.blindSpotToggleMute = () => {
        volumeCommands = volumeCommands.then(() => {
          if (directActive) {
            directAudio.muted = !directAudio.muted;
            send("volume_result", {
              volume: directAudio.muted ? 0 : Math.round(directAudio.volume * 100)
            });
            return;
          }
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
      window.blindSpotPlayDirect = (url, item, positionMs) => {
        directAudio.pause();
        directItem = item;
        directActive = true;
        if (player) {
          player.getCurrentState().then(state => {
            if (state && !state.paused) {
              player.pause().catch(() => {});
            }
          }).catch(() => {});
        }
        directAudio.src = url;
        directAudio.load();
        const start = () => {
          directAudio.removeEventListener("loadedmetadata", start);
          if (positionMs > 0) {
            directAudio.currentTime = positionMs / 1000;
          }
          directAudio.play().catch(error => reportCommandError("direct audio", error));
        };
        directAudio.addEventListener("loadedmetadata", start);
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
        media: dict[str, Path] = {}
        self.media = media

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                path = urllib.parse.urlsplit(self.path).path
                if path.startswith("/media/"):
                    self._send_media(media.get(path.removeprefix("/media/")))
                    return
                if path not in ("/", "/player"):
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)

            def _send_media(self, path: Path | None) -> None:
                if path is None or not path.is_file():
                    self.send_error(404)
                    return
                size = path.stat().st_size
                start, end = 0, max(0, size - 1)
                range_header = self.headers.get("Range", "")
                if range_header.startswith("bytes="):
                    try:
                        first, last = range_header[6:].split("-", 1)
                        start = int(first) if first else 0
                        end = min(end, int(last)) if last else end
                    except ValueError:
                        self.send_error(416)
                        return
                if start < 0 or start > end or start >= size:
                    self.send_error(416)
                    return
                length = end - start + 1
                self.send_response(206 if range_header else 200)
                self.send_header(
                    "Content-Type",
                    mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                )
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(length))
                if range_header:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.end_headers()
                with path.open("rb") as source:
                    source.seek(start)
                    remaining = length
                    while remaining:
                        block = source.read(min(1024 * 1024, remaining))
                        if not block:
                            break
                        self.wfile.write(block)
                        remaining -= len(block)

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

    def media_url(self, key: str, path: Path) -> str:
        safe_key = urllib.parse.quote(key, safe="")
        self.media[safe_key] = path.resolve()
        port = self.server.server_address[1]
        return f"http://127.0.0.1:{port}/media/{safe_key}"

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
        initial_volume_percent: int = 80,
    ) -> None:
        self.spotify = spotify
        self.on_ready = on_ready
        self.on_error = on_error
        self.on_playback_update = on_playback_update
        self.initial_volume_percent = min(
            100,
            max(0, int(initial_volume_percent)),
        )
        self.device_id: str | None = None
        self.page_ready = False
        self.closed = False
        self.playback_state_callbacks: list[Callable[[dict], None]] = []
        self.volume_callbacks: list[Callable[[int | None], None]] = []
        self.pending_direct: tuple[str, dict, int] | None = None
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
                    msg.WEBVIEW2_REQUIRED
                )
            raise RuntimeError(msg.BROWSER_COMPONENT_FAILED)

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

    def pause(self) -> None:
        self._run_script("window.blindSpotPause();")

    def previous_track(self) -> None:
        self._run_script("window.blindSpotPreviousTrack();")

    def next_track(self) -> None:
        self._run_script("window.blindSpotNextTrack();")

    def seek_relative(self, delta_ms: int) -> None:
        self._run_script(f"window.blindSpotSeekRelative({int(delta_ms)});")

    def seek_to(self, position_ms: int) -> None:
        self._run_script(f"window.blindSpotSeekTo({int(position_ms)});")

    def seek_and_play(self, position_ms: int) -> None:
        self._run_script(f"window.blindSpotSeekAndPlay({int(position_ms)});")

    def play_direct(self, url: str, item: dict, position_ms: int = 0) -> None:
        if not self.page_ready:
            self.pending_direct = (url, item, position_ms)
            return
        self._run_script(
            "window.blindSpotPlayDirect("
            f"{json.dumps(url)}, {json.dumps(item)}, {int(position_ms)});"
        )

    def serve_media(self, key: str, path: Path) -> str:
        if not self.server:
            return ""
        return self.server.media_url(key, path)

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
            if self.pending_direct:
                url, item, position_ms = self.pending_direct
                self.pending_direct = None
                self.play_direct(url, item, position_ms)
            if getattr(self.spotify, "connected", True):
                self.provide_token()
        elif message_type == "ready":
            self.device_id = message.get("device_id")
            if self.device_id:
                logger.info("BlindSpot Spotify device is ready")
                self._run_script(
                    "window.blindSpotSetVolume("
                    f"{self.initial_volume_percent});"
                )
                self.on_ready(self.device_id)
        elif message_type == "not_ready":
            self.device_id = None
            self.on_error(msg.PLAYBACK_DEVICE_OFFLINE)
        elif message_type == "autoplay_failed":
            self.on_error(msg.AUTOPLAY_BLOCKED)
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
            detail = message.get("message", msg.UNKNOWN_PLAYER_ERROR)
            logger.error("Web player error source=%s message=%s", source, detail)
            if (source == "direct audio"):
                self.on_error(detail)
            elif (
                source == "playback_error"
                and "no list was loaded" in detail.casefold()
            ):
                self.on_error(msg.NO_TRACKS)
            else:
                self.on_error(msg.spotify_player_error(source, detail))

    def _on_webview_error(self, event: wx.html2.WebViewEvent) -> None:
        message = event.GetString() or msg.WEB_PLAYER_PAGE_FAILED
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
