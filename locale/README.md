# Translating BlindSpot

You do not need to be a programmer. A language is one text file:

```
locale/<language code>/LC_MESSAGES/blindspot.po
```

For example, Polish is `locale/pl/LC_MESSAGES/blindspot.po`. Each entry pairs
an English message (`msgid`) with your translation (`msgstr`). Anything you
leave empty is shown in English, so a partly finished translation is safe to
use and to submit.

## Two ways to help

* **Improve an existing language.** Open its `.po` file in a text editor or in
  [Poedit](https://poedit.net) (free) and correct the `msgstr` lines.
* **Add a new language.** Ask for it in a
  [GitHub issue](https://github.com/sjtaylor82/BlindSpot/issues), or follow
  "Starting a new language" below.

Send your finished `.po` file by attaching it to an issue, or open a pull
request. If you are not comfortable with GitHub, attaching the file is fine.

## Rules that keep the app working

* **Placeholders such as `{name}` and `{count}` must stay exactly as written.**
  You may move them to wherever your grammar needs them, but do not translate
  or remove them.
* **`&` marks the Alt-key shortcut letter in menus and buttons.** In
  `&Play` the shortcut is Alt+P. Keep one `&` in your translation, put it
  before a letter of your word, and try to use a different letter for each item
  in the same menu.
* **Plural entries have one line per plural form** (`msgstr[0]`, `msgstr[1]`,
  and so on). The file header states how many forms your language has and which
  numbers use which form. Polish has three.
* **Keep line breaks** (`\n`) where the English has them.
* **Leave key names and shortcuts alone**, such as `(F6)`, `Ctrl+A` and
  `Command+A`. Leave product names alone: BlindSpot, Spotify, Last.fm,
  MusicBrainz, Ticketmaster, Apple Music.
* **Screen readers read these messages aloud.** Prefer short, natural phrases
  and check your wording with a screen reader if you can.
* **Some entries have a `msgctxt` line.** It explains where the text is used.
  For example `month in a date` means the month name as it appears inside
  "5 March 2026"; use the grammatical form your language needs there.
* **One entry is the language's own name.** Its context is "The name of this
  language, written in that language" and its English text is `English`.
  Translate it to your language's name for itself ("Polski", "Deutsch"). This
  is what appears in the Language choice in Preferences.

`python scripts/i18n.py check` reports mistakes of this kind, so run it before
you submit.

## Trying your translation

You need Python and Babel. From the BlindSpot folder:

```
pip install -r requirements.txt babel
python scripts/i18n.py check
python scripts/i18n.py compile
```

Then start BlindSpot (`python src/blindspot_launcher.py`), open
File, Preferences, choose your language and restart BlindSpot. The compiled
`.mo` files are build output and are not committed.

## Starting a new language

```
python scripts/i18n.py new de Deutsch
```

This creates `locale/de/LC_MESSAGES/blindspot.po` with every message ready to
translate. Use the two-letter language code (`de`, `fr`, `es`, and so on).

## When BlindSpot changes

New and changed English text appears in your file as empty entries after the
maintainer runs `python scripts/i18n.py update`. Translate them at your own
pace. Until then those messages are shown in English.

## What is not translated

* The manual (`manual.html`) is English only for now.
* Diagnostic reports and log files stay in English so problems can be
  investigated.
* Names supplied by Spotify, Last.fm and Ticketmaster (genres, device names,
  event names) appear as those services provide them.

## Status of the shipped translations

The Polish translation was drafted with Claude (an AI model). Corrections are
very welcome, especially of menu wording, grammar and anything that sounds
unnatural when spoken by a screen reader.
