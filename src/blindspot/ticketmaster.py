from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .network import TLS_CONTEXT


API_ROOT = "https://app.ticketmaster.com/discovery/v2"

# Ticketmaster's published Discovery API country list. Labels are presented to
# users; codes are sent to the API. Ticketmaster publishes ND for Northern
# Ireland even though the rest of the list largely follows ISO 3166-1 alpha-2.
TICKETMASTER_COUNTRIES = (
    ("AD", "Andorra"), ("AI", "Anguilla"), ("AR", "Argentina"),
    ("AU", "Australia"), ("AT", "Austria"), ("AZ", "Azerbaijan"),
    ("BS", "Bahamas"), ("BH", "Bahrain"), ("BB", "Barbados"),
    ("BE", "Belgium"), ("BM", "Bermuda"), ("BR", "Brazil"),
    ("BG", "Bulgaria"), ("CA", "Canada"), ("CL", "Chile"),
    ("CN", "China"), ("CO", "Colombia"), ("CR", "Costa Rica"),
    ("HR", "Croatia"), ("CY", "Cyprus"), ("CZ", "Czech Republic"),
    ("DK", "Denmark"), ("DO", "Dominican Republic"), ("EC", "Ecuador"),
    ("EE", "Estonia"), ("FO", "Faroe Islands"), ("FI", "Finland"),
    ("FR", "France"), ("GE", "Georgia"), ("DE", "Germany"),
    ("GH", "Ghana"), ("GI", "Gibraltar"),
    ("GB", "United Kingdom / Great Britain"), ("GR", "Greece"),
    ("HK", "Hong Kong"), ("HU", "Hungary"), ("IS", "Iceland"),
    ("IN", "India"), ("IE", "Ireland"), ("IL", "Israel"),
    ("IT", "Italy"), ("JM", "Jamaica"), ("JP", "Japan"),
    ("KR", "South Korea"), ("LV", "Latvia"), ("LB", "Lebanon"),
    ("LT", "Lithuania"), ("LU", "Luxembourg"), ("MY", "Malaysia"),
    ("MT", "Malta"), ("MX", "Mexico"), ("MC", "Monaco"),
    ("ME", "Montenegro"), ("MA", "Morocco"), ("NL", "Netherlands"),
    ("AN", "Netherlands Antilles"), ("NZ", "New Zealand"),
    ("ND", "Northern Ireland"), ("NO", "Norway"), ("PE", "Peru"),
    ("PL", "Poland"), ("PT", "Portugal"), ("RO", "Romania"),
    ("RU", "Russian Federation"), ("LC", "Saint Lucia"),
    ("SA", "Saudi Arabia"), ("RS", "Serbia"), ("SG", "Singapore"),
    ("SK", "Slovakia"), ("SI", "Slovenia"), ("ZA", "South Africa"),
    ("ES", "Spain"), ("SE", "Sweden"), ("CH", "Switzerland"),
    ("TW", "Taiwan"), ("TH", "Thailand"),
    ("TT", "Trinidad and Tobago"), ("TR", "Turkey"), ("UA", "Ukraine"),
    ("AE", "United Arab Emirates"), ("US", "United States"),
    ("UY", "Uruguay"), ("VE", "Venezuela"),
)


class TicketmasterError(RuntimeError):
    pass


@dataclass(slots=True)
class ConcertEvent:
    id: str
    name: str
    date: str = ""
    time: str = ""
    venue: str = ""
    city: str = ""
    state: str = ""
    country: str = ""
    genre: str = ""
    url: str = ""

    def accessible_label(self) -> str:
        parts = [self.name]
        location = ", ".join(
            part
            for part in (self.venue, self.city, self.state, self.country)
            if part
        )
        if location:
            parts.append(location)
        if self.genre:
            parts.append(self.genre)
        when = self.date
        if self.time:
            when += f" at {self.time[:5]}"
        if when:
            parts.append(when)
        return " — ".join(parts)


@dataclass(slots=True)
class ConcertPage:
    events: list[ConcertEvent]
    page: int
    total_pages: int
    total_events: int

    @property
    def has_more(self) -> bool:
        return self.page + 1 < self.total_pages and (self.page + 1) * 50 < 1000


@dataclass(slots=True)
class EventCategory:
    id: str
    name: str
    genres: list[tuple[str, str]]


