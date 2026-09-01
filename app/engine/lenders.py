"""Matching real institutions to an applicant.

An honest statement of what this can and cannot do:

FDIC BankFind tells us which banks exist, where they are chartered, how large
they are, and where their branches sit. The CFPB tells us how many people
complained about them and how often they answered on time. Neither source
publishes which loan programs a bank originates or what its credit overlays
are - no free API does.

So this module does not claim to know who will approve you. It ranks the real
institutions that actually serve your area by the signals that are genuinely
observable, and pairs them with the programs the engine says you qualify for.
The output is a call list, not a decision.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.cache import SourceLog, gather_safe, record_cfpb_resolution
from app.providers import cfpb, fdic

# Asset thresholds, in dollars, used to describe a lender's scale. Larger banks
# run more loan programs; small community banks and thrifts often do not offer
# jumbo or SBA lending at all.
LARGE_BANK = 50_000_000_000
MID_BANK = 10_000_000_000
COMMUNITY_BANK = 1_000_000_000

# Programs that generally need a lender of a certain size to be on the menu.
PROGRAM_SCALE_HINT = {
    "jumbo": MID_BANK,
    "sba_7a": COMMUNITY_BANK,
    "usda": COMMUNITY_BANK,
}


def scale_label(assets: int) -> str:
    if assets >= LARGE_BANK:
        return "National"
    if assets >= MID_BANK:
        return "Regional"
    if assets >= COMMUNITY_BANK:
        return "Community"
    return "Local"


async def match_lenders(
    state_abbr: str,
    zip_code: str | None,
    purpose: str,
    eligible_program_ids: list[str],
    limit: int = 12,
    slog: SourceLog | None = None,
) -> dict[str, Any]:
    """Build a ranked list of real institutions serving the applicant's area."""

    state_task = fdic.institutions_in_state(state_abbr, limit=60, slog=slog)
    branch_task = (
        fdic.branches_in_zip(zip_code, limit=60, slog=slog)
        if zip_code
        else _empty_list()
    )
    state_banks, branches = await gather_safe(
        state_task, branch_task, labels=["fdic.institutions_in_state", "fdic.branches_in_zip"]
    )

    # None means the upstream failed; [] means it answered with nothing. The
    # difference decides whether the page says "temporarily unavailable" or
    # "none found", and those are very different claims.
    fdic_down = state_banks is None and branches is None
    state_banks = state_banks or []
    branches = branches or []

    if fdic_down:
        return {
            "lenders": [],
            "degraded": True,
            "note": (
                "Bank data is temporarily unavailable. The FDIC institution "
                "directory did not respond, so no lenders can be listed right now. "
                "Your loan program results above are unaffected."
            ),
        }

    # Branches in the ZIP may belong to banks chartered in another state, which
    # is exactly how national lenders show up. Pull those institutions in too.
    by_cert: dict[str, dict[str, Any]] = {b["cert"]: b for b in state_banks if b["cert"]}
    branch_certs = {b["cert"] for b in branches if b["cert"]}
    missing = [c for c in branch_certs if c not in by_cert]
    if missing:
        extra = await fdic.institutions_by_cert(missing[:40], slog=slog)
        by_cert.update(extra)

    branch_count: dict[str, int] = {}
    branch_sample: dict[str, dict[str, Any]] = {}
    for b in branches:
        if not b["cert"]:
            continue
        branch_count[b["cert"]] = branch_count.get(b["cert"], 0) + 1
        branch_sample.setdefault(b["cert"], b)

    candidates = list(by_cert.values())
    if not candidates:
        return {
            "lenders": [],
            "degraded": False,
            "note": f"FDIC returned no active insured institutions for {state_abbr}.",
        }

    # Score before fetching complaint data, so the expensive lookup only runs
    # for the lenders that will actually be shown.
    scored = sorted(
        candidates,
        key=lambda inst: _base_score(inst, branch_count.get(inst["cert"], 0)),
        reverse=True,
    )[:limit]

    # The holding-company name is offered as a fallback because many banks file
    # with the CFPB under the parent rather than the charter.
    profiles = await gather_safe(
        *[
            cfpb.complaint_profile(
                inst["name"],
                purpose,
                alt_names=[inst.get("holding_company")],
                slog=slog,
            )
            for inst in scored
        ],
        labels=[f"cfpb.complaint_profile({i['name']})" for i in scored],
    )

    lenders = []
    for inst, profile in zip(scored, profiles):
        local_branches = branch_count.get(inst["cert"], 0)
        lenders.append(
            {
                "cert": inst["cert"],
                "name": inst["name"],
                "city": inst["city"],
                "state_abbr": inst["state_abbr"],
                "website": inst["website"],
                "assets_usd": inst["assets_usd"],
                "scale": scale_label(inst["assets_usd"]),
                "domestic_offices": inst["domestic_offices"],
                "branches_in_zip": local_branches,
                "nearest_branch": branch_sample.get(inst["cert"]),
                "as_of": inst["as_of"],
                "complaints": profile,
                "complaint_rate": _complaint_rate(profile, inst["assets_usd"]),
                "likely_programs": _likely_programs(inst, eligible_program_ids),
                "why": _why(inst, local_branches, profile),
            }
        )

    # Final ordering puts genuinely nearby lenders first, then service record.
    lenders.sort(key=lambda x: _rank_key(x), reverse=True)

    # Watching this rate is how a future name-matching regression gets noticed
    # before a user does.
    resolved = sum(1 for x in lenders if (x.get("complaints") or {}).get("matched"))
    record_cfpb_resolution(len(lenders), resolved)

    return {
        "lenders": lenders,
        "degraded": False,
        "state_institutions_found": len(state_banks),
        "branches_found_in_zip": len(branches),
        "cfpb_matched": resolved,
    }


