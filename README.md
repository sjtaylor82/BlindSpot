# BlindSpot

BlindSpot is a portable, screen-reader-friendly Spotify client for Windows and macOS. 

## Current milestone

- Search tab with Songs, Albums, Artists, Playlists, Podcasts, Podcast
  episodes, Audiobooks, and All filters.
- A separate editable **Genre** field browses community-tagged
  Songs, Albums, or Artists and resolves the ranked results to Spotify. An
  optional Search query narrows the Last.fm names before matching. You do
  not need to know a tag's name: a song or artist's context menu offers
  **Browse genres (Last.fm)**, which lists that item's strongest
  community tags, with Last.fm's own 0 to 100 weight, and opens the one
  you choose as an ordinary Genre search. Tags that only repeat the
  artist or title, name a year, or describe opinion rather than genre
  (for example "seen live") are left out.
- Album context menus include **Related albums**, which opens a deduplicated
  discovery list derived from the source album. Results behave like ordinary
  albums and Backspace restores the originating view.
- Liked Songs, Queue, Playlists, Recently Played, Audiobooks, Podcasts,
  Saved Albums, and Discover tabs. Bookmarks and concert search open from the
  File menu instead of the tab bar.
- The Discover tab offers **New releases**, **Followed artists and authors**,
  **Top charts**, and **Historical charts**. The Apple charts show the most-played
  songs or albums for one of 45 countries, taken from Apple Music's
  public RSS feed, which reports real play data from Apple Music's whole
  user base and needs no API key. Rows announce their chart position.
  Apple provides up to 100 entries, all listed at once. The chart appears
  instantly because BlindSpot does not search Spotify for chart entries up
  front: it looks an item up only when you play, queue, save, or open the
  menu for it, which keeps BlindSpot well inside Spotify's request limits.
  Rows show Apple's title, artist and year until then. The country
  defaults to your Spotify account's country when Apple publishes a chart
  for it, and choosing a country yourself always takes precedence. The
  status line names the source and country, when BlindSpot loaded the
  chart, that Apple publishes rank only (no play counts, reporting period
  or measurement time), and that songs are looked up on Spotify on demand.
  Apple's own "updated" stamp is deliberately not shown: it tracks the
  moment of the request, not when the ranking was measured. Like any real
  chart, long-standing favourites appear alongside new releases because
  people genuinely keep playing them.
  **New releases** reads Apple's iTunes Store genre charts for a country (for
  example Country in Australia), keeps only releases inside a chosen window
  (7, 14, 30 or 90 days, or any time), and lists them newest first. Typing an
  artist or title in its keyword box instead searches Apple's catalogue (the
  genre is ignored, the window still applies), which finds small releases that
  never chart.
  **Top charts** shows Apple's most-played chart for the chosen country;
  choose Songs or Albums under Show.
  **Followed artists and authors** lists new releases by artists you follow and
  new audiobooks by authors you follow. Right-click an artist, song, album or
  audiobook and choose Follow for new releases (or use Playback, Now playing,
  Follow artist or author for new releases for what is playing). Audiobook
  releases come from Apple's catalogue, keep only titles marked Unabridged or
  Abridged to skip translated editions, and open in the Audiobooks tab if
  Spotify has them.
  File, Followed artists and authors lists everyone you follow and lets you
  stop. BlindSpot
  also checks for new releases at start-up and announces any it has not told
  you about yet; Preferences can turn that off. The list is kept locally in
  data/followed_artists.json and is separate from following on Spotify.
  Spotify's own new-release search is no longer used, because it returns the
  top 100 worldwide releases and cannot be limited by genre or country.
  **Historical charts** has two sources. The experimental US Billboard Hot 100
  accepts a date, maps it to the latest weekly chart on or before that day,
  and reads the JSON live from the community-maintained
  mhollingshead/billboard-hot-100 project on GitHub. It is unofficial, is not
  bundled with BlindSpot, and may change or disappear. **Number ones by
  country** covers the United Kingdom (singles from 1952, albums from 1956),
  Australia (singles from 1940, albums from 1965) and New Zealand (singles and
  albums from 1980). Choose the country, then Songs or Albums under Show, and
  type a year (such as 1985) or a date (1985-07-13). A year lists every number
  one that year once each, with its weeks at number one that year and in
  total, most weeks first by default or in date order. A date gives the number
  one for that week. The data comes from Wikipedia's lists of number ones
  (CC BY-SA), compiled from each country's official charts. They list only
  number ones, and Wikipedia is community edited so it can contain mistakes.
