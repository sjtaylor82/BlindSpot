"""Central source for user-facing messages, prompts, and status text."""

from __future__ import annotations

from collections.abc import Iterable

from datetime import date

from .i18n import ntr, on_language_change, ptr, tr, tr_noop


SETUP_WELCOME = tr_noop(
    "Welcome to BlindSpot\n"
    "This app requires a developer account. This is a one-time setup."
)
SETUP_INSTRUCTIONS = tr_noop(
    "1. Open the Spotify Developer Dashboard and create an app.\n"
    "2. Use BlindSpot Personal as its name. Select both Web API and Web "
    "Playback SDK.\n"
    "3. Add this redirect URI: http://127.0.0.1:43821/callback\n"
    "4. Open the app's settings, copy its Client ID, and paste it here.\n"
    "Do not copy or share the Client Secret."
)
PASTE_CLIENT_ID = tr_noop(
    "Paste the Client ID from your Spotify application."
)
ENTER_CLIENT_ID = tr_noop("Enter a Spotify Client ID first.")
CONNECT_FIRST = tr_noop("Connect BlindSpot to Spotify first.")
ALREADY_RUNNING = tr_noop("BlindSpot is already running.")

SYNCED_LYRICS_UNAVAILABLE = tr_noop(
    "Synced lyrics unavailable for this track."
)
MOVE_TO_SYNCED_LINE = tr_noop("Move to a synced lyric line.")
ENTER_SEARCH_QUERY = tr_noop("Enter a search query.")
SEARCHING_SPOTIFY = tr_noop("Searching Spotify")
LOADING_MORE_RESULTS = tr_noop("Loading more Spotify results")
NO_MORE_RESULTS = tr_noop("No more results.")
READ_ONLY = tr_noop("Read only.")
RENAMED = tr_noop("Renamed.")
REMOVED_FROM_LIBRARY = tr_noop("Removed from library.")
NO_DESCRIPTION = tr_noop("No description available.")
NO_ITEM_SELECTED = tr_noop("No item selected.")
SELECT_PLAYABLE_ITEM = tr_noop("Select a playable item.")
NOTHING_PLAYING = tr_noop("Nothing playing.")
NO_TRACK = tr_noop("No track.")
NOTHING_CURRENTLY_PLAYING = tr_noop("Nothing playing.")
QUEUE_EMPTY = tr_noop("Queue empty.")
INSTRUMENTAL_TRACK = tr_noop("This track is instrumental.")
NO_CURRENT_TRACK = tr_noop("Nothing playing.")
BOOKMARK_DELETED = tr_noop("Bookmark deleted.")
SELECT_TRACK_OR_EPISODE = tr_noop("Select a track or episode.")
NO_PLAYLISTS = tr_noop("No playlists.")
CHOOSE_PLAYLIST = tr_noop("Choose a playlist.")
ENTER_PLAYLIST_NAME = tr_noop("Enter a new playlist name.")
ADDED = tr_noop("Added.")
READY = tr_noop("Ready.")
NO_PLAYABLE_TRACKS = tr_noop("No playable tracks selected.")
QUEUED = tr_noop("Queued.")
FINDING_EPISODE_DOWNLOAD = tr_noop("Finding episode download.")
DOWNLOADING_EPISODE = tr_noop("Downloading episode.")
EPISODE_DOWNLOADED = tr_noop("Episode downloaded.")
MUTED = tr_noop("Muted.")
UNMUTED = tr_noop("Unmuted.")
SHUFFLE_ON = tr_noop("Shuffle on.")
SHUFFLE_OFF = tr_noop("Shuffle off.")
REPEAT_OFF = tr_noop("Repeat off.")
REPEAT_ALL = tr_noop("Repeat all.")
REPEAT_ONE = tr_noop("Repeat one.")
LIKED = tr_noop("Liked.")
UNLIKED = tr_noop("Unliked.")

