from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .i18n import tr, tr_noop
from .network import TLS_CONTEXT


API_ROOT = "https://app.ticketmaster.com/discovery/v2"

# Ticketmaster's published Discovery API country list. Labels are presented to
# users; codes are sent to the API. Ticketmaster publishes ND for Northern
# Ireland even though the rest of the list largely follows ISO 3166-1 alpha-2.
TICKETMASTER_COUNTRIES = (
    ("AD", tr_noop("Andorra")),
    ("AI", tr_noop("Anguilla")),
    ("AR", tr_noop("Argentina")),
    ("AU", tr_noop("Australia")),
    ("AT", tr_noop("Austria")),
    ("AZ", tr_noop("Azerbaijan")),
    ("BS", tr_noop("Bahamas")),
    ("BH", tr_noop("Bahrain")),
    ("BB", tr_noop("Barbados")),
    ("BE", tr_noop("Belgium")),
    ("BM", tr_noop("Bermuda")),
    ("BR", tr_noop("Brazil")),
    ("BG", tr_noop("Bulgaria")),
    ("CA", tr_noop("Canada")),
    ("CL", tr_noop("Chile")),
    ("CN", tr_noop("China")),
    ("CO", tr_noop("Colombia")),
    ("CR", tr_noop("Costa Rica")),
    ("HR", tr_noop("Croatia")),
    ("CY", tr_noop("Cyprus")),
    ("CZ", tr_noop("Czech Republic")),
    ("DK", tr_noop("Denmark")),
    ("DO", tr_noop("Dominican Republic")),
    ("EC", tr_noop("Ecuador")),
    ("EE", tr_noop("Estonia")),
    ("FO", tr_noop("Faroe Islands")),
    ("FI", tr_noop("Finland")),
    ("FR", tr_noop("France")),
    ("GE", tr_noop("Georgia")),
    ("DE", tr_noop("Germany")),
    ("GH", tr_noop("Ghana")),
    ("GI", tr_noop("Gibraltar")),
    ("GB", tr_noop("United Kingdom / Great Britain")),
    ("GR", tr_noop("Greece")),
    ("HK", tr_noop("Hong Kong")),
    ("HU", tr_noop("Hungary")),
    ("IS", tr_noop("Iceland")),
    ("IN", tr_noop("India")),
    ("IE", tr_noop("Ireland")),
    ("IL", tr_noop("Israel")),
    ("IT", tr_noop("Italy")),
    ("JM", tr_noop("Jamaica")),
    ("JP", tr_noop("Japan")),
    ("KR", tr_noop("South Korea")),
    ("LV", tr_noop("Latvia")),
    ("LB", tr_noop("Lebanon")),
    ("LT", tr_noop("Lithuania")),
    ("LU", tr_noop("Luxembourg")),
    ("MY", tr_noop("Malaysia")),
    ("MT", tr_noop("Malta")),
    ("MX", tr_noop("Mexico")),
    ("MC", tr_noop("Monaco")),
    ("ME", tr_noop("Montenegro")),
    ("MA", tr_noop("Morocco")),
    ("NL", tr_noop("Netherlands")),
    ("AN", tr_noop("Netherlands Antilles")),
    ("NZ", tr_noop("New Zealand")),
    ("ND", tr_noop("Northern Ireland")),
    ("NO", tr_noop("Norway")),
    ("PE", tr_noop("Peru")),
    ("PL", tr_noop("Poland")),
    ("PT", tr_noop("Portugal")),
    ("RO", tr_noop("Romania")),
    ("RU", tr_noop("Russian Federation")),
    ("LC", tr_noop("Saint Lucia")),
    ("SA", tr_noop("Saudi Arabia")),
    ("RS", tr_noop("Serbia")),
    ("SG", tr_noop("Singapore")),
    ("SK", tr_noop("Slovakia")),
    ("SI", tr_noop("Slovenia")),
    ("ZA", tr_noop("South Africa")),
    ("ES", tr_noop("Spain")),
    ("SE", tr_noop("Sweden")),
    ("CH", tr_noop("Switzerland")),
    ("TW", tr_noop("Taiwan")),
    ("TH", tr_noop("Thailand")),
    ("TT", tr_noop("Trinidad and Tobago")),
    ("TR", tr_noop("Turkey")),
    ("UA", tr_noop("Ukraine")),
    ("AE", tr_noop("United Arab Emirates")),
    ("US", tr_noop("United States")),
    ("UY", tr_noop("Uruguay")),
    ("VE", tr_noop("Venezuela")),
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
                tr(
                    "Enter a Ticketmaster API key in BlindSpot preferences "
                    "first."
                )
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
                tr("Ticketmaster returned {code}").format(code=error.code)
                + (f": {detail}" if detail else ".")
            ) from error
        except (OSError, ValueError) as error:
            raise TicketmasterError(tr(
                "Could not search Ticketmaster: {error}"
            ).format(error=error)) from error

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
                tr(
                    "Enter a Ticketmaster API key in BlindSpot preferences "
                    "first."
                )
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
                tr(
                    "Ticketmaster returned {code} while loading categories."
                ).format(code=error.code)
            ) from error
        except (OSError, ValueError) as error:
            raise TicketmasterError(
                tr(
                    "Could not load Ticketmaster categories: {error}"
                ).format(error=error)
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
            name=str(value.get("name") or tr("Untitled event")),
            date=str(start.get("localDate") or tr("Date to be announced")),
            time=str(start.get("localTime") or ""),
            venue=str(venue.get("name") or ""),
            city=str((venue.get("city") or {}).get("name") or ""),
            state=str((venue.get("state") or {}).get("name") or ""),
            country=str((venue.get("country") or {}).get("name") or ""),
            genre=str(genre.get("name") or ""),
            url=str(value.get("url") or ""),
        )
