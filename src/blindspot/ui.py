from __future__ import annotations

import io
import logging
import re
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.request
import uuid
import webbrowser
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import NamedTuple

import wx
import wx.dataview as dv
from accessible_output2.outputs.auto import Auto

from . import __version__
from . import audio_devices
from . import diagnostics
from . import export as exporting
from . import i18n
from . import messages as msg
from . import recent_plays
from .applemusic import (
    CHART_COUNTRIES,
    DEFAULT_COUNTRY as DEFAULT_CHART_COUNTRY,
    DEFAULT_RELEASE_WINDOW,
    GENRES,
    RELEASE_WINDOWS,
    AppleMusicClient,
    country_name,
    loaded_label,
    released_on,
)
from .auth_callback import CallbackServer
from .followed import ARTIST, AUTHOR, FollowedArtists, primary_artist
from .carts import (
    Cart,
    cart_cutoff_state,
    dump_carts,
    load_carts,
    next_cart_number,
)
from .logging_setup import LOG_LEVELS, configure_logging
from .deepl import DeepLClient, TARGET_LANGUAGES
from .lyrics import (
    LRCLibClient,
    Lyrics,
    LyricsUnavailable,
    section_starts,
    section_target,
)
from .lastfm import DEFAULT_API_KEY as DEFAULT_LASTFM_API_KEY, LastfmClient
from .lastfm import GenreTag, SimilarTrack, TaggedItem
from .i18n import ntr, tr, tr_noop
from .historical_charts import HistoricalHot100Client, PROJECT_URL
from .abcclassic import (
    ARCHIVE_URL as CLASSIC_100_ARCHIVE_URL,
    COUNTDOWNS as CLASSIC_100_COUNTDOWNS,
    CURRENT_URL as CLASSIC_100_CURRENT_URL,
    Classic100Client,
    ClassicCountdown,
)
from .rnbooks import (
    COUNTDOWNS as RN_BOOK_COUNTDOWNS,
    NEXT_100_URL as RN_BOOKS_NEXT_URL,
    TOP_100_URL as RN_BOOKS_TOP_URL,
    BookCountdown,
    RNBooksClient,
)
from .triplej import ARCHIVE_URL as TRIPLE_J_ARCHIVE_URL
from .triplej import (
    COUNTDOWNS as TRIPLE_J_COUNTDOWNS,
    Countdown,
    Hottest100Client,
)
from .numberones import COUNTRIES as NUMBER_ONE_COUNTRIES, NumberOnesClient
from .ukcharts import (
    ALBUMS as UK_ALBUMS,
    SINGLES as UK_SINGLES,
    UKChartError,
    UKChartsClient,
    artist_candidates,
    title_candidates,
    weeks_text,
)
from .musicbrainz import CoversUnavailable, CoverResults, MusicBrainzClient
from .wikipedia import SongStory, SongStoryUnavailable, WikipediaClient
from .keymap import (
    ACTIONS_BY_ID,
    CONTEXTS,
    CONTEXT_LABELS,
    KEY_ACTIONS,
    KeyMap,
    chord_from_event,
    conflict_warning,
    warnings_seen,
)
from .models import ItemKind, SpotifyItem, ViewState
from .navigation import NavigationHistory
from .network import TLS_CONTEXT
from .portable import PortableStore, resource_directory
from .podcasts import PodcastDownload, download_episode, find_episode_download
from .rss_podcasts import (
    RSSPodcastError,
    RSSSubscriptionStore,
    feed_episodes,
)
from .transcripts import (
    EpisodeMedia,
    Transcript,
    TranscriptCache,
    TranscriptUnavailable,
    WHISPER_PLAYBACK_OFFSET_MS,
    WhisperTranscriber,
    fetch_publisher_transcript,
    find_episode_media,
)
from .playlist_operations import (
    PlaylistClipboard,
    PlaylistOperations,
    PlaylistSelection,
    locate_playlist_selections,
)
from .spotify import (
    REDIRECT_URI,
    PlaylistContentsUnavailable,
    RecentlyPlayedPermissionRequired,
    SpotifyClient,
    SpotifyError,
    _base_track_title as base_track_title,
)
from .ticketmaster import (
    ConcertEvent,
    ConcertPage,
    EventCategory,
    TICKETMASTER_COUNTRIES,
    TicketmasterClient,
)
from .updates import (
    download_and_install,
    latest_release,
    newer_than,
    supports_automatic_update,
    supports_managed_download,
)
from .web_player import WebPlaybackController

logger = logging.getLogger("blindspot.ui")


def album_artwork_url(item: SpotifyItem) -> str:
    """Return the largest artwork URL supplied by Spotify."""
    images = item.raw.get("images") or []
    available = [image for image in images if image.get("url")]
    if not available:
        return ""
    largest = max(
        available,
        key=lambda image: int(image.get("width") or 0)
        * int(image.get("height") or 0),
    )
    return str(largest["url"])


def download_album_artwork(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "BlindSpot Spotify client"},
    )
    with urllib.request.urlopen(
        request,
        timeout=20,
        context=TLS_CONTEXT,
    ) as response:
        return response.read()


class AlbumArtworkDialog(wx.Dialog):
    def __init__(
        self,
        parent: wx.Window,
        item: SpotifyItem,
        artwork: bytes,
    ) -> None:
        title = tr("Album artwork for {name}").format(name=item.name)
        super().__init__(
            parent,
            title=title,
            size=(700, 760),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.item = item
        self.artwork = artwork
        self.original_image = wx.Image(io.BytesIO(artwork), wx.BITMAP_TYPE_ANY)
        if not self.original_image.IsOk():
            raise ValueError(msg.ALBUM_ARTWORK_INVALID)

        panel = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)
        description = title + (tr(" by {artist}").format(artist=item.artist) if item.artist else "")
        label = wx.StaticText(panel, label=description)
        self.bitmap = wx.StaticBitmap(panel)
        self.bitmap.SetName(description)
        buttons = wx.StdDialogButtonSizer()
        open_button = wx.Button(panel, label=tr("Open in &photo viewer"))
        close_button = wx.Button(panel, wx.ID_CLOSE, tr("&Close"))
        buttons.AddButton(open_button)
        buttons.AddButton(close_button)
        buttons.Realize()
        outer.Add(label, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 10)
        outer.Add(self.bitmap, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        outer.Add(buttons, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 10)
        panel.SetSizer(outer)

        open_button.Bind(wx.EVT_BUTTON, self.on_open_in_photo_viewer)
        close_button.Bind(wx.EVT_BUTTON, lambda event: self.EndModal(wx.ID_CLOSE))
        self.Bind(wx.EVT_SIZE, self.on_size)
        self.SetMinSize((360, 440))
        self.CentreOnParent()
        wx.CallAfter(self.update_bitmap)

    def on_size(self, event: wx.SizeEvent) -> None:
        event.Skip()
        wx.CallAfter(self.update_bitmap)

    def update_bitmap(self) -> None:
        area = self.bitmap.GetClientSize()
        width = max(1, area.width)
        height = max(1, area.height)
        source_width = self.original_image.GetWidth()
        source_height = self.original_image.GetHeight()
        scale = min(width / source_width, height / source_height)
        target_width = max(1, int(source_width * scale))
        target_height = max(1, int(source_height * scale))
        image = self.original_image.Scale(
            target_width,
            target_height,
            wx.IMAGE_QUALITY_HIGH,
        )
        self.bitmap.SetBitmap(wx.Bitmap(image))

    def on_open_in_photo_viewer(self, event: wx.CommandEvent) -> None:
        safe_name = re.sub(r"[^A-Za-z0-9._ -]+", "_", self.item.name).strip()
        path = Path(tempfile.gettempdir()) / f"BlindSpot - {safe_name or 'album artwork'}.jpg"
        path.write_bytes(self.artwork)
        if not wx.LaunchDefaultApplication(str(path)):
            wx.MessageBox(
                msg.ALBUM_ARTWORK_VIEWER_FAILED,
                "BlindSpot",
                wx.OK | wx.ICON_ERROR,
                self,
            )


if sys.platform == "win32":
    class _NamedPageAccessible(wx.Accessible):
        """Expose a notebook page label to MSAA clients such as JAWS."""

        def __init__(self, window, title: str):
            super().__init__(window)
            self._title = title

        def GetName(self, child_id):
            if child_id == wx.ACC_SELF:
                return wx.ACC_OK, self._title
            return wx.ACC_NOT_IMPLEMENTED, ""

        def GetRole(self, child_id):
            if child_id == wx.ACC_SELF:
                return wx.ACC_OK, wx.ROLE_SYSTEM_PROPERTYPAGE
            return wx.ACC_NOT_IMPLEMENTED, wx.ROLE_SYSTEM_PANE


    class _NamedControlAccessible(wx.Accessible):
        """Provide an explicit MSAA name for a native form control."""

        def __init__(self, window: wx.Window, name: str) -> None:
            super().__init__(window)
            self._name = name

        def GetName(self, child_id):
            if child_id == wx.ACC_SELF:
                return wx.ACC_OK, self._name
            return wx.ACC_NOT_IMPLEMENTED, ""
    class _SilentLabelAccessible(wx.Accessible):
        """Hide a painted label from screen readers that would announce it."""

        def GetName(self, child_id):
            return wx.ACC_OK, ""

        def GetState(self, child_id):
            return wx.ACC_OK, wx.ACC_STATE_SYSTEM_INVISIBLE
else:
    _NamedPageAccessible = None
    _NamedControlAccessible = None
    _SilentLabelAccessible = None


def set_windows_accessible(
    window: wx.Window,
    accessible_type: type[wx.Accessible] | None,
    name: str,
) -> None:
    """Attach a custom MSAA object only on Windows."""
    if sys.platform == "win32" and accessible_type is not None:
        window.SetAccessible(accessible_type(window, name))

def silence_labels(window: wx.Window, keep: tuple[object, ...] = ()) -> None:
    """Stop screen readers announcing the static labels inside ``window``.

    Every control keeps its own accessible name, so the labels only add noise
    when a dialog opens and its whole text is read out.
    """
    if sys.platform != "win32" or _SilentLabelAccessible is None:
        return
    for child in window.GetChildren():
        if isinstance(child, wx.StaticText) and child not in keep:
            child.SetAccessible(_SilentLabelAccessible(child))
        silence_labels(child, keep)


SEARCH_LABELS = [
    tr_noop("Songs"),
    tr_noop("Albums"),
    tr_noop("Artists"),
    tr_noop("Playlists"),
    tr_noop("Podcasts"),
    tr_noop("Podcast episodes"),
    tr_noop("Audiobooks"),
    tr_noop("All"),
]
SEARCH_TYPES = [
    "track",
    "album",
    "artist",
    "playlist",
    "show",
    "episode",
    "audiobook",
    "all",
]
LASTFM_TAG_CHOICES = (
    "Alternative",
    "Ambient",
    "Blues",
    "Classical",
    "Country",
    "Electronic",
    "Folk",
    "Hip hop",
    "Indie",
    "Jazz",
    "Metal",
    "Pop",
    "Punk",
    "R&B",
    "Reggae",
    "Rock",
    "Soul",
    "Soundtrack",
    "World",
)
PODCAST_BROWSE_CATEGORIES = (
    (tr_noop("General discovery"), "podcast"),
    (tr_noop("Arts"), "arts podcast"),
    (tr_noop("Business"), "business podcast"),
    (tr_noop("Comedy"), "comedy podcast"),
    (tr_noop("Education"), "education podcast"),
    (tr_noop("Fiction"), "fiction podcast"),
    (tr_noop("Health"), "health podcast"),
    (tr_noop("History"), "history podcast"),
    (tr_noop("Kids and family"), "kids family podcast"),
    (tr_noop("Music"), "music podcast"),
    (tr_noop("News"), "news podcast"),
    (tr_noop("Science"), "science podcast"),
    (tr_noop("Society and culture"), "society culture podcast"),
    (tr_noop("Sports"), "sports podcast"),
    (tr_noop("Technology"), "technology podcast"),
    (tr_noop("True crime"), "true crime podcast"),
)
POLISH_PODCAST_BROWSE_QUERIES = {
    "General discovery": "podcast po polsku",
    "Arts": "sztuka kultura podcast po polsku",
    "Business": "biznes podcast po polsku",
    "Comedy": "komedia humor podcast po polsku",
    "Education": "edukacja podcast po polsku",
    "Fiction": "fikcja słuchowisko podcast po polsku",
    "Health": "zdrowie podcast po polsku",
    "History": "historia podcast po polsku",
    "Kids and family": "dzieci rodzina podcast po polsku",
    "Music": "muzyka podcast po polsku",
    "News": "wiadomości podcast po polsku",
    "Science": "nauka podcast po polsku",
    "Society and culture": "społeczeństwo kultura podcast po polsku",
    "Sports": "sport podcast po polsku",
    "Technology": "technologia podcast po polsku",
    "True crime": "kryminał true crime podcast po polsku",
}
PODCAST_LISTENING_STATUSES = (
    (tr_noop("All listening statuses"), "all"),
    (tr_noop("Not started"), "not_started"),
    (tr_noop("In progress"), "in_progress"),
    (tr_noop("Completed"), "completed"),
    (tr_noop("Unknown"), "unknown"),
)
PODCAST_LANGUAGE_NAMES = {
    "ar": tr_noop("Arabic"),
    "bg": tr_noop("Bulgarian"),
    "bn": tr_noop("Bengali"),
    "ca": tr_noop("Catalan"),
    "cs": tr_noop("Czech"),
    "da": tr_noop("Danish"),
    "de": tr_noop("German"),
    "el": tr_noop("Greek"),
    "en": tr_noop("English"),
    "es": tr_noop("Spanish"),
    "et": tr_noop("Estonian"),
    "fa": tr_noop("Persian"),
    "fi": tr_noop("Finnish"),
    "fil": tr_noop("Filipino"),
    "fr": tr_noop("French"),
    "he": tr_noop("Hebrew"),
    "hi": tr_noop("Hindi"),
    "hr": tr_noop("Croatian"),
    "hu": tr_noop("Hungarian"),
    "id": tr_noop("Indonesian"),
    "is": tr_noop("Icelandic"),
    "it": tr_noop("Italian"),
    "ja": tr_noop("Japanese"),
    "ko": tr_noop("Korean"),
    "lt": tr_noop("Lithuanian"),
    "lv": tr_noop("Latvian"),
    "ms": tr_noop("Malay"),
    "nl": tr_noop("Dutch"),
    "no": tr_noop("Norwegian"),
    "pl": tr_noop("Polish"),
    "pt": tr_noop("Portuguese"),
    "ro": tr_noop("Romanian"),
    "ru": tr_noop("Russian"),
    "sk": tr_noop("Slovak"),
    "sl": tr_noop("Slovenian"),
    "sr": tr_noop("Serbian"),
    "sv": tr_noop("Swedish"),
    "sw": tr_noop("Swahili"),
    "ta": tr_noop("Tamil"),
    "th": tr_noop("Thai"),
    "tr": tr_noop("Turkish"),
    "uk": tr_noop("Ukrainian"),
    "ur": tr_noop("Urdu"),
    "vi": tr_noop("Vietnamese"),
    "zh": tr_noop("Chinese"),
}
BRAILLE_LYRICS_TIMER_MS = 100
BRAILLE_LYRIC_LEAD_MS = 1_000
PHRASE_MODE_TIMER_MS = 25
PREVIOUS_DOUBLE_PRESS_SECONDS = 0.5
ENTER_KEY_CODES = (10, 13, wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
DEVELOPER_DASHBOARD_URL = "https://developer.spotify.com/dashboard"
TICKETMASTER_DEVELOPER_URL = (
    "https://developer.ticketmaster.com/products-and-docs/apis/getting-started/"
)
DEEPL_DEVELOPER_URL = "https://www.deepl.com/en/developers"


def normalise_filter_text(value: str) -> str:
    """Return case- and accent-insensitive text for local list filtering."""
    folded = value.casefold().translate(
        str.maketrans({"ł": "l", "đ": "d", "ð": "d", "þ": "th"})
    )
    decomposed = unicodedata.normalize("NFKD", folded)
    return "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )


def filter_spotify_items(
    items: list[SpotifyItem],
    query: str,
) -> list[SpotifyItem]:
    words = normalise_filter_text(query).split()
    if not words:
        return list(items)
    return [
        item
        for item in items
        if all(
            word in normalise_filter_text(item.accessible_label())
            for word in words
        )
    ]


LOG_LEVEL_LABELS = {
    "Off": tr_noop("Off"),
    "Debug": tr_noop("Debug"),
    "Information": tr_noop("Information"),
    "Warnings": tr_noop("Warnings"),
    "Errors": tr_noop("Errors"),
}
DEVICE_TYPE_LABELS = {
    "Computer": tr_noop("Computer"),
    "Tablet": tr_noop("Tablet"),
    "Smartphone": tr_noop("Smartphone"),
    "Speaker": tr_noop("Speaker"),
    "TV": tr_noop("TV"),
    "AVR": tr_noop("AV receiver"),
    "STB": tr_noop("Set-top box"),
    "AudioDongle": tr_noop("Audio dongle"),
    "GameConsole": tr_noop("Game console"),
    "CastVideo": tr_noop("Cast video"),
    "CastAudio": tr_noop("Cast audio"),
    "Automobile": tr_noop("Car"),
    "Unknown": tr_noop("Unknown device"),
}
SORT_LABELS = {
    "original": tr_noop("Original order"),
    "title": tr_noop("Title"),
    "artist": tr_noop("Artist"),
    "album": tr_noop("Album"),
    "duration": tr_noop("Duration"),
    "date_added": tr_noop("Date added"),
}


def sortable_item_value(item: SpotifyItem, sort_key: str) -> object | None:
    if sort_key == "title":
        return normalise_filter_text(item.name)
    if sort_key == "artist":
        return normalise_filter_text(item.artist) if item.artist else None
    if sort_key == "album":
        return normalise_filter_text(item.album) if item.album else None
    if sort_key == "duration":
        return item.duration_ms if item.duration_ms else None
    if sort_key == "date_added":
        value = str(item.raw.get("added_at") or "")
        return value or None
    return None


def sort_spotify_items(
    items: list[SpotifyItem],
    sort_key: str,
    descending: bool = False,
) -> list[SpotifyItem]:
    """Sort a displayed copy while retaining missing values at the end."""
    if sort_key == "original":
        return list(items)
    headings = [item for item in items if item.kind == ItemKind.HEADING]
    items = [item for item in items if item.kind != ItemKind.HEADING]
    available = [
        item for item in items if sortable_item_value(item, sort_key) is not None
    ]
    missing = [
        item for item in items if sortable_item_value(item, sort_key) is None
    ]
    available.sort(
        key=lambda item: sortable_item_value(item, sort_key),
        reverse=descending,
    )
    return available + missing + headings


def available_sort_keys(items: list[SpotifyItem]) -> set[str]:
    if not any(item.kind != ItemKind.HEADING for item in items):
        return set()
    keys = {"original", "title"}
    for sort_key in ("artist", "album", "duration", "date_added"):
        if any(sortable_item_value(item, sort_key) is not None for item in items):
            keys.add(sort_key)
    return keys


def podcast_language_codes(item: SpotifyItem) -> tuple[str, ...]:
    languages = item.raw.get("languages") or []
    if isinstance(languages, str):
        languages = [languages]
    return tuple(
        dict.fromkeys(
            re.split(r"[-_]", str(language).strip().casefold(), maxsplit=1)[0]
            for language in languages
            if str(language).strip()
        )
    )


def podcast_listening_status(item: SpotifyItem) -> str:
    if item.kind != ItemKind.EPISODE:
        return "unknown"
    resume = item.raw.get("resume_point")
    if not isinstance(resume, dict):
        return "unknown"
    if resume.get("fully_played") is True:
        return "completed"
    if int(resume.get("resume_position_ms") or 0) > 0:
        return "in_progress"
    return "not_started"


def podcast_browse_query(
    category_label: str,
    default_query: str,
    language_code: str,
) -> str:
    if language_code == "pl":
        return POLISH_PODCAST_BROWSE_QUERIES.get(
            category_label,
            f"{default_query} po polsku",
        )
    if language_code and language_code != "unknown":
        language_name = PODCAST_LANGUAGE_NAMES.get(
            language_code,
            language_code,
        )
        return f"{default_query} {language_name}"
    return default_query
PAYPAL_DONATE_URL = (
    "https://www.paypal.com/donate?"
    "business=samtaylor9%40me.com&currency_code=AUD&item_name=BlindSpot"
)
GLOBAL_SHORTCUT_ACTIONS = (
    ("previous_track", 3101),
    ("pause_resume", 3102),
    ("next_track", 3103),
    ("seek_backward", 3104),
    ("seek_forward", 3105),
    ("volume_down", 3106),
    ("volume_up", 3107),
    ("toggle_mute", 3108),
    ("like_current", 3109),
    ("speak_current", 3110),
    ("speak_up_next", 3111),
    ("speak_total", 3112),
    ("speak_elapsed", 3113),
    ("speak_remaining", 3114),
    ("bookmark_current", 3115),
    ("toggle_shuffle", 3116),
    ("cycle_repeat", 3117),
)
GLOBAL_SHORTCUT_IDS = {
    action: hotkey_id
    for action, hotkey_id in GLOBAL_SHORTCUT_ACTIONS
}
RESUME_MODES = ("none", "track", "track_and_position")
RESUME_MODE_LABELS = (
    tr_noop("Do not remember the last played track"),
    tr_noop("Remember the last played track"),
    tr_noop("Remember the last played track and position"),
)


def space_belongs_to_control(window: wx.Window | None) -> bool:
    """Return whether the focused control should handle bare Space itself."""
    return isinstance(
        window,
        (
            wx.Button,
            wx.BitmapButton,
            wx.ToggleButton,
            wx.CheckBox,
            wx.RadioButton,
            wx.RadioBox,
            wx.TextCtrl,
            wx.ComboBox,
            wx.SearchCtrl,
            wx.SpinCtrl,
        ),
    )


def album_track_label(
    item: SpotifyItem,
    index: int,
    state: ViewState,
    multi_disc: bool,
) -> str:
    track_number = int(item.raw.get("track_number") or index + 1)
    disc_number = int(item.raw.get("disc_number") or 1)
    if multi_disc:
        label = tr(
            "Disc {disc_number} track {track_number} {name}"
        ).format(
            disc_number=disc_number,
            track_number=track_number,
            name=item.name,
        )
    else:
        label = f"{track_number} {item.name}"

    album_artist_ids = set(state.parent_artist_ids)
    album_artist_names = {
        name.casefold() for name in state.parent_artist_names
    }
    track_artists = item.raw.get("artists") or []
    featured = []
    for artist in track_artists:
        name = str(artist.get("name") or "")
        artist_id = str(artist.get("id") or "")
        if not name:
            continue
        if artist_id and album_artist_ids:
            additional = artist_id not in album_artist_ids
        else:
            additional = name.casefold() not in album_artist_names
        if additional and name not in featured:
            featured.append(name)
    if not track_artists and item.artist:
        if item.artist.casefold() not in album_artist_names:
            featured.append(item.artist)
    if featured:
        label += tr(" — featuring {artists}").format(
            artists=", ".join(featured)
        )
    return label


def normalized_global_shortcuts(value: object) -> dict[str, dict[str, int]]:
    if not isinstance(value, dict):
        return {}
    shortcuts = {}
    for action, _ in GLOBAL_SHORTCUT_ACTIONS:
        shortcut = value.get(action)
        if not isinstance(shortcut, dict):
            continue
        try:
            modifiers = int(shortcut.get("modifiers", 0))
            keycode = int(shortcut["keycode"])
        except (KeyError, TypeError, ValueError):
            continue
        if keycode > 0:
            shortcuts[action] = {
                "modifiers": modifiers,
                "keycode": keycode,
            }
    return shortcuts


def shortcut_label(shortcut: dict[str, int] | None) -> str:
    if not shortcut:
        return tr("Not assigned")
    modifiers = int(shortcut.get("modifiers", 0))
    keycode = int(shortcut.get("keycode", 0))
    special_keys = {
        wx.WXK_MEDIA_PREV_TRACK: "Media Previous",
        wx.WXK_MEDIA_PLAY_PAUSE: "Media Play/Pause",
        wx.WXK_MEDIA_NEXT_TRACK: "Media Next",
        wx.WXK_MEDIA_STOP: "Media Stop",
        wx.WXK_VOLUME_MUTE: "Volume Mute",
        wx.WXK_VOLUME_DOWN: "Volume Down",
        wx.WXK_VOLUME_UP: "Volume Up",
        wx.WXK_SPACE: "Space",
        wx.WXK_RETURN: "Enter",
        wx.WXK_TAB: "Tab",
        wx.WXK_DELETE: "Delete",
        wx.WXK_BACK: "Backspace",
        wx.WXK_LEFT: "Left",
        wx.WXK_RIGHT: "Right",
        wx.WXK_UP: "Up",
        wx.WXK_DOWN: "Down",
        wx.WXK_HOME: "Home",
        wx.WXK_END: "End",
        wx.WXK_PAGEUP: "Page Up",
        wx.WXK_PAGEDOWN: "Page Down",
    }
    if wx.WXK_F1 <= keycode <= wx.WXK_F24:
        key_name = f"F{keycode - wx.WXK_F1 + 1}"
    elif keycode in special_keys:
        key_name = special_keys[keycode]
    elif 32 <= keycode < 127:
        key_name = chr(keycode).upper()
    else:
        key_name = f"Key {keycode}"
    parts = []
    if modifiers & wx.MOD_CONTROL:
        parts.append("Control")
    if modifiers & wx.MOD_ALT:
        parts.append("Alt")
    if modifiers & wx.MOD_SHIFT:
        parts.append("Shift")
    if modifiers & wx.MOD_WIN:
        parts.append("Windows")
    parts.append(key_name)
    return "+".join(parts)


def captured_shortcut(event: wx.KeyEvent) -> dict[str, int]:
    modifiers = int(event.GetModifiers())
    windows_down = bool(event.MetaDown())
    if sys.platform == "win32":
        windows_down = windows_down or bool(
            wx.GetKeyState(wx.WXK_WINDOWS_LEFT)
            or wx.GetKeyState(wx.WXK_WINDOWS_RIGHT)
        )
    if windows_down:
        modifiers |= wx.MOD_WIN
    return {
        "modifiers": modifiers,
        "keycode": int(event.GetKeyCode()),
    }


def resume_mode_from_settings(settings: dict) -> str:
    mode = str(settings.get("resume_mode") or "")
    if mode in RESUME_MODES:
        return mode
    return "track_and_position" if settings.get("resume_last_track") else "none"


def volume_percent_from_settings(settings: dict) -> int:
    try:
        volume = int(settings.get("playback_volume_percent", 80))
    except (TypeError, ValueError):
        return 80
    return min(100, max(0, volume))


def playback_state_for_resume(state: dict, mode: str) -> dict:
    stored = dict(state)
    if mode == "track":
        stored["progress_ms"] = 0
    return stored


def radio_box_letter_index(box: wx.RadioBox, letter: str) -> int | None:
    count = box.GetCount()
    if not count:
        return None
    current = box.GetSelection()
    for offset in range(1, count + 1):
        index = (current + offset) % count
        label = box.GetString(index)
        if label.lstrip().casefold().startswith(letter):
            return index
    return None


def move_radio_box_focus(box: wx.RadioBox, target: int) -> None:
    """Move real keyboard focus to the target item, not just its checked state.

    wx.RadioBox.SetSelection() only flips which button is checked; it does
    not move keyboard focus and does not fire the platform accessibility
    events a screen reader relies on, so a caller that only calls
    SetSelection() produces a silent, unannounced change. Native radio
    groups instead move focus (and announce the change) when the user
    presses Up/Down, so we drive that same native path with synthetic
    Up/Down key presses rather than faking the selection.
    """
    current = box.GetSelection()
    count = box.GetCount()
    if target == current or count <= 0:
        return
    forward_steps = (target - current) % count
    backward_steps = (current - target) % count
    if forward_steps <= backward_steps:
        key, steps = wx.WXK_DOWN, forward_steps
    else:
        key, steps = wx.WXK_UP, backward_steps
    simulator = wx.UIActionSimulator()
    for _ in range(steps):
        simulator.KeyDown(key)
        simulator.KeyUp(key)


def physical_control_down(event: wx.KeyEvent) -> bool:
    if sys.platform != "darwin":
        return event.ControlDown()
    get_modifiers = getattr(event, "GetModifiers", None)
    if get_modifiers and bool(int(get_modifiers()) & wx.MOD_RAW_CONTROL):
        return True
    raw_control_down = getattr(event, "RawControlDown", None)
    if raw_control_down:
        return bool(raw_control_down())
    return bool(wx.GetKeyState(wx.WXK_RAW_CONTROL))


def playback_adjustment_modifier_down(event: wx.KeyEvent) -> bool:
    return (
        event.ShiftDown()
        and not event.AltDown()
        and not physical_control_down(event)
    )


def lyric_navigation_modifier_down(event: wx.KeyEvent) -> bool:
    if sys.platform != "darwin":
        return (
            event.AltDown()
            and not physical_control_down(event)
            and not event.ShiftDown()
        )
    get_modifiers = getattr(event, "GetModifiers", None)
    if get_modifiers:
        modifiers = int(get_modifiers())
        return (
            bool(modifiers & wx.MOD_CONTROL)
            and bool(modifiers & wx.MOD_ALT)
            and not bool(modifiers & wx.MOD_RAW_CONTROL)
            and not event.ShiftDown()
        )
    return (
        event.ControlDown()
        and event.AltDown()
        and not event.ShiftDown()
        and not physical_control_down(event)
    )


def chord_display(chord: str, platform: str = sys.platform) -> str:
    """Show a stored key chord the way it is written in the manual."""
    if platform != "darwin":
        chord = chord.replace("Control", "Ctrl")
    return chord


def menu_function_shortcut(
    shortcut: str,
    platform: str = sys.platform,
) -> str:
    # Configurable commands must not retain a second, hidden source of truth in
    # native menu accelerators. The context dispatcher handles their keys.
    return ""


def native_text_positions(
    text: str,
    positions: list[int],
    platform: str = sys.platform,
) -> list[int]:
    if platform != "win32":
        return positions
    return [
        position + text[:position].count("\n")
        for position in positions
    ]


def window_is_or_descendant(
    window: wx.Window | None,
    ancestor: wx.Window,
) -> bool:
    while window:
        if window is ancestor:
            return True
        try:
            window = window.GetParent()
        except (AttributeError, RuntimeError):
            return False
    return False


class SetupDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, client_id: str = "") -> None:
        super().__init__(
            parent,
            title=tr("BlindSpot setup"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        outer = wx.BoxSizer(wx.VERTICAL)
        welcome = wx.StaticText(
            self,
            label=msg.SETUP_WELCOME,
        )
        instructions_label = wx.StaticText(
            self,
            label=tr("Setup instructions"),
        )
        instructions = wx.TextCtrl(
            self,
            value=msg.SETUP_INSTRUCTIONS,
            style=wx.TE_MULTILINE | wx.TE_READONLY,
            size=(-1, 125),
        )
        self.open_dashboard = wx.Button(
            self, label=tr("&Open Spotify Developer Dashboard")
        )
        redirect_label = wx.StaticText(self, label=tr("Redirect URI"))
        self.redirect = wx.TextCtrl(self, value=REDIRECT_URI, style=wx.TE_READONLY)
        client_label = wx.StaticText(self, label=tr("Spotify Client ID"))
        self.client_id = wx.TextCtrl(self, value=client_id)
        buttons = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        connect_button = self.FindWindow(wx.ID_OK)
        if isinstance(connect_button, wx.Button):
            connect_button.SetLabel(tr("&Connect to Spotify"))

        outer.Add(welcome, 0, wx.EXPAND | wx.ALL, 12)
        outer.Add(instructions_label, 0, wx.LEFT | wx.RIGHT, 12)
        outer.Add(instructions, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        outer.Add(self.open_dashboard, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        outer.Add(redirect_label, 0, wx.LEFT | wx.RIGHT, 12)
        outer.Add(self.redirect, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        outer.Add(client_label, 0, wx.LEFT | wx.RIGHT, 12)
        outer.Add(self.client_id, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        if buttons:
            outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizerAndFit(outer)
        self.SetMinSize((600, self.GetSize().height))
        self.open_dashboard.Bind(
            wx.EVT_BUTTON,
            lambda event: webbrowser.open(DEVELOPER_DASHBOARD_URL),
        )
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self.focus_initial_control()

    def focus_initial_control(self) -> None:
        self.open_dashboard.SetFocus()

    def on_ok(self, event: wx.CommandEvent) -> None:
        if not self.client_id.GetValue().strip():
            wx.MessageBox(
                msg.PASTE_CLIENT_ID,
                tr("BlindSpot setup"),
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            self.client_id.SetFocus()
            return
        event.Skip()

    def get_client_id(self) -> str:
        return self.client_id.GetValue().strip()


class ShortcutCaptureDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, action_label: str) -> None:
        super().__init__(parent, title=tr(
            "Assign global shortcut: {action_label}"
        ).format(action_label=action_label))
        self.shortcut: dict[str, int] | None = None
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(
            wx.StaticText(
                self,
                label=msg.shortcut_capture(action_label),
            ),
            0,
            wx.EXPAND | wx.ALL,
            16,
        )
        cancel = self.CreateSeparatedButtonSizer(wx.CANCEL)
        if cancel:
            outer.Add(cancel, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizerAndFit(outer)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key)

    def on_key(self, event: wx.KeyEvent) -> None:
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        if keycode in (
            wx.WXK_CONTROL,
            wx.WXK_SHIFT,
            wx.WXK_ALT,
            wx.WXK_RAW_CONTROL,
            wx.WXK_WINDOWS_LEFT,
            wx.WXK_WINDOWS_RIGHT,
        ):
            return
        self.shortcut = captured_shortcut(event)
        self.EndModal(wx.ID_OK)


class KeymapCaptureDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, action_label: str) -> None:
        super().__init__(parent, title=tr(
            "Assign key: {action_label}"
        ).format(action_label=action_label))
        self.chord: str | None = None
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(
            wx.StaticText(self, label=tr(
                "Press a key combination. Escape cancels."
            )),
            0,
            wx.EXPAND | wx.ALL,
            16,
        )
        cancel = self.CreateSeparatedButtonSizer(wx.CANCEL)
        if cancel:
            outer.Add(cancel, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizerAndFit(outer)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key)

    def on_key(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        chord = chord_from_event(event)
        if not chord:
            return
        self.chord = chord
        self.EndModal(wx.ID_OK)


class KeyboardManagerDialog(wx.Dialog):
    def __init__(
        self,
        parent: wx.Window,
        keymap: KeyMap,
        seen_warnings: set[str],
        global_shortcuts: dict[str, dict[str, int]],
    ) -> None:
        super().__init__(
            parent,
            title=tr("Keyboard Manager"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.keymap = KeyMap(
            {"bindings": keymap.custom},
            platform=keymap.platform,
        )
        self.seen_warnings = set(seen_warnings)
        self.global_shortcuts = normalized_global_shortcuts(global_shortcuts)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(
            wx.StaticText(self, label=tr("Context")),
            0,
            wx.LEFT | wx.RIGHT | wx.TOP,
            12,
        )
        self.context = wx.Choice(
            self,
            choices=[
                tr("All commands"),
                *(tr(CONTEXT_LABELS.get(name, name)) for name in CONTEXTS),
            ],
        )
        self.context.SetSelection(0)
        outer.Add(
            self.context,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        outer.Add(
            wx.StaticText(self, label=tr("Search commands")),
            0,
            wx.LEFT | wx.RIGHT,
            12,
        )
        self.search = wx.TextCtrl(self)
        outer.Add(
            self.search,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        outer.Add(
            wx.StaticText(self, label=tr("Commands and assigned keys")),
            0,
            wx.LEFT | wx.RIGHT,
            12,
        )
        self.actions = wx.ListBox(self, choices=self.action_choices())
        if self.actions.GetCount():
            self.actions.SetSelection(0)
        outer.Add(self.actions, 1, wx.EXPAND | wx.ALL, 12)
        action_buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.assign = wx.Button(self, label=tr("&Assign..."))
        self.clear = wx.Button(self, label=tr("&Clear"))
        self.assign_global = wx.Button(self, label=tr("Assign &global..."))
        self.clear_global = wx.Button(self, label=tr("Clear g&lobal"))
        self.defaults = wx.Button(self, label=tr("Restore &defaults"))
        action_buttons.Add(self.assign, 0, wx.RIGHT, 8)
        action_buttons.Add(self.clear, 0, wx.RIGHT, 8)
        action_buttons.Add(self.assign_global, 0, wx.RIGHT, 8)
        action_buttons.Add(self.clear_global, 0, wx.RIGHT, 8)
        action_buttons.Add(self.defaults)
        outer.Add(
            action_buttons,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        buttons = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        if buttons:
            outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizerAndFit(outer)
        self.SetMinSize((650, 480))
        self.context.Bind(wx.EVT_CHOICE, self.on_context)
        self.search.Bind(wx.EVT_TEXT, self.on_search)
        self.assign.Bind(wx.EVT_BUTTON, self.on_assign)
        self.clear.Bind(wx.EVT_BUTTON, self.on_clear)
        self.assign_global.Bind(wx.EVT_BUTTON, self.on_assign_global)
        self.clear_global.Bind(wx.EVT_BUTTON, self.on_clear_global)
        self.defaults.Bind(wx.EVT_BUTTON, self.on_defaults)
        self.actions.Bind(wx.EVT_LISTBOX_DCLICK, self.on_assign)
        self.actions.Bind(wx.EVT_LISTBOX, self.on_action_selected)
        self.search.SetFocus()
        self.update_global_buttons()

    def current_context(self) -> str | None:
        selected = self.context.GetSelection()
        return None if selected == 0 else CONTEXTS[selected - 1]

    def context_actions(self) -> list:
        context = self.current_context()
        actions = (
            list(KEY_ACTIONS)
            if context is None
            else [action for action in KEY_ACTIONS if action.context == context]
        )
        search = getattr(self, "search", None)
        query = search.GetValue().strip().casefold() if search else ""
        if not query:
            return actions
        return [
            action
            for action in actions
            if query
            in " ".join(
                (
                    action.title,
                    action.context_title,
                    *self.keymap.bindings(action.id),
                )
            ).casefold()
        ]

    def action_choices(self) -> list[str]:
        choices = []
        for action in self.context_actions():
            local = ", ".join(self.keymap.bindings(action.id)) or tr(
                "Not assigned"
            )
            global_label = shortcut_label(self.global_shortcuts.get(action.id))
            description = (
                f"{action.context_title}: {action.title}: "
                f"{local}"
                if self.current_context() is None
                else f"{action.title}: {local}"
            )
            if action.id in GLOBAL_SHORTCUT_IDS:
                description += tr(
                    "; global: {global_label}"
                ).format(global_label=global_label)
            choices.append(description)
        return choices

    def refresh_choices(self, selected: int = 0) -> None:
        self.actions.Set(self.action_choices())
        if self.actions.GetCount():
            self.actions.SetSelection(
                min(max(0, selected), self.actions.GetCount() - 1)
            )
        self.update_global_buttons()

    def on_context(self, event: wx.Event) -> None:
        self.refresh_choices()

    def on_search(self, event: wx.Event) -> None:
        self.refresh_choices()

    def selected_action(self):
        selected = self.actions.GetSelection()
        actions = self.context_actions()
        if selected == wx.NOT_FOUND or not 0 <= selected < len(actions):
            return None
        return actions[selected]

    def update_global_buttons(self) -> None:
        action = self.selected_action()
        eligible = bool(action and action.id in GLOBAL_SHORTCUT_IDS)
        self.assign_global.Enable(eligible)
        self.clear_global.Enable(
            bool(eligible and action.id in self.global_shortcuts)
        )

    def on_action_selected(self, event: wx.Event) -> None:
        self.update_global_buttons()

    def on_assign(self, event: wx.Event) -> None:
        selected = self.actions.GetSelection()
        actions = self.context_actions()
        if selected == wx.NOT_FOUND or not 0 <= selected < len(actions):
            return
        action = actions[selected]
        capture = KeymapCaptureDialog(self, action.title)
        accepted = capture.ShowModal() == wx.ID_OK and capture.chord
        chord = capture.chord
        capture.Destroy()
        if not accepted or not chord:
            return
        owner = self.keymap.owner(chord, action.context)
        if owner and owner.id != action.id:
            answer = wx.MessageBox(
                tr("Replace {label}?").format(label=owner.title),
                tr("Keyboard Manager"),
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
                self,
            )
            if answer != wx.YES:
                return
        warning = conflict_warning(chord, self.keymap.platform)
        if warning and warning not in self.seen_warnings:
            if warning in {"navigation", "typing"}:
                answer = wx.MessageBox(
                    (
                        msg.KEYMAP_NAVIGATION_WARNING
                        if warning == "navigation"
                        else msg.KEYMAP_TYPING_WARNING
                    ),
                    tr("Keyboard Manager"),
                    wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
                    self,
                )
                if answer != wx.YES:
                    return
            else:
                wx.MessageBox(
                    (
                        msg.KEYMAP_VOICEOVER_WARNING
                        if warning == "voiceover"
                        else msg.KEYMAP_OS_WARNING
                    ),
                    tr("Keyboard Manager"),
                    wx.OK | wx.ICON_WARNING,
                    self,
                )
            self.seen_warnings.add(warning)
        self.keymap.set_binding(action.id, chord)
        self.refresh_choices(selected)

    def on_clear(self, event: wx.Event) -> None:
        selected = self.actions.GetSelection()
        actions = self.context_actions()
        if selected == wx.NOT_FOUND or not 0 <= selected < len(actions):
            return
        self.keymap.clear(actions[selected].id)
        self.refresh_choices(selected)

    def on_assign_global(self, event: wx.Event) -> None:
        action = self.selected_action()
        if action is None or action.id not in GLOBAL_SHORTCUT_IDS:
            return
        capture = ShortcutCaptureDialog(self, action.title)
        accepted = capture.ShowModal() == wx.ID_OK and capture.shortcut
        shortcut = capture.shortcut
        capture.Destroy()
        if not accepted or not shortcut:
            return
        if "global" not in self.seen_warnings:
            answer = wx.MessageBox(
                msg.KEYMAP_GLOBAL_WARNING,
                tr("Keyboard Manager"),
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
                self,
            )
            if answer != wx.YES:
                return
            self.seen_warnings.add("global")
        duplicate = next(
            (
                other_action
                for other_action, existing in self.global_shortcuts.items()
                if other_action != action.id and existing == shortcut
            ),
            None,
        )
        if duplicate:
            other_label = ACTIONS_BY_ID[duplicate].title
            answer = wx.MessageBox(
                msg.shortcut_replace(shortcut_label(shortcut), other_label),
                tr("Keyboard Manager"),
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
                self,
            )
            if answer != wx.YES:
                return
            self.global_shortcuts.pop(duplicate, None)
        self.global_shortcuts[action.id] = dict(shortcut)
        self.refresh_choices(self.actions.GetSelection())

    def on_clear_global(self, event: wx.Event) -> None:
        action = self.selected_action()
        if action is None:
            return
        selected = self.actions.GetSelection()
        self.global_shortcuts.pop(action.id, None)
        self.refresh_choices(selected)

    def on_defaults(self, event: wx.Event) -> None:
        self.keymap.restore_defaults(self.current_context())
        self.refresh_choices()


class PreferencesDialog(wx.Dialog):
    def __init__(
        self,
        parent: wx.Window,
        logging_level: str,
        announce_track_changes: bool,
        resume_mode: str,
        ticketmaster_api_key: str = "",
        lastfm_api_key: str = DEFAULT_LASTFM_API_KEY,
        open_logs_folder: Callable[[], None] | None = None,
        open_keyboard_manager: Callable[[wx.Window | None], None] | None = None,
        language: str = i18n.DEFAULT_LANGUAGE_SETTING,
        announce_lyric_sections: bool = False,
        announce_volume_changes: bool = True,
        announce_cart_names: bool = True,
        check_followed_on_start: bool = True,
        deepl_api_key: str = "",
        lyrics_translation_language: str = "",
    ) -> None:
        super().__init__(parent, title=tr("BlindSpot preferences"))
        self.open_logs_folder_callback = open_logs_folder
        self.open_keyboard_manager_callback = open_keyboard_manager
        outer = wx.BoxSizer(wx.VERTICAL)
        self.announce_track_changes = wx.CheckBox(
            self,
            label=tr("Speak track name when playback changes"),
        )
        self.announce_track_changes.SetValue(announce_track_changes)
        outer.Add(
            self.announce_track_changes,
            0,
            wx.ALL,
            12,
        )
        self.announce_lyric_sections = wx.CheckBox(
            self,
            label=tr("Speak section number when jumping between lyric sections"),
        )
        self.announce_lyric_sections.SetValue(announce_lyric_sections)
        outer.Add(
            self.announce_lyric_sections,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        self.announce_volume_changes = wx.CheckBox(
            self,
            label=tr("Speak volume level when it changes"),
        )
        self.announce_volume_changes.SetValue(announce_volume_changes)
        outer.Add(
            self.announce_volume_changes,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        self.announce_cart_names = wx.CheckBox(
            self,
            label=tr("Speak cart name when a cart plays"),
        )
        self.announce_cart_names.SetValue(announce_cart_names)
        outer.Add(
            self.announce_cart_names,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        self.check_followed_on_start = wx.CheckBox(
            self,
            label=tr("Check followed artists and authors for new releases at start-up"),
        )
        self.check_followed_on_start.SetValue(check_followed_on_start)
        outer.Add(
            self.check_followed_on_start,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        self.language_codes = [i18n.SYSTEM_LANGUAGE] + [
            code for code, _name in i18n.available_languages()
        ]
        self.language = wx.RadioBox(
            self,
            label=tr("Language (restart required)"),
            choices=[tr("System default")]
            + [name for _code, name in i18n.available_languages()],
            majorDimension=1,
            style=wx.RA_SPECIFY_ROWS,
        )
        self.language.SetSelection(
            self.language_codes.index(language)
            if language in self.language_codes
            else self.language_codes.index(i18n.DEFAULT_LANGUAGE)
        )
        outer.Add(
            self.language,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        self.resume_mode = wx.RadioBox(
            self,
            label=tr("Startup playback memory"),
            choices=[tr(label) for label in RESUME_MODE_LABELS],
            majorDimension=1,
            style=wx.RA_SPECIFY_ROWS,
        )
        self.resume_mode.SetSelection(
            RESUME_MODES.index(resume_mode)
            if resume_mode in RESUME_MODES
            else 0
        )
        outer.Add(
            self.resume_mode,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        self.keyboard_manager = wx.Button(
            self,
            label=tr("&Keyboard Manager..."),
        )
        outer.Add(
            self.keyboard_manager,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        self.logging_level = wx.RadioBox(
            self,
            label=tr("Logging level"),
            choices=[tr(LOG_LEVEL_LABELS[name]) for name in LOG_LEVELS],
            majorDimension=1,
            style=wx.RA_SPECIFY_ROWS,
        )
        self.logging_level.SetSelection(
            list(LOG_LEVELS).index(
                logging_level if logging_level in LOG_LEVELS else "Off"
            )
        )
        outer.Add(
            self.logging_level,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        self.open_logs_folder = wx.Button(
            self,
            label=tr("Open &logs folder"),
        )
        outer.Add(
            self.open_logs_folder,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        outer.Add(
            wx.StaticText(self, label=tr("Ticketmaster API key")),
            0,
            wx.LEFT | wx.RIGHT | wx.TOP,
            12,
        )
        self.ticketmaster_api_key = wx.TextCtrl(
            self,
            value=ticketmaster_api_key,
        )
        self.ticketmaster_api_key.SetName(tr("Ticketmaster API key"))
        set_windows_accessible(
            self.ticketmaster_api_key,
            _NamedControlAccessible,
            tr("Ticketmaster API key"),
        )
        outer.Add(
            self.ticketmaster_api_key,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        self.get_ticketmaster_key_button = wx.Button(
            self,
            label=tr("&Get a Ticketmaster API key..."),
        )
        outer.Add(
            self.get_ticketmaster_key_button,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        outer.Add(
            wx.StaticText(self, label=tr("Last.fm API key")),
            0,
            wx.LEFT | wx.RIGHT | wx.TOP,
            12,
        )
        self.lastfm_api_key = wx.TextCtrl(self, value=lastfm_api_key)
        self.lastfm_api_key.SetName(tr("Last.fm API key"))
        outer.Add(
            self.lastfm_api_key,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        lyrics_box = wx.StaticBoxSizer(wx.VERTICAL, self, label=tr("Lyrics"))
        lyrics_box.Add(
            wx.StaticText(self, label=tr("DeepL API key")),
            0,
            wx.LEFT | wx.RIGHT | wx.TOP,
            8,
        )
        self.deepl_api_key = wx.TextCtrl(
            self,
            value=deepl_api_key,
            style=wx.TE_PASSWORD,
        )
        self.deepl_api_key.SetName(tr("DeepL API key"))
        lyrics_box.Add(
            self.deepl_api_key,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            8,
        )
        self.get_deepl_key_button = wx.Button(
            self,
            label=tr("&Get a DeepL API key..."),
        )
        lyrics_box.Add(
            self.get_deepl_key_button,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            8,
        )
        self.lyrics_translation_codes = [code for code, _name in TARGET_LANGUAGES]
        self.lyrics_translation_language = wx.Choice(
            self,
            choices=[tr(name) for _code, name in TARGET_LANGUAGES],
        )
        self.lyrics_translation_language.SetName(
            tr("Lyrics translation language")
        )
        set_windows_accessible(
            self.lyrics_translation_language,
            _NamedControlAccessible,
            tr("Lyrics translation language"),
        )
        self.lyrics_translation_language.SetSelection(
            self.lyrics_translation_codes.index(lyrics_translation_language)
            if lyrics_translation_language in self.lyrics_translation_codes
            else 0
        )
        lyrics_box.Add(
            wx.StaticText(self, label=tr("Lyrics translation language")),
            0,
            wx.LEFT | wx.RIGHT | wx.TOP,
            8,
        )
        lyrics_box.Add(
            self.lyrics_translation_language,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            8,
        )
        outer.Add(
            lyrics_box,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        buttons = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        if buttons:
            outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizerAndFit(outer)
        self.open_logs_folder.Bind(
            wx.EVT_BUTTON,
            self.on_open_logs_folder,
        )
        self.keyboard_manager.Bind(
            wx.EVT_BUTTON,
            self.on_keyboard_manager,
        )
        self.get_ticketmaster_key_button.Bind(
            wx.EVT_BUTTON,
            lambda event: webbrowser.open(TICKETMASTER_DEVELOPER_URL),
        )
        self.get_deepl_key_button.Bind(
            wx.EVT_BUTTON,
            lambda event: webbrowser.open(DEEPL_DEVELOPER_URL),
        )
        self.announce_track_changes.SetFocus()

    def get_logging_level(self) -> str:
        return list(LOG_LEVELS)[self.logging_level.GetSelection()]

    def get_language(self) -> str:
        return self.language_codes[self.language.GetSelection()]

    def get_ticketmaster_api_key(self) -> str:
        return self.ticketmaster_api_key.GetValue().strip()

    def get_lastfm_api_key(self) -> str:
        return self.lastfm_api_key.GetValue().strip()

    def get_deepl_api_key(self) -> str:
        return self.deepl_api_key.GetValue().strip()

    def get_lyrics_translation_language(self) -> str:
        return self.lyrics_translation_codes[self.lyrics_translation_language.GetSelection()]

    def on_open_logs_folder(self, event: wx.Event) -> None:
        if self.open_logs_folder_callback:
            self.open_logs_folder_callback()

    def on_keyboard_manager(self, event: wx.Event) -> None:
        if self.open_keyboard_manager_callback:
            self.open_keyboard_manager_callback(self)

    def get_announce_track_changes(self) -> bool:
        return self.announce_track_changes.GetValue()

    def get_announce_lyric_sections(self) -> bool:
        return self.announce_lyric_sections.GetValue()

    def get_announce_volume_changes(self) -> bool:
        return self.announce_volume_changes.GetValue()

    def get_announce_cart_names(self) -> bool:
        return self.announce_cart_names.GetValue()

    def get_check_followed_on_start(self) -> bool:
        return self.check_followed_on_start.GetValue()

    def get_resume_mode(self) -> str:
        return RESUME_MODES[self.resume_mode.GetSelection()]

TRANSPORT_KEY_ACTIONS: dict[str, tuple[str, tuple[object, ...]]] = {
    "seek_backward": ("seek", (-5000,)),
    "seek_forward": ("seek", (5000,)),
    "next_verse": ("jump_lyric_section", (1,)),
    "previous_verse": ("jump_lyric_section", (-1,)),
    "previous_track": ("previous_track", ()),
    "pause_resume": ("toggle_pause_resume", ()),
    "next_track": ("next_track", ()),
    "toggle_mute": ("toggle_mute", ()),
    "volume_down": ("adjust_volume", (-5,)),
    "volume_up": ("adjust_volume", (5,)),
}


class HostedPanelDialog(wx.Dialog):
    """A modal window holding a panel that used to be a main-window tab.

    The labels are painted but hidden from screen readers, which would
    otherwise read every one of them aloud when the dialog opens. Playback keys
    still work here, so music can be controlled while browsing.
    """

    def __init__(
        self,
        frame: "MainFrame",
        title: str,
        make_panel: Callable[[wx.Window], wx.Panel],
    ) -> None:
        super().__init__(
            frame,
            title=title,
            size=(760, 640),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.frame = frame
        self.panel = make_panel(self)
        self.panel.hosted_in = self
        silence_labels(self.panel, keep=(getattr(self.panel, "status", None),))
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(self.panel, 1, wx.EXPAND)
        buttons = self.CreateSeparatedButtonSizer(wx.CLOSE)
        if buttons:
            outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizer(outer)
        self.SetEscapeId(wx.ID_CLOSE)
        self.Bind(wx.EVT_BUTTON, self.on_close_button, id=wx.ID_CLOSE)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)

    def on_close_button(self, event: wx.Event) -> None:
        self.EndModal(wx.ID_CLOSE)

    def present(self, focus: wx.Window) -> None:
        wx.CallAfter(focus.SetFocus)
        self.ShowModal()

    def handle_key(self, event: wx.KeyEvent) -> bool:
        action = self.frame.keymap_action_for_event(event, ("Main",))
        if action == "play_focused":
            self.panel.on_open()
            return True
        if action not in TRANSPORT_KEY_ACTIONS:
            return False
        if (
            action == "pause_resume"
            and event.GetKeyCode() == wx.WXK_SPACE
            and space_belongs_to_control(event.GetEventObject())
        ):
            return False
        method, arguments = TRANSPORT_KEY_ACTIONS[action]
        getattr(self.frame, method)(*arguments)
        return True

    def on_char_hook(self, event: wx.KeyEvent) -> None:
        if not self.handle_key(event):
            event.Skip()


class SongStoryDialog(wx.Dialog):
    """A song's Wikipedia article in a read-only box, with a link to open it."""

    def __init__(
        self,
        parent: wx.Window,
        item: SpotifyItem,
        story: SongStory,
    ) -> None:
        super().__init__(
            parent,
            title=tr("{name} on Wikipedia").format(name=item.name),
            size=(700, 600),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.url = story.url
        outer = wx.BoxSizer(wx.VERTICAL)
        body = (story.text or story.summary) + "\n\n" + tr(
            "Source: Wikipedia, licensed CC BY-SA."
        )
        self.text = wx.TextCtrl(
            self,
            value=body,
            style=wx.TE_MULTILINE | wx.TE_READONLY,
        )
        self.text.SetName(tr("About {name}").format(name=item.name))
        outer.Add(self.text, 1, wx.EXPAND | wx.ALL, 12)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.open_button = wx.Button(self, label=tr("Open on &Wikipedia"))
        close_button = wx.Button(self, wx.ID_CLOSE)
        buttons.Add(self.open_button, 0, wx.RIGHT, 8)
        buttons.Add(close_button, 0)
        outer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.SetSizer(outer)
        self.SetEscapeId(wx.ID_CLOSE)
        self.open_button.Bind(wx.EVT_BUTTON, self.on_open)
        close_button.Bind(
            wx.EVT_BUTTON,
            lambda event: self.EndModal(wx.ID_CLOSE),
        )
        self.text.SetFocus()

    def on_open(self, event: wx.Event) -> None:
        webbrowser.open(self.url)


class MusicDetailsDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, title: str, text: str) -> None:
        super().__init__(
            parent,
            title=tr("Information about {name}").format(name=title),
            size=(700, 600),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        outer = wx.BoxSizer(wx.VERTICAL)
        self.text = wx.TextCtrl(
            self,
            value=text,
            style=wx.TE_MULTILINE | wx.TE_READONLY,
        )
        self.text.SetName(tr("Album and recording information"))
        outer.Add(self.text, 1, wx.EXPAND | wx.ALL, 12)
        buttons = self.CreateSeparatedButtonSizer(wx.CLOSE)
        if buttons:
            outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizer(outer)
        self.SetEscapeId(wx.ID_CLOSE)
        self.text.SetInsertionPoint(0)
        self.text.SetFocus()


def music_details_text(details: dict) -> str:
    track = details.get("track") or {}
    album = details.get("album") or track.get("album") or {}
    lines: list[str] = []

    def add(label: str, value: object) -> None:
        if value not in (None, "", [], {}):
            lines.append(f"{tr(label)}: {value}")

    if track:
        lines.append(tr("Recording"))
        add("Title", track.get("name"))
        add("Artist", ", ".join(
            str(artist.get("name") or "")
            for artist in track.get("artists") or []
            if artist.get("name")
        ))
        add("Track number", track.get("track_number"))
        add("Disc number", track.get("disc_number"))
        duration_ms = int(track.get("duration_ms") or 0)
        if duration_ms:
            minutes, seconds = divmod(duration_ms // 1000, 60)
            add("Duration", msg.minutes_seconds(minutes, seconds))
        add("ISRC", (track.get("external_ids") or {}).get("isrc"))
        add("Explicit", tr("Yes") if track.get("explicit") else tr("No"))
        lines.append("")
    if album:
        lines.append(tr("Album"))
        add("Title", album.get("name"))
        add("Album artist", ", ".join(
            str(artist.get("name") or "")
            for artist in album.get("artists") or []
            if artist.get("name")
        ))
        add("Release type", str(album.get("album_type") or "").title())
        add("Release date", album.get("release_date"))
        add("Total tracks", album.get("total_tracks"))
        add("Record label", album.get("label"))
        add("UPC", (album.get("external_ids") or {}).get("upc"))
        add("Genres", ", ".join(album.get("genres") or []))
        for copyright_value in album.get("copyrights") or []:
            add("Copyright", copyright_value.get("text"))
    return "\n".join(lines).strip()


class TranscriptDialog(wx.Dialog):
    def __init__(
        self,
        parent: "MainFrame",
        item: SpotifyItem,
        transcript: Transcript | None = None,
    ) -> None:
        super().__init__(
            parent,
            title=tr("Transcript for {episode_name} - BlindSpot").format(
                episode_name=item.name
            ),
            size=(700, 650),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.frame = parent
        self.item = item
        self.transcriber: WhisperTranscriber | None = None
        self.cache: TranscriptCache | None = None
        self.latest = transcript
        self.running = False
        self.closed = False
        self.was_activated = False
        self.track_id = item.id
        self.synced_lines: list[tuple[int, str]] = []
        self.synced_line_positions: list[int] = []
        self.last_followed_line = -1
        self.follow_timer = wx.Timer(self)
        self.activation_focus_timer = wx.Timer(self)
        self.activation_focus_retries: list[wx.CallLater] = []

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(wx.StaticText(self, label=item.name), 0, wx.ALL, 10)
        self.follow_playback = wx.CheckBox(
            self, label=tr("&Follow transcript playback")
        )
        self.follow_playback.SetValue(True)
        outer.Add(self.follow_playback, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Create controls in tab order.  Reordering them afterwards with
        # MoveBeforeInTabOrder left Tab and Shift+Tab visiting different
        # controls around the view choice on Windows.
        self.translation_view = None
        self.fetch_translation = None
        translation_enabled = bool(
            parent.deepl.api_key and parent.deepl.target_language
        )
        if translation_enabled or (transcript and transcript.translated_text):
            self.translation_view = wx.Choice(
                self,
                # Offer the translation up front so choosing it fetches one,
                # rather than hiding it until the button has been found.
                choices=[tr("Original"), tr("Translation")],
            )
            self.translation_view.SetName(tr("Transcript view"))
            self.translation_view.SetSelection(0)
            outer.Add(
                self.translation_view,
                0,
                wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
                10,
            )
        self.text = wx.TextCtrl(
            self,
            value=transcript.text if transcript else "",
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
        )
        self.text.SetName(
            tr("Transcript for {episode_name}").format(episode_name=item.name)
        )
        outer.Add(self.text, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        if self.translation_view and (
            not transcript or not transcript.translated_text
        ):
            self.fetch_translation = wx.Button(
                self, label=tr("&Translate with DeepL")
            )
            self.fetch_translation.SetToolTip(
                tr("Sends this transcript text to DeepL for translation.")
            )
            outer.Add(
                self.fetch_translation,
                0,
                wx.LEFT | wx.RIGHT | wx.TOP,
                10,
            )

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.stop_button = wx.Button(self, label=tr("&Stop transcription"))
        self.stop_button.Enable(False)
        self.close_button = wx.Button(self, wx.ID_CLOSE, tr("&Close"))
        buttons.Add(self.stop_button, 0, wx.RIGHT, 8)
        buttons.Add(self.close_button, 0)
        outer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        self.SetSizer(outer)
        self.stop_button.Bind(wx.EVT_BUTTON, self.on_stop)
        self.close_button.Bind(wx.EVT_BUTTON, self.on_close)
        self.follow_playback.Bind(wx.EVT_CHECKBOX, self.on_follow_playback)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_ACTIVATE, self.on_activate)
        wx.GetApp().Bind(wx.EVT_ACTIVATE_APP, self.on_app_activate)
        self.frame.Bind(wx.EVT_CHILD_FOCUS, self.on_parent_child_focus)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_dialog_key)
        self.Bind(wx.EVT_TIMER, self.on_follow_timer, self.follow_timer)
        self.Bind(
            wx.EVT_TIMER,
            self.on_activation_focus_timer,
            self.activation_focus_timer,
        )
        self.text.Bind(wx.EVT_KEY_DOWN, self.on_text_key)
        if self.translation_view:
            self.translation_view.Bind(wx.EVT_CHOICE, self.on_translation_view)
        if self.fetch_translation:
            self.fetch_translation.Bind(wx.EVT_BUTTON, self.on_fetch_translation)
        self.set_transcript(transcript)
        self.follow_timer.Start(BRAILLE_LYRICS_TIMER_MS)
        self.text.SetFocus()

    @staticmethod
    def consume_key(event: wx.KeyEvent) -> None:
        stop = getattr(event, "StopPropagation", None)
        if stop:
            stop()

    def on_activate(self, event: wx.ActivateEvent) -> None:
        event.Skip()
        if event.GetActive():
            if self.was_activated:
                self.activation_focus_timer.StartOnce(200)
            self.was_activated = True

    def on_app_activate(self, event: wx.ActivateEvent) -> None:
        """Recover the modal transcript focus Windows can return to its parent."""
        event.Skip()
        if event.GetActive() and not self.closed:
            logger.debug("Transcript app activation scheduling text focus")
            self.schedule_activation_focus()

    def on_parent_child_focus(self, event: wx.ChildFocusEvent) -> None:
        """Reject native focus escaping into the disabled frame on Windows."""
        event.Skip()
        if not self.closed and self.IsShown():
            focused = event.GetWindow()
            logger.debug(
                "Transcript recovering focus from parent child=%s",
                type(focused).__name__ if focused else "none",
            )
            self.schedule_activation_focus()

    def schedule_activation_focus(self) -> None:
        for retry in self.activation_focus_retries:
            retry.Stop()
        self.activation_focus_retries = [
            wx.CallLater(delay, self.restore_activation_focus)
            for delay in (1, 150, 500)
        ]

    def restore_activation_focus(self) -> None:
        if not self.closed:
            logger.debug("Transcript restoring focus to read-only text")
            self.Raise()
            self.text.SetFocus()

    def on_activation_focus_timer(
        self,
        event: wx.TimerEvent | None = None,
    ) -> None:
        self.restore_activation_focus()

    def on_follow_playback(self, event: wx.CommandEvent | None = None) -> None:
        if self.follow_playback.GetValue():
            self.last_followed_line = -1
            self.follow_timer.Start(BRAILLE_LYRICS_TIMER_MS)
            self.on_follow_timer()
        else:
            self.follow_timer.Stop()

    def set_transcript(self, transcript: Transcript | None) -> None:
        self.latest = transcript
        self.synced_lines = [
            (
                line.start_ms
                + (
                    WHISPER_PLAYBACK_OFFSET_MS
                    if transcript and transcript.source == "whisper" and line.start_ms
                    else 0
                ),
                line.text,
            )
            for line in (transcript.lines if transcript else ())
        ]
        positions: list[int] = []
        position = 0
        for line in (transcript.text.splitlines(keepends=True) if transcript else ()):
            positions.append(position)
            position += len(line)
        self.synced_line_positions = native_text_positions(
            transcript.text if transcript else "", positions
        )

    def on_translation_view(self, event: wx.CommandEvent | None = None) -> None:
        if (
            self.translation_view
            and self.translation_view.GetSelection() == 1
            and not (self.latest and self.latest.translated_text)
        ):
            self.translation_view.SetSelection(0)
            if self.running or not self.latest:
                self.frame.say(
                    tr("The transcript can be translated when transcription finishes.")
                )
            else:
                self.on_fetch_translation()
            return
        if not self.latest:
            return
        previous_value = self.text.GetValue()
        previous_position = self.text.GetInsertionPoint()
        translated = bool(
            self.translation_view
            and self.translation_view.GetSelection() == 1
            and self.latest.translated_text
        )
        value = self.latest.translated_text if translated else self.latest.text
        position = LyricsDialog._corresponding_text_position(
            previous_value, value, previous_position
        )
        original_positions: list[int] = []
        source_position = 0
        for line in self.latest.text.splitlines(keepends=True):
            original_positions.append(source_position)
            source_position += len(line)
        positions = (
            LyricsDialog._corresponding_line_positions(
                self.latest.text, value, original_positions
            )
            if translated
            else original_positions
        )
        self.synced_line_positions = native_text_positions(value, positions)
        self.text.SetValue(value)
        self.text.SetName(
            tr("Translated transcript")
            if translated
            else tr("Original transcript")
        )
        self.text.SetInsertionPoint(position)
        self.text.ShowPosition(position)

    def on_fetch_translation(self, event: wx.CommandEvent | None = None) -> None:
        if not self.latest or self.running:
            return
        if self.fetch_translation:
            self.fetch_translation.Disable()
            self.fetch_translation.SetLabel(tr("Translating..."))
        self.frame.run_task(
            tr("Translating transcript"),
            lambda: self.frame.translate_transcript(self.item, self.latest),
            self.finish_fetch_translation,
            failure=self.fail_fetch_translation,
            error_parent=self,
            requires_spotify=False,
        )

    def finish_fetch_translation(self, transcript: Transcript) -> None:
        if self.closed:
            return
        self.latest = transcript
        if self.fetch_translation:
            self.fetch_translation.Hide()
        self.Layout()
        if self.translation_view:
            self.translation_view.SetSelection(1)
            self.on_translation_view()
            self.text.SetFocus()

    def fail_fetch_translation(self) -> None:
        if self.closed or not self.fetch_translation:
            return
        self.fetch_translation.Enable()
        self.fetch_translation.SetLabel(tr("&Translate with DeepL"))

    def begin(
        self,
        transcriber: WhisperTranscriber,
        media: EpisodeMedia,
        cache: TranscriptCache,
        source_path: Path | None = None,
    ) -> None:
        self.transcriber = transcriber
        self.cache = cache
        self.running = True
        self.stop_button.Enable(True)
        if self.fetch_translation:
            self.fetch_translation.Disable()
        self.frame.say(tr("Transcribing episode."))

        def update(transcript: Transcript) -> None:
            cache.write(self.item.id, transcript)
            wx.CallAfter(self.update_transcript, transcript)

        def audio_ready(path: Path) -> None:
            wx.CallAfter(self.frame.use_transcript_audio, self.item, path)

        if source_path is not None:
            self.frame.use_transcript_audio(self.item, source_path)

        def run() -> None:
            try:
                if source_path is not None:
                    transcript = transcriber.transcribe(source_path, update)
                else:
                    transcript = transcriber.transcribe(
                        media.audio_url,
                        update,
                        audio_path=cache.audio_path(self.item.id),
                        audio_ready=audio_ready,
                    )
            except TranscriptUnavailable as error:
                wx.CallAfter(self.finish_error, str(error))
            except Exception as error:
                logger.exception("Podcast transcription failed")
                wx.CallAfter(self.finish_error, str(error))
            else:
                cache.write(self.item.id, transcript)
                wx.CallAfter(self.finish, transcript)

        threading.Thread(target=run, daemon=True).start()

    def update_transcript(self, transcript: Transcript) -> None:
        if self.closed:
            return
        self.set_transcript(transcript)
        insertion = self.text.GetInsertionPoint()
        self.text.ChangeValue(transcript.text)
        self.text.SetInsertionPoint(min(insertion, len(transcript.text)))

    def finish(self, transcript: Transcript) -> None:
        if self.closed:
            return
        transcript = self.frame.cached_transcript_translation(
            self.item, transcript
        )
        self.update_transcript(transcript)
        self.running = False
        self.stop_button.Enable(False)
        if self.fetch_translation:
            if transcript.translated_text:
                self.fetch_translation.Hide()
                self.Layout()
            else:
                self.fetch_translation.Enable()
        self.frame.say(tr("Transcription complete."))

    def finish_error(self, message: str) -> None:
        if self.closed:
            return
        self.running = False
        self.stop_button.Enable(False)
        if self.fetch_translation and self.latest:
            self.fetch_translation.Enable()
        if self.latest:
            partial = Transcript(self.latest.lines, self.latest.source, False)
            self.update_transcript(partial)
        self.frame.say(message)

    def on_stop(self, event: wx.Event | None = None) -> None:
        if self.transcriber and self.running:
            self.transcriber.stop()
            self.running = False
            self.stop_button.Enable(False)
            if self.fetch_translation and self.latest:
                self.fetch_translation.Enable()
            self.frame.say(tr("Stopping transcription."))

    def selected_line_index(self) -> int | None:
        if not self.synced_lines:
            return None
        insertion_point = self.text.GetInsertionPoint()
        selected = None
        for index, position in enumerate(self.synced_line_positions):
            if position > insertion_point:
                break
            selected = index
        return selected

    def play_selected_line(self) -> None:
        line_index = self.selected_line_index()
        if line_index is None:
            self.frame.say(tr("Move to a timed transcript line first."))
            return
        timestamp_ms = self.synced_lines[line_index][0]
        if self.frame.current_track_is_paused(self.track_id):
            self.frame.resume_from_lyric(self.track_id, timestamp_ms)
        else:
            self.frame.play_from_lyric(self.item, timestamp_ms)

    def play_adjacent_line(self, direction: int) -> None:
        selected = self.selected_line_index()
        target = 0 if selected is None else selected + direction
        if not 0 <= target < len(self.synced_lines):
            self.frame.say(
                tr("First transcript line.")
                if direction < 0
                else tr("Last transcript line.")
            )
            return
        position = self.synced_line_positions[target]
        self.text.SetInsertionPoint(position)
        self.text.ShowPosition(position)
        timestamp_ms = self.synced_lines[target][0]
        if self.frame.current_track_is_paused(self.track_id):
            self.frame.resume_from_lyric(self.track_id, timestamp_ms)
        else:
            self.frame.play_from_lyric(self.item, timestamp_ms)

    def on_follow_timer(self, event: wx.TimerEvent | None = None) -> None:
        position_ms = self.frame.playback_position_ms(self.track_id)
        if position_ms is None:
            return
        line_index = -1
        for index, (timestamp_ms, _text) in enumerate(self.synced_lines):
            if timestamp_ms > position_ms:
                break
            line_index = index
        if line_index < 0 or line_index == self.last_followed_line:
            return
        self.last_followed_line = line_index
        position = self.synced_line_positions[line_index]
        self.text.SetInsertionPoint(position)
        self.text.ShowPosition(position)

    def dispatch_mapped_key(self, event: wx.KeyEvent) -> bool:
        action = self.frame.keymap_action_for_event(event, ("Lyrics", "Main"))
        if not action:
            return False
        if (
            action == "pause_resume"
            and event.GetKeyCode() == wx.WXK_SPACE
            and space_belongs_to_control(event.GetEventObject())
        ):
            return False
        if action == "play_lyric_line":
            self.play_selected_line()
        elif action in {"previous_lyric_line", "next_lyric_line"}:
            self.play_adjacent_line(
                -1 if action == "previous_lyric_line" else 1
            )
        elif action == "play_focused":
            self.frame.play(self.item, announce=False)
        elif action == "seek_backward":
            self.frame.seek(-5000)
        elif action == "seek_forward":
            self.frame.seek(5000)
        elif action == "previous_track":
            self.frame.previous_track()
        elif action == "pause_resume":
            if (
                event.GetKeyCode() == wx.WXK_SPACE
                and event.GetEventObject() is self.text
            ):
                self.play_selected_line()
            else:
                self.frame.toggle_pause_resume()
        elif action == "next_track":
            self.frame.next_track()
        elif action == "toggle_mute":
            self.frame.toggle_mute()
        elif action == "volume_down":
            self.frame.adjust_volume(-5)
        elif action == "volume_up":
            self.frame.adjust_volume(5)
        else:
            return False
        return True

    def on_text_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if (
            key == wx.WXK_SPACE
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
        ):
            self.play_selected_line()
            self.consume_key(event)
            return
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.frame.toggle_pause_resume()
            self.consume_key(event)
            return
        if (
            key in (wx.WXK_UP, wx.WXK_DOWN)
            and lyric_navigation_modifier_down(event)
        ):
            self.play_adjacent_line(-1 if key == wx.WXK_UP else 1)
            self.consume_key(event)
            return
        event.Skip()

    def on_dialog_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        focused = event.GetEventObject()
        if key == wx.WXK_F4 and event.AltDown():
            self.on_close(event)
            return
        if key == wx.WXK_ESCAPE:
            self.on_close(event)
            return
        if key in ENTER_KEY_CODES + (wx.WXK_SPACE,):
            if focused is self.stop_button:
                self.on_stop(event)
                return
            if focused is self.close_button:
                self.on_close(event)
                return
        if self.dispatch_mapped_key(event):
            self.consume_key(event)
            return
        if (
            key in (wx.WXK_UP, wx.WXK_DOWN)
            and lyric_navigation_modifier_down(event)
        ):
            self.play_adjacent_line(-1 if key == wx.WXK_UP else 1)
            self.consume_key(event)
            return
        if (
            key == wx.WXK_SPACE
            and not event.AltDown()
            and not event.ShiftDown()
            and focused is self.text
        ):
            self.play_selected_line()
            self.consume_key(event)
            return
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and focused is self.text:
            self.frame.toggle_pause_resume()
            self.consume_key(event)
            return
        if key == wx.WXK_F7 and playback_adjustment_modifier_down(event):
            self.frame.toggle_mute()
            return
        if key == wx.WXK_F4 and not event.AltDown() and not event.ShiftDown() and not physical_control_down(event):
            self.frame.play(self.item, announce=False)
            return
        if key == wx.WXK_F4 and playback_adjustment_modifier_down(event):
            self.frame.adjust_volume(-5)
            return
        if key == wx.WXK_F5 and playback_adjustment_modifier_down(event):
            self.frame.adjust_volume(5)
            return
        if key == wx.WXK_F5 and not event.AltDown() and not event.ShiftDown() and not physical_control_down(event):
            self.frame.previous_track()
            return
        if key == wx.WXK_F6 and not event.AltDown() and not event.ShiftDown() and not physical_control_down(event):
            self.frame.seek(-5000)
            return
        if key == wx.WXK_F7 and not event.AltDown() and not event.ShiftDown() and not physical_control_down(event):
            self.frame.toggle_pause_resume()
            return
        if key == wx.WXK_F8 and not event.AltDown() and not event.ShiftDown() and not physical_control_down(event):
            self.frame.seek(5000)
            return
        if key == wx.WXK_F9 and not event.AltDown() and not event.ShiftDown() and not physical_control_down(event):
            self.frame.next_track()
            return
        event.Skip()

    def on_close(self, event: wx.Event | None = None) -> None:
        if self.transcriber and self.running:
            self.transcriber.stop()
        self.follow_timer.Stop()
        self.activation_focus_timer.Stop()
        for retry in self.activation_focus_retries:
            retry.Stop()
        self.activation_focus_retries.clear()
        wx.GetApp().Unbind(wx.EVT_ACTIVATE_APP, handler=self.on_app_activate)
        self.frame.Unbind(
            wx.EVT_CHILD_FOCUS,
            handler=self.on_parent_child_focus,
        )
        self.closed = True
        if self.IsModal():
            self.EndModal(wx.ID_CLOSE)
        else:
            self.Destroy()


class LyricsDialog(wx.Dialog):
    def __init__(
        self,
        parent: "MainFrame",
        lyrics: Lyrics,
        item: SpotifyItem,
    ) -> None:
        super().__init__(
            parent,
            title=tr(
                "Lyrics for {track_name} - BlindSpot"
            ).format(track_name=lyrics.track_name),
            size=(650, 600),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.frame = parent
        self.lyrics_data = lyrics
        self.closing = False
        outer = wx.BoxSizer(wx.VERTICAL)
        heading = lyrics.track_name
        if lyrics.artist_name:
            heading += tr(
                " by {artist_name}"
            ).format(artist_name=lyrics.artist_name)
        outer.Add(
            wx.StaticText(self, label=heading),
            0,
            wx.EXPAND | wx.ALL,
            12,
        )
        self.follow_braille = wx.CheckBox(
            self,
            label=tr("Follow playback on braille display"),
        )
        self.follow_braille.Enable(bool(lyrics.synced_lines))
        self.follow_braille.SetValue(
            bool(
                lyrics.synced_lines
                and parent.follow_braille_lyrics
            )
        )
        lyric_options = wx.BoxSizer(wx.HORIZONTAL)
        lyric_options.Add(
            self.follow_braille,
            0,
            wx.RIGHT,
            18,
        )
        self.phrase_mode = wx.CheckBox(
            self,
            label=tr("Enable phrase mode"),
        )
        self.phrase_mode.Enable(bool(lyrics.synced_lines))
        self.phrase_mode.SetValue(False)
        lyric_options.Add(
            self.phrase_mode,
            0,
        )
        outer.Add(
            lyric_options,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        self.find_panel = wx.Panel(self)
        find_layout = wx.BoxSizer(wx.HORIZONTAL)
        find_label = wx.StaticText(self.find_panel, label=tr("&Find"))
        self.find_text = wx.TextCtrl(
            self.find_panel,
            style=wx.TE_PROCESS_ENTER,
        )
        find_label.SetToolTip(tr("Find in lyrics"))
        self.find_text.SetName(tr("Find in lyrics"))
        self.find_previous = wx.Button(
            self.find_panel,
            label=tr("&Previous"),
        )
        self.find_next = wx.Button(
            self.find_panel,
            label=tr("&Next"),
        )
        self.find_close = wx.Button(
            self.find_panel,
            label=tr("&Close find"),
        )
        find_layout.Add(find_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        find_layout.Add(self.find_text, 1, wx.RIGHT, 6)
        find_layout.Add(self.find_previous, 0, wx.RIGHT, 6)
        find_layout.Add(self.find_next, 0, wx.RIGHT, 6)
        find_layout.Add(self.find_close, 0)
        self.find_panel.SetSizer(find_layout)
        self.find_panel.Hide()
        outer.Add(
            self.find_panel,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        self.text = wx.TextCtrl(
            self,
            value=lyrics.text,
            style=wx.TE_MULTILINE | wx.TE_READONLY,
        )
        self.text.SetName(tr("Lyrics for {heading}").format(heading=heading))
        outer.Add(
            self.text,
            1,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        self.translation_view = None
        self.fetch_translation = None
        translation_enabled = bool(
            parent.deepl.api_key and parent.deepl.target_language
        )
        if translation_enabled or lyrics.translated_text:
            self.translation_view = wx.Choice(
                self,
                choices=[tr("Original")]
                + ([tr("Translation")] if lyrics.translated_text else []),
            )
            self.translation_view.SetName(tr("Lyrics view"))
            self.translation_view.SetSelection(0)
            outer.Detach(self.text)
            outer.Add(
                self.translation_view,
                0,
                wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
                12,
            )
            outer.Add(
                self.text,
                1,
                wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
                12,
            )
            if not lyrics.translated_text:
                self.fetch_translation = wx.Button(
                    self,
                    label=tr("&Fetch translation"),
                )
                outer.Add(
                    self.fetch_translation,
                    0,
                    wx.LEFT | wx.RIGHT | wx.BOTTOM,
                    12,
                )
        buttons = self.CreateSeparatedButtonSizer(wx.CLOSE)
        if buttons:
            outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizer(outer)
        self.SetEscapeId(wx.ID_CLOSE)
        close_button = self.FindWindow(wx.ID_CLOSE)
        if self.translation_view:
            self.translation_view.MoveBeforeInTabOrder(self.text)
        if self.fetch_translation:
            self.fetch_translation.MoveAfterInTabOrder(self.text)
            if close_button:
                close_button.MoveAfterInTabOrder(self.fetch_translation)
        elif close_button:
            close_button.MoveAfterInTabOrder(self.text)
        self.item = item
        self.track_id = lyrics.track_id
        self.synced_lines = lyrics.synced_lines
        self.synced_line_positions = self._view_synced_line_positions(
            lyrics.text,
            translated=False,
        )
        self.lyric_adjustment_ms = parent.lyric_adjustment_ms(lyrics.track_id)
        self.last_braille_line = -1
        self.braille_timer = wx.Timer(self)
        self.phrase_timer = wx.Timer(self)
        self.phrase_start_ms: int | None = None
        self.phrase_end_ms: int | None = None
        self.phrase_started = False
        self.Bind(wx.EVT_CHAR_HOOK, self.on_dialog_key)
        self.Bind(wx.EVT_CHECKBOX, self.on_follow_braille, self.follow_braille)
        self.Bind(wx.EVT_CHECKBOX, self.on_phrase_mode, self.phrase_mode)
        self.Bind(wx.EVT_TIMER, self.on_braille_timer, self.braille_timer)
        self.Bind(wx.EVT_TIMER, self.on_phrase_timer, self.phrase_timer)
        self.Bind(wx.EVT_BUTTON, self.on_close_button, id=wx.ID_CLOSE)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.text.Bind(wx.EVT_KEY_DOWN, self.on_text_key)
        self.find_text.Bind(wx.EVT_KEY_DOWN, self.on_find_key)
        self.find_previous.Bind(
            wx.EVT_BUTTON,
            lambda event: self.find_lyrics(-1),
        )
        self.find_next.Bind(
            wx.EVT_BUTTON,
            lambda event: self.find_lyrics(1),
        )
        self.find_close.Bind(wx.EVT_BUTTON, self.on_close_find)
        if self.translation_view:
            self.translation_view.Bind(
                wx.EVT_CHOICE,
                self.on_translation_view,
            )
        if self.fetch_translation:
            self.fetch_translation.Bind(
                wx.EVT_BUTTON,
                self.on_fetch_translation,
            )
        self.text.SetInsertionPoint(0)
        self.text.SetFocus()
        if self.follow_braille.GetValue():
            self.braille_timer.Start(BRAILLE_LYRICS_TIMER_MS)
            self.update_braille_line()

    def on_translation_view(self, event: wx.CommandEvent | None = None) -> None:
        previous_value = self.text.GetValue()
        previous_position = self.text.GetInsertionPoint()
        translated = bool(
            self.translation_view
            and self.translation_view.GetSelection() == 1
            and self.lyrics_data.translated_text
        )
        value = (
            self.lyrics_data.translated_text
            if translated
            else self.lyrics_data.text
        )
        position = self._corresponding_text_position(
            previous_value,
            value,
            previous_position,
        )
        self.text.SetValue(value)
        self.synced_line_positions = self._view_synced_line_positions(
            value,
            translated=translated,
        )
        self.text.SetName(
            tr("Translated lyrics") if translated else tr("Original lyrics")
        )
        self.text.SetInsertionPoint(position)
        self.text.ShowPosition(position)

    def on_fetch_translation(self, event: wx.CommandEvent) -> None:
        if not self.fetch_translation:
            return
        logger.debug("Lyrics Fetch translation command received")
        self.fetch_translation.Disable()
        self.fetch_translation.SetLabel(tr("Fetching translation..."))
        self.frame.run_task(
            tr("Fetching lyrics translation"),
            lambda: self.frame.translate_lyrics(self.lyrics_data),
            self.finish_fetch_translation,
            failure=self.fail_fetch_translation,
            error_parent=self,
            requires_spotify=False,
        )

    def finish_fetch_translation(self, lyrics: Lyrics) -> None:
        if self.closing:
            return
        if self.translation_view and self.translation_view.GetCount() == 1:
            self.translation_view.Append(tr("Translation"))
        if self.fetch_translation:
            self.fetch_translation.Hide()
        self.Layout()
        if self.translation_view:
            self.translation_view.SetSelection(1)
            self.on_translation_view()
            self.text.SetFocus()

    def fail_fetch_translation(self) -> None:
        if self.closing:
            return
        if self.fetch_translation:
            self.fetch_translation.Enable()
            self.fetch_translation.SetLabel(tr("&Fetch translation"))

    @staticmethod
    def _synced_line_positions(
        lyrics_text: str,
        synced_lines: list[tuple[int, str]],
    ) -> list[int]:
        display_lines = []
        position = 0
        for line in lyrics_text.splitlines(keepends=True):
            display_lines.append((position, " ".join(line.split()).casefold()))
            position += len(line)
        positions = []
        next_display_line = 0
        for index, (_, lyric) in enumerate(synced_lines):
            wanted = " ".join(lyric.split()).casefold()
            match = next(
                (
                    line_index
                    for line_index in range(next_display_line, len(display_lines))
                    if display_lines[line_index][1] == wanted
                ),
                None,
            )
            if match is not None:
                positions.append(display_lines[match][0])
                next_display_line = match + 1
            elif index < len(display_lines):
                positions.append(display_lines[index][0])
            else:
                positions.append(len(lyrics_text))
        return positions

    def _view_synced_line_positions(
        self,
        lyrics_text: str,
        *,
        translated: bool,
    ) -> list[int]:
        original_positions = self._synced_line_positions(
            self.lyrics_data.text,
            self.synced_lines,
        )
        if translated:
            positions = self._corresponding_line_positions(
                self.lyrics_data.text,
                lyrics_text,
                original_positions,
            )
        else:
            positions = original_positions
        return native_text_positions(lyrics_text, positions)

    @staticmethod
    def _corresponding_line_positions(
        source_text: str,
        target_text: str,
        source_positions: list[int],
    ) -> list[int]:
        """Map line starts from source lyrics to the same translated lines."""
        source_starts = []
        position = 0
        for line in source_text.splitlines(keepends=True):
            source_starts.append(position)
            position += len(line)

        target_starts = []
        position = 0
        for line in target_text.splitlines(keepends=True):
            target_starts.append(position)
            position += len(line)

        source_lines = {position: index for index, position in enumerate(source_starts)}
        return [
            target_starts[source_lines[position]]
            if position in source_lines
            and source_lines[position] < len(target_starts)
            else len(target_text)
            for position in source_positions
        ]

    @staticmethod
    def _corresponding_text_position(
        source_text: str,
        target_text: str,
        source_position: int,
        platform: str | None = None,
    ) -> int:
        """Keep the caret near the same place when changing lyric views."""
        platform = sys.platform if platform is None else platform
        source_lines = source_text.split("\n")
        target_lines = target_text.split("\n")

        def starts(text: str, lines: list[str]) -> list[int]:
            logical = []
            position = 0
            for line in lines:
                logical.append(position)
                position += len(line) + 1
            return native_text_positions(text, logical, platform)

        source_starts = starts(source_text, source_lines)
        target_starts = starts(target_text, target_lines)
        source_line = 0
        for index, start in enumerate(source_starts):
            if start > source_position:
                break
            source_line = index

        target_line = min(source_line, len(target_lines) - 1)
        source_length = len(source_lines[source_line])
        source_column = max(0, source_position - source_starts[source_line])
        proportion = min(source_column, source_length) / max(source_length, 1)
        target_column = round(proportion * len(target_lines[target_line]))
        return target_starts[target_line] + target_column

    def on_follow_braille(self, event: wx.CommandEvent) -> None:
        enabled = self.follow_braille.GetValue()
        self.frame.set_follow_braille_lyrics(enabled)
        if enabled:
            self.last_braille_line = -1
            self.braille_timer.Start(BRAILLE_LYRICS_TIMER_MS)
            self.update_braille_line()
        else:
            self.braille_timer.Stop()

    def on_phrase_mode(self, event: wx.CommandEvent) -> None:
        if not self.phrase_mode.GetValue():
            LyricsDialog.cancel_phrase(self)

    def on_text_key(self, event: wx.KeyEvent) -> None:
        if (
            event.GetKeyCode() in (ord("N"), ord("n"), ord("P"), ord("p"))
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
            and getattr(self, "find_panel", None)
            and self.find_panel.IsShown()
            and self.find_text.GetValue()
        ):
            self.find_lyrics(
                -1 if event.GetKeyCode() in (ord("P"), ord("p")) else 1
            )
            return
        if (
            event.GetKeyCode() == wx.WXK_SPACE
            and not event.AltDown()
            and event.ShiftDown()
            and not physical_control_down(event)
        ):
            LyricsDialog.playback_from_selected_lyric(self)
            return
        if (
            event.GetKeyCode() == wx.WXK_SPACE
            and not event.AltDown()
            and not event.ShiftDown()
        ):
            LyricsDialog.cancel_phrase(self)
            LyricsDialog.playback_from_selected_lyric(self, False)
            return
        if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            LyricsDialog.cancel_phrase(self)
            self.frame.toggle_pause_resume()
            return
        key = event.GetKeyCode()
        if (
            key in (wx.WXK_UP, wx.WXK_DOWN)
            and lyric_navigation_modifier_down(event)
        ):
            direction = -1 if key == wx.WXK_UP else 1
            LyricsDialog.playback_from_adjacent_lyric(self, direction)
            return
        if not physical_control_down(event):
            event.Skip()
            return
        if event.ShiftDown() and key in (ord(","), ord("<")):
            self.adjust_lyric_timing(500)
            return
        if event.ShiftDown() and key in (ord("."), ord(">")):
            self.adjust_lyric_timing(-500)
            return
        event.Skip()

    @staticmethod
    def find_shortcut_down(event: wx.KeyEvent) -> bool:
        if sys.platform == "darwin":
            return event.ControlDown() and not physical_control_down(event)
        return physical_control_down(event)

    def show_find(self) -> None:
        if not self.find_panel.IsShown():
            self.find_paused_braille = bool(self.follow_braille.GetValue())
            if self.find_paused_braille:
                self.braille_timer.Stop()
            self.find_panel.Show()
            self.Layout()
        self.find_text.SetFocus()
        self.find_text.SelectAll()

    def close_find(self) -> None:
        self.find_panel.Hide()
        self.Layout()
        self.text.SetFocus()
        if (
            getattr(self, "find_paused_braille", False)
            and self.follow_braille.GetValue()
        ):
            self.last_braille_line = -1
            self.braille_timer.Start(BRAILLE_LYRICS_TIMER_MS)
        self.find_paused_braille = False

    def on_close_find(self, event: wx.CommandEvent) -> None:
        self.close_find()

    def on_find_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.find_lyrics(-1 if event.ShiftDown() else 1)
            return
        if key == wx.WXK_ESCAPE:
            self.close_find()
            return
        event.Skip()

    def find_lyrics(self, direction: int) -> None:
        query = self.find_text.GetValue()
        if not query:
            self.frame.say(tr("Enter text to find."))
            return
        value = self.text.GetValue()
        if sys.platform == "win32":
            value = value.replace("\n", "\r\n")
        searchable = value.casefold()
        wanted = query.casefold()
        selection_start, selection_end = self.text.GetSelection()
        same_query = getattr(self, "last_find_query", None) == wanted
        previous_match = getattr(self, "last_find_match", None)
        if direction < 0:
            before = (
                previous_match[0]
                if same_query and previous_match
                else selection_start
            )
            position = searchable.rfind(wanted, 0, before)
        else:
            after = (
                previous_match[1]
                if same_query and previous_match
                else selection_end
            )
            position = searchable.find(wanted, after)
        self.last_find_query = wanted
        if position < 0:
            self.frame.say(tr("Not found."))
            return
        end = position + len(query)
        self.last_find_match = (position, end)
        self.text.SetFocus()
        self.text.SetInsertionPoint(position)
        self.text.ShowPosition(position)
        line_start = value.rfind("\n", 0, position) + 1
        line_end = value.find("\n", end)
        if line_end < 0:
            line_end = len(value)
        found_line = value[line_start:line_end].strip()
        if found_line:
            self.frame.say(found_line)
        logger.debug(
            "Lyrics find moved caret position=%d length=%d direction=%d",
            position,
            len(query),
            direction,
        )

    def on_dialog_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if key == wx.WXK_F4 and event.AltDown():
            logger.debug("Lyrics Alt+F4 closing dialog")
            self.on_close_button(event)
            return
        if (
            key == wx.WXK_TAB
            and not event.AltDown()
            and not physical_control_down(event)
        ):
            self.move_tab_focus(-1 if event.ShiftDown() else 1)
            return
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER, wx.WXK_SPACE):
            focused = event.GetEventObject()
            find_window = getattr(self, "FindWindow", None)
            close_button = find_window(wx.ID_CLOSE) if find_window else None
            if focused is close_button:
                logger.debug("Lyrics Close activated from keyboard")
                self.on_close_button(event)
                return
            fetch = getattr(self, "fetch_translation", None)
            if fetch and focused is fetch:
                logger.debug("Lyrics Fetch translation activated from keyboard")
                self.on_fetch_translation(event)
                return
        if key == wx.WXK_ESCAPE and not self.find_panel.IsShown():
            logger.debug("Lyrics Escape closing dialog")
            self.on_close_button(event)
            return
        if (
            key in (ord("F"), ord("f"))
            and LyricsDialog.find_shortcut_down(event)
            and not event.AltDown()
            and not event.ShiftDown()
        ):
            self.show_find()
            return
        if (
            event.GetKeyCode() == wx.WXK_ESCAPE
            and getattr(self, "find_panel", None)
            and self.find_panel.IsShown()
            and window_is_or_descendant(
                event.GetEventObject(), self.find_panel
            )
        ):
            self.close_find()
            return
        if LyricsDialog.dispatch_mapped_key(self, event):
            return
        frame_keymap = getattr(getattr(self, "frame", None), "keymap", None)
        if frame_keymap:
            chord = chord_from_event(event, frame_keymap.platform)
            if chord and frame_keymap.disabled_default(
                chord,
                ("Lyrics", "Main"),
            ):
                return
        if (
            key in (wx.WXK_UP, wx.WXK_DOWN)
            and lyric_navigation_modifier_down(event)
        ):
            direction = -1 if key == wx.WXK_UP else 1
            LyricsDialog.playback_from_adjacent_lyric(self, direction)
            return
        if (
            key == wx.WXK_SPACE
            and not event.AltDown()
            and event.ShiftDown()
            and not physical_control_down(event)
        ):
            LyricsDialog.playback_from_selected_lyric(self)
            return
        if (
            key == wx.WXK_SPACE
            and not event.AltDown()
            and not event.ShiftDown()
            and event.GetEventObject() is getattr(self, "text", None)
        ):
            LyricsDialog.cancel_phrase(self)
            LyricsDialog.playback_from_selected_lyric(self, False)
            return
        if (
            key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
            and event.GetEventObject() is getattr(self, "text", None)
        ):
            LyricsDialog.cancel_phrase(self)
            self.frame.toggle_pause_resume()
            return
        if (
            key == wx.WXK_F7
            and playback_adjustment_modifier_down(event)
        ):
            self.frame.toggle_mute()
            return
        if (
            key == wx.WXK_F4
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
        ):
            LyricsDialog.cancel_phrase(self)
            self.frame.play(self.item, announce=False)
            return
        if (
            key == wx.WXK_F4
            and playback_adjustment_modifier_down(event)
        ):
            self.frame.adjust_volume(-5)
            return
        if (
            key == wx.WXK_F5
            and playback_adjustment_modifier_down(event)
        ):
            self.frame.adjust_volume(5)
            return
        if (
            key == wx.WXK_F5
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
        ):
            LyricsDialog.cancel_phrase(self)
            self.frame.previous_track()
            return
        if (
            key == wx.WXK_F6
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
        ):
            LyricsDialog.cancel_phrase(self)
            self.frame.seek(-5000)
            return
        if (
            key == wx.WXK_F7
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
        ):
            LyricsDialog.cancel_phrase(self)
            self.frame.toggle_pause_resume()
            return
        if (
            key == wx.WXK_F8
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
        ):
            LyricsDialog.cancel_phrase(self)
            self.frame.seek(5000)
            return
        if (
            key == wx.WXK_F9
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
        ):
            LyricsDialog.cancel_phrase(self)
            self.frame.next_track()
            return
        event.Skip()

    def tab_controls(self) -> list[wx.Window]:
        controls = [self.follow_braille, self.phrase_mode]
        if self.find_panel.IsShown():
            controls.extend(
                [
                    self.find_text,
                    self.find_previous,
                    self.find_next,
                    self.find_close,
                ]
            )
        if self.translation_view:
            controls.append(self.translation_view)
        controls.append(self.text)
        if self.fetch_translation and self.fetch_translation.IsShown():
            controls.append(self.fetch_translation)
        close_button = self.FindWindow(wx.ID_CLOSE)
        if close_button:
            controls.append(close_button)
        return [
            control
            for control in controls
            if control.IsShown() and control.IsEnabled()
        ]

    def move_tab_focus(self, direction: int) -> None:
        controls = self.tab_controls()
        if not controls:
            return
        focused = wx.Window.FindFocus()
        try:
            current = controls.index(focused)
        except ValueError:
            current = -1 if direction > 0 else 0
        controls[(current + direction) % len(controls)].SetFocus()

    def dispatch_mapped_key(self, event: wx.KeyEvent) -> bool:
        frame = getattr(self, "frame", None)
        if not frame or not hasattr(frame, "keymap_action_for_event"):
            return False
        action = frame.keymap_action_for_event(event, ("Lyrics", "Main"))
        if not action:
            return False
        if (
            action == "pause_resume"
            and event.GetKeyCode() == wx.WXK_SPACE
            and space_belongs_to_control(event.GetEventObject())
        ):
            return False
        if action == "play_lyric_line":
            LyricsDialog.playback_from_selected_lyric(self)
        elif action in {"previous_lyric_line", "next_lyric_line"}:
            LyricsDialog.playback_from_adjacent_lyric(
                self,
                -1 if action == "previous_lyric_line" else 1,
            )
        elif action == "lyrics_earlier":
            self.adjust_lyric_timing(500)
        elif action == "lyrics_later":
            self.adjust_lyric_timing(-500)
        elif action == "play_focused":
            LyricsDialog.cancel_phrase(self)
            frame.play(self.item, announce=False)
        elif action == "seek_backward":
            LyricsDialog.cancel_phrase(self)
            frame.seek(-5000)
        elif action == "seek_forward":
            LyricsDialog.cancel_phrase(self)
            frame.seek(5000)
        elif action in {"next_verse", "previous_verse"}:
            LyricsDialog.cancel_phrase(self)
            frame.jump_lyric_section(1 if action == "next_verse" else -1)
        elif action == "previous_track":
            LyricsDialog.cancel_phrase(self)
            frame.previous_track()
        elif action == "pause_resume":
            if (
                event.GetKeyCode() == wx.WXK_SPACE
                and event.GetEventObject() is getattr(self, "text", None)
            ):
                LyricsDialog.cancel_phrase(self)
                LyricsDialog.playback_from_selected_lyric(self, False)
            else:
                LyricsDialog.cancel_phrase(self)
                frame.toggle_pause_resume()
        elif action == "next_track":
            LyricsDialog.cancel_phrase(self)
            frame.next_track()
        elif action == "toggle_mute":
            frame.toggle_mute()
        elif action == "volume_down":
            frame.adjust_volume(-5)
        elif action == "volume_up":
            frame.adjust_volume(5)
        else:
            return False
        return True

    def selected_synced_line_index(self) -> int | None:
        if not getattr(self, "synced_lines", None):
            return None
        insertion_point = self.text.GetInsertionPoint()
        selected = None
        for index, position in enumerate(self.synced_line_positions):
            if position > insertion_point:
                break
            selected = index
        return selected

    def playback_from_selected_lyric(self, use_phrase_mode: bool = True) -> None:
        if not getattr(self, "synced_lines", None):
            self.frame.say(msg.SYNCED_LYRICS_UNAVAILABLE)
            return
        line_index = LyricsDialog.selected_synced_line_index(self)
        if line_index is None:
            self.frame.say(msg.MOVE_TO_SYNCED_LINE)
            return
        LyricsDialog.play_synced_line(self, line_index, use_phrase_mode)

    def play_synced_line(
        self,
        line_index: int,
        use_phrase_mode: bool = True,
    ) -> None:
        timestamp_ms = self.synced_lines[line_index][0]
        phrase_mode = getattr(self, "phrase_mode", None)
        if use_phrase_mode and phrase_mode and phrase_mode.GetValue():
            end_ms = (
                self.synced_lines[line_index + 1][0]
                if line_index + 1 < len(self.synced_lines)
                else int(getattr(self.item, "duration_ms", 0) or 0)
            )
            if end_ms > timestamp_ms:
                self.phrase_start_ms = timestamp_ms
                self.phrase_end_ms = end_ms
                self.phrase_started = False
                self.phrase_timer.Start(PHRASE_MODE_TIMER_MS)
            else:
                LyricsDialog.cancel_phrase(self)
                self.frame.say(msg.PHRASE_END_UNAVAILABLE)
                return
        else:
            LyricsDialog.cancel_phrase(self)
        if self.frame.current_track_is_paused(self.track_id):
            self.frame.resume_from_lyric(self.track_id, timestamp_ms)
        else:
            self.frame.play_from_lyric(self.item, timestamp_ms)

    def playback_from_adjacent_lyric(self, direction: int) -> None:
        if not getattr(self, "synced_lines", None):
            self.frame.say(msg.SYNCED_LYRICS_UNAVAILABLE)
            return
        selected = LyricsDialog.selected_synced_line_index(self)
        target = 0 if selected is None else selected + direction
        if not 0 <= target < len(self.synced_lines):
            boundary = tr("First") if direction < 0 else tr("Last")
            self.frame.say(msg.lyric_boundary(boundary))
            return
        position = self.synced_line_positions[target]
        self.text.SetInsertionPoint(position)
        self.text.ShowPosition(position)
        LyricsDialog.play_synced_line(self, target)

    def adjust_lyric_timing(self, delta_ms: int) -> None:
        self.lyric_adjustment_ms += delta_ms
        self.frame.set_lyric_adjustment_ms(
            self.track_id,
            self.lyric_adjustment_ms,
        )
        effective_lead_ms = BRAILLE_LYRIC_LEAD_MS + self.lyric_adjustment_ms
        if effective_lead_ms >= 0:
            timing = tr(
                "{seconds:g} seconds early"
            ).format(seconds=effective_lead_ms / 1000)
        else:
            timing = tr(
                "{seconds:g} seconds late"
            ).format(seconds=abs(effective_lead_ms) / 1000)
        self.frame.say(msg.lyric_timing(timing))
        self.last_braille_line = -1
        self.update_braille_line()

    def on_braille_timer(self, event: wx.TimerEvent) -> None:
        self.update_braille_line()

    def on_phrase_timer(self, event: wx.TimerEvent) -> None:
        if self.phrase_start_ms is None or self.phrase_end_ms is None:
            LyricsDialog.cancel_phrase(self)
            return
        position_ms = self.frame.playback_position_ms(self.track_id)
        if position_ms is None:
            return
        if not self.phrase_started:
            if self.phrase_start_ms <= position_ms < self.phrase_end_ms:
                self.phrase_started = True
            return
        if position_ms >= self.phrase_end_ms:
            LyricsDialog.cancel_phrase(self)
            self.frame.pause_phrase_playback(self.track_id)

    def cancel_phrase(self) -> None:
        phrase_timer = getattr(self, "phrase_timer", None)
        if phrase_timer:
            phrase_timer.Stop()
        self.phrase_start_ms = None
        self.phrase_end_ms = None
        self.phrase_started = False

    def update_braille_line(self) -> None:
        position_ms = self.frame.playback_position_ms(self.track_id)
        if position_ms is None:
            # Keep following armed while this song has not started yet. The
            # timer will pick up its playback position as soon as it begins.
            return
        position_ms += BRAILLE_LYRIC_LEAD_MS + self.lyric_adjustment_ms
        line_index = -1
        for index, (timestamp_ms, text) in enumerate(self.synced_lines):
            if timestamp_ms > position_ms:
                break
            line_index = index
        if line_index < 0:
            return
        if line_index == self.last_braille_line:
            return
        self.last_braille_line = line_index
        try:
            line = self.synced_lines[line_index][1]
            if sys.platform in ("win32", "darwin"):
                # Let the screen reader follow the caret instead of sending
                # transient output messages, which interrupt braille reading.
                position = self.synced_line_positions[line_index]
                self.text.SetInsertionPoint(position)
                self.text.ShowPosition(position)
            else:
                self.frame.announcer.braille(line)
        except Exception:
            logger.exception("Braille lyric output failed")
            self.follow_braille.SetValue(False)
            self.braille_timer.Stop()

    def on_close_button(self, event: wx.CommandEvent) -> None:
        logger.debug("Lyrics modal close requested is_modal=%s", self.IsModal())
        self.closing = True
        self.braille_timer.Stop()
        LyricsDialog.cancel_phrase(self)
        if self.IsModal():
            self.EndModal(wx.ID_CLOSE)
        else:
            self.Destroy()

    def on_close(self, event: wx.CloseEvent) -> None:
        self.closing = True
        self.braille_timer.Stop()
        LyricsDialog.cancel_phrase(self)
        if self.IsModal():
            self.EndModal(wx.ID_CLOSE)
        else:
            self.Destroy()


class AlternateVersionsDialog(wx.Dialog):
    def __init__(
        self,
        parent: "MainFrame",
        original: SpotifyItem,
        candidates: list[SpotifyItem],
        replace: Callable[[SpotifyItem, "AlternateVersionsDialog"], None]
        | None = None,
    ) -> None:
        super().__init__(
            parent,
            title=tr(
                "Alternate versions of {name}"
            ).format(name=original.name),
            size=(760, 480),
        )
        self.frame = parent
        self.replace = replace
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(
            wx.StaticText(
                self,
                label=tr(
                    "Alternate versions of {name}"
                ).format(name=original.name),
            ),
            0,
            wx.ALL,
            10,
        )
        self.items = ItemList(self)
        self.items.SetName(tr("Alternate versions"))
        self.items.set_items(candidates)
        outer.Add(self.items, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.replace_button = (
            wx.Button(self, label=tr("&Replace")) if replace else None
        )
        self.close_button = wx.Button(self, wx.ID_CLOSE, tr("&Close"))
        if self.replace_button:
            buttons.Add(self.replace_button, 0, wx.RIGHT, 8)
        buttons.Add(self.close_button, 0)
        outer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        self.SetSizer(outer)
        self.items.Bind(self.items.ACTIVATED_EVENT, self.on_review)
        self.items.Bind(wx.EVT_CONTEXT_MENU, self.on_context_menu)
        if self.replace_button:
            self.replace_button.Bind(wx.EVT_BUTTON, self.on_replace)
        self.close_button.Bind(wx.EVT_BUTTON, self.on_close)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key)
        self.items.SetFocus()

    def on_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if (
            key in (wx.WXK_BACK, wx.WXK_ESCAPE)
            and not physical_control_down(event)
            and not event.AltDown()
            and not event.ShiftDown()
        ):
            AlternateVersionsDialog.on_close(self)
            return
        if (
            key != wx.WXK_TAB
            or physical_control_down(event)
            or event.AltDown()
        ):
            event.Skip()
            return
        controls = [self.items]
        if self.replace_button:
            controls.append(self.replace_button)
        controls.append(self.close_button)
        focused = wx.Window.FindFocus()
        focused_list = item_list_ancestor(focused)
        if focused_list is self.items:
            focused = self.items
        try:
            index = controls.index(focused)
        except ValueError:
            index = 0 if event.ShiftDown() else -1
        direction = -1 if event.ShiftDown() else 1
        controls[(index + direction) % len(controls)].SetFocus()

    def on_item_list_char_hook(self, event: wx.KeyEvent) -> None:
        AlternateVersionsDialog.on_key(self, event)

    def selected_item(self) -> SpotifyItem | None:
        return self.items.selected_item()

    def on_review(self, event: wx.Event | None = None) -> None:
        item = AlternateVersionsDialog.selected_item(self)
        if item:
            self.frame.play_playable_item(item)

    def on_replace(self, event: wx.Event | None = None) -> None:
        item = AlternateVersionsDialog.selected_item(self)
        if item and self.replace:
            self.replace(item, self)

    def on_context_menu(self, event: wx.Event | None = None) -> None:
        item = AlternateVersionsDialog.selected_item(self)
        if not item:
            return
        menu = wx.Menu()
        review = menu.Append(wx.ID_ANY, tr("&Review"))
        menu.Bind(wx.EVT_MENU, self.on_review, review)
        if self.replace:
            replace = menu.Append(
                wx.ID_ANY, tr("&Replace playlist track...")
            )
            menu.Bind(wx.EVT_MENU, self.on_replace, replace)
        self.items.PopupMenu(menu)
        menu.Destroy()

    def finish_replace(self) -> None:
        if self.IsModal():
            self.EndModal(wx.ID_OK)
        else:
            self.Destroy()

    def on_close(self, event: wx.Event | None = None) -> None:
        if self.IsModal():
            self.EndModal(wx.ID_CLOSE)
        else:
            self.Destroy()


class CreatePlaylistDialog(wx.Dialog):
    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, title=tr("Create playlist"))
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(
            wx.StaticText(self, label=tr("Playlist name")),
            0,
            wx.LEFT | wx.RIGHT | wx.TOP,
            12,
        )
        self.name = wx.TextCtrl(self)
        self.public = wx.CheckBox(self, label=tr("Public playlist"))
        outer.Add(self.name, 0, wx.EXPAND | wx.ALL, 12)
        outer.Add(self.public, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        buttons = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        if buttons:
            outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizerAndFit(outer)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        # Run after the modal window is shown; otherwise Windows may give the
        # default OK button focus when the dialog is activated.
        wx.CallAfter(self.focus_name)

    def focus_name(self) -> None:
        self.name.SetFocus()
        self.name.SelectAll()

    def on_ok(self, event: wx.CommandEvent) -> None:
        if not self.name.GetValue().strip():
            self.name.SetFocus()
            return
        event.Skip()


ITEM_LIST_USES_DATAVIEW = sys.platform == "darwin"
ItemListBase = dv.DataViewListCtrl if ITEM_LIST_USES_DATAVIEW else wx.ListCtrl


class ItemList(ItemListBase):
    TYPEAHEAD_TIMEOUT_SECONDS = 1.0
    ACTIVATED_EVENT = (
        dv.EVT_DATAVIEW_ITEM_ACTIVATED
        if ITEM_LIST_USES_DATAVIEW
        else wx.EVT_LIST_ITEM_ACTIVATED
    )

    def __init__(self, parent: wx.Window) -> None:
        if ITEM_LIST_USES_DATAVIEW:
            super().__init__(
                parent,
                style=dv.DV_MULTIPLE | dv.DV_NO_HEADER,
            )
            self.AppendTextColumn("")
        else:
            super().__init__(
                parent,
                style=wx.LC_REPORT | wx.LC_NO_HEADER,
            )
            self.InsertColumn(0, "")
        self.SetName(tr("Items"))
        self.items: list[SpotifyItem] = []
        self._typeahead_text = ""
        self._typeahead_time = 0.0
        self.Bind(wx.EVT_SIZE, self.on_size)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)

    def on_char_hook(self, event: wx.KeyEvent) -> None:
        panel = self.GetParent()
        get_keycode = getattr(event, "GetKeyCode", None)
        chord = None
        if get_keycode and get_keycode() in tuple(
            ord(letter) for letter in "AaCcXxVv"
        ):
            try:
                chord = chord_from_event(event)
            except AttributeError:
                # Some synthetic accessibility events expose only a subset
                # of wx.KeyEvent. They should continue through normal routing.
                pass
        if chord in {"Control+A", "Command+A"}:
            self.select_all_items()
            frame = getattr(panel, "frame", None)
            if frame:
                frame.say(msg.selected_count(len(self.GetSelections())))
            return
        if chord in {"Control+C", "Command+C"}:
            frame = getattr(panel, "frame", None)
            if frame:
                frame.copy_items_to_playlist_clipboard(self, cut=False)
            return
        if chord in {"Control+X", "Command+X"}:
            frame = getattr(panel, "frame", None)
            if frame:
                frame.copy_items_to_playlist_clipboard(self, cut=True)
            return
        if chord in {"Control+V", "Command+V"}:
            frame = getattr(panel, "frame", None)
            if frame:
                frame.paste_playlist_clipboard()
            return
        host = getattr(panel, "hosted_in", None)
        if host:
            if not host.handle_key(event) and not ItemList.select_by_typed_letter(
                self, event
            ):
                event.Skip()
            return
        panel_handler = getattr(panel, "on_item_list_char_hook", None)
        if panel_handler:
            panel_handler(event)
            return
        if ItemList.select_by_typed_letter(self, event):
            return
        frame = getattr(panel, "frame", None)
        if frame:
            # macOS DataView controls consume keyboard chords before their
            # containing frame sees them, and on Windows an unhandled bare
            # letter otherwise falls through to native dialog mnemonic
            # matching (e.g. plain "S" activating the "&Search" button).
            # Route every key through the same global dispatcher used by
            # the rest of the interface.
            frame.on_global_key(event)
        else:
            event.Skip()

    def select_by_typed_letter(self, event: wx.KeyEvent) -> bool:
        get_modifiers = getattr(event, "GetModifiers", None)
        get_keycode = getattr(event, "GetKeyCode", None)
        if not get_modifiers or not get_keycode:
            return False
        modifiers = int(get_modifiers())
        command_modifiers = (
            wx.MOD_CONTROL | wx.MOD_ALT | wx.MOD_WIN | wx.MOD_RAW_CONTROL
        )
        meta_down = getattr(event, "MetaDown", None)
        if modifiers & command_modifiers or (meta_down and meta_down()):
            return False
        keycode = int(get_keycode())
        if not ord("A") <= keycode <= ord("Z"):
            return False
        letter = chr(keycode).casefold()
        now = time.monotonic()
        previous_text = getattr(self, "_typeahead_text", "")
        previous_time = getattr(self, "_typeahead_time", 0.0)
        prefix = (
            previous_text + letter
            if now - previous_time <= ItemList.TYPEAHEAD_TIMEOUT_SECONDS
            else letter
        )
        self._typeahead_text = prefix
        self._typeahead_time = now
        count = self.GetItemCount()
        if not count:
            return False
        current = self.GetSelection()
        start = 0 if len(prefix) > 1 else 1
        for offset in range(start, count + start):
            row = (current + offset) % count
            if ITEM_LIST_USES_DATAVIEW:
                label = str(self.GetTextValue(row, 0))
            else:
                label = str(self.GetItemText(row, 0))
            if label.lstrip().casefold().startswith(prefix):
                self.SetSelection(row)
                return True
        if len(prefix) > 1:
            self._typeahead_text = letter
            for offset in range(1, count + 1):
                row = (current + offset) % count
                label = (
                    str(self.GetTextValue(row, 0))
                    if ITEM_LIST_USES_DATAVIEW
                    else str(self.GetItemText(row, 0))
                )
                if label.lstrip().casefold().startswith(letter):
                    self.SetSelection(row)
                    return True
        return False

    def on_size(self, event: wx.SizeEvent) -> None:
        width = self.GetClientSize().width
        if width > 0:
            if ITEM_LIST_USES_DATAVIEW:
                self.GetColumn(0).SetWidth(width)
            else:
                self.SetColumnWidth(0, width)
        event.Skip()

    def set_items(
        self,
        items: list[SpotifyItem],
        selected: int = 0,
        *,
        labels: list[str] | None = None,
    ) -> None:
        self.items = items
        self.Freeze()
        try:
            self.DeleteAllItems()
            for index, item in enumerate(items):
                label = labels[index] if labels is not None else item.accessible_label()
                if ITEM_LIST_USES_DATAVIEW:
                    self.AppendItem([label])
                else:
                    self.InsertItem(index, label)
        finally:
            self.Thaw()
        if items:
            self.SetSelection(min(max(0, selected), len(items) - 1))

    def SetSelection(self, index: int) -> None:
        if ITEM_LIST_USES_DATAVIEW:
            self.UnselectAll()
            if 0 <= index < len(self.items):
                item = self.RowToItem(index)
                self.SelectRow(index)
                self.SetCurrentItem(item)
                self.EnsureVisible(item)
            return
        state_mask = wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED
        for row in range(self.GetItemCount()):
            self.SetItemState(row, 0, state_mask)
        if 0 <= index < len(self.items):
            self.SetItemState(index, state_mask, state_mask)
            self.EnsureVisible(index)

    def GetSelection(self) -> int:
        if ITEM_LIST_USES_DATAVIEW:
            current = self.ItemToRow(self.GetCurrentItem())
            return current if current >= 0 else self.GetSelectedRow()
        focused = self.GetNextItem(
            -1,
            wx.LIST_NEXT_ALL,
            wx.LIST_STATE_FOCUSED,
        )
        return focused if focused >= 0 else self.GetFirstSelected()

    def GetSelections(self) -> list[int]:
        if ITEM_LIST_USES_DATAVIEW:
            return [
                row
                for item in super().GetSelections()
                if (row := self.ItemToRow(item)) >= 0
            ]
        selected = []
        row = self.GetFirstSelected()
        while row >= 0:
            selected.append(row)
            row = self.GetNextSelected(row)
        return selected

    def Append(self, label: str) -> None:
        if ITEM_LIST_USES_DATAVIEW:
            self.AppendItem([label])
        else:
            self.InsertItem(self.GetItemCount(), label)

    def Insert(self, label: str, index: int) -> None:
        if ITEM_LIST_USES_DATAVIEW:
            self.InsertItem(index, [label])
        else:
            self.InsertItem(index, label)

    def Delete(self, index: int) -> None:
        super().DeleteItem(index)

    def SetString(self, index: int, label: str) -> None:
        if ITEM_LIST_USES_DATAVIEW:
            self.SetValue(label, index, 0)
        else:
            self.SetItem(index, 0, label)

    def selected_item(self) -> SpotifyItem | None:
        index = self.GetSelection()
        return self.items[index] if 0 <= index < len(self.items) else None

    def marked_items(self) -> list[SpotifyItem]:
        return [
            self.items[index]
            for index in self.GetSelections()
            if 0 <= index < len(self.items)
        ]

    def select_all_items(self) -> None:
        if ITEM_LIST_USES_DATAVIEW:
            self.SelectAll()
            return
        state = wx.LIST_STATE_SELECTED
        for row in range(self.GetItemCount()):
            self.SetItemState(row, state, state)

    def remove_at(self, index: int) -> None:
        if not 0 <= index < len(self.items):
            return
        del self.items[index]
        self.Delete(index)
        if self.items:
            self.SetSelection(min(index, len(self.items) - 1))


def item_list_ancestor(window: wx.Window | None) -> ItemList | None:
    while window:
        if isinstance(window, ItemList):
            return window
        try:
            window = window.GetParent()
        except (AttributeError, RuntimeError):
            return None
    return None


def focusable_control(window: wx.Window) -> bool:
    """Report whether Tab can land on this control."""
    try:
        return bool(window.IsEnabled() and window.IsShown())
    except RuntimeError:
        return False


def radio_box_ancestor(window: wx.Window | None) -> wx.RadioBox | None:
    while window:
        if isinstance(window, wx.RadioBox):
            return window
        try:
            window = window.GetParent()
        except (AttributeError, RuntimeError):
            return None
    return None


class SearchPanel(wx.Panel):
    def __init__(self, parent: wx.Window, frame: "MainFrame") -> None:
        super().__init__(parent)
        self.frame = frame
        self.history = NavigationHistory(ViewState(tr("Search results"), []))

        outer = wx.BoxSizer(wx.VERTICAL)
        query_label = wx.StaticText(self, label=tr("Search query"))
        self.query = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.query.SetName(tr("Search query"))
        tag_label = wx.StaticText(self, label=tr("Genre"))
        self.tag = wx.ComboBox(
            self,
            choices=[tr("None"), *LASTFM_TAG_CHOICES],
            style=wx.CB_DROPDOWN | wx.TE_PROCESS_ENTER,
        )
        self.tag.SetValue(tr("None"))
        self.tag.SetName(tr("Genre"))
        self.categories = wx.RadioBox(
            self,
            label=tr("Search for"),
            choices=[tr(label) for label in SEARCH_LABELS],
            majorDimension=1,
            style=wx.RA_SPECIFY_ROWS,
        )
        self.search_button = wx.Button(self, label=tr("&Search"))
        self.heading = wx.StaticText(self, label=tr("Search results"))
        self.album_artwork_button = wx.Button(
            self,
            label=tr("Display album &artwork..."),
        )
        self.album_artwork_button.Hide()
        self.results = ItemList(self)
        self.results.SetName(tr("Search results"))
        self.status = wx.StaticText(self, label=msg.ENTER_SEARCH_QUERY)

        outer.Add(query_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        outer.Add(self.query, 0, wx.EXPAND | wx.ALL, 10)
        outer.Add(tag_label, 0, wx.LEFT | wx.RIGHT, 10)
        outer.Add(self.tag, 0, wx.EXPAND | wx.ALL, 10)
        outer.Add(self.categories, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        outer.Add(self.search_button, 0, wx.ALL, 10)
        outer.Add(self.heading, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        outer.Add(
            self.album_artwork_button,
            0,
            wx.LEFT | wx.RIGHT | wx.TOP,
            10,
        )
        outer.Add(self.results, 1, wx.EXPAND | wx.ALL, 10)
        outer.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(outer)

        self.query.Bind(wx.EVT_TEXT_ENTER, self.on_search)
        self.tag.Bind(wx.EVT_TEXT_ENTER, self.on_search)
        self.categories.Bind(wx.EVT_KEY_DOWN, self.on_category_key)
        self.search_button.Bind(wx.EVT_BUTTON, self.on_search)
        self.album_artwork_button.Bind(
            wx.EVT_BUTTON,
            self.on_display_album_artwork,
        )
        self.results.Bind(self.results.ACTIVATED_EVENT, self.on_open)
        self.results.Bind(wx.EVT_KEY_DOWN, self.on_list_key)
        self.results.Bind(wx.EVT_CONTEXT_MENU, self.on_context_menu)
        self.results.Bind(wx.EVT_NAVIGATION_KEY, self.on_navigation)

    def focus_query(self) -> None:
        self.query.SetFocus()
        self.query.SelectAll()

    def on_category_key(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            logger.debug("Search submitted from category radio group")
            self.on_search()
        else:
            event.Skip()

    def on_search(self, event: wx.Event | None = None) -> None:
        query = self.query.GetValue().strip()
        tag = self.tag.GetValue().strip()
        if tag.casefold() in {"none", tr("None").casefold()}:
            tag = ""
        if not query and not tag:
            self.frame.say(msg.ENTER_SEARCH_QUERY)
            self.query.SetFocus()
            return
        category = SEARCH_TYPES[self.categories.GetSelection()]
        if tag:
            if category not in {"track", "album", "artist"}:
                self.frame.say(
                    tr(
                        "Last.fm genre and tag browsing is available for "
                        "Songs, Albums, and Artists."
                    )
                )
                self.categories.SetFocus()
                return
            self.frame.run_task(
                msg.finding_tag_results(tag, category),
                lambda: self.frame.lastfm_tag_results(
                    tag,
                    category,
                    query=query,
                ),
                lambda items: self.show_tag_search(query, tag, category, items),
            )
            return
        self.frame.run_task(
            msg.SEARCHING_SPOTIFY,
            lambda: self.frame.spotify.search(query, category),
            lambda items: self.show_search(query, category, items),
        )

    def show_search(
        self,
        query: str,
        category: str,
        items: list[SpotifyItem],
    ) -> None:
        state = ViewState(
            tr("Results for {query}").format(query=query),
            items,
            query=query,
            category=category,
        )
        self.history.reset(state)
        self.render(state, focus=True)
        result_count = sum(
            item.kind != ItemKind.HEADING for item in items
        )
        self.status.SetLabel(msg.result_count(result_count, query))
        if not result_count:
            self.frame.say(msg.result_count(result_count, query))
            self.query.SetFocus()

    def show_tag_search(
        self,
        query: str,
        tag: str,
        category: str,
        items: list[SpotifyItem],
    ) -> None:
        state = ViewState(
            tr("Last.fm tag: {tag}").format(tag=tag),
            items,
            query=query,
            category=category,
            tag=tag,
        )
        self.history.reset(state)
        self.render(state, focus=True)
        count = sum(item.kind != ItemKind.HEADING for item in items)
        self.status.SetLabel(
            ntr(
                "{count} Spotify match from Last.fm tag {tag}.",
                "{count} Spotify matches from Last.fm tag {tag}.",
                count,
            ).format(count=count, tag=tag)
        )
        if not count:
            self.frame.say(tr(
                "No Spotify matches found for Last.fm tag {tag}."
            ).format(tag=tag))

    def on_open(self, event: wx.Event | None = None) -> None:
        item = self.results.selected_item()
        if not item:
            return
        if item.raw.get("load_more_episodes"):
            self.load_more_episodes(item)
            return
        if item.raw.get("lastfm_load_more"):
            self.frame.load_more_lastfm_mix(item)
            return
        if item.raw.get("lastfm_tag_load_more"):
            self.load_more_tag_results(item)
            return
        if item.raw.get("load_more"):
            self.load_more(item)
            return
        if item.kind == ItemKind.HEADING:
            return
        logger.info(
            "Opening search result kind=%s id=%s name=%r",
            item.kind,
            item.id,
            item.name,
        )
        self.history.remember_selection(self.results.GetSelection())
        if item.playable:
            self.frame.play_playable_item(item)
        elif item.container:
            self.frame.run_task(
                msg.opening(item.name),
                lambda: self.frame.spotify.children(item),
                lambda items: self.open_children(item, items),
            )
    def load_more(self, item: SpotifyItem) -> None:
        state = self.history.current
        offset = int(item.raw.get("next_offset") or 0)
        self.frame.run_task(
            msg.LOADING_MORE_RESULTS,
            lambda: self.frame.spotify.search(
                state.query,
                state.category,
                offset,
            ),
            lambda items: (
                self.append_search_results(items)
                if self.history.current is state
                else None
            ),
        )

    def load_more_tag_results(self, marker: SpotifyItem) -> None:
        state = self.history.current
        page = int(marker.raw.get("page") or 1)
        self.frame.run_task(
            tr("Loading more Last.fm tag results"),
            lambda: self.frame.lastfm_tag_results(
                state.tag,
                state.category,
                query=state.query,
                page=page,
            ),
            lambda items: self.append_tag_results(state, items),
        )

    def append_tag_results(
        self,
        state: ViewState,
        items: list[SpotifyItem],
    ) -> None:
        if self.history.current is not state:
            return
        existing = [
            item
            for item in state.items
            if not item.raw.get("lastfm_tag_load_more")
        ]
        seen = {item.id for item in existing}
        additions = [
            item
            for item in items
            if item.raw.get("lastfm_tag_load_more") or item.id not in seen
        ]
        added = sum(item.kind != ItemKind.HEADING for item in additions)
        state.items[:] = existing + additions
        state.selected = len(existing) if added else max(0, len(existing) - 1)
        self.render(state, focus=True)
        self.status.SetLabel(
            ntr(
                "{count} Spotify match from Last.fm tag {tag}.",
                "{count} Spotify matches from Last.fm tag {tag}.",
                sum(item.kind != ItemKind.HEADING for item in state.items),
            ).format(
                count=sum(
                    item.kind != ItemKind.HEADING for item in state.items
                ),
                tag=state.tag,
            )
        )
        self.frame.say(
            ntr(
                "Loaded {added} additional result.",
                "Loaded {added} additional results.",
                added,
            ).format(added=added)
            if added
            else msg.NO_MORE_RESULTS
        )

    def append_search_results(self, items: list[SpotifyItem]) -> None:
        state = self.history.current
        existing = [
            item for item in state.items if not item.raw.get("load_more")
        ]
        existing_ids = {
            item.id
            for item in existing
            if item.kind != ItemKind.HEADING
        }
        new_results = [
            item
            for item in items
            if item.kind == ItemKind.HEADING or item.id not in existing_ids
        ]
        result_count = sum(
            item.kind != ItemKind.HEADING for item in new_results
        )
        first_new = len(existing)
        state.items[:] = existing + new_results
        state.selected = first_new if result_count else max(0, first_new - 1)
        self.render(state, focus=True)
        if result_count:
            self.frame.say(
                ntr(
                    "Loaded {count} additional result.",
                    "Loaded {count} additional results.",
                    result_count,
                ).format(count=result_count)
            )
        else:
            self.frame.say(msg.NO_MORE_RESULTS)

    def load_more_episodes(self, item: SpotifyItem) -> None:
        state = self.history.current
        show = state.parent_item
        if not show or show.kind != ItemKind.SHOW:
            return
        offset = int(item.raw.get("next_offset") or 0)
        self.frame.run_task(
            msg.LOADING_MORE_RESULTS,
            lambda: self.frame.spotify.podcast_episodes(show, offset),
            lambda episodes: (
                self.append_episodes(episodes)
                if self.history.current is state
                else None
            ),
        )

    def append_episodes(self, episodes: list[SpotifyItem]) -> None:
        state = self.history.current
        existing = [
            item
            for item in state.items
            if not item.raw.get("load_more_episodes")
        ]
        existing_ids = {item.id for item in existing}
        new_episodes = [
            item
            for item in episodes
            if item.raw.get("load_more_episodes") or item.id not in existing_ids
        ]
        added = sum(item.kind == ItemKind.EPISODE for item in new_episodes)
        first_new = len(existing)
        state.items[:] = existing + new_episodes
        state.selected = first_new if added else max(0, first_new - 1)
        self.render(state, focus=True)
        self.frame.say(
            ntr(
                "Loaded {added} additional episode.",
                "Loaded {added} additional episodes.",
                added,
            ).format(added=added)
            if added
            else msg.NO_MORE_RESULTS
        )

    def open_children(self, parent: SpotifyItem, items: list[SpotifyItem]) -> None:
        logger.info("Displaying %d children for %r", len(items), parent.name)
        parent_artists = parent.raw.get("artists") or []
        parent_artist_names = tuple(
            artist.get("name", "")
            for artist in parent_artists
            if artist.get("name")
        )
        parent_artist_ids = tuple(
            artist.get("id", "")
            for artist in parent_artists
            if artist.get("id")
        )
        if not parent_artist_names and parent.artist:
            parent_artist_names = (parent.artist,)
        self.history.push(
            ViewState(
                parent.name,
                items,
                parent_id=parent.id,
                parent_kind=parent.kind,
                parent_item=parent,
                parent_artist_names=parent_artist_names,
                parent_artist_ids=parent_artist_ids,
            )
        )
        self.render(self.history.current, focus=True)
        if not items:
            self.frame.say(msg.named_item_count(parent.name, 0))

    def go_back(self) -> bool:
        return_from_album = getattr(
            self.frame,
            "return_from_open_album",
            None,
        )
        if return_from_album and return_from_album(self.history.current):
            return True
        if not self.history.can_go_back:
            return False
        state = self.history.back()
        self.render(state, focus=True)
        return True

    def render(self, state: ViewState, *, focus: bool) -> None:
        self.heading.SetLabel(state.title)
        self.frame.update_title_for_page(self, state.title)
        self.album_artwork_button.Show(
            state.parent_kind == ItemKind.ALBUM
            and state.parent_item is not None
        )
        self.Layout()
        if state.parent_kind == ItemKind.ALBUM:
            multi_disc = any(
                int(item.raw.get("disc_number") or 1) > 1
                for item in state.items
            )
            labels = [
                album_track_label(item, index, state, multi_disc)
                for index, item in enumerate(state.items)
            ]
            self.results.set_items(
                state.items,
                state.selected,
                labels=labels,
            )
        else:
            self.results.set_items(state.items, state.selected)
        if focus:
            if state.items:
                self.results.SetFocus()
            elif self.album_artwork_button.IsShown():
                self.album_artwork_button.SetFocus()

    def on_display_album_artwork(
        self,
        event: wx.Event | None = None,
    ) -> None:
        album = self.history.current.parent_item
        if album and album.kind == ItemKind.ALBUM:
            self.frame.show_album_artwork(album)

    def refresh(self) -> None:
        if self.history.can_go_back:
            return
        if self.history.current.query or self.history.current.tag:
            self.query.SetValue(self.history.current.query)
            self.categories.SetSelection(
                SEARCH_TYPES.index(self.history.current.category)
            )
            self.tag.SetValue(self.history.current.tag or tr("None"))
            self.on_search()

    def on_list_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if key == wx.WXK_TAB and not event.ShiftDown():
            self.frame.focus_tab_bar()
        elif (
            key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
            and physical_control_down(event)
        ):
            self.frame.open_selected_track_album(
                self.results.selected_item()
            )
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.on_open()
        elif key == wx.WXK_BACK:
            if not self.go_back():
                self.focus_query()
        elif physical_control_down(event) and key in (ord("Q"), ord("q")):
            self.frame.queue_from_list(self.results)
        elif physical_control_down(event) and key in (ord("L"), ord("l")):
            self.frame.toggle_like_item(self.results.selected_item())
        elif (
            (key == wx.WXK_F10 and event.ShiftDown())
            or key in (wx.WXK_MENU, wx.WXK_WINDOWS_MENU)
        ):
            self.on_context_menu()
        else:
            event.Skip()

    def on_context_menu(self, event: wx.Event | None = None) -> None:
        item = self.results.selected_item()
        if not item or item.kind == ItemKind.HEADING:
            return
        artist = SearchPanel.artist_for_album_view(self, item)
        artist_actions = []
        if artist:
            artist_id, artist_name = artist
            artist_actions.append(
                (
                    tr(
                        "Show albums by &{artist_name}"
                    ).format(artist_name=artist_name),
                    lambda: self.open_artist_albums(artist_id, artist_name),
                )
            )
        source_album = (
            self.history.current.parent_item
            if self.history.current.parent_kind == ItemKind.ALBUM
            else None
        )
        if source_album:
            artist_actions.append(
                (
                    tr("&Related albums..."),
                    lambda: self.frame.show_related_albums(source_album),
                )
            )
        self.frame.popup_item_menu(
            self.results,
            item,
            open_callback=self.on_open if item.container else None,
            include_album_action=(
                self.history.current.parent_kind != ItemKind.ALBUM
            ),
            top_level_actions=artist_actions,
        )

    def artist_for_album_view(
        self, item: SpotifyItem
    ) -> tuple[str, str] | None:
        state = self.history.current
        if state.parent_kind == ItemKind.ALBUM:
            if state.parent_artist_ids and state.parent_artist_names:
                return state.parent_artist_ids[0], state.parent_artist_names[0]
            return None
        if item.kind not in (ItemKind.ALBUM, ItemKind.TRACK):
            return None
        artists = item.raw.get("artists") or []
        if not artists:
            return None
        artist_id = str(artists[0].get("id") or "")
        artist_name = str(artists[0].get("name") or "")
        if not artist_id or not artist_name:
            return None
        return artist_id, artist_name

    def open_artist_albums(self, artist_id: str, artist_name: str) -> None:
        artist = SpotifyItem(artist_id, ItemKind.ARTIST, artist_name)
        self.history.remember_selection(self.results.GetSelection())
        self.frame.run_task(
            msg.opening(artist_name),
            lambda: self.frame.spotify.children(artist),
            lambda albums: self.open_children(artist, albums),
        )

    def on_navigation(self, event: wx.NavigationKeyEvent) -> None:
        if event.IsFromTab() and event.GetDirection():
            logger.debug("Forward navigation from search results to main tab bar")
            self.frame.focus_tab_bar()
        else:
            event.Skip()


class CollectionPanel(wx.Panel):
    def __init__(
        self,
        parent: wx.Window,
        frame: "MainFrame",
        title: str,
        loader: Callable[[], list[SpotifyItem]],
        *,
        removable: bool = False,
        silent_load: bool = False,
        load_on_first_focus: bool = False,
    ) -> None:
        super().__init__(parent)
        self.frame = frame
        self.hosted_in: wx.Window | None = None
        self.title = title
        self.loader = loader
        self.removable = removable
        self.silent_load = silent_load
        self.load_on_first_focus = load_on_first_focus
        self.loaded_once = False
        self.loading = False
        self.all_items: list[SpotifyItem] = []
        self.sort_key = "original"
        self.sort_descending = False
        outer = wx.BoxSizer(wx.VERTICAL)
        self.heading = wx.StaticText(self, label=title)
        self.items = ItemList(self)
        self.items.SetName(title)
        self.status = wx.StaticText(self, label=msg.load_hint(title))
        self.filter = wx.TextCtrl(self)
        self.filter.SetName(tr("Filter"))
        set_windows_accessible(
            self.filter,
            _NamedControlAccessible,
            tr("Filter"),
        )
        outer.Add(self.heading, 0, wx.ALL, 10)
        outer.Add(self.items, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        outer.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        outer.Add(
            wx.StaticText(self, label=tr("Filter this list")),
            0,
            wx.LEFT | wx.RIGHT,
            10,
        )
        outer.Add(self.filter, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizer(outer)
        self.items.Bind(self.items.ACTIVATED_EVENT, self.on_open)
        self.items.Bind(wx.EVT_KEY_DOWN, self.on_key)
        self.items.Bind(wx.EVT_CONTEXT_MENU, self.on_context_menu)
        self.items.Bind(wx.EVT_NAVIGATION_KEY, self.on_navigation)
        self.items.Bind(wx.EVT_SET_FOCUS, self.on_list_focus)
        self.filter.Bind(wx.EVT_TEXT, self.on_filter)

    def refresh(self) -> None:
        if self.loading:
            return
        self.loading = True
        self.frame.run_task(
            None if self.silent_load else msg.loading(self.title),
            self.loader,
            self.show_items,
            failure=self.finish_load_error,
        )

    def show_items(self, items: list[SpotifyItem]) -> None:
        self.loading = False
        self.loaded_once = True
        self.frame.update_title_for_page(self, self.title)
        self.all_items = list(items)
        if hasattr(self, "filter"):
            CollectionPanel.apply_filter(self)
        else:
            self.items.set_items(items)
            self.status.SetLabel(msg.item_count(len(items)))

    def on_filter(self, event: wx.CommandEvent | None = None) -> None:
        self.apply_filter()

    def apply_filter(self, *, preferred: SpotifyItem | None = None) -> None:
        if preferred is None:
            preferred = self.items.selected_item()
        matches = filter_spotify_items(self.all_items, self.filter.GetValue())
        matches = sort_spotify_items(
            matches,
            self.sort_key,
            self.sort_descending,
        )
        selected = 0
        if preferred in matches:
            selected = matches.index(preferred)
        self.items.set_items(matches, selected)
        if self.filter.GetValue().strip():
            status = msg.matching_items(len(matches), len(self.all_items))
        else:
            status = msg.item_count(len(self.all_items))
        if self.sort_key != "original":
            direction = (
                tr("descending")
                if self.sort_descending
                else tr("ascending")
            )
            status += tr(
                " Sorted by {sort_label} {direction}."
            ).format(
                sort_label=tr(SORT_LABELS[self.sort_key]),
                direction=direction,
            )
        self.status.SetLabel(status)

    def sort_options(self) -> set[str]:
        return available_sort_keys(self.all_items)

    def current_sort(self) -> tuple[str, bool]:
        return self.sort_key, self.sort_descending

    def set_sort(self, sort_key: str) -> None:
        if sort_key not in self.sort_options():
            return
        self.sort_key = sort_key
        if sort_key == "original":
            self.sort_descending = False
        self.apply_filter()
        self.items.SetFocus()

    def set_sort_descending(self, descending: bool) -> None:
        if self.sort_key == "original":
            return
        self.sort_descending = descending
        self.apply_filter()
        self.items.SetFocus()

    def on_list_focus(self, event: wx.FocusEvent) -> None:
        event.Skip()
        if self.load_on_first_focus and not self.loaded_once and not self.loading:
            wx.CallAfter(self.refresh)

    def finish_load_error(self) -> None:
        self.loading = False

    def on_open(self, event: wx.Event | None = None) -> None:
        item = self.items.selected_item()
        if item:
            self.frame.play_playable_item(item)

    def on_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if key == wx.WXK_TAB and self.hosted_in:
            event.Skip()
        elif key == wx.WXK_TAB and not event.ShiftDown():
            self.frame.focus_tab_bar()
        elif (
            key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
            and physical_control_down(event)
        ):
            self.frame.open_selected_track_album(
                self.items.selected_item()
            )
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.on_open()
        elif key == wx.WXK_DELETE and self.removable:
            self.remove_selected()
        elif physical_control_down(event) and key in (ord("Q"), ord("q")):
            self.frame.queue_from_list(self.items)
        elif physical_control_down(event) and key in (ord("L"), ord("l")):
            self.frame.toggle_like_item(self.items.selected_item())
        elif key == wx.WXK_F10 and event.ShiftDown():
            self.on_context_menu()
        else:
            event.Skip()

    def on_context_menu(self, event: wx.Event | None = None) -> None:
        item = self.items.selected_item()
        if not item:
            return
        self.frame.popup_item_menu(
            self.items,
            item,
            open_callback=self.on_open if item.container else None,
            remove_callback=self.remove_selected if self.removable else None,
        )

    def remove_selected(self) -> None:
        index = self.items.GetSelection()
        item = self.items.selected_item()
        if not item:
            return
        self.frame.run_task(
            None,
            lambda: self.frame.spotify.remove(item),
            lambda result: self.finish_remove(index),
        )

    def finish_remove(self, index: int) -> None:
        item = self.items.items[index] if 0 <= index < len(self.items.items) else None
        if item in self.all_items:
            self.all_items.remove(item)
        self.apply_filter()
        self.items.SetFocus()

    def on_navigation(self, event: wx.NavigationKeyEvent) -> None:
        if self.hosted_in:
            event.Skip()
        elif event.IsFromTab() and event.GetDirection():
            logger.debug(
                "Forward navigation from %s list to main tab bar",
                self.title,
            )
            self.frame.focus_tab_bar()
        else:
            event.Skip()


class RecentlyPlayedPanel(CollectionPanel):
    """A chronological history, never a title/artist-sorted collection."""

    def show_items(self, items: list[SpotifyItem]) -> None:
        self.sort_key = "original"
        self.sort_descending = False
        super().show_items(items)
        # New plays arrive at the top.  Keeping the previous selection would
        # leave them above the reader, so a refresh starts at the newest.
        if getattr(self, "all_items", None):
            CollectionPanel.apply_filter(self, preferred=self.all_items[0])

    def sort_options(self) -> set[str]:
        return {"original"}


class SavedAlbumsPanel(CollectionPanel):
    def __init__(self, parent: wx.Window, frame: "MainFrame") -> None:
        super().__init__(
            parent,
            frame,
            tr("Saved Albums"),
            frame.spotify.saved_albums,
            removable=True,
            silent_load=True,
            load_on_first_focus=True,
        )

    def on_open(self, event: wx.Event | None = None) -> None:
        album = self.items.selected_item()
        if not album:
            return
        self.frame.run_task(
            msg.opening(album.name),
            lambda: self.frame.spotify.children(album),
            lambda tracks: self.frame.finish_open_album(album, tracks),
        )


NEW_MUSIC_LANGUAGE_SUFFIXES = {
    "bengali",
    "gujarati",
    "hindi",
    "kannada",
    "malayalam",
    "marathi",
    "odia",
    "punjabi",
    "tamil",
    "telugu",
    "urdu",
}


def normalized_new_album_name(name: str) -> str:
    normalized = " ".join(name.split()).casefold()
    suffix = re.search(r"\(([^()]*)\)\s*$", normalized)
    if suffix and suffix.group(1).strip() in NEW_MUSIC_LANGUAGE_SUFFIXES:
        normalized = normalized[: suffix.start()].rstrip()
    return normalized


def new_album_identity(album: SpotifyItem) -> tuple[str, str, int | None]:
    """Identify equivalent releases even when Spotify gives them different IDs."""
    primary_artist = album.artist.split(",", 1)[0]
    return (
        normalized_new_album_name(album.name),
        " ".join(primary_artist.split()).casefold(),
        album.total,
    )


DISCOVER_SOURCES = (
    "releases",
    "followed",
    "charts",
    "historical",
)
# How far back the start-up check looks for releases by followed artists.
FOLLOWED_CHECK_DAYS = 30
# Apple's feed allows up to 100 entries. Rows are built from Apple's own data
# and only looked up on Spotify when someone acts on them, because every lookup
# is a separate Spotify search and a burst of them earns an hours-long penalty.
CHART_SIZE = 100


def parse_chart_date(value: str) -> date:
    """Accept an ISO date with or without separators."""
    text = value.strip()
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return date.fromisoformat(text)


class ChartResults(NamedTuple):
    """A chart as Apple published it, before any Spotify lookup."""

    items: list[SpotifyItem]
    country: str = ""
    loaded_at: float = 0.0
    media_type: str = "songs"
    chart_date: str = ""
    detail: str = ""


FIELDS_FROM_SPOTIFY = (
    "id", "kind", "name", "artist", "album", "duration_ms", "explicit",
    "year", "total", "uri",
)


def apply_resolved_row(row: SpotifyItem, real: SpotifyItem) -> None:
    """Fill a chart row with its Spotify track, keeping the same row object.

    Keeping the object means the list, its selection and any marks stay valid,
    and nothing has to be redrawn or re-announced.
    """
    for name in FIELDS_FROM_SPOTIFY:
        setattr(row, name, getattr(real, name))
    kept = {
        key: row.raw[key]
        for key in (
            "list_note", "chart_url", "artist_first", "classical_chart_album",
            "classical_source_work", "classical_source_composer",
            "classical_vocal",
        )
        if key in row.raw
    }
    row.raw = {**real.raw, **kept}


def cover_summary(source: SpotifyItem, result: CoverResults) -> str:
    """Describe a covers list, including what it left out and why."""
    artists = len({cover.artist for cover in result.covers})
    versions = ntr(
        "{count} version", "{count} versions", len(result.covers)
    ).format(count=len(result.covers))
    artist_count = ntr(
        "{count} artist", "{count} artists", artists
    ).format(count=artists)
    parts = [
        tr(
            "{versions} by {artists}, from MusicBrainz."
        ).format(versions=versions, artists=artist_count),
        tr(
            "Live and karaoke recordings and recordings by {value} are left "
            "out."
        ).format(
            value=source.artist.split(',', 1)[0].strip()
            or tr("the original artist"),
        ),
    ]
    if result.examined < result.total_recordings:
        parts.append(
            tr(
                "Checked the first {examined} of {total_recordings} "
                "recordings."
            ).format(
                examined=result.examined,
                total_recordings=result.total_recordings,
            )
        )
    parts.append(
        tr(
            "Songs are looked up on Spotify only when you play, queue or "
            "save them, so some may be unavailable."
        )
    )
    return " ".join(parts)


def chart_provenance(result: ChartResults) -> str:
    """Say where a chart came from and what it can and cannot tell you."""
    if result.media_type == "historical_us":
        return tr(
                "Experimental US Billboard Hot 100 for {chart_date}, read "
                "live from the community archive at {PROJECT_URL}. This is "
                "an unofficial external dataset and may change or "
                "disappear. Songs are looked up on Spotify only when you "
                "act on them."
            ).format(chart_date=result.chart_date, PROJECT_URL=PROJECT_URL)
    if result.media_type == "number_ones":
        return tr(
            "{detail}. From Wikipedia's lists of number ones (licensed "
            "CC BY-SA), compiled from each country's official charts. Only "
            "number ones are listed. Songs are looked up on Spotify only "
            "when you play, queue or save them."
        ).format(detail=result.detail)
    if result.media_type == "triple_j":
        return tr(
            "Triple J Hottest 100 {countdown}, read live from the official "
            "ABC archive. This is an annual listener poll, not an Australian "
            "sales chart. Songs are looked up on Spotify only when you play, "
            "queue or save them."
        ).format(countdown=result.detail)
    if result.media_type == "classic_100":
        return tr(
            "ABC Classic 100 {countdown}, from ABC Classic's official "
            "listener-poll archive. A representative Spotify recording is "
            "looked up only when you act on a work; large works may resolve "
            "to one movement or excerpt."
        ).format(countdown=result.detail)
    if result.media_type == "rn_books":
        return tr(
            "ABC Radio National {countdown}, from ABC's official "
            "listener-voted book countdown. Audiobooks are looked up on "
            "Spotify only when you act on a book; browsing the list does "
            "not use audiobook listening time. Availability depends on "
            "your Spotify plan and country."
        ).format(countdown=result.detail)
    if result.media_type == "new_releases":
        source = result.detail
        stamp = loaded_label(result.loaded_at)
        if stamp:
            source += tr(", loaded {stamp}").format(stamp=stamp)
        return tr(
            "{source}. Releases are looked up on Spotify only when you "
            "play, queue or save them, so a few may turn out to be "
            "unavailable."
        ).format(source=source)
    source = (
        tr(
            "Most played albums on Apple Music in {country_name}"
        ).format(country_name=country_name(result.country))
        if result.media_type == "albums"
        else tr(
            "Most played on Apple Music in {country_name}"
        ).format(country_name=country_name(result.country))
    )
    stamp = loaded_label(result.loaded_at)
    if stamp:
        source += tr(", loaded {stamp}").format(stamp=stamp)
    if result.media_type == "albums":
        return tr(
            "{source}. Apple publishes rank only, with no play counts, "
            "reporting period or measurement time. Albums are looked up on "
            "Spotify only when you play, queue or save them, so a few may "
            "turn out to be unavailable."
        ).format(source=source)
    return tr(
        "{source}. Apple publishes rank only, with no play counts, "
        "reporting period or measurement time. Songs are looked up on "
        "Spotify only when you play, queue or save them, so a few may "
        "turn out to be unavailable."
    ).format(source=source)


class NewMusicPanel(CollectionPanel):
    def __init__(self, parent: wx.Window, frame: "MainFrame") -> None:
        super().__init__(
            parent,
            frame,
            tr("Discover"),
            list,
            silent_load=True,
        )
        self.result_mode = "releases"
        self.chart_note = ""
        self.country_touched = False
        self.country_resolved = False
        self.discovery_source = wx.RadioBox(
            self,
            label=tr("Discover"),
            choices=[
                tr("New releases"),
                tr("Followed artists and authors"),
                tr("Apple Music most played"),
                tr("Charts and countdowns"),
            ],
            majorDimension=1,
            style=wx.RA_SPECIFY_ROWS,
        )
        self.release_types = wx.RadioBox(
            self,
            label=tr("Show"),
            choices=[tr("Songs"), tr("Albums")],
            majorDimension=1,
            style=wx.RA_SPECIFY_ROWS,
        )
        self.genre_label = wx.StaticText(self, label=tr("Genre"))
        self.genre = wx.Choice(
            self,
            choices=[tr(name) for _code, name in GENRES],
        )
        self.genre.SetSelection(0)
        self.genre.SetName(tr("Genre"))
        self.release_window_label = wx.StaticText(
            self,
            label=tr("Released within"),
        )
        self.release_window = wx.Choice(
            self,
            choices=[tr(name) for _days, name in RELEASE_WINDOWS],
        )
        self.release_window.SetSelection(
            next(
                index
                for index, (days, _name) in enumerate(RELEASE_WINDOWS)
                if days == DEFAULT_RELEASE_WINDOW
            )
        )
        self.release_window.SetName(tr("Released within"))
        self.keyword_label = wx.StaticText(
            self,
            label=tr("Artist or title (optional)"),
        )
        self.keyword = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.keyword.SetName(tr("Artist or title, optional"))
        self.keyword.Bind(wx.EVT_TEXT_ENTER, self.on_search)
        self.chart_country = wx.Choice(
            self,
            choices=[tr(name) for _code, name in CHART_COUNTRIES],
        )
        self.chart_country.SetSelection(
            next(
                index
                for index, (code, _name) in enumerate(CHART_COUNTRIES)
                if code == DEFAULT_CHART_COUNTRY
            )
        )
        self.chart_country.SetName(tr("Chart country"))
        self.history_chart_label = wx.StaticText(self, label=tr("Chart"))
        self.triple_j_countdown_label = wx.StaticText(
            self, label=tr("Countdown")
        )
        self.triple_j_countdown = wx.Choice(
            self,
            choices=[tr("Choose a year or special countdown")]
            + [tr(value.label) for value in TRIPLE_J_COUNTDOWNS],
        )
        self.triple_j_countdown.SetSelection(0)
        self.triple_j_countdown.SetName(
            tr("Triple J Hottest 100 year or special countdown")
        )
        self.classic_100_countdown_label = wx.StaticText(
            self, label=tr("Classic 100 countdown")
        )
        self.classic_100_countdown = wx.Choice(
            self,
            choices=[tr("Choose a Classic 100 countdown")]
            + [tr(value.label) for value in CLASSIC_100_COUNTDOWNS],
        )
        self.classic_100_countdown.SetSelection(0)
        self.classic_100_countdown.SetName(tr("ABC Classic 100 countdown"))
        self.rn_books_countdown_label = wx.StaticText(
            self, label=tr("Radio National book countdown")
        )
        self.rn_books_countdown = wx.Choice(
            self,
            choices=[tr("Choose a Radio National book countdown")]
            + [tr(value.label) for value in RN_BOOK_COUNTDOWNS],
        )
        self.rn_books_countdown.SetSelection(0)
        self.rn_books_countdown.SetName(tr("ABC Radio National book countdown"))
        self.history_chart = wx.Choice(
            self,
            choices=[
                tr("US Billboard Hot 100 (experimental)"),
                tr("Number ones by country"),
                tr("Triple J Hottest 100"),
                tr("ABC Classic 100"),
                tr("ABC Radio National Top Books"),
            ],
        )
        self.history_chart.SetSelection(0)
        self.history_chart.SetName(tr("Historical chart"))
        self.number_ones_country_label = wx.StaticText(
            self, label=tr("Number ones country")
        )
        self.number_ones_country = wx.Choice(
            self,
            choices=[country_name(code) for code in NUMBER_ONE_COUNTRIES],
        )
        self.number_ones_country.SetSelection(0)
        self.number_ones_country.SetName(tr("Number ones country"))
        self.number_ones_order_label = wx.StaticText(self, label=tr("Order"))
        self.number_ones_order = wx.Choice(
            self,
            choices=[tr("By date"), tr("Most weeks at number one")],
        )
        self.number_ones_order.SetSelection(1)
        self.number_ones_order.SetName(tr("Order of number ones"))
        self.chart_date_label = wx.StaticText(
            self,
            label=tr("Historical chart date (YYYY-MM-DD)"),
        )
        self.chart_date = wx.TextCtrl(
            self,
            value=date.today().isoformat(),
            style=wx.TE_PROCESS_ENTER,
        )
        self.chart_date.SetName(tr("Chart date, year-month-day"))
        self.chart_date.Bind(wx.EVT_TEXT_ENTER, self.on_search)
        self.search_button = wx.Button(self, label=tr("&Search"))
        sizer = self.GetSizer()
        sizer.Insert(1, self.discovery_source, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        # Reading and Tab order follow the order of choices: the chart is
        # picked first, then Songs or Albums, then the options that follow.
        sizer.Insert(2, self.history_chart_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        sizer.Insert(3, self.history_chart, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Insert(4, self.triple_j_countdown_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        sizer.Insert(5, self.triple_j_countdown, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Insert(6, self.classic_100_countdown_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        sizer.Insert(7, self.classic_100_countdown, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Insert(8, self.rn_books_countdown_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        sizer.Insert(9, self.rn_books_countdown, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Insert(10, self.number_ones_country_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        sizer.Insert(11, self.number_ones_country, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Insert(12, self.release_types, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Insert(13, self.number_ones_order_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        sizer.Insert(14, self.number_ones_order, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Insert(15, self.genre_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        sizer.Insert(16, self.genre, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Insert(17, self.release_window_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        sizer.Insert(18, self.release_window, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Insert(19, self.keyword_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        sizer.Insert(20, self.keyword, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Insert(21, self.chart_country, 0, wx.EXPAND | wx.ALL, 10)
        sizer.Insert(22, self.chart_date_label, 0, wx.LEFT | wx.RIGHT, 10)
        sizer.Insert(23, self.chart_date, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Insert(24, self.search_button, 0, wx.ALL, 10)
        self.history_chart.Bind(wx.EVT_CHOICE, self.on_history_chart_changed)
        self.discovery_source.Bind(wx.EVT_RADIOBOX, self.on_source_changed)
        self.chart_country.Bind(wx.EVT_CHOICE, self.on_country_chosen)
        self.search_button.Bind(wx.EVT_BUTTON, self.on_search)
        self.status.SetLabel(msg.DISCOVER_SEARCH_PROMPT)
        self.update_source_controls()

    def on_source_changed(self, event: wx.Event | None = None) -> None:
        self.update_source_controls()
        if self.source() in {"releases", "followed", "charts"}:
            self.resolve_account_country()

    def on_country_chosen(self, event: wx.Event | None = None) -> None:
        # An explicit choice always wins over the account default.
        self.country_touched = True

    def resolve_account_country(self) -> None:
        """Preselect the chart for the account's own country, once."""
        if self.country_resolved or self.country_touched:
            return
        self.country_resolved = True
        self.frame.run_task(
            None,
            self.frame.spotify.account_country,
            self.apply_account_country,
            failure=self.forget_country_resolution,
        )

    def forget_country_resolution(self) -> None:
        self.country_resolved = False

    def apply_account_country(self, code: str) -> None:
        if self.country_touched or not code:
            return
        index = next(
            (
                position
                for position, (value, _name) in enumerate(CHART_COUNTRIES)
                if value == code.upper()
            ),
            None,
        )
        if index is not None:
            self.chart_country.SetSelection(index)

    def update_source_controls(self) -> None:
        source = self.source()
        releases = source == "releases"
        for control in (self.genre, self.keyword):
            control.Enable(releases)
        historical = source == "historical"
        history_chart = getattr(self, "history_chart", None)
        history_selection = (
            history_chart.GetSelection() if historical and history_chart else -1
        )
        numbers = bool(
            historical and history_selection == 1
        )
        triple_j = historical and history_selection == 2
        classic_100 = historical and history_selection == 3
        rn_books = historical and history_selection == 4
        self.release_types.Enable(source in {"releases", "charts"} or numbers)
        self.release_window.Enable(source in {"releases", "followed"})
        # Followed people use the account storefront automatically. Keeping
        # this shared picker disabled also removes it from keyboard tab order.
        self.chart_country.Enable(source in {"releases", "charts"})
        if history_chart:
            history_chart.Enable(historical)
        triple_j_countdown = getattr(self, "triple_j_countdown", None)
        if triple_j_countdown:
            triple_j_countdown.Enable(triple_j)
        classic_countdown = getattr(self, "classic_100_countdown", None)
        if classic_countdown:
            classic_countdown.Enable(classic_100)
        rn_books_countdown = getattr(self, "rn_books_countdown", None)
        if rn_books_countdown:
            rn_books_countdown.Enable(rn_books)
        for name in ("number_ones_country", "number_ones_order"):
            control = getattr(self, name, None)
            if control:
                control.Enable(numbers)
        chart_date = getattr(self, "chart_date", None)
        if chart_date:
            chart_date.Enable(
                historical and not triple_j and not classic_100 and not rn_books
            )
            label = getattr(self, "chart_date_label", None)
            if label:
                label.SetLabel(
                    tr("Year or date (YYYY or YYYY-MM-DD)")
                    if numbers
                    else tr("Historical chart date (YYYY-MM-DD)")
                )

    def on_history_chart_changed(self, event: wx.Event | None = None) -> None:
        self.update_source_controls()

    def source(self) -> str:
        return DISCOVER_SOURCES[self.discovery_source.GetSelection()]

    def release_media(self) -> str:
        return ("songs", "albums")[self.release_types.GetSelection()]

    def chart_country_code(self) -> str:
        return CHART_COUNTRIES[self.chart_country.GetSelection()][0]

    def on_search(self, event: wx.Event | None = None) -> None:
        if self.loading:
            return
        self.loading = True
        if self.source() == "charts":
            country = self.chart_country_code()
            media_type = self.release_media()
            self.frame.run_task(
                msg.LOADING_MUSIC_CHART,
                lambda: self.frame.chart_results(country, media_type),
                self.show_chart_items,
                failure=self.finish_load_error,
            )
            return
        if (
            self.source() == "historical"
            and self.history_chart.GetSelection() == 4
        ):
            selection = self.rn_books_countdown.GetSelection()
            if selection <= 0:
                self.loading = False
                self.frame.say(
                    tr("Choose an ABC Radio National book countdown.")
                )
                self.rn_books_countdown.SetFocus()
                return
            countdown = RN_BOOK_COUNTDOWNS[selection - 1]
            self.frame.run_task(
                tr("Loading ABC Radio National Top Books"),
                lambda: self.frame.rn_book_results(countdown),
                self.show_chart_items,
                failure=self.finish_load_error,
            )
            return
        if (
            self.source() == "historical"
            and self.history_chart.GetSelection() == 3
        ):
            selection = self.classic_100_countdown.GetSelection()
            if selection <= 0:
                self.loading = False
                self.frame.say(tr("Choose an ABC Classic 100 countdown."))
                self.classic_100_countdown.SetFocus()
                return
            countdown = CLASSIC_100_COUNTDOWNS[selection - 1]
            self.frame.run_task(
                tr("Loading ABC Classic 100"),
                lambda: self.frame.classic_100_results(countdown),
                self.show_chart_items,
                failure=self.finish_load_error,
            )
            return
        if (
            self.source() == "historical"
            and self.history_chart.GetSelection() == 2
        ):
            selection = self.triple_j_countdown.GetSelection()
            if selection <= 0:
                self.loading = False
                self.frame.say(
                    tr("Choose a Triple J Hottest 100 year or special countdown.")
                )
                self.triple_j_countdown.SetFocus()
                return
            countdown = TRIPLE_J_COUNTDOWNS[
                selection - 1
            ]
            self.frame.run_task(
                tr("Loading Triple J Hottest 100"),
                lambda: self.frame.triple_j_results(countdown),
                self.show_chart_items,
                failure=self.finish_load_error,
            )
            return
        if self.source() == "historical" and self.history_chart.GetSelection() == 1:
            self.search_number_ones()
            return
        if self.source() == "historical":
            try:
                requested = parse_chart_date(self.chart_date.GetValue())
            except ValueError:
                self.loading = False
                self.frame.say(tr("Enter the chart date as year-month-day."))
                self.chart_date.SetFocus()
                return
            self.frame.run_task(
                tr("Loading experimental historical chart"),
                lambda: self.frame.historical_chart_results(requested),
                self.show_chart_items,
                failure=self.finish_load_error,
            )
            return
        if self.source() == "followed":
            country = self.chart_country_code()
            days = RELEASE_WINDOWS[self.release_window.GetSelection()][0]
            if not self.frame.followed.artists:
                self.loading = False
                self.frame.say(
                    tr(
                        "You are not following any artists yet. Right-click an "
                        "artist or song and choose Follow for new releases."
                    )
                )
                return
            self.frame.run_task(
                msg.LOADING_NEW_RELEASES,
                lambda: self.frame.followed_release_results(country, days),
                self.show_chart_items,
                failure=self.finish_load_error,
            )
            return
        country = self.chart_country_code()
        media_type = self.release_media()
        genre = GENRES[self.genre.GetSelection()][0]
        days = RELEASE_WINDOWS[self.release_window.GetSelection()][0]
        keyword = self.keyword.GetValue().strip()
        self.frame.run_task(
            msg.LOADING_NEW_RELEASES,
            lambda: self.frame.new_release_results(
                country, media_type, genre, days, keyword
            ),
            self.show_chart_items,
            failure=self.finish_load_error,
        )

    def search_number_ones(self) -> None:
        text = self.chart_date.GetValue().strip()
        year: int | None = None
        day: date | None = None
        if len(text) == 4 and text.isdigit():
            year = int(text)
        else:
            try:
                day = parse_chart_date(text)
            except ValueError:
                self.loading = False
                self.frame.say(
                    tr(
                        "Enter a year, such as 1985, or a date as "
                        "year-month-day."
                    )
                )
                self.chart_date.SetFocus()
                return
        kind = UK_SINGLES if self.release_media() == "songs" else UK_ALBUMS
        by_weeks = self.number_ones_order.GetSelection() == 1
        country = NUMBER_ONE_COUNTRIES[self.number_ones_country.GetSelection()]
        self.frame.run_task(
            tr("Loading number ones"),
            lambda: self.frame.number_ones_results(
                country, kind, year, day, by_weeks
            ),
            self.show_chart_items,
            failure=self.finish_load_error,
        )

    def refresh(self) -> None:
        self.on_search()

    def show_chart_items(self, result: ChartResults) -> None:
        self.loading = False
        self.loaded_once = True
        self.result_mode = "chart"
        self.chart_note = chart_provenance(result)
        self.all_items = list(result.items)
        # A filter from the previously displayed source can otherwise make a
        # freshly loaded chart appear empty even though its rows arrived.
        self.filter.SetValue("")
        self.frame.update_title_for_page(self, self.title)
        self.render_results()
        logger.info(
            "Displayed Discover chart media_type=%s entries=%d rendered=%d",
            result.media_type,
            len(self.all_items),
            len(self.items.items),
        )
        if self.items.items:
            self.items.SetFocus()
        else:
            self.frame.say(tr("No matching releases were found."))

    def apply_filter(self, *, preferred: SpotifyItem | None = None) -> None:
        if preferred is None:
            preferred = self.items.selected_item()
        self.render_results(preferred)

    def render_results(self, preferred: SpotifyItem | None = None) -> None:
        """Draw the filtered and sorted view, keeping the load-more row last."""
        matches = sort_spotify_items(
            filter_spotify_items(self.all_items, self.filter.GetValue()),
            self.sort_key,
            self.sort_descending,
        )
        rendered = matches
        selected = rendered.index(preferred) if preferred in rendered else 0
        self.items.set_items(rendered, selected)
        self.status.SetLabel(self.result_status(len(matches)))

    def result_status(self, shown: int) -> str:
        total = len(self.all_items)
        filtering = bool(self.filter.GetValue().strip())
        if self.result_mode == "chart":
            status = (
                msg.matching_chart_entries(shown, total)
                if filtering
                else msg.chart_entry_count(total)
            )
        else:
            status = (
                msg.matching_items(shown, total)
                if filtering
                else msg.item_count(total)
            )
        if self.result_mode == "chart" and self.chart_note:
            status += f" {self.chart_note}"
        if self.sort_key != "original":
            direction = (
                tr("descending")
                if self.sort_descending
                else tr("ascending")
            )
            status += tr(
                " Sorted by {sort_label} {direction}."
            ).format(
                sort_label=tr(SORT_LABELS[self.sort_key]),
                direction=direction,
            )
        return status

    def on_open(self, event: wx.Event | None = None) -> None:
        item = self.items.selected_item()
        if not item:
            return
        if self.frame.resolve_then([item], lambda: self.on_open()):
            return
        if item.kind == ItemKind.ALBUM and item.raw.get("classical_chart_album"):
            self.frame.current_classical_alternate_source = item
            self.frame.play(item)
            return
        if item.kind == ItemKind.AUDIOBOOK:
            self.frame.open_audiobook(item)
            return
        if item.kind == ItemKind.TRACK or item.raw.get("classical_chart_album"):
            self.frame.play_playable_item(item)
            return
        album = item
        self.frame.run_task(
            msg.opening(album.name),
            lambda: self.frame.spotify.children(album),
            lambda tracks: self.frame.finish_open_album(album, tracks),
        )

class ConcertsPanel(wx.Panel):
    def __init__(self, parent: wx.Window, frame: "MainFrame") -> None:
        super().__init__(parent)
        self.SetName(tr("Concerts"))
        self.frame = frame
        self.hosted_in: wx.Window | None = None
        self.page = 0
        self.loading = False
        self.classifications_loading = False
        self.classifications_loaded = False
        self.categories: list[EventCategory] = []
        outer = wx.BoxSizer(wx.VERTICAL)
        fields = wx.FlexGridSizer(cols=2, hgap=10, vgap=8)
        fields.AddGrowableCol(1, 1)
        self.keyword = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.country = wx.Choice(
            self,
            choices=[
                f"{tr(name)} ({code})" for code, name in TICKETMASTER_COUNTRIES
            ],
        )
        self.country.SetSelection(
            next(
                index
                for index, (code, _name) in enumerate(TICKETMASTER_COUNTRIES)
                if code == "AU"
            )
        )
        self.state = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.city = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.category = wx.ComboBox(
            self,
            choices=[tr("All categories")],
            style=wx.CB_READONLY,
        )
        self.category.SetSelection(0)
        self.genre = wx.ComboBox(
            self,
            choices=[tr("All genres")],
            style=wx.CB_READONLY,
        )
        self.genre.SetSelection(0)
        today = date.today()
        date_offsets = (
            (0, tr("Today")),
            (1, tr("Tomorrow")),
            (7, tr("One week from today")),
            (30, tr("30 days from today")),
            (90, tr("Three months from today")),
            (180, tr("Six months from today")),
            (365, tr("One year from today")),
        )
        self.date_values = [
            (today + timedelta(days=offset)).isoformat()
            for offset, _label in date_offsets
        ]
        date_labels = [
            f"{label}, {(today + timedelta(days=offset)).isoformat()}"
            for offset, label in date_offsets
        ]
        self.start_date = wx.ComboBox(
            self,
            choices=date_labels,
            style=wx.CB_READONLY,
        )
        self.start_date.SetSelection(0)
        self.end_date = wx.ComboBox(
            self,
            choices=[tr("Any future date"), *date_labels],
            style=wx.CB_READONLY,
        )
        self.end_date.SetSelection(0)
        for label, accessible_name, control in (
            (
                tr("&Keyword"),
                tr("Keyword, artist, event, or venue"),
                self.keyword,
            ),
            (tr("&Country"), tr("Country"), self.country),
            (tr("&State code"), tr("State or territory code"), self.state),
            (tr("Cit&y"), tr("City"), self.city),
            (tr("C&ategory"), tr("Event category"), self.category),
            (tr("&Genre"), tr("Event genre"), self.genre),
            (tr("&From"), tr("Concerts from date"), self.start_date),
            (tr("&Until"), tr("Concerts until date"), self.end_date),
        ):
            fields.Add(
                wx.StaticText(self, label=label),
                0,
                wx.ALIGN_CENTER_VERTICAL,
            )
            fields.Add(control, 1, wx.EXPAND)
            control.SetName(accessible_name)
            set_windows_accessible(
                control,
                _NamedControlAccessible,
                accessible_name,
            )
            if isinstance(control, wx.TextCtrl):
                control.Bind(wx.EVT_TEXT_ENTER, self.on_search)
        self.search_button = wx.Button(self, label=tr("&Search concerts"))
        self.search_button.SetName(tr("Search concerts"))
        self.heading = wx.StaticText(self, label=tr("Upcoming concerts"))
        self.heading.SetName(tr("Upcoming concerts"))
        self.items = ItemList(self)
        self.items.SetName(tr("Upcoming concert results"))
        self.status = wx.StaticText(
            self,
            label=(
                tr("Enter search filters, then press Search concerts.")
                if frame.ticketmaster.api_key
                else tr(
                    "Ticketmaster API key required. Add one in Preferences."
                )
            ),
        )
        self.status.SetName(tr("Concert search status"))
        outer.Add(fields, 0, wx.EXPAND | wx.ALL, 10)
        outer.Add(self.search_button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        outer.Add(self.heading, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        outer.Add(self.items, 1, wx.EXPAND | wx.ALL, 10)
        outer.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(outer)
        self.search_button.Bind(wx.EVT_BUTTON, self.on_search)
        self.items.Bind(self.items.ACTIVATED_EVENT, self.on_open)
        self.category.Bind(wx.EVT_COMBOBOX, self.on_category_changed)

    def ensure_classifications(self) -> None:
        if (
            self.classifications_loaded
            or self.classifications_loading
            or not self.frame.ticketmaster.api_key
        ):
            return
        self.classifications_loading = True
        self.frame.run_task(
            tr("Loading Ticketmaster categories"),
            self.frame.ticketmaster.classifications,
            self.show_classifications,
            failure=self.finish_classification_error,
        )

    def finish_classification_error(self) -> None:
        self.classifications_loading = False

    def show_classifications(
        self, categories: list[EventCategory]
    ) -> None:
        self.classifications_loading = False
        self.classifications_loaded = True
        self.categories = categories
        self.category.Clear()
        self.category.Append(tr("All categories"))
        for category in categories:
            self.category.Append(category.name)
        self.category.SetSelection(0)
        self.populate_genres()

    def on_category_changed(self, event: wx.Event | None = None) -> None:
        self.populate_genres()

    def populate_genres(self) -> None:
        self.genre.Clear()
        self.genre.Append(tr("All genres"))
        selected = self.category.GetSelection()
        if selected > 0 and selected <= len(self.categories):
            for _genre_id, genre_name in self.categories[selected - 1].genres:
                self.genre.Append(genre_name)
        self.genre.SetSelection(0)

    def filters(self) -> dict[str, str]:
        return {
            "keyword": self.keyword.GetValue(),
            "country": TICKETMASTER_COUNTRIES[
                self.country.GetSelection()
            ][0],
            "state": self.state.GetValue(),
            "city": self.city.GetValue(),
            "genre": "",
            "category_id": (
                ""
                if self.category.GetSelection() <= 0
                else self.categories[self.category.GetSelection() - 1].id
            ),
            "genre_id": self.selected_genre_id(),
            "start_date": self.date_values[self.start_date.GetSelection()],
            "end_date": (
                ""
                if self.end_date.GetSelection() == 0
                else self.date_values[self.end_date.GetSelection() - 1]
            ),
        }

    def selected_genre_id(self) -> str:
        category_index = self.category.GetSelection() - 1
        genre_index = self.genre.GetSelection() - 1
        if (
            category_index < 0
            or category_index >= len(self.categories)
            or genre_index < 0
            or genre_index >= len(self.categories[category_index].genres)
        ):
            return ""
        return self.categories[category_index].genres[genre_index][0]

    def update_api_key_status(self) -> None:
        if not self.frame.ticketmaster.api_key:
            self.status.SetLabel(
                tr("Ticketmaster API key required. Add one in Preferences.")
            )
        elif not self.items.items:
            self.status.SetLabel(
                tr("Enter search filters, then press Search concerts.")
            )

    def on_search(self, event: wx.Event | None = None) -> None:
        self.ensure_classifications()
        filters = self.filters()
        if (
            filters["end_date"]
            and filters["end_date"] < filters["start_date"]
        ):
            self.frame.say(tr(
                "Until date must not be earlier than From date."
            ))
            self.end_date.SetFocus()
            return
        self.page = 0
        self.search_page(0, append=False)

    def search_page(self, page: int, *, append: bool) -> None:
        if self.loading:
            return
        self.loading = True
        filters = self.filters()
        self.frame.run_task(
            tr("Searching upcoming concerts"),
            lambda: self.frame.ticketmaster.search(**filters, page=page),
            lambda result: self.show_page(result, append=append),
            failure=self.finish_error,
        )

    def finish_error(self) -> None:
        self.loading = False

    def show_page(self, result: ConcertPage, *, append: bool) -> None:
        self.loading = False
        self.page = result.page
        existing = (
            [item for item in self.items.items if item.id != "__load_more__"]
            if append
            else []
        )
        events = existing + result.events
        rendered: list[ConcertEvent] = list(events)
        if result.has_more:
            rendered.append(ConcertEvent("__load_more__", tr(
                "Load more results"
            )))
        selected = len(existing) if append and result.events else 0
        self.items.set_items(rendered, selected=selected)
        self.status.SetLabel(
            ntr(
                "Showing {count} of {total_events} concert.",
                "Showing {count} of {total_events} concerts.",
                result.total_events,
            ).format(count=len(events), total_events=result.total_events)
        )
        self.frame.update_title_for_page(self, tr("Concerts"))
        if rendered:
            self.items.SetFocus()
        else:
            self.frame.say(tr("No upcoming concerts found."))
            self.keyword.SetFocus()

    def on_open(self, event: wx.Event | None = None) -> None:
        item = self.items.selected_item()
        if not item:
            return
        if item.id == "__load_more__":
            self.search_page(self.page + 1, append=True)
        elif item.url:
            webbrowser.open(item.url)

    def refresh(self) -> None:
        self.on_search()

    def on_context_menu(self, event: wx.Event | None = None) -> None:
        self.on_open()


class BookmarksPanel(CollectionPanel):
    def __init__(self, parent: wx.Window, frame: "MainFrame") -> None:
        super().__init__(
            parent,
            frame,
            tr("Bookmarks"),
            frame.load_bookmarks,
            removable=True,
            silent_load=True,
            load_on_first_focus=True,
        )

    def on_open(self, event: wx.Event | None = None) -> None:
        item = self.items.selected_item()
        if item:
            self.frame.resume_bookmark(item)

    def remove_selected(self) -> None:
        index = self.items.GetSelection()
        item = self.items.selected_item()
        if not item:
            return
        self.frame.delete_bookmark(item)
        self.items.remove_at(index)
        self.status.SetLabel(msg.item_count(len(self.items.items)))
        if self.items.items:
            self.items.SetFocus()

    def rename_selected(self) -> None:
        item = self.items.selected_item()
        if not item:
            return
        current_name = str(item.raw.get("bookmark_name") or "")
        dialog = wx.TextEntryDialog(
            self,
            tr(
                "Enter a bookmark name. Leave blank to use the track or "
                "episode title."
            ),
            tr("Rename bookmark"),
            current_name,
        )
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            self.frame.rename_bookmark(item, dialog.GetValue().strip())
        finally:
            dialog.Destroy()
        self.render(self.history.current, focus=True)

    def on_context_menu(self, event: wx.Event | None = None) -> None:
        item = self.items.selected_item()
        if not item:
            return
        menu = wx.Menu()
        actions = [
            (
                menu.Append(wx.ID_ANY, tr("&Resume from bookmark")),
                lambda: self.frame.resume_bookmark(item),
            ),
            (
                menu.Append(wx.ID_ANY, tr("Open &album")),
                lambda: self.frame.open_album_for_track(item),
            ),
            (
                menu.Append(wx.ID_ANY, tr("Add to &queue")),
                lambda: self.frame.queue_selected(item),
            ),
            (
                menu.Append(wx.ID_ANY, tr("&Save to library")),
                lambda: self.frame.like_selected(item),
            ),
            (
                menu.Append(wx.ID_ANY, tr("Re&name bookmark...")),
                self.rename_selected,
            ),
        ]
        menu.AppendSeparator()
        actions.append(
            (
                menu.Append(wx.ID_ANY, tr("&Delete bookmark")),
                self.remove_selected,
            )
        )
        for menu_item, callback in actions:
            menu.Bind(
                wx.EVT_MENU,
                lambda menu_event, action=callback: action(),
                menu_item,
            )
        self.items.PopupMenu(menu)
        menu.Destroy()


class PlaylistsPanel(wx.Panel):
    def __init__(
        self,
        parent: wx.Window,
        frame: "MainFrame",
        title: str = tr_noop("Playlists"),
    ) -> None:
        super().__init__(parent)
        title = tr(title)
        self.frame = frame
        self.title = title
        self.history = NavigationHistory(ViewState(title, []))
        self.current_playlist: SpotifyItem | None = None
        self.pending_playlist_selection_id: str | None = None
        self.loaded_once = False
        self.loading = False

        outer = wx.BoxSizer(wx.VERTICAL)
        self.heading = wx.StaticText(self, label=title)
        self.items = ItemList(self)
        self.items.SetName(title)
        self.status = wx.StaticText(self, label=msg.PLAYLISTS_LOAD_HINT)
        self.filter = wx.TextCtrl(self)
        self.filter.SetName(tr("Filter"))
        set_windows_accessible(
            self.filter,
            _NamedControlAccessible,
            tr("Filter"),
        )
        outer.Add(self.heading, 0, wx.ALL, 10)
        outer.Add(self.items, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        outer.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        outer.Add(
            wx.StaticText(self, label=tr("Filter this list")),
            0,
            wx.LEFT | wx.RIGHT,
            10,
        )
        outer.Add(self.filter, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizer(outer)

        self.items.Bind(wx.EVT_SET_FOCUS, self.on_focus)
        self.items.Bind(wx.EVT_KEY_DOWN, self.on_key)
        self.items.Bind(self.items.ACTIVATED_EVENT, self.on_open)
        self.items.Bind(wx.EVT_CONTEXT_MENU, self.on_context_menu)
        self.filter.Bind(wx.EVT_TEXT, self.on_filter)

    def on_focus(self, event: wx.FocusEvent) -> None:
        event.Skip()
        if not self.loaded_once and not self.loading:
            wx.CallAfter(self.refresh)

    def refresh(self) -> None:
        if self.loading:
            return
        if self.history.can_go_back and self.current_playlist:
            playlist = self.current_playlist
            self.loading = True
            self.frame.run_task(
                None,
                lambda: self.frame.spotify.children(playlist),
                lambda items: self.show_tracks(playlist, items, replace=True),
                failure=self.finish_load_error,
            )
            return
        self.loading = True
        self.frame.run_task(
            msg.loading(self.title),
            self.frame.spotify.user_playlists,
            self.show_playlists,
            failure=self.finish_load_error,
        )

    def finish_load_error(self) -> None:
        self.loading = False

    def show_playlists(self, playlists: list[SpotifyItem]) -> None:
        self.loading = False
        self.loaded_once = True
        state = ViewState(tr("Playlists"), playlists)
        if self.pending_playlist_selection_id:
            state.selected = next(
                (
                    index
                    for index, playlist in enumerate(playlists)
                    if playlist.id == self.pending_playlist_selection_id
                ),
                0,
            )
            self.pending_playlist_selection_id = None
        self.history.reset(state)
        self.current_playlist = None
        self.render(
            state,
            focus=window_is_or_descendant(wx.Window.FindFocus(), self.items),
        )

    def on_open(self, event: wx.Event | None = None) -> None:
        item = self.items.selected_item()
        if not item:
            return
        if self.history.can_go_back:
            if self.current_playlist:
                self.frame.play_in_context(self.current_playlist, item)
            else:
                self.frame.play(item)
            return
        if item in self.history.current.items:
            self.history.remember_selection(
                self.history.current.items.index(item)
            )
        self.loading = True
        self.frame.run_task(
            None,
            lambda: self.frame.spotify.children(item),
            lambda tracks: self.show_tracks(item, tracks),
            failure=self.finish_load_error,
        )

    def show_tracks(
        self,
        playlist: SpotifyItem,
        tracks: list[SpotifyItem],
        *,
        replace: bool = False,
    ) -> None:
        self.loading = False
        self.current_playlist = playlist
        title = (
            tr("{name}, read only").format(name=playlist.name)
            if playlist.raw.get("editable") is False
            else playlist.name
        )
        state = ViewState(title, tracks)
        if replace:
            selected = self.history.current.selected
            state.selected = selected
            self.history.replace(state)
        else:
            self.history.push(state)
        self.render(
            state,
            focus=window_is_or_descendant(wx.Window.FindFocus(), self.items),
        )

    def go_back(self) -> bool:
        if not self.history.can_go_back:
            return False
        state = self.history.back()
        self.current_playlist = None
        self.render(state, focus=True)
        return True

    def render(self, state: ViewState, *, focus: bool) -> None:
        self.heading.SetLabel(state.title)
        self.frame.update_title_for_page(self, state.title)
        preferred = (
            state.items[state.selected]
            if 0 <= state.selected < len(state.items)
            else None
        )
        matches = self.filtered_items(state.items)
        matches = sort_spotify_items(
            matches,
            state.sort_key,
            state.sort_descending,
        )
        selected = matches.index(preferred) if preferred in matches else 0
        self.items.set_items(matches, selected)
        self.update_filter_status(len(matches), len(state.items))
        if focus:
            self.items.SetFocus()

    def on_filter(self, event: wx.CommandEvent | None = None) -> None:
        state = self.history.current
        preferred = self.items.selected_item()
        if preferred in state.items:
            state.selected = state.items.index(preferred)
        self.render(state, focus=False)

    def filtered_items(
        self,
        items: list[SpotifyItem],
    ) -> list[SpotifyItem]:
        return filter_spotify_items(items, self.filter.GetValue())

    def update_filter_status(self, matches: int, total: int) -> None:
        if self.filter.GetValue().strip():
            self.status.SetLabel(msg.matching_items(matches, total))
        else:
            self.status.SetLabel(msg.item_count(total))
        state = self.history.current
        if state.sort_key != "original":
            direction = (
                tr("descending")
                if state.sort_descending
                else tr("ascending")
            )
            self.status.SetLabel(
                self.status.GetLabel()
                + tr(
                    " Sorted by {sort_label} {direction}."
                ).format(
                    sort_label=tr(SORT_LABELS[state.sort_key]),
                    direction=direction,
                )
            )

    def sort_options(self) -> set[str]:
        return available_sort_keys(self.history.current.items)

    def current_sort(self) -> tuple[str, bool]:
        state = self.history.current
        return state.sort_key, state.sort_descending

    def set_sort(self, sort_key: str) -> None:
        if sort_key not in self.sort_options():
            return
        state = self.history.current
        preferred = self.items.selected_item()
        if preferred in state.items:
            state.selected = state.items.index(preferred)
        state.sort_key = sort_key
        if sort_key == "original":
            state.sort_descending = False
        self.render(state, focus=True)

    def set_sort_descending(self, descending: bool) -> None:
        state = self.history.current
        if state.sort_key == "original":
            return
        state.sort_descending = descending
        self.render(state, focus=True)

    def filtered_playback_items(
        self,
        selected: SpotifyItem,
    ) -> list[SpotifyItem]:
        """Return the visible playback sequence beginning at selected."""
        if not self.filter.GetValue().strip() or selected not in self.items.items:
            return []
        start = self.items.items.index(selected)
        return [
            item
            for item in self.items.items[start:]
            if item.playable and item.uri
        ]

    def on_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if (
            key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
            and physical_control_down(event)
        ):
            self.frame.open_selected_track_album(
                self.items.selected_item()
            )
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.on_open()
        elif key == wx.WXK_BACK:
            self.go_back()
        elif key == wx.WXK_DELETE:
            if self.history.can_go_back:
                self.remove_selected()
            else:
                playlist = self.items.selected_item()
                if playlist:
                    self.remove_playlist(playlist)
        elif key == wx.WXK_F10 and event.ShiftDown():
            self.on_context_menu()
        else:
            event.Skip()


    def remove_selected(self) -> None:
        playlist = self.current_playlist
        item = self.items.selected_item()
        if not playlist or not item:
            return
        if playlist.raw.get("editable") is False:
            self.frame.say(msg.READ_ONLY)
            return
        answer = wx.MessageBox(
            (
                tr(
                    "Remove \"{name}\" from the playlist \"{playlist}\"?"
                ).format(name=item.name, playlist=playlist.name)
            ),
            tr("Remove playlist item"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
            self,
        )
        if answer != wx.YES:
            return
        index = self.items.GetSelection()
        self.frame.run_task(
            None,
            lambda: self.frame.spotify.remove_from_playlist(playlist, item),
            lambda result: self.finish_remove(index),
        )

    def finish_remove(self, index: int) -> None:
        item = self.items.items[index] if 0 <= index < len(self.items.items) else None
        state = self.history.current
        if item in state.items:
            state.items.remove(item)
        state.selected = min(index, max(0, len(state.items) - 1))
        self.render(state, focus=False)
        self.items.SetFocus()

    def on_context_menu(self, event: wx.Event | None = None) -> None:
        item = self.items.selected_item()
        if not item:
            return
        if not self.history.can_go_back:
            self.popup_playlist_menu(item)
            return
        removable = bool(
            self.current_playlist
            and self.current_playlist.raw.get("editable") is not False
        )
        move_actions = (
            PlaylistsPanel.playlist_move_actions(self)
            if self.current_playlist
            and self.current_playlist.raw.get("owned") is True
            else None
        )
        playlist_actions = [
            (
                tr("&Copy to playlist..."),
                lambda: self.frame.choose_playlist_for_items(
                    self.items.marked_items() or [item]
                ),
            )
        ]
        if removable:
            playlist_actions.append(
                (
                    tr("Move to another &playlist..."),
                    self.move_selected_to_playlist,
                )
            )
        if (
            self.current_playlist
            and self.current_playlist.raw.get("owned") is True
        ):
            playlist_actions.append(
                (
                    tr("Find &alternate versions..."),
                    self.find_alternate_versions,
                )
            )
        self.frame.popup_item_menu(
            self.items,
            item,
            play_callback=(
                lambda: self.frame.play_in_context(
                    self.current_playlist,
                    item,
                )
                if self.current_playlist
                else self.frame.play(item)
            ),
            remove_callback=self.remove_selected if removable else None,
            remove_label=tr("&Remove from playlist"),
            additional_actions=move_actions,
            top_level_actions=playlist_actions,
        )

    def move_selected_to_playlist(self) -> None:
        source = self.current_playlist
        if not source or source.raw.get("editable") is False:
            self.frame.say(msg.READ_ONLY)
            return
        selected = self.items.marked_items() or [self.items.selected_item()]
        selections = locate_playlist_selections(
            self.history.current.items,
            [item for item in selected if item and item.uri],
        )
        if not selections:
            self.frame.say(msg.SELECT_TRACK_OR_EPISODE)
            return
        self.frame.choose_playlist_for_items(
            [selection.item for selection in selections],
            move_from=source,
            move_selections=selections,
            on_moved=lambda: self.finish_move_to_playlist(selections),
        )

    def finish_move_to_playlist(
        self, moved: list[PlaylistSelection]
    ) -> None:
        state = self.history.current
        for selection in sorted(
            moved, key=lambda selection: selection.source_index, reverse=True
        ):
            if 0 <= selection.source_index < len(state.items):
                del state.items[selection.source_index]
        state.selected = min(
            self.items.GetSelection(), max(0, len(state.items) - 1)
        )
        self.render(state, focus=False)
        self.items.SetFocus()

    def find_alternate_versions(self) -> None:
        playlist = self.current_playlist
        original = self.items.selected_item()
        source = (
            self.history.current.items.index(original)
            if original in self.history.current.items
            else -1
        )
        if (
            not playlist
            or playlist.raw.get("owned") is not True
            or not original
            or original.kind != ItemKind.TRACK
            or source < 0
        ):
            return
        occurrences = sum(
            track.uri == original.uri
            for track in self.history.current.items
        )
        if occurrences > 1:
            self.frame.say(msg.DUPLICATE_PLAYLIST_REPLACEMENT)
            return
        self.frame.run_task(
            None,
            lambda: self.frame.spotify.alternate_versions(original),
            lambda candidates: self.show_alternate_versions(
                playlist,
                original,
                source,
                candidates,
            ),
        )

    def show_alternate_versions(
        self,
        playlist: SpotifyItem,
        original: SpotifyItem,
        source: int,
        candidates: list[SpotifyItem],
    ) -> None:
        if not candidates:
            self.frame.say(msg.NO_ALTERNATE_VERSIONS)
            return
        dialog = AlternateVersionsDialog(
            self.frame,
            original,
            candidates,
            lambda replacement, owner: self.replace_playlist_track(
                playlist,
                original,
                replacement,
                source,
                owner,
            ),
        )
        dialog.ShowModal()
        dialog.Destroy()
        if self.current_playlist is playlist:
            wx.CallAfter(self.restore_playlist_item_focus, source)

    def restore_playlist_item_focus(self, source: int) -> None:
        state = self.history.current
        if not self.history.can_go_back or not 0 <= source < len(state.items):
            return
        state.selected = source
        self.render(state, focus=False)
        self.items.SetFocus()

    def replace_playlist_track(
        self,
        playlist: SpotifyItem,
        original: SpotifyItem,
        replacement: SpotifyItem,
        source: int,
        dialog: AlternateVersionsDialog,
    ) -> None:
        if (
            self.current_playlist is not playlist
            or not 0 <= source < len(self.history.current.items)
            or self.history.current.items[source].uri != original.uri
        ):
            return
        answer = wx.MessageBox(
            msg.replace_playlist_track(original.name, replacement.name),
            tr("Replace playlist track"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
            self,
        )
        if answer != wx.YES:
            return
        self.frame.run_task(
            None,
            lambda: self.frame.spotify.replace_playlist_item(
                playlist,
                original,
                replacement,
                source,
            ),
            lambda result: self.finish_replace_playlist_track(
                source,
                replacement,
                dialog,
            ),
        )

    def finish_replace_playlist_track(
        self,
        source: int,
        replacement: SpotifyItem,
        dialog: AlternateVersionsDialog,
    ) -> None:
        tracks = list(self.history.current.items)
        tracks[source] = replacement
        self.history.current.items = tracks
        self.history.current.selected = source
        if hasattr(self, "render"):
            self.render(self.history.current, focus=False)
        else:
            self.items.set_items(tracks, source)
        dialog.finish_replace()
        self.frame.say(msg.PLAYLIST_TRACK_REPLACED)

    def playlist_move_actions(
        self,
    ) -> list[tuple[str, Callable[[], None]]]:
        history = getattr(self, "history", None)
        state_items = (
            history.current.items
            if history is not None
            else self.items.items
        )
        selected_item = getattr(self.items, "selected_item", None)
        selected = selected_item() if selected_item else None
        if selected is None:
            visible_source = self.items.GetSelection()
            selected = (
                state_items[visible_source]
                if 0 <= visible_source < len(state_items)
                else None
            )
        source = (
            state_items.index(selected)
            if selected in state_items
            else -1
        )
        total = len(state_items)
        if source < 0 or total < 2:
            return []
        actions: list[tuple[str, Callable[[], None]]] = []
        if source > 0:
            actions.extend(
                [
                    (tr("Move &up"), lambda: self.move_selected_to(source - 1)),
                    (tr("Move to &top"), lambda: self.move_selected_to(0)),
                ]
            )
        if source < total - 1:
            actions.extend(
                [
                    (tr("Move &down"), lambda: self.move_selected_to(source + 1)),
                    (
                        tr("Move to &bottom"),
                        lambda: self.move_selected_to(total - 1),
                    ),
                ]
            )
        actions.append(
            (
                tr("Move to &position..."),
                self.move_selected_to_position,
            )
        )
        return actions

    def move_selected_to_position(self) -> None:
        selected = self.items.selected_item()
        source = (
            self.history.current.items.index(selected)
            if selected in self.history.current.items
            else -1
        )
        total = len(self.history.current.items)
        if source < 0 or total < 2:
            return
        dialog = wx.TextEntryDialog(
            self,
            msg.playlist_position_prompt(total),
            tr("Move playlist item"),
            str(source + 1),
        )
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        value = dialog.GetValue().strip()
        dialog.Destroy()
        try:
            target = int(value) - 1
        except ValueError:
            self.frame.say(msg.INVALID_PLAYLIST_POSITION)
            return
        if not 0 <= target < total:
            self.frame.say(msg.INVALID_PLAYLIST_POSITION)
            return
        self.move_selected_to(target)

    def move_selected_to(self, target: int) -> None:
        playlist = self.current_playlist
        selected = self.items.selected_item()
        source = (
            self.history.current.items.index(selected)
            if selected in self.history.current.items
            else -1
        )
        total = len(self.history.current.items)
        if (
            not playlist
            or playlist.raw.get("owned") is not True
            or source < 0
            or not 0 <= target < total
            or source == target
        ):
            return
        self.frame.run_task(
            None,
            lambda: self.frame.spotify.reorder_playlist_item(
                playlist,
                source,
                target,
            ),
            lambda result: self.finish_move(source, target),
        )

    def finish_move(self, source: int, target: int) -> None:
        tracks = list(self.history.current.items)
        track = tracks.pop(source)
        tracks.insert(target, track)
        self.history.current.items = tracks
        self.history.current.selected = target
        if hasattr(self, "render"):
            self.render(self.history.current, focus=False)
        else:
            self.items.set_items(tracks, target)
        self.items.SetFocus()
        self.frame.say(msg.playlist_item_moved(target + 1, len(tracks)))

    def popup_playlist_menu(self, playlist: SpotifyItem) -> None:
        menu = wx.Menu()
        actions = [
            (menu.Append(wx.ID_ANY, tr("&Open")), self.on_open),
            (
                menu.Append(wx.ID_ANY, tr("&Play")),
                lambda: self.frame.play(playlist),
            ),
            (
                menu.Append(wx.ID_ANY, tr("Playlist &information...")),
                lambda: self.frame.show_playlist_information(playlist),
            ),
            (
                menu.Append(wx.ID_ANY, tr("&New playlist...")),
                self.frame.create_playlist,
            ),
        ]
        if playlist.raw.get("owned") is True:
            actions.append(
                (
                    menu.Append(wx.ID_ANY, tr("Re&name...")),
                    lambda: self.rename_playlist(playlist),
                )
            )
        menu.AppendSeparator()
        actions.append(
            (
                menu.Append(wx.ID_ANY, tr("Remove from &library...")),
                lambda: self.remove_playlist(playlist),
            )
        )
        for menu_item, callback in actions:
            menu.Bind(
                wx.EVT_MENU,
                lambda event, action=callback: action(),
                menu_item,
            )
        self.items.PopupMenu(menu)
        menu.Destroy()

    def rename_playlist(self, playlist: SpotifyItem) -> None:
        dialog = wx.TextEntryDialog(
            self,
            msg.ENTER_PLAYLIST_NAME,
            tr("Rename playlist"),
            playlist.name,
        )
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        name = dialog.GetValue().strip()
        dialog.Destroy()
        if not name or name == playlist.name:
            return
        self.frame.run_task(
            None,
            lambda: self.frame.spotify.rename_playlist(playlist, name),
            lambda result: self.finish_rename_playlist(playlist, name),
        )

    def finish_rename_playlist(
        self,
        playlist: SpotifyItem,
        name: str,
    ) -> None:
        playlist.name = name
        index = self.items.items.index(playlist)
        self.items.SetString(index, playlist.accessible_label())
        self.items.SetSelection(index)
        self.frame.say(msg.RENAMED)

    def remove_playlist(self, playlist: SpotifyItem) -> None:
        answer = wx.MessageBox(
            msg.remove_playlist(playlist.name),
            tr("Remove playlist"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
            self,
        )
        if answer != wx.YES:
            return
        self.frame.run_task(
            None,
            lambda: self.frame.spotify.remove_playlist_from_library(playlist),
            lambda result: self.finish_remove_playlist(playlist),
        )

    def finish_remove_playlist(self, playlist: SpotifyItem) -> None:
        index = self.items.items.index(playlist)
        self.items.remove_at(index)
        self.history.current.items = list(self.items.items)
        self.history.current.selected = self.items.GetSelection()
        self.status.SetLabel(msg.item_count(len(self.items.items)))
        self.frame.say(msg.REMOVED_FROM_LIBRARY)

    def on_navigation(self, event: wx.NavigationKeyEvent) -> None:
        if event.IsFromTab() and event.GetDirection():
            logger.debug(
                "Forward navigation from %s list to main tab bar",
                self.title,
            )
            self.frame.focus_tab_bar()
        else:
            event.Skip()


class AudiobooksPanel(PlaylistsPanel):
    def __init__(self, parent: wx.Window, frame: "MainFrame") -> None:
        super().__init__(parent, frame, tr("Audiobooks"))
        self.history.reset(ViewState(tr("Audiobooks"), []))
        self.heading.SetLabel(tr("Audiobooks"))
        self.status.SetLabel(msg.AUDIOBOOKS_LOAD_HINT)

    def refresh(self) -> None:
        if self.loading:
            return
        if self.history.can_go_back and self.current_playlist:
            audiobook = self.current_playlist
            self.loading = True
            self.frame.run_task(
                None,
                lambda: self.frame.spotify.audiobook_chapters(audiobook),
                lambda chapters: self.show_chapters(
                    audiobook,
                    chapters,
                    replace=True,
                ),
                failure=self.finish_load_error,
            )
            return
        self.loading = True
        self.frame.run_task(
            None,
            self.frame.spotify.saved_audiobooks,
            self.show_audiobooks,
            failure=self.finish_load_error,
        )

    def show_audiobooks(self, audiobooks: list[SpotifyItem]) -> None:
        self.loading = False
        self.loaded_once = True
        state = ViewState(tr("Audiobooks"), audiobooks)
        self.history.reset(state)
        self.current_playlist = None
        self.render(
            state,
            focus=window_is_or_descendant(wx.Window.FindFocus(), self.items),
        )
        if not self.frame.spotify.has_scope("user-read-playback-position"):
            self.status.SetLabel(
                msg.audiobook_resume_permission(len(audiobooks))
            )

    def on_open(self, event: wx.Event | None = None) -> None:
        item = self.items.selected_item()
        if not item:
            return
        if self.history.can_go_back:
            self.frame.play_audiobook_chapter(item)
            return
        if item in self.history.current.items:
            self.history.remember_selection(
                self.history.current.items.index(item)
            )
        self.loading = True
        self.frame.run_task(
            None,
            lambda: self.frame.spotify.audiobook_chapters(item),
            lambda chapters: self.show_chapters(item, chapters),
            failure=self.finish_load_error,
        )

    def show_chapters(
        self,
        audiobook: SpotifyItem,
        chapters: list[SpotifyItem],
        *,
        replace: bool = False,
    ) -> None:
        self.loading = False
        self.current_playlist = audiobook
        state = ViewState(audiobook.name, chapters)
        if replace:
            state.selected = self.history.current.selected
            self.history.replace(state)
        else:
            self.history.push(state)
        self.render(
            state,
            focus=window_is_or_descendant(wx.Window.FindFocus(), self.items),
        )

    def on_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if (
            key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
            and physical_control_down(event)
        ):
            self.frame.open_selected_track_album(
                self.items.selected_item()
            )
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.on_open()
        elif key == wx.WXK_BACK:
            self.go_back()
        elif key == wx.WXK_F10 and event.ShiftDown():
            self.on_context_menu()
        else:
            event.Skip()

    def on_context_menu(self, event: wx.Event | None = None) -> None:
        item = self.items.selected_item()
        if not item:
            return
        self.frame.popup_item_menu(
            self.items,
            item,
            open_callback=self.on_open,
        )


class PodcastsPanel(PlaylistsPanel):
    def __init__(self, parent: wx.Window, frame: "MainFrame") -> None:
        super().__init__(parent, frame, tr("Podcasts"))
        self.history.reset(ViewState(tr("Podcasts"), []))
        self.heading.SetLabel(tr("Podcasts"))
        self.status.SetLabel(msg.PODCASTS_LOAD_HINT)
        self.rss_store = RSSSubscriptionStore(frame.store)
        self.pending_refresh_announcement: str | None = None
        browse_controls = wx.BoxSizer(wx.HORIZONTAL)
        browse_controls.Add(
            wx.StaticText(self, label=tr("Browse category")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            6,
        )
        self.browse_category = wx.Choice(
            self,
            choices=[
                tr(label) for label, _query in PODCAST_BROWSE_CATEGORIES
            ],
        )
        self.browse_category.SetSelection(0)
        browse_controls.Add(self.browse_category, 1, wx.RIGHT, 6)
        browse_controls.Add(
            wx.StaticText(self, label=tr("Language")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            6,
        )
        self.language_filter = wx.Choice(self)
        self.language_options: list[tuple[str, str]] = []
        browse_controls.Add(self.language_filter, 1, wx.RIGHT, 6)
        self.browse_button = wx.Button(self, label=tr("&Browse podcasts"))
        browse_controls.Add(self.browse_button, 0)
        self.GetSizer().Insert(
            1,
            browse_controls,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            10,
        )
        podcast_filters = wx.BoxSizer(wx.HORIZONTAL)
        podcast_filters.Add(
            wx.StaticText(self, label=tr("Listening status")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            6,
        )
        self.listening_status_filter = wx.Choice(
            self,
            choices=[
                tr(label) for label, _value in PODCAST_LISTENING_STATUSES
            ],
        )
        self.listening_status_filter.SetSelection(0)
        podcast_filters.Add(self.listening_status_filter, 1)
        self.GetSizer().Add(
            podcast_filters,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            10,
        )
        self.update_language_options([])
        self.browse_button.Bind(wx.EVT_BUTTON, self.on_browse)
        self.language_filter.Bind(wx.EVT_CHOICE, self.on_filter)
        self.listening_status_filter.Bind(wx.EVT_CHOICE, self.on_filter)
        self.browse_button.MoveBeforeInTabOrder(self.items)
        self.language_filter.MoveBeforeInTabOrder(self.browse_button)
        self.browse_category.MoveBeforeInTabOrder(self.language_filter)
        self.Layout()

    def update_language_options(self, items: list[SpotifyItem]) -> None:
        selected_code = ""
        selection = self.language_filter.GetSelection()
        if 0 <= selection < len(self.language_options):
            selected_code = self.language_options[selection][1]
        codes = sorted(
            set(PODCAST_LANGUAGE_NAMES)
            | {
                code
                for item in items
                for code in podcast_language_codes(item)
            },
            key=lambda code: tr(
                PODCAST_LANGUAGE_NAMES.get(code, code)
            ).casefold(),
        )
        options = [(tr("All languages"), "")]
        options.extend(
            (
                f"{tr(PODCAST_LANGUAGE_NAMES.get(code, code))} ({code})",
                code,
            )
            for code in codes
        )
        options.append((tr("Unknown language"), "unknown"))
        self.language_options = options
        self.language_filter.Set(
            [label for label, _code in self.language_options]
        )
        selected = next(
            (
                index
                for index, (_label, code) in enumerate(options)
                if code == selected_code
            ),
            0,
        )
        self.language_filter.SetSelection(selected)

    def selected_language_code(self) -> str:
        selection = self.language_filter.GetSelection()
        if 0 <= selection < len(self.language_options):
            return self.language_options[selection][1]
        return ""

    def render(self, state: ViewState, *, focus: bool) -> None:
        self.update_language_options(state.items)
        super().render(state, focus=focus)

    def filtered_items(
        self,
        items: list[SpotifyItem],
    ) -> list[SpotifyItem]:
        pagination = [item for item in items if item.kind == ItemKind.HEADING]
        matches = super().filtered_items(
            [item for item in items if item.kind != ItemKind.HEADING]
        )
        language = self.selected_language_code()
        status_selection = self.listening_status_filter.GetSelection()
        status = PODCAST_LISTENING_STATUSES[
            max(0, status_selection)
        ][1]
        if language:
            matches = [
                item
                for item in matches
                if (
                    not podcast_language_codes(item)
                    if language == "unknown"
                    else language in podcast_language_codes(item)
                )
            ]
        if status != "all":
            matches = [
                item
                for item in matches
                if podcast_listening_status(item) == status
            ]
        return matches + pagination

    def update_filter_status(self, matches: int, total: int) -> None:
        matches = sum(
            item.kind != ItemKind.HEADING for item in self.items.items
        )
        total = sum(
            item.kind != ItemKind.HEADING
            for item in self.history.current.items
        )
        filters_active = bool(self.filter.GetValue().strip())
        filters_active = filters_active or self.language_filter.GetSelection() > 0
        filters_active = (
            filters_active or self.listening_status_filter.GetSelection() > 0
        )
        if filters_active:
            incomplete = any(
                item.raw.get("load_more")
                or item.raw.get("load_more_episodes")
                for item in self.history.current.items
            )
            self.status.SetLabel(
                msg.matching_loaded_items(matches, total)
                if incomplete
                else msg.matching_items(matches, total)
            )
        else:
            super().update_filter_status(matches, total)

    def on_browse(self, event: wx.Event | None = None) -> None:
        if self.loading:
            return
        index = self.browse_category.GetSelection()
        label, default_query = PODCAST_BROWSE_CATEGORIES[max(0, index)]
        query = podcast_browse_query(
            label,
            default_query,
            self.selected_language_code(),
        )
        self.loading = True
        self.frame.run_task(
            msg.SEARCHING_SPOTIFY,
            lambda: self.frame.spotify.search(query, "show"),
            lambda shows: self.show_browse_results(label, query, shows),
            failure=self.finish_load_error,
        )

    def show_browse_results(
        self,
        label: str,
        query: str,
        shows: list[SpotifyItem],
    ) -> None:
        self.loading = False
        self.loaded_once = True
        state = ViewState(
            tr("Browse podcasts: {label}").format(label=tr(label)),
            shows,
            query=query,
            category="show",
        )
        if self.history.current.items:
            self.history.push(state)
        else:
            self.history.reset(state)
        self.current_playlist = None
        self.render(state, focus=True)
        count = sum(show.kind == ItemKind.SHOW for show in shows)
        rendered_items = getattr(
            getattr(self, "items", None),
            "items",
            shows,
        )
        visible_count = sum(
            show.kind == ItemKind.SHOW for show in rendered_items
        )
        selected_language = (
            self.selected_language_code()
            if hasattr(self, "selected_language_code")
            else ""
        )
        if selected_language:
            self.update_filter_status(visible_count, count)
        else:
            self.status.SetLabel(
                ntr(
                    "{count} podcast search result. Not a complete Spotify "
                    "catalogue.",
                    "{count} podcast search results. Not a complete Spotify "
                    "catalogue.",
                    count,
                ).format(count=count)
            )
        if not visible_count:
            self.frame.say(
                tr(
                    "No podcasts found with the selected category and "
                    "language."
                )
            )

    def on_show_saved(self, event: wx.Event | None = None) -> None:
        if self.loading:
            return
        self.loading = True
        self.frame.run_task(
            None,
            lambda: (
                self.frame.spotify.saved_shows(),
                self.frame.spotify.saved_episodes(),
                self.rss_store.shows(),
            ),
            lambda result: self.show_library(*result),
            failure=self.finish_load_error,
        )

    def refresh(self) -> None:
        if self.loading:
            return
        if self.history.can_go_back and self.current_playlist:
            show = self.current_playlist
            self.loading = True
            self.frame.run_task(
                None,
                lambda: self.frame.spotify.children(show),
                lambda episodes: self.show_episodes(
                    show,
                    episodes,
                    replace=True,
                ),
                failure=self.finish_load_error,
            )
            return
        self.loading = True
        self.frame.run_task(
            None,
            lambda: (
                self.frame.spotify.saved_shows(),
                self.frame.spotify.saved_episodes(),
                self.rss_store.shows(),
            ),
            lambda result: self.show_library(*result),
            failure=self.finish_load_error,
        )

    def show_library(
        self,
        shows: list[SpotifyItem],
        episodes: list[SpotifyItem],
        rss_shows: list[SpotifyItem] | None = None,
    ) -> None:
        self.loading = False
        self.loaded_once = True
        imported = rss_shows or []
        items = [*shows, *imported, *episodes]
        state = ViewState(tr("Podcasts"), items)
        self.history.reset(state)
        self.current_playlist = None
        self.render(
            state,
            focus=window_is_or_descendant(wx.Window.FindFocus(), self.items),
        )
        self.status.SetLabel(
            msg.saved_podcasts(len(shows) + len(imported), len(episodes))
        )
        if getattr(self, "pending_refresh_announcement", None):
            announcement = self.pending_refresh_announcement
            self.pending_refresh_announcement = None
            self.frame.say(announcement)

    def on_open(self, event: wx.Event | None = None) -> None:
        item = self.items.selected_item()
        if not item:
            return
        if item.raw.get("load_more"):
            self.load_more_podcasts(item)
            return
        if item.raw.get("load_more_episodes"):
            self.load_more_episodes(item)
            return
        if item.kind == ItemKind.HEADING:
            return
        if item.kind == ItemKind.EPISODE:
            self.frame.play_playable_item(item)
            return
        if item.kind != ItemKind.SHOW:
            return
        if item in self.history.current.items:
            self.history.remember_selection(
                self.history.current.items.index(item)
            )
        self.loading = True
        if item.raw.get("rss_subscription"):
            self.frame.run_task(
                tr("Loading podcast feed."),
                lambda: feed_episodes(item),
                lambda episodes: self.show_episodes(item, episodes),
                failure=self.finish_load_error,
                requires_spotify=False,
            )
            return
        self.frame.run_task(
            None,
            lambda: self.frame.spotify.children(item),
            lambda episodes: self.show_episodes(item, episodes),
            failure=self.finish_load_error,
        )

    def load_more_podcasts(self, item: SpotifyItem) -> None:
        state = self.history.current
        if state.category != "show" or not state.query:
            return
        offset = int(item.raw.get("next_offset") or 0)
        self.loading = True
        self.frame.run_task(
            msg.LOADING_MORE_RESULTS,
            lambda: self.frame.spotify.search(state.query, "show", offset),
            lambda shows: self.append_browse_results(state, shows),
            failure=self.finish_load_error,
        )

    def append_browse_results(
        self,
        state: ViewState,
        shows: list[SpotifyItem],
    ) -> None:
        self.loading = False
        if self.history.current is not state:
            return
        existing = [show for show in state.items if not show.raw.get("load_more")]
        existing_ids = {show.id for show in existing}
        additions = [
            show
            for show in shows
            if show.raw.get("load_more") or show.id not in existing_ids
        ]
        added = sum(show.kind == ItemKind.SHOW for show in additions)
        first_new = len(existing)
        state.items[:] = existing + additions
        state.selected = first_new if added else max(0, first_new - 1)
        self.render(state, focus=True)
        total = sum(show.kind == ItemKind.SHOW for show in state.items)
        rendered_items = getattr(
            getattr(self, "items", None),
            "items",
            state.items,
        )
        visible = sum(
            show.kind == ItemKind.SHOW for show in rendered_items
        )
        selected_language = (
            self.selected_language_code()
            if hasattr(self, "selected_language_code")
            else ""
        )
        if selected_language:
            self.update_filter_status(visible, total)
        else:
            self.status.SetLabel(
                ntr(
                    "{total} podcast search result. Not a complete Spotify "
                    "catalogue.",
                    "{total} podcast search results. Not a complete Spotify "
                    "catalogue.",
                    total,
                ).format(total=total)
            )
        self.frame.say(
            ntr(
                "Loaded {added} additional podcast.",
                "Loaded {added} additional podcasts.",
                added,
            ).format(added=added)
            if added
            else msg.NO_MORE_RESULTS
        )

    def show_episodes(
        self,
        show: SpotifyItem,
        episodes: list[SpotifyItem],
        *,
        replace: bool = False,
    ) -> None:
        self.loading = False
        self.current_playlist = show
        state = ViewState(show.name, episodes)
        if replace:
            state.selected = self.history.current.selected
            self.history.replace(state)
        else:
            self.history.push(state)
        self.render(
            state,
            focus=window_is_or_descendant(wx.Window.FindFocus(), self.items),
        )

    def load_more_episodes(self, item: SpotifyItem) -> None:
        state = self.history.current
        show = self.current_playlist
        if not show:
            return
        offset = int(item.raw.get("next_offset") or 0)
        self.loading = True
        self.frame.run_task(
            msg.LOADING_MORE_RESULTS,
            lambda: self.frame.spotify.podcast_episodes(show, offset),
            lambda episodes: self.append_episodes(state, episodes),
            failure=self.finish_load_error,
        )

    def append_episodes(
        self,
        state: ViewState,
        episodes: list[SpotifyItem],
    ) -> None:
        self.loading = False
        if self.history.current is not state:
            return
        existing = [
            episode
            for episode in state.items
            if not episode.raw.get("load_more_episodes")
        ]
        existing_ids = {episode.id for episode in existing}
        new_episodes = [
            episode
            for episode in episodes
            if episode.raw.get("load_more_episodes")
            or episode.id not in existing_ids
        ]
        added = sum(
            episode.kind == ItemKind.EPISODE for episode in new_episodes
        )
        first_new = len(existing)
        state.items[:] = existing + new_episodes
        state.selected = first_new if added else max(0, first_new - 1)
        self.render(state, focus=True)
        self.frame.say(
            ntr(
                "Loaded {added} additional episode.",
                "Loaded {added} additional episodes.",
                added,
            ).format(added=added)
            if added
            else msg.NO_MORE_RESULTS
        )

    def on_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if (
            key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
            and physical_control_down(event)
        ):
            self.frame.open_selected_track_album(
                self.items.selected_item()
            )
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.on_open()
        elif key == wx.WXK_BACK:
            self.go_back()
        elif (
            key == wx.WXK_DELETE
            and not self.history.can_go_back
            and self.history.current.category != "show"
        ):
            item = self.items.selected_item()
            if item:
                self.remove_saved_item(item)
        elif key == wx.WXK_F10 and event.ShiftDown():
            self.on_context_menu()
        else:
            event.Skip()

    def on_context_menu(self, event: wx.Event | None = None) -> None:
        item = self.items.selected_item()
        if not item or item.kind == ItemKind.HEADING:
            return
        saved_library_item = (
            not self.history.can_go_back
            and self.history.current.category != "show"
        )
        remove_callback = None
        remove_label = None
        if saved_library_item and item.kind == ItemKind.SHOW:
            remove_callback = lambda: self.remove_saved_item(item)
            remove_label = tr("&Unsubscribe...")
        elif saved_library_item and item.kind == ItemKind.EPISODE:
            remove_callback = lambda: self.remove_saved_item(item)
            remove_label = tr("Remove saved &episode...")
        self.frame.popup_item_menu(
            self.items,
            item,
            open_callback=self.on_open if item.kind == ItemKind.SHOW else None,
            play_callback=(
                lambda: self.frame.play_playable_item(item)
                if item.kind == ItemKind.EPISODE
                else None
            ),
            remove_callback=remove_callback,
            remove_label=remove_label,
        )

    def remove_saved_item(self, item: SpotifyItem) -> None:
        if item.raw.get("rss_subscription") and item.kind == ItemKind.SHOW:
            answer = wx.MessageBox(
                msg.unsubscribe_podcast(item.name),
                tr("Unsubscribe"),
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
                self,
            )
            if answer == wx.YES:
                self.rss_store.remove(str(item.raw.get("feed_url") or ""))
                self.finish_remove_saved_item()
            return
        prompt = (
            msg.unsubscribe_podcast(item.name)
            if item.kind == ItemKind.SHOW
            else msg.remove_saved_episode(item.name)
        )
        title = (
            tr("Unsubscribe")
            if item.kind == ItemKind.SHOW
            else tr("Remove saved episode")
        )
        answer = wx.MessageBox(
            prompt,
            title,
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
            self,
        )
        if answer != wx.YES:
            return
        self.frame.run_task(
            None,
            lambda: self.frame.spotify.remove(item),
            lambda result: self.finish_remove_saved_item(),
        )

    def finish_remove_saved_item(self) -> None:
        self.frame.say(msg.REMOVED_FROM_LIBRARY)
        self.refresh()

    def import_opml(self, path: Path) -> None:
        self.frame.run_task(
            tr("Importing podcast subscriptions."),
            lambda: self.rss_store.import_file(path),
            self.finish_import_opml,
            requires_spotify=False,
        )

    def finish_import_opml(self, result: tuple[int, int]) -> None:
        added, total = result
        self.pending_refresh_announcement = tr(
            "Imported {added} podcast subscriptions; {total} stored."
        ).format(
            added=added,
            total=total,
        )
        self.loading = False
        self.refresh()


class NowPlayingPanel(wx.Panel):
    def __init__(self, parent: wx.Window, frame: "MainFrame") -> None:
        super().__init__(parent)
        self.frame = frame
        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(
            wx.StaticText(self, label=tr("Now Playing")),
            0,
            wx.LEFT | wx.RIGHT | wx.TOP,
            6,
        )
        self.items = ItemList(self)
        self.items.SetName(tr("Now Playing"))
        self.items.SetMinSize((-1, self.FromDIP(42)))
        layout.Add(self.items, 1, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(layout)
        self.set_item(None)
        self.items.Bind(wx.EVT_CONTEXT_MENU, self.on_context_menu)

    def set_item(self, item: SpotifyItem | None) -> None:
        current = self.items.items[0] if len(self.items.items) == 1 else None
        if item:
            if (
                current
                and current.id == item.id
                and current.accessible_label() == item.accessible_label()
            ):
                # Playback state arrives frequently. Keep the underlying item
                # current without rebuilding the focused accessibility row.
                self.items.items[0] = item
                return
            announce = item.accessible_label()
            self.items.set_items([item])
        else:
            if current and current.id == "__nothing_playing__":
                return
            placeholder = SpotifyItem(
                "__nothing_playing__",
                ItemKind.HEADING,
                tr("Nothing playing"),
            )
            announce = msg.NOTHING_PLAYING
            self.items.set_items([placeholder])
        if item_list_ancestor(wx.Window.FindFocus()) is self.items:
            self.frame.say(announce)

    def selected_item(self) -> SpotifyItem | None:
        item = self.items.selected_item()
        if not item or item.kind == ItemKind.HEADING:
            return None
        return item

    def on_context_menu(self, event: wx.Event | None = None) -> None:
        item = self.selected_item()
        if not item:
            self.frame.say(msg.NOTHING_PLAYING)
            return
        top_level_actions = [
            (tr("Show &lyrics"), lambda: self.frame.show_lyrics_for_item(item)),
            (
                tr("Add to &playlist..."),
                lambda: self.frame.choose_playlist_for_item(item),
            ),
        ]
        artists = item.raw.get("artists") or []
        if item.kind == ItemKind.TRACK and artists:
            artist_id = str(artists[0].get("id") or "")
            artist_name = str(artists[0].get("name") or "")
            if artist_id and artist_name:
                top_level_actions.append(
                    (
                        tr(
                            "Show albums by &{artist_name}"
                        ).format(artist_name=artist_name),
                        lambda: self.frame.show_artist_albums(
                            artist_id, artist_name
                        ),
                    )
                )
        self.frame.popup_item_menu(
            self.items,
            item,
            top_level_actions=top_level_actions,
            include_select_all=False,
        )

    def on_item_list_char_hook(self, event: wx.KeyEvent) -> None:
        self.frame.on_global_key(event)


def copy_to_clipboard(text: str) -> bool:
    """Put text on the system clipboard. Returns False if it was unavailable."""
    clipboard = wx.TheClipboard
    if not clipboard.Open():
        return False
    try:
        return bool(clipboard.SetData(wx.TextDataObject(text)))
    finally:
        clipboard.Close()


def default_export_dir() -> Path:
    documents = Path.home() / "Documents"
    return documents if documents.is_dir() else Path.home()


class ErrorDialog(wx.Dialog):
    """An error message with a button that copies shareable details.

    Escape and Close simply dismiss it, so copying is always deliberate.
    """

    def __init__(
        self,
        parent: wx.Window | None,
        message: str,
        on_copy: Callable[[], None],
    ) -> None:
        super().__init__(
            parent,
            title="BlindSpot",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.text = wx.TextCtrl(
            self,
            value=message,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP,
            size=(480, 120),
        )
        self.text.SetName(tr("Error"))
        self.copy_button = wx.Button(self, label=tr("&Copy error details"))
        self.close_button = wx.Button(self, wx.ID_OK, tr("&Close"))
        self.close_button.SetDefault()
        self.SetAffirmativeId(wx.ID_OK)
        self.SetEscapeId(wx.ID_OK)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.Add(self.copy_button, 0, wx.RIGHT, 8)
        buttons.Add(self.close_button)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(self.text, 1, wx.EXPAND | wx.ALL, 10)
        outer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizerAndFit(outer)
        self.copy_button.Bind(wx.EVT_BUTTON, lambda event: on_copy())
        self.text.SetFocus()


class DiagnosticDialog(wx.Dialog):
    """Shows the exact developer report, and lets the user choose what goes in."""

    def __init__(
        self,
        parent: wx.Window | None,
        render: Callable[[bool, bool], str],
        on_copy: Callable[[str], None],
        on_save: Callable[[wx.Window, str], None],
    ) -> None:
        super().__init__(
            parent,
            title=tr("Capture log for developer"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.render = render
        self.on_copy = on_copy
        self.on_save = on_save
        intro = wx.StaticText(
            self,
            label=(
                tr(
                    "This report lists BlindSpot and system versions, "
                    "non-secret settings and the last error. Passwords, "
                    "tokens and API keys are always removed. Read it below "
                    "before you copy or save it."
                )
            ),
        )
        intro.Wrap(560)
        self.include_log = wx.CheckBox(self, label=tr(
            "Include recent &log lines"
        ))
        self.include_names = wx.CheckBox(
            self,
            label=(
                tr(
                    "Include song, artist and &playlist names and search "
                    "terms in the log lines"
                )
            ),
        )
        self.include_names.Disable()
        self.report = wx.TextCtrl(
            self,
            style=wx.TE_MULTILINE | wx.TE_READONLY,
            size=(640, 340),
        )
        self.report.SetName(tr("Report contents"))
        self.copy_button = wx.Button(self, label=tr("&Copy to clipboard"))
        self.save_button = wx.Button(self, label=tr("&Save to file..."))
        self.close_button = wx.Button(self, wx.ID_CLOSE, tr("Close"))
        self.SetAffirmativeId(wx.ID_CLOSE)
        self.SetEscapeId(wx.ID_CLOSE)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.Add(self.copy_button, 0, wx.RIGHT, 8)
        buttons.Add(self.save_button, 0, wx.RIGHT, 8)
        buttons.Add(self.close_button)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(intro, 0, wx.ALL, 10)
        outer.Add(self.include_log, 0, wx.LEFT | wx.RIGHT, 10)
        outer.Add(self.include_names, 0, wx.ALL, 10)
        outer.Add(self.report, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        outer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        self.SetSizerAndFit(outer)
        self.include_log.Bind(wx.EVT_CHECKBOX, self.on_options_changed)
        self.include_names.Bind(wx.EVT_CHECKBOX, self.on_options_changed)
        self.copy_button.Bind(
            wx.EVT_BUTTON,
            lambda event: self.on_copy(self.report.GetValue()),
        )
        self.save_button.Bind(wx.EVT_BUTTON, self.on_save_clicked)
        self.refresh()
        self.report.SetFocus()

    def on_save_clicked(self, event: wx.Event | None = None) -> None:
        # The file dialog must be a child of this dialog, not of the main
        # window behind it, or closing it hands focus to a disabled window.
        self.on_save(self, self.report.GetValue())
        self.save_button.SetFocus()

    def on_options_changed(self, event: wx.Event | None = None) -> None:
        self.include_names.Enable(self.include_log.GetValue())
        if not self.include_log.GetValue():
            self.include_names.SetValue(False)
        self.refresh()

    def refresh(self) -> None:
        self.report.SetValue(
            self.render(
                self.include_log.GetValue(),
                self.include_names.GetValue(),
            )
        )
        self.report.SetInsertionPoint(0)


class MainFrame(wx.Frame):
    def __init__(self, spotify: SpotifyClient, store: PortableStore) -> None:
        super().__init__(None, title="BlindSpot", size=(820, 620))
        self.spotify = spotify
        self.playlist_operations = PlaylistOperations(spotify)
        self.playlist_clipboard: PlaylistClipboard | None = None
        self.store = store
        settings = self.store.read("settings.json", {}) or {}
        raw_keymap = self.store.read("keymap.json", {}) or {}
        self.keymap = KeyMap(raw_keymap)
        self.keymap_warnings_seen = warnings_seen(raw_keymap)
        self.announce_track_changes = bool(
            settings.get("announce_track_changes", False)
        )
        self.announce_lyric_sections = bool(
            settings.get("announce_lyric_sections", False)
        )
        self.announce_volume_changes = bool(
            settings.get("announce_volume_changes", True)
        )
        self.announce_cart_names = bool(
            settings.get("announce_cart_names", True)
        )
        self.check_followed_on_start = bool(
            settings.get("check_followed_on_start", True)
        )
        self.resume_mode = resume_mode_from_settings(settings)
        self.playback_volume_percent = volume_percent_from_settings(settings)
        self.global_shortcuts = normalized_global_shortcuts(
            settings.get("global_shortcuts", {})
        )
        self.follow_braille_lyrics = bool(
            settings.get("follow_braille_lyrics", False)
        )
        self.registered_hotkey_ids: list[int] = []
        self.last_player_item_id: str | None = None
        self.suppress_track_announcement_id: str | None = None
        self.current_player_state: dict = {}
        self.playback_state_updated_at = time.monotonic()
        self.lyric_sections: tuple[str, list[int]] | None = None
        self.carts = load_carts(self.store.read("carts.json", []))
        self.followed = FollowedArtists(self.store)
        self.cart_start: tuple[SpotifyItem, int] | None = None
        self.pending_cart: tuple[SpotifyItem, int, int] | None = None
        self.playing_cart: Cart | None = None
        self.playing_cart_armed = False
        self.cart_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_cart_timer, self.cart_timer)
        self.pending_previous_restart: wx.CallLater | None = None
        self.shuffle_enabled: bool | None = None
        self.repeat_state: str | None = None
        self.pending_resume: tuple[SpotifyItem, int, str] | None = None
        self.deferred_queue_items: list[SpotifyItem] = []
        self.deferred_queue_flushing = False
        self.deferred_queue_start_item: SpotifyItem | None = None
        self.continuous_mix_generation = 0
        self.continuous_mix: dict[str, object] | None = None
        self.open_album_return_page: int | None = None
        self.open_album_return_state: ViewState | None = None
        self.announcer = Auto()
        self.player: WebPlaybackController | None = None
        self.current_player_item: SpotifyItem | None = None
        self.standalone_player_item_id: str | None = None
        self.lyric_start_item_id: str | None = None
        self.pending_lyric_seek: tuple[str, int] | None = None
        self.pending_play_item: SpotifyItem | None = None
        self.pending_play_items: list[SpotifyItem] = []
        self.pending_play_items_message = ""
        self.pending_play_items_callback: Callable[[], None] | None = None
        self.pending_play_items_disable_repeat = False
        self.pending_play_context: SpotifyItem | None = None
        self.pending_play_position_ms = 0
        self.lyrics = LRCLibClient()
        self.deepl = DeepLClient(
            str(settings.get("deepl_api_key") or ""),
            str(settings.get("lyrics_translation_language") or ""),
        )
        self.ticketmaster = TicketmasterClient(
            str(settings.get("ticketmaster_api_key") or "")
        )
        self.lastfm = LastfmClient(
            str(settings.get("lastfm_api_key") or DEFAULT_LASTFM_API_KEY)
        )
        self.applemusic = AppleMusicClient()
        self.historical_charts = HistoricalHot100Client()
        self.triple_j = Hottest100Client()
        self.classic_100 = Classic100Client()
        self.rn_books = RNBooksClient()
        self.numberones = NumberOnesClient()
        self.musicbrainz = MusicBrainzClient()
        self.wikipedia = WikipediaClient()
        self.last_error: diagnostics.ErrorDetails | None = None
        self.remote_device_id: str | None = None
        self.remote_device_name = ""
        self.remote_supports_volume: bool | None = None
        self.pending_transfer_device: dict | None = None
        self.audio_output_applied = False
        self.listening_timer = recent_plays.ListeningTimer()
        self.volume_before_mute_percent = self.playback_volume_percent
        self.remote_refresh_pending = False
        self.remote_refresh_timer = wx.Timer(self)
        self.Bind(
            wx.EVT_TIMER,
            lambda event: self.refresh_remote_playback(),
            self.remote_refresh_timer,
        )
        self.sleep_timer = wx.Timer(self)
        self.Bind(
            wx.EVT_TIMER,
            lambda event: self.on_sleep_timer(),
            self.sleep_timer,
        )
        self.sleep_after_track_id: str | None = None
        self.authorization_in_progress = False
        self.recent_permission_authorization = False
        self.available_release = None
        self.update_progress = None
        self.CreateStatusBar()
        self._build_menu()
        layout = wx.BoxSizer(wx.VERTICAL)
        self.notebook = wx.Notebook(self)
        self.search = SearchPanel(self.notebook, self)
        self.liked = CollectionPanel(
            self.notebook,
            self,
            tr("Liked Songs"),
            spotify.liked_songs,
            removable=True,
            silent_load=False,
            load_on_first_focus=True,
        )
        self.queue = CollectionPanel(
            self.notebook,
            self,
            tr("Queue"),
            self.queue_items,
            silent_load=True,
            load_on_first_focus=True,
        )
        self.playlists = PlaylistsPanel(self.notebook, self)
        self.recently_played = RecentlyPlayedPanel(
            self.notebook,
            self,
            tr("Recently Played"),
            self.load_recently_played,
            silent_load=True,
            load_on_first_focus=True,
        )
        self.audiobooks = AudiobooksPanel(self.notebook, self)
        self.podcasts = PodcastsPanel(self.notebook, self)
        self.saved_albums = SavedAlbumsPanel(self.notebook, self)
        self.new_music = NewMusicPanel(self.notebook, self)
        self.bookmarks_dialog: HostedPanelDialog | None = None
        self.concerts_dialog: HostedPanelDialog | None = None
        for panel, label in (
            (self.search, tr("Search")),
            (self.liked, tr("Liked Songs")),
            (self.queue, tr("Queue")),
            (self.playlists, tr("Playlists")),
            (self.recently_played, tr("Recently Played")),
            (self.audiobooks, tr("Audiobooks")),
            (self.podcasts, tr("Podcasts")),
            (self.saved_albums, tr("Saved Albums")),
            (self.new_music, tr("Discover")),
        ):
            set_windows_accessible(panel, _NamedPageAccessible, label)
            self.notebook.AddPage(panel, label)
        self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.on_tab_changed)
        self.now_playing = NowPlayingPanel(self, self)
        layout.Add(self.notebook, 1, wx.EXPAND)
        layout.Add(self.now_playing, 0, wx.EXPAND)
        self.SetSizer(layout)
        self.set_view_title(tr("Search"))
        self.load_pending_resume()
        self.Bind(wx.EVT_CHAR_HOOK, self.on_global_key)
        for _, hotkey_id in GLOBAL_SHORTCUT_ACTIONS:
            self.Bind(wx.EVT_HOTKEY, self.on_global_hotkey, id=hotkey_id)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Centre()
        self._create_web_player()
        wx.CallLater(4000, self.check_followed_releases)
        wx.CallAfter(self.apply_global_hotkey_setting)
        wx.CallAfter(self.initial_focus)
        wx.CallAfter(self.check_for_updates, False)

    def set_follow_braille_lyrics(self, enabled: bool) -> None:
        self.follow_braille_lyrics = enabled
        settings = self.store.read("settings.json", {}) or {}
        settings["follow_braille_lyrics"] = enabled
        self.store.write("settings.json", settings)

    def lyric_adjustment_ms(self, track_id: str) -> int:
        records = self.store.read("lyrics.json", {}) or {}
        record = records.get(track_id) or {}
        return int(record.get("adjustment_ms") or 0)

    def set_lyric_adjustment_ms(
        self,
        track_id: str,
        adjustment_ms: int,
    ) -> None:
        records = self.store.read("lyrics.json", {}) or {}
        record = records.get(track_id) or {}
        record["adjustment_ms"] = adjustment_ms
        records[track_id] = record
        self.store.write("lyrics.json", records)

    def lyrics_for_item(self, item: SpotifyItem) -> Lyrics:
        records = self.store.read("lyrics.json", {}) or {}
        source = (records.get(item.id) or {}).get("source")
        if source:
            lyrics = Lyrics(
                track_name=str(source.get("track_name") or item.name),
                artist_name=str(source.get("artist_name") or ""),
                text=str(source.get("text") or ""),
                synced=bool(source.get("synced")),
                track_id=item.id,
                synced_lines=[
                    (int(line[0]), str(line[1]))
                    for line in source.get("synced_lines") or []
                ],
                substitute=True,
                synced_breaks=[
                    int(stop) for stop in source.get("synced_breaks") or []
                ],
            )
        else:
            recent = getattr(self, "recent_lyrics", None)
            if recent and recent[0] == item.id:
                lyrics = recent[1]
            else:
                lyrics = self.lyrics.lyrics_for(item)
                self.recent_lyrics = (item.id, lyrics)
                if lyrics.substitute:
                    record = records.get(item.id) or {}
                    record["source"] = {
                        "track_name": lyrics.track_name,
                        "artist_name": lyrics.artist_name,
                        "text": lyrics.text,
                        "synced": lyrics.synced,
                        "synced_lines": lyrics.synced_lines,
                        "synced_breaks": lyrics.synced_breaks,
                    }
                    records[item.id] = record
                    self.store.write("lyrics.json", records)
        lyrics = self.cached_translation(lyrics, records)
        # The Lyrics dialog and lyric-section shortcuts share this copy.  Keep
        # it even when the original lyrics came from the persistent cache so
        # Shift+F6/Shift+F8 never need to perform another lyrics lookup.
        self.recent_lyrics = (item.id, lyrics)
        return lyrics

    def cached_translation(self, lyrics: Lyrics, records: dict) -> Lyrics:
        target = self.deepl.target_language
        if not self.deepl.api_key or not target or not lyrics.text:
            logger.debug(
                "Lyrics translation unavailable configured=%s target=%s text=%s",
                bool(self.deepl.api_key),
                bool(target),
                bool(lyrics.text),
            )
            lyrics.translated_text = ""
            lyrics.translated_language = ""
            return lyrics
        record = records.get(lyrics.track_id) or {}
        cached = record.get("translation") or {}
        if (
            cached.get("target_language") == target
            and cached.get("source_text") == lyrics.text
            and cached.get("text")
        ):
            logger.info(
                "Lyrics translation served from cache track=%s target=%s",
                lyrics.track_id,
                target,
            )
            lyrics.translated_text = str(cached["text"])
            lyrics.translated_language = target
        else:
            logger.debug(
                "Lyrics translation not cached track=%s target=%s",
                lyrics.track_id,
                target,
            )
            lyrics.translated_text = ""
            lyrics.translated_language = ""
        return lyrics

    def translate_lyrics(self, lyrics: Lyrics) -> Lyrics:
        logger.info(
            "DeepL translation requested by user track=%s target=%s",
            lyrics.track_id,
            self.deepl.target_language,
        )
        translated = self.deepl.translate(lyrics.text)
        records = self.store.read("lyrics.json", {}) or {}
        record = records.get(lyrics.track_id) or {}
        record["translation"] = {
            "target_language": self.deepl.target_language,
            "source_text": lyrics.text,
            "text": translated,
        }
        records[lyrics.track_id] = record
        self.store.write("lyrics.json", records)
        lyrics.translated_text = translated
        lyrics.translated_language = self.deepl.target_language
        logger.info(
            "DeepL translation completed track=%s target=%s characters=%d",
            lyrics.track_id,
            self.deepl.target_language,
            len(lyrics.text),
        )
        return lyrics

    def cached_transcript_translation(
        self,
        item: SpotifyItem,
        transcript: Transcript,
    ) -> Transcript:
        target = self.deepl.target_language
        if not self.deepl.api_key or not target or not transcript.text:
            return transcript
        return TranscriptCache(self.store).read_translation(
            item.id, transcript, target
        )

    def translate_transcript(
        self,
        item: SpotifyItem,
        transcript: Transcript,
    ) -> Transcript:
        target = self.deepl.target_language
        logger.info(
            "DeepL transcript translation requested item=%s target=%s characters=%d",
            item.id,
            target,
            len(transcript.text),
        )
        translated = self.deepl.translate(transcript.text)
        return TranscriptCache(self.store).write_translation(
            item.id, transcript, target, translated
        )

    def _create_web_player(self) -> None:
        try:
            self.player = WebPlaybackController(
                self,
                self.spotify,
                on_ready=self.on_player_ready,
                on_error=self.on_player_error,
                on_playback_update=self.on_playback_update,
                initial_volume_percent=self.playback_volume_percent,
            )
        except Exception as error:
            logger.exception("Could not create BlindSpot web player")
            self.player = None
            self.say(str(error))

    def _build_menu(self) -> None:
        ctrl = "RAWCTRL" if sys.platform == "darwin" else "Ctrl"
        menu_bar = wx.MenuBar()
        file_menu = wx.Menu()
        export_list = file_menu.Append(wx.ID_ANY, tr("&Export list..."))
        import_opml = file_menu.Append(
            wx.ID_ANY, tr("Import podcast subscriptions from OP&ML...")
        )
        transcribe_local_audio = file_menu.Append(
            wx.ID_ANY, tr("Transcribe &local audio...")
        )
        manage_carts = file_menu.Append(wx.ID_ANY, tr("Manage &carts..."))
        followed_artists = file_menu.Append(
            wx.ID_ANY, tr("Followed &artists and authors...")
        )
        open_bookmarks = file_menu.Append(
            wx.ID_ANY,
            tr("&Bookmarks...") + menu_function_shortcut(f"{ctrl}+B"),
        )
        search_concerts = file_menu.Append(
            wx.ID_ANY,
            (
                tr("Search for c&oncerts...")
                + menu_function_shortcut(f"{ctrl}+Shift+G")
            ),
        )
        create_playlist = file_menu.Append(
            wx.ID_ANY,
            (
                tr("&New playlist...") + menu_function_shortcut(f'{ctrl}+Shift+N')
            ),
        )
        file_menu.AppendSeparator()
        preferences = file_menu.Append(
            wx.ID_PREFERENCES,
            tr("&Preferences...") + menu_function_shortcut(f'{ctrl}+,'),
        )
        account = wx.Menu()
        connect = account.Append(
            wx.ID_ANY,
            (
                tr("&Connect to Spotify...") + menu_function_shortcut(f'{ctrl}+Shift+C')
            ),
        )
        refresh_permissions = account.Append(
            wx.ID_ANY,
            tr("&Refresh Spotify permissions..."),
        )
        sign_out = account.Append(wx.ID_ANY, tr(
            "Sign &out and erase credentials"
        ))
        file_menu.AppendSubMenu(account, tr("Accoun&t"))
        file_menu.AppendSeparator()
        close = file_menu.Append(wx.ID_EXIT, tr("E&xit\tAlt+F4"))
        menu_bar.Append(file_menu, tr("&File"))
        edit = wx.Menu()
        select_all_label = (
            tr("Select &all (Command+A)")
            if sys.platform == "darwin"
            else tr("Select &all (Ctrl+A)")
        )
        clipboard_key = "Command" if sys.platform == "darwin" else "Ctrl"
        cut_items = edit.Append(
            wx.ID_CUT, tr(
                "Cu&t playlist items ({clipboard_key}+X)"
            ).format(clipboard_key=clipboard_key)
        )
        copy_items = edit.Append(
            wx.ID_COPY, tr(
                "&Copy playlist items ({clipboard_key}+C)"
            ).format(clipboard_key=clipboard_key)
        )
        paste_items = edit.Append(
            wx.ID_PASTE, tr(
                "&Paste playlist items ({clipboard_key}+V)"
            ).format(clipboard_key=clipboard_key)
        )
        edit.AppendSeparator()
        select_all = edit.Append(wx.ID_SELECTALL, select_all_label)
        self.edit_menu = edit
        self.select_all_item = select_all
        self.cut_items_menu_item = cut_items
        self.copy_items_menu_item = copy_items
        self.paste_items_menu_item = paste_items
        menu_bar.Append(edit, tr("&Edit"))
        go = wx.Menu()
        self.keyed_menu_items: list[tuple[wx.MenuItem, str, str]] = []

        def add_item(
            menu: wx.Menu,
            label: str,
            handler: Callable[[], None],
            action_id: str = "",
        ) -> wx.MenuItem:
            menu_item = menu.Append(
                wx.ID_ANY,
                MainFrame.menu_label(self, label, action_id),
            )
            # Let the native menu close and restore focus before the command
            # speaks.  Otherwise a screen reader can announce the restored
            # control over (or immediately after) the command's status/error.
            self.Bind(
                wx.EVT_MENU,
                lambda event: wx.CallAfter(handler),
                menu_item,
            )
            if action_id:
                self.keyed_menu_items.append((menu_item, label, action_id))
            return menu_item

        add_item(
            go, tr("&Play focused item"), self.play_selected, "play_focused"
        )
        add_item(
            go,
            tr("Pause or &resume"),
            self.toggle_pause_resume,
            "pause_resume",
        )
        add_item(
            go, tr("Pre&vious track"), self.previous_track, "previous_track"
        )
        add_item(go, tr("&Next track"), self.next_track, "next_track")
        go.AppendSeparator()

        seek_menu = wx.Menu()
        add_item(
            seek_menu,
            tr("Seek &backward 5 seconds"),
            lambda: self.seek(-5000),
            "seek_backward",
        )
        add_item(
            seek_menu,
            tr("Seek &forward 5 seconds"),
            lambda: self.seek(5000),
            "seek_forward",
        )
        add_item(
            seek_menu,
            tr("&Previous lyric section"),
            lambda: self.jump_lyric_section(-1),
            "previous_verse",
        )
        add_item(
            seek_menu,
            tr("&Next lyric section"),
            lambda: self.jump_lyric_section(1),
            "next_verse",
        )
        add_item(
            seek_menu,
            tr("&Jump to time..."),
            self.jump_to_time,
            "jump_time",
        )
        add_item(
            seek_menu,
            tr("Bookmark current p&osition"),
            self.save_current_bookmark,
            "bookmark_current",
        )
        go.AppendSubMenu(seek_menu, tr("S&eek and jump"))

        volume_menu = wx.Menu()
        add_item(
            volume_menu,
            tr("Volume &down 5 percent"),
            lambda: self.adjust_volume(-5),
            "volume_down",
        )
        add_item(
            volume_menu,
            tr("Volume &up 5 percent"),
            lambda: self.adjust_volume(5),
            "volume_up",
        )
        add_item(
            volume_menu,
            tr("&Mute or unmute"),
            self.toggle_mute,
            "toggle_mute",
        )
        go.AppendSubMenu(volume_menu, tr("Vol&ume"))

        speak_menu = wx.Menu()
        add_item(
            speak_menu,
            tr("Speak &total time"),
            lambda: self.announce_time("total"),
            "speak_total",
        )
        add_item(
            speak_menu,
            tr("Speak &elapsed time"),
            lambda: self.announce_time("elapsed"),
            "speak_elapsed",
        )
        add_item(
            speak_menu,
            tr("Speak &remaining time"),
            lambda: self.announce_time("remaining"),
            "speak_remaining",
        )
        add_item(
            speak_menu,
            tr("Speak &current track"),
            self.speak_current_track,
            "speak_current",
        )
        add_item(
            speak_menu,
            tr("Speak &up next"),
            self.speak_up_next,
            "speak_up_next",
        )
        go.AppendSubMenu(speak_menu, tr("Spea&k"))

        now_playing_menu = wx.Menu()
        add_item(
            now_playing_menu,
            tr("What's this song &about?"),
            self.show_current_song_story,
            "song_story",
        )
        add_item(
            now_playing_menu,
            tr("Album and recording &information..."),
            self.show_current_music_details,
        )
        add_item(
            now_playing_menu,
            tr("&Open album"),
            self.open_current_album,
            "open_current_album",
        )
        add_item(
            now_playing_menu,
            tr("Find alternate &versions..."),
            self.find_alternate_versions_for_current,
        )
        add_item(
            now_playing_menu,
            tr("&Lyrics..."),
            self.show_lyrics,
            "show_lyrics",
        )
        add_item(
            now_playing_menu,
            tr("Albums by a&rtist"),
            self.show_current_artist_albums,
        )
        add_item(
            now_playing_menu,
            tr("Find &covers (MusicBrainz)"),
            self.find_covers_for_current,
        )
        current_mix_menu = wx.Menu()
        add_item(
            current_mix_menu,
            tr("&Open for inspection"),
            self.open_similar_mix_for_current_track,
        )
        add_item(
            current_mix_menu,
            tr("Start &now"),
            self.start_similar_mix_for_current_track,
        )
        add_item(
            current_mix_menu,
            tr("Add after current &queue"),
            self.queue_similar_mix_for_current_track,
        )
        now_playing_menu.AppendSubMenu(
            current_mix_menu,
            tr("Similar-track &mix (Last.fm)"),
        )
        add_item(
            now_playing_menu,
            tr("Browse &genres (Last.fm)..."),
            self.browse_genres_for_current,
        )
        add_item(
            now_playing_menu,
            tr("Add to &playlist..."),
            self.add_current_to_playlist,
        )
        add_item(
            now_playing_menu,
            tr("&Follow artist or author for new releases"),
            self.follow_current_artist,
        )
        add_item(
            now_playing_menu,
            tr("Like or unlike &now playing"),
            self.toggle_like_current_track,
            "like_current",
        )
        go.AppendSubMenu(now_playing_menu, tr("Now pla&ying"))
        go.AppendSeparator()

        add_item(go, tr("Repea&t"), self.cycle_repeat, "cycle_repeat")
        add_item(go, tr("&Shuffle"), self.toggle_shuffle, "toggle_shuffle")
        add_item(
            go,
            tr("Choose playback &device..."),
            self.choose_playback_device,
            "choose_device",
        )
        sleep_menu = wx.Menu()
        add_item(
            sleep_menu,
            tr("After current &track"),
            self.set_sleep_after_current_track,
        )
        add_item(
            sleep_menu,
            tr("After &15 minutes"),
            lambda: self.set_sleep_timer(15),
        )
        add_item(
            sleep_menu,
            tr("After &30 minutes"),
            lambda: self.set_sleep_timer(30),
        )
        add_item(
            sleep_menu,
            tr("After &60 minutes"),
            lambda: self.set_sleep_timer(60),
        )
        sleep_menu.AppendSeparator()
        add_item(
            sleep_menu,
            tr("&Cancel sleep timer"),
            self.cancel_sleep_timer,
        )
        go.AppendSubMenu(sleep_menu, tr("S&leep timer..."))
        menu_bar.Append(go, tr("&Playback"))

        view = wx.Menu()
        sort_menu = wx.Menu()
        self.sort_menu_items: dict[str, wx.MenuItem] = {}
        for sort_key in (
            "original",
            "title",
            "artist",
            "album",
            "duration",
            "date_added",
        ):
            menu_item = sort_menu.AppendRadioItem(
                wx.ID_ANY,
                tr(SORT_LABELS[sort_key]),
            )
            self.sort_menu_items[sort_key] = menu_item
            self.Bind(
                wx.EVT_MENU,
                lambda event, key=sort_key: self.sort_current_view(key),
                menu_item,
            )
        self.sort_submenu_item = view.AppendSubMenu(sort_menu, tr("&Sort by"))
        self.sort_descending_item = view.AppendCheckItem(
            wx.ID_ANY,
            tr("&Descending"),
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.set_current_sort_descending(
                self.sort_descending_item.IsChecked()
            ),
            self.sort_descending_item,
        )
        view.AppendSeparator()
        refresh_view = view.Append(
            wx.ID_REFRESH,
            (
                tr("&Refresh current view") + menu_function_shortcut(f'{ctrl}+Shift+F')
            ),
        )
        self.view_menu = view
        menu_bar.Append(view, tr("&View"))

        help_menu = wx.Menu()
        manual = help_menu.Append(wx.ID_HELP, tr("&Manual"))
        check_updates = help_menu.Append(
            wx.ID_ANY,
            tr("Check for &updates..."),
        )
        donate = help_menu.Append(wx.ID_ANY, tr("&Donate to Project"))
        help_menu.AppendSeparator()
        copy_error = help_menu.Append(wx.ID_ANY, tr(
            "Copy last &error details"
        ))
        capture_log = help_menu.Append(wx.ID_ANY, tr(
            "Capture &log for developer..."
        ))
        help_menu.AppendSeparator()
        about = help_menu.Append(wx.ID_ABOUT, tr("&About BlindSpot..."))
        menu_bar.Append(help_menu, tr("&Help"))
        self.SetMenuBar(menu_bar)
        self.Bind(wx.EVT_MENU_OPEN, self.on_menu_open)
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.select_all_in_current_list(),
            select_all,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.copy_selected_items(cut=True),
            cut_items,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.copy_selected_items(cut=False),
            copy_items,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.paste_playlist_clipboard(),
            paste_items,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.create_playlist(),
            create_playlist,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.refresh_current_view(),
            refresh_view,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.open_bookmarks_window(),
            open_bookmarks,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.open_concerts_window(),
            search_concerts,
        )
        self.Bind(wx.EVT_MENU, self.on_preferences, preferences)
        self.Bind(wx.EVT_MENU, self.on_connect, connect)
        self.Bind(
            wx.EVT_MENU,
            lambda event: self._start_authorization(force_dialog=True),
            refresh_permissions,
        )
        self.Bind(wx.EVT_MENU, self.on_sign_out, sign_out)
        self.Bind(wx.EVT_MENU, lambda event: self.Close(), close)
        self.Bind(wx.EVT_MENU, self.on_manual, manual)
        self.Bind(
            wx.EVT_MENU,
            lambda event: wx.CallAfter(self.export_list_command),
            export_list,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.import_podcast_opml(),
            import_opml,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.transcribe_local_audio(),
            transcribe_local_audio,
        )
        self.Bind(wx.EVT_MENU, lambda event: self.manage_carts(), manage_carts)
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.manage_followed_artists(),
            followed_artists,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.copy_error_details(),
            copy_error,
        )
        self.Bind(
            wx.EVT_MENU,
            lambda event: self.open_diagnostic_report(),
            capture_log,
        )
        self.Bind(wx.EVT_MENU, self.on_check_updates, check_updates)
        self.Bind(
            wx.EVT_MENU,
            lambda event: webbrowser.open(PAYPAL_DONATE_URL),
            donate,
        )
        self.Bind(wx.EVT_MENU, self.on_about, about)
    def initial_focus(self) -> None:
        if not self.spotify.connected:
            if self.spotify.client_id and self.spotify.token.get("refresh_token"):
                self.search.focus_query()
            elif self.spotify.client_id:
                self.say(msg.AUTHORIZATION_REQUIRED)
                wx.CallAfter(self.on_connect, None)
            else:
                self.say(msg.NOT_CONNECTED)
                wx.CallAfter(self.on_connect, None)
        else:
            self.search.focus_query()
            if not self.spotify.web_playback_authorized:
                self.say(msg.PERMISSIONS_REQUIRED)

    def say(self, message: str) -> None:
        self.SetStatusText(message)
        # Screen readers announce focus/selection changes asynchronously.  Let
        # those settle before speaking BlindSpot's status so a returning focus
        # announcement cannot overwrite or follow the useful message.
        wx.CallAfter(self._announce_status, message)

    def _announce_status(self, message: str) -> None:
        try:
            self.announcer.speak(message, interrupt=False)
        except Exception:
            logger.exception(
                "Could not speak status through accessible-output2"
            )
        try:
            self.announcer.braille(message)
        except Exception:
            # The status text and speech remain available when a screen reader
            # does not expose a braille output channel.
            logger.exception(
                "Could not braille status through accessible-output2"
            )

    def set_view_title(self, title: str) -> None:
        self.SetTitle(tr("{title} - BlindSpot").format(title=title))

    def current_sort_panel(self) -> CollectionPanel | PlaylistsPanel | None:
        panel_names = {
            1: "liked",
            3: "playlists",
            5: "audiobooks",
            6: "podcasts",
            7: "saved_albums",
            8: "new_music",
        }
        name = panel_names.get(self.notebook.GetSelection())
        return getattr(self, name, None) if name else None

    def menu_label(self, label: str, action_id: str = "") -> str:
        """A menu label followed by the action's current key, if it has one."""
        keymap = getattr(self, "keymap", None)
        if not action_id or not keymap:
            return label
        keys = [chord_display(chord) for chord in keymap.bindings(action_id)]
        return f"{label} ({tr(' or ').join(keys)})" if keys else label

    def refresh_menu_key_labels(self) -> None:
        for menu_item, label, action_id in getattr(
            self, "keyed_menu_items", ()
        ):
            menu_item.SetItemLabel(MainFrame.menu_label(self, label, action_id))

    def on_menu_open(self, event: wx.MenuEvent) -> None:
        event.Skip()
        MainFrame.refresh_menu_key_labels(self)
        if event.GetMenu() is self.edit_menu:
            page = self.notebook.GetSelection()
            self.select_all_item.Enable(
                page != 8 or self.new_music.result_mode == "chart"
            )
            current_list = self.current_item_list()
            self.copy_items_menu_item.Enable(current_list is not None)
            playlist = self.playlists.current_playlist
            editable_playlist = bool(
                page == 3
                and self.playlists.history.can_go_back
                and playlist
                and playlist.raw.get("editable") is not False
            )
            self.cut_items_menu_item.Enable(
                bool(current_list) and editable_playlist
            )
            self.paste_items_menu_item.Enable(
                bool(self.playlist_clipboard) and editable_playlist
            )
            return
        if event.GetMenu() is not self.view_menu:
            return
        panel = self.current_sort_panel()
        options = panel.sort_options() if panel else set()
        sort_key, descending = (
            panel.current_sort() if panel else ("original", False)
        )
        self.sort_submenu_item.Enable(bool(options))
        for key, menu_item in self.sort_menu_items.items():
            menu_item.Enable(key in options)
            menu_item.Check(key == sort_key)
        self.sort_descending_item.Enable(
            panel is not None and sort_key != "original"
        )
        self.sort_descending_item.Check(descending)

    def sort_current_view(self, sort_key: str) -> None:
        panel = self.current_sort_panel()
        if panel:
            panel.set_sort(sort_key)

    def set_current_sort_descending(self, descending: bool) -> None:
        panel = self.current_sort_panel()
        if panel:
            panel.set_sort_descending(descending)

    def update_title_for_page(self, page: wx.Window, title: str) -> None:
        if self.notebook.GetCurrentPage() is page:
            self.set_view_title(title)

    def title_for_page(self, selection: int) -> str:
        page = self.notebook.GetPage(selection)
        history = getattr(page, "history", None)
        current = getattr(history, "current", None)
        title = getattr(current, "title", "")
        if title:
            return str(title)
        panel_title = getattr(page, "title", "")
        if panel_title:
            return str(panel_title)
        return str(self.notebook.GetPageText(selection))

    def focus_tab_bar(self) -> None:
        self.SetTitle("BlindSpot")
        self.notebook.SetFocus()

    def run_task(
        self,
        message: str | None,
        worker: Callable[[], object],
        success: Callable[[object], None],
        *,
        failure: Callable[[], None] | None = None,
        error_parent: wx.Window | None = None,
        requires_spotify: bool = True,
    ) -> None:
        if requires_spotify and not self.spotify.connected:
            if failure:
                failure()
            self.say(msg.CONNECT_FIRST)
            return
        if message:
            self.say(message)

        def run() -> None:
            try:
                result = worker()
            except Exception as error:
                expected_unavailable = (
                    PlaylistContentsUnavailable,
                    LyricsUnavailable,
                    TranscriptUnavailable,
                    RSSPodcastError,
                    CoversUnavailable,
                    SongStoryUnavailable,
                    UKChartError,
                )
                if isinstance(error, expected_unavailable):
                    logger.info(
                        "Background task unavailable: %s: %s",
                        message or "unnamed task",
                        error,
                    )
                else:
                    logger.exception(
                        "Background task failed: %s",
                        message or "unnamed task",
                    )
                    self.last_error = diagnostics.capture_error(
                        error,
                        str(error),
                        message or "",
                    )
                error_message = str(error)

                def report_error(
                    caught_error: Exception = error,
                    caught_message: str = error_message,
                ) -> None:
                    if failure:
                        failure()
                    if isinstance(caught_error, RecentlyPlayedPermissionRequired):
                        self.offer_permission_refresh()
                    elif isinstance(
                        caught_error,
                        (
                            PlaylistContentsUnavailable,
                            LyricsUnavailable,
                            TranscriptUnavailable,
                            RSSPodcastError,
                            CoversUnavailable,
                            SongStoryUnavailable,
                            UKChartError,
                        ),
                    ):
                        self.say(caught_message)
                    else:
                        if error_parent is None:
                            self.show_error(caught_message)
                        else:
                            self.show_error(caught_message, error_parent)

                wx.CallAfter(report_error)
            else:
                wx.CallAfter(success, result)

        threading.Thread(target=run, daemon=True).start()

    def offer_permission_refresh(self) -> None:
        answer = wx.MessageBox(
            msg.RECENT_PERMISSION_PROMPT,
            tr("Recently Played"),
            wx.YES_NO | wx.YES_DEFAULT | wx.ICON_QUESTION,
            self,
        )
        if answer == wx.YES:
            self.recent_permission_authorization = True
            # Returning focus to the list must not trigger another automatic
            # load while browser authorization is still in progress.
            self.recently_played.loading = True
            if not self._start_authorization(force_dialog=True):
                self.recent_permission_authorization = False
                self.recently_played.loading = False
        else:
            self.recently_played.loaded_once = True
            self.say(msg.RECENT_NOT_AUTHORIZED)

    def show_error(
        self,
        message: str,
        parent: wx.Window | None = None,
    ) -> None:
        self.say(message)
        # Failures from background tasks were recorded with their traceback;
        # anything else is recorded here with just its message.
        if not self.last_error or self.last_error.message != message:
            self.last_error = diagnostics.capture_error(None, message)
        dialog = ErrorDialog(parent or self, message, self.copy_error_details)
        dialog.ShowModal()
        dialog.Destroy()

    def known_secrets(self) -> list[str]:
        """Every credential BlindSpot holds, so reports can strip them."""
        settings = self.store.read("settings.json", {}) or {}
        token = getattr(self.spotify, "token", None) or {}
        values = [
            token.get("access_token"),
            token.get("refresh_token"),
            token.get("client_id"),
            settings.get("ticketmaster_api_key"),
            settings.get("lastfm_api_key"),
            settings.get("deepl_api_key"),
        ]
        return [str(value) for value in values if value]

    def copy_text(self, text: str, done: str) -> None:
        if copy_to_clipboard(text):
            self.say(done)
        else:
            self.say(msg.CLIPBOARD_UNAVAILABLE)

    def copy_error_details(self) -> None:
        if not self.last_error:
            self.say(msg.NO_ERROR_TO_COPY)
            return
        self.copy_text(
            diagnostics.error_report(self.last_error, self.known_secrets()),
            msg.ERROR_DETAILS_COPIED,
        )

    def diagnostic_text(self, include_log: bool, include_names: bool) -> str:
        settings = self.store.read("settings.json", {}) or {}
        level = str(settings.get("logging_level") or "Off")
        token = getattr(self.spotify, "token", None) or {}
        log_lines = (
            diagnostics.tail_lines(self.store.root / "blindspot.log")
            if include_log
            else None
        )
        return diagnostics.diagnostic_report(
            settings,
            secrets_configured={
                "Spotify client ID": "set" if token.get("client_id") else "not set",
                "Ticketmaster key": (
                    "set" if settings.get("ticketmaster_api_key") else "not set"
                ),
                "Last.fm key": (
                    "custom" if settings.get("lastfm_api_key") else "built-in default"
                ),
                "DeepL key": (
                    "set" if settings.get("deepl_api_key") else "not set"
                ),
            },
            connected=bool(self.spotify.connected),
            last_error=self.last_error,
            log_lines=log_lines,
            logging_level=level,
            include_names=include_names,
            secrets=self.known_secrets(),
        )

    def open_diagnostic_report(self) -> None:
        dialog = DiagnosticDialog(
            self,
            self.diagnostic_text,
            lambda text: self.copy_text(text, msg.REPORT_COPIED),
            lambda parent, text: self.save_text_report(
                text,
                "BlindSpot diagnostic report",
                parent,
            ),
        )
        dialog.ShowModal()
        dialog.Destroy()

    def save_text_report(
        self,
        text: str,
        default_name: str,
        parent: wx.Window | None = None,
    ) -> None:
        """Save a report; `parent` is the dialog that asked, so focus returns to it."""
        dialog = wx.FileDialog(
            parent or self,
            tr("Save report"),
            defaultDir=str(default_export_dir()),
            defaultFile=default_name,
            wildcard=tr("Text file") + " (*.txt)|*.txt",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        )
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        path = Path(dialog.GetPath())
        dialog.Destroy()
        if not path.suffix:
            path = path.with_suffix(".txt")
        try:
            path.write_text(text, encoding="utf-8")
        except OSError as error:
            self.show_error(
                msg.file_save_failed(error.strerror or error),
                parent=parent,
            )
            return
        self.say(tr("Report saved to {name}.").format(name=path.name))

    def current_view_name(self) -> str:
        page = self.notebook.GetSelection()
        if page == 0:
            return self.search.history.current.title
        return self.notebook.GetPageText(page)

    def import_podcast_opml(self) -> None:
        dialog = wx.FileDialog(
            self,
            tr("Import podcast subscriptions"),
            wildcard=tr("OPML files") + "|*.opml;*.xml|" + tr("All files") + "|*.*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        path = Path(dialog.GetPath())
        dialog.Destroy()
        self.podcasts.import_opml(path)

    def transcribe_local_audio(self) -> None:
        dialog = wx.FileDialog(
            self,
            tr("Transcribe local audio"),
            wildcard=(
                tr("Audio files")
                + "|*.mp3;*.m4a;*.aac;*.wav;*.flac;*.ogg;*.opus;*.wma;"
                "*.mp4;*.m4v;*.webm|"
                + tr("All files")
                + "|*.*"
            ),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        path = Path(dialog.GetPath()).resolve()
        dialog.Destroy()
        self.transcribe_local_audio_path(path)

    def transcribe_local_audio_path(self, path: Path) -> None:
        try:
            details = path.stat()
        except OSError as error:
            self.show_error(str(error))
            return
        identity = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{path}|{details.st_size}|{details.st_mtime_ns}",
        )
        item = SpotifyItem(
            f"local-audio:{identity}",
            ItemKind.EPISODE,
            path.stem,
            raw={"local_audio_path": str(path)},
        )
        cache = TranscriptCache(self.store)
        cached = cache.read(item.id)
        self.use_transcript_audio(item, path)
        if cached and cached.complete:
            self.display_transcript(item, cached)
            return
        transcriber = WhisperTranscriber(self.store)
        if not transcriber.ready:
            answer = wx.MessageBox(
                tr(
                    "Local audio transcription requires the optional Whisper "
                    "components and model. The one-time download is about "
                    "150 MB. Download the components now?"
                ),
                tr("Set up local audio transcription"),
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
                self,
            )
            if answer != wx.YES:
                self.say(tr("Transcription was not started."))
                return
            self.run_task(
                tr("Setting up optional local audio transcription."),
                lambda: transcriber.install(
                    lambda message: wx.CallAfter(self.say, message)
                ),
                lambda result: self.start_local_audio_transcript(
                    item, path, cache, transcriber, cached
                ),
                requires_spotify=False,
            )
            return
        self.start_local_audio_transcript(
            item, path, cache, transcriber, cached
        )

    def start_local_audio_transcript(
        self,
        item: SpotifyItem,
        path: Path,
        cache: TranscriptCache,
        transcriber: WhisperTranscriber,
        existing: Transcript | None = None,
    ) -> None:
        dialog = TranscriptDialog(self, item, existing)
        dialog.begin(
            transcriber,
            EpisodeMedia(str(path)),
            cache,
            source_path=path,
        )
        dialog.ShowModal()
        dialog.Destroy()

    def export_list_command(self) -> None:
        """Export the list in view, or the playlist or album selected in it."""
        item_list = self.current_item_list()
        if item_list is None:
            self.say(msg.NOTHING_TO_EXPORT)
            return
        items = list(item_list.items)
        if any(exporting.is_exportable(item) for item in items):
            self.export_items(self.current_view_name(), items)
            return
        selected = item_list.selected_item()
        if selected and selected.kind in {
            ItemKind.PLAYLIST,
            ItemKind.ALBUM,
            ItemKind.SHOW,
        }:
            self.run_task(
                tr("Loading {name} to export").format(name=selected.name),
                lambda: self.spotify.children(selected),
                lambda tracks: self.export_items(selected.name, tracks),
            )
            return
        self.say(msg.NOTHING_TO_EXPORT)

    def export_items(self, name: str, items: list[SpotifyItem]) -> None:
        if not exporting.export_rows(items):
            self.say(msg.NOTHING_TO_EXPORT)
            return
        partial = exporting.is_partial(items)
        dialog = wx.FileDialog(
            self,
            tr("Export list"),
            defaultDir=str(default_export_dir()),
            defaultFile=exporting.safe_filename(name),
            wildcard=(
                tr("Plain text")
                + " (*.txt)|*.txt|"
                + tr("CSV spreadsheet")
                + " (*.csv)|*.csv"
            ),
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        )
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        path = dialog.GetPath()
        fmt = exporting.format_for_path(path, dialog.GetFilterIndex())
        dialog.Destroy()
        if not Path(path).suffix:
            path += f".{fmt}"
        try:
            count = exporting.write_export(
                path,
                fmt,
                name,
                items,
                partial=partial,
            )
        except OSError as error:
            self.show_error(msg.file_save_failed(error.strerror or error))
            return
        logger.info(
            "Exported %d items format=%s partial=%s",
            count,
            fmt,
            partial,
        )
        self.say(msg.exported_items(count, Path(path).name, partial))

    def on_connect(self, event: wx.Event | None) -> None:
        dialog = SetupDialog(self, self.spotify.client_id)
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            self.search.focus_query()
            return
        client_id = dialog.get_client_id()
        dialog.Destroy()
        self.spotify.set_client_id(client_id)
        self._start_authorization()

    def _start_authorization(self, *, force_dialog: bool = False) -> bool:
        if self.authorization_in_progress:
            self.say(msg.AUTHORIZATION_IN_PROGRESS)
            return False
        try:
            request = self.spotify.begin_authorization(
                force_dialog=force_dialog,
            )
        except SpotifyError as error:
            self.show_error(str(error))
            return False
        self.authorization_in_progress = True
        self.say(msg.COMPLETE_LOGIN)

        def authorize() -> None:
            try:
                server = CallbackServer(request.state)
                code = server.wait(
                    on_ready=lambda: wx.CallAfter(
                        webbrowser.open,
                        request.url,
                    ),
                )
                self.spotify.complete_authorization(code, request.verifier)
            except TimeoutError as error:
                wx.CallAfter(self.say, str(error))
            except Exception as error:
                wx.CallAfter(self.show_error, str(error))
            else:
                wx.CallAfter(self.on_connected)
            finally:
                wx.CallAfter(self._authorization_finished)

        threading.Thread(target=authorize, daemon=True).start()
        return True

    def _authorization_finished(self) -> None:
        self.authorization_in_progress = False
        if self.recent_permission_authorization:
            # on_connected clears this flag first on success. If it is still
            # set, authorization failed or timed out.
            self.recent_permission_authorization = False
            self.recently_played.loading = False
            self.recently_played.loaded_once = True
            self.recently_played.status.SetLabel(
                msg.RECENT_AUTH_NOT_COMPLETED
            )

    def on_sign_out(self, event: wx.Event) -> None:
        answer = wx.MessageBox(
            msg.SIGN_OUT_PROMPT,
            tr("Sign out of BlindSpot"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
            self,
        )
        if answer == wx.YES:
            self.spotify.sign_out()
            self.close_spotify_session()
            self.say(msg.SIGNED_OUT)

    def close_spotify_session(self) -> None:
        if self.player:
            self.player.close()
            self.player = None
        self.remote_refresh_timer.Stop()
        self.remote_device_id = None
        self.remote_device_name = ""
        self.remote_supports_volume = None
        self.current_player_state = {}
        self.current_player_item = None
        MainFrame.update_now_playing(self, None)

    def on_preferences(self, event: wx.Event | None = None) -> None:
        settings = self.store.read("settings.json", {}) or {}
        dialog = PreferencesDialog(
            self,
            settings.get("logging_level", "Off"),
            bool(settings.get("announce_track_changes", False)),
            resume_mode_from_settings(settings),
            str(settings.get("ticketmaster_api_key") or ""),
            str(settings.get("lastfm_api_key") or DEFAULT_LASTFM_API_KEY),
            open_logs_folder=self.open_logs_folder,
            open_keyboard_manager=self.open_keyboard_manager,
            language=str(
                settings.get("language") or i18n.DEFAULT_LANGUAGE_SETTING
            ),
            announce_lyric_sections=bool(
                settings.get("announce_lyric_sections", False)
            ),
            announce_volume_changes=bool(
                settings.get("announce_volume_changes", True)
            ),
            announce_cart_names=bool(
                settings.get("announce_cart_names", True)
            ),
            check_followed_on_start=bool(
                settings.get("check_followed_on_start", True)
            ),
            deepl_api_key=str(settings.get("deepl_api_key") or ""),
            lyrics_translation_language=str(
                settings.get("lyrics_translation_language") or ""
            ),
        )
        if dialog.ShowModal() == wx.ID_OK:
            # Keyboard Manager can save globals while Preferences is open.
            # Re-read settings so accepting this dialog cannot overwrite them.
            settings = self.store.read("settings.json", {}) or {}
            level = dialog.get_logging_level()
            settings["logging_level"] = level
            previous_language = str(
                settings.get("language") or i18n.DEFAULT_LANGUAGE_SETTING
            )
            language = dialog.get_language()
            settings["language"] = language
            self.announce_track_changes = (
                dialog.get_announce_track_changes()
            )
            settings["announce_track_changes"] = (
                self.announce_track_changes
            )
            self.announce_lyric_sections = (
                dialog.get_announce_lyric_sections()
            )
            settings["announce_lyric_sections"] = (
                self.announce_lyric_sections
            )
            self.announce_volume_changes = (
                dialog.get_announce_volume_changes()
            )
            settings["announce_volume_changes"] = (
                self.announce_volume_changes
            )
            self.announce_cart_names = dialog.get_announce_cart_names()
            settings["announce_cart_names"] = self.announce_cart_names
            self.check_followed_on_start = dialog.get_check_followed_on_start()
            settings["check_followed_on_start"] = self.check_followed_on_start
            self.resume_mode = dialog.get_resume_mode()
            settings["resume_mode"] = self.resume_mode
            ticketmaster_api_key = dialog.get_ticketmaster_api_key()
            settings["ticketmaster_api_key"] = ticketmaster_api_key
            self.ticketmaster.api_key = ticketmaster_api_key
            lastfm_api_key = dialog.get_lastfm_api_key()
            settings["lastfm_api_key"] = lastfm_api_key
            self.lastfm.api_key = lastfm_api_key
            deepl_api_key = dialog.get_deepl_api_key()
            translation_language = dialog.get_lyrics_translation_language()
            settings["deepl_api_key"] = deepl_api_key
            settings["lyrics_translation_language"] = translation_language
            self.deepl.api_key = deepl_api_key
            self.deepl.target_language = translation_language
            concerts = getattr(self.concerts_dialog, "panel", None)
            if concerts:
                concerts.classifications_loaded = False
                concerts.update_api_key_status()
            settings.pop("resume_last_track", None)
            self.store.write("settings.json", settings)
            if self.resume_mode == "none":
                self.pending_resume = None
                self.store.remove("playback.json")
            elif self.current_player_state:
                self.store.write(
                    "playback.json",
                    playback_state_for_resume(
                        self.current_player_state,
                        self.resume_mode,
                    ),
                )
            configure_logging(self.store.root / "blindspot.log", level)
            if language != previous_language:
                self.say(tr("Restart BlindSpot to use the new language."))
        dialog.Destroy()

    def open_keyboard_manager(
        self,
        parent: wx.Window | None = None,
    ) -> None:
        original_warnings = set(self.keymap_warnings_seen)
        dialog = KeyboardManagerDialog(
            parent or self,
            self.keymap,
            self.keymap_warnings_seen,
            self.global_shortcuts,
        )
        accepted = dialog.ShowModal() == wx.ID_OK
        self.keymap_warnings_seen = set(dialog.seen_warnings)
        if accepted:
            self.keymap = dialog.keymap
            self.global_shortcuts = normalized_global_shortcuts(
                dialog.global_shortcuts
            )
        if accepted or self.keymap_warnings_seen != original_warnings:
            self.store.write(
                "keymap.json",
                self.keymap.to_json(self.keymap_warnings_seen),
            )
        if accepted:
            settings = self.store.read("settings.json", {}) or {}
            settings["global_shortcuts"] = self.global_shortcuts
            settings.pop("global_seek_volume_hotkeys", None)
            self.store.write("settings.json", settings)
            self.apply_global_hotkey_setting()
            self.say(tr("Keyboard map saved."))
        dialog.Destroy()

    def open_logs_folder(self) -> None:
        if not wx.LaunchDefaultApplication(str(self.store.root.resolve())):
            self.show_error(msg.LOGS_FOLDER_OPEN_FAILED)

    def on_manual(self, event: wx.Event | None = None) -> None:
        manual = resource_directory() / "manual.html"
        if not manual.exists():
            self.show_error(msg.MANUAL_NOT_FOUND)
            return
        webbrowser.open(manual.resolve().as_uri())

    def on_check_updates(self, event: wx.Event) -> None:
        self.check_for_updates(True)

    def check_for_updates(self, report_current: bool) -> None:
        def run() -> None:
            try:
                release = latest_release()
            except Exception as error:
                logger.warning("Update check failed: %s", error)
                if report_current:
                    wx.CallAfter(
                        self.show_error,
                        msg.UPDATE_CHECK_FAILED,
                    )
                return
            wx.CallAfter(self._finish_update_check, release, report_current)

        threading.Thread(target=run, daemon=True).start()

    def _finish_update_check(self, release, report_current: bool) -> None:
        if newer_than(release.version, __version__):
            settings = self.store.read("settings.json", {}) or {}
            if (
                not report_current
                and settings.get("dismissed_update") == release.version
            ):
                return
            if supports_automatic_update(release):
                action = msg.UPDATE_INSTALL_PROMPT
            elif supports_managed_download(release):
                action = msg.UPDATE_DOWNLOAD_PROMPT
            else:
                action = msg.UPDATE_PAGE_PROMPT
            previous_focus = wx.Window.FindFocus()
            answer = wx.MessageBox(
                msg.update_available(release.version, action),
                tr("BlindSpot update available"),
                wx.YES_NO | wx.ICON_INFORMATION,
                self,
            )
            if answer == wx.YES:
                self.available_release = release
                self.update_progress = wx.ProgressDialog(
                    tr("Downloading update"),
                    tr("Downloading BlindSpot update..."),
                    maximum=100,
                    parent=self,
                    style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE,
                )
                threading.Thread(
                    target=self._download_update,
                    daemon=True,
                ).start()
            else:
                settings["dismissed_update"] = release.version
                self.store.write("settings.json", settings)
                wx.CallAfter(self._restore_focus_after_update_prompt, previous_focus)
        elif report_current:
            wx.MessageBox(
                msg.update_current(__version__),
                tr("Check for updates"),
                wx.OK | wx.ICON_INFORMATION,
                self,
            )

    def _restore_focus_after_update_prompt(
        self,
        previous_focus: wx.Window | None,
    ) -> None:
        try:
            if (
                previous_focus
                and previous_focus.IsShown()
                and previous_focus.IsEnabled()
            ):
                previous_focus.SetFocus()
                return
        except RuntimeError:
            pass
        self.search.focus_query()

    def _download_update(self) -> None:
        def progress(percent: int) -> None:
            if self.update_progress:
                wx.CallAfter(self.update_progress.Update, percent)

        try:
            success = download_and_install(
                self.available_release,
                progress_callback=progress,
            )
        except Exception as error:
            logger.exception("Update download failed")
            success = False
            message = str(error)
        wx.CallAfter(self._finish_update_download, success, message if not success else "")

    def _finish_update_download(self, success: bool, message: str) -> None:
        if self.update_progress:
            self.update_progress.Destroy()
            self.update_progress = None
        if success and sys.platform == "win32" and getattr(sys, "frozen", False):
            # Let wx fully unwind the app-modal progress dialog before closing
            # the frame. Closing in the same callback can be ignored on Windows.
            wx.CallAfter(self.Close)
        elif success and sys.platform == "darwin" and getattr(sys, "frozen", False):
            wx.MessageBox(
                msg.UPDATE_READY_MACOS,
                tr("BlindSpot update ready"),
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
        elif not success:
            self.show_error(
                message or msg.UPDATE_DOWNLOAD_FAILED
            )

    def on_about(self, event: wx.Event) -> None:
        wx.MessageBox(
            msg.about(__version__),
            tr("About BlindSpot"),
            wx.OK | wx.ICON_INFORMATION,
            self,
        )

    def on_connected(self) -> None:
        if self.recent_permission_authorization:
            self.recent_permission_authorization = False
            if self.spotify.has_scope("user-read-recently-played"):
                self.say(msg.RECENT_AUTHORIZED)
                self.recently_played.loaded_once = False
                self.recently_played.loading = False
                wx.CallAfter(self.recently_played.refresh)
            else:
                self.recently_played.loading = False
                self.recently_played.loaded_once = True
                self.recently_played.status.SetLabel(
                    msg.RECENT_ACCESS_NOT_GRANTED_STATUS
                )
                self.say(msg.RECENT_ACCESS_NOT_GRANTED)
        else:
            self.say(msg.CONNECTED)
        if not self.player:
            self._create_web_player()
        else:
            self.player.provide_token()

    def on_tab_changed(self, event: wx.BookCtrlEvent) -> None:
        old_selection = getattr(event, "GetOldSelection", lambda: -1)()
        selection = getattr(event, "GetSelection", lambda: -1)()
        if old_selection == 0 and selection != 0:
            self.discard_transient_open_album()
        if selection >= 0:
            self.set_view_title(self.title_for_page(selection))
        else:
            self.SetTitle("BlindSpot")
        event.Skip()

    def keymap_action_for_event(
        self,
        event: wx.KeyEvent,
        contexts: tuple[str, ...],
    ) -> str | None:
        keymap = getattr(self, "keymap", None)
        if not keymap:
            return None
        chord = chord_from_event(event, keymap.platform)
        if not chord:
            return None
        for context in contexts:
            for action in KEY_ACTIONS:
                if (
                    action.context == context
                    and chord in keymap.bindings(action.id)
                ):
                    return action.id
        return None

    def dispatch_mapped_key(
        self,
        event: wx.KeyEvent,
        focused: wx.Window | None,
        focused_list: ItemList | None,
    ) -> bool:
        contexts = ("Lists", "Main") if focused_list else ("Main",)
        action = MainFrame.keymap_action_for_event(self, event, contexts)
        if not action:
            return False
        if (
            action == "pause_resume"
            and event.GetKeyCode() == wx.WXK_SPACE
            and space_belongs_to_control(focused)
        ):
            return False
        simple_actions = {
            **TRANSPORT_KEY_ACTIONS,
            "show_manual": ("on_manual", ()),
            "preferences": ("on_preferences", ()),
            "speak_total": ("announce_time", ("total",)),
            "speak_elapsed": ("announce_time", ("elapsed",)),
            "speak_remaining": ("announce_time", ("remaining",)),
            "refresh_view": ("refresh_current_view", ()),
            "choose_device": ("choose_playback_device", ()),
            "speak_current": ("speak_current_track", ()),
            "speak_up_next": ("speak_up_next", ()),
            "jump_time": ("jump_to_time", ()),
            "sleep_timer": ("choose_sleep_timer", ()),
            "show_lyrics": ("show_lyrics", ()),
            "cycle_repeat": ("cycle_repeat", ()),
            "toggle_shuffle": ("toggle_shuffle", ()),
            "like_current": ("toggle_like_current_track", ()),
            "song_story": ("show_current_song_story", ()),
            "open_current_album": ("open_focused_or_current_album", ()),
            "bookmark_current": ("save_current_bookmark", ()),
            "new_playlist": ("create_playlist", ()),
            "item_actions": ("show_selected_actions", ()),
            "open_similar_current": (
                "open_similar_mix_for_current_track",
                (),
            ),
            "start_similar_current": (
                "start_similar_mix_for_current_track",
                (),
            ),
        }
        if action in simple_actions:
            method_name, arguments = simple_actions[action]
            getattr(self, method_name)(*arguments)
            return True
        if action == "play_focused":
            self.play_focused_or_remembered(focused_list)
            return True
        if action in {"cycle_tabs", "cycle_tabs_backward"}:
            direction = -1 if action == "cycle_tabs_backward" else 1
            selection = (
                self.notebook.GetSelection() + direction
            ) % self.notebook.GetPageCount()
            self.notebook.SetSelection(selection)
            self.notebook.SetFocus()
            return True
        if action == "focus_search":
            self.discard_transient_open_album()
            self.notebook.SetSelection(0)
            self.search.focus_query()
            return True
        tab_actions = {
            "open_search": 0,
            "open_liked": 1,
            "open_queue": 2,
            "open_playlists": 3,
            "open_recent": 4,
            "open_audiobooks": 5,
            "open_podcasts": 6,
            "open_saved_albums": 7,
            "open_new_music": 8,
        }
        if action == "open_bookmarks":
            self.open_bookmarks_window()
            return True
        if action == "open_concerts":
            self.open_concerts_window()
            return True
        if action in tab_actions:
            page = tab_actions[action]
            if page == 0:
                self.discard_transient_open_album()
            self.notebook.SetSelection(page)
            if page == 0:
                self.search.focus_query()
            elif page == 8:
                self.new_music.discovery_source.SetFocus()
            return True
        if not focused_list:
            return False
        if action == "select_all":
            notebook = getattr(self, "notebook", None)
            new_music = getattr(self, "new_music", None)
            discover_allows_selection = (
                new_music is not None
                and getattr(new_music, "result_mode", "releases") == "chart"
            )
            if (
                notebook is None
                or notebook.GetSelection() != 8
                or discover_allows_selection
            ):
                focused_list.select_all_items()
        elif action == "open_similar_focused":
            self.open_similar_mix(focused_list.selected_item())
        elif action == "start_similar_focused":
            self.start_similar_mix(focused_list.selected_item())
        elif action == "queue_marked":
            self.queue_from_list(focused_list)
        elif action == "like_focused":
            self.toggle_like_item(focused_list.selected_item())
        elif action == "add_to_playlist":
            self.choose_playlist_for_selected()
        elif action == "open_album":
            self.open_selected_track_album(focused_list.selected_item())
        else:
            return False
        return True

    def on_global_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        focused = wx.Window.FindFocus()
        focused_list = item_list_ancestor(focused)
        if (
            event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
            and ord("1") <= key <= ord("9")
        ):
            self.use_cart_number(key - ord("0"))
            return
        if (
            not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
            and key in (ord("["), ord("]"))
            and self.current_player_item
        ):
            if key == ord("["):
                self.mark_cart_start()
            else:
                self.mark_cart_end()
            return
        if MainFrame.dispatch_mapped_key(self, event, focused, focused_list):
            return
        keymap = getattr(self, "keymap", None)
        if keymap:
            chord = chord_from_event(event, keymap.platform)
            contexts = ("Lists", "Main") if focused_list else ("Main",)
            if chord and keymap.disabled_default(chord, contexts):
                return
        focused_radio_box = radio_box_ancestor(focused)
        if (
            focused_radio_box is not None
            and ord("A") <= key <= ord("Z")
            and not event.AltDown()
            and not physical_control_down(event)
            and not bool(int(event.GetModifiers()) & wx.MOD_WIN)
        ):
            letter = chr(key).casefold()
            index = radio_box_letter_index(focused_radio_box, letter)
            if index is not None:
                move_radio_box_focus(focused_radio_box, index)
            return
        if key == wx.WXK_F1:
            self.on_manual()
        elif (
            key == wx.WXK_F7
            and playback_adjustment_modifier_down(event)
        ):
            self.toggle_mute()
        elif (
            key == wx.WXK_F4
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
        ):
            self.play_focused_or_remembered(focused_list)
        elif (
            key == wx.WXK_F4
            and playback_adjustment_modifier_down(event)
        ):
            self.adjust_volume(-5)
        elif (
            key == wx.WXK_F5
            and playback_adjustment_modifier_down(event)
        ):
            self.adjust_volume(5)
        elif (
            key == wx.WXK_F5
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
        ):
            self.previous_track()
        elif (
            key == wx.WXK_F6
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
        ):
            self.seek(-5000)
        elif (
            key == wx.WXK_F7
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
        ):
            self.toggle_pause_resume()
        elif (
            key == wx.WXK_F8
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
        ):
            self.seek(5000)
        elif (
            key == wx.WXK_F9
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
        ):
            self.next_track()
        elif (
            key == wx.WXK_SPACE
            and not event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
            and not space_belongs_to_control(focused)
        ):
            self.toggle_pause_resume()
            return
        elif physical_control_down(event) and key == wx.WXK_TAB:
            direction = -1 if event.ShiftDown() else 1
            selection = (
                self.notebook.GetSelection() + direction
            ) % self.notebook.GetPageCount()
            self.notebook.SetSelection(selection)
            self.notebook.SetFocus()
        elif key == wx.WXK_TAB:
            self.move_focus(backward=event.ShiftDown())
        elif key == wx.WXK_F10 and event.ShiftDown():
            self.show_selected_actions()
        elif (
            sys.platform == "darwin"
            and event.AltDown()
            and not event.ShiftDown()
            and not physical_control_down(event)
            and key in (ord("M"), ord("m"))
        ):
            self.show_selected_actions()
        elif physical_control_down(event) and event.ShiftDown() and key in (ord("T"), ord("t")):
            self.announce_time("total")
        elif physical_control_down(event) and event.ShiftDown() and key in (ord("E"), ord("e")):
            self.announce_time("elapsed")
        elif physical_control_down(event) and event.ShiftDown() and key in (ord("R"), ord("r")):
            self.announce_time("remaining")
        elif physical_control_down(event) and event.ShiftDown() and key in (ord("F"), ord("f")):
            self.refresh_current_view()
        elif (
            physical_control_down(event)
            and event.ShiftDown()
            and key in (ord("D"), ord("d"))
        ):
            self.choose_playback_device()
        elif physical_control_down(event) and event.ShiftDown() and key in (ord("I"), ord("i")):
            self.speak_current_track()
        elif physical_control_down(event) and event.ShiftDown() and key in (ord("U"), ord("u")):
            self.speak_up_next()
        elif (
            physical_control_down(event)
            and event.ShiftDown()
            and key in (ord("J"), ord("j"))
        ):
            self.choose_sleep_timer()
        elif physical_control_down(event) and key in (ord("J"), ord("j")):
            self.jump_to_time()
        elif physical_control_down(event) and key in (ord("Y"), ord("y")):
            self.show_lyrics()
        elif (
            physical_control_down(event)
            and event.ShiftDown()
            and key in (ord("N"), ord("n"))
        ):
            self.create_playlist()
        elif physical_control_down(event) and key in (ord("R"), ord("r")):
            self.cycle_repeat()
        elif physical_control_down(event) and key in (ord("S"), ord("s")):
            self.toggle_shuffle()
        elif (
            physical_control_down(event)
            and key in (ord("Q"), ord("q"))
            and focused_list
        ):
            self.queue_from_list(focused_list)
        elif (
            physical_control_down(event)
            and event.ShiftDown()
            and key in (ord("L"), ord("l"))
        ):
            self.toggle_like_current_track()
        elif (
            physical_control_down(event)
            and not event.ShiftDown()
            and key in (ord("L"), ord("l"))
            and focused_list
        ):
            self.toggle_like_item(focused_list.selected_item())
        elif (
            physical_control_down(event)
            and event.ShiftDown()
            and key in (ord("A"), ord("a"))
            and focused_list
        ):
            self.choose_playlist_for_selected()
        elif (
            physical_control_down(event)
            and event.ShiftDown()
            and key in (ord("B"), ord("b"))
        ):
            self.save_current_bookmark()
        elif (
            physical_control_down(event)
            and key in ENTER_KEY_CODES
            and focused_list
        ):
            self.open_selected_track_album(focused_list.selected_item())
        elif key in ENTER_KEY_CODES:
            if focused is self.search.categories:
                logger.debug("Frame routed Enter from search category")
                self.search.on_search()
            elif focused_list is self.search.results:
                logger.debug("Frame routed Enter to search result action")
                self.search.on_open()
            elif focused_list is self.liked.items:
                self.liked.on_open()
            elif focused_list is self.queue.items:
                self.queue.on_open()
            elif focused_list is self.playlists.items:
                self.playlists.on_open()
            elif focused_list is self.recently_played.items:
                self.recently_played.on_open()
            elif focused_list is self.audiobooks.items:
                self.audiobooks.on_open()
            elif focused_list is self.podcasts.items:
                self.podcasts.on_open()
            elif focused_list is self.saved_albums.items:
                self.saved_albums.on_open()
            elif focused_list is self.new_music.items:
                self.new_music.on_open()
            else:
                event.Skip()
        elif physical_control_down(event) and key in (ord("F"), ord("f")):
            self.discard_transient_open_album()
            self.notebook.SetSelection(0)
            self.search.focus_query()
        elif physical_control_down(event) and key == ord(","):
            self.on_preferences()
        elif (
            physical_control_down(event)
            and event.ShiftDown()
            and key in (ord("G"), ord("g"))
        ):
            self.open_concerts_window()
        elif (
            physical_control_down(event)
            and not event.ShiftDown()
            and key in (ord("B"), ord("b"))
        ):
            self.open_bookmarks_window()
        elif physical_control_down(event) and not event.ShiftDown() and (
            ord("1") <= key <= ord("9")
        ):
            page = key - ord("1")
            if page == 0:
                self.discard_transient_open_album()
            self.notebook.SetSelection(page)
            if page == 0:
                self.search.focus_query()
            elif page == 8:
                self.new_music.discovery_source.SetFocus()
        elif event.AltDown() and key == wx.WXK_LEFT:
            if self.notebook.GetSelection() == 0 and self.search.go_back():
                return
            event.Skip()
        else:
            event.Skip()

    def apply_global_hotkey_setting(self) -> None:
        self.unregister_global_hotkeys()
        failed = []
        labels = {
            action: ACTIONS_BY_ID[action].title
            for action, _ in GLOBAL_SHORTCUT_ACTIONS
        }
        for action, shortcut in self.global_shortcuts.items():
            hotkey_id = GLOBAL_SHORTCUT_IDS[action]
            try:
                registered = self.RegisterHotKey(
                    hotkey_id,
                    int(shortcut["modifiers"]),
                    int(shortcut["keycode"]),
                )
            except Exception:
                logger.exception("Could not register global hotkey %d", hotkey_id)
                registered = False
            if not registered:
                failed.append(
                    f"{labels[action]} ({shortcut_label(shortcut)})"
                )
            else:
                self.registered_hotkey_ids.append(hotkey_id)
        if failed:
            self.say(msg.shortcut_registration_failed(failed))

    def unregister_global_hotkeys(self) -> None:
        for hotkey_id in self.registered_hotkey_ids:
            try:
                self.UnregisterHotKey(hotkey_id)
            except Exception:
                logger.exception("Could not unregister global hotkey %d", hotkey_id)
        self.registered_hotkey_ids.clear()

    def on_global_hotkey(self, event: wx.HotkeyEvent) -> None:
        actions = {
            GLOBAL_SHORTCUT_IDS["previous_track"]: self.previous_track,
            GLOBAL_SHORTCUT_IDS["pause_resume"]: self.toggle_pause_resume,
            GLOBAL_SHORTCUT_IDS["next_track"]: self.next_track,
            GLOBAL_SHORTCUT_IDS["seek_backward"]: lambda: self.seek(-5000),
            GLOBAL_SHORTCUT_IDS["seek_forward"]: lambda: self.seek(5000),
            GLOBAL_SHORTCUT_IDS["volume_down"]: (
                lambda: self.adjust_volume(-5)
            ),
            GLOBAL_SHORTCUT_IDS["volume_up"]: (
                lambda: self.adjust_volume(5)
            ),
            GLOBAL_SHORTCUT_IDS["toggle_mute"]: self.toggle_mute,
            GLOBAL_SHORTCUT_IDS["like_current"]: (
                self.toggle_like_current_track
            ),
            GLOBAL_SHORTCUT_IDS["speak_current"]: self.speak_current_track,
            GLOBAL_SHORTCUT_IDS["speak_up_next"]: self.speak_up_next,
            GLOBAL_SHORTCUT_IDS["speak_total"]: (
                lambda: self.announce_time("total")
            ),
            GLOBAL_SHORTCUT_IDS["speak_elapsed"]: (
                lambda: self.announce_time("elapsed")
            ),
            GLOBAL_SHORTCUT_IDS["speak_remaining"]: (
                lambda: self.announce_time("remaining")
            ),
            GLOBAL_SHORTCUT_IDS["bookmark_current"]: (
                self.save_current_bookmark
            ),
            GLOBAL_SHORTCUT_IDS["toggle_shuffle"]: self.toggle_shuffle,
            GLOBAL_SHORTCUT_IDS["cycle_repeat"]: self.cycle_repeat,
        }
        action = actions.get(event.GetId())
        if action:
            action()

    def move_focus(self, *, backward: bool) -> None:
        """Move through every control in a predictable, wrapping tab loop."""
        page = self.notebook.GetSelection()
        if page == 0:
            controls: list[wx.Window] = [
                self.notebook,
                self.search.query,
                getattr(self.search, "tag", None),
                self.search.categories,
                self.search.search_button,
                self.search.results,
            ]
            artwork_button = getattr(
                self.search,
                "album_artwork_button",
                None,
            )
            if artwork_button and artwork_button.IsShown():
                controls.insert(-1, artwork_button)
        elif page == 1:
            controls = [
                self.notebook,
                self.liked.items,
                getattr(self.liked, "filter", None),
            ]
        elif page == 2:
            controls = [
                self.notebook,
                self.queue.items,
                getattr(self.queue, "filter", None),
            ]
        elif page == 3:
            controls = [
                self.notebook,
                self.playlists.items,
                getattr(self.playlists, "filter", None),
            ]
        elif page == 4:
            controls = [
                self.notebook,
                self.recently_played.items,
                getattr(self.recently_played, "filter", None),
            ]
        elif page == 5:
            controls = [
                self.notebook,
                self.audiobooks.items,
                getattr(self.audiobooks, "filter", None),
            ]
        elif page == 6:
            controls = [
                self.notebook,
                self.podcasts.browse_category,
                getattr(self.podcasts, "language_filter", None),
                self.podcasts.browse_button,
                self.podcasts.items,
                getattr(self.podcasts, "filter", None),
                getattr(self.podcasts, "listening_status_filter", None),
            ]
        elif page == 7:
            controls = [
                self.notebook,
                self.saved_albums.items,
                getattr(self.saved_albums, "filter", None),
            ]
        elif page == 8:
            controls = [
                self.notebook,
                self.new_music.discovery_source,
                getattr(self.new_music, "history_chart", None),
                getattr(self.new_music, "triple_j_countdown", None),
                getattr(self.new_music, "classic_100_countdown", None),
                getattr(self.new_music, "rn_books_countdown", None),
                getattr(self.new_music, "number_ones_country", None),
                self.new_music.release_types,
                getattr(self.new_music, "number_ones_order", None),
                getattr(self.new_music, "genre", None),
                getattr(self.new_music, "release_window", None),
                getattr(self.new_music, "keyword", None),
                self.new_music.chart_country,
                getattr(self.new_music, "chart_date", None),
                self.new_music.search_button,
                self.new_music.items,
                getattr(self.new_music, "filter", None),
            ]
        else:
            controls = [self.notebook]
        now_playing = getattr(self, "now_playing", None)
        if now_playing:
            controls.append(now_playing.items)
        # A disabled control silently swallows SetFocus, which would strand
        # Tab on the control before it, so skip anything unfocusable.
        controls = [
            control
            for control in controls
            if control is not None and focusable_control(control)
        ]

        focused = wx.Window.FindFocus()
        focused_list = item_list_ancestor(focused)
        if focused_list:
            focused = focused_list
        else:
            focused_radio_box = radio_box_ancestor(focused)
            if focused_radio_box:
                focused = focused_radio_box
        try:
            index = controls.index(focused)
        except ValueError:
            index = 0 if backward else -1
        step = -1 if backward else 1
        target = controls[(index + step) % len(controls)]
        logger.debug(
            "%s Tab focus from %s to %s",
            "Backward" if backward else "Forward",
            type(focused).__name__ if focused else "none",
            type(target).__name__,
        )
        target.SetFocus()
        if isinstance(target, (wx.TextCtrl, wx.ComboBox)):
            target.SelectAll()

    def using_local_player(self) -> bool:
        return bool(
            getattr(self, "player", None)
            and (
                self.current_player_state.get("direct_audio")
                or not self.remote_device_id
            )
        )

    def playback_position_ms(self, track_id: str) -> int | None:
        item = self.current_player_item
        if not item or item.id != track_id:
            return None
        position_ms = int(self.current_player_state.get("progress_ms") or 0)
        if self.current_player_state.get("is_playing"):
            elapsed_ms = int(
                (time.monotonic() - self.playback_state_updated_at) * 1000
            )
            position_ms += max(0, elapsed_ms)
        if item.duration_ms:
            position_ms = min(position_ms, item.duration_ms)
        return max(0, position_ms)

    def mark_cart_start(self) -> None:
        item = self.current_player_item
        if not item or item.kind != ItemKind.TRACK:
            self.say(tr("Play a song before marking a cart."))
            return
        self.request_cart_position(item, self.finish_mark_cart_start)

    def request_cart_position(
        self,
        item: SpotifyItem,
        callback: Callable[[SpotifyItem, int], None],
    ) -> None:
        """Ask the player for its position now instead of extrapolating.

        The extrapolated position trails the real one by however long the last
        state report took to arrive, so cart marks would land early.
        """
        estimate = self.playback_position_ms(item.id)

        def finish(state: object) -> None:
            position = estimate
            reported = self.item_from_player_state(state) if state else None
            if (
                isinstance(state, dict)
                and reported
                and reported.id == item.id
                and state.get("progress_ms") is not None
            ):
                position = max(0, int(state["progress_ms"]))
                if item.duration_ms:
                    position = min(position, item.duration_ms)
                logger.info(
                    "Cart position fresh_ms=%s estimated_ms=%s",
                    position,
                    estimate,
                )
            if position is not None:
                callback(item, position)

        if self.using_local_player():
            self.player.request_playback_state(finish)
        else:
            self.run_task(None, self.spotify.playback_state, finish)

    def finish_mark_cart_start(self, item: SpotifyItem, position: int) -> None:
        self.cart_start = (item, position)
        self.pending_cart = None
        self.say(tr("Cart start {position}.").format(position=self.format_time(position)))

    def mark_cart_end(self) -> None:
        item = self.current_player_item
        if not self.cart_start:
            self.say(tr("Mark the cart start with left bracket first."))
            return
        start_item, start_ms = self.cart_start
        if not item or item.id != start_item.id:
            self.cart_start = None
            self.say(tr("The song changed. Mark the cart start again."))
            return
        self.request_cart_position(
            item,
            lambda item, end_ms: self.finish_mark_cart_end(
                start_item, start_ms, end_ms
            ),
        )

    def finish_mark_cart_end(
        self,
        start_item: SpotifyItem,
        start_ms: int,
        end_ms: int,
    ) -> None:
        if end_ms <= start_ms:
            self.say(tr("The cart end must be after its start."))
            return
        self.pending_cart = (start_item, start_ms, end_ms)
        self.say(tr("Cart end {position}. Press Alt plus 1 through 9 to assign it.").format(position=self.format_time(end_ms)))

    def use_cart_number(self, number: int) -> None:
        if self.pending_cart:
            item, start_ms, end_ms = self.pending_cart
            self.carts[number] = Cart(
                number, item.id, item.uri, item.name, item.artist, item.album,
                item.duration_ms, start_ms, end_ms,
            )
            self.store.write("carts.json", dump_carts(self.carts))
            self.cart_start = None
            self.pending_cart = None
            self.say(tr("Cart {number} assigned to {name}, {duration}.").format(
                number=number, name=item.name,
                duration=self.format_time(end_ms - start_ms),
            ))
            return
        self.play_cart(number)

    def play_cart(self, number: int) -> None:
        cart = self.carts.get(number)
        if not cart:
            self.say(tr("Cart {number} is empty.").format(number=number))
            return
        self.playing_cart = cart
        self.playing_cart_armed = False
        self.cart_timer.Start(25)
        if (
            self.using_local_player()
            and self.player.ready
            and not getattr(self, "pending_transfer_device", None)
            and not getattr(self, "pending_resume", None)
        ):
            # Ask the player what it really has loaded: the song shown as
            # current may only be a remembered one, which nothing can seek.
            self.player.request_playback_state(
                lambda state: self.start_cart_playback(cart, state)
            )
        else:
            self.play_from_lyric(cart.item, cart.start_ms)
        if getattr(self, "announce_cart_names", True):
            self.say(
                tr("Playing cart {number}: {name}.").format(
                    number=number,
                    name=cart.name,
                )
            )

    def start_cart_playback(self, cart: Cart, state: dict) -> None:
        if self.playing_cart is not cart:
            return
        loaded = (state.get("item") or {}).get("id")
        if loaded == cart.track_id:
            # The song is already loaded, so seeking in place avoids the
            # Web API play round trip and track reload that add the lag.
            self.player.seek_and_play(cart.start_ms)
        else:
            self.play_from_lyric(cart.item, cart.start_ms)

    def on_cart_timer(self, event: wx.TimerEvent) -> None:
        cart = self.playing_cart
        if not cart:
            self.cart_timer.Stop()
            return
        position = self.playback_position_ms(cart.track_id)
        if position is None:
            return
        self.playing_cart_armed, should_stop = cart_cutoff_state(
            cart,
            position,
            self.playing_cart_armed,
        )
        if not should_stop:
            return
        if self.repeat_state == "track":
            self.playing_cart_armed = False
            self.loop_cart(cart)
            return
        if self.repeat_state == "context":
            next_number = next_cart_number(self.carts, cart.number)
            if next_number is not None:
                self.play_cart(next_number)
                return
        self.playing_cart = None
        self.cart_timer.Stop()
        self.pause_phrase_playback(cart.track_id)

    def loop_cart(self, cart: Cart) -> None:
        device_id = self.player_device_id()
        if not device_id:
            self.playing_cart = None
            self.cart_timer.Stop()
            return
        if self.using_local_player():
            self.player.seek_to(cart.start_ms)
            return
        self.run_task(
            None,
            lambda: self.spotify.seek_to(cart.start_ms, device_id),
            lambda position: logger.info(
                "Looped cart %d to %d ms",
                cart.number,
                position,
            ),
        )

    def manage_carts(self) -> None:
        dialog = wx.Dialog(
            self,
            title=tr("Manage Carts"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        panel = wx.Panel(dialog)
        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(wx.StaticText(panel, label=tr("Carts 1 through 9")), 0, wx.ALL, 8)
        choices = []
        for number in range(1, 10):
            cart = self.carts.get(number)
            description = (
                f"{cart.name} — {self.format_time(cart.start_ms)} to {self.format_time(cart.end_ms)}"
                if cart else tr("Empty")
            )
            choices.append(tr("Cart {number}: {description}").format(number=number, description=description))
        carts_list = wx.ListBox(panel, choices=choices)
        carts_list.SetSelection(0)
        layout.Add(carts_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        preview = wx.Button(panel, label=tr("&Preview"))
        clear = wx.Button(panel, label=tr("&Clear"))
        close = wx.Button(panel, wx.ID_CLOSE, tr("&Close"))
        for button in (preview, clear, close):
            buttons.Add(button, 0, wx.ALL, 5)
        layout.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 3)
        panel.SetSizer(layout)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        dialog.SetSizerAndFit(outer)
        dialog.SetMinSize((520, 330))

        def selected_number() -> int:
            return carts_list.GetSelection() + 1

        def clear_selected(event: wx.CommandEvent) -> None:
            number = selected_number()
            self.carts.pop(number, None)
            self.store.write("carts.json", dump_carts(self.carts))
            carts_list.SetString(number - 1, tr("Cart {number}: Empty").format(number=number))
            self.say(tr("Cart {number} cleared.").format(number=number))

        preview.Bind(wx.EVT_BUTTON, lambda event: self.play_cart(selected_number()))
        clear.Bind(wx.EVT_BUTTON, clear_selected)
        close.Bind(wx.EVT_BUTTON, lambda event: dialog.EndModal(wx.ID_CLOSE))
        carts_list.Bind(wx.EVT_LISTBOX_DCLICK, lambda event: self.play_cart(selected_number()))
        dialog.ShowModal()
        dialog.Destroy()

    def current_track_is_paused(self, track_id: str) -> bool:
        live_item = self.current_player_state.get("item") or {}
        return bool(
            live_item.get("id") == track_id
            and not self.current_player_state.get("is_playing")
        )

    def choose_sleep_timer(self) -> None:
        choices = [
            tr("After current track"),
            tr("After 15 minutes"),
            tr("After 30 minutes"),
            tr("After 60 minutes"),
            tr("Cancel sleep timer"),
        ]
        dialog = wx.SingleChoiceDialog(
            self,
            msg.SLEEP_TIMER_PROMPT,
            tr("Sleep timer"),
            choices,
        )
        dialog.SetSelection(0)
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        selection = dialog.GetSelection()
        dialog.Destroy()
        if selection == 0:
            self.set_sleep_after_current_track()
        elif selection == 1:
            self.set_sleep_timer(15)
        elif selection == 2:
            self.set_sleep_timer(30)
        elif selection == 3:
            self.set_sleep_timer(60)
        else:
            self.cancel_sleep_timer()

    def set_sleep_after_current_track(self) -> None:
        if not self.current_player_item:
            self.say(msg.NO_CURRENT_TRACK)
            return
        self.sleep_timer.Stop()
        self.sleep_after_track_id = self.current_player_item.id
        self.synchronize_sleep_after_track(self.current_player_state)
        self.say(msg.SLEEP_END_OF_TRACK)

    def synchronize_sleep_after_track(self, state: dict) -> None:
        if not self.sleep_after_track_id:
            return
        item = self.item_from_player_state(state)
        if not item or item.id != self.sleep_after_track_id:
            self.sleep_timer.Stop()
            return
        if not state.get("is_playing"):
            self.sleep_timer.Stop()
            return
        duration_ms = int((state.get("item") or {}).get("duration_ms") or 0)
        progress_ms = int(state.get("progress_ms") or 0)
        if duration_ms <= 0:
            self.sleep_timer.Stop()
            return
        self.sleep_timer.StartOnce(max(1, duration_ms - progress_ms))

    def on_sleep_timer(self) -> None:
        if not self.sleep_after_track_id:
            self.expire_sleep_timer()
            return
        if self.using_local_player():
            self.player.request_playback_state(self.finish_sleep_deadline)
            return
        self.run_task(
            None,
            self.spotify.playback_state,
            self.finish_sleep_deadline,
        )

    def finish_sleep_deadline(self, state: dict) -> None:
        item = self.item_from_player_state(state)
        if not item or item.id != self.sleep_after_track_id:
            self.expire_sleep_timer()
            return
        duration_ms = int((state.get("item") or {}).get("duration_ms") or 0)
        progress_ms = int(state.get("progress_ms") or 0)
        remaining_ms = max(0, duration_ms - progress_ms)
        if not state.get("is_playing"):
            self.sleep_timer.Stop()
        elif remaining_ms > 1_000:
            self.sleep_timer.StartOnce(remaining_ms)
        else:
            self.expire_sleep_timer()

    def set_sleep_timer(self, minutes: int) -> None:
        self.sleep_after_track_id = None
        if self.remote_device_id:
            self.remote_refresh_timer.Start(10_000)
        self.sleep_timer.StartOnce(minutes * 60 * 1000)
        self.say(msg.sleep_minutes(minutes))

    def cancel_sleep_timer(self) -> None:
        active = self.sleep_timer.IsRunning() or bool(
            self.sleep_after_track_id
        )
        self.sleep_timer.Stop()
        self.sleep_after_track_id = None
        if self.remote_device_id:
            self.remote_refresh_timer.Start(10_000)
        self.say(
            msg.SLEEP_CANCELLED
            if active
            else msg.NO_SLEEP_TIMER
        )

    def expire_sleep_timer(self) -> None:
        self.sleep_timer.Stop()
        self.sleep_after_track_id = None
        if self.remote_device_id:
            self.remote_refresh_timer.Start(10_000)
        device_id = self.player_device_id()
        if not device_id:
            return
        self.run_task(
            None,
            lambda: self.spotify.pause_playback(device_id),
            lambda result: self.say(msg.SLEEP_STOPPED),
        )

    def choose_playback_device(self) -> None:
        self.run_task(
            msg.GETTING_DEVICES,
            self.spotify.available_devices,
            self.show_playback_devices,
        )

    def show_playback_devices(self, devices: list[dict]) -> None:
        outputs = self.sound_card_choices()
        labels = []
        selected = 0
        for index, device in enumerate(devices):
            parts = [
                str(device.get("name") or tr("Unnamed device")),
                tr(
                    DEVICE_TYPE_LABELS.get(
                        str(device.get("type")), str(device.get("type"))
                    )
                )
                if device.get("type")
                else tr("device"),
            ]
            if device.get("is_active"):
                parts.append(tr("active"))
                selected = index
            volume = device.get("volume_percent")
            if volume is not None:
                parts.append(tr(
                    "volume {volume} percent"
                ).format(volume=volume))
            labels.append(", ".join(parts))
        chosen_output = (self.store.read("settings.json", {}) or {}).get(
            "audio_output_device"
        )
        for output in outputs:
            label = tr("Sound card: {name}").format(name=output.name)
            if output.id == (chosen_output or ""):
                label = tr("{label}, current").format(label=label)
            labels.append(label)
        labels.append(tr("Refresh device list"))
        dialog = wx.SingleChoiceDialog(
            self,
            msg.DEVICE_SELECTION_PROMPT,
            tr("Choose playback device - BlindSpot"),
            labels,
        )
        dialog.SetSelection(selected)
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        selection = dialog.GetSelection()
        dialog.Destroy()
        self.handle_playback_device_selection(devices, selection, outputs)

    def handle_playback_device_selection(
        self,
        devices: list[dict],
        selection: int,
        outputs: list[audio_devices.AudioOutput] | None = None,
    ) -> None:
        outputs = outputs or []
        if selection < len(devices):
            self.choose_playback_device_action(devices[selection])
        elif selection < len(devices) + len(outputs):
            self.choose_sound_card(outputs[selection - len(devices)])
        else:
            self.choose_playback_device()

    def sound_card_choices(self) -> list[audio_devices.AudioOutput]:
        """List Windows sound cards, led by a choice to follow the default."""
        if not audio_devices.AVAILABLE:
            return []
        try:
            outputs = audio_devices.output_devices()
        except (OSError, audio_devices.AudioDeviceError):
            logger.exception("Could not list Windows sound cards")
            return []
        return [audio_devices.AudioOutput("", tr("Windows default"), True), *outputs]

    def choose_sound_card(self, output: audio_devices.AudioOutput) -> None:
        settings = self.store.read("settings.json", {}) or {}
        settings["audio_output_device"] = output.id
        self.store.write("settings.json", settings)
        self.audio_output_applied = False
        self.apply_audio_output()
        self.say(tr("BlindSpot plays through {name}.").format(name=output.name))

    def apply_audio_output(self) -> None:
        """Route BlindSpot's audio to the sound card chosen in the device list.

        Windows only accepts processes that have opened audio, and WebView2
        starts its audio process when sound first plays, so this runs again
        at the start of playback until it succeeds.
        """
        device_id = (self.store.read("settings.json", {}) or {}).get(
            "audio_output_device"
        )
        if device_id is None or not audio_devices.AVAILABLE:
            self.audio_output_applied = True
            return
        try:
            routed = audio_devices.route_process_tree(str(device_id))
        except (OSError, audio_devices.AudioDeviceError):
            logger.exception("Could not route audio to the chosen sound card")
            self.audio_output_applied = True
            return
        self.audio_output_applied = routed > 0

    def choose_playback_device_action(self, device: dict) -> None:
        choices = [
            tr("Continue playing on this device"),
            tr("Move to this device without playing"),
            tr("Force transfer on next play"),
        ]
        dialog = wx.SingleChoiceDialog(
            self,
            tr("Choose what BlindSpot should do with this device."),
            tr("Connected device action - BlindSpot"),
            choices,
        )
        dialog.SetSelection(0)
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        action = dialog.GetSelection()
        dialog.Destroy()
        if action == 2:
            self.target_playback_device(device)
            return
        device_id = str(device["id"])
        name = str(device.get("name") or tr("device"))
        if action == 1:
            self.run_task(
                msg.transferring_to(name),
                lambda: self.spotify.transfer_playback_paused(device_id),
                lambda result: self.finish_transfer_playback(
                    device,
                    playing=False,
                ),
            )
            return
        self.run_task(
            msg.transferring_to(name),
            lambda: self.spotify.transfer_playback(device_id, play=True),
            lambda result: self.finish_transfer_playback(device),
        )

    def target_playback_device(self, device: dict) -> None:
        self.pending_transfer_device = device
        self.say(
            msg.device_targeted(str(device.get("name") or tr("device")))
        )

    def set_remote_playback_device(self, device: dict) -> None:
        device_id = str(device["id"])
        local_device_id = self.player.device_id if self.player else None
        if local_device_id and device_id == local_device_id:
            self.remote_device_id = None
            self.remote_device_name = ""
            self.remote_supports_volume = None
            self.remote_refresh_timer.Stop()
        else:
            self.remote_device_id = device_id
            self.remote_device_name = str(device.get("name") or tr("device"))
            self.remote_supports_volume = bool(
                device.get("supports_volume", True)
            )

    def finish_transfer_playback(
        self,
        device: dict,
        *,
        playing: bool = True,
    ) -> None:
        self.shuffle_enabled = None
        self.repeat_state = None
        self.pending_transfer_device = None
        self.set_remote_playback_device(device)
        if self.remote_device_id:
            self.remote_refresh_timer.Start(10_000)
            wx.CallLater(750, self.refresh_remote_playback)
        name = str(device.get("name") or tr("device"))
        self.say(
            msg.playing_on(name)
            if playing
            else msg.moved_without_playing(name)
        )

    def refresh_remote_playback(self) -> None:
        if not self.remote_device_id or self.remote_refresh_pending:
            return
        self.remote_refresh_pending = True

        def refresh() -> None:
            try:
                state = self.spotify.playback_state()
            except Exception:
                logger.exception("Could not refresh remote playback state")
                wx.CallAfter(self.finish_remote_refresh, None)
            else:
                wx.CallAfter(self.finish_remote_refresh, state)

        threading.Thread(
            target=refresh,
            name="BlindSpotRemotePlayback",
            daemon=True,
        ).start()

    def finish_remote_refresh(self, state: dict | None) -> None:
        self.remote_refresh_pending = False
        if state and self.remote_device_id:
            active_device = state.get("device") or {}
            active_id = active_device.get("id")
            local_id = self.player.device_id if self.player else None
            if active_id and local_id and active_id == local_id:
                self.remote_device_id = None
                self.remote_device_name = ""
                self.remote_supports_volume = None
                self.remote_refresh_timer.Stop()
                return
            if active_id:
                self.remote_device_id = str(active_id)
                self.remote_device_name = str(
                    active_device.get("name") or self.remote_device_name
                )
                self.remote_supports_volume = bool(
                    active_device.get("supports_volume", True)
                )
            self.apply_playback_update(state)

    def play(
        self,
        item: SpotifyItem,
        *,
        announce: bool = False,
    ) -> None:
        if getattr(item, "raw", {}).get("audio_url"):
            self.play_direct_audio(item, 0, announce=announce)
            return
        self.suppress_track_announcement_id = item.id
        pending_transfer = getattr(self, "pending_transfer_device", None)
        if pending_transfer:
            device_id = str(pending_transfer["id"])
        elif self.remote_device_id:
            device_id = self.remote_device_id
        elif self.player:
            self.player.activate()
            if not self.player.ready:
                self.pending_play_item = item
                message = (
                    msg.player_starting(item.name)
                    if announce
                    else msg.PLAYER_STARTING
                )
                self.say(message)
                self.player.provide_token()
                return
            device_id = self.player.device_id
        else:
            device_id = None
        self.run_task(
            msg.playing(item.name) if announce else None,
            lambda: self.spotify.play(item, device_id=device_id),
            lambda result: self.on_play_started(
                item,
                standalone=item.playable,
            ),
        )

    def play_items(
        self,
        items: list[SpotifyItem],
        *,
        started_message: str = "",
        after_started: Callable[[], None] | None = None,
        disable_repeat: bool = False,
    ) -> None:
        playable = [item for item in items if item.playable and item.uri]
        if not playable:
            self.say(msg.NO_PLAYABLE_TRACKS)
            return
        first = playable[0]
        self.suppress_track_announcement_id = first.id
        pending_transfer = getattr(self, "pending_transfer_device", None)
        if pending_transfer:
            device_id = str(pending_transfer["id"])
        elif self.remote_device_id:
            device_id = self.remote_device_id
        elif self.player:
            self.player.activate()
            if not self.player.ready:
                self.pending_play_items = list(playable)
                self.pending_play_items_message = started_message
                self.pending_play_items_callback = after_started
                self.pending_play_items_disable_repeat = disable_repeat
                self.say(msg.player_starting(first.name))
                self.player.provide_token()
                return
            device_id = self.player.device_id
        else:
            device_id = None
        def start() -> None:
            if disable_repeat and device_id:
                self.spotify.set_repeat("off", device_id)
            self.spotify.play_items(playable, device_id=device_id)

        self.run_task(
            msg.playing(first.name),
            start,
            lambda result: self.finish_play_items(
                first,
                started_message,
                after_started,
                disable_repeat,
            ),
        )

    def finish_play_items(
        self,
        first: SpotifyItem,
        message: str = "",
        after_started: Callable[[], None] | None = None,
        repeat_was_disabled: bool = False,
    ) -> None:
        self.on_play_started(first, standalone=False)
        if repeat_was_disabled:
            self.repeat_state = "off"
        if message:
            self.say(message)
        if after_started:
            after_started()

    def play_from_lyric(
        self,
        item: SpotifyItem,
        position_ms: int,
    ) -> None:
        if getattr(item, "raw", {}).get("audio_url"):
            self.play_direct_audio(item, position_ms)
            return
        self.suppress_track_announcement_id = item.id
        pending_transfer = getattr(self, "pending_transfer_device", None)
        if pending_transfer:
            device_id = str(pending_transfer["id"])
        elif self.remote_device_id:
            device_id = self.remote_device_id
        elif self.player:
            self.player.activate()
            if not self.player.ready:
                self.pending_play_item = item
                self.pending_play_context = None
                self.pending_play_position_ms = position_ms
                self.say(msg.player_starting(item.name))
                self.player.provide_token()
                return
            device_id = self.player.device_id
        else:
            self.say(msg.PLAYER_NOT_READY)
            return
        self.lyric_start_item_id = item.id
        self.pending_lyric_seek = (item.id, position_ms)
        self.run_task(
            None,
            lambda: self.play_at_with_entitlement_message(
                item,
                position_ms,
                device_id,
            ),
            lambda result: self.finish_lyric_start(item),
            failure=self.cancel_lyric_start,
        )

    def play_at_with_entitlement_message(
        self,
        item: SpotifyItem,
        position_ms: int,
        device_id: str,
    ) -> None:
        try:
            self.spotify.play_at(item, position_ms, device_id)
        except SpotifyError as error:
            message = str(error)
            if (
                item.kind == ItemKind.CHAPTER
                and ("403" in message or "payment" in message.lower())
            ):
                raise SpotifyError(msg.AUDIOBOOK_PLAYBACK_UNAVAILABLE) from error
            raise

    def finish_lyric_start(self, item: SpotifyItem) -> None:
        self.on_play_started(item, standalone=True)

    def cancel_lyric_start(self) -> None:
        self.lyric_start_item_id = None
        self.pending_lyric_seek = None

    def play_in_context(
        self,
        context: SpotifyItem,
        item: SpotifyItem,
    ) -> None:
        self.suppress_track_announcement_id = item.id
        pending_transfer = getattr(self, "pending_transfer_device", None)
        if pending_transfer:
            device_id = str(pending_transfer["id"])
        elif self.remote_device_id:
            device_id = self.remote_device_id
        elif self.player:
            self.player.activate()
            if not self.player.ready:
                self.pending_play_item = item
                self.pending_play_context = context
                self.say(msg.player_starting(item.name))
                self.player.provide_token()
                return
            device_id = self.player.device_id
        else:
            self.say(msg.PLAYER_NOT_READY)
            return
        self.run_task(
            msg.playing(item.name),
            lambda: self.spotify.play_at(
                item,
                0,
                device_id,
                context.uri,
            ),
            lambda result: self.on_play_started(item, standalone=False),
        )

    def on_play_started(
        self,
        item: SpotifyItem,
        *,
        standalone: bool,
    ) -> None:
        pending_transfer = getattr(self, "pending_transfer_device", None)
        if pending_transfer:
            device = pending_transfer
            self.pending_transfer_device = None
            self.set_remote_playback_device(device)
            if self.remote_device_id:
                self.remote_refresh_timer.Start(10_000)
        self.standalone_player_item_id = item.id if standalone else None
        current = self.current_player_item
        if current and current.id == item.id:
            self.current_player_state["standalone"] = standalone
            if self.resume_mode != "none":
                self.store.write(
                    "playback.json",
                    playback_state_for_resume(
                        self.current_player_state,
                        self.resume_mode,
                    ),
                )
        logger.info("Playback started kind=%s id=%s name=%r", item.kind, item.id, item.name)
        if self.deferred_queue_start_item is item:
            index = next(
                (
                    index
                    for index, queued_item in enumerate(
                        self.deferred_queue_items
                    )
                    if queued_item is item
                ),
                None,
            )
            if index is not None:
                del self.deferred_queue_items[index]
            self.deferred_queue_start_item = None
        self.flush_deferred_queue()

    def play_audiobook_chapter(self, item: SpotifyItem) -> None:
        position_ms = int(item.raw.get("resume_position_ms") or 0)
        if item.raw.get("resume_point", {}).get("fully_played"):
            position_ms = 0
        self.play_from_lyric(item, position_ms)

    def play_direct_audio(
        self,
        item: SpotifyItem,
        position_ms: int = 0,
        *,
        announce: bool = True,
    ) -> None:
        if not self.player:
            self.say(msg.PLAYER_NOT_READY)
            return
        audio_url = str(item.raw.get("audio_url") or "")
        if not audio_url:
            self.say(tr("Direct audio is unavailable."))
            return
        self.suppress_track_announcement_id = item.id
        value = {
            "id": item.id,
            "uri": item.uri,
            "type": "episode",
            "name": item.name,
            "duration_ms": item.duration_ms,
            "artists": ([{"name": item.artist}] if item.artist else []),
            "album": {"name": item.album},
            "audio_url": audio_url,
            "feed_url": str(item.raw.get("feed_url") or ""),
            "transcript_url": str(item.raw.get("transcript_url") or ""),
            "transcript_type": str(item.raw.get("transcript_type") or ""),
            "description": str(item.raw.get("description") or ""),
            "local_audio_path": str(item.raw.get("local_audio_path") or ""),
            "rss_subscription": bool(item.raw.get("rss_subscription")),
        }
        self.player.play_direct(audio_url, value, position_ms)
        if announce:
            self.say(msg.playing(item.name))

    def play_playable_item(self, item: SpotifyItem) -> None:
        if self.resolve_then([item], lambda: self.play_playable_item(item)):
            return
        if item.kind in {ItemKind.EPISODE, ItemKind.CHAPTER}:
            position_ms = int(item.raw.get("resume_position_ms") or 0)
            if item.raw.get("resume_point", {}).get("fully_played"):
                position_ms = 0
            if position_ms or item.kind == ItemKind.CHAPTER:
                self.play_from_lyric(item, position_ms)
                return
        self.play(item)

    def show_item_description(self, item: SpotifyItem) -> None:
        description = str(item.raw.get("description") or "").strip()
        if not description:
            self.say(msg.NO_DESCRIPTION)
            return
        wx.MessageBox(
            description,
            tr("{name} description").format(name=item.name),
            wx.OK | wx.ICON_INFORMATION,
            self,
        )

    def show_playlist_information(self, item: SpotifyItem) -> None:
        owner = item.raw.get("owner") or {}
        owner_name = str(
            owner.get("display_name")
            or owner.get("name")
            or owner.get("id")
            or ""
        )
        wx.MessageBox(
            msg.playlist_information(
                owner_name,
                item.total,
                item.raw.get("public"),
                bool(item.raw.get("collaborative")),
                str(item.raw.get("description") or "").strip(),
            ),
            tr("{name} information").format(name=item.name),
            wx.OK | wx.ICON_INFORMATION,
            self,
        )

    def current_selected_item(self) -> SpotifyItem | None:
        now_playing = getattr(self, "now_playing", None)
        if now_playing:
            focused_list = item_list_ancestor(wx.Window.FindFocus())
            if focused_list is now_playing.items:
                return now_playing.selected_item()
        page = self.notebook.GetSelection()
        if page == 0:
            return self.search.results.selected_item()
        if page == 1:
            return self.liked.items.selected_item()
        if page == 2:
            return self.queue.items.selected_item()
        if page == 3:
            return self.playlists.items.selected_item()
        if page == 4:
            return self.recently_played.items.selected_item()
        if page == 5:
            return self.audiobooks.items.selected_item()
        if page == 6:
            return self.podcasts.items.selected_item()
        if page == 7:
            return self.saved_albums.items.selected_item()
        if page == 8:
            return self.new_music.items.selected_item()
        return None

    def current_item_list(self) -> ItemList | None:
        focused = item_list_ancestor(wx.Window.FindFocus())
        if focused:
            return focused
        page = self.notebook.GetSelection()
        panel_names = {
            0: ("search", "results"),
            1: ("liked", "items"),
            2: ("queue", "items"),
            3: ("playlists", "items"),
            4: ("recently_played", "items"),
            5: ("audiobooks", "items"),
            6: ("podcasts", "items"),
            7: ("saved_albums", "items"),
            8: ("new_music", "items"),
        }
        names = panel_names.get(page)
        if not names:
            return None
        panel_name, list_name = names
        return getattr(getattr(self, panel_name), list_name, None)

    def select_all_in_current_list(
        self,
        item_list: ItemList | None = None,
    ) -> None:
        notebook = getattr(self, "notebook", None)
        new_music = getattr(self, "new_music", None)
        if (
            notebook is not None
            and notebook.GetSelection() == 8
            and getattr(new_music, "result_mode", "releases") != "chart"
        ):
            return
        target = item_list or self.current_item_list()
        if not target:
            return
        target.select_all_items()
        self.say(msg.selected_count(len(target.GetSelections())))

    def play_focused_or_remembered(self, focused_list: ItemList | None) -> None:
        """F4: play the focused item, else the song remembered from last time."""
        if focused_list:
            self.play_selected()
        elif getattr(self, "pending_resume", None):
            self.toggle_playback()
        else:
            self.say(msg.NO_SONG_SELECTED)

    def play_selected(self) -> None:
        item = self.current_selected_item()
        if not item:
            self.say(msg.NO_ITEM_SELECTED)
            return
        if item.kind == ItemKind.HEADING:
            self.say(msg.SELECT_PLAYABLE_ITEM)
            return
        current_list = getattr(self, "current_item_list", lambda: None)()
        chosen = (current_list.marked_items() if current_list else []) or [item]
        if self.resolve_then(chosen, lambda: self.play_selected()):
            return
        page = self.notebook.GetSelection()
        item_list = getattr(self, "current_item_list", lambda: None)()
        selected = [
            selected_item
            for selected_item in (
                item_list.marked_items() if item_list else []
            )
            if selected_item.playable and selected_item.uri
        ]
        if len(selected) > 1:
            self.play_items(selected)
            return
        if (
            page == 2
            and any(
                queued_item is item
                for queued_item in self.deferred_queue_items
            )
        ):
            self.deferred_queue_start_item = item
        if (
            page == 5
            and item.kind == ItemKind.CHAPTER
        ):
            self.play_audiobook_chapter(item)
            return
        if (
            page == 6
            and item.kind == ItemKind.EPISODE
        ):
            self.play_playable_item(item)
            return
        if item.container:
            self.play(item, announce=False)
            return
        if page == 0:
            state = self.search.history.current
            if (
                item.kind == ItemKind.TRACK
                and state.parent_kind == ItemKind.ALBUM
                and state.parent_id
            ):
                album = SpotifyItem(
                    state.parent_id,
                    ItemKind.ALBUM,
                    state.title,
                    uri=f"spotify:album:{state.parent_id}",
                )
                self.play_in_context(album, item)
                return
        if (
            page == 3
            and self.playlists.current_playlist
        ):
            filtered_items = self.playlists.filtered_playback_items(item)
            if filtered_items:
                self.play_items(filtered_items)
                return
            self.play_in_context(self.playlists.current_playlist, item)
            return
        self.play_playable_item(item)

    def player_device_id(self) -> str | None:
        if (
            getattr(self, "player", None)
            and getattr(self, "current_player_state", {}).get("direct_audio")
        ):
            return "direct-audio"
        if self.remote_device_id:
            return self.remote_device_id
        if not self.player or not self.player.ready:
            self.say(msg.PLAYER_NOT_READY)
            return None
        self.player.activate()
        return self.player.device_id

    def toggle_playback(self) -> None:
        if self.pending_resume and self.pending_resume[0].id.startswith(
            "local-audio:"
        ):
            item, position_ms, _context_uri = self.pending_resume
            self.pending_resume = None
            path_value = str(item.raw.get("local_audio_path") or "")
            path = Path(path_value) if path_value else None
            if path and path.is_file():
                self.use_transcript_audio(item, path)
                self.play_direct_audio(item, position_ms, announce=False)
            else:
                self.say(
                    tr(
                        "Select the local audio file again from File, "
                        "Transcribe local audio."
                    )
                )
            return
        device_id = self.player_device_id()
        if not device_id:
            return
        if self.pending_resume:
            item, position_ms, context_uri = self.pending_resume
            self.pending_resume = None
            self.run_task(
                None,
                lambda: self.spotify.play_at(
                    item,
                    position_ms,
                    device_id,
                    context_uri,
                ),
                lambda result: self.on_play_started(
                    item,
                    standalone=not bool(context_uri),
                ),
            )
            return
        if self.using_local_player():
            self.player.toggle_playback()
            return
        self.run_task(
            None,
            lambda: self.spotify.toggle_playback(device_id),
            lambda playing: logger.info(
                "Playback toggled; playing=%s",
                playing,
            ),
        )

    def toggle_pause_resume(self) -> None:
        if not self.current_player_item:
            self.say(msg.NOTHING_PLAYING)
            return
        self.toggle_playback()

    def resume_from_lyric(self, track_id: str, position_ms: int) -> None:
        if not self.current_track_is_paused(track_id):
            self.toggle_pause_resume()
            return
        device_id = self.player_device_id()
        if not device_id:
            return
        if self.using_local_player():
            self.player.seek_to(position_ms)
            self.toggle_playback()
            return
        self.run_task(
            None,
            lambda: self.spotify.seek_to(position_ms, device_id),
            lambda position: self.toggle_playback(),
        )

    def pause_phrase_playback(self, track_id: str) -> None:
        item = self.current_player_item
        if not item or item.id != track_id:
            return
        device_id = self.player_device_id()
        if not device_id:
            return
        if self.using_local_player():
            self.player.pause()
            return
        self.run_task(
            None,
            lambda: self.spotify.pause_playback(device_id),
            lambda result: logger.info("Phrase playback paused"),
        )

    def seek(self, delta_ms: int) -> None:
        device_id = self.player_device_id()
        if not device_id:
            return
        if self.using_local_player():
            self.player.seek_relative(delta_ms)
            return
        self.run_task(
            None,
            lambda: self.spotify.seek_relative(delta_ms, device_id),
            lambda position: logger.info("Seeked to %d ms", position),
        )

    def adjust_volume(self, delta_percent: int) -> None:
        if self.remote_device_id and self.remote_supports_volume is False:
            self.say(msg.unsupported_volume(self.remote_device_name))
            return
        device_id = self.player_device_id()
        if not device_id:
            return
        if self.using_local_player():
            self.player.adjust_volume(
                delta_percent,
                self.finish_adjust_volume,
            )
            return
        self.run_task(
            None,
            lambda: self.spotify.adjust_volume(delta_percent, device_id),
            self.finish_adjust_volume,
        )

    def finish_adjust_volume(self, volume: int | None) -> None:
        if volume is None:
            return
        volume = min(100, max(0, int(volume)))
        self.playback_volume_percent = volume
        if volume > 0:
            self.volume_before_mute_percent = volume
        settings = self.store.read("settings.json", {}) or {}
        settings["playback_volume_percent"] = volume
        self.store.write("settings.json", settings)
        if getattr(self, "announce_volume_changes", True):
            self.say(f"{volume}%.")

    def toggle_mute(self) -> None:
        if self.remote_device_id and self.remote_supports_volume is False:
            self.say(msg.unsupported_volume(self.remote_device_name))
            return
        device_id = self.player_device_id()
        if not device_id:
            return
        if self.using_local_player():
            self.player.toggle_mute(self.finish_toggle_mute)
            return
        restore_volume = self.volume_before_mute_percent

        def change_volume() -> tuple[int, int]:
            state = self.spotify.playback_state()
            device = state.get("device") if state else None
            current = device.get("volume_percent") if device else None
            if current is None:
                raise SpotifyError(msg.CURRENT_VOLUME_UNAVAILABLE)
            current = int(current)
            target = 0 if current > 0 else restore_volume
            self.spotify.set_volume(target, device_id)
            return current, target

        self.run_task(None, change_volume, self.finish_remote_toggle_mute)

    def finish_remote_toggle_mute(self, result: tuple[int, int]) -> None:
        previous, volume = result
        if volume == 0 and previous > 0:
            self.volume_before_mute_percent = previous
        self.finish_toggle_mute(volume)

    def finish_toggle_mute(self, volume: int | None) -> None:
        if volume is None:
            return
        if volume == 0:
            self.say(msg.MUTED)
        else:
            self.say(msg.UNMUTED)

    def announce_time(self, part: str) -> None:
        device_id = self.player_device_id()
        if not device_id:
            return
        if self.using_local_player():
            self.player.request_playback_state(
                lambda state: self.finish_announce_time(state, part)
            )
            return
        self.run_task(
            None,
            self.spotify.playback_state,
            lambda state: self.finish_announce_time(state, part),
        )

    def finish_announce_time(self, state: dict, part: str) -> None:
        item = state.get("item") or {}
        duration_ms = int(item.get("duration_ms") or 0)
        progress_ms = int(state.get("progress_ms") or 0)
        if not duration_ms:
            self.say(msg.NO_TRACK)
            return
        values = {
            "total": duration_ms,
            "elapsed": progress_ms,
            "remaining": max(0, duration_ms - progress_ms),
        }
        self.say(f"{self.format_time(values[part])}.")

    def speak_current_track(self) -> None:
        if self.using_local_player():
            self.player.request_playback_state(self.finish_speak_current_track)
            return
        self.run_task(
            None,
            self.spotify.playback,
            lambda item: self.say(
                item.accessible_label()
                if item
                else msg.NOTHING_CURRENTLY_PLAYING
            ),
        )

    def finish_speak_current_track(self, state: dict) -> None:
        item = self.item_from_player_state(state)
        self.say(
            item.accessible_label()
            if item
            else msg.NOTHING_CURRENTLY_PLAYING
        )

    def speak_up_next(self) -> None:
        self.run_task(
            None,
            self.spotify.next_queued,
            lambda item: self.say(
                item.accessible_label()
                if item
                else msg.QUEUE_EMPTY
            ),
        )

    def show_lyrics(self) -> None:
        focused = wx.Window.FindFocus()
        focused_list = item_list_ancestor(focused)
        focused_item = (
            focused_list.selected_item()
            if focused_list
            else None
        )
        item = (
            focused_item
            if focused_item and focused_item.playable
            else self.current_player_item
        )
        if not item:
            self.say(msg.NOTHING_PLAYING)
            return
        self.show_lyrics_for_item(item)

    def show_lyrics_for_item(self, item: SpotifyItem) -> None:
        self.run_task(
            msg.GETTING_LYRICS,
            lambda: self.lyrics_for_item(item),
            lambda lyrics: self.finish_show_lyrics(lyrics, item),
        )

    def finish_show_lyrics(
        self,
        lyrics: Lyrics,
        item: SpotifyItem,
    ) -> None:
        if lyrics.instrumental:
            self.say(msg.INSTRUMENTAL_TRACK)
            return
        dialog = LyricsDialog(self, lyrics, item)
        dialog.ShowModal()
        dialog.Destroy()

    def toggle_shuffle(self) -> None:
        device_id = self.player_device_id()
        if not device_id:
            return
        if self.shuffle_enabled is None:
            operation = lambda: self.spotify.toggle_shuffle(device_id)
        else:
            enabled = not self.shuffle_enabled
            operation = lambda: self.spotify.set_shuffle(enabled, device_id)

        def completed(enabled: bool) -> None:
            self.shuffle_enabled = enabled
            self.say(msg.SHUFFLE_ON if enabled else msg.SHUFFLE_OFF)

        self.run_task(
            None,
            operation,
            completed,
        )

    def cycle_repeat(self) -> None:
        device_id = self.player_device_id()
        if not device_id:
            return
        labels = {
            "off": msg.REPEAT_OFF,
            "context": msg.REPEAT_ALL,
            "track": msg.REPEAT_ONE,
        }
        if self.repeat_state is None:
            operation = lambda: self.spotify.cycle_repeat(device_id)
        else:
            state = {
                "off": "context",
                "context": "track",
                "track": "off",
            }[self.repeat_state]
            operation = lambda: self.spotify.set_repeat(state, device_id)

        def completed(state: str) -> None:
            self.repeat_state = state
            self.say(labels[state])

        self.run_task(
            None,
            operation,
            completed,
        )

    def jump_lyric_section(self, direction: int) -> None:
        item = self.current_player_item
        if not item or item.kind != ItemKind.TRACK:
            self.say(msg.NOTHING_PLAYING)
            return
        cached = self.lyric_sections
        if cached and cached[0] == item.id:
            self.finish_jump_lyric_section(item, cached[1], direction)
            return

        def loaded(lyrics: Lyrics) -> None:
            starts = section_starts(
                lyrics.synced_lines,
                lyrics.synced_breaks,
                lyrics.text,
            )
            self.lyric_sections = (item.id, starts)
            current = self.current_player_item
            if current and current.id == item.id:
                self.finish_jump_lyric_section(item, starts, direction)

        recent = getattr(self, "recent_lyrics", None)
        if recent and recent[0] == item.id:
            loaded(recent[1])
            return

        self.run_task(
            msg.GETTING_LYRICS,
            lambda: self.lyrics_for_item(item),
            loaded,
        )

    def finish_jump_lyric_section(
        self,
        item: SpotifyItem,
        starts: list[int],
        direction: int,
    ) -> None:
        if not starts:
            self.say(msg.SYNCED_LYRICS_UNAVAILABLE)
            return
        position_ms = self.playback_position_ms(item.id)
        if position_ms is None:
            self.say(msg.NOTHING_PLAYING)
            return
        adjustment_ms = self.lyric_adjustment_ms(item.id)
        starts = [max(0, start - adjustment_ms) for start in starts]
        index = section_target(starts, position_ms, direction)
        if index is None:
            self.say(
                tr("No later section.")
                if direction > 0
                else tr("No earlier section.")
            )
            return
        self.seek_to_position(starts[index])
        if getattr(self, "announce_lyric_sections", False):
            self.say(
                tr("Section {number} of {total}.").format(
                    number=index + 1,
                    total=len(starts),
                )
            )

    def seek_to_position(self, position_ms: int) -> None:
        device_id = self.player_device_id()
        if not device_id:
            return
        if self.using_local_player():
            self.player.seek_to(position_ms)
            return
        self.run_task(
            None,
            lambda: self.spotify.seek_to(position_ms, device_id),
            lambda position: logger.info("Jumped to %d ms", position),
        )

    def jump_to_time(self) -> None:
        dialog = wx.TextEntryDialog(
            self,
            msg.JUMP_TIME_PROMPT,
            tr("Jump to time"),
        )
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        value = dialog.GetValue()
        dialog.Destroy()
        try:
            position_ms = self.parse_time(value)
        except ValueError:
            self.say(msg.JUMP_TIME_INVALID)
            return
        device_id = self.player_device_id()
        if not device_id:
            return
        if self.using_local_player():
            self.player.seek_to(position_ms)
            return
        self.run_task(
            None,
            lambda: self.spotify.seek_to(position_ms, device_id),
            lambda position: logger.info("Jumped to %d ms", position),
        )

    @staticmethod
    def parse_time(value: str) -> int:
        parts = value.strip().split(":")
        if len(parts) in (2, 3) and parts[-1] == "":
            parts[-1] = "0"
        if not 1 <= len(parts) <= 3 or any(not part.isdigit() for part in parts):
            raise ValueError("Invalid time")
        numbers = [int(part) for part in parts]
        if len(numbers) > 1 and any(part >= 60 for part in numbers[1:]):
            raise ValueError("Invalid time")
        seconds = 0
        for number in numbers:
            seconds = seconds * 60 + number
        return seconds * 1000

    @staticmethod
    def format_time(milliseconds: int) -> str:
        minutes, seconds = divmod(max(0, milliseconds) // 1000, 60)
        return f"{minutes}:{seconds:02d}"

    @staticmethod
    def bookmark_position_label(milliseconds: int) -> str:
        minutes, seconds = divmod(max(0, milliseconds) // 1000, 60)
        return tr("bookmarked at {position}").format(
            position=msg.minutes_seconds(minutes, seconds)
        )

    def bookmark_item_from_record(self, record: dict) -> SpotifyItem | None:
        if not record.get("bookmark_id") or not record.get("track_id"):
            return None
        position_ms = int(record.get("position_ms") or 0)
        raw = dict(record.get("track_raw") or {})
        raw["bookmark_id"] = str(record["bookmark_id"])
        raw["bookmark_position_ms"] = position_ms
        raw["bookmark_context_uri"] = str(record.get("context_uri") or "")
        raw["bookmark_position_label"] = self.bookmark_position_label(position_ms)
        raw["bookmark_name"] = str(record.get("bookmark_name") or "")
        return SpotifyItem(
            id=str(record["track_id"]),
            kind=ItemKind.TRACK,
            name=str(record.get("name") or "Untitled"),
            artist=str(record.get("artist") or ""),
            album=str(record.get("album") or ""),
            duration_ms=int(record.get("duration_ms") or 0),
            uri=str(record.get("uri") or ""),
            raw=raw,
        )

    def load_bookmarks(self) -> list[SpotifyItem]:
        records = self.store.read("bookmarks.json", []) or []
        if not isinstance(records, list):
            return []
        items = []
        for record in records:
            if not isinstance(record, dict):
                continue
            item = self.bookmark_item_from_record(record)
            if item:
                items.append(item)
        return items

    def load_recently_played(self) -> list[SpotifyItem]:
        return recent_plays.merge(
            self.spotify.recently_played(),
            recent_plays.load(self.store),
        )

    def note_listening(self, state: dict) -> None:
        """Record songs Spotify leaves out of Recently Played.

        Spotify only lists songs that played to the end, so BlindSpot keeps
        its own record of anything it has played for a short while.
        """
        timer = getattr(self, "listening_timer", None)
        if timer is None:
            return
        item = self.current_player_item
        uri = item.uri if item and item.uri.startswith("spotify:") else ""
        if timer.update(uri, bool(state.get("is_playing")), time.monotonic()):
            recent_plays.remember(self.store, item)
            logger.info("Recorded local play item=%s", item.id)

    def save_current_bookmark(self) -> None:
        if self.using_local_player():
            self.player.request_playback_state(self.finish_save_current_bookmark)
            return
        self.run_task(
            None,
            self.spotify.playback_state,
            self.finish_save_current_bookmark,
        )

    def finish_save_current_bookmark(self, state: dict) -> None:
        item = self.item_from_player_state(state)
        if not item:
            self.say(msg.NO_CURRENT_TRACK)
            return
        position_ms = int(state.get("progress_ms") or 0)
        context_uri = str(state.get("context_uri") or "")
        if not context_uri:
            context_uri = str((state.get("context") or {}).get("uri") or "")
        record = {
            "bookmark_id": uuid.uuid4().hex,
            "track_id": item.id,
            "name": item.name,
            "artist": item.artist,
            "album": item.album,
            "duration_ms": item.duration_ms,
            "uri": item.uri,
            "position_ms": position_ms,
            "context_uri": context_uri,
            "track_raw": item.raw,
        }
        records = self.store.read("bookmarks.json", []) or []
        if not isinstance(records, list):
            records = []
        records.insert(0, record)
        self.store.write("bookmarks.json", records)
        self.say(msg.bookmark_saved(self.format_time(position_ms)))

    def delete_bookmark(self, item: SpotifyItem) -> None:
        bookmark_id = str(item.raw.get("bookmark_id") or "")
        records = self.store.read("bookmarks.json", []) or []
        if isinstance(records, list):
            self.store.write(
                "bookmarks.json",
                [
                    record
                    for record in records
                    if not isinstance(record, dict)
                    or str(record.get("bookmark_id") or "") != bookmark_id
                ],
            )
        self.say(msg.BOOKMARK_DELETED)

    def rename_bookmark(self, item: SpotifyItem, name: str) -> None:
        bookmark_id = str(item.raw.get("bookmark_id") or "")
        records = self.store.read("bookmarks.json", []) or []
        if not isinstance(records, list):
            return
        for record in records:
            if (
                isinstance(record, dict)
                and str(record.get("bookmark_id") or "") == bookmark_id
            ):
                if name:
                    record["bookmark_name"] = name
                else:
                    record.pop("bookmark_name", None)
                break
        else:
            return
        self.store.write("bookmarks.json", records)
        item.raw["bookmark_name"] = name
        self.say(tr("Bookmark renamed.") if name else tr("Bookmark name cleared."))

    def resume_bookmark(self, item: SpotifyItem) -> None:
        device_id = self.player_device_id()
        if not device_id:
            return
        position_ms = int(item.raw.get("bookmark_position_ms") or 0)
        context_uri = str(item.raw.get("bookmark_context_uri") or "")
        self.run_task(
            None,
            lambda: self.spotify.play_at(
                item,
                position_ms,
                device_id,
                context_uri,
            ),
            lambda result: self.finish_resume_bookmark(
                item,
                position_ms,
                context_uri,
            ),
        )

    def finish_resume_bookmark(
        self,
        item: SpotifyItem,
        position_ms: int,
        context_uri: str,
    ) -> None:
        self.on_play_started(item, standalone=not bool(context_uri))
        self.say(msg.resumed(item.name, self.format_time(position_ms)))

    def next_track(self) -> None:
        device_id = self.player_device_id()
        if not device_id:
            return
        self.send_next_track(device_id)

    def send_next_track(self, device_id: str) -> None:
        current = self.current_player_item
        state = getattr(self, "current_player_state", {}) or {}
        if current:
            logger.info(
                "Skipping to next track current_id=%s current_name=%r "
                "context=%s repeat=%s shuffle=%s",
                current.id,
                current.name,
                state.get("context_uri", ""),
                getattr(self, "repeat_state", None) or "unknown",
                getattr(self, "shuffle_enabled", None),
            )

        self.run_task(
            None,
            lambda: self.spotify.next_track(device_id),
            lambda result: logger.info("Skipped to next track"),
        )

    def previous_track(self) -> None:
        device_id = self.player_device_id()
        if not device_id:
            return
        pending = getattr(self, "pending_previous_restart", None)
        if pending and pending.IsRunning():
            pending.Stop()
            self.pending_previous_restart = None
            self.run_task(
                None,
                lambda: self.spotify.previous_track(device_id),
                lambda result: logger.info("Returned to previous track"),
            )
            return
        item = self.current_player_item
        if item:
            self.pending_previous_restart = wx.CallLater(
                int(PREVIOUS_DOUBLE_PRESS_SECONDS * 1000),
                self.restart_current_track,
                item.id,
            )
            return
        self.run_task(
            None,
            lambda: self.spotify.previous_track(device_id),
            lambda result: logger.info("Returned to previous track"),
        )

    def restart_current_track(self, item_id: str) -> None:
        self.pending_previous_restart = None
        item = self.current_player_item
        if not item or item.id != item_id:
            return
        device_id = self.player_device_id()
        if not device_id:
            return
        if self.using_local_player():
            self.player.seek_to(0)
            logger.info("Restarted current track")
            return
        self.run_task(
            None,
            lambda: self.spotify.seek_to(0, device_id),
            lambda position: logger.info("Restarted current track"),
        )

    def open_bookmarks_window(self) -> None:
        if self.bookmarks_dialog is None:
            self.bookmarks_dialog = HostedPanelDialog(
                self,
                tr("Bookmarks"),
                lambda parent: BookmarksPanel(parent, self),
            )
        panel = self.bookmarks_dialog.panel
        panel.refresh()
        self.bookmarks_dialog.present(panel.items)

    def open_concerts_window(self) -> None:
        if self.concerts_dialog is None:
            self.concerts_dialog = HostedPanelDialog(
                self,
                tr("Search for concerts"),
                lambda parent: ConcertsPanel(parent, self),
            )
        panel = self.concerts_dialog.panel
        panel.ensure_classifications()
        self.concerts_dialog.present(panel.keyword)

    def show_selected_actions(self) -> None:
        now_playing = getattr(self, "now_playing", None)
        if now_playing:
            focused_list = item_list_ancestor(wx.Window.FindFocus())
            if focused_list is now_playing.items:
                now_playing.on_context_menu()
                return
        page = self.notebook.GetSelection()
        panels = (
            self.search,
            self.liked,
            self.queue,
            self.playlists,
            self.recently_played,
            self.audiobooks,
            self.podcasts,
            self.saved_albums,
            getattr(self, "new_music", None),
        )
        if 0 <= page < len(panels):
            panels[page].on_context_menu()

    def open_selected_track_album(self, item: SpotifyItem | None) -> None:
        if item and self.resolve_then(
            [item],
            lambda: self.open_selected_track_album(item),
        ):
            return
        if item and item.kind == ItemKind.TRACK:
            self.open_album_for_track(item)

    def refresh_current_view(self) -> None:
        page = self.notebook.GetCurrentPage()
        refresh = getattr(page, "refresh", None)
        if refresh:
            refresh()

    def toggle_like_selected(self) -> None:
        self.toggle_like_item(self.current_selected_item())

    def toggle_like_current_track(self) -> None:
        item = self.current_player_item
        if (
            getattr(self, "pending_resume", None)
            or not item
            or item.kind != ItemKind.TRACK
        ):
            self.say(msg.NOTHING_PLAYING)
            return
        self.toggle_like_item(item)

    def toggle_like_item(self, item: SpotifyItem | None) -> None:
        if item and self.resolve_then(
            [item],
            lambda: self.toggle_like_item(item),
        ):
            return
        if not item or not item.uri:
            self.say(msg.NO_ITEM_SELECTED)
            return
        self.run_task(
            None,
            lambda: self.spotify.toggle_saved(item),
            lambda saved: self.finish_toggle_like(item, saved),
        )

    def finish_toggle_like(self, item: SpotifyItem, saved: bool) -> None:
        self.sync_liked_item(item, saved)
        self.sync_saved_album(item, saved)
        self.say(msg.LIKED if saved else msg.UNLIKED)

    def choose_playlist_for_selected(self) -> None:
        focused_list = item_list_ancestor(wx.Window.FindFocus())
        items = focused_list.marked_items() if focused_list else []
        if not items:
            focused = (
                focused_list.selected_item()
                if focused_list
                else self.current_selected_item()
            )
            items = [focused] if focused else []
        self.choose_playlist_for_items(items)

    def copy_items_to_playlist_clipboard(
        self, item_list: ItemList, *, cut: bool
    ) -> None:
        selected = item_list.marked_items() or [item_list.selected_item()]
        selected = [
            item
            for item in selected
            if item
            and item.kind in {ItemKind.TRACK, ItemKind.EPISODE}
            and item.uri
        ]
        if not selected:
            self.say(msg.SELECT_TRACK_OR_EPISODE)
            return
        source = None
        source_items: list[SpotifyItem] = []
        if cut:
            playlists = self.playlists
            if (
                item_list is not playlists.items
                or not playlists.history.can_go_back
                or not playlists.current_playlist
                or playlists.current_playlist.raw.get("editable") is False
            ):
                self.say(
                    tr("Cut is available only inside an editable playlist.")
                )
                return
            source = playlists.current_playlist
            source_items = list(playlists.history.current.items)
            selections = locate_playlist_selections(source_items, selected)
        else:
            selections = [
                PlaylistSelection(item, -1) for item in selected
            ]
        if not selections:
            self.say(msg.SELECT_TRACK_OR_EPISODE)
            return
        self.playlist_clipboard = PlaylistClipboard(
            tuple(selections),
            cut=cut,
            source=source,
        )
        count = len(selections)
        self.say(
            ntr(
                "Cut {count} item. Open a playlist and paste.",
                "Cut {count} items. Open a playlist and paste.",
                count,
            ).format(count=count)
            if cut
            else ntr(
                "Copied {count} item. Open a playlist and paste.",
                "Copied {count} items. Open a playlist and paste.",
                count,
            ).format(count=count)
        )

    def copy_selected_items(self, *, cut: bool) -> None:
        item_list = self.current_item_list()
        if not item_list:
            self.say(msg.NO_ITEM_SELECTED)
            return
        self.copy_items_to_playlist_clipboard(item_list, cut=cut)

    def paste_playlist_clipboard(self) -> None:
        clipboard = self.playlist_clipboard
        playlists = self.playlists
        destination = playlists.current_playlist
        if not clipboard:
            self.say(tr("The playlist clipboard is empty."))
            return
        if (
            not playlists.history.can_go_back
            or not destination
            or destination.raw.get("editable") is False
        ):
            self.say(tr("Open an editable playlist before pasting."))
            return
        if (
            clipboard.cut
            and clipboard.source
            and clipboard.source.id == destination.id
        ):
            self.say(tr("The cut items are already in this playlist."))
            return
        items = [selection.item for selection in clipboard.selections]

        def task() -> None:
            if clipboard.cut and clipboard.source:
                self.playlist_operations.move(
                    clipboard.source,
                    destination,
                    list(clipboard.selections),
                )
            else:
                self.playlist_operations.copy(
                    destination, list(clipboard.selections)
                )

        self.run_task(
            None,
            task,
            lambda result: self.finish_playlist_paste(
                destination, items, clipboard
            ),
        )

    def finish_playlist_paste(
        self,
        destination: SpotifyItem,
        items: list[SpotifyItem],
        clipboard: PlaylistClipboard,
    ) -> None:
        self.finish_add_to_playlist(
            destination, items, moved=clipboard.cut
        )
        if clipboard.cut and self.playlist_clipboard is clipboard:
            self.playlist_clipboard = None

    def choose_playlist_for_item(self, item: SpotifyItem | None) -> None:
        self.choose_playlist_for_items([item] if item else [])

    def choose_playlist_for_items(
        self,
        items: list[SpotifyItem],
        *,
        move_from: SpotifyItem | None = None,
        move_selections: list[PlaylistSelection] | None = None,
        on_moved: Callable[[], None] | None = None,
    ) -> None:
        if self.resolve_then(
            items,
            lambda: self.choose_playlist_for_items(
                items,
                move_from=move_from,
                move_selections=move_selections,
                on_moved=on_moved,
            ),
        ):
            return
        items = [
            item
            for item in items
            if item.kind in {ItemKind.TRACK, ItemKind.EPISODE} and item.uri
        ]
        if not items:
            self.say(msg.SELECT_TRACK_OR_EPISODE)
            return
        self.run_task(
            None,
            self.spotify.user_playlists,
            lambda playlists: self.show_playlist_picker(
                items,
                [
                    playlist
                    for playlist in playlists
                    if playlist.raw.get("editable") is not False
                    and (not move_from or playlist.id != move_from.id)
                ],
                move_from=move_from,
                move_selections=move_selections,
                on_moved=on_moved,
            ),
        )

    def create_playlist(self) -> None:
        dialog = CreatePlaylistDialog(self)
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        name = dialog.name.GetValue().strip()
        public = dialog.public.GetValue()
        dialog.Destroy()
        self.run_task(
            None,
            lambda: self.spotify.create_playlist(name, public),
            self.finish_create_playlist,
        )

    def finish_create_playlist(self, playlist: SpotifyItem) -> None:
        if self.playlists.history.can_go_back:
            self.playlists.go_back()
        self.notebook.SetSelection(3)
        self.playlists.pending_playlist_selection_id = playlist.id
        self.playlists.items.SetFocus()
        self.playlists.refresh()

    def show_playlist_picker(
        self,
        items: list[SpotifyItem],
        playlists: list[SpotifyItem],
        *,
        move_from: SpotifyItem | None = None,
        move_selections: list[PlaylistSelection] | None = None,
        on_moved: Callable[[], None] | None = None,
    ) -> None:
        if not playlists:
            self.say(msg.NO_PLAYLISTS)
            return
        dialog = wx.SingleChoiceDialog(
            self,
            msg.CHOOSE_PLAYLIST,
            tr("Move to playlist") if move_from else tr("Copy to playlist"),
            [playlist.accessible_label() for playlist in playlists],
        )
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        playlist = playlists[dialog.GetSelection()]
        dialog.Destroy()

        def task() -> None:
            if move_from:
                self.playlist_operations.move(
                    move_from,
                    playlist,
                    move_selections
                    or [
                        PlaylistSelection(item, index)
                        for index, item in enumerate(items)
                    ],
                )
            else:
                self.playlist_operations.copy(
                    playlist,
                    [PlaylistSelection(item, -1) for item in items],
                )

        self.run_task(
            None,
            task,
            lambda result: self.finish_add_to_playlist(
                playlist, items, moved=bool(move_from), on_moved=on_moved
            ),
        )

    def finish_add_to_playlist(
        self,
        playlist: SpotifyItem,
        items: SpotifyItem | list[SpotifyItem],
        *,
        moved: bool = False,
        on_moved: Callable[[], None] | None = None,
    ) -> None:
        if isinstance(items, SpotifyItem):
            items = [items]
        count = len(items)
        self.say(
            ntr(
                "Moved {count} item to the playlist.",
                "Moved {count} items to the playlist.",
                count,
            ).format(count=count)
            if moved
            else ntr(
                "Added {count} item to the playlist.",
                "Added {count} items to the playlist.",
                count,
            ).format(count=count)
        )
        if moved and on_moved:
            on_moved()
        current = self.playlists.current_playlist
        if not current or current.id != playlist.id:
            return
        self.playlists.history.current.items.extend(items)
        self.playlists.render(
            self.playlists.history.current,
            focus=False,
        )

    def sync_liked_item(self, item: SpotifyItem, saved: bool) -> None:
        if item.kind != ItemKind.TRACK:
            return
        matches = [
            index
            for index, existing in enumerate(self.liked.items.items)
            if existing.id == item.id
        ]
        if saved and not matches:
            self.liked.items.items.insert(0, item)
            self.liked.items.Insert(item.accessible_label(), 0)
        elif not saved:
            for index in reversed(matches):
                del self.liked.items.items[index]
                self.liked.items.Delete(index)
        self.liked.status.SetLabel(
            msg.item_count(len(self.liked.items.items))
        )

    def sync_saved_album(self, item: SpotifyItem, saved: bool) -> None:
        if item.kind != ItemKind.ALBUM:
            return
        albums = self.saved_albums.items
        matches = [
            index
            for index, existing in enumerate(albums.items)
            if existing.id == item.id
        ]
        if saved and not matches and self.saved_albums.loaded_once:
            albums.items.insert(0, item)
            albums.Insert(item.accessible_label(), 0)
        elif not saved:
            for index in reversed(matches):
                del albums.items[index]
                albums.Delete(index)
        self.saved_albums.status.SetLabel(msg.item_count(len(albums.items)))

    def on_player_ready(self, device_id: str) -> None:
        self.say(msg.READY)
        if self.pending_play_items:
            items = self.pending_play_items
            message = self.pending_play_items_message
            callback = self.pending_play_items_callback
            disable_repeat = self.pending_play_items_disable_repeat
            self.pending_play_items = []
            self.pending_play_items_message = ""
            self.pending_play_items_callback = None
            self.pending_play_items_disable_repeat = False
            self.play_items(
                items,
                started_message=message,
                after_started=callback,
                disable_repeat=disable_repeat,
            )
            return
        if self.pending_play_item:
            item = self.pending_play_item
            context = self.pending_play_context
            position_ms = self.pending_play_position_ms
            self.pending_play_item = None
            self.pending_play_context = None
            self.pending_play_position_ms = 0
            if context:
                self.play_in_context(context, item)
            elif position_ms or item.kind == ItemKind.CHAPTER:
                self.play_from_lyric(item, position_ms)
            else:
                self.play(item)

    def on_playback_update(self, state: dict) -> None:
        if self.remote_device_id and not state.get("direct_audio"):
            return
        if state.get("is_playing") and not getattr(
            self, "audio_output_applied", True
        ):
            self.apply_audio_output()
        self.apply_playback_update(state)
        self.note_listening(state)

    @staticmethod
    def report_transit_seconds(state: dict) -> float:
        """Time since the web player sampled its position, if it says when."""
        sent_at_ms = state.get("sent_at_ms")
        if not isinstance(sent_at_ms, (int, float)):
            return 0.0
        return min(2.0, max(0.0, (time.time() * 1000 - sent_at_ms) / 1000))

    def apply_playback_update(self, state: dict) -> None:
        state = dict(state)
        if not state.get("context_uri"):
            context = state.get("context") or {}
            state["context_uri"] = context.get("uri", "")
        self.current_player_state = state
        logger.debug(
            "Playback update item=%s playing=%s progress_ms=%s",
            (state.get("item") or {}).get("id"),
            state.get("is_playing"),
            state.get("progress_ms"),
        )
        self.playback_state_updated_at = time.monotonic() - self.report_transit_seconds(state)
        self.current_player_item = self.item_from_player_state(state)
        MainFrame.update_now_playing(self, self.current_player_item)
        self.apply_pending_lyric_seek()
        state["standalone"] = bool(
            self.current_player_item
            and self.standalone_player_item_id
            == self.current_player_item.id
        )
        if (
            self.sleep_after_track_id
            and self.current_player_item
            and self.current_player_item.id != self.sleep_after_track_id
        ):
            wx.CallAfter(self.expire_sleep_timer)
        elif self.sleep_after_track_id:
            self.synchronize_sleep_after_track(state)
        if "shuffle_state" in state:
            self.shuffle_enabled = bool(state["shuffle_state"])
        if state.get("repeat_state") in {"off", "context", "track"}:
            self.repeat_state = state["repeat_state"]
        if self.current_player_item:
            self.pending_resume = None
            is_new_track = self.current_player_item.id != self.last_player_item_id
            self.last_player_item_id = self.current_player_item.id
            if is_new_track:
                self.set_view_title(self.current_player_item.name)
                self.update_continuous_similar_mix(self.current_player_item)
            suppress_announcement = (
                self.current_player_item.id
                == self.suppress_track_announcement_id
            )
            if suppress_announcement:
                self.suppress_track_announcement_id = None
            if (
                self.announce_track_changes
                and is_new_track
                and not suppress_announcement
            ):
                announcement = self.current_player_item.name
                if self.current_player_item.artist:
                    announcement += tr(
                        " by {artist}"
                    ).format(artist=self.current_player_item.artist)
                self.say(announcement)
            if self.resume_mode != "none":
                self.store.write(
                    "playback.json",
                    playback_state_for_resume(state, self.resume_mode),
                )

    def apply_pending_lyric_seek(self) -> None:
        pending = self.pending_lyric_seek
        item = self.current_player_item
        if not pending or not item or item.id != pending[0]:
            return
        _, position_ms = pending
        self.pending_lyric_seek = None
        self.lyric_start_item_id = None
        if not position_ms:
            return
        progress_ms = int(self.current_player_state.get("progress_ms") or 0)
        if abs(progress_ms - position_ms) <= 1_500:
            logger.info(
                "Confirmed lyric start position item=%s position_ms=%s",
                item.id,
                position_ms,
            )
            return
        # The play request already included position_ms. Playback updates can
        # briefly describe the previous position while Spotify changes state;
        # issuing a second seek here races rapid lyric-navigation commands and
        # can produce a transient "Nothing playing" error.
        logger.info(
            "Accepted lyric start before position confirmation "
            "item=%s requested_ms=%s reported_ms=%s",
            item.id,
            position_ms,
            progress_ms,
        )

    def load_pending_resume(self) -> None:
        if self.resume_mode == "none":
            return
        state = self.store.read("playback.json", {}) or {}
        item = self.item_from_player_state(state)
        if not item:
            return
        position_ms = (
            int(state.get("progress_ms") or 0)
            if self.resume_mode == "track_and_position"
            else 0
        )
        context_uri = str(state.get("context_uri") or "")
        self.current_player_item = item
        MainFrame.update_now_playing(self, item)
        standalone = bool(
            state.get("standalone", not bool(context_uri))
        )
        self.standalone_player_item_id = item.id if standalone else None
        self.pending_resume = (item, position_ms, context_uri)
        self.last_player_item_id = item.id
        self.set_view_title(item.name)

    def update_now_playing(self, item: SpotifyItem | None) -> None:
        panel = getattr(self, "now_playing", None)
        if panel:
            panel.set_item(item)

    @staticmethod
    def item_from_player_state(state: dict) -> SpotifyItem | None:
        value = state.get("item") or {}
        if not value.get("id"):
            return None
        artists = ", ".join(
            artist.get("name", "")
            for artist in value.get("artists", [])
            if artist.get("name")
        )
        album = value.get("album") or {}
        kind = ItemKind.TRACK
        if value.get("type") == "episode":
            kind = ItemKind.EPISODE
        if value.get("type") == "chapter" or str(value.get("uri", "")).startswith(
            "spotify:chapter:"
        ):
            kind = ItemKind.CHAPTER
            audiobook = value.get("audiobook") or {}
            album = audiobook
            artists = ", ".join(
                author.get("name", "")
                for author in audiobook.get("authors", [])
                if author.get("name")
            )
        return SpotifyItem(
            id=value["id"],
            kind=kind,
            name=value.get("name", "Untitled"),
            artist=artists,
            album=album.get("name", ""),
            duration_ms=int(value.get("duration_ms") or 0),
            uri=value.get("uri", ""),
            raw=value,
        )

    def on_player_error(self, message: str) -> None:
        if message == msg.NO_TRACKS and self.lyric_start_item_id:
            logger.info(
                "Ignored transient empty-player error while starting lyric item=%s",
                self.lyric_start_item_id,
            )
            return
        self.say(message)
        logger.error("BlindSpot player: %s", message)

    def on_close(self, event: wx.CloseEvent) -> None:
        self.unregister_global_hotkeys()
        self.remote_refresh_timer.Stop()
        self.sleep_timer.Stop()
        self.cart_timer.Stop()
        if self.player:
            self.player.close()
            self.player = None
        event.Skip()

    def queue_selected(self, item: SpotifyItem | None) -> None:
        if item and self.resolve_then(
            [item],
            lambda: self.queue_selected(item),
        ):
            return
        if not item or not item.uri or not item.playable:
            return
        if self.queue_should_be_deferred():
            self.deferred_queue_items.append(item)
            self.finish_queue(item)
            logger.info("Deferred queue item id=%s name=%r", item.id, item.name)
            return
        device_id = self.player_device_id()
        if not device_id:
            return
        self.run_task(
            None,
            lambda: self.spotify.add_to_queue(item, device_id),
            lambda result: self.finish_queue(item),
        )

    def queue_command(self) -> None:
        focused = wx.Window.FindFocus()
        focused_list = item_list_ancestor(focused)
        if focused_list:
            self.queue_from_list(focused_list)
        else:
            self.queue_selected(self.current_selected_item())

    def queue_from_list(self, item_list: ItemList) -> None:
        chosen = item_list.marked_items() or (
            [item_list.selected_item()] if item_list.selected_item() else []
        )
        if self.resolve_then(chosen, lambda: self.queue_from_list(item_list)):
            return
        marked = [
            item
            for item in item_list.marked_items()
            if item.uri and item.playable
        ]
        if not marked:
            focused = item_list.selected_item()
            marked = (
                [focused]
                if focused and focused.uri and focused.playable
                else []
            )
        if not marked:
            self.say(msg.NO_PLAYABLE_TRACKS)
            return
        if self.queue_should_be_deferred():
            self.deferred_queue_items.extend(marked)
            self.finish_queue_many(marked)
            logger.info("Deferred %s queue items", len(marked))
            return
        device_id = self.player_device_id()
        if not device_id:
            return
        added: list[SpotifyItem] = []

        def add_all() -> None:
            for item in marked:
                self.spotify.add_to_queue(item, device_id)
                added.append(item)

        self.run_task(
            None,
            add_all,
            lambda result: self.finish_queue_many(marked),
            failure=lambda: self.finish_queue_many(added) if added else None,
        )

    def queue_should_be_deferred(self) -> bool:
        return bool(getattr(self, "pending_resume", None)) or (
            getattr(self, "current_player_item", None) is None
        )

    def queue_items(self) -> list[SpotifyItem]:
        try:
            spotify_items = self.spotify.queue()
        except SpotifyError:
            if not self.deferred_queue_items:
                raise
            logger.info(
                "Spotify queue unavailable; showing %s deferred items",
                len(self.deferred_queue_items),
            )
            return list(self.deferred_queue_items)
        return spotify_items + list(self.deferred_queue_items)

    def flush_deferred_queue(self) -> None:
        if self.deferred_queue_flushing or not self.deferred_queue_items:
            return
        device_id = self.player_device_id()
        if not device_id:
            return
        items = list(self.deferred_queue_items)
        self.deferred_queue_flushing = True
        added: list[SpotifyItem] = []

        def forget_added() -> None:
            # Remove one occurrence for each successful request. The list may
            # have changed while the background task ran, so never delete by
            # snapshot position and never collapse intentional duplicates.
            for done in added:
                position = next(
                    (
                        index
                        for index, queued_item in enumerate(
                            self.deferred_queue_items
                        )
                        if queued_item is done
                    ),
                    None,
                )
                if position is not None:
                    del self.deferred_queue_items[position]

        def add_all() -> None:
            for queued_item in items:
                self.spotify.add_to_queue(queued_item, device_id)
                added.append(queued_item)

        def finished(result: object) -> None:
            forget_added()
            self.deferred_queue_flushing = False
            logger.info("Flushed %s deferred queue items", len(items))

        def failed() -> None:
            # Items Spotify already accepted must not be queued a second
            # time when the flush is retried.
            forget_added()
            self.deferred_queue_flushing = False

        self.run_task(None, add_all, finished, failure=failed)

    def finish_queue_many(
        self,
        items: list[SpotifyItem],
        *,
        announcement: str = "",
    ) -> None:
        if self.queue.loaded_once:
            for item in items:
                self.queue.items.items.append(item)
                self.queue.items.Append(item.accessible_label())
            self.queue.status.SetLabel(
                msg.item_count(len(self.queue.items.items))
            )
        count = len(items)
        self.say(announcement or msg.queued_count(count))

    def finish_queue(self, item: SpotifyItem) -> None:
        if self.queue.loaded_once:
            self.queue.items.items.append(item)
            self.queue.items.Append(item.accessible_label())
            self.queue.status.SetLabel(
                msg.item_count(len(self.queue.items.items))
            )
        self.say(msg.QUEUED)

    def like_selected(self, item: SpotifyItem | None) -> None:
        if not item or not item.uri:
            return
        self.run_task(
            None,
            lambda: self.spotify.save(item),
            lambda result: self.finish_save_to_library(item),
        )

    def finish_save_to_library(self, item: SpotifyItem) -> None:
        self.sync_liked_item(item, True)
        self.say(msg.LIKED)

    def open_album_for_track(self, item: SpotifyItem) -> None:
        if self.notebook.GetSelection() == 0:
            # Ctrl+Enter reaches this action without going through
            # SearchPanel.on_open, so preserve the precise source row here.
            # Otherwise a paginated search retains its page-boundary
            # selection (for example row 0 or 20) when Backspace is pressed.
            self.search.history.remember_selection(
                self.search.results.GetSelection()
            )

        def load_album() -> tuple[SpotifyItem, list[SpotifyItem]]:
            album = self.spotify.album_for_track(item)
            return album, self.spotify.children(album)

        self.run_task(
            msg.opening_album(item.name),
            load_album,
            lambda result: self.finish_open_album(*result),
        )

    def finish_open_album(
        self,
        album: SpotifyItem,
        tracks: list[SpotifyItem],
    ) -> None:
        origin_page = self.notebook.GetSelection()
        state = ViewState(
            album.name,
            tracks,
            parent_id=album.id,
            parent_kind=ItemKind.ALBUM,
            parent_item=album,
            parent_artist_names=tuple(
                artist.get("name", "")
                for artist in album.raw.get("artists") or []
                if artist.get("name")
            )
            or ((album.artist,) if album.artist else ()),
            parent_artist_ids=tuple(
                artist.get("id", "")
                for artist in album.raw.get("artists") or []
                if artist.get("id")
            ),
        )
        if origin_page != 0:
            self.open_album_return_page = origin_page
            self.open_album_return_state = state
        self.notebook.SetSelection(0)
        self.search.history.push(state)
        self.search.render(self.search.history.current, focus=True)
        # Cocoa can restore focus to the contextual-menu owner after its
        # command callback returns.  When that owner belongs to the page we
        # just hid, VoiceOver is left on an inaccessible object.  Reassert
        # focus on the next event-loop turn, after the menu and DataView's
        # accessibility tree have both settled.
        wx.CallAfter(self.focus_open_album)
        if not tracks:
            self.say(msg.named_item_count(album.name, 0))

    def return_from_open_album(self, state: ViewState) -> bool:
        if (
            state is not self.open_album_return_state
            or self.open_album_return_page is None
        ):
            return False
        page = self.open_album_return_page
        self.discard_transient_open_album()
        self.notebook.SetSelection(page)
        panels = (
            self.search,
            self.liked,
            self.queue,
            self.playlists,
            self.recently_played,
            self.audiobooks,
            self.podcasts,
            self.saved_albums,
            getattr(self, "new_music", None),
        )
        panels[page].items.SetFocus()
        return True

    def discard_transient_open_album(self) -> bool:
        state = self.open_album_return_state
        if state is None or self.search.history.current is not state:
            return False
        self.open_album_return_page = None
        self.open_album_return_state = None
        restored = self.search.history.back()
        self.search.render(restored, focus=False)
        return True

    def focus_open_album(self) -> None:
        if self.notebook.GetCurrentPage() is not self.search:
            return
        if self.search.results.items:
            self.search.results.SetFocus()
        else:
            self.search.query.SetFocus()

    def popup_item_menu(
        self,
        owner: wx.Window,
        item: SpotifyItem,
        *,
        open_callback: Callable[[], None] | None = None,
        play_callback: Callable[[], None] | None = None,
        remove_callback: Callable[[], None] | None = None,
        remove_label: str = tr_noop("&Remove from Liked Songs"),
        include_album_action: bool = True,
        additional_actions: list[
            tuple[str, Callable[[], None]]
        ] | None = None,
        top_level_actions: list[
            tuple[str, Callable[[], None]]
        ] | None = None,
        include_select_all: bool = True,
    ) -> None:
        if self.resolve_then(
            [item],
            lambda: self.popup_item_menu(
                owner,
                item,
                open_callback=open_callback,
                play_callback=play_callback,
                remove_callback=remove_callback,
                remove_label=remove_label,
                include_album_action=include_album_action,
                additional_actions=additional_actions,
                top_level_actions=top_level_actions,
                include_select_all=include_select_all,
            ),
        ):
            return
        menu = wx.Menu()
        actions: list[tuple[wx.MenuItem, Callable[[], None]]] = []
        if open_callback:
            actions.append((menu.Append(wx.ID_ANY, tr("&Open")), open_callback))
        if item.playable:
            actions.append(
                (
                    menu.Append(wx.ID_ANY, tr("&Play now")),
                    lambda: self.play_now_from_menu(
                        owner,
                        item,
                        play_callback,
                    ),
                )
            )
        if item.kind == ItemKind.TRACK:
            actions.append(
                (
                    menu.Append(wx.ID_ANY, tr("Find &alternate versions...")),
                    lambda: self.find_alternate_versions_for(item),
                )
            )
        if item.kind == ItemKind.ALBUM:
            actions.append(
                (
                    menu.Append(wx.ID_ANY, tr("&Related albums...")),
                    lambda: self.show_related_albums(item),
                )
            )
            actions.append(
                (
                    menu.Append(wx.ID_ANY, tr("Display album &artwork...")),
                    lambda: self.show_album_artwork(item),
                )
            )
            if not top_level_actions:
                artists = item.raw.get("artists") or []
                if artists:
                    artist_id = str(artists[0].get("id") or "")
                    artist_name = str(artists[0].get("name") or "")
                    if artist_id and artist_name:
                        actions.append(
                            (
                                menu.Append(
                                    wx.ID_ANY,
                                    tr(
                                        "Show albums by &{artist_name}"
                                    ).format(artist_name=artist_name),
                                ),
                                lambda: self.show_artist_albums(
                                    artist_id, artist_name
                                ),
                            )
                        )
        if item.kind == ItemKind.PLAYLIST:
            actions.append(
                (
                    menu.Append(wx.ID_ANY, tr("Playlist &information...")),
                    lambda: self.show_playlist_information(item),
                )
            )
        elif item.raw.get("description"):
            actions.append(
                (
                    menu.Append(wx.ID_ANY, tr("&Description...")),
                    lambda: self.show_item_description(item),
                )
            )
        if additional_actions:
            move_menu = wx.Menu()
            for label, callback in additional_actions:
                menu_item = move_menu.Append(wx.ID_ANY, label)
                move_menu.Bind(
                    wx.EVT_MENU,
                    lambda event, action=callback: action(),
                    menu_item,
                )
            menu.AppendSubMenu(move_menu, tr("&Move"))
        if top_level_actions:
            for label, callback in top_level_actions:
                actions.append(
                    (menu.Append(wx.ID_ANY, label), callback)
                )
        if item.kind == ItemKind.EPISODE:
            actions.append(
                (
                    menu.Append(wx.ID_ANY, tr("Show &transcript...")),
                    lambda: self.show_transcript_for_item(item),
                )
            )
            actions.append(
                (
                    menu.Append(wx.ID_ANY, tr("&Download episode...")),
                    lambda: self.find_episode_download(item),
                )
            )
        if item.kind == ItemKind.TRACK:
            if not any(
                label.replace("&", "").casefold()
                == tr("Show &lyrics").replace("&", "").casefold()
                for label, _callback in (top_level_actions or [])
            ):
                actions.append(
                    (
                        menu.Append(wx.ID_ANY, tr("Show &lyrics")),
                        lambda: self.show_lyrics_for_item(item),
                    )
                )
            mix_menu = wx.Menu()
            open_mix = mix_menu.Append(wx.ID_ANY, tr("&Open for inspection"))
            start_mix = mix_menu.Append(wx.ID_ANY, tr("Start &now"))
            queue_mix = mix_menu.Append(
                wx.ID_ANY, tr("Add after current &queue")
            )
            mix_menu.Bind(
                wx.EVT_MENU,
                lambda event: self.open_similar_mix(item),
                open_mix,
            )
            mix_menu.Bind(
                wx.EVT_MENU,
                lambda event: self.start_similar_mix(item),
                start_mix,
            )
            mix_menu.Bind(
                wx.EVT_MENU,
                lambda event: self.queue_similar_mix(item),
                queue_mix,
            )
            menu.AppendSubMenu(mix_menu, tr("Similar-track mix (Last.&fm)"))
            if include_album_action:
                actions.append(
                    (
                        menu.Append(wx.ID_ANY, tr("Open &album")),
                        lambda: self.open_album_for_track(item),
                    )
                )
        if item.kind == ItemKind.ARTIST:
            actions.append(
                (
                    menu.Append(wx.ID_ANY, tr(
                        "Find similar &artists (Last.fm)"
                    )),
                    lambda: self.find_similar_artists(item),
                )
            )
        about_artist = MainFrame.unambiguous_artist_name(item)
        if about_artist:
            actions.append(
                (
                    menu.Append(
                        wx.ID_ANY,
                        tr("&About {artist}...").format(artist=about_artist),
                    ),
                    lambda: self.show_artist_story(about_artist),
                )
            )
        if item.kind in (ItemKind.TRACK, ItemKind.ARTIST):
            actions.append(
                (
                    menu.Append(wx.ID_ANY, tr("Browse &genres (Last.fm)...")),
                    lambda: self.browse_genres_for(item),
                )
            )
        if item.kind == ItemKind.TRACK:
            actions.append(
                (
                    menu.Append(wx.ID_ANY, tr("Find &covers (MusicBrainz)")),
                    lambda: self.find_covers_for(item),
                )
            )
            actions.append(
                (
                    menu.Append(wx.ID_ANY, tr("&What's this song about?")),
                    lambda: self.show_song_story(item),
                )
            )
        if (
            item.kind in (ItemKind.TRACK, ItemKind.ALBUM)
            and not item.raw.get("unresolved")
        ):
            actions.append(
                (
                    menu.Append(
                        wx.ID_ANY,
                        tr("Album and recording &information..."),
                    ),
                    lambda: self.show_music_details(item),
                )
            )
        follow_name, follow_kind = MainFrame.follow_target(item)
        if follow_name and item.kind in (
            ItemKind.TRACK,
            ItemKind.ALBUM,
            ItemKind.ARTIST,
            ItemKind.AUDIOBOOK,
            ItemKind.CHAPTER,
        ):
            following = self.followed.is_following(follow_name, follow_kind)
            if follow_kind == AUTHOR:
                label = (
                    tr("Stop following author {artist} for &new releases")
                    if following
                    else tr("Follow author {artist} for &new releases")
                )
            else:
                label = (
                    tr("Stop following {artist} for &new releases")
                    if following
                    else tr("Follow {artist} for &new releases")
                )
            actions.append(
                (
                    menu.Append(wx.ID_ANY, label.format(artist=follow_name)),
                    lambda: self.toggle_follow_artist(follow_name, follow_kind),
                )
            )
        if item.raw.get("lastfm_url"):
            actions.append(
                (
                    menu.Append(wx.ID_ANY, tr("Open on Last.&fm...")),
                    lambda: webbrowser.open(str(item.raw["lastfm_url"])),
                )
            )
            if self.current_player_item and item.id == self.current_player_item.id:
                actions.append(
                    (
                        menu.Append(wx.ID_ANY, tr(
                            "Bookmark current &position"
                        )),
                        self.save_current_bookmark,
                    )
                )
        if item.playable and item.uri:
            if isinstance(owner, ItemList):
                queue_action = lambda: self.queue_from_list(owner)
            else:
                queue_action = lambda: self.queue_selected(item)
            actions.append(
                (
                    menu.Append(wx.ID_ANY, tr("Add to &queue")),
                    queue_action,
                )
            )
            if not remove_callback:
                actions.append(
                    (
                        menu.Append(wx.ID_ANY, tr("&Save to library")),
                        lambda: self.like_selected(item),
                    )
                )
        if remove_callback:
            menu.AppendSeparator()
            actions.append(
                (
                    menu.Append(wx.ID_ANY, tr(remove_label)),
                    remove_callback,
                )
            )
        if include_select_all and isinstance(owner, ItemList):
            menu.AppendSeparator()
            shortcut = "Command+A" if sys.platform == "darwin" else "Ctrl+A"
            actions.append(
                (
                    menu.Append(
                        wx.ID_SELECTALL,
                        tr(
                            "Select &all ({shortcut})"
                        ).format(shortcut=shortcut),
                    ),
                    lambda: self.select_all_in_current_list(owner),
                )
            )
        for menu_item, callback in actions:
            menu.Bind(
                wx.EVT_MENU,
                lambda event, action=callback: action(),
                menu_item,
            )
        owner.PopupMenu(menu)
        menu.Destroy()

    def play_now_from_menu(
        self,
        owner: wx.Window,
        item: SpotifyItem,
        play_callback: Callable[[], None] | None = None,
    ) -> None:
        marked_items = getattr(owner, "marked_items", None)
        selected = [
            selected_item
            for selected_item in (marked_items() if marked_items else [])
            if selected_item.playable and selected_item.uri
        ]
        if len(selected) > 1:
            self.play_items(selected)
            return
        if play_callback:
            play_callback()
            return
        self.play_playable_item(item)

    def show_artist_albums(self, artist_id: str, artist_name: str) -> None:
        origin_page = self.notebook.GetSelection()
        artist = SpotifyItem(artist_id, ItemKind.ARTIST, artist_name)
        self.run_task(
            msg.opening(artist_name),
            lambda: self.spotify.children(artist),
            lambda albums: self.finish_show_artist_albums(
                origin_page,
                artist,
                albums,
            ),
        )

    def finish_show_artist_albums(
        self,
        origin_page: int,
        artist: SpotifyItem,
        albums: list[SpotifyItem],
    ) -> None:
        self.notebook.SetSelection(0)
        self.search.open_children(artist, albums)
        if origin_page != 0:
            self.open_album_return_page = origin_page
            self.open_album_return_state = self.search.history.current
        wx.CallAfter(self.focus_open_album)

    def show_related_albums(self, album: SpotifyItem) -> None:
        origin_page = self.notebook.GetSelection()
        self.run_task(
            tr("Finding albums related to {name}").format(name=album.name),
            lambda: self.related_albums_for(album),
            lambda albums: self.finish_show_related_albums(
                origin_page,
                album,
                albums,
            ),
        )

    def related_albums_for(self, source_album: SpotifyItem) -> list[SpotifyItem]:
        tracks = [
            item
            for item in self.spotify.children(source_album)
            if item.kind == ItemKind.TRACK and item.artist
        ]
        if not tracks:
            return []
        seed_indexes = sorted({0, len(tracks) // 2, len(tracks) - 1})
        candidates: list[SimilarTrack] = []
        seen_candidates: set[tuple[str, str]] = set()
        for index in seed_indexes:
            seed = tracks[index]
            artist = seed.artist.split(",", 1)[0].strip()
            for candidate in self.lastfm.similar_tracks(
                seed.name,
                artist,
                limit=12,
            ):
                identity = (
                    normalise_filter_text(candidate.name),
                    normalise_filter_text(candidate.artist),
                )
                if identity in seen_candidates:
                    continue
                seen_candidates.add(identity)
                candidates.append(candidate)

        source_identity = new_album_identity(source_album)
        albums: dict[tuple[str, str, int | None], SpotifyItem] = {}
        scores: dict[tuple[str, str, int | None], int] = {}
        seen_tracks: set[str] = set()
        for candidate in candidates:
            track = self.spotify.find_track(candidate.name, candidate.artist)
            if not track or track.id in seen_tracks:
                continue
            seen_tracks.add(track.id)
            album = self.spotify.album_for_track(track)
            identity = new_album_identity(album)
            if album.id == source_album.id or identity == source_identity:
                continue
            albums.setdefault(identity, album)
            scores[identity] = scores.get(identity, 0) + 1
        return sorted(
            albums.values(),
            key=lambda album: (
                -scores[new_album_identity(album)],
                normalise_filter_text(album.artist),
                normalise_filter_text(album.name),
            ),
        )[:20]

    def finish_show_related_albums(
        self,
        origin_page: int,
        source_album: SpotifyItem,
        albums: list[SpotifyItem],
    ) -> None:
        state = ViewState(tr(
            "Related albums to {name}"
        ).format(name=source_album.name), albums)
        self.notebook.SetSelection(0)
        self.search.history.push(state)
        self.search.render(state, focus=True)
        if origin_page != 0:
            self.open_album_return_page = origin_page
            self.open_album_return_state = state
        if not albums:
            self.say(tr(
                "No related albums found for {name}."
            ).format(name=source_album.name))
        wx.CallAfter(self.focus_open_album)

    def lastfm_tracks_for(self, item: SpotifyItem) -> list[SpotifyItem]:
        source_artist = item.artist.split(",", 1)[0].strip()
        results = self.lastfm.similar_tracks(item.name, source_artist)
        return self.match_lastfm_tracks(results, {item.id})

    def match_lastfm_tracks(
        self,
        candidates: list[SimilarTrack],
        seen: set[str],
    ) -> list[SpotifyItem]:
        matched = []
        for result in candidates:
            track = self.spotify.find_track(result.name, result.artist)
            if track and track.id not in seen:
                track.raw["lastfm_url"] = result.url
                seen.add(track.id)
                matched.append(track)
        return matched

    def lastfm_tag_results(
        self,
        tag: str,
        category: str,
        *,
        query: str = "",
        page: int = 1,
    ) -> list[SpotifyItem]:
        tag_page = self.lastfm.top_tag_items(
            tag,
            category,
            page=page,
            limit=20,
        )
        words = normalise_filter_text(query).split()
        candidates = [
            candidate
            for candidate in tag_page.items
            if not words
            or all(
                word
                in normalise_filter_text(
                    f"{candidate.name} {candidate.artist}"
                )
                for word in words
            )
        ]
        matched: list[SpotifyItem] = []
        seen: set[str] = set()
        for candidate in candidates:
            item = self.match_lastfm_tag_item(candidate, category)
            if not item or item.id in seen:
                continue
            item.raw["lastfm_url"] = candidate.url
            item.raw["lastfm_tag"] = tag
            seen.add(item.id)
            matched.append(item)
        if tag_page.page < tag_page.total_pages:
            matched.append(
                SpotifyItem(
                    "__lastfm_tag_load_more__",
                    ItemKind.HEADING,
                    tr("Show more Last.fm tag results"),
                    raw={
                        "lastfm_tag_load_more": True,
                        "page": tag_page.page + 1,
                    },
                )
            )
        return matched

    def chart_results(
        self,
        country: str,
        media_type: str = "songs",
    ) -> ChartResults:
        """Return an Apple Music chart as rows, with no Spotify lookups."""
        album_chart = media_type == "albums"
        feed = (
            self.applemusic.top_albums(country, limit=CHART_SIZE)
            if album_chart
            else self.applemusic.top_songs(country, limit=CHART_SIZE)
        )
        items = [
            SpotifyItem(
                f"apple:{entry.apple_id or rank}",
                ItemKind.ALBUM if album_chart else ItemKind.TRACK,
                entry.name,
                artist=entry.artist,
                year=entry.release_date[:4],
                raw={
                    "unresolved": True,
                    "list_note": f"chart rank {rank}",
                    "chart_url": entry.url,
                },
            )
            for rank, entry in enumerate(feed.entries, start=1)
        ]
        logger.info(
            "Apple Music chart country=%s entries=%d (no Spotify lookups)",
            feed.country,
            len(items),
        )
        return ChartResults(items, feed.country, feed.fetched_at, media_type)

    @staticmethod
    def apple_release_rows(
        entries: list, kind: ItemKind
    ) -> list[SpotifyItem]:
        items = []
        for position, entry in enumerate(entries, start=1):
            released = released_on(entry.release_date)
            note = (
                tr("released {release_date}").format(
                    release_date=msg.long_date(released)
                )
                if released
                else ""
            )
            items.append(
                SpotifyItem(
                    f"apple:{entry.apple_id or position}",
                    (
                        ItemKind.AUDIOBOOK
                        if getattr(entry, "kind", "album") == "audiobook"
                        else kind
                    ),
                    entry.name,
                    artist=entry.artist,
                    raw={
                        "unresolved": True,
                        "list_note": note,
                        "chart_url": entry.url,
                    },
                )
            )
        return items

    def followed_pairs(self, kind: str) -> list[tuple[str, str]]:
        return [(a.name, a.apple_id) for a in self.followed.of_kind(kind)]

    def followed_release_results(self, country: str, days: int) -> ChartResults:
        """Recent Apple releases by followed artists and authors."""
        feed, artist_ids, author_ids = self.applemusic.followed_releases(
            country,
            self.followed_pairs(ARTIST),
            self.followed_pairs(AUTHOR),
            days=days,
        )
        self.followed.remember_apple_ids(artist_ids, ARTIST)
        self.followed.remember_apple_ids(author_ids, AUTHOR)
        window = (
            ntr(
                "released in the last {days} day",
                "released in the last {days} days",
                days,
            ).format(days=days)
            if days
            else tr("of any age")
        )
        detail = tr(
            "Releases by followed artists and authors in {country}, "
            "{window}, newest first"
        ).format(country=country_name(feed.country), window=window)
        return ChartResults(
            self.apple_release_rows(feed.entries, ItemKind.ALBUM),
            feed.country,
            feed.fetched_at,
            "new_releases",
            detail=detail,
        )

    @staticmethod
    def follow_target(item: SpotifyItem) -> tuple[str, str]:
        """The name to follow for an item, and whether it is an artist or author."""
        if item.kind in (ItemKind.AUDIOBOOK, ItemKind.CHAPTER):
            return primary_artist(item.artist), AUTHOR
        if item.kind == ItemKind.ARTIST:
            return item.name.strip(), ARTIST
        return primary_artist(item.artist), ARTIST

    @staticmethod
    def item_artist_name(item: SpotifyItem) -> str:
        return MainFrame.follow_target(item)[0]

    def toggle_follow_artist(self, name: str, kind: str = ARTIST) -> None:
        name = primary_artist(name)
        if not name:
            self.say(tr("This item has no artist to follow."))
        elif self.followed.is_following(name, kind):
            self.followed.unfollow(name, kind)
            self.say(tr("Stopped following {artist}.").format(artist=name))
        else:
            self.followed.follow(name, kind)
            self.say(
                (
                    tr(
                        "Following author {artist} for new releases. Find "
                        "them under Discover, Followed artists and authors."
                    )
                    if kind == AUTHOR
                    else tr(
                        "Following {artist} for new releases. Find them "
                        "under Discover, Followed artists and authors."
                    )
                ).format(artist=name)
            )

    def follow_current_artist(self) -> None:
        item = self.current_player_item
        if not item or not item.artist:
            self.say(msg.NOTHING_PLAYING)
            return
        name, kind = MainFrame.follow_target(item)
        self.toggle_follow_artist(name, kind)

    def check_followed_releases(self) -> None:
        """At start-up, quietly look for releases by followed artists."""
        if not (
            self.check_followed_on_start
            and self.followed.artists
            and self.spotify.connected
        ):
            return
        artists = self.followed_pairs(ARTIST)
        authors = self.followed_pairs(AUTHOR)

        def look() -> None:
            try:
                try:
                    country = (
                        self.spotify.account_country()
                        or DEFAULT_CHART_COUNTRY
                    )
                except Exception:
                    country = DEFAULT_CHART_COUNTRY
                feed, artist_ids, author_ids = (
                    self.applemusic.followed_releases(
                        country, artists, authors, days=FOLLOWED_CHECK_DAYS
                    )
                )
            except Exception:
                logger.exception("Followed artists check failed")
                return
            wx.CallAfter(
                self.finish_followed_check, feed, artist_ids, author_ids
            )

        threading.Thread(
            target=look, name="BlindSpotFollowedCheck", daemon=True
        ).start()

    def finish_followed_check(
        self,
        feed,
        artist_ids: dict[str, str],
        author_ids: dict[str, str] | None = None,
    ) -> None:
        self.followed.remember_apple_ids(artist_ids, ARTIST)
        self.followed.remember_apple_ids(author_ids or {}, AUTHOR)
        fresh_ids = set(
            self.followed.unseen([entry.apple_id for entry in feed.entries])
        )
        fresh = [entry for entry in feed.entries if entry.apple_id in fresh_ids]
        logger.info(
            "Followed artists check releases=%d new=%d",
            len(feed.entries),
            len(fresh),
        )
        if not fresh:
            return
        self.followed.mark_seen([entry.apple_id for entry in fresh])
        first = fresh[0]
        self.say(
            ntr(
                "{count} new release from followed artists and authors: "
                "{name} by {artist}. Open Discover, Followed artists and "
                "authors to see it.",
                "{count} new releases from followed artists and authors, "
                "including {name} by {artist}. Open Discover, Followed "
                "artists and authors to see them.",
                len(fresh),
            ).format(count=len(fresh), name=first.name, artist=first.artist)
        )

    def manage_followed_artists(self) -> None:
        dialog = wx.Dialog(
            self,
            title=tr("Followed artists and authors"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        panel = wx.Panel(dialog)
        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(
            wx.StaticText(
                panel,
                label=tr("Checked for new releases"),
            ),
            0,
            wx.ALL,
            8,
        )
        entries = list(self.followed.artists)

        def label(artist) -> str:
            return (
                tr("{name}, author").format(name=artist.name)
                if artist.kind == AUTHOR
                else artist.name
            )

        artists_list = wx.ListBox(
            panel, choices=[label(artist) for artist in entries]
        )
        artists_list.SetName(tr("Followed artists and authors"))
        if entries:
            artists_list.SetSelection(0)
        layout.Add(artists_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        remove = wx.Button(panel, label=tr("&Stop following"))
        close = wx.Button(panel, wx.ID_CLOSE, tr("&Close"))
        for button in (remove, close):
            buttons.Add(button, 0, wx.ALL, 5)
        layout.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 3)
        panel.SetSizer(layout)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        dialog.SetSizerAndFit(outer)
        dialog.SetMinSize((460, 320))
        silence_labels(panel, keep=())

        def remove_selected(event: wx.CommandEvent) -> None:
            index = artists_list.GetSelection()
            if index == wx.NOT_FOUND:
                return
            artist = entries.pop(index)
            self.followed.unfollow(artist.name, artist.kind)
            artists_list.Delete(index)
            if artists_list.GetCount():
                artists_list.SetSelection(min(index, artists_list.GetCount() - 1))
            self.say(tr("Stopped following {artist}.").format(artist=artist.name))

        remove.Bind(wx.EVT_BUTTON, remove_selected)
        close.Bind(wx.EVT_BUTTON, lambda event: dialog.EndModal(wx.ID_CLOSE))
        dialog.SetEscapeId(wx.ID_CLOSE)
        wx.CallAfter(artists_list.SetFocus)
        dialog.ShowModal()
        dialog.Destroy()

    def open_audiobook(self, item: SpotifyItem) -> None:
        """Show an audiobook's chapters in the Audiobooks tab."""
        self.notebook.SetSelection(5)
        self.audiobooks.loading = True
        self.run_task(
            None,
            lambda: self.spotify.audiobook_chapters(item),
            lambda chapters: self.finish_open_audiobook(item, chapters),
            failure=self.audiobooks.finish_load_error,
        )

    def finish_open_audiobook(
        self, item: SpotifyItem, chapters: list[SpotifyItem]
    ) -> None:
        self.audiobooks.show_chapters(item, chapters)
        self.audiobooks.items.SetFocus()

    def new_release_results(
        self,
        country: str,
        media_type: str,
        genre: str,
        days: int,
        keyword: str,
    ) -> ChartResults:
        """Recent Apple releases as rows, with no Spotify lookups."""
        feed = self.applemusic.new_releases(
            country,
            media_type=media_type,
            genre=genre,
            days=days,
            keyword=keyword,
        )
        # A keyword lists releases (singles included), so its rows are albums.
        kind = (
            ItemKind.TRACK
            if media_type == "songs" and not keyword
            else ItemKind.ALBUM
        )
        items = self.apple_release_rows(feed.entries, kind)
        place = country_name(feed.country)
        window = (
            ntr(
                "released in the last {days} day",
                "released in the last {days} days",
                days,
            ).format(days=days)
            if days
            else tr("of any age")
        )
        if keyword:
            detail = tr(
                "Apple Music releases matching {keyword} in {country}, "
                "{window}, newest first"
            ).format(keyword=keyword, country=place, window=window)
        else:
            genre_name = tr(
                next(name for code, name in GENRES if code == genre)
            )
            detail = tr(
                "{genre} {media} in {country} from Apple's iTunes Store "
                "chart, {window}, newest first"
            ).format(
                genre=genre_name if genre else tr("Any genre"),
                media=tr("songs") if media_type == "songs" else tr("albums"),
                country=place,
                window=window,
            )
        logger.info(
            "Apple Music new releases country=%s media=%s genre=%s days=%s "
            "keyword=%r entries=%d",
            feed.country,
            media_type,
            genre,
            days,
            keyword,
            len(items),
        )
        return ChartResults(
            items,
            feed.country,
            feed.fetched_at,
            "new_releases",
            detail=detail,
        )

    def number_ones_results(
        self,
        country: str,
        kind: str,
        year: int | None,
        day: date | None,
        by_weeks: bool,
    ) -> ChartResults:
        """Number ones for a year, or for the week containing a date."""
        songs = kind == UK_SINGLES
        item_kind = ItemKind.TRACK if songs else ItemKind.ALBUM
        which = tr("singles") if songs else tr("albums")
        rows: list[SpotifyItem] = []
        if year is not None:
            for position, entry in enumerate(
                self.numberones.year(country, kind, year, by_weeks=by_weeks),
                start=1,
            ):
                in_year = ntr(
                    "{weeks} week at number one in {year}",
                    "{weeks} weeks at number one in {year}",
                    MainFrame.week_count(entry.weeks_in_year),
                ).format(weeks=weeks_text(entry.weeks_in_year), year=year)
                if entry.total_weeks != entry.weeks_in_year:
                    in_year += tr(", {weeks} in total").format(
                        weeks=weeks_text(entry.total_weeks)
                    )
                rows.append(
                    SpotifyItem(
                        f"{country.lower()}:{kind}:{year}:{position}",
                        item_kind,
                        entry.title,
                        artist=entry.artist,
                        raw={
                            "unresolved": True,
                            "list_note": in_year,
                            "resolve_artists": artist_candidates(entry.artist),
                            "resolve_titles": title_candidates(entry.title),
                        },
                    )
                )
            detail = tr(
                "{country} number one {which} of {year}, {order}"
            ).format(
                country=country_name(country),
                which=which,
                year=year,
                order=(
                    tr("most weeks at number one first")
                    if by_weeks
                    else tr("in date order")
                ),
            )
        else:
            run = self.numberones.week(country, kind, day)
            if run:
                note = ntr(
                    "{weeks} week at number one from {date}",
                    "{weeks} weeks at number one from {date}",
                    MainFrame.week_count(run.weeks),
                ).format(
                    weeks=weeks_text(run.weeks),
                    date=msg.long_date(run.first_week),
                )
                rows.append(
                    SpotifyItem(
                        f"{country.lower()}:{kind}:{run.first_week.isoformat()}",
                        item_kind,
                        run.title,
                        artist=run.artist,
                        raw={
                            "unresolved": True,
                            "list_note": note,
                            "resolve_artists": artist_candidates(run.artist),
                            "resolve_titles": title_candidates(run.title),
                        },
                    )
                )
            detail = tr(
                "{country} number one {which} for the week of {date}"
            ).format(
                country=country_name(country),
                which=which,
                date=msg.long_date(day),
            )
        logger.info(
            "Number ones country=%s kind=%s year=%s day=%s rows=%d",
            country,
            kind,
            year,
            day,
            len(rows),
        )
        return ChartResults(rows, country, 0.0, "number_ones", detail=detail)

    @staticmethod
    def week_count(weeks: float) -> int:
        """A count that picks the right plural form for whole or half weeks."""
        return int(weeks) if weeks == int(weeks) else 2

    def historical_chart_results(self, requested: date) -> ChartResults:
        chart = self.historical_charts.chart_for_date(requested)
        items = [
            SpotifyItem(
                f"hot100:{chart.chart_date}:{entry.rank}",
                ItemKind.TRACK,
                entry.name,
                artist=entry.artist,
                raw={
                    "unresolved": True,
                    "list_note": f"chart rank {entry.rank}",
                    "chart_url": PROJECT_URL,
                },
            )
            for entry in chart.entries
        ]
        return ChartResults(
            items,
            "US",
            0.0,
            "historical_us",
            chart.chart_date.isoformat(),
        )

    def triple_j_results(self, countdown: Countdown) -> ChartResults:
        entries = self.triple_j.countdown(countdown)
        items = [
            SpotifyItem(
                f"triplej:{countdown.year}:{int(countdown.special)}:{entry.rank}",
                ItemKind.TRACK,
                entry.name,
                artist=entry.artist,
                year=entry.release_year,
                raw={
                    "unresolved": True,
                    "list_note": f"countdown rank {entry.rank}",
                    "chart_url": TRIPLE_J_ARCHIVE_URL,
                },
            )
            for entry in entries
        ]
        return ChartResults(
            items, "AU", 0.0, "triple_j", detail=countdown.label
        )

    def classic_100_results(self, countdown: ClassicCountdown) -> ChartResults:
        entries = self.classic_100.countdown(countdown)
        chart_url = (
            CLASSIC_100_CURRENT_URL
            if countdown.current
            else CLASSIC_100_ARCHIVE_URL
        )
        items = [
            SpotifyItem(
                f"classic100:{countdown.year}:{countdown.pollname}:{entry.rank}",
                ItemKind.TRACK,
                entry.work,
                artist=entry.composer,
                raw={
                    "unresolved": True,
                    "classical_work": True,
                    "classical_chart_album": True,
                    "classical_vocal": countdown.pollname == "voice",
                    "classical_source_work": entry.work,
                    "classical_source_composer": entry.composer,
                    "list_note": f"countdown rank {entry.rank}",
                    "chart_url": chart_url,
                },
            )
            for entry in entries
        ]
        return ChartResults(
            items, "AU", 0.0, "classic_100", detail=countdown.label
        )

    def rn_book_results(self, countdown: BookCountdown) -> ChartResults:
        entries = self.rn_books.countdown(countdown)
        items = [
            SpotifyItem(
                f"rnbooks:{countdown.year}:{entry.rank}",
                ItemKind.AUDIOBOOK,
                entry.title,
                artist=entry.author,
                raw={
                    "unresolved": True,
                    "list_note": f"countdown rank {entry.rank}",
                    "chart_url": (
                        RN_BOOKS_TOP_URL
                        if entry.rank <= 100
                        else RN_BOOKS_NEXT_URL
                    ),
                },
            )
            for entry in entries
        ]
        return ChartResults(
            items, "AU", 0.0, "rn_books", detail=countdown.label
        )

    def resolve_track_row(self, row: SpotifyItem) -> SpotifyItem | None:
        if row.kind == ItemKind.AUDIOBOOK:
            return self.spotify.find_audiobook(row.name, row.artist)
        if row.raw.get("classical_work"):
            vocal_work_words = {
                "cantata", "mass", "messiah", "opera", "oratorio",
                "passion", "requiem",
            }
            title_words = set(re.findall(r"[^\W_]+", row.name.casefold()))
            require_vocal = bool(
                row.raw.get("classical_vocal")
                or title_words & vocal_work_words
            )
            row.raw["classical_vocal"] = require_vocal
            excerpt_words = {
                "aria", "chorus", "duet", "overture", "prelude", "song"
            }
            is_excerpt = bool(title_words & excerpt_words)
            row.raw["classical_chart_album"] = not is_excerpt
            if is_excerpt:
                return self.spotify.find_classical_work(
                    row.name, row.artist, require_vocal=require_vocal
                )
            return self.spotify.find_classical_album(
                row.name, row.artist, require_vocal=require_vocal
            )
        find = (
            self.spotify.find_album
            if row.kind == ItemKind.ALBUM
            else self.spotify.find_track
        )
        for title in row.raw.get("resolve_titles") or [row.name]:
            for artist in row.raw.get("resolve_artists") or [row.artist]:
                found = find(title, artist)
                if found:
                    return found
        return None

    def resolve_then(
        self,
        items: list[SpotifyItem],
        retry: Callable[[], None],
    ) -> bool:
        """Look chart rows up on Spotify, then run `retry`.

        Returns True when the caller should stop because the lookup, or an
        announcement that a song is unavailable, has taken over. Rows that are
        already on Spotify pass straight through without a request.
        """
        pending = [item for item in items if item.raw.get("unresolved")]
        if not pending:
            return False
        todo = [item for item in pending if not item.raw.get("spotify_missing")]
        if not todo:
            if len(pending) == len(items):
                first = pending[0]
                self.say(tr(
                    "{name} by {artist} was not found on Spotify."
                ).format(name=first.name, artist=first.artist))
                return True
            # Others are ready; the unavailable ones simply drop out of the action.
            return False
        label = (
            tr("Finding {name} on Spotify").format(name=todo[0].name)
            if len(todo) == 1
            else tr("Finding {items} on Spotify").format(
                items=msg.counted_rows(todo, ItemKind.ALBUM, ItemKind.TRACK)
            )
        )
        self.run_task(
            label,
            lambda: [self.resolve_track_row(row) for row in todo],
            lambda results: self.finish_resolve(todo, results, retry),
        )
        return True

    def finish_resolve(
        self,
        rows: list[SpotifyItem],
        results: list[SpotifyItem | None],
        retry: Callable[[], None],
    ) -> None:
        resolved = 0
        missing: list[SpotifyItem] = []
        for row, real in zip(rows, results):
            if real is None:
                row.raw["spotify_missing"] = True
                missing.append(row)
            else:
                apply_resolved_row(row, real)
                resolved += 1
        if len(missing) == 1:
            self.say(
                tr(
                    "{name} by {artist} was not found on Spotify."
                ).format(name=missing[0].name, artist=missing[0].artist)
            )
        elif missing:
            self.say(tr(
                "{items} were not found on Spotify."
            ).format(
                items=msg.counted_rows(
                    missing, ItemKind.ALBUM, ItemKind.TRACK
                )
            ))
        if resolved:
            retry()

    def match_lastfm_tag_item(
        self,
        candidate: TaggedItem,
        category: str,
    ) -> SpotifyItem | None:
        if category == "track":
            return self.spotify.find_track(candidate.name, candidate.artist)
        if category == "album":
            return self.spotify.find_album(candidate.name, candidate.artist)
        if category == "artist":
            return self.spotify.find_artist(candidate.name)
        return None

    def first_lastfm_mix_page(
        self,
        item: SpotifyItem,
    ) -> tuple[list[SpotifyItem], list[SimilarTrack], set[str]]:
        source_artist = item.artist.split(",", 1)[0].strip()
        candidates = self.lastfm.similar_tracks(item.name, source_artist)
        seen = {item.id}
        results = self.match_lastfm_tracks(candidates[:20], seen)
        return results, candidates[20:], seen

    def open_similar_mix(self, item: SpotifyItem | None) -> None:
        if not item or item.kind != ItemKind.TRACK:
            self.say(msg.NO_ITEM_SELECTED)
            return

        self.run_task(
            (
                tr(
                    "Finding tracks similar to {name} using Last.fm. Please "
                    "wait."
                ).format(name=item.name)
            ),
            lambda: self.first_lastfm_mix_page(item),
            lambda result: self.finish_open_similar_mix(item, *result),
        )

    def finish_open_similar_mix(
        self,
        source: SpotifyItem,
        results: list[SpotifyItem],
        remaining: list[SimilarTrack] | None = None,
        seen: set[str] | None = None,
    ) -> None:
        remaining = list(remaining or [])
        seen = set(seen or {source.id})
        if not results and not remaining:
            self.say(tr(
                "No Last.fm similar-track mix found for {name}"
            ).format(name=source.name))
            return
        displayed = list(results)
        if remaining:
            displayed.append(
                SpotifyItem(
                    "__lastfm_load_more__",
                    ItemKind.HEADING,
                    tr("Load more similar tracks"),
                    raw={
                        "lastfm_load_more": True,
                        "source": source,
                        "remaining": remaining,
                        "seen": seen,
                    },
                )
            )
        self.show_lastfm_results(
            tr(
                "Tracks similar to {name}, provided by Last.fm"
            ).format(name=source.name),
            displayed,
        )
        self.say(
            tr(
                "Opened Last.fm similar-track mix for {name}, {tracks}"
            ).format(name=source.name, tracks=msg.track_count(len(results)))
        )

    def load_more_lastfm_mix(self, marker: SpotifyItem) -> None:
        source = marker.raw.get("source")
        remaining = list(marker.raw.get("remaining") or [])
        seen = set(marker.raw.get("seen") or set())
        if not isinstance(source, SpotifyItem) or not remaining:
            return
        state = self.search.history.current
        page = remaining[:20]

        def loaded(results: list[SpotifyItem]) -> None:
            if self.search.history.current is not state:
                return
            existing = [
                item
                for item in state.items
                if not item.raw.get("lastfm_load_more")
            ]
            rest = remaining[20:]
            state.items = existing + results
            if rest:
                state.items.append(
                    SpotifyItem(
                        "__lastfm_load_more__",
                        ItemKind.HEADING,
                        tr("Load more similar tracks"),
                        raw={
                            "lastfm_load_more": True,
                            "source": source,
                            "remaining": rest,
                            "seen": seen,
                        },
                    )
                )
            state.selected = len(existing) if results else max(0, len(existing) - 1)
            self.search.render(state, focus=True)
            self.search.status.SetLabel(msg.item_count(len(existing) + len(results)))
            self.say(
                ntr(
                    "Loaded {count} more similar track for {name}",
                    "Loaded {count} more similar tracks for {name}",
                    len(results),
                ).format(count=len(results), name=source.name)
            )

        self.run_task(
            tr(
                "Loading more tracks similar to {name}. Please wait."
            ).format(name=source.name),
            lambda: self.match_lastfm_tracks(page, seen),
            loaded,
        )

    def start_similar_mix(self, item: SpotifyItem | None) -> None:
        if item and self.resolve_then(
            [item],
            lambda: self.start_similar_mix(item),
        ):
            return
        if not item or item.kind != ItemKind.TRACK:
            self.say(msg.NO_ITEM_SELECTED)
            return
        self.run_task(
            (
                tr(
                    "Finding tracks similar to {name} using Last.fm. Please "
                    "wait."
                ).format(name=item.name)
            ),
            lambda: self.first_lastfm_mix_page(item),
            lambda result: self.finish_start_similar_mix(item, *result),
        )

    def finish_start_similar_mix(
        self,
        source: SpotifyItem,
        results: list[SpotifyItem],
        remaining: list[SimilarTrack] | None = None,
        seen: set[str] | None = None,
    ) -> None:
        if not results:
            self.say(tr(
                "No Last.fm similar-track mix found for {name}"
            ).format(name=source.name))
            return
        remaining = list(remaining or [])
        seen = set(seen or {source.id, *(item.id for item in results)})
        self.continuous_mix_generation = (
            getattr(self, "continuous_mix_generation", 0) + 1
        )
        self.continuous_mix = {
            "generation": self.continuous_mix_generation,
            "seen": seen,
            # The first result is started immediately. Add the remaining IDs
            # only after Spotify accepts each queue request.
            "queued": {results[0].id},
            "building": True,
        }
        continuation = lambda: self.queue_initial_similar_mix(
            source,
            results[1:],
            remaining,
            seen,
        )
        self.play_items(
            [results[0]],
            started_message=(
                ntr(
                    "Started Last.fm similar-track mix for {name}, {count} "
                    "track ready",
                    "Started Last.fm similar-track mix for {name}, {count} "
                    "tracks ready",
                    len(results),
                ).format(name=source.name, count=len(results))
            ),
            after_started=continuation,
            disable_repeat=True,
        )

    def queue_initial_similar_mix(
        self,
        source: SpotifyItem,
        results: list[SpotifyItem],
        remaining: list[SimilarTrack],
        seen: set[str],
    ) -> None:
        if not results:
            if remaining:
                self.continue_similar_mix(source, remaining, seen)
            else:
                self.finish_continuous_mix_build()
            return
        device_id = self.player_device_id()
        if not device_id:
            return
        generation = getattr(self, "continuous_mix_generation", 0)
        added: list[SpotifyItem] = []

        def remember_added() -> None:
            session = getattr(self, "continuous_mix", None)
            if not session or session.get("generation") != generation:
                return
            queued_ids = session.get("queued")
            if isinstance(queued_ids, set):
                queued_ids.update(item.id for item in added)

        def add_all() -> None:
            for item in results:
                self.spotify.add_to_queue(item, device_id)
                added.append(item)

        def queued(result: object) -> None:
            remember_added()
            self.finish_queue_many(
                results,
                announcement=(
                    ntr(
                        "Queued {count} more track in the Last.fm mix for "
                        "{name}",
                        "Queued {count} more tracks in the Last.fm mix for "
                        "{name}",
                        len(results),
                    ).format(count=len(results), name=source.name)
                ),
            )
            if remaining:
                self.continue_similar_mix(source, remaining, seen)
            else:
                self.finish_continuous_mix_build()

        def failed() -> None:
            remember_added()
            self.abandon_continuous_mix_build(generation)

        self.run_task(
            None,
            add_all,
            queued,
            failure=failed,
        )

    def continue_similar_mix(
        self,
        source: SpotifyItem,
        remaining: list[SimilarTrack],
        seen: set[str],
    ) -> None:
        generation = getattr(self, "continuous_mix_generation", 0)
        self.run_task(
            None,
            lambda: self.match_lastfm_tracks(remaining, seen),
            lambda results: self.append_similar_mix_continuation(
                source,
                results,
            ),
            failure=lambda: self.abandon_continuous_mix_build(generation),
        )

    def append_similar_mix_continuation(
        self,
        source: SpotifyItem,
        results: list[SpotifyItem],
    ) -> None:
        if not results:
            self.finish_continuous_mix_build()
            return
        device_id = self.player_device_id()
        if not device_id:
            return
        generation = getattr(self, "continuous_mix_generation", 0)

        def add_all() -> None:
            for item in results:
                self.spotify.add_to_queue(item, device_id)

        def queued(result: object) -> None:
            self.finish_queue_many(
                results,
                announcement=(
                    ntr(
                        "Added {count} more track to the Last.fm mix for "
                        "{name}",
                        "Added {count} more tracks to the Last.fm mix for "
                        "{name}",
                        len(results),
                    ).format(count=len(results), name=source.name)
                ),
            )
            session = getattr(self, "continuous_mix", None)
            if session:
                queued_ids = session.get("queued")
                if isinstance(queued_ids, set):
                    queued_ids.update(item.id for item in results)
            self.finish_continuous_mix_build()

        self.run_task(
            None,
            add_all,
            queued,
            failure=lambda: self.abandon_continuous_mix_build(generation),
        )

    def abandon_continuous_mix_build(self, generation: int) -> None:
        """Clear the building flag after a failed step so the mix can retry.

        Without this a single failed request would leave the flag set and the
        continuous mix would silently stop replenishing the queue.
        """
        session = getattr(self, "continuous_mix", None)
        if session and session.get("generation") == generation:
            session["building"] = False

    def finish_continuous_mix_build(self) -> None:
        session = getattr(self, "continuous_mix", None)
        if not session:
            return
        session["building"] = False
        item = getattr(self, "current_player_item", None)
        if item:
            self.update_continuous_similar_mix(item)

    def update_continuous_similar_mix(self, item: SpotifyItem) -> None:
        session = getattr(self, "continuous_mix", None)
        if not session:
            return
        seen = session.get("seen")
        queued = session.get("queued")
        if not isinstance(seen, set) or not isinstance(queued, set):
            self.continuous_mix = None
            return
        if item.id not in seen:
            self.continuous_mix = None
            return
        queued.discard(item.id)
        if session.get("building") or len(queued) > 10:
            return
        session["building"] = True
        generation = int(session.get("generation") or 0)
        source_artist = item.artist.split(",", 1)[0].strip()

        def find_more() -> list[SpotifyItem]:
            candidates = self.lastfm.similar_tracks(item.name, source_artist)
            return self.match_lastfm_tracks(candidates, seen)

        self.run_task(
            None,
            find_more,
            lambda results: self.queue_continuous_similar_results(
                item,
                results,
                generation,
            ),
            failure=lambda: self.abandon_continuous_mix_build(generation),
        )

    def queue_continuous_similar_results(
        self,
        source: SpotifyItem,
        results: list[SpotifyItem],
        generation: int,
    ) -> None:
        session = getattr(self, "continuous_mix", None)
        if not session or session.get("generation") != generation:
            return
        if not results:
            session["building"] = False
            return
        device_id = self.player_device_id()
        if not device_id:
            session["building"] = False
            return

        def add_all() -> None:
            for result in results:
                self.spotify.add_to_queue(result, device_id)

        def queued(result: object) -> None:
            current_session = getattr(self, "continuous_mix", None)
            if not current_session or current_session.get("generation") != generation:
                return
            queued_ids = current_session.get("queued")
            if isinstance(queued_ids, set):
                queued_ids.update(item.id for item in results)
            current_session["building"] = False
            self.finish_queue_many(results)

        self.run_task(
            None,
            add_all,
            queued,
            failure=lambda: self.abandon_continuous_mix_build(generation),
        )

    def queue_similar_mix(self, item: SpotifyItem | None) -> None:
        if not item or item.kind != ItemKind.TRACK:
            self.say(msg.NO_ITEM_SELECTED)
            return
        self.run_task(
            (
                tr(
                    "Finding tracks similar to {name} using Last.fm. Please "
                    "wait."
                ).format(name=item.name)
            ),
            lambda: self.lastfm_tracks_for(item),
            lambda results: self.finish_queue_similar_mix(item, results),
        )

    def finish_queue_similar_mix(
        self,
        source: SpotifyItem,
        results: list[SpotifyItem],
    ) -> None:
        if not results:
            self.say(tr(
                "No Last.fm similar-track mix found for {name}"
            ).format(name=source.name))
            return
        announcement = tr(
            "Added Last.fm similar-track mix for {name} after the "
            "current queue, {tracks}"
        ).format(name=source.name, tracks=msg.track_count(len(results)))
        if self.queue_should_be_deferred():
            self.deferred_queue_items.extend(results)
            self.finish_queue_many(results, announcement=announcement)
            return
        device_id = self.player_device_id()
        if not device_id:
            return

        def add_all() -> None:
            for result in results:
                self.spotify.add_to_queue(result, device_id)

        self.run_task(
            None,
            add_all,
            lambda result: self.finish_queue_many(
                results,
                announcement=announcement,
            ),
        )

    def current_track_for_similar_mix(self) -> SpotifyItem | None:
        item = self.current_player_item
        if getattr(self, "pending_resume", None) or not item:
            self.say(msg.NOTHING_PLAYING)
            return None
        if item.kind != ItemKind.TRACK:
            self.say(tr("The currently playing item is not a track"))
            return None
        return item

    def open_similar_mix_for_current_track(self) -> None:
        item = self.current_track_for_similar_mix()
        if item:
            self.open_similar_mix(item)

    def start_similar_mix_for_current_track(self) -> None:
        item = self.current_track_for_similar_mix()
        if item:
            self.start_similar_mix(item)

    def queue_similar_mix_for_current_track(self) -> None:
        item = self.current_track_for_similar_mix()
        if item:
            self.queue_similar_mix(item)

    def current_track(self) -> SpotifyItem | None:
        item = self.current_player_item
        if not item or item.kind != ItemKind.TRACK:
            self.say(msg.NOTHING_PLAYING)
            return None
        return item

    def find_alternate_versions_for(self, item: SpotifyItem) -> None:
        """Offer playable alternatives without modifying a playlist."""
        work = str(item.raw.get("classical_source_work") or "")
        composer = str(item.raw.get("classical_source_composer") or "")
        classical_album = bool(item.raw.get("classical_chart_album"))
        if not (work and composer):
            source_title = item.name if item.kind == ItemKind.ALBUM else item.album
            source_words = set(
                re.findall(r"[^\W_]+", source_title.casefold())
            )
            classical_markers = {
                "bwv", "cantata", "concerto", "hwv", "mass", "messiah",
                "opera", "oratorio", "passion", "requiem", "rv", "sonata",
                "symphony",
            }
            if source_title and source_words & classical_markers:
                composer = item.artist.split(",", 1)[0].strip()
                work = re.sub(
                    r"\s*\([^)]*\b(?:complete|recording|version)\b[^)]*\)\s*$",
                    "",
                    source_title,
                    flags=re.IGNORECASE,
                ).strip()
                surname = composer.rsplit(" ", 1)[-1]
                work = re.sub(
                    rf"^{re.escape(surname)}\s*:\s*",
                    "",
                    work,
                    flags=re.IGNORECASE,
                )
                classical_album = bool(composer and work)
        if work and composer and classical_album:
            vocal_words = {
                "cantata", "mass", "messiah", "opera", "oratorio",
                "passion", "requiem",
            }
            require_vocal = bool(
                item.raw.get("classical_vocal")
                or set(re.findall(r"[^\W_]+", work.casefold())) & vocal_words
            )
            logger.info(
                "Alternate versions route=classical-album work=%r composer=%r",
                work,
                composer,
            )
            worker = lambda: self.spotify.alternate_classical_albums(
                work,
                composer,
                require_vocal=require_vocal,
                exclude_uri=item.uri,
            )
        else:
            logger.info(
                "Alternate versions route=track name=%r artist=%r",
                item.name,
                item.artist,
            )
            worker = lambda: self.spotify.alternate_versions(item)
        self.run_task(
            None,
            worker,
            lambda candidates: self.show_playable_alternate_versions(
                item, candidates
            ),
        )

    def show_playable_alternate_versions(
        self,
        original: SpotifyItem,
        candidates: list[SpotifyItem],
    ) -> None:
        if not candidates:
            self.say(msg.NO_ALTERNATE_VERSIONS)
            return
        dialog = AlternateVersionsDialog(self, original, candidates)
        try:
            dialog.ShowModal()
        finally:
            dialog.Destroy()

    def find_alternate_versions_for_current(self) -> None:
        item = self.current_track()
        if item:
            source = getattr(self, "current_classical_alternate_source", None)
            context_uri = str(
                getattr(self, "current_player_state", {}).get(
                    "context_uri", ""
                )
            )
            self.find_alternate_versions_for(
                source
                if source and source.uri == context_uri
                else item
            )

    def show_current_song_story(self) -> None:
        item = self.current_track()
        if item:
            self.show_song_story(item)

    def open_current_album(self) -> None:
        item = self.current_track()
        if item:
            self.open_album_for_track(item)

    def open_focused_or_current_album(self) -> None:
        """Open the focused item's album, falling back to Now Playing."""
        focused_list = item_list_ancestor(wx.Window.FindFocus())
        if focused_list:
            item = focused_list.selected_item()
            if not item:
                return
            if item.kind == ItemKind.TRACK:
                self.open_selected_track_album(item)
            elif item.kind == ItemKind.ALBUM:
                self.run_task(
                    msg.opening(item.name),
                    lambda: self.spotify.children(item),
                    lambda tracks: self.finish_open_album(item, tracks),
                )
            return
        self.open_current_album()

    def show_current_artist_albums(self) -> None:
        item = self.current_track()
        if not item:
            return
        for artist in item.raw.get("artists") or []:
            artist_id = str(artist.get("id") or "")
            artist_name = str(artist.get("name") or "")
            if artist_id and artist_name:
                self.show_artist_albums(artist_id, artist_name)
                return
        self.say(tr("This track has no artist to show."))

    def find_covers_for_current(self) -> None:
        item = self.current_track()
        if item:
            self.find_covers_for(item)

    def browse_genres_for_current(self) -> None:
        item = self.current_track()
        if item:
            self.browse_genres_for(item)

    def add_current_to_playlist(self) -> None:
        item = self.current_track()
        if item:
            self.choose_playlist_for_item(item)

    def show_song_story(self, item: SpotifyItem) -> None:
        """Explain a track using its English Wikipedia article, if it has one."""
        self.run_task(
            tr("Looking up {name} on Wikipedia.").format(name=item.name),
            lambda: self.wikipedia.song_story(item.name, item.artist),
            lambda story: self.finish_song_story(item, story),
        )

    @staticmethod
    def unambiguous_artist_name(item: SpotifyItem) -> str:
        if item.kind == ItemKind.ARTIST:
            return item.name.strip()
        if item.kind not in (ItemKind.TRACK, ItemKind.ALBUM):
            return ""
        artists = item.raw.get("artists") or []
        if len(artists) != 1:
            return ""
        return str(artists[0].get("name") or "").strip()

    def show_artist_story(self, name: str) -> None:
        item = SpotifyItem("wikipedia-artist", ItemKind.ARTIST, name)
        self.run_task(
            tr("Looking up {name} on Wikipedia.").format(name=name),
            lambda: self.wikipedia.artist_story(name),
            lambda story: self.finish_song_story(item, story),
        )

    def show_current_music_details(self) -> None:
        item = self.current_track()
        if item:
            self.show_music_details(item)

    def show_music_details(self, item: SpotifyItem) -> None:
        self.run_task(
            tr("Loading album and recording information for {name}").format(
                name=item.name
            ),
            lambda: self.spotify.music_details(item),
            lambda details: self.finish_music_details(item, details),
        )

    def finish_music_details(self, item: SpotifyItem, details: dict) -> None:
        text = music_details_text(details)
        if not text:
            self.say(
                tr("No additional album or recording information was found.")
            )
            return
        dialog = MusicDetailsDialog(self, item.name, text)
        dialog.ShowModal()
        dialog.Destroy()

    def finish_song_story(self, item: SpotifyItem, story: SongStory) -> None:
        dialog = SongStoryDialog(self, item, story)
        dialog.ShowModal()
        dialog.Destroy()

    def find_covers_for(self, item: SpotifyItem) -> None:
        """List other artists' versions of a track, using MusicBrainz."""
        title = base_track_title(item.name)
        artist = item.artist.split(",", 1)[0].strip()
        self.run_task(
            tr(
                "Finding covers of {name} using MusicBrainz. This can take "
                "up to 20 seconds."
            ).format(name=item.name),
            lambda: self.musicbrainz.find_covers(title, artist, item.duration_ms),
            lambda result: self.show_covers(item, result),
        )

    def show_covers(self, source: SpotifyItem, result: CoverResults) -> None:
        if not result.covers:
            self.say(
                tr(
                    "MusicBrainz lists no other studio versions of {name}."
                ).format(name=source.name)
            )
            return
        rows = [
            SpotifyItem(
                f"musicbrainz:{cover.recording_id}",
                ItemKind.TRACK,
                cover.title,
                artist=cover.artist,
                year=cover.year,
                raw={
                    "unresolved": True,
                    "artist_first": True,
                    **({"list_note": "cover"} if cover.marked_cover else {}),
                },
            )
            for cover in result.covers
        ]
        self.show_lastfm_results(
            tr(
                "Covers of {base_track_title}, provided by MusicBrainz"
            ).format(base_track_title=base_track_title(source.name)),
            rows,
        )
        self.search.status.SetLabel(cover_summary(source, result))

    def browse_genres_for(self, item: SpotifyItem) -> None:
        """Offer the item's Last.fm genre tags, then browse the one chosen."""
        kind = "track" if item.kind == ItemKind.TRACK else "artist"
        artist = item.artist.split(",", 1)[0].strip() if kind == "track" else ""
        self.run_task(
            tr(
                "Finding genres for {name} using Last.fm"
            ).format(name=item.name),
            lambda: self.lastfm.top_genre_tags(kind, item.name, artist),
            lambda tags: self.choose_genre(item, kind, tags),
        )

    def choose_genre(
        self,
        item: SpotifyItem,
        category: str,
        tags: list[GenreTag],
    ) -> None:
        if not tags:
            self.say(tr(
                "Last.fm has no genre tags for {name}."
            ).format(name=item.name))
            return
        dialog = wx.SingleChoiceDialog(
            self,
            (
                tr(
                    "Last.fm community tags for {name}. Choose one to browse "
                    "more songs with that tag."
                )
                if category == "track"
                else tr(
                    "Last.fm community tags for {name}. Choose one to browse "
                    "more artists with that tag."
                )
            ).format(name=item.name),
            tr("Browse genres"),
            [tr(
                "{name} ({weight} out of 100)"
            ).format(name=tag.name, weight=tag.weight) for tag in tags],
        )
        dialog.SetSelection(0)
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        tag = tags[dialog.GetSelection()].name
        dialog.Destroy()
        self.run_task(
            msg.finding_tag_results(tag, category),
            lambda: self.lastfm_tag_results(tag, category),
            lambda items: self.finish_browse_genre(tag, category, items),
        )

    def finish_browse_genre(
        self,
        tag: str,
        category: str,
        items: list[SpotifyItem],
    ) -> None:
        # Show the result as the Search tab's own Genre search, so its
        # controls, Load more and Backspace all behave as they do there.
        self.notebook.SetSelection(0)
        self.search.query.SetValue("")
        self.search.tag.SetValue(tag)
        self.search.categories.SetSelection(SEARCH_TYPES.index(category))
        self.search.show_tag_search("", tag, category, items)

    def find_similar_artists(self, item: SpotifyItem) -> None:
        def load() -> list[SpotifyItem]:
            results = self.lastfm.similar_artists(item.name)
            matched = []
            seen = set()
            for result in results:
                artist = self.spotify.find_artist(result.name)
                if artist and artist.id not in seen:
                    artist.raw["lastfm_url"] = result.url
                    seen.add(artist.id)
                    matched.append(artist)
            return matched

        self.run_task(
            tr(
                "Finding artists similar to {name} using Last.fm"
            ).format(name=item.name),
            load,
            lambda results: self.show_lastfm_results(
                tr(
                    "Artists similar to {name}, provided by Last.fm"
                ).format(name=item.name), results
            ),
        )

    def show_lastfm_results(
        self, title: str, results: list[SpotifyItem]
    ) -> None:
        state = ViewState(title, results)
        self.notebook.SetSelection(0)
        self.search.history.push(state)
        self.search.render(state, focus=True)
        self.search.status.SetLabel(msg.item_count(len(results)))

    def show_album_artwork(self, item: SpotifyItem) -> None:
        url = album_artwork_url(item)
        if not url:
            self.say(msg.ALBUM_ARTWORK_UNAVAILABLE)
            wx.MessageBox(
                msg.ALBUM_ARTWORK_UNAVAILABLE,
                "BlindSpot",
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            return
        self.run_task(
            msg.LOADING_ALBUM_ARTWORK,
            lambda: download_album_artwork(url),
            lambda artwork: self.display_album_artwork(item, artwork),
        )

    def display_album_artwork(self, item: SpotifyItem, artwork: bytes) -> None:
        try:
            dialog = AlbumArtworkDialog(self, item, artwork)
        except ValueError as error:
            self.show_error(str(error))
            return
        dialog.ShowModal()
        dialog.Destroy()

    def find_episode_download(self, item: SpotifyItem) -> None:
        self.run_task(
            msg.FINDING_EPISODE_DOWNLOAD,
            lambda: find_episode_download(item),
            self.choose_episode_destination,
        )

    def show_transcript_for_item(self, item: SpotifyItem) -> None:
        cache = TranscriptCache(self.store)
        cached = cache.read(item.id)
        local_path_value = str(item.raw.get("local_audio_path") or "")
        if item.id.startswith("local-audio:"):
            local_path = Path(local_path_value) if local_path_value else None
            if local_path and local_path.is_file():
                logger.info(
                    "Routing local-audio transcript to original file item=%s",
                    item.id,
                )
                self.transcribe_local_audio_path(local_path.resolve())
                return
            if cached:
                logger.warning(
                    "Original local audio unavailable; displaying cached transcript "
                    "item=%s complete=%s",
                    item.id,
                    cached.complete,
                )
                self.say(
                    tr(
                        "The original local audio file is unavailable. "
                        "Showing the cached transcript without playback."
                    )
                )
                self.display_transcript(item, cached)
                return
            self.say(tr("The original local audio file is unavailable."))
            return
        audio_path = cache.audio_path(item.id)
        transcript_path = cache.path(item.id)
        matched_whisper_audio = (
            audio_path.is_file()
            and transcript_path.is_file()
            and transcript_path.stat().st_mtime >= audio_path.stat().st_mtime
        )
        if (
            cached
            and cached.complete
            and (cached.source != "whisper" or matched_whisper_audio)
        ):
            if audio_path.is_file():
                self.use_transcript_audio(item, audio_path)
            self.display_transcript(item, cached)
            return
        existing = cached if cached and cached.source != "whisper" else None

        def find() -> tuple[EpisodeMedia, Transcript | None]:
            media = find_episode_media(item)
            return media, fetch_publisher_transcript(media)

        self.run_task(
            tr("Looking for an episode transcript."),
            find,
            lambda result: self.finish_find_transcript(
                item, cache, result[0], result[1], existing
            ),
            requires_spotify=False,
        )

    def finish_find_transcript(
        self,
        item: SpotifyItem,
        cache: TranscriptCache,
        media: EpisodeMedia,
        transcript: Transcript | None,
        existing: Transcript | None = None,
    ) -> None:
        if transcript:
            cache.write(item.id, transcript)
            self.display_transcript(item, transcript)
            return

        transcriber = WhisperTranscriber(self.store)
        if not transcriber.ready:
            answer = wx.MessageBox(
                tr(
                    "This episode has no publisher transcript. BlindSpot can "
                    "download optional local transcription components and a "
                    "Whisper model. The one-time download is about 150 MB and "
                    "the installed files are kept in the portable data "
                    "directory. To keep transcript timing accurate when "
                    "podcasts insert changing ads, the transcribed episode "
                    "audio is also kept in that directory. "
                    "Download the components now?"
                ),
                tr("Set up podcast transcription"),
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
                self,
            )
            if answer != wx.YES:
                self.say(tr("Transcription was not started."))
                return
            self.run_task(
                tr("Setting up optional podcast transcription."),
                lambda: transcriber.install(
                    lambda message: wx.CallAfter(self.say, message)
                ),
                lambda result: self.start_whisper_transcript(
                    item, media, cache, transcriber, existing
                ),
                requires_spotify=False,
            )
            return
        self.start_whisper_transcript(
            item, media, cache, transcriber, existing
        )

    def display_transcript(
        self,
        item: SpotifyItem,
        transcript: Transcript,
    ) -> None:
        transcript = self.cached_transcript_translation(item, transcript)
        dialog = TranscriptDialog(self, item, transcript)
        dialog.ShowModal()
        dialog.Destroy()

    def use_transcript_audio(self, item: SpotifyItem, path: Path) -> None:
        """Play the same cached bytes Whisper timed, including inserted ads."""
        if not self.player:
            return
        url = self.player.serve_media(item.id, path)
        if url:
            item.raw["audio_url"] = url

    def start_whisper_transcript(
        self,
        item: SpotifyItem,
        media: EpisodeMedia,
        cache: TranscriptCache,
        transcriber: WhisperTranscriber,
        existing: Transcript | None = None,
    ) -> None:
        dialog = TranscriptDialog(self, item, existing)
        dialog.begin(transcriber, media, cache)
        dialog.ShowModal()
        dialog.Destroy()

    def choose_episode_destination(self, download: PodcastDownload) -> None:
        dialog = wx.FileDialog(
            self,
            tr("Download podcast episode"),
            defaultFile=download.filename,
            wildcard=(
                tr("Audio files")
                + "|*.mp3;*.m4a;*.aac;*.ogg;*.opus;*.wav;*.flac;*.mp4;*.m4v;"
                "*.webm|"
                + tr("All files")
                + "|*.*"
            ),
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        )
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        destination = Path(dialog.GetPath())
        dialog.Destroy()
        self.run_task(
            msg.DOWNLOADING_EPISODE,
            lambda: download_episode(download, destination),
            lambda result: self.say(msg.EPISODE_DOWNLOADED),
        )