PLAYLISTS_LOAD_HINT = tr_noop("Move into the list to load playlists.")
AUDIOBOOKS_LOAD_HINT = tr_noop("Move into the list to load saved audiobooks.")
PODCASTS_LOAD_HINT = tr_noop("Move into the list to load saved podcasts.")
AUTHORIZATION_REQUIRED = tr_noop("Spotify authorization required.")
NOT_CONNECTED = tr_noop(
    "Not connected to Spotify. Use the Account menu to connect."
)
PERMISSIONS_REQUIRED = tr_noop(
    "Browsing is connected. Refresh Spotify permissions from the Account "
    "menu to enable BlindSpot's player."
)
MAIN_TABS = tr_noop("Main tabs.")
RECENT_PERMISSION_PROMPT = tr_noop(
    "Recently Played needs an additional Spotify permission. Authorize it "
    "now?"
)
RECENT_NOT_AUTHORIZED = tr_noop("Recently Played was not authorized.")
AUTHORIZATION_IN_PROGRESS = tr_noop("authorization already in progress.")
COMPLETE_LOGIN = tr_noop("Complete Spotify login in your browser.")
RECENT_AUTH_NOT_COMPLETED = tr_noop(
    "Recently Played authorization was not completed."
)
SIGN_OUT_PROMPT = tr_noop("Erase Spotify session from folder?")
SIGNED_OUT = tr_noop("Signed out and erased credentials.")
MANUAL_NOT_FOUND = tr_noop("manual not found.")
UPDATE_DOWNLOAD_FAILED = tr_noop(
    "The BlindSpot update could not be downloaded."
)
UPDATE_CHECK_FAILED = tr_noop("BlindSpot could not check for updates.")
UPDATE_INSTALL_PROMPT = tr_noop("Download and install the update now?")
UPDATE_DOWNLOAD_PROMPT = tr_noop(
    "Download the update and reveal it in Finder?"
)
UPDATE_PAGE_PROMPT = tr_noop("Open the download page now?")
UPDATE_READY_MACOS = tr_noop(
    "The BlindSpot update is ready in Downloads. Quit BlindSpot, extract "
    "the ZIP, and replace the current BlindSpot.app with the new one."
)
RECENT_AUTHORIZED = tr_noop("Recently Played authorized.")
RECENT_ACCESS_NOT_GRANTED_STATUS = tr_noop(
    "Spotify did not grant access to Recently Played."
)
RECENT_ACCESS_NOT_GRANTED = tr_noop(
    "Spotify did not grant Recently Played access for this app. The tab is "
    "unavailable."
)
CONNECTED = tr_noop("Connected to Spotify. Starting player.")
NO_SONG_SELECTED = tr_noop("No song selected.")
SLEEP_END_OF_TRACK = tr_noop("Sleep timer set for end of track.")
SLEEP_CANCELLED = tr_noop("Sleep timer cancelled.")
NO_SLEEP_TIMER = tr_noop("No sleep timer set.")
SLEEP_STOPPED = tr_noop("Sleep timer. Playback stopped.")
NO_DEVICES = tr_noop(
    "No controllable devices available. Open Spotify on the device and try "
    "again."
)
SLEEP_TIMER_PROMPT = tr_noop("Choose when playback should stop.")
PLAYER_NOT_READY = tr_noop("not ready.")
PLAYER_STARTING = tr_noop("player starting.")
WEBVIEW2_REQUIRED = tr_noop(
    "BlindSpot's player requires Microsoft WebView2. Install the Evergreen "
    "WebView2 Runtime and restart BlindSpot."
)
BROWSER_COMPONENT_FAILED = tr_noop(
    "BlindSpot could not start the system web browser component."
)
PLAYBACK_DEVICE_OFFLINE = tr_noop(
    "BlindSpot's Spotify playback device went offline."
)
AUTOPLAY_BLOCKED = tr_noop(
    "The browser blocked automatic playback. Press Play again to activate "
    "BlindSpot's player."
)
NO_TRACKS = tr_noop("No tracks.")
UNKNOWN_PLAYER_ERROR = tr_noop("Unknown Spotify player error")
WEB_PLAYER_PAGE_FAILED = tr_noop("The web player page could not load.")
KEYMAP_OS_WARNING = tr_noop("The system may use this key.")
KEYMAP_VOICEOVER_WARNING = tr_noop("VoiceOver may use this key.")
KEYMAP_NAVIGATION_WARNING = tr_noop(
    "This key normally navigates. Assign anyway?"
)
KEYMAP_TYPING_WARNING = tr_noop("This key normally types. Assign anyway?")
KEYMAP_GLOBAL_WARNING = tr_noop(
    "Global shortcuts work while BlindSpot is in the background and may "
    "override shortcuts in other applications. Enable this assignment at "
    "your own risk?"
)
GETTING_LYRICS = tr_noop("Getting lyrics.")
GETTING_DEVICES = tr_noop("Getting available devices.")
DEVICE_SELECTION_PROMPT = tr_noop(
    "Select the Spotify Connect device for playback."
)
DISCOVER_SEARCH_PROMPT = tr_noop(
    "Choose New releases or Top songs, then activate Search."
)
LOADING_MUSIC_CHART = tr_noop("Loading chart")
ERROR_DETAILS_COPIED = tr_noop("Error details copied to the clipboard.")
NO_ERROR_TO_COPY = tr_noop("No error has occurred in this session.")
CLIPBOARD_UNAVAILABLE = tr_noop("The clipboard could not be opened.")
REPORT_COPIED = tr_noop("Report copied to the clipboard.")
NOTHING_TO_EXPORT = tr_noop(
    "There are no songs to export here. Open a playlist or album, or select "
    "one."
)


