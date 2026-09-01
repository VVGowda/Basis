"""Currency conversion via Frankfurter (European Central Bank reference rates).

Income entered in rupees, pounds or euros is converted to USD before any
debt-to-income ratio is computed. Comparing a number in one currency against a
threshold in another is the kind of silent bug that produces a confidently
wrong answer, so the conversion is explicit and reported back to the user.
"""

from __future__ import annotations

from typing import Any

from app.cache import SourceLog, fetch_json
from app.config import ENDPOINTS, TTL

SUPPORTED = ["USD", "EUR", "GBP", "INR", "CAD", "AUD", "JPY", "SGD", "CHF", "MXN", "BRL", "ZAR"]


async def to_usd(
    amount: float, currency: str, slog: SourceLog | None = None
) -> dict[str, Any]:
    """Convert an amount to USD. Falls back to treating it as USD if the
    rate source is unreachable, and says so."""
    currency = (currency or "USD").upper()
    if currency == "USD":
        return {"usd": round(amount, 2), "rate": 1.0, "currency": "USD", "converted": False}

    data = await fetch_json(
        "frankfurter",
        ENDPOINTS["frankfurter"],
        params={"base": currency, "symbols": "USD"},
        ttl=TTL["frankfurter"],
        slog=slog,
    )
    rate = ((data or {}).get("rates") or {}).get("USD")
    if not rate:
        return {
            "usd": round(amount, 2),
            "rate": None,
            "currency": currency,
            "converted": False,
            "warning": f"Could not fetch a {currency} to USD rate. The figure was used as-is.",
        }

    return {
        "usd": round(amount * float(rate), 2),
        "rate": float(rate),
        "currency": currency,
        "converted": True,
        "as_of": (data or {}).get("date"),
    }
