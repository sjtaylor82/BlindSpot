"""Central source for user-facing messages, prompts, and status text."""

from __future__ import annotations

from collections.abc import Iterable


SETUP_WELCOME = (
    "Welcome to BlindSpot\n"
    "This app requires a developer account. This is a one-time setup."
)
SETUP_INSTRUCTIONS = (
    "1. Open the Spotify Developer Dashboard and create an app.\n"
    "2. Use BlindSpot Personal as its name. Select both Web API "
    "and Web Playback SDK.\n"
    "3. Add this redirect URI: http://127.0.0.1:43821/callback\n"
    "4. Open the app's settings, copy its Client ID, and paste it here.\n"
    "Do not copy or share the Client Secret."
)
PASTE_CLIENT_ID = "Paste the Client ID from your Spotify application."
ENTER_CLIENT_ID = "Enter a Spotify Client ID first."
CONNECT_FIRST = "Connect BlindSpot to Spotify first."
ALREADY_RUNNING = "BlindSpot is already running."

SYNCED_LYRICS_UNAVAILABLE = "Synced lyrics unavailable for this track."
MOVE_TO_SYNCED_LINE = "Move to a synced lyric line."
ENTER_SEARCH_QUERY = "Enter a search query."
SEARCHING_SPOTIFY = "Searching Spotify"
LOADING_MORE_RESULTS = "Loading more Spotify results"
NO_MORE_RESULTS = "No more results."
READ_ONLY = "Read only."
RENAMED = "Renamed."
REMOVED_FROM_LIBRARY = "Removed from library."
NO_DESCRIPTION = "No description available."
NO_ITEM_SELECTED = "No item selected."
SELECT_PLAYABLE_ITEM = "Select a playable item."
NOTHING_PLAYING = "Nothing playing."
NO_TRACK = "No track."
NOTHING_CURRENTLY_PLAYING = "Nothing playing."
QUEUE_EMPTY = "Queue empty."
INSTRUMENTAL_TRACK = "This track is instrumental."
NO_CURRENT_TRACK = "Nothing playing."
BOOKMARK_DELETED = "Bookmark deleted."
SELECT_TRACK_OR_EPISODE = "Select a track or episode."
NO_PLAYLISTS = "No playlists."
CHOOSE_PLAYLIST = "Choose a playlist."
ENTER_PLAYLIST_NAME = "Enter a new playlist name."
ADDED = "Added."
READY = "Ready."
NO_PLAYABLE_TRACKS = "No playable tracks selected."
QUEUED = "Queued."
FINDING_EPISODE_DOWNLOAD = "Finding episode download."
DOWNLOADING_EPISODE = "Downloading episode."
EPISODE_DOWNLOADED = "Episode downloaded."
MUTED = "Muted."
UNMUTED = "Unmuted."
SHUFFLE_ON = "Shuffle on."
SHUFFLE_OFF = "Shuffle off."
REPEAT_OFF = "Repeat off."
REPEAT_ALL = "Repeat all."
REPEAT_ONE = "Repeat one."
LIKED = "Liked."
UNLIKED = "Unliked."

