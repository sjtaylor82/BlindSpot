from __future__ import annotations

from dataclasses import asdict, dataclass

from .models import ItemKind, SpotifyItem

# Pausing or seeking takes this long to reach the audio after the cutoff is
# detected, so the cutoff fires early to make the sound stop at the marked end.
CART_STOP_LEAD_MS = 250


@dataclass(frozen=True, slots=True)
class Cart:
    number: int
    track_id: str
    uri: str
    name: str
    artist: str
    album: str
    duration_ms: int
    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        if not 1 <= self.number <= 9:
            raise ValueError("Cart number must be from 1 to 9")
        if self.start_ms < 0 or self.end_ms <= self.start_ms:
            raise ValueError("Cart end must be after its start")

    @property
    def item(self) -> SpotifyItem:
        return SpotifyItem(
            id=self.track_id,
            kind=ItemKind.TRACK,
            name=self.name,
            artist=self.artist,
            album=self.album,
            duration_ms=self.duration_ms,
            uri=self.uri,
        )

    def record(self) -> dict[str, object]:
        return asdict(self)


def load_carts(value: object) -> dict[int, Cart]:
    if not isinstance(value, list):
        return {}
    carts: dict[int, Cart] = {}
    for record in value:
        if not isinstance(record, dict):
            continue
        try:
            cart = Cart(
                number=int(record["number"]),
                track_id=str(record["track_id"]),
                uri=str(record["uri"]),
                name=str(record.get("name") or "Untitled"),
                artist=str(record.get("artist") or ""),
                album=str(record.get("album") or ""),
                duration_ms=int(record.get("duration_ms") or 0),
                start_ms=int(record["start_ms"]),
                end_ms=int(record["end_ms"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
        carts[cart.number] = cart
    return carts


def dump_carts(carts: dict[int, Cart]) -> list[dict[str, object]]:
    return [carts[number].record() for number in sorted(carts)]


def cart_cutoff_state(cart: Cart, position_ms: int, armed: bool) -> tuple[bool, bool]:
    """Return ``(armed, stop)`` for a reported cart playback position.

    A cart must first be observed inside its range. This prevents the position
    from the previously playing song (including the same song beyond the cart
    end) from stopping playback before Spotify has applied the cart seek.
    """
    if not armed:
        if cart.start_ms - 1_000 <= position_ms < cart.end_ms:
            return True, False
        return False, False
    lead_ms = min(CART_STOP_LEAD_MS, (cart.end_ms - cart.start_ms) // 2)
    return True, position_ms >= cart.end_ms - lead_ms


def next_cart_number(carts: dict[int, Cart], current: int) -> int | None:
    numbers = sorted(carts)
    if not numbers:
        return None
    return next((number for number in numbers if number > current), numbers[0])
