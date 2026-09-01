"""Standalone lookup endpoints.

These are useful on their own and they double as a live demonstration that each
public API is actually wired in rather than being a claim in a README.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.cache import SourceLog, fetch_json, metrics_snapshot
from app.config import ENDPOINTS, SOURCES, TTL
from app.engine import eligibility
from app.providers import cfpb, fdic, fx, geo, india, rates

router = APIRouter(prefix="/api", tags=["lookup"])


@router.get("/zip/{zip_code}")
async def zip_lookup(zip_code: str) -> dict[str, Any]:
    """ZIP code to city, state and coordinates. Source: Zippopotam.us."""
    slog = SourceLog()
    place = await geo.lookup_zip(zip_code, slog)
    if not place:
        raise HTTPException(404, f"No US place found for ZIP {zip_code}.")
    return {"place": place, "sources_used": slog.as_list()}


@router.get("/banks/{state_abbr}")
async def banks_in_state(
    state_abbr: str, limit: int = Query(default=25, ge=1, le=100)
) -> dict[str, Any]:
    """Active FDIC-insured institutions chartered in a state, largest first."""
    slog = SourceLog()
    banks = await fdic.institutions_in_state(state_abbr.upper(), limit=limit, slog=slog)
    return {
        "state": state_abbr.upper(),
        "count": len(banks),
        "banks": banks,
        "sources_used": slog.as_list(),
    }


@router.get("/branches/{zip_code}")
async def branches(zip_code: str) -> dict[str, Any]:
    """Real bank branch addresses inside a ZIP code. Source: FDIC BankFind."""
    slog = SourceLog()
    found = await fdic.branches_in_zip(zip_code, slog=slog)
    return {"zip": zip_code, "count": len(found), "branches": found, "sources_used": slog.as_list()}


@router.get("/complaints")
async def complaints(
    company: str = Query(description="Institution name, as reported to the CFPB."),
    purpose: str = Query(default="home_purchase"),
) -> dict[str, Any]:
    """Consumer complaint record for one institution. Source: CFPB."""
    slog = SourceLog()
    profile = await cfpb.complaint_profile(company, purpose, slog=slog)
    if profile is None:
        raise HTTPException(503, "The CFPB complaint database did not respond.")
    return {"profile": profile, "sources_used": slog.as_list()}


@router.get("/rates")
async def benchmark_rates(country: str = Query(default="US")) -> dict[str, Any]:
    """The benchmark rate used to model pricing."""
    slog = SourceLog()
    country = country.upper()
    data = (
        await rates.us_benchmark(slog)
        if country == "US"
        else await rates.country_benchmark(country, slog)
    )
    return {"benchmark": data, "sources_used": slog.as_list()}


@router.get("/convert")
async def convert(
    amount: float = Query(gt=0), currency: str = Query(default="INR")
) -> dict[str, Any]:
    """Convert an amount to USD. Source: Frankfurter / ECB reference rates."""
    slog = SourceLog()
    result = await fx.to_usd(amount, currency.upper(), slog)
    return {"conversion": result, "sources_used": slog.as_list()}


@router.get("/ifsc/{code}")
async def ifsc(code: str) -> dict[str, Any]:
    """Indian bank branch lookup by IFSC code. Source: Razorpay IFSC."""
    slog = SourceLog()
    branch = await india.lookup_ifsc(code, slog)
    if not branch:
        raise HTTPException(404, f"No Indian branch found for IFSC {code.upper()}.")
    return {"branch": branch, "sources_used": slog.as_list()}


@router.get("/programs")
async def programs() -> dict[str, Any]:
    """Every loan program in the catalog, with the authority behind each one."""
    return {
        "purposes": eligibility.all_purposes(),
        "programs": eligibility.catalog(),
    }


@router.get("/stats")
async def stats() -> dict[str, Any]:
    """Headline counts for the landing page, read live rather than hardcoded.

    A number typed into the HTML is correct on the day it is written and
    quietly wrong forever after.
    """
    slog = SourceLog()
    payload = await fetch_json(
        "fdic_institutions",
        ENDPOINTS["fdic_institutions"],
        params={"filters": "ACTIVE:1", "fields": "NAME", "limit": 1, "format": "json"},
        ttl=TTL["fdic_institutions"],
        slog=slog,
    )
    total = ((payload or {}).get("meta") or {}).get("total")
    return {
        "active_fdic_institutions": total,
        "loan_programs": len(eligibility.catalog()),
        "public_apis": len(SOURCES),
        "sources_used": slog.as_list(),
    }


@router.get("/metrics")
async def metrics() -> dict[str, Any]:
    """Upstream health and CFPB match rate since this process started.

    Contains no applicant data of any kind. The CFPB match rate is the number
    worth watching: if it falls, name matching has regressed and banks are
    silently losing their complaint records.
    """
    return metrics_snapshot()


@router.get("/sources")
async def sources() -> dict[str, Any]:
    """Every public API this site is built on."""
    return {"count": len(SOURCES), "sources": SOURCES}