async def _empty_list() -> list:
    return []


def _base_score(inst: dict[str, Any], local_branches: int) -> float:
    score = 0.0
    score += min(local_branches, 5) * 20
    score += min(inst.get("domestic_offices") or 0, 300) * 0.05
    # Log-ish scaling so a trillion-dollar bank does not swamp everything.
    assets = inst.get("assets_usd") or 0
    score += (assets ** 0.28) / 1000 if assets > 0 else 0
    return score


def _complaint_rate(profile: dict[str, Any] | None, assets: int) -> dict[str, Any] | None:
    """Complaints per billion dollars of assets.

    A raw complaint count punishes big banks purely for being big. Normalising
    by size makes the number comparable across a national bank and a community
    one. It is still a rough proxy: assets are not customers.

    Returns None when the institution could not be matched in the CFPB
    database. That is not the same as a clean record and must not be shown
    as one.
    """
    if not profile or not profile.get("matched") or profile.get("complaints") is None:
        return None
    if assets <= 0:
        return None
    billions = assets / 1_000_000_000
    return {
        "per_billion_assets": round(profile["complaints"] / billions, 1),
        "basis": "complaints since 2023 per $1B in assets",
    }


def _likely_programs(inst: dict[str, Any], eligible_program_ids: list[str]) -> dict[str, Any]:
    """Split the applicant's eligible programs into ones this lender plausibly
    offers and ones worth asking about. This is inference from institution
    size, not published product data, and is labelled that way in the UI."""
    assets = inst.get("assets_usd") or 0
    likely, ask = [], []
    for pid in eligible_program_ids:
        needed = PROGRAM_SCALE_HINT.get(pid)
        if needed is None or assets >= needed:
            likely.append(pid)
        else:
            ask.append(pid)
    return {
        "likely": likely,
        "ask_about": ask,
        "basis": "Inferred from institution size. FDIC does not publish which loan programs a bank originates.",
    }


def _why(inst: dict[str, Any], local_branches: int, profile: dict[str, Any] | None) -> list[str]:
    reasons = []
    if local_branches:
        plural = "branch" if local_branches == 1 else "branches"
        reasons.append(f"{local_branches} {plural} in your ZIP code")
    elif inst.get("state_abbr"):
        reasons.append(f"Chartered in {inst['state_abbr']}")

    reasons.append(f"{scale_label(inst['assets_usd'])} institution, ${inst['assets_usd'] / 1e9:,.1f}B in assets")

    if profile is None:
        reasons.append("CFPB complaint database was unavailable")
    elif not profile.get("matched"):
        # Absent from the database is not the same as having a clean record,
        # and saying so would be a flattering guess rather than a finding.
        # The institution may also simply be filed under a brand name.
        reasons.append("No CFPB record matched this legal name")
    elif profile["complaints"] == 0:
        reasons.append("No CFPB complaints on file since 2023")
    elif profile.get("timely_response_rate") is not None:
        pct = round(profile["timely_response_rate"] * 100, 1)
        reasons.append(
            f"{profile['complaints']:,} CFPB complaints since 2023, {pct} percent answered on time"
        )
    else:
        reasons.append(f"{profile['complaints']:,} CFPB complaints since 2023")

    return reasons


def _rank_key(lender: dict[str, Any]) -> tuple:
    """Sort key, best last. Proximity dominates, then service record.

    An institution with no CFPB record scores neutral rather than good or bad,
    so a small community bank is neither punished for being absent from a
    complaint database nor credited with a spotless history it never earned.
    """
    profile = lender.get("complaints") or {}
    rate = lender.get("complaint_rate")

    if not profile.get("matched"):
        service = 0.5
    else:
        timely = profile.get("timely_response_rate")
        timely_part = timely if timely is not None else 0.95
        # Fewer complaints per billion in assets is better. Capped so one
        # outlier cannot dominate the ordering.
        per_billion = rate["per_billion_assets"] if rate else 0.0
        service = round(timely_part - min(per_billion / 200.0, 0.5), 3)

    return (min(lender["branches_in_zip"], 3), service, lender["assets_usd"])
