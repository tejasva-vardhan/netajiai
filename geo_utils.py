"""
Reverse geocoding (Nominatim / OpenStreetMap) and DB city matching.
See https://operations.osmfoundation.org/policies/nominatim/ — use a valid User-Agent.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from models import City, State

logger = logging.getLogger(__name__)

NOMINATIM_REVERSE = "https://nominatim.openstreetmap.org/reverse"
AINETA_USER_AGENT = "AINETA-chatbot/1.0 (civic complaint assistant; local development)"

# OSM / common spellings → canonical `City.name` in our database
CITY_NAME_ALIASES: Dict[str, str] = {
    "bengaluru": "Bangalore",
    "bombay": "Mumbai",
    "gurugram": "Gurgaon",
    "vizag": "Visakhapatnam",
    "new delhi": "Delhi",
}

# Nominatim often returns full UT names; our `State.name` uses short forms (e.g. "Delhi").
STATE_NAME_ALIASES: Dict[str, str] = {
    "national capital territory of delhi": "Delhi",
    "nct of delhi": "Delhi",
}


def _normalize_state_name(state: Optional[str]) -> Optional[str]:
    if not state or not str(state).strip():
        return None
    key = state.strip().lower()
    return STATE_NAME_ALIASES.get(key, state.strip())

FALLBACK_CITY_NAME = "General India Helpdesk"


def _resolve_default_city_id(db: Session) -> Optional[int]:
    """Prefer DEFAULT_CITY_ID env, else Shivpuri, else first city."""
    raw = os.getenv("DEFAULT_CITY_ID")
    if raw and raw.strip().isdigit():
        return int(raw)
    city = db.query(City).filter(City.name == "Shivpuri").first()
    if city:
        return city.id
    first = db.query(City).order_by(City.id.asc()).first()
    return first.id if first else None


def reverse_geocode_osm(latitude: float, longitude: float) -> Optional[Dict[str, Optional[str]]]:
    """
    Call Nominatim reverse API. Returns {"city_name": str|None, "state_name": str|None} or None on failure.
    """
    params = urllib.parse.urlencode(
        {
            "lat": latitude,
            "lon": longitude,
            "format": "json",
            "addressdetails": 1,
        }
    )
    url = f"{NOMINATIM_REVERSE}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": AINETA_USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger.warning("Reverse geocoding failed: %s", exc)
        return None

    addr = raw.get("address") or {}
    city = (
        addr.get("city")
        or addr.get("town")
        or addr.get("village")
        or addr.get("municipality")
        or addr.get("county")
        or addr.get("state_district")
    )
    state = addr.get("state")
    if isinstance(city, str):
        city = city.strip()
    else:
        city = None
    if isinstance(state, str):
        state = state.strip()
    else:
        state = None

    if not city and not state:
        return None
    return {"city_name": city, "state_name": state}


def _canonical_city_name(detected: str) -> str:
    key = detected.strip().lower()
    return CITY_NAME_ALIASES.get(key, detected.strip())


def find_city_in_db(
    db: Session,
    city_name: Optional[str],
    state_name: Optional[str],
) -> Optional[City]:
    """Match a geocoded place to a `City` row (case-insensitive), optionally scoped by state."""
    if not city_name or not str(city_name).strip():
        return None
    canonical = _canonical_city_name(city_name)
    candidates = [canonical, city_name.strip()]
    state_for_match = _normalize_state_name(state_name)

    for name in candidates:
        if not name:
            continue
        lower = name.lower()

        q = (
            db.query(City)
            .options(joinedload(City.state))
            .filter(func.lower(City.name) == lower)
        )
        if state_for_match:
            st_lower = state_for_match.lower()
            q = q.join(State, City.state_id == State.id).filter(
                func.lower(State.name) == st_lower
            )
            hit = q.first()
            if hit:
                return hit

        hit = (
            db.query(City)
            .options(joinedload(City.state))
            .filter(func.lower(City.name) == lower)
            .first()
        )
        if hit:
            return hit

    return None


def get_fallback_city_id(db: Session) -> Optional[int]:
    row = db.query(City).filter(City.name == FALLBACK_CITY_NAME).first()
    return row.id if row else None


def resolve_city_id_from_gps(
    db: Session,
    latitude: float,
    longitude: float,
) -> Tuple[int, Dict[str, Any]]:
    """
    Reverse-geocode (lat, lon), match `City` or use General India Helpdesk.
    Returns (city_id, debug_dict).
    """
    fallback_id = get_fallback_city_id(db)
    geo = reverse_geocode_osm(latitude, longitude)
    if not geo:
        print(
            f"⚠️ [GEO] Reverse geocode returned nothing for ({latitude}, {longitude}); "
            f"using fallback city_id={fallback_id}"
        )
        if fallback_id is None:
            raise RuntimeError(
                f"Fallback city {FALLBACK_CITY_NAME!r} missing — run seed or migrations."
            )
        return fallback_id, {
            "geo_source": "nominatim",
            "matched": False,
            "reason": "reverse_geocode_failed",
            "latitude": latitude,
            "longitude": longitude,
        }

    city_name = geo.get("city_name")
    state_name = geo.get("state_name")
    matched = find_city_in_db(db, city_name, state_name)

    if matched:
        print(
            f"✅ [GEO] Matched GPS to city id={matched.id} name={matched.name!r} "
            f"(detected: {city_name!r}, state: {state_name!r})"
        )
        return matched.id, {
            "geo_source": "nominatim",
            "matched": True,
            "detected_city": city_name,
            "detected_state": state_name,
            "city_id": matched.id,
            "latitude": latitude,
            "longitude": longitude,
        }

    print(
        f"📍 [GEO] Unregistered city request — detected {city_name!r}, state {state_name!r}; "
        f"using General India Helpdesk (city_id={fallback_id})"
    )
    if fallback_id is None:
        raise RuntimeError(
            f"Fallback city {FALLBACK_CITY_NAME!r} missing — run seed or migrations."
        )
    return fallback_id, {
        "geo_source": "nominatim",
        "matched": False,
        "reason": "unregistered_city",
        "detected_city": city_name,
        "detected_state": state_name,
        "latitude": latitude,
        "longitude": longitude,
        "fallback_city_id": fallback_id,
    }


def resolve_city_id_for_request(
    db: Session,
    latitude: Optional[float],
    longitude: Optional[float],
    city_id_override: Optional[int],
) -> int:
    """
    Prefer GPS-based resolution when both coordinates are present.
    Else use explicit city_id if provided, else default env/Shivpuri/first city.
    """
    if (
        latitude is not None
        and longitude is not None
        and not (latitude == 0.0 and longitude == 0.0)
    ):
        cid, _meta = resolve_city_id_from_gps(db, latitude, longitude)
        return cid

    if city_id_override is not None:
        return city_id_override

    resolved = _resolve_default_city_id(db)
    if resolved is None:
        raise RuntimeError("No city configured — seed the database.")
    return resolved
