from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .models import ItemKind, SpotifyItem
from . import messages as msg
from .network import TLS_CONTEXT
from .portable import PortableStore

logger = logging.getLogger("blindspot.spotify")

API_ROOT = "https://api.spotify.com/v1"
AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
REDIRECT_URI = "http://127.0.0.1:43821/callback"
SCOPES = (
    "user-read-private user-read-email user-library-read user-library-modify "
    "playlist-read-private playlist-modify-public playlist-modify-private "
    "user-read-playback-state user-read-currently-playing "
    "user-read-playback-position "
    "user-read-recently-played "
    "user-modify-playback-state streaming"
)
ALTERNATE_VERSION_WORDS = (
    r"live|acoustic|unplugged|demo|session|rehearsal|"
    r"remaster(?:ed)?|radio edit|single edit|edit|"
    r"mono|stereo|remix(?:ed)?|mix|version|take|re-record(?:ed|ing)?"
)
VERSION_QUALIFIER = re.compile(
    rf"\s*[\(\[].*?\b(?:{ALTERNATE_VERSION_WORDS})\b.*?[\)\]]",
    re.IGNORECASE,
)
VERSION_SUFFIX = re.compile(
    rf"\s*(?:[-–—:,]\s*).*?\b(?:{ALTERNATE_VERSION_WORDS})\b.*$",
    re.IGNORECASE,
)
SEARCH_WORD = re.compile(r"[^\W_]+|\d+", re.UNICODE)


