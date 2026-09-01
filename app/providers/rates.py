"""Benchmark interest rates.

US pricing is anchored to the Treasury's own reported average interest rates;
everything else falls back to the World Bank's commercial lending rate for
that country. Both are published government or multilateral figures, so the
APR shown to a user is built on a real number rather than an invented one.
"""

from __future__ import annotations

from typing import Any

from app.cache import SourceLog, fetch_json
from app.config import ENDPOINTS, TTL

# Long-run fallback used only when both upstreams are unreachable, so the
# calculator still returns something. Flagged as an assumption in the response.
FALLBACK_BENCHMARK = 4.0


async def us_benchmark(slog: SourceLog | None = None) -> dict[str, Any]:
    """Average interest rate on marketable Treasury Notes, most recent month."""
    data = await fetch_json(
        "treasury",
        ENDPOINTS["treasury"],
        params={
            "sort": "-record_date",
            "page[size]": 40,
            "format": "json",
            "filter": "security_desc:eq:Treasury Notes",
        },
        ttl=TTL["treasury"],
        slog=slog,
    )
    rows = (data or {}).get("data") or []
    for row in rows:
        try:
            rate = float(row["avg_interest_rate_amt"])
        except (KeyError, TypeError, ValueError):
            continue
        return {
            "rate": rate,
            "label": "US Treasury Notes, average interest rate",
            "as_of": row.get("record_date"),
            "source": "US Treasury Fiscal Data",
            "estimated": False,
        }

    return {
        "rate": FALLBACK_BENCHMARK,
        "label": "Assumed benchmark (Treasury source unreachable)",
        "as_of": None,
        "source": "fallback assumption",
        "estimated": True,
    }


async def country_benchmark(iso2: str, slog: SourceLog | None = None) -> dict[str, Any]:
    """Most recent non-null commercial lending rate for a country."""
    data = await fetch_json(
        "worldbank",
        f"{ENDPOINTS['worldbank']}/country/{iso2}/indicator/FR.INR.LEND",
        params={"format": "json", "per_page": 30, "date": "2010:2026"},
        ttl=TTL["worldbank"],
        slog=slog,
    )
    rows = data[1] if isinstance(data, list) and len(data) > 1 and data[1] else []
    for row in rows:
        if row.get("value") is not None:
            return {
                "rate": round(float(row["value"]), 2),
                "label": f"Average commercial lending rate, {row.get('country', {}).get('value', iso2)}",
                "as_of": row.get("date"),
                "source": "World Bank indicator FR.INR.LEND",
                "estimated": False,
            }

    return {
        "rate": FALLBACK_BENCHMARK,
        "label": "Assumed benchmark (no reported lending rate for this country)",
        "as_of": None,
        "source": "fallback assumption",
        "estimated": True,
    }
