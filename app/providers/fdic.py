"""Real FDIC-insured institutions and branch locations, via FDIC BankFind.

This is the backbone of the 'which banks' answer. Everything returned here is
a genuine, currently insured institution reported by a US government API - not
a curated list maintained by this project.
"""

from __future__ import annotations

import re
from typing import Any

from app.cache import SourceLog, fetch_json
from app.config import ENDPOINTS, TTL

# NAMEHCR is the holding-company name. Many banks file with the CFPB under
# the parent rather than the charter, and the two names can share no words
# at all, so it is fetched as a fallback for name resolution.
INSTITUTION_FIELDS = "NAME,CITY,STALP,ASSET,OFFDOM,CERT,WEBADDR,ESTYMD,BKCLASS,REPDTE,NAMEHCR"
LOCATION_FIELDS = "NAME,ADDRESS,CITY,STALP,ZIP,CERT,SERVTYPE_DESC"


def _unwrap(payload: Any) -> list[dict[str, Any]]:
    """FDIC wraps every row as {'data': {...}, 'score': n}. Flatten it."""
    if not payload or not isinstance(payload, dict):
        return []
    return [row.get("data", {}) for row in payload.get("data", []) if isinstance(row, dict)]


async def institutions_in_state(
    state_abbr: str, limit: int = 60, slog: SourceLog | None = None
) -> list[dict[str, Any]] | None:
    """Active institutions headquartered in a state, largest first.

    Returns None when FDIC was unreachable, and [] when it answered with no
    institutions. Collapsing both into [] would let an outage render as
    "there are no banks in your state", which is a confident falsehood.
    """
    if not state_abbr:
        return []

    payload = await fetch_json(
        "fdic_institutions",
        ENDPOINTS["fdic_institutions"],
        params={
            "filters": f"STALP:{state_abbr} AND ACTIVE:1",
            "fields": INSTITUTION_FIELDS,
            "sort_by": "ASSET",
            "sort_order": "DESC",
            "limit": limit,
            "format": "json",
        },
        ttl=TTL["fdic_institutions"],
        slog=slog,
    )
    if payload is None:
        return None
    return [_norm_institution(r) for r in _unwrap(payload)]


async def institutions_by_cert(
    certs: list[str], slog: SourceLog | None = None
) -> dict[str, dict[str, Any]]:
    """Look up institutions by FDIC certificate number, keyed by cert."""
    certs = [c for c in {str(c) for c in certs} if c]
    if not certs:
        return {}

    payload = await fetch_json(
        "fdic_institutions",
        ENDPOINTS["fdic_institutions"],
        params={
            "filters": "CERT:(" + " OR ".join(certs) + ")",
            "fields": INSTITUTION_FIELDS,
            "limit": len(certs),
            "format": "json",
        },
        ttl=TTL["fdic_institutions"],
        slog=slog,
    )
    out: dict[str, dict[str, Any]] = {}
    for row in _unwrap(payload):
        inst = _norm_institution(row)
        if inst["cert"]:
            out[inst["cert"]] = inst
    return out


async def branches_in_zip(
    zip_code: str, limit: int = 40, slog: SourceLog | None = None
) -> list[dict[str, Any]] | None:
    """Physical branches with an address inside the given ZIP.

    Returns None when FDIC was unreachable, [] when the ZIP genuinely has none.
    """
    if not zip_code:
        return []

    payload = await fetch_json(
        "fdic_locations",
        ENDPOINTS["fdic_locations"],
        params={
            "filters": f"ZIP:{zip_code}",
            "fields": LOCATION_FIELDS,
            "limit": limit,
            "format": "json",
        },
        ttl=TTL["fdic_locations"],
        slog=slog,
    )
    if payload is None:
        return None
    return [
        {
            "cert": str(r.get("CERT") or ""),
            "name": r.get("NAME"),
            "address": r.get("ADDRESS"),
            "city": r.get("CITY"),
            "state_abbr": r.get("STALP"),
            "zip": r.get("ZIP"),
            "service_type": (r.get("SERVTYPE_DESC") or "").title(),
        }
        for r in _unwrap(payload)
    ]


def _norm_institution(row: dict[str, Any]) -> dict[str, Any]:
    # ASSET is reported in thousands of dollars.
    assets_k = row.get("ASSET") or 0
    website = (row.get("WEBADDR") or "").strip()
    if website and not website.lower().startswith("http"):
        website = "https://" + website

    # FDIC records carry doubled spaces in some names, as in "Frost  Bank".
    def tidy(value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").strip())

    holding = tidy(row.get("NAMEHCR"))

    return {
        "cert": str(row.get("CERT") or ""),
        "name": tidy(row.get("NAME")),
        "holding_company": holding or None,
        "city": tidy(row.get("CITY")),
        "state_abbr": row.get("STALP"),
        "assets_usd": int(assets_k) * 1000 if assets_k else 0,
        "domestic_offices": row.get("OFFDOM") or 0,
        "website": website or None,
        "established": row.get("ESTYMD"),
        "charter_class": row.get("BKCLASS"),
        "as_of": row.get("REPDTE"),
    }
