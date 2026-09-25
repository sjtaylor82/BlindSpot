"""BlindSpot's own record of what it has played.

Spotify only adds a song to Recently Played once it has played to the end,
so songs skipped part way through never appear there.  BlindSpot records
any Spotify song or episode it has played for LISTEN_SECONDS and merges
that record with Spotify's list, newest first.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .models import ItemKind, SpotifyItem
from .portable import PortableStore
from .spotify import played_at_label

FILE_NAME = "recently_played.json"
LISTEN_SECONDS = 20
LIMIT = 50
# Playback updates arrive about every ten seconds while nothing changes.
# A longer gap means updates stopped, so it is not counted as listening.
MAX_UPDATE_GAP_SECONDS = 15.0

_OLDEST = datetime.min.replace(tzinfo=timezone.utc)


class ListeningTimer:
    """Count how long the current item has actually played, ignoring pauses."""

    def __init__(self) -> None:
        self.key = ""
        self.seconds = 0.0
        self.last_update: float | None = None
        self.recorded = False

    def update(self, key: str, playing: bool, now: float) -> bool:
        """Return True once, when key first reaches LISTEN_SECONDS of play."""
        if key != self.key:
            self.key = key
            self.seconds = 0.0
            self.last_update = None
            self.recorded = False
        if playing and self.last_update is not None:
            self.seconds += min(max(now - self.last_update, 0.0), MAX_UPDATE_GAP_SECONDS)
        self.last_update = now if playing else None
        if key and playing and not self.recorded and self.seconds >= LISTEN_SECONDS:
            self.recorded = True
            return True
        return False


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def played_at(item: SpotifyItem) -> datetime:
    value = str(item.raw.get("played_at") or "")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return _OLDEST
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _records(store: PortableStore) -> list[dict]:
    records = store.read(FILE_NAME, []) or []
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def remember(
    store: PortableStore,
    item: SpotifyItem,
    when: datetime | None = None,
) -> None:
    record = {
        "id": item.id,
        "kind": item.kind.value,
        "name": item.name,
        "artist": item.artist,
        "album": item.album,
        "duration_ms": item.duration_ms,
        "uri": item.uri,
        "played_at": _format_time(when or datetime.now(timezone.utc)),
        "raw": item.raw,
    }
    records = [
        existing
        for existing in _records(store)
        if str(existing.get("uri") or "") != item.uri
    ]
    records.insert(0, record)
    store.write(FILE_NAME, records[:LIMIT])


def load(store: PortableStore) -> list[SpotifyItem]:
    items = []
    for record in _records(store):
        # Records from before 2026.9.4 have no time, so they can't be placed
        # in the list and are left out.
        if not record.get("id") or not record.get("played_at"):
            continue
        try:
            kind = ItemKind(record.get("kind", ItemKind.TRACK))
        except ValueError:
            kind = ItemKind.TRACK
        raw = dict(record.get("raw") or {})
        raw["played_at"] = str(record["played_at"])
        raw["played_at_label"] = played_at_label(raw["played_at"])
        items.append(
            SpotifyItem(
                id=str(record["id"]),
                kind=kind,
                name=str(record.get("name") or ""),
                artist=str(record.get("artist") or ""),
                album=str(record.get("album") or ""),
                duration_ms=int(record.get("duration_ms") or 0),
                uri=str(record.get("uri") or ""),
                raw=raw,
            )
        )
    return items


def merge(*lists: list[SpotifyItem]) -> list[SpotifyItem]:
    """Combine play lists newest first, keeping each item's latest play."""
    combined = sorted(
        (item for items in lists for item in items),
        key=played_at,
        reverse=True,
    )
    merged: list[SpotifyItem] = []
    seen: set[str] = set()
    for item in combined:
        key = item.uri or f"{item.kind.value}:{item.id}"
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged[:LIMIT]