def exported_items(count: int, filename: str, partial: bool) -> str:
    message = ntr(
        "Exported {count} item to {filename}.",
        "Exported {count} items to {filename}.",
        count,
    ).format(count=count, filename=filename)
    if partial:
        message += tr(
            " This was a partial list. Choose the Show more row and "
            "export again to include everything."
        )
    return message


def file_save_failed(detail: object) -> str:
    return tr("The file could not be saved: {detail}").format(detail=detail)
JUMP_TIME_PROMPT = tr_noop(
    "Enter seconds, minutes and seconds, or hours, minutes and seconds."
)
JUMP_TIME_INVALID = tr_noop("Enter a time such as 90, 1:30, or 1:02:30.")

AUTHORIZATION_TIMEOUT = tr_noop(
    "Spotify authorization timed out. BlindSpot is still available; try "
    "again from the Account menu."
)
AUTH_STATE_MISMATCH = tr_noop("Spotify login state did not match")
AUTH_CODE_MISSING = tr_noop("Spotify authorization code was missing")
CALLBACK_RECEIVED = tr_noop(
    "BlindSpot received the Spotify response. You may close this browser "
    "tab."
)

NOT_ENOUGH_LYRIC_INFO = tr_noop(
    "There is not enough track information to find lyrics."
)
LYRICS_UNAVAILABLE_TRACK = tr_noop("Lyrics unavailable for this track.")
LRCLIB_BUSY = tr_noop("LRCLIB is busy. Please try again later.")
LYRICS_RETRIEVAL_FAILED = tr_noop("Lyrics could not be retrieved.")
PHRASE_END_UNAVAILABLE = tr_noop("The end of this lyric line is unavailable.")
INVALID_PLAYLIST_POSITION = tr_noop("Enter a valid playlist position.")
NO_ALTERNATE_VERSIONS = tr_noop("No alternate versions were found.")
DUPLICATE_PLAYLIST_REPLACEMENT = tr_noop(
    "This recording occurs more than once in the playlist, so BlindSpot "
    "cannot safely replace only this occurrence."
)
PLAYLIST_TRACK_REPLACED = tr_noop("Playlist track replaced.")
LOGS_FOLDER_OPEN_FAILED = tr_noop(
    "The BlindSpot logs folder could not be opened."
)

