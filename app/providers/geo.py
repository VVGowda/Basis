"""ZIP code to place, via Zippopotam.us."""

from __future__ import annotations

import re
from typing import Any

from app.cache import SourceLog, fetch_json
from app.config import ENDPOINTS, TTL

ZIP_RE = re.compile(r"^\d{5}$")


async def lookup_zip(zip_code: str, slog: SourceLog | None = None) -> dict[str, Any] | None:
    """Return {city, state, state_abbr, lat, lon} for a US ZIP, or None."""
    zip_code = (zip_code or "").strip()
    if not ZIP_RE.match(zip_code):
        return None

    data = await fetch_json(
        "zippopotam",
        f"{ENDPOINTS['zippopotam']}/us/{zip_code}",
        ttl=TTL["zippopotam"],
        slog=slog,
    )
    if not data or not data.get("places"):
        return None

    place = data["places"][0]
    return {
        "zip": zip_code,
        "city": place.get("place name"),
        "state": place.get("state"),
        "state_abbr": place.get("state abbreviation"),
        "lat": _num(place.get("latitude")),
        "lon": _num(place.get("longitude")),
    }


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