- Upcoming Ticketmaster live-event search by keyword, country, state, city, and
  genre, with 50 results per page. Add your own Ticketmaster Discovery API key
  in Preferences to use it; a link beneath the key field opens Ticketmaster's
  registration instructions.
- Right-click or Shift+F10 a track and choose "What's this song about?" to read the introduction of its English Wikipedia article. It makes one Wikipedia request when chosen, and says so if no matching article exists.
- Preferences can turn off spoken volume percentages and spoken cart names (both on by default).
- File > Search for concerts (Ctrl+Shift+G) opens concert search; File > Bookmarks (Ctrl+B) opens your bookmarks. Playback keys such as F5 to F9 still work in both windows. Ctrl+9 opens Discover.
- Enter drills into containers and plays tracks or episodes.
- Backspace returns to the previous view and restores the selected row.
- Q queues an item, L likes or unlikes it, and Ctrl+F returns to search.
- Library and playlist views include a **Filter this list** edit box immediately
  before Now Playing in the Tab order. It filters the fully loaded local view by
  title, artist or publisher, and album or show; matching is case- and
  diacritic-insensitive. In an open playlist, F4 plays the visible filtered
  sequence beginning with the focused track.
- **View > Sort by** temporarily sorts supported collection views by original
  order, title, artist, album, duration, or date added where that metadata is
  available. Descending order is optional, and sorting never rewrites a Spotify
  playlist. Queue and Recently Played retain their meaningful service order.
- **Add selected to a playlist** copies every marked track to an editable
  destination in displayed order; with no marked selection it copies the
  focused track. Spotify-sized batches support selections over 100 tracks.
- Type several letters quickly in an item list to jump to the first item whose
  label starts with that prefix. The prefix resets after a short pause.
- Playlist-track context menus include **Copy to playlist** and, for editable
  sources, **Move to another playlist**. Marked tracks are handled together;
  moves remove the source entries only after the destination addition succeeds.
- In item lists, Ctrl+C or Command+C copies marked tracks to BlindSpot's
  playlist clipboard. Ctrl+X or Command+X cuts from an editable playlist, and
  Ctrl+V or Command+V pastes into the open editable playlist. Delete asks for
  confirmation before removing a playlist entry.
- The Podcasts tab browses category-based Spotify podcast search results in
  accessible pages, alongside followed shows and saved episodes. Show
  descriptions, publishers, and paginated episode lists remain available.
- A song's context menu offers **Find covers (MusicBrainz)**, which lists
  other artists' recordings of the same song. MusicBrainz is a free open
  music database that links every recording of a song together and marks
  which are covers; no key or account is needed. Live, video and karaoke
  recordings and the original artist's own are left out, and those marked
  as covers come first, with novelty versions such as 8-bit arrangements
  last. It also includes same-title recordings that MusicBrainz has not yet
  linked to the song, common for recent releases, checked against your
  track's length. A lookup takes up to about 20 seconds because MusicBrainz asks
  for no more than one request a second, and it reads at most the first
  300 recordings of a very popular song, saying so when it stops early.
  Rows show the artist, title and year and are looked up on Spotify only
  when you play, queue or save them, so some obscure covers may turn out
  not to be on Spotify.
- **File > Export list...** saves the list in view as plain text or CSV:
  position, title, artist, album, duration and a Spotify link. It exports
  what is displayed, so a filter or sort is respected. In a list of
  playlists or albums it exports the selected one's tracks. CSV files open
  correctly in spreadsheets with accented and Polish characters. Only
  metadata is exported, never audio. If more results were still to be
  loaded, the file and the announcement say it is a partial list.
- Errors offer **Copy error details**, and Help > **Copy last error
  details** copies the same at any time: what BlindSpot was doing, the
  error type and message, any Spotify status and wait time, and the
  traceback, with credentials and personal paths removed.
- Help > **Capture log for developer...** shows a diagnostic report you
  read in full before copying or saving it. It holds versions, non-secret
  settings, whether each credential is set (never its value) and the last
  error. Recent log lines are opt-in, and song, artist and playlist names
  and search terms are hidden unless you separately tick them in. Tokens,
  API keys, e-mail addresses and your Windows user name are always
  removed. Logging is off by default, so set it to Debug in Preferences and
  repeat the problem first.