class TicketmasterClient:
    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key.strip()

    def search(
        self,
        *,
        keyword: str = "",
        country: str = "",
        state: str = "",
        city: str = "",
        genre: str = "",
        category_id: str = "",
        genre_id: str = "",
        start_date: str = "",
        end_date: str = "",
        page: int = 0,
    ) -> ConcertPage:
        if not self.api_key:
            raise TicketmasterError(
                "Enter a Ticketmaster API key in BlindSpot preferences first."
            )
        query: dict[str, str | int] = {
            "apikey": self.api_key,
            "size": 50,
            "page": page,
            "sort": "date,asc",
        }
        now = datetime.now(timezone.utc).replace(microsecond=0)
        today = now.date().isoformat()
        query["startDateTime"] = (
            now.isoformat().replace("+00:00", "Z")
            if not start_date or start_date == today
            else f"{start_date}T00:00:00Z"
        )
        if end_date:
            query["endDateTime"] = f"{end_date}T23:59:59Z"
        for key, value in (
            ("keyword", keyword),
            ("countryCode", country.upper()),
            ("stateCode", state.upper()),
            ("city", city),
            ("classificationName", genre),
            ("segmentId", category_id),
            ("genreId", genre_id),
        ):
            if value.strip():
                query[key] = value.strip()
        url = f"{API_ROOT}/events.json?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(
            url, headers={"User-Agent": "BlindSpot concert search"}
        )
        try:
            with urllib.request.urlopen(
                request, timeout=20, context=TLS_CONTEXT
            ) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            try:
                payload = json.loads(error.read().decode("utf-8"))
                detail = (
                    payload.get("fault", {}).get("faultstring")
                    or payload.get("detail")
                    or payload.get("message")
                )
            except Exception:
                detail = None
            raise TicketmasterError(
                f"Ticketmaster returned {error.code}"
                + (f": {detail}" if detail else ".")
            ) from error
        except (OSError, ValueError) as error:
            raise TicketmasterError(f"Could not search Ticketmaster: {error}") from error

        values = (data.get("_embedded") or {}).get("events") or []
        page_data = data.get("page") or {}
        return ConcertPage(
            [self._map_event(value) for value in values],
            int(page_data.get("number") or page),
            int(page_data.get("totalPages") or 0),
            int(page_data.get("totalElements") or len(values)),
        )

    def classifications(self) -> list[EventCategory]:
        if not self.api_key:
            raise TicketmasterError(
                "Enter a Ticketmaster API key in BlindSpot preferences first."
            )
        query = urllib.parse.urlencode(
            {"apikey": self.api_key, "locale": "*", "size": 200}
        )
        request = urllib.request.Request(
            f"{API_ROOT}/classifications.json?{query}",
            headers={"User-Agent": "BlindSpot concert search"},
        )
        try:
            with urllib.request.urlopen(
                request, timeout=20, context=TLS_CONTEXT
            ) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise TicketmasterError(
                f"Ticketmaster returned {error.code} while loading categories."
            ) from error
        except (OSError, ValueError) as error:
            raise TicketmasterError(
                f"Could not load Ticketmaster categories: {error}"
            ) from error
        categories = []
        for classification in (
            (data.get("_embedded") or {}).get("classifications") or []
        ):
            segment = classification.get("segment") or {}
            segment_id = str(segment.get("id") or "")
            segment_name = str(segment.get("name") or "")
            if not segment_id or not segment_name:
                continue
            genres = []
            for genre in (
                (segment.get("_embedded") or {}).get("genres") or []
            ):
                genre_id = str(genre.get("id") or "")
                genre_name = str(genre.get("name") or "")
                if genre_id and genre_name:
                    genres.append((genre_id, genre_name))
            categories.append(
                EventCategory(
                    segment_id,
                    segment_name,
                    sorted(genres, key=lambda value: value[1].casefold()),
                )
            )
        return sorted(categories, key=lambda value: value.name.casefold())

    @staticmethod
    def _map_event(value: dict[str, Any]) -> ConcertEvent:
        dates = value.get("dates") or {}
        start = dates.get("start") or {}
        venues = (value.get("_embedded") or {}).get("venues") or []
        venue = venues[0] if venues else {}
        classifications = value.get("classifications") or []
        classification = classifications[0] if classifications else {}
        genre = classification.get("genre") or {}
        return ConcertEvent(
            id=str(value.get("id") or ""),
            name=str(value.get("name") or "Untitled event"),
            date=str(start.get("localDate") or "Date to be announced"),
            time=str(start.get("localTime") or ""),
            venue=str(venue.get("name") or ""),
            city=str((venue.get("city") or {}).get("name") or ""),
            state=str((venue.get("state") or {}).get("name") or ""),
            country=str((venue.get("country") or {}).get("name") or ""),
            genre=str(genre.get("name") or ""),
            url=str(value.get("url") or ""),
        )