def _search_normalized(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    value = "".join(
        character
        for character in value
        if not unicodedata.combining(character)
    )
    return " ".join(SEARCH_WORD.findall(value))


def _base_track_title(value: str) -> str:
    title = VERSION_QUALIFIER.sub("", value)
    title = VERSION_SUFFIX.sub("", title)
    return " ".join(title.split()).strip(" -–—:,") or value


def _primary_track_artist(value: str) -> str:
    return " ".join(value.split(",", 1)[0].split())


def _played_at_label(value: str) -> str:
    try:
        played_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "played recently"
    local = played_at.astimezone()
    return local.strftime("played %A %d %B at %I:%M %p").replace(
        " 0",
        " ",
    )


class SpotifyError(RuntimeError):
    pass


class PlaylistContentsUnavailable(SpotifyError):
    pass


class RecentlyPlayedPermissionRequired(SpotifyError):
    pass


@dataclass(slots=True)
class AuthorizationRequest:
    url: str
    verifier: str
    state: str


class SpotifyClient:
    def __init__(self, store: PortableStore) -> None:
        self.store = store
        self.token = store.read("authentication.json", {}) or {}
        self._token_lock = threading.Lock()

    @property
    def client_id(self) -> str:
        return str(self.token.get("client_id", "")).strip()

    @property
    def connected(self) -> bool:
        return bool(self.client_id and self.token.get("refresh_token"))

    def has_scope(self, scope: str) -> bool:
        return scope in set(str(self.token.get("scope", "")).split())

    @property
    def web_playback_authorized(self) -> bool:
        granted = set(str(self.token.get("scope", "")).split())
        required = {"streaming", "user-read-private", "user-read-email"}
        return bool(
            self.connected
            and required.issubset(granted)
        )

    def access_token(self) -> str:
        self._refresh_if_needed()
        token = self.token.get("access_token")
        if not token:
            raise SpotifyError(msg.CONNECT_FIRST)
        return str(token)

    def set_client_id(self, client_id: str) -> None:
        self.token["client_id"] = client_id.strip()
        self.store.write("authentication.json", self.token)

    def begin_authorization(
        self,
        *,
        force_dialog: bool = False,
    ) -> AuthorizationRequest:
        if not self.client_id:
            raise SpotifyError(msg.ENTER_CLIENT_ID)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        state = secrets.token_urlsafe(24)
        query = urllib.parse.urlencode(
            {
                "client_id": self.client_id,
                "response_type": "code",
                "redirect_uri": REDIRECT_URI,
                "scope": SCOPES,
                "code_challenge_method": "S256",
                "code_challenge": challenge,
                "state": state,
                "show_dialog": "true" if force_dialog else "false",
            }
        )
        logger.info("Created Spotify PKCE authorization request")
        return AuthorizationRequest(f"{AUTHORIZE_URL}?{query}", verifier, state)

    def complete_authorization(self, code: str, verifier: str) -> None:
        logger.info("Exchanging Spotify authorization code")
        client_id = self.client_id
        self.token = self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": client_id,
                "code_verifier": verifier,
            }
        )
        self.token["client_id"] = client_id
        self._save_token()
        logger.info("Spotify authorization completed and token was saved")

    def sign_out(self) -> None:
        self.token = {}
        self.store.remove("authentication.json")

    def search(
        self,
        query: str,
        category: str,
        offset: int = 0,
    ) -> list[SpotifyItem]:
        logger.info(
            "Searching Spotify category=%s offset=%d",
            category,
            offset,
        )
        types = (
            "track,album,artist,playlist,show,episode,audiobook"
            if category == "all"
            else category
        )
        request_limit = 4 if category == "all" else 10
        offsets = (
            [offset]
            if category == "all"
            else [value for value in (offset, offset + 10) if value <= 1000]
        )
        payloads = [
            self._request(
                "GET",
                "/search",
                query={
                    "q": query,
                    "type": types,
                    "limit": request_limit,
                    "offset": offset,
                    "include_external": "audio",
                },
            )
            for offset in offsets
        ]
        items: list[SpotifyItem] = []
        keys = (
            ("tracks", ItemKind.TRACK),
            ("albums", ItemKind.ALBUM),
            ("artists", ItemKind.ARTIST),
            ("playlists", ItemKind.PLAYLIST),
            ("shows", ItemKind.SHOW),
            ("episodes", ItemKind.EPISODE),
            ("audiobooks", ItemKind.AUDIOBOOK),
        )
        for key, kind in keys:
            values = [
                value
                for payload in payloads
                for value in (payload.get(key) or {}).get("items", [])
                if value
            ]
            if not values:
                continue
            if category == "all":
                items.append(
                    SpotifyItem(key, ItemKind.HEADING, key.title())
                )
            items.extend(
                self._map_item(value, kind)
                for value in values
            )
        next_offset = offset + (request_limit if category == "all" else 20)
        has_more = next_offset <= 1000 and any(
            int((payload.get(key) or {}).get("total") or 0) > next_offset
            for payload in payloads
            for key, _kind in keys
        )
        if has_more:
            items.append(
                SpotifyItem(
                    "__load_more__",
                    ItemKind.HEADING,
                    "Load more results",
                    raw={
                        "load_more": True,
                        "next_offset": next_offset,
                    },
                )
            )
        return items

    def children(self, item: SpotifyItem) -> list[SpotifyItem]:
        logger.info(
            "Loading children kind=%s id=%s name=%r",
            item.kind,
            item.id,
            item.name,
        )
        if item.kind == ItemKind.ALBUM:
            data = self._request("GET", f"/albums/{item.id}/tracks", query={"limit": 50})
            items = [
                self._map_item(x, ItemKind.TRACK, album=item.name)
                for x in data["items"]
            ]
            logger.info("Loaded %d album tracks", len(items))
            return items
        if item.kind == ItemKind.ARTIST:
            data = self._request(
                "GET", f"/artists/{item.id}/albums", query={"limit": 50}
            )
            return [self._map_item(x, ItemKind.ALBUM) for x in data["items"]]
        if item.kind == ItemKind.PLAYLIST:
            try:
                entries = self._paged_items(
                    "GET",
                    f"/playlists/{item.id}/items",
                    query={"limit": 50},
                )
            except SpotifyError as error:
                if "Spotify returned 403:" not in str(error):
                    raise
                raise PlaylistContentsUnavailable(
                    msg.PLAYLIST_ITEMS_UNAVAILABLE
                ) from error
            values = []
            for entry in entries:
                if not entry:
                    continue
                value = entry.get("item") or entry.get("track") or entry
                if value.get("id"):
                    values.append(self._map_item(value, self._kind_for(value)))
            return values
        if item.kind == ItemKind.SHOW:
            values = self._paged_items(
                "GET", f"/shows/{item.id}/episodes", query={"limit": 50}
            )
            episodes = [
                self._map_item(x, ItemKind.EPISODE, album=item.name)
                for x in values
            ]
            for episode in episodes:
                if not episode.artist:
                    episode.artist = item.artist
                episode.raw.setdefault(
                    "show",
                    {
                        "id": item.id,
                        "name": item.name,
                        "publisher": item.artist,
                    },
                )
            return episodes
        if item.kind == ItemKind.AUDIOBOOK:
            return self.audiobook_chapters(item)
        return []

    def album_for_track(self, item: SpotifyItem) -> SpotifyItem:
        album = item.raw.get("album") or {}
        if not album.get("id"):
            track = self._request("GET", f"/tracks/{item.id}")
            album = track.get("album") or {}
        if not album.get("id"):
            raise SpotifyError(msg.ALBUM_NOT_PROVIDED)
        return self._map_item(album, ItemKind.ALBUM)

    def liked_songs(self) -> list[SpotifyItem]:
        data = self._request("GET", "/me/tracks", query={"limit": 50})
        return [
            self._map_item(x["track"], ItemKind.TRACK)
            for x in data.get("items", [])
            if x.get("track")
        ]

    def recently_played(self) -> list[SpotifyItem]:
        if not self.has_scope("user-read-recently-played"):
            raise RecentlyPlayedPermissionRequired(
                msg.RECENT_PERMISSION_REQUIRED
            )
        data = self._request(
            "GET",
            "/me/player/recently-played",
            query={"limit": 50},
        )
        items = []
        seen_tracks: set[str] = set()
        for value in data.get("items", []):
            track = value.get("track")
            if not track:
                continue
            track_key = str(track.get("id") or track.get("uri") or "")
            if track_key and track_key in seen_tracks:
                continue
            if track_key:
                seen_tracks.add(track_key)
            item = self._map_item(track, ItemKind.TRACK)
            item.raw["played_at"] = value.get("played_at", "")
            item.raw["played_at_label"] = _played_at_label(
                str(value.get("played_at") or "")
            )
            items.append(item)
        return items

    def saved_audiobooks(self) -> list[SpotifyItem]:
        values = self._paged_items(
            "GET",
            "/me/audiobooks",
            query={"limit": 50},
        )
        return [
            self._map_item(value, ItemKind.AUDIOBOOK)
            for value in values
            if value and value.get("id")
        ]

    def saved_albums(self) -> list[SpotifyItem]:
        values = self._paged_items("GET", "/me/albums", query={"limit": 50})
        return [
            self._map_item(entry["album"], ItemKind.ALBUM)
            for entry in values
            if entry and entry.get("album")
        ]

    def saved_shows(self) -> list[SpotifyItem]:
        values = self._paged_items("GET", "/me/shows", query={"limit": 50})
        return [
            self._map_item(entry["show"], ItemKind.SHOW)
            for entry in values
            if entry and entry.get("show")
        ]

    def saved_episodes(self) -> list[SpotifyItem]:
        values = self._paged_items(
            "GET",
            "/me/episodes",
            query={"limit": 50},
        )
        return [
            self._map_item(entry["episode"], ItemKind.EPISODE)
            for entry in values
            if entry and entry.get("episode")
        ]

    def audiobook_chapters(self, audiobook: SpotifyItem) -> list[SpotifyItem]:
        values = self._paged_items(
            "GET",
            f"/audiobooks/{audiobook.id}/chapters",
            query={"limit": 50},
        )
        chapters = []
        for value in values:
            if not value or not value.get("id"):
                continue
            chapter = self._map_item(
                value,
                ItemKind.CHAPTER,
                album=audiobook.name,
            )
            authors = audiobook.raw.get("authors") or []
            chapter.artist = ", ".join(
                author.get("name", "")
                for author in authors
                if author.get("name")
            )
            resume = value.get("resume_point") or {}
            resume_ms = int(resume.get("resume_position_ms") or 0)
            chapter.raw["resume_position_ms"] = resume_ms
            if resume.get("fully_played"):
                chapter.raw["resume_position_label"] = "finished"
            elif resume_ms:
                minutes, seconds = divmod(resume_ms // 1000, 60)
                chapter.raw["resume_position_label"] = (
                    f"resume at {minutes} minutes {seconds} seconds"
                )
            chapters.append(chapter)
        return chapters

    def _paged_items(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any],
    ) -> list[dict[str, Any]]:
        page_query = dict(query)
        values = []
        while True:
            data = self._request(method, path, query=page_query)
            page = [value for value in data.get("items", []) if value]
            values.extend(page)
            total = int(data.get("total") or len(values))
            if not page or len(values) >= total:
                return values
            page_query["offset"] = len(values)

    def user_playlists(self) -> list[SpotifyItem]:
        profile = self._request("GET", "/me")
        user_id = profile.get("id", "")
        data = self._request("GET", "/me/playlists", query={"limit": 50})
        playlists = []
        for value in data.get("items", []):
            if not value:
                continue
            item = self._map_item(value, ItemKind.PLAYLIST)
            owner = value.get("owner") or {}
            owned = owner.get("id") == user_id
            editable = bool(
                owned or value.get("collaborative")
            )
            item.raw["owned"] = owned
            item.raw["editable"] = editable
            playlists.append(item)
        return playlists

    def add_to_playlist(self, playlist: SpotifyItem, item: SpotifyItem) -> None:
        self._request(
            "POST",
            f"/playlists/{playlist.id}/items",
            body={"uris": [item.uri]},
        )

    def create_playlist(self, name: str, public: bool = False) -> SpotifyItem:
        value = self._request(
            "POST",
            "/me/playlists",
            body={"name": name, "public": public},
        )
        item = self._map_item(value, ItemKind.PLAYLIST)
        item.raw["editable"] = True
        item.raw["owned"] = True
        return item

    def rename_playlist(self, playlist: SpotifyItem, name: str) -> None:
        self._request(
            "PUT",
            f"/playlists/{playlist.id}",
            body={"name": name},
            allow_empty=True,
        )

    def remove_playlist_from_library(self, playlist: SpotifyItem) -> None:
        self._request(
            "DELETE",
            "/me/library",
            query={"uris": playlist.uri},
            allow_empty=True,
        )

    def remove_from_playlist(
        self,
        playlist: SpotifyItem,
        item: SpotifyItem,
    ) -> None:
        self._request(
            "DELETE",
            f"/playlists/{playlist.id}/items",
            body={"items": [{"uri": item.uri}]},
        )

    def reorder_playlist_item(
        self,
        playlist: SpotifyItem,
        source_index: int,
        target_index: int,
    ) -> None:
        insert_before = (
            target_index
            if target_index < source_index
            else target_index + 1
        )
        self._request(
            "PUT",
            f"/playlists/{playlist.id}/items",
            body={
                "range_start": source_index,
                "insert_before": insert_before,
                "range_length": 1,
            },
            allow_empty=True,
        )

    def alternate_versions(self, item: SpotifyItem) -> list[SpotifyItem]:
        title = _base_track_title(item.name)
        artist = _primary_track_artist(item.artist)
        query = f'track:"{title}"'
        if artist:
            query += f' artist:"{artist}"'
        payloads = [
            self._request(
                "GET",
                "/search",
                query={
                    "q": query,
                    "type": "track",
                    "limit": 10,
                    "offset": offset,
                    "include_external": "audio",
                },
            )
            for offset in (0, 10)
        ]
        wanted_title = _search_normalized(title)
        wanted_artist = _search_normalized(artist)
        source_isrc = _search_normalized(
            str((item.raw.get("external_ids") or {}).get("isrc") or "")
        )
        results: list[SpotifyItem] = []
        seen: set[str] = {item.uri or item.id}
        for payload in payloads:
            for value in (payload.get("tracks") or {}).get("items", []):
                if not value:
                    continue
                candidate = self._map_item(value, ItemKind.TRACK)
                key = candidate.uri or candidate.id
                candidate_artist = _search_normalized(
                    _primary_track_artist(candidate.artist)
                )
                candidate_isrc = _search_normalized(
                    str(
                        (candidate.raw.get("external_ids") or {}).get(
                            "isrc"
                        )
                        or ""
                    )
                )
                if (
                    not key
                    or key in seen
                    or _search_normalized(
                        _base_track_title(candidate.name)
                    )
                    != wanted_title
                    or candidate_artist != wanted_artist
                    or (
                        source_isrc
                        and candidate_isrc
                        and candidate_isrc == source_isrc
                    )
                ):
                    continue
                seen.add(key)
                results.append(candidate)
        return results

    def replace_playlist_item(
        self,
        playlist: SpotifyItem,
        original: SpotifyItem,
        replacement: SpotifyItem,
        position: int,
    ) -> None:
        self._request(
            "POST",
            f"/playlists/{playlist.id}/items",
            body={"uris": [replacement.uri], "position": position},
        )
        self._request(
            "DELETE",
            f"/playlists/{playlist.id}/items",
            body={"items": [{"uri": original.uri}]},
        )

    def queue(self) -> list[SpotifyItem]:
        data = self._request("GET", "/me/player/queue")
        values = []
        current = data.get("currently_playing")
        if current:
            values.append(self._map_item(current, self._kind_for(current)))
        values.extend(
            self._map_item(x, self._kind_for(x))
            for x in data.get("queue", [])
        )
        return values

    def next_queued(self) -> SpotifyItem | None:
        data = self._request("GET", "/me/player/queue")
        queue = data.get("queue", [])
        return (
            self._map_item(queue[0], self._kind_for(queue[0]))
            if queue
            else None
        )

    def playback(self) -> SpotifyItem | None:
        data = self._request("GET", "/me/player/currently-playing", allow_empty=True)
        value = data.get("item") if data else None
        return self._map_item(value, self._kind_for(value)) if value else None

    def playback_state(self) -> dict[str, Any]:
        return self._request("GET", "/me/player", allow_empty=True)

    def available_devices(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/me/player/devices")
        return [
            device
            for device in data.get("devices", [])
            if device.get("id") and not device.get("is_restricted")
        ]

    def transfer_playback(self, device_id: str, *, play: bool = True) -> None:
        self._request(
            "PUT",
            "/me/player",
            body={"device_ids": [device_id], "play": play},
            allow_empty=True,
        )

    def play(self, item: SpotifyItem, device_id: str | None = None) -> None:
        body = {"uris": [item.uri]} if item.playable else {"context_uri": item.uri}
        query = {"device_id": device_id} if device_id else None
        try:
            self._request(
                "PUT",
                "/me/player/play",
                query=query,
                body=body,
                allow_empty=True,
            )
        except SpotifyError as error:
            if device_id or "No active device found" not in str(error):
                raise
            logger.info("No active device; requesting Spotify Connect devices")
            device = self._preferred_device()
            logger.info(
                "Retrying playback on device name=%r type=%s",
                device.get("name", "Unknown"),
                device.get("type", "unknown"),
            )
            self._request(
                "PUT",
                "/me/player/play",
                query={"device_id": device["id"]},
                body=body,
                allow_empty=True,
            )

    def play_at(
        self,
        item: SpotifyItem,
        position_ms: int,
        device_id: str,
        context_uri: str = "",
    ) -> None:
        body = {
            "uris": [item.uri],
            "position_ms": max(0, int(position_ms)),
        }
        if context_uri:
            body = {
                "context_uri": context_uri,
                "offset": {"uri": item.uri},
                "position_ms": max(0, int(position_ms)),
            }
        try:
            self._request(
                "PUT",
                "/me/player/play",
                query={"device_id": device_id},
                body=body,
                allow_empty=True,
            )
        except SpotifyError:
            if not context_uri:
                raise
            logger.info(
                "Spotify rejected saved playback context; "
                "resuming the individual track"
            )
            self._request(
                "PUT",
                "/me/player/play",
                query={"device_id": device_id},
                body={
                    "uris": [item.uri],
                    "position_ms": max(0, int(position_ms)),
                },
                allow_empty=True,
            )

    def _preferred_device(self) -> dict[str, Any]:
        devices = self.available_devices()
        if not devices:
            raise SpotifyError(
                msg.NO_CONTROLLABLE_DEVICE
            )
        return next(
            (device for device in devices if device.get("is_active")),
            devices[0],
        )

    def add_to_queue(
        self,
        item: SpotifyItem,
        device_id: str | None = None,
    ) -> None:
        query = {"uri": item.uri}
        if device_id:
            query["device_id"] = device_id
        self._request(
            "POST",
            "/me/player/queue",
            query=query,
            allow_empty=True,
        )

    def save(self, item: SpotifyItem) -> None:
        self._request(
            "PUT",
            "/me/library",
            query={"uris": item.uri},
            allow_empty=True,
        )

    def remove(self, item: SpotifyItem) -> None:
        self._request(
            "DELETE",
            "/me/library",
            query={"uris": item.uri},
            allow_empty=True,
        )

    def toggle_saved(self, item: SpotifyItem) -> bool:
        result = self._request(
            "GET",
            "/me/library/contains",
            query={"uris": item.uri},
        )
        is_saved = bool(result and result[0])
        if is_saved:
            self.remove(item)
            return False
        self.save(item)
        return True

    def toggle_playback(self, device_id: str) -> bool:
        state = self.playback_state()
        if state.get("is_playing"):
            self._request(
                "PUT",
                "/me/player/pause",
                query={"device_id": device_id},
                allow_empty=True,
            )
            return False
        self._request(
            "PUT",
            "/me/player/play",
            query={"device_id": device_id},
            allow_empty=True,
        )
        return True

    def pause_playback(self, device_id: str) -> None:
        self._request(
            "PUT",
            "/me/player/pause",
            query={"device_id": device_id},
            allow_empty=True,
        )

    def toggle_shuffle(self, device_id: str) -> bool:
        state = self.playback_state()
        enabled = not bool(state.get("shuffle_state"))
        return self.set_shuffle(enabled, device_id)

    def set_shuffle(self, enabled: bool, device_id: str) -> bool:
        self._request(
            "PUT",
            "/me/player/shuffle",
            query={"state": str(enabled).lower(), "device_id": device_id},
            allow_empty=True,
        )
        return enabled

    def cycle_repeat(self, device_id: str) -> str:
        state = self.playback_state()
        current = state.get("repeat_state", "off")
        target = {"off": "context", "context": "track", "track": "off"}.get(
            current,
            "off",
        )
        return self.set_repeat(target, device_id)

    def set_repeat(self, state: str, device_id: str) -> str:
        self._request(
            "PUT",
            "/me/player/repeat",
            query={"state": state, "device_id": device_id},
            allow_empty=True,
        )
        return state

    def seek_relative(self, delta_ms: int, device_id: str) -> int:
        state = self.playback_state()
        if not state or not state.get("item"):
            raise SpotifyError(msg.NOTHING_CURRENTLY_PLAYING)
        duration = int(state["item"].get("duration_ms", 0) or 0)
        current = int(state.get("progress_ms", 0) or 0)
        target = max(0, current + delta_ms)
        if duration:
            target = min(target, max(0, duration - 1))
        self._request(
            "PUT",
            "/me/player/seek",
            query={"position_ms": target, "device_id": device_id},
            allow_empty=True,
        )
        return target

    def seek_to(self, position_ms: int, device_id: str) -> int:
        state = self.playback_state()
        if not state or not state.get("item"):
            raise SpotifyError(msg.NOTHING_CURRENTLY_PLAYING)
        duration = int(state["item"].get("duration_ms", 0) or 0)
        target = max(0, position_ms)
        if duration:
            target = min(target, max(0, duration - 1))
        self._request(
            "PUT",
            "/me/player/seek",
            query={"position_ms": target, "device_id": device_id},
            allow_empty=True,
        )
        return target

    def adjust_volume(self, delta_percent: int, device_id: str) -> int:
        state = self.playback_state()
        device = state.get("device") if state else None
        if not device:
            raise SpotifyError(msg.PLAYBACK_DEVICE_INACTIVE)
        current = device.get("volume_percent")
        if current is None:
            raise SpotifyError(msg.CURRENT_VOLUME_UNAVAILABLE)
        target = min(100, max(0, int(current) + delta_percent))
        self._request(
            "PUT",
            "/me/player/volume",
            query={"volume_percent": target, "device_id": device_id},
            allow_empty=True,
        )
        return target

    def set_volume(self, volume_percent: int, device_id: str) -> int:
        target = min(100, max(0, int(volume_percent)))
        self._request(
            "PUT",
            "/me/player/volume",
            query={"volume_percent": target, "device_id": device_id},
            allow_empty=True,
        )
        return target

    def next_track(self, device_id: str) -> None:
        self._request(
            "POST",
            "/me/player/next",
            query={"device_id": device_id},
            allow_empty=True,
        )

    def previous_track(self, device_id: str) -> None:
        self._request(
            "POST",
            "/me/player/previous",
            query={"device_id": device_id},
            allow_empty=True,
        )

    def _kind_for(self, value: dict[str, Any] | None) -> ItemKind:
        return ItemKind.EPISODE if value and value.get("type") == "episode" else ItemKind.TRACK

    def _map_item(
        self,
        value: dict[str, Any],
        kind: ItemKind,
        *,
        album: str = "",
    ) -> SpotifyItem:
        artists = ", ".join(x.get("name", "") for x in value.get("artists", []))
        album_value = value.get("album") or {}
        release_date = value.get("release_date", "")
        total = None
        if kind == ItemKind.ALBUM:
            total = value.get("total_tracks")
        elif kind == ItemKind.PLAYLIST:
            tracks = value.get("tracks") or {}
            if isinstance(tracks, dict):
                total = tracks.get("total")
        elif kind == ItemKind.SHOW:
            total = value.get("total_episodes")
            artists = str(value.get("publisher") or "")
        elif kind == ItemKind.AUDIOBOOK:
            total = value.get("total_chapters")
            artists = ", ".join(
                x.get("name", "") for x in value.get("authors", [])
            )
        if kind == ItemKind.EPISODE:
            show = value.get("show") or {}
            album_value = show
            artists = str(show.get("publisher") or "")
            resume = value.get("resume_point") or {}
            resume_ms = int(resume.get("resume_position_ms") or 0)
            if resume.get("fully_played"):
                value["resume_position_label"] = "finished"
            elif resume_ms:
                minutes, seconds = divmod(resume_ms // 1000, 60)
                value["resume_position_label"] = (
                    f"resume at {minutes} minutes {seconds} seconds"
                )
            value["resume_position_ms"] = resume_ms
        return SpotifyItem(
            id=value.get("id", ""),
            kind=kind,
            name=value.get("name", "Untitled"),
            artist=artists,
            album=album or album_value.get("name", ""),
            duration_ms=value.get("duration_ms", 0) or 0,
            explicit=bool(value.get("explicit")),
            year=release_date[:4],
            total=total,
            uri=value.get("uri", ""),
            raw=value,
        )

    def _save_token(self) -> None:
        self.token["expires_at"] = int(time.time()) + int(self.token.get("expires_in", 3600)) - 30
        self.store.write("authentication.json", self.token)

    def _refresh_if_needed(self) -> None:
        if int(self.token.get("expires_at", 0)) > time.time():
            return
        with self._token_lock:
            if int(self.token.get("expires_at", 0)) > time.time():
                return
            refresh = self.token.get("refresh_token")
            if not refresh:
                raise SpotifyError(msg.CONNECT_FIRST)
            refreshed = self._token_request(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": refresh,
                    "client_id": self.client_id,
                }
            )
            refreshed.setdefault("refresh_token", refresh)
            refreshed.setdefault("client_id", self.client_id)
            self.token = refreshed
            self._save_token()

    def _token_request(self, fields: dict[str, str]) -> dict[str, Any]:
        request = urllib.request.Request(
            TOKEN_URL,
            data=urllib.parse.urlencode(fields).encode("ascii"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        return self._open_json(request)

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        allow_empty: bool = False,
    ) -> Any:
        self._refresh_if_needed()
        logger.debug(
            "Spotify request %s %s query_fields=%s",
            method,
            path,
            sorted((query or {}).keys()),
        )
        url = API_ROOT + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self.token['access_token']}",
                "Content-Type": "application/json",
            },
            method=method,
        )
        return self._open_json(request, allow_empty=allow_empty)

    def _open_json(
        self, request: urllib.request.Request, *, allow_empty: bool = False
    ) -> Any:
        try:
            with urllib.request.urlopen(
                request,
                timeout=20,
                context=TLS_CONTEXT,
            ) as response:
                logger.debug(
                    "Spotify response status=%s endpoint=%s",
                    response.status,
                    urllib.parse.urlparse(request.full_url).path,
                )
                payload = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            try:
                message = json.loads(detail).get("error", {})
                if isinstance(message, dict):
                    message = message.get("message", detail)
            except ValueError:
                message = detail
            logger.error(
                "Spotify HTTP error status=%s endpoint=%s message=%s",
                error.code,
                urllib.parse.urlparse(request.full_url).path,
                message,
            )
            raise SpotifyError(msg.spotify_error(error.code, message)) from error
        except OSError as error:
            logger.exception("Spotify connection failed")
            raise SpotifyError(msg.spotify_contact_failed(error)) from error
        if allow_empty or response.status == 204:
            return {}
        if not payload:
            raise SpotifyError(msg.SPOTIFY_EMPTY_RESPONSE)
        return json.loads(payload.decode("utf-8"))