- Track and artist context menus can find similar Spotify content using
  recommendations provided by Last.fm. BlindSpot includes a default Last.fm
  application key, which can be replaced in Preferences.
- Track context menus can open a Last.fm similar-track mix for inspection,
  start it now as an ordered Spotify playback sequence, or append it after the
  current queue. The Playback menu offers the same actions for the currently playing
  track. BlindSpot requests up to 50 Last.fm candidates and resolves browsed
  results in pages of 20; fewer may remain after Spotify matching and duplicate
  removal.
- Track and album context menus include **Album and recording information**.
  It opens a read-only, searchable view of Spotify's full metadata, including
  release date and type, label, copyrights, track and disc numbers, duration,
  explicit status, ISRC and UPC identifiers when Spotify supplies them.
- Starting a mix resolves and starts the first page, then prepares the remaining
  candidates in the background and appends matched tracks to the mix. BlindSpot
  starts one track and places the rest in Spotify's queue, avoiding the looping
  behaviour of Spotify's multi-URI playback context. Repeat is switched off
  before a mix starts. When about ten queued mix tracks remain, BlindSpot uses
  the current track to find and append another deduplicated batch. Playing an
  unrelated item ends this continuous mix session.
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

- Ctrl+1 through Ctrl+9: select the tabs in the interface: Search, Liked
  Songs, Queue, Playlists, Recently Played, Audiobooks, Podcasts, Saved Albums,
  and Discover.
- Ctrl+Tab and Ctrl+Shift+Tab: cycle main tabs.
- Ctrl+F: focus Search.
- Ctrl+Comma: open Preferences.
- Enter: open a container or play a track/episode.
- Ctrl+Enter: open the focused track's album.
- Backspace or Alt+Left: return to the previous remembered view.
- F4: play the focused track, playlist, album, or artist. In an open album,
  Enter plays only the selected track, while F4 plays the album beginning at
  that track. When no list has focus, F4 plays the song remembered from your
  last session, as F7 does.
- F5: restart the current track after the half-second double-press window.
  Press twice within that window to move to the previous track immediately.
- F6 and F8: seek backward or forward five seconds.
- Shift+F8 and Shift+F6: jump to the next or previous lyric section (verse or chorus), found from the stanza breaks in the lyrics (or gaps in the synced timing). The section number is only spoken if you turn on "Speak section number when jumping between lyric sections" in Preferences.
- F7: pause or resume the current track.
- F9: next track.
- Shift+F4 and Shift+F5: decrease or increase volume five percent.
- Shift+F7: mute or restore the previous volume.
- BlindSpot remembers the last manually selected volume for its built-in player
  between sessions; temporary muting does not replace that saved level.
- Space: pause or resume playback, except when focus is in a control that
  uses Space itself, such as a button, checkbox, radio button, or edit field.
- Shift+Space: play from the current line in Lyrics. In Lyrics, enable
  **Phrase mode** to pause at
  the start of the next synced line. Alt+Up and Alt+Down move to and play
  the previous or next line using the same mode on Windows; on macOS, use
  Option+Command+Up and Option+Command+Down.
- Ctrl+F in the Lyrics window, or Command+F on macOS: show the lyrics Find
  box. Enter finds the next match and Shift+Enter finds the previous match.
  With focus back in the read-only lyrics, N and P repeat next and previous.
  Escape closes the Find box.
- Preferences can translate lyrics with DeepL. Enter a DeepL API key and
  choose a target language; API Free keys are detected automatically. Lyrics
  are not submitted automatically: use **Fetch translation** in the Lyrics
  window. A successful result adds Translation to the keyboard-accessible
  **Lyrics view** choice. Translations are cached locally to avoid repeat
  charges.
- Ctrl+Space on Windows: select or deselect the focused list item while
  preserving other selections. On macOS, use VoiceOver's native selection
  commands.
- Ctrl+A on Windows and Linux, or Command+A on macOS: select every item in
  the focused list. Select all is also available from the Edit menu and list
  context menus.
- Ctrl+Q: queue marked tracks in list order, or the focused track if none are marked.
- Ctrl+Shift+M opens a Last.fm mix for the focused track; Ctrl+Shift+P starts
  it. Ctrl+Alt+M and Ctrl+Alt+P perform those actions for the currently playing
  track. On macOS, the current-track shortcuts are Option+Command+M and
  Option+Command+P. All shortcuts can be changed in the keyboard manager.