PLAYLISTS_LOAD_HINT = "Move into the list to load playlists."
AUDIOBOOKS_LOAD_HINT = "Move into the list to load saved audiobooks."
PODCASTS_LOAD_HINT = "Move into the list to load saved podcasts."
AUTHORIZATION_REQUIRED = "Spotify authorization required."
NOT_CONNECTED = "Not connected to Spotify. Use the Account menu to connect."
PERMISSIONS_REQUIRED = (
    "Browsing is connected. Refresh Spotify permissions from "
    "the Account menu to enable BlindSpot's player."
)
MAIN_TABS = "Main tabs."
RECENT_PERMISSION_PROMPT = (
    "Recently Played needs an additional Spotify permission. "
    "Authorize it now?"
)
RECENT_NOT_AUTHORIZED = "Recently Played was not authorized."
AUTHORIZATION_IN_PROGRESS = "authorization already in progress."
COMPLETE_LOGIN = "Complete Spotify login in your browser."
RECENT_AUTH_NOT_COMPLETED = "Recently Played authorization was not completed."
SIGN_OUT_PROMPT = "Erase Spotify session from folder?"
SIGNED_OUT = "Signed out and erased credentials."
MANUAL_NOT_FOUND = "manual not found."
UPDATE_DOWNLOAD_FAILED = "The BlindSpot update could not be downloaded."
UPDATE_CHECK_FAILED = "BlindSpot could not check for updates."
UPDATE_INSTALL_PROMPT = "Download and install the update now?"
UPDATE_PAGE_PROMPT = "Open the download page now?"
RECENT_AUTHORIZED = "Recently Played authorized."
RECENT_ACCESS_NOT_GRANTED_STATUS = (
    "Spotify did not grant access to Recently Played."
)
RECENT_ACCESS_NOT_GRANTED = (
    "Spotify did not grant Recently Played access for this app. "
    "The tab is unavailable."
)
CONNECTED = "Connected to Spotify. Starting player."
NO_SONG_SELECTED = "No song selected."
SLEEP_END_OF_TRACK = "Sleep timer set for end of track."
SLEEP_CANCELLED = "Sleep timer cancelled."
NO_SLEEP_TIMER = "No sleep timer set."
SLEEP_STOPPED = "Sleep timer. Playback stopped."
NO_DEVICES = (
    "No controllable devices available. "
    "Open Spotify on the device and try again."
)
SLEEP_TIMER_PROMPT = "Choose when playback should stop."
PLAYER_NOT_READY = "not ready."
PLAYER_STARTING = "player starting."
WEBVIEW2_REQUIRED = (
    "BlindSpot's player requires Microsoft WebView2. "
    "Install the Evergreen WebView2 Runtime and restart BlindSpot."
)
BROWSER_COMPONENT_FAILED = (
    "BlindSpot could not start the system web browser component."
)
PLAYBACK_DEVICE_OFFLINE = "BlindSpot's Spotify playback device went offline."
AUTOPLAY_BLOCKED = (
    "The browser blocked automatic playback. "
    "Press Play again to activate BlindSpot's player."
)
NO_TRACKS = "No tracks."
UNKNOWN_PLAYER_ERROR = "Unknown Spotify player error"
WEB_PLAYER_PAGE_FAILED = "The web player page could not load."
GETTING_LYRICS = "Getting lyrics."
GETTING_DEVICES = "Getting available devices."
DEVICE_SELECTION_PROMPT = "Select the Spotify Connect device for playback."
JUMP_TIME_PROMPT = (
    "Enter seconds, minutes and seconds, or hours, minutes and seconds."
)
JUMP_TIME_INVALID = "Enter a time such as 90, 1:30, or 1:02:30."

AUTHORIZATION_TIMEOUT = (
    "Spotify authorization timed out. BlindSpot is still available; "
    "try again from the Account menu."
)
AUTH_STATE_MISMATCH = "Spotify login state did not match"
AUTH_CODE_MISSING = "Spotify authorization code was missing"
CALLBACK_RECEIVED = (
    "BlindSpot received the Spotify response. You may close this browser tab."
)

NOT_ENOUGH_LYRIC_INFO = "There is not enough track information to find lyrics."
LYRICS_UNAVAILABLE_TRACK = "Lyrics unavailable for this track."
LRCLIB_BUSY = "LRCLIB is busy. Please try again later."
LYRICS_RETRIEVAL_FAILED = "Lyrics could not be retrieved."
PHRASE_END_UNAVAILABLE = "The end of this lyric line is unavailable."
INVALID_PLAYLIST_POSITION = "Enter a valid playlist position."
NO_ALTERNATE_VERSIONS = "No alternate versions were found."
DUPLICATE_PLAYLIST_REPLACEMENT = (
    "This recording occurs more than once in the playlist, so BlindSpot "
    "cannot safely replace only this occurrence."
)
PLAYLIST_TRACK_REPLACED = "Playlist track replaced."
LOGS_FOLDER_OPEN_FAILED = "The BlindSpot logs folder could not be opened."

PLAYLIST_ITEMS_UNAVAILABLE = (
    "Individual tracks can't be browsed. Press F4 to play the playlist."
)
ALBUM_NOT_PROVIDED = "Spotify did not provide an album for this track."
RECENT_PERMISSION_REQUIRED = (
    "Recently Played needs an additional Spotify permission."
)
NO_CONTROLLABLE_DEVICE = (
    "No controllable Spotify device is available. "
    "Open Spotify on your computer, phone, or speaker, then try again."
)
PLAYBACK_DEVICE_INACTIVE = "playback device not active."
CURRENT_VOLUME_UNAVAILABLE = "Spotify did not report the current volume."
AUDIOBOOK_PLAYBACK_UNAVAILABLE = (
    "Spotify cannot play this audiobook chapter for this account. "
    "Audiobook playback depends on the individual's Spotify plan "
    "and available listening time."
)
SPOTIFY_EMPTY_RESPONSE = "Spotify returned an empty response."

UPDATE_HELPER_STOPPED = "The update helper stopped during preparation."
UPDATE_PREPARATION_TIMEOUT = "Update preparation timed out."
UPDATE_PREPARATION_FAILED = "The update could not be prepared."


