"""The main endpoint: applicant in, eligible programs plus real lenders out."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter

from app.cache import METRICS, SourceLog, gather_safe
from app.engine import eligibility, lenders as lender_engine
from app.models import MatchRequest, MatchResponse
from app.providers import fx, geo, holidays, rates

router = APIRouter(prefix="/api", tags=["match"])

DISCLAIMER = (
    "This is an estimate built from public data, not a credit decision and not an offer of credit. "
    "No credit bureau was contacted and no credit check of any kind was performed - the score used is "
    "the one you typed in. Program thresholds are published federal and GSE standards, but individual "
    "lenders add their own overlays. Rates shown are modelled from a Treasury benchmark, not quoted. "
    "Only a lender can tell you what you actually qualify for."
)

# How long each loan type typically takes to fund, in business days.
FUNDING_DAYS = {
    "home_purchase": 30,
    "home_refinance": 30,
    "auto": 3,
    "personal": 5,
    "small_business": 45,
}


@router.post("/match", response_model=MatchResponse)
async def match(req: MatchRequest) -> dict[str, Any]:
    slog = SourceLog()

    # Location and the rate benchmark are independent, so fetch them together.
    location_task = geo.lookup_zip(req.zip_code, slog) if req.zip_code else _none()
    income_task = fx.to_usd(req.annual_income, req.income_currency, slog)
    benchmark_task = rates.us_benchmark(slog)

    METRICS["match_requests"] += 1

    location, income, benchmark = await gather_safe(
        location_task, income_task, benchmark_task,
        labels=["geo.lookup_zip", "fx.to_usd", "rates.us_benchmark"],
    )

    # gather_safe converts a raising provider into None, so the two results the
    # rest of this function cannot do without need a floor.
    if income is None:
        income = {
            "usd": req.annual_income, "rate": None, "currency": req.income_currency,
            "converted": False,
            "warning": "Currency conversion was unavailable. Amounts were used as entered.",
        }
    if benchmark is None:
        benchmark = {
            "rate": rates.FALLBACK_BENCHMARK,
            "label": "Assumed benchmark (rate source unavailable)",
            "as_of": None, "source": "fallback assumption", "estimated": True,
        }

    # The chosen currency governs every money field on the form, not just
    # income. Converting income alone but leaving existing debt in its original
    # units silently compares rupees against dollars and produces a wildly
    # wrong debt-to-income ratio, which then reads as a confident rejection.
    rate = income.get("rate") or 1.0

    def to_usd(amount: float) -> float:
        return round(amount * rate, 2)

    annual_usd = income["usd"]
    monthly_income = round(annual_usd / 12, 2)
    monthly_debt = to_usd(req.monthly_debt)
    loan_amount = to_usd(req.loan_amount)
    down_payment = to_usd(req.down_payment)
    asset_value = (
        to_usd(req.asset_value) if req.asset_value else (loan_amount + down_payment)
    )

    applicant = {
        "purpose": req.purpose,
        "credit_score": req.credit_score,
        "credit_band": eligibility.credit_band(req.credit_score),
        "annual_income_usd": annual_usd,
        "monthly_income_usd": monthly_income,
        "monthly_debt_usd": monthly_debt,
        "loan_amount_usd": loan_amount,
        "down_payment_usd": down_payment,
        "asset_value_usd": asset_value,
        "term_months": req.term_months,
        "military_service": req.military_service,
        "rural_property": req.rural_property,
        "business_operating": req.business_operating,
        "currency_conversion": income,
    }

    result = eligibility.evaluate(applicant, benchmark["rate"])

    eligible_ids = [
        p["program_id"] for p in result["programs"] if p["verdict"] != eligibility.NOT_ELIGIBLE
    ]

    # Lender matching and the funding date estimate are independent too.
    if location and location.get("state_abbr"):
        lender_task = lender_engine.match_lenders(
            location["state_abbr"], location["zip"], req.purpose, eligible_ids, slog=slog
        )
    elif req.zip_code:
        # A ZIP was given but could not be resolved. Telling this user to add a
        # ZIP code would be nonsense, and blaming their input for an outage is
        # worse than admitting the outage.
        lender_task = _lookup_unavailable()
    else:
        lender_task = _no_zip_given()

    funding_task = (
        holidays.add_business_days(date.today(), FUNDING_DAYS[req.purpose], "US", slog)
        if eligible_ids
        else _none()
    )

    lender_result, funding = await gather_safe(
        lender_task, funding_task, labels=["lenders.match_lenders", "holidays.add_business_days"]
    )

    if lender_result is None:
        lender_result = {
            "lenders": [],
            "degraded": True,
            "note": "Bank data could not be loaded for this request. Your loan program results above are unaffected.",
        }

    if funding:
        funding["typical_business_days"] = FUNDING_DAYS[req.purpose]
        funding["note"] = (
            "Counted in business days, skipping weekends and US bank holidays. "
            "Typical timeline for this loan type, not a commitment."
        )

    return {
        "applicant": applicant,
        "location": location,
        "benchmark": benchmark,
        "eligibility": result,
        "lenders": lender_result,
        "funding_estimate": funding,
        "sources_used": slog.as_list(),
        "disclaimer": DISCLAIMER,
    }


async def _none() -> None:
    return None


async def _no_zip_given() -> dict[str, Any]:
    return {
        "lenders": [],
        "degraded": False,
        "note": "Add a US ZIP code to see the real FDIC-insured banks that serve your area.",
    }


async def _lookup_unavailable() -> dict[str, Any]:
    return {
        "lenders": [],
        "degraded": True,
        "note": (
            "Your ZIP code could not be looked up, so nearby banks are temporarily "
            "unavailable. Your loan program results above are unaffected."
        ),
    }
