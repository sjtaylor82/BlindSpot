"""Readable exports of a track list: plain text and CSV.

This exports metadata only (position, title, artist, album, duration and a
Spotify link). It never downloads audio.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .models import ItemKind, SpotifyItem

EXPORTABLE_KINDS = frozenset({ItemKind.TRACK, ItemKind.EPISODE})
CSV_COLUMNS = ("Position", "Title", "Artist", "Album", "Duration", "Spotify link")
_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_SPOTIFY_URI = re.compile(r"^spotify:(track|episode):([A-Za-z0-9]+)$")


@dataclass(frozen=True, slots=True)
class ExportRow:
    position: int
    title: str
    artist: str
    album: str
    duration: str
    link: str


def duration_label(milliseconds: int) -> str:
    """Format a duration as m:ss, or h:mm:ss for an hour or more."""
    if milliseconds <= 0:
        return ""
    seconds = round(milliseconds / 1000)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def spotify_link(item: SpotifyItem) -> str:
    """Return a shareable open.spotify.com link, or nothing if unavailable."""
    match = _SPOTIFY_URI.match(item.uri or "")
    if not match:
        return ""
    return f"https://open.spotify.com/{match[1]}/{match[2]}"


def is_exportable(item: SpotifyItem) -> bool:
    return item.kind in EXPORTABLE_KINDS


def is_partial(items: list[SpotifyItem]) -> bool:
    """True when the list still has a row that loads more results."""
    return any(
        item.kind == ItemKind.HEADING
        and any("load_more" in str(key) for key in item.raw)
        for item in items
    )


def export_rows(items: list[SpotifyItem]) -> list[ExportRow]:
    """Number the exportable items in display order, skipping headings."""
    rows = []
    for item in items:
        if not is_exportable(item):
            continue
        rows.append(
            ExportRow(
                len(rows) + 1,
                item.name,
                item.artist,
                item.album,
                duration_label(item.duration_ms),
                spotify_link(item),
            )
        )
    return rows


def safe_filename(name: str, fallback: str = "BlindSpot list") -> str:
    """Make a name usable as a file name on Windows, macOS and Linux."""
    cleaned = _UNSAFE_FILENAME.sub(" ", name)
    cleaned = " ".join(cleaned.split()).strip(". ")
    return (cleaned or fallback)[:100].rstrip(". ")


def to_text(
    name: str,
    rows: list[ExportRow],
    *,
    partial: bool = False,
    today: date | None = None,
) -> str:
    when = (today or date.today()).strftime("%d %B %Y").lstrip("0")
    noun = "item" if len(rows) == 1 else "items"
    lines = [name, f"Exported from BlindSpot on {when}: {len(rows)} {noun}"]
    if partial:
        lines.append(
            "This is a partial list: more items exist that had not been loaded."
        )
    lines.append("")
    for row in rows:
        parts = [row.title, row.artist, row.album, row.duration]
        line = f"{row.position}. " + " - ".join(part for part in parts if part)
        if row.link:
            line += f" ({row.link})"
        lines.append(line)
    return "\n".join(lines) + "\n"


def _csv_cell(value: str) -> str:
    """Stop a spreadsheet from running a title that looks like a formula."""
    return "'" + value if value.startswith(_FORMULA_START) else value


def to_csv(rows: list[ExportRow]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        writer.writerow(
            [
                row.position,
                _csv_cell(row.title),
                _csv_cell(row.artist),
                _csv_cell(row.album),
                row.duration,
                row.link,
            ]
        )
    return buffer.getvalue()


def write_export(
    path: str | Path,
    fmt: str,
    name: str,
    items: list[SpotifyItem],
    *,
    partial: bool = False,
) -> int:
    """Write the exportable items to `path` and return how many were written.

    CSV is written with a byte order mark so spreadsheet programs open
    accented and Polish characters correctly.
    """
    rows = export_rows(items)
    if fmt == "csv":
        Path(path).write_text(to_csv(rows), encoding="utf-8-sig", newline="")
    else:
        Path(path).write_text(
            to_text(name, rows, partial=partial), encoding="utf-8"
        )
    return len(rows)


def format_for_path(path: str, fallback_index: int) -> str:
    """Pick "csv" or "txt" from the chosen file name, else from the filter."""
    lowered = path.lower()
    if lowered.endswith(".csv"):
        return "csv"
    if lowered.endswith(".txt"):
        return "txt"
    return "csv" if fallback_index == 1 else "txt"