PLAYLIST_ITEMS_UNAVAILABLE = tr_noop(
    "Unable to browse. You don't own or collaborate on this playlist. Press "
    "F4 to play."
)
ALBUM_NOT_PROVIDED = tr_noop(
    "Spotify did not provide an album for this track."
)
LOADING_ALBUM_ARTWORK = tr_noop("Loading album artwork.")
ALBUM_ARTWORK_UNAVAILABLE = tr_noop(
    "Spotify did not provide artwork for this album."
)
ALBUM_ARTWORK_INVALID = tr_noop("The album artwork could not be displayed.")
ALBUM_ARTWORK_VIEWER_FAILED = tr_noop(
    "The default photo viewer could not be opened."
)
RECENT_PERMISSION_REQUIRED = tr_noop(
    "Recently Played needs an additional Spotify permission."
)
NO_CONTROLLABLE_DEVICE = tr_noop(
    "No controllable Spotify device is available. Open Spotify on your "
    "computer, phone, or speaker, then try again."
)
PLAYBACK_DEVICE_INACTIVE = tr_noop("playback device not active.")
CURRENT_VOLUME_UNAVAILABLE = tr_noop(
    "Spotify did not report the current volume."
)
AUDIOBOOK_PLAYBACK_UNAVAILABLE = tr_noop(
    "Spotify cannot play this audiobook chapter for this account. Audiobook "
    "playback depends on the individual's Spotify plan and available "
    "listening time."
)
SPOTIFY_EMPTY_RESPONSE = tr_noop("Spotify returned an empty response.")

UPDATE_HELPER_STOPPED = tr_noop(
    "The update helper stopped during preparation."
)
UPDATE_PREPARATION_TIMEOUT = tr_noop("Update preparation timed out.")
UPDATE_PREPARATION_FAILED = tr_noop("The update could not be prepared.")


def shortcut_capture(action: str) -> str:
    return tr(
        "Press the shortcut for {action}. Press Escape to cancel."
    ).format(
        action=action,
    )


def shortcut_replace(shortcut: str, action: str) -> str:
    return tr(
        "{shortcut} is assigned to {action}. Replace assignment?"
    ).format(
        shortcut=shortcut,
        action=action,
    )


def lyric_boundary(boundary: str) -> str:
    return tr("{boundary} synced lyric line.").format(boundary=boundary)


def playlist_position_prompt(total: int) -> str:
    return tr("Enter a position from 1 to {total}.").format(total=total)


def playlist_item_moved(position: int, total: int) -> str:
    return tr(
        "Moved to position {position} of {total}."
    ).format(
        position=position,
        total=total,
    )


def replace_playlist_track(original: str, replacement: str) -> str:
    return tr(
        "Replace \"{original}\" with \"{replacement}\"?"
    ).format(
        original=original,
        replacement=replacement,
    )


def lyric_timing(timing: str) -> str:
    return tr("Lyrics now {timing}.").format(timing=timing)


def result_count(count: int, query: str) -> str:
    if not count:
        return tr("No results for {query}.").format(query=query)
    return ntr("{count} result.", "{count} results.", count).format(
        count=count
    )


def item_count(count: int) -> str:
    return ntr("{count} item.", "{count} items.", count).format(count=count)


def weekday_name(index: int) -> str:
    """Name of a weekday, 0 for Monday."""
    return (
        ptr("weekday", "Monday"),
        ptr("weekday", "Tuesday"),
        ptr("weekday", "Wednesday"),
        ptr("weekday", "Thursday"),
        ptr("weekday", "Friday"),
        ptr("weekday", "Saturday"),
        ptr("weekday", "Sunday"),
    )[index]


def month_name(month: int) -> str:
    """Name of a month as used inside a date, 1 for January."""
    return (
        ptr("month in a date", "January"),
        ptr("month in a date", "February"),
        ptr("month in a date", "March"),
        ptr("month in a date", "April"),
        ptr("month in a date", "May"),
        ptr("month in a date", "June"),
        ptr("month in a date", "July"),
        ptr("month in a date", "August"),
        ptr("month in a date", "September"),
        ptr("month in a date", "October"),
        ptr("month in a date", "November"),
        ptr("month in a date", "December"),
    )[month - 1]


def long_date(value: date) -> str:
    return tr("{day} {month} {year}").format(
        day=value.day, month=month_name(value.month), year=value.year
    )


def minutes_seconds(minutes: int, seconds: int) -> str:
    return tr("{minutes} {seconds}").format(
        minutes=ntr("{count} minute", "{count} minutes", minutes).format(
            count=minutes
        ),
        seconds=ntr("{count} second", "{count} seconds", seconds).format(
            count=seconds
        ),
    )


