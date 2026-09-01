"""Tests for the parts that decide things.

Deliberately scoped to the pure logic: amortization, ratios, and the rule
engine. The provider modules talk to live public APIs, so they are exercised by
scripts/check_apis.py rather than being asserted against here - a test suite
that fails because someone else's free endpoint is down is a test suite people
learn to ignore.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine import affordability as af
from app.engine import eligibility as el
from app.engine.programs import CONFORMING_LIMIT, get_program

BENCHMARK = 3.3


def approx(a, b, tol=0.02):
    return abs(a - b) <= tol


# --------------------------------------------------------------------------
# Amortization
# --------------------------------------------------------------------------

def test_payment_matches_known_value():
    # $300,000 at 6% over 30 years is a widely quoted $1,798.65.
    assert approx(af.monthly_payment(300_000, 6.0, 360), 1798.65, 0.5)


def test_zero_rate_is_straight_division():
    assert af.monthly_payment(12_000, 0.0, 12) == 1000.0


def test_payment_and_max_principal_are_inverses():
    payment = af.monthly_payment(250_000, 5.5, 360)
    assert approx(af.max_principal_for_payment(payment, 5.5, 360), 250_000, 1.0)


def test_degenerate_inputs_do_not_explode():
    assert af.monthly_payment(0, 6.0, 360) == 0.0
    assert af.monthly_payment(100_000, 6.0, 0) == 0.0
    assert af.max_principal_for_payment(0, 6.0, 360) == 0.0


def test_dti_and_ltv():
    assert af.back_end_dti(2000, 500, 10_000) == 25.0
    assert af.loan_to_value(190_000, 200_000) == 95.0
    assert af.back_end_dti(2000, 500, 0) is None
    assert af.loan_to_value(100, 0) is None


def test_payment_budget_never_goes_negative():
    # Existing debt already past the cap must return 0, not a negative budget.
    assert af.payment_budget_at_dti(5000, 4000, 43.0) == 0.0


# --------------------------------------------------------------------------
# Rule engine
# --------------------------------------------------------------------------

def applicant(**over):
    base = {
        "purpose": "home_purchase",
        "credit_score": 720,
        "monthly_income_usd": 8000.0,
        "monthly_debt_usd": 400.0,
        "loan_amount_usd": 300_000.0,
        "down_payment_usd": 60_000.0,
        "asset_value_usd": 360_000.0,
        "term_months": None,
        "military_service": False,
        "rural_property": False,
        "business_operating": False,
    }
    base.update(over)
    return base


def verdict_for(program_id, **over):
    return el.evaluate_program(get_program(program_id), applicant(**over), BENCHMARK)


def test_strong_applicant_clears_conventional():
    assert verdict_for("conventional")["verdict"] == el.LIKELY


def test_credit_below_hard_floor_blocks_and_explains():
    r = verdict_for("conventional", credit_score=560)
    assert r["verdict"] == el.NOT_ELIGIBLE
    credit = next(c for c in r["checks"] if c["id"] == "credit")
    assert credit["status"] == el.FAIL
    assert "60 points short" in credit["detail"]


def test_fha_reaches_lower_than_conventional():
    # 590 is under conventional's 620 floor but over FHA's 580.
    assert verdict_for("conventional", credit_score=590)["verdict"] == el.NOT_ELIGIBLE
    assert verdict_for("fha", credit_score=590)["verdict"] != el.NOT_ELIGIBLE


def test_fha_demands_more_down_below_580():
    # At 570 FHA needs 10 percent down, so 3 percent must not pass clean.
    r = verdict_for(
        "fha", credit_score=570, loan_amount_usd=291_000.0,
        down_payment_usd=9_000.0, asset_value_usd=300_000.0,
    )
    ltv = next(c for c in r["checks"] if c["id"] == "ltv")
    assert ltv["status"] in (el.WARN, el.FAIL)


def test_va_requires_declared_service():
    assert verdict_for("va", military_service=False)["verdict"] == el.NOT_ELIGIBLE
    assert verdict_for("va", military_service=True)["verdict"] != el.NOT_ELIGIBLE


def test_va_needs_no_down_payment():
    r = verdict_for(
        "va", military_service=True, loan_amount_usd=360_000.0,
        down_payment_usd=0.0, asset_value_usd=360_000.0,
    )
    assert r["verdict"] != el.NOT_ELIGIBLE
    assert r["estimate"]["ltv_pct"] == 100.0


def test_conventional_rejects_100_percent_ltv():
    r = verdict_for(
        "conventional", loan_amount_usd=360_000.0,
        down_payment_usd=0.0, asset_value_usd=360_000.0,
    )
    assert r["verdict"] == el.NOT_ELIGIBLE
    ltv = next(c for c in r["checks"] if c["id"] == "ltv")
    assert ltv["status"] == el.FAIL


def test_amount_over_conforming_limit_is_blocked():
    r = verdict_for(
        "conventional",
        loan_amount_usd=CONFORMING_LIMIT + 50_000,
        down_payment_usd=200_000.0,
        asset_value_usd=CONFORMING_LIMIT + 260_000,
    )
    amount = next(c for c in r["checks"] if c["id"] == "amount")
    assert amount["status"] == el.FAIL


def test_jumbo_rejects_small_loans():
    amount = next(c for c in verdict_for("jumbo")["checks"] if c["id"] == "amount")
    assert amount["status"] == el.FAIL


def test_high_debt_fails_on_dti():
    r = verdict_for("conventional", monthly_debt_usd=3200.0)
    dti = next(c for c in r["checks"] if c["id"] == "dti")
    assert dti["status"] == el.FAIL
    assert r["verdict"] == el.NOT_ELIGIBLE


def test_dti_between_standard_and_stretch_is_a_warning_not_a_rejection():
    # Tuned to land between conventional's 45 percent limit and 50 percent ceiling.
    r = verdict_for("conventional", monthly_debt_usd=1700.0, monthly_income_usd=6000.0)
    dti = next(c for c in r["checks"] if c["id"] == "dti")
    assert dti["status"] in (el.WARN, el.FAIL)


def test_better_credit_never_costs_more():
    low = verdict_for("conventional", credit_score=660)["estimate"]["rate_pct"]
    high = verdict_for("conventional", credit_score=780)["estimate"]["rate_pct"]
    assert high < low


def test_fha_adds_mip_and_conventional_adds_pmi_above_80_ltv():
    fha = verdict_for("fha")["estimate"]
    assert fha["mortgage_insurance"] > 0

    high_ltv = verdict_for(
        "conventional", loan_amount_usd=342_000.0,
        down_payment_usd=18_000.0, asset_value_usd=360_000.0,
    )["estimate"]
    assert high_ltv["mortgage_insurance"] > 0

    low_ltv = verdict_for(
        "conventional", loan_amount_usd=250_000.0,
        down_payment_usd=110_000.0, asset_value_usd=360_000.0,
    )["estimate"]
    assert low_ltv["mortgage_insurance"] == 0


def test_every_check_reports_its_status():
    for check in verdict_for("fha")["checks"]:
        assert check["status"] in (el.PASS, el.WARN, el.FAIL)
        assert check["detail"]


# --------------------------------------------------------------------------
# Full evaluation
# --------------------------------------------------------------------------

def test_evaluate_ranks_eligible_programs_first():
    result = el.evaluate(applicant(), BENCHMARK)
    verdicts = [p["verdict"] for p in result["programs"]]
    rank = {el.LIKELY: 0, el.POSSIBLE: 1, el.NOT_ELIGIBLE: 2}
    assert [rank[v] for v in verdicts] == sorted(rank[v] for v in verdicts)
    assert result["best"] is not None


def test_evaluate_handles_an_applicant_who_qualifies_for_nothing():
    result = el.evaluate(applicant(credit_score=400, monthly_debt_usd=7000.0), BENCHMARK)
    assert result["eligible_count"] == 0
    assert result["best"] is None


def test_affordability_ceiling_scales_with_income():
    poorer = el.affordability_summary(applicant(monthly_income_usd=5000.0), BENCHMARK, "home_purchase")
    richer = el.affordability_summary(applicant(monthly_income_usd=15000.0), BENCHMARK, "home_purchase")
    assert richer["max_loan_usd"] > poorer["max_loan_usd"]


def test_ceiling_never_exceeds_the_programs_own_limit():
    # The San Francisco case: a high earner was told they could borrow $1.77M
    # "via Conventional conforming loan" on a page that rejected that program
    # for exceeding its $806,500 ceiling.
    rich = applicant(
        credit_score=780, monthly_income_usd=34_167.0, monthly_debt_usd=1_800.0,
        loan_amount_usd=1_250_000.0, down_payment_usd=350_000.0, asset_value_usd=1_600_000.0,
    )
    result = el.affordability_summary(rich, BENCHMARK, "home_purchase")
    program = get_program(result["program_id"])
    if program.get("max_loan"):
        assert result["max_loan_usd"] <= program["max_loan"], (
            f"{result['program_name']} quoted above its own ceiling"
        )


def test_ceiling_reports_what_constrained_it():
    rich = applicant(
        credit_score=780, monthly_income_usd=34_167.0, monthly_debt_usd=1_800.0,
    )
    result = el.affordability_summary(rich, BENCHMARK, "home_purchase")
    assert result["limited_by"]


def test_ceiling_never_names_a_program_the_applicant_is_barred_from():
    # A non-veteran must never be told their ceiling comes "via VA loan", and a
    # non-rural buyer must never be quoted USDA.
    civilian = applicant(military_service=False, rural_property=False)
    result = el.affordability_summary(civilian, BENCHMARK, "home_purchase")
    assert result["program_id"] not in ("va", "usda")


def test_ceiling_respects_a_program_floor():
    # A modest earner cannot be quoted a jumbo loan, whose floor is above what
    # their income could ever carry.
    modest = applicant(monthly_income_usd=4_000.0, monthly_debt_usd=300.0)
    result = el.affordability_summary(modest, BENCHMARK, "home_purchase")
    assert result["program_id"] != "jumbo"


def test_veteran_can_still_be_quoted_va():
    vet = applicant(military_service=True, monthly_income_usd=7_333.0, monthly_debt_usd=200.0)
    result = el.affordability_summary(vet, BENCHMARK, "home_purchase")
    assert result["max_loan_usd"] > 0


def test_credit_bands():
    assert el.credit_band(810) == "Exceptional"
    assert el.credit_band(750) == "Very good"
    assert el.credit_band(700) == "Good"
    assert el.credit_band(600) == "Fair"
    assert el.credit_band(520) == "Poor"


def test_non_mortgage_purposes_return_programs():
    for purpose in ("auto", "personal", "small_business"):
        result = el.evaluate(
            applicant(
                purpose=purpose, loan_amount_usd=25_000.0,
                down_payment_usd=3_000.0, asset_value_usd=28_000.0,
                business_operating=True,
            ),
            BENCHMARK,
        )
        assert result["programs"], f"no programs returned for {purpose}"


if __name__ == "__main__":
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            passed += 1
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {name}  {exc}")
        except Exception as exc:
            failed += 1
            print(f"ERROR {name}  {type(exc).__name__}: {exc}")
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
