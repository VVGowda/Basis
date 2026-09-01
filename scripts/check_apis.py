"""Health check for every upstream public API.

Run this when something looks wrong, or before demoing. It hits each provider
once with a known-good input and reports what came back. Free public endpoints
go down and change shape without notice, and this is how you find out which one
did rather than guessing from a blank panel.

    venv\\Scripts\\python.exe scripts\\check_apis.py
"""

import asyncio
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.cache import SourceLog, close_client
from app.providers import cfpb, fdic, fx, geo, holidays, india, rates

OK, BAD = "  ok  ", " FAIL "


def line(name: str, ok: bool, detail: str) -> None:
    print(f"[{OK if ok else BAD}] {name:<34} {detail}")


async def main() -> int:
    slog = SourceLog()
    failures = 0

    def check(name, ok, detail):
        nonlocal failures
        if not ok:
            failures += 1
        line(name, ok, detail)

    print("\nBasis upstream check\n" + "-" * 74)

    place = await geo.lookup_zip("21201", slog)
    check(
        "Zippopotam.us",
        bool(place and place.get("state_abbr")),
        f"21201 -> {place['city']}, {place['state_abbr']}" if place else "no response",
    )

    banks = await fdic.institutions_in_state("MD", limit=5, slog=slog)
    check(
        "FDIC BankFind, institutions",
        bool(banks),
        f"{len(banks)} MD banks, largest is {banks[0]['name']}" if banks else "no response",
    )

    branches = await fdic.branches_in_zip("21201", slog=slog)
    check(
        "FDIC BankFind, locations",
        bool(branches),
        f"{len(branches)} branches in 21201" if branches else "no response",
    )

    profile = await cfpb.complaint_profile("Bank of America, National Association", "home_purchase", slog=slog)
    # A large national bank must resolve and must have a non-zero record. If it
    # comes back unmatched or zero, name resolution has broken again.
    check(
        "CFPB complaint database",
        bool(profile and profile.get("matched") and profile.get("complaints")),
        (
            f"matched {profile['company_matched']}, {profile['complaints']:,} mortgage complaints"
            if profile and profile.get("matched") and profile.get("complaints")
            else f"name resolution failed: {profile}" if profile else "no response"
        ),
    )

    bench = await rates.us_benchmark(slog)
    check(
        "Treasury Fiscal Data",
        not bench["estimated"],
        f"{bench['rate']}% as of {bench['as_of']}" if not bench["estimated"] else "fell back to assumption",
    )

    world = await rates.country_benchmark("IN", slog)
    check(
        "World Bank indicators",
        not world["estimated"],
        f"India lending rate {world['rate']}% ({world['as_of']})" if not world["estimated"] else "no reported value",
    )

    conv = await fx.to_usd(100_000, "INR", slog)
    check(
        "Frankfurter FX",
        conv.get("converted", False),
        f"100,000 INR -> ${conv['usd']:,.2f}" if conv.get("converted") else "conversion unavailable",
    )

    fund = await holidays.add_business_days(date.today(), 30, "US", slog)
    check(
        "Nager.Date holidays",
        fund["holiday_data_available"],
        f"30 business days from today lands on {fund['date']}",
    )

    branch = await india.lookup_ifsc("HDFC0000001", slog)
    check(
        "Razorpay IFSC",
        branch is not None,
        f"{branch['bank']}, {branch['city']}" if branch else "no response",
    )

    print("-" * 74)
    print(f"{9 - failures} of 9 upstreams healthy\n")

    await close_client()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