def finding_tag_results(tag: str, category: str) -> str:
    if category == "album":
        return tr("Finding {tag} album results using Last.fm").format(tag=tag)
    if category == "artist":
        return tr("Finding {tag} artist results using Last.fm").format(
            tag=tag
        )
    return tr("Finding {tag} track results using Last.fm").format(tag=tag)


def selected_count(count: int) -> str:
    return ntr(
        "{count} item selected", "{count} items selected", count
    ).format(count=count)


def matching_items(matches: int, total: int) -> str:
    return ntr(
        "{matches} matching item in {total}.",
        "{matches} matching items in {total}.",
        matches,
    ).format(matches=matches, total=total)


def matching_loaded_items(matches: int, total: int) -> str:
    return ntr(
        "{matches} matching loaded item in {total}.",
        "{matches} matching loaded items in {total}.",
        matches,
    ).format(matches=matches, total=total)


def matching_chart_entries(matches: int, total: int) -> str:
    return ntr(
        "{matches} matching chart entry in {total}.",
        "{matches} matching chart entries in {total}.",
        matches,
    ).format(matches=matches, total=total)


def chart_entry_count(total: int) -> str:
    return ntr(
        "{total} chart entry.", "{total} chart entries.", total
    ).format(total=total)


def track_count(count: int) -> str:
    return ntr("{count} track", "{count} tracks", count).format(count=count)


def song_count(count: int) -> str:
    return ntr("{count} song", "{count} songs", count).format(count=count)


def album_count(count: int) -> str:
    return ntr("{count} album", "{count} albums", count).format(count=count)


def counted_rows(rows: list, album_kind: object, track_kind: object) -> str:
    """Name a mixed selection: all albums, all songs, or just items."""
    count = len(rows)
    if all(row.kind == album_kind for row in rows):
        return album_count(count)
    if all(row.kind == track_kind for row in rows):
        return song_count(count)
    return ntr("{count} item", "{count} items", count).format(count=count)


def named_item_count(name: str, count: int) -> str:
    return tr("{name}. {items}").format(name=name, items=item_count(count))


def loading(title: str) -> str:
    return tr("Loading {title}").format(title=title)


def load_hint(title: str) -> str:
    return tr("Press F5 to load {title}.").format(title=title)


def opening(name: str) -> str:
    return tr("Opening {name}").format(name=name)


def opening_album(name: str) -> str:
    return tr("Opening album for {name}").format(name=name)


def remove_playlist(name: str) -> str:
    return tr("Remove {name} from your Spotify library?").format(name=name)


def audiobook_resume_permission(count: int) -> str:
    return tr(
        "{items} Refresh Spotify permissions to read chapter resume "
        "positions."
    ).format(items=item_count(count))


def saved_podcasts(shows: int, episodes: int) -> str:
    return tr("{podcasts} and {episodes}.").format(
        podcasts=ntr("{count} podcast", "{count} podcasts", shows).format(
            count=shows
        ),
        episodes=ntr(
            "{count} saved episode", "{count} saved episodes", episodes
        ).format(count=episodes),
    )


def unsubscribe_podcast(name: str) -> str:
    return tr("Unsubscribe from {name}?").format(name=name)


def remove_saved_episode(name: str) -> str:
    return tr("Remove {name}?").format(name=name)


def update_available(version: str, action: str) -> str:
    return tr(
        "BlindSpot {version} is available.\n"
        "\n"
        "{action}"
    ).format(
        version=version,
        action=action,
    )


def update_current(version: str) -> str:
    return tr("BlindSpot {version} is up to date.").format(version=version)


def about(version: str) -> str:
    return tr(
        "BlindSpot\n"
        "Build {version}\n"
        "Copyright © 2026 Sam Taylor\n"
        "A portable, accessible Spotify client."
    ).format(
        version=version,
    )


def shortcut_registration_failed(shortcuts: Iterable[str]) -> str:
    return tr(
        "Could not register global {shortcuts}. Another app may already be "
        "using it."
    ).format(shortcuts=", ".join(shortcuts))


def sleep_minutes(minutes: int) -> str:
    return ntr(
        "Sleep timer set for {minutes} minute.",
        "Sleep timer set for {minutes} minutes.",
        minutes,
    ).format(minutes=minutes)


