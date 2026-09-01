"""Failure tests: the site must still answer when the internet does not.

Nine live public APIs feed one page. Free endpoints go down without notice, and
the CFPB has already returned a 503 during this project's development. The
question these tests answer is not "does it work" but "what does a user see
when a source is dead".

Every case here points real providers at unreachable hosts, so nothing is
mocked at the function level and the whole path including the HTTP client and
the cache is exercised.
"""

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config
from app.cache import close_client
from app.models import MatchRequest
from app.routers.match import match

# A port nothing listens on, on a host that resolves instantly.
DEAD = "http://127.0.0.1:9"

LIVE_ENDPOINTS = dict(config.ENDPOINTS)


def kill(*keys: str) -> None:
    """Point named upstreams at a socket that refuses connections."""
    for key in keys:
        config.ENDPOINTS[key] = DEAD


def revive() -> None:
    config.ENDPOINTS.clear()
    config.ENDPOINTS.update(LIVE_ENDPOINTS)


def request(**over):
    body = {
        "purpose": "home_purchase",
        "annual_income": 95000,
        "monthly_debt": 450,
        "credit_score": 712,
        "loan_amount": 340000,
        "down_payment": 60000,
        "asset_value": 400000,
        "zip_code": "21201",
    }
    body.update(over)
    return MatchRequest(**body)


def run(req):
    """Run one request on a fresh event loop.

    The HTTP client is shared and bound to the loop that created it, so it has
    to be closed between runs or later tests fail with "Event loop is closed"
    and appear to be testing something they are not.
    """
    async def go():
        try:
            return await match(req)
        finally:
            await close_client()

    return asyncio.run(go())


def isolate_cache():
    """Point the cache at an empty temp directory.

    Without this a killed upstream is quietly served from a previous run's
    cache and the test proves nothing.
    """
    tmp = Path(tempfile.mkdtemp(prefix="basis-test-"))
    original = config.CACHE_DIR
    config.CACHE_DIR = tmp

    import app.cache as cache_module
    cache_module.CACHE_DIR = tmp
    return tmp, original


def restore_cache(tmp, original):
    import app.cache as cache_module
    config.CACHE_DIR = original
    cache_module.CACHE_DIR = original
    shutil.rmtree(tmp, ignore_errors=True)


def with_dead(keys, assertion):
    tmp, original = isolate_cache()
    kill(*keys)
    try:
        assertion(run(request()))
    finally:
        revive()
        restore_cache(tmp, original)


# --------------------------------------------------------------------------

def test_everything_down_still_returns_a_usable_answer():
    def check(result):
        # The rule engine is pure and must survive a total outage.
        assert result["eligibility"]["programs"], "no programs returned"
        assert result["disclaimer"]
        assert result["lenders"]["lenders"] == []
        assert result["lenders"].get("degraded") is True
        for program in result["eligibility"]["programs"]:
            assert program["verdict"] in ("likely_eligible", "possible", "not_eligible")

    with_dead(list(LIVE_ENDPOINTS.keys()), check)


def test_fdic_down_says_unavailable_not_none_found():
    def check(result):
        note = result["lenders"].get("note", "")
        assert result["lenders"].get("degraded") is True
        assert "unavailable" in note.lower() or "could not be loaded" in note.lower()
        # The claim "there are no banks in your state" would be a falsehood.
        assert "no active insured institutions" not in note.lower()
        # Programs are unaffected by a lender-data outage and must still show.
        assert result["eligibility"]["eligible_count"] >= 0
        assert result["eligibility"]["programs"]

    with_dead(["fdic_institutions", "fdic_locations"], check)


def test_rate_source_down_falls_back_and_flags_the_estimate():
    def check(result):
        assert result["benchmark"]["estimated"] is True
        assert result["benchmark"]["rate"] > 0
        # Payments must still compute on the fallback rate.
        assert result["eligibility"]["programs"][0]["estimate"]["total_monthly"] > 0

    with_dead(["treasury"], check)


def test_zip_lookup_down_degrades_to_no_lenders_but_keeps_programs():
    def check(result):
        assert result["location"] is None
        assert result["lenders"]["lenders"] == []
        assert result["lenders"].get("note")
        assert result["eligibility"]["programs"]

    with_dead(["zippopotam"], check)


def test_cfpb_down_keeps_lenders_without_inventing_a_clean_record():
    def check(result):
        lenders = result["lenders"]["lenders"]
        assert lenders, "lenders should still be listed without CFPB"
        for lender in lenders:
            profile = lender.get("complaints")
            # Never a fabricated zero.
            if profile is not None:
                assert profile.get("complaints") is None or profile.get("matched") is not True
            assert lender.get("complaint_rate") is None

    with_dead(["cfpb", "cfpb_suggest"], check)


def test_holiday_source_down_does_not_break_the_response():
    def check(result):
        funding = result["funding_estimate"]
        # Either a date computed without holiday data, or nothing at all.
        if funding:
            assert funding["holiday_data_available"] is False
            assert funding["date"]

    with_dead(["nager"], check)


def test_currency_source_down_uses_amounts_as_entered_and_warns():
    tmp, original = isolate_cache()
    kill("frankfurter")
    try:
        result = run(request(income_currency="INR", annual_income=2_400_000))
        conversion = result["applicant"]["currency_conversion"]
        assert conversion["converted"] is False
        assert conversion.get("warning"), "a silent non-conversion is the dangerous case"
        # The unconverted figure must be used as-is rather than scaled by a guess.
        assert result["applicant"]["annual_income_usd"] == 2_400_000
    finally:
        revive()
        restore_cache(tmp, original)


def test_every_source_can_die_alone_without_a_crash():
    for key in LIVE_ENDPOINTS:
        with_dead([key], lambda result: (
            assert_programs(result), assert_shape(result)
        ))


def assert_programs(result):
    assert result["eligibility"]["programs"], "programs missing"


def assert_shape(result):
    for field in ("applicant", "benchmark", "eligibility", "lenders", "sources_used", "disclaimer"):
        assert field in result, f"{field} missing from response"


if __name__ == "__main__":
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            passed += 1
            print(f"  ok   {name}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL   {name}  {exc}")
        except Exception as exc:
            failed += 1
            print(f"ERROR  {name}  {type(exc).__name__}: {exc}")
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
