"""Indian bank branch lookup by IFSC code, via the Razorpay IFSC API.

India mode is deliberately narrower than US mode: there is no free equivalent
of FDIC BankFind for Indian institutions, so the site verifies a branch the
user names rather than pretending to enumerate every lender that might serve them.
"""

from __future__ import annotations

import re
from typing import Any

from app.cache import SourceLog, fetch_json
from app.config import ENDPOINTS, TTL

IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


async def lookup_ifsc(code: str, slog: SourceLog | None = None) -> dict[str, Any] | None:
    code = (code or "").strip().upper()
    if not IFSC_RE.match(code):
        return None

    data = await fetch_json(
        "ifsc", f"{ENDPOINTS['ifsc']}/{code}", ttl=TTL["ifsc"], slog=slog
    )
    if not isinstance(data, dict) or not data.get("BANK"):
        return None

    return {
        "ifsc": data.get("IFSC"),
        "bank": data.get("BANK"),
        "branch": (data.get("BRANCH") or "").title(),
        "city": (data.get("CITY") or "").title(),
        "district": (data.get("DISTRICT") or "").title(),
        "state": (data.get("STATE") or "").title(),
        "address": (data.get("ADDRESS") or "").title(),
        "swift": data.get("SWIFT"),
        "supports": [k for k in ("NEFT", "RTGS", "IMPS", "UPI") if data.get(k)],
    }