def player_starting(name: str) -> str:
    return tr("player starting.")


def playing_on(name: str) -> str:
    return tr("Playing on {name}.").format(name=name)


def moved_without_playing(name: str) -> str:
    return tr("Playback moved to {name} without playing.").format(name=name)


def device_targeted(name: str) -> str:
    return tr(
        "{name} will receive a forced transfer on the next play."
    ).format(
        name=name,
    )


def transferring_to(name: str) -> str:
    return tr("Transferring playback to {name}.").format(name=name)


def playing(name: str) -> str:
    return tr("Playing {name}").format(name=name)


def unsupported_volume(name: str) -> str:
    return tr("{name} does not support volume control.").format(name=name)


def bookmark_saved(position: str) -> str:
    return tr("Bookmark saved at {position}.").format(position=position)


def resumed(name: str, position: str) -> str:
    return tr(
        "Resumed {name} at {position}."
    ).format(
        name=name,
        position=position,
    )


def queued_count(count: int) -> str:
    return ntr(
        "Queued {count} track.", "Queued {count} tracks.", count
    ).format(count=count)


def playlist_information(
    owner: str,
    total: int | None,
    public: bool | None,
    collaborative: bool,
    description: str,
) -> str:
    visibility = (
        tr("Public")
        if public is True
        else tr("Private")
        if public is False
        else tr("Unspecified")
    )
    lines = [
        tr("Owner: {owner}").format(owner=owner or tr("Unknown")),
        tr("Tracks: {total}").format(
            total=total if total is not None else tr("Unknown")
        ),
        tr("Visibility: {visibility}").format(visibility=visibility),
        tr("Collaborative: {collaborative}").format(
            collaborative=tr("Yes") if collaborative else tr("No")
        ),
    ]
    if description:
        lines.extend(
            ("", tr("Description: {description}").format(
                description=description
            ))
        )
    return "\n".join(lines)


def spotify_error(status: int, detail: str) -> str:
    return tr(
        "Spotify returned {status}: {detail}"
    ).format(
        status=status,
        detail=detail,
    )


def spotify_rate_limited(retry_after: int | None) -> str:
    """Explain a 429 in terms of how long to wait, when Spotify says."""
    if not retry_after:
        return tr(
            "Spotify is limiting BlindSpot's requests. Wait a little "
            "while and try again."
        )
    if retry_after < 90:
        if retry_after > 45:
            wait = tr("about a minute")
        else:
            wait = ntr(
                "{seconds} second", "{seconds} seconds", retry_after
            ).format(seconds=retry_after)
    elif retry_after < 5400:
        minutes = round(retry_after / 60)
        wait = ntr(
            "about {minutes} minute", "about {minutes} minutes", minutes
        ).format(minutes=minutes)
    else:
        hours = round(retry_after / 3600)
        wait = ntr(
            "about {hours} hour", "about {hours} hours", hours
        ).format(hours=hours)
    return tr(
        "Spotify is limiting BlindSpot's requests. Try again in {wait}."
    ).format(wait=wait)


def spotify_contact_failed(detail: object) -> str:
    return tr("Could not contact Spotify: {detail}").format(detail=detail)


def spotify_login_failed(detail: str) -> str:
    return tr("Spotify login failed: {detail}").format(detail=detail)


def spotify_player_error(source: str, detail: str) -> str:
    return tr(
        "Spotify {source}: {detail}"
    ).format(
        source=source,
        detail=detail,
    )


def lyrics_unavailable(name: str) -> str:
    return tr("Lyrics unavailable for {name}.").format(name=name)


def lrclib_retry(seconds: str) -> str:
    return tr(
        "LRCLIB is busy. Try again in {seconds} seconds."
    ).format(
        seconds=seconds,
    )


def lrclib_error(status: int) -> str:
    return tr("LRCLIB returned error {status}.").format(status=status)


_SOURCE_TEXT = {
    name: value
    for name, value in list(globals().items())
    if name.isupper() and isinstance(value, str)
}


def retranslate() -> None:
    """Re-read every constant in the active language."""
    for name, text in _SOURCE_TEXT.items():
        globals()[name] = tr(text)


on_language_change(retranslate)