- Ctrl+L: like or unlike the selected item.
- Ctrl+Shift+L: like or unlike the currently loaded track.
- Ctrl+Shift+B: bookmark the current playback position.
- Ctrl+Shift+D: choose a Spotify Connect playback device.
- Ctrl+Shift+N: new playlist.
- Ctrl+Shift+R: speak remaining track time.
- Ctrl+Shift+F: refresh the current view.
- Shift+F10 or the Applications key on Windows, or Option+M on macOS: open
  the selected item's actions.

Search initially displays up to 20 results for a selected category. When more
are available, activate **Load more results** at the end of the list to append
the next page.

The Podcasts library contains subscribed shows and individually saved
episodes. Their context menus can unsubscribe or remove them. Podcast episode
context menus offer **Download episode** when a public RSS
enclosure can be matched through the podcast publisher's feed. Private and
Spotify-exclusive episodes may not provide a public download.
Podcast views can also be filtered using Spotify's declared language metadata
and the listening states Not started, In progress, Completed, and Unknown.
When another page is available, the count explicitly refers to loaded items.

Tracks in playlists you own can be reordered from the selected track's
**Move** context submenu. BlindSpot retains focus on the moved track and
announces its new position.

The same context menu can find alternate recordings by the track's primary
artist. Enter reviews a candidate; the Replace button or candidate context
menu substitutes it at the original playlist position.

User-facing announcements, prompts, status text, and practical error messages
are maintained centrally in `src/blindspot/messages.py`.

Built-in shortcuts can be changed from Keyboard Manager in Preferences. All
commands are shown initially and can be filtered by typing
part of a name, context, or assigned key. Commands are grouped into Main,
Lists, and Lyrics contexts, so the same key can perform different actions in
different parts of BlindSpot.
Assign replaces an existing key in the same context, Clear leaves a command
unassigned, and Restore defaults resets the selected context. Playback,
seeking, Spotify volume, mute, current-track liking and announcements, time
announcements, bookmarks, shuffle, and repeat commands can also receive an
opt-in global assignment from the same manager. Global shortcuts work while
BlindSpot is in the background and may override other applications; none are
assigned by default. Existing global assignments are retained. Custom bindings
are stored in `data/keymap.json` and the application settings on Windows, or
BlindSpot's application-support folder on macOS. Conflict warnings are brief
and shown only once.

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

See the [plain-English changelog](CHANGELOG.txt) for a record of what users
received in each version.

Pushing a version tag such as `v2026.7.0.0` builds Windows and macOS portable
ZIP files and publishes them as a GitHub Release. BlindSpot checks that release
feed at startup and Help > Check for updates checks it on demand. When a newer
build exists, BlindSpot offers to install it. Portable Windows builds download
the ZIP, preserve the `data` folder, replace the application files after
BlindSpot closes, and restart automatically. On macOS, the release page opens
for a manual replacement of the running app bundle.

## Languages

BlindSpot's interface can be translated. English is the built-in language and
the fallback for any message a translation has not covered. A language is a
single gettext `.po` file under `locale/`, so a translator needs a text editor
rather than programming skills. See [locale/README.md](locale/README.md) for
the translator guide.

Polish is included. It was drafted with Claude, and corrections from native
speakers are welcome. By default BlindSpot follows the operating system's
language and uses English when no translation exists; choose a language
explicitly in File, Preferences, Language, then restart BlindSpot.

For developers, user-visible text goes through `tr()`, `ntr()` (plurals),
`ptr()` (context) and `tr_noop()` (module-level tables) from
`blindspot.i18n`. Maintain the catalogues with `scripts/i18n.py`, which needs
Babel (`python -m pip install babel`):

```
python scripts/i18n.py update    # refresh locale/blindspot.pot and every .po
python scripts/i18n.py check     # validate translations and show coverage
python scripts/i18n.py compile   # build the .mo files the app loads
```

Compiled `.mo` files are build output. The release builds compile them, and CI
fails if the template is stale or a translation breaks a placeholder.

## License

Copyright © 2026 Sam Taylor. BlindSpot is free software licensed under the
GNU General Public License version 3 or later. See `LICENSE`.
