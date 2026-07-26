# BlindSpot

BlindSpot is a portable, screen-reader-friendly Spotify client for Windows and macOS. 

## Current milestone

- Search tab with Songs, Albums, Artists, Playlists, Podcasts, Podcast
  episodes, Audiobooks, and All filters.
- Liked Songs, Queue, Playlists, Recently Played, Bookmarks, and saved
  Audiobooks and Podcasts tabs.
- Enter drills into containers and plays tracks or episodes.
- Backspace returns to the previous view and restores the selected row.
- Q queues an item, L likes or unlikes it, and Ctrl+F returns to search.
- Spotify login uses OAuth Authorization Code with PKCE; no client secret is
  stored or required.
- An integrated Spotify Web Playback SDK instance makes BlindSpot its own Spotify
  Connect device. The visible interface remains entirely native wxPython.
- Settings and tokens live in the portable `data` folder.

## Run from source

1. Install Python 3.11 or newer.
2. Run `python -m pip install -r requirements.txt`.
3. Run `python -m blindspot` with `src` on `PYTHONPATH`, or install in editable
   mode using `python -m pip install -e .`.
4. Follow BlindSpot's one-time setup screen. It opens the Spotify Developer
   Dashboard, provides the redirect URI, and asks for the Client ID.
   Select both Web API and Web Playback SDK when creating the Spotify app.

Register this redirect URI in the Spotify developer dashboard:

`http://127.0.0.1:43821/callback`

## Keyboard model

- Ctrl+1 through Ctrl+8: select a tab in the interface.
- Ctrl+Tab and Ctrl+Shift+Tab: cycle main tabs.
- Ctrl+F: focus Search.
- Ctrl+Comma: open Preferences.
- Enter: open a container or play a track/episode.
- Ctrl+Enter: open the focused track's album.
- Backspace or Alt+Left: return to the previous remembered view.
- F4: play the focused track, playlist, album, or artist. In an open album,
  Enter plays only the selected track, while F4 plays the album beginning at
  that track.
- F5 and F6: seek backward or forward five seconds.
- F7: restart the current track after the half-second double-press window.
  Press twice within that window to move to the previous track immediately.
- F9: next track.
- F8: pause or resume the current track.
- Ctrl+F5 and Ctrl+F6: decrease or increase volume five percent.
- Ctrl+F4: mute or restore the previous volume.
- Space: pause or resume playback, except when focus is in a control that
  uses Space itself, such as a button, checkbox, radio button, or edit field.
- Ctrl+Space: play from the current line in Lyrics; elsewhere, mark or
  unmark the focused list item.
- Ctrl+Q: queue marked tracks in list order, or the focused track if none are marked.
- Ctrl+L: like or unlike the selected item.
- Ctrl+Shift+B: bookmark the current playback position.
- Ctrl+Shift+N: new playlist.
- Ctrl+Shift+R: refresh the current view.
- Applications key or Shift+F10: open the selected item's actions.

Search initially displays up to 20 results for a selected category. When more
are available, activate **Load more results** at the end of the list to append
the next page.

The Podcasts library contains subscribed shows and individually saved
episodes. Their context menus can unsubscribe or remove them. Podcast episode
context menus offer **Download episode** when a public RSS
enclosure can be matched through the podcast publisher's feed. Private and
Spotify-exclusive episodes may not provide a public download.

User-facing announcements, prompts, status text, and practical error messages
are maintained centrally in `src/blindspot/messages.py`.

Global assignments for playback, seeking, volume, and mute can be configured
individually in Preferences. No global shortcuts are assigned by default.

## Portable data

Packaged Windows builds resolve `data` beside the BlindSpot executable.
macOS stores settings and authentication in
`~/Library/Application Support/BlindSpot` so they remain available when
BlindSpot.app is moved or updated. Use Account > Sign out and erase
credentials before sharing a Windows portable folder.

## macOS GitHub build

The `Build macOS app` GitHub Actions workflow runs the tests, installs
wxPython and the VoiceOver `appscript` bridge, builds `BlindSpot.app`, and
uploads `BlindSpot-macOS.zip`. It can be started manually from the Actions
tab and also runs for pushes to `main` and pull requests.

The build is unsigned. After extracting the ZIP, open Terminal, change
to the extracted `BlindSpot-macOS` folder, and run:

```sh
sh prepare-macos.sh
```

The helper acts only on `BlindSpot.app` beside it: it removes that app's
downloaded quarantine attribute and opens the app.
It does not require administrator access or change system-wide security
settings.

## Releases and updates

Pushing a version tag such as `v2026.7.0.0` builds Windows and macOS portable
ZIP files and publishes them as a GitHub Release. BlindSpot checks that release
feed at startup and Help > Check for updates checks it on demand. When a newer
build exists, BlindSpot offers to install it. Portable Windows builds download
the ZIP, preserve the `data` folder, replace the application files after
BlindSpot closes, and restart automatically. On macOS, the release page opens
for a manual replacement of the running app bundle.

## License

Copyright © 2026 Sam Taylor. BlindSpot is free software licensed under the
GNU General Public License version 3 or later. See `LICENSE`.
