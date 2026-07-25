# BlindSpot

BlindSpot is a portable, screen-reader-friendly Spotify client for Windows and macOS. 

## Current milestone

- Search tab with Songs, Albums, Artists, Playlists, Podcasts, and All filters.
- Liked Songs, Queue, Playlists, Recently Played, Bookmarks, and saved
  Audiobooks tabs.
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

## Demo mode

Run `python -m blindspot --demo` to exercise the complete native interface
without Spotify authentication or network access. Demo playback, queue, liked
songs, albums, artists, playlists, and podcasts are held in memory and reset
when BlindSpot closes. No audio is available in Demo mode.

## Keyboard model

- Ctrl+1 through Ctrl+7: select a tab in the interface.
- Ctrl+Tab and Ctrl+Shift+Tab: cycle main tabs.
- Ctrl+F: focus Search.
- Ctrl+Comma: open Preferences.
- Enter: open a container or play a track/episode.
- Backspace or Alt+Left: return to the previous remembered view.
- F4: play the focused track, playlist, album, or artist.
- F5 and F6: seek backward or forward five seconds.
- F7 and F9: previous or next track.
- F8: pause or resume the current track.
- Ctrl+F5 and Ctrl+F6: decrease or increase volume five percent.
- Ctrl+F4: mute or restore the previous volume.
- Ctrl+Space: mark or unmark the focused item.
- Ctrl+Q: queue marked tracks in list order, or the focused track if none are marked.
- Ctrl+L: like or unlike the selected item.
- Ctrl+Shift+B: bookmark the current playback position.
- Ctrl+Shift+N: new playlist.
- Applications key or Shift+F10: open the selected item's actions.

Global assignments for playback, seeking, volume, and mute can be configured
individually in Preferences. No global shortcuts are assigned by default.

## Portable data

Packaged Windows builds resolve `data` beside the BlindSpot executable. A
packaged macOS build uses `data` beside `BlindSpot.app` when that location is
writable. If it is installed in a read-only location, it falls back to
`~/Library/Application Support/BlindSpot`. Use Account > Sign out and erase
credentials before sharing a portable folder.

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
