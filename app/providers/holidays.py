"""US bank holidays via Nager.Date, used to estimate a realistic funding date.

A lender quoting 'funds in 5 business days' means five days the bank is open.
Counting calendar days over a holiday week produces a date that cannot happen.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.cache import SourceLog, fetch_json
from app.config import ENDPOINTS, TTL


async def bank_holidays(
    year: int, country: str = "US", slog: SourceLog | None = None
) -> set[str]:
    data = await fetch_json(
        "nager",
        f"{ENDPOINTS['nager']}/{year}/{country}",
        ttl=TTL["nager"],
        slog=slog,
    )
    if not isinstance(data, list):
        return set()
    # Only days banks actually close. Nager marks these with a Public or Bank type.
    return {
        row["date"]
        for row in data
        if row.get("date") and {"Public", "Bank"} & set(row.get("types") or [])
    }


async def add_business_days(
    start: date, days: int, country: str = "US", slog: SourceLog | None = None
) -> dict:
    """Advance a date by N business days, skipping weekends and bank holidays."""
    closed = await bank_holidays(start.year, country, slog)
    closed |= await bank_holidays(start.year + 1, country, slog)

    current = start
    remaining = days
    skipped: list[str] = []

    while remaining > 0:
        current += timedelta(days=1)
        iso = current.isoformat()
        if current.weekday() >= 5:
            continue
        if iso in closed:
            skipped.append(iso)
            continue
        remaining -= 1

    return {
        "date": current.isoformat(),
        "business_days": days,
        "holidays_skipped": skipped,
        "holiday_data_available": bool(closed),
    }