def shortcut_capture(action: str) -> str:
    return f"Press the shortcut for {action}. Press Escape to cancel."


def shortcut_replace(shortcut: str, action: str) -> str:
    return f"{shortcut} is assigned to {action}. Replace assignment?"


def lyric_boundary(boundary: str) -> str:
    return f"{boundary} synced lyric line."


def playlist_position_prompt(total: int) -> str:
    return f"Enter a position from 1 to {total}."


def playlist_item_moved(position: int, total: int) -> str:
    return f"Moved to position {position} of {total}."


def replace_playlist_track(original: str, replacement: str) -> str:
    return f'Replace "{original}" with "{replacement}"?'


def lyric_timing(timing: str) -> str:
    return f"Lyrics now {timing}."


def result_count(count: int, query: str) -> str:
    return f"{count} results." if count else f"No results for {query}."


def item_count(count: int) -> str:
    return f"{count} items."


def named_item_count(name: str, count: int) -> str:
    return f"{name}. {count} items."


def loading(title: str) -> str:
    return f"Loading {title}"


def load_hint(title: str) -> str:
    return f"Press F5 to load {title}."


def opening(name: str) -> str:
    return f"Opening {name}"


def opening_album(name: str) -> str:
    return f"Opening album for {name}"


def remove_playlist(name: str) -> str:
    return f"Remove {name} from your Spotify library?"


def audiobook_resume_permission(count: int) -> str:
    return (
        f"{count} items. Refresh Spotify permissions "
        "to read chapter resume positions."
    )


def saved_podcasts(shows: int, episodes: int) -> str:
    show_word = "podcast" if shows == 1 else "podcasts"
    episode_word = "episode" if episodes == 1 else "episodes"
    return f"{shows} {show_word} and {episodes} saved {episode_word}."


def unsubscribe_podcast(name: str) -> str:
    return f"Unsubscribe from {name}?"


def remove_saved_episode(name: str) -> str:
    return f"Remove {name}?"


def update_available(version: str, action: str) -> str:
    return f"BlindSpot {version} is available.\n\n{action}"


def update_current(version: str) -> str:
    return f"BlindSpot {version} is up to date."


def about(version: str) -> str:
    return (
        "BlindSpot\n"
        f"Build {version}\n"
        "Copyright © 2026 Sam Taylor\n"
        "A portable, accessible Spotify client."
    )


def shortcut_registration_failed(shortcuts: Iterable[str]) -> str:
    return (
        "Could not register global "
        + ", ".join(shortcuts)
        + ". Another app may already be using it."
    )


def sleep_minutes(minutes: int) -> str:
    return f"Sleep timer set for {minutes} minutes."


def player_starting(name: str) -> str:
    return (
        "player starting. "
    )


def playing_on(name: str) -> str:
    return f"Playing on {name}."


def transferring_to(name: str) -> str:
    return f"Transferring playback to {name}."


def playing(name: str) -> str:
    return f"Playing {name}"


def unsupported_volume(name: str) -> str:
    return f"{name} does not support volume control."


def bookmark_saved(position: str) -> str:
    return f"Bookmark saved at {position}."


def resumed(name: str, position: str) -> str:
    return f"Resumed {name} at {position}."


def queued_count(count: int) -> str:
    return f"Queued {count} {'track' if count == 1 else 'tracks'}."


def playlist_information(
    owner: str,
    total: int | None,
    public: bool | None,
    collaborative: bool,
    description: str,
) -> str:
    visibility = (
        "Public"
        if public is True
        else "Private"
        if public is False
        else "Unspecified"
    )
    lines = [
        f"Owner: {owner or 'Unknown'}",
        f"Tracks: {total if total is not None else 'Unknown'}",
        f"Visibility: {visibility}",
        f"Collaborative: {'Yes' if collaborative else 'No'}",
    ]
    if description:
        lines.extend(("", f"Description: {description}"))
    return "\n".join(lines)


def spotify_error(status: int, detail: str) -> str:
    return f"Spotify returned {status}: {detail}"


def spotify_contact_failed(detail: object) -> str:
    return f"Could not contact Spotify: {detail}"


def spotify_login_failed(detail: str) -> str:
    return f"Spotify login failed: {detail}"


def spotify_player_error(source: str, detail: str) -> str:
    return f"Spotify {source}: {detail}"


def lyrics_unavailable(name: str) -> str:
    return f"Lyrics unavailable for {name}."


def lrclib_retry(seconds: str) -> str:
    return f"LRCLIB is busy. Try again in {seconds} seconds."


def lrclib_error(status: int) -> str:
    return f"LRCLIB returned error {status}."
