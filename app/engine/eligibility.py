"""The eligibility engine.

Design rule: this module never returns a bare verdict. Every program comes back
with the individual checks that produced it, each one carrying the user's value,
the threshold it was compared against, and where that threshold comes from. A
user who is declined can see exactly which number did it and by how much.

Nothing here contacts a credit bureau, and nothing here is a credit decision.
The credit score used is the one the user typed in.
"""

from __future__ import annotations

from typing import Any

from app.engine import affordability as af
from app.engine.programs import PROGRAMS, programs_for

PASS, WARN, FAIL = "pass", "warn", "fail"

# Verdicts, worst to best.
NOT_ELIGIBLE = "not_eligible"
POSSIBLE = "possible"
LIKELY = "likely_eligible"

# Rate adjustment by credit band, in percentage points. Lenders publish these as
# loan-level price adjustments; the shape below is representative, not any one
# lender's grid.
CREDIT_ADJUSTMENTS = [
    (760, -0.35),
    (740, -0.20),
    (720, -0.10),
    (700, 0.05),
    (680, 0.20),
    (660, 0.50),
    (640, 0.85),
    (620, 1.30),
    (580, 2.20),
    (0, 3.60),
]


def credit_adjustment(score: int) -> float:
    for floor, adj in CREDIT_ADJUSTMENTS:
        if score >= floor:
            return adj
    return CREDIT_ADJUSTMENTS[-1][1]


def credit_band(score: int) -> str:
    if score >= 800:
        return "Exceptional"
    if score >= 740:
        return "Very good"
    if score >= 670:
        return "Good"
    if score >= 580:
        return "Fair"
    return "Poor"


def _check(
    check_id: str,
    label: str,
    status: str,
    detail: str,
    your_value: Any = None,
    threshold: Any = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": status,
        "detail": detail,
        "your_value": your_value,
        "threshold": threshold,
    }


def _is_mortgage(program: dict) -> bool:
    return bool(set(program["purposes"]) & {"home_purchase", "home_refinance"})


def evaluate_program(
    program: dict, applicant: dict, benchmark_rate: float
) -> dict[str, Any]:
    """Run one program against one applicant. Returns the verdict plus every
    check that produced it."""
    checks: list[dict[str, Any]] = []

    score = applicant["credit_score"]
    monthly_income = applicant["monthly_income_usd"]
    existing_debt = applicant["monthly_debt_usd"]
    loan_amount = applicant["loan_amount_usd"]
    down_payment = applicant.get("down_payment_usd", 0.0)
    asset_value = applicant.get("asset_value_usd") or (loan_amount + down_payment)
    term_months = applicant.get("term_months") or program["typical_term_months"]

    # ---- Credit score -------------------------------------------------------
    hard_floor = program.get("min_credit_absolute", program["min_credit"])
    preferred = program.get("min_credit_lender_overlay") or program["min_credit"]

    if score < hard_floor:
        checks.append(
            _check(
                "credit",
                "Credit score",
                FAIL,
                f"This program does not go below {hard_floor}. You are {hard_floor - score} points short.",
                score,
                hard_floor,
            )
        )
    elif score < preferred:
        checks.append(
            _check(
                "credit",
                "Credit score",
                WARN,
                f"Above the {hard_floor} hard floor but below the {preferred} most lenders want. "
                "Expect a larger down payment, a higher rate, or both.",
                score,
                preferred,
            )
        )
    else:
        checks.append(
            _check(
                "credit",
                "Credit score",
                PASS,
                f"Clears the {preferred} threshold with {score - preferred} points to spare.",
                score,
                preferred,
            )
        )

    # ---- Down payment and loan-to-value ------------------------------------
    ltv = af.loan_to_value(loan_amount, asset_value)
    required_down_pct = program["min_down_pct"]

    # FHA raises the down payment requirement for scores under 580.
    if (
        program.get("min_down_pct_low_credit")
        and score < program.get("low_credit_threshold", 0)
    ):
        required_down_pct = program["min_down_pct_low_credit"]

    if program.get("max_ltv") is not None:
        down_pct = round(down_payment / asset_value * 100, 2) if asset_value > 0 else 0.0
        if ltv is not None and ltv > program["max_ltv"]:
            shortfall = round(asset_value * (ltv - program["max_ltv"]) / 100, 2)
            checks.append(
                _check(
                    "ltv",
                    "Down payment",
                    FAIL,
                    f"Loan-to-value of {ltv} percent exceeds the {program['max_ltv']} percent cap. "
                    f"About ${shortfall:,.0f} more down would bring it inside.",
                    f"{ltv} percent LTV",
                    f"{program['max_ltv']} percent max",
                )
            )
        elif down_pct < required_down_pct:
            checks.append(
                _check(
                    "ltv",
                    "Down payment",
                    WARN,
                    f"Your {down_pct} percent down is below the {required_down_pct} percent this program "
                    "normally asks for at your credit score.",
                    f"{down_pct} percent",
                    f"{required_down_pct} percent",
                )
            )
        else:
            checks.append(
                _check(
                    "ltv",
                    "Down payment",
                    PASS,
                    f"{down_pct} percent down clears the {required_down_pct} percent minimum.",
                    f"{down_pct} percent",
                    f"{required_down_pct} percent",
                )
            )

    # ---- Loan size ---------------------------------------------------------
    if program.get("max_loan") and loan_amount > program["max_loan"]:
        checks.append(
            _check(
                "amount",
                "Loan amount",
                FAIL,
                f"Above this program's ${program['max_loan']:,.0f} ceiling.",
                loan_amount,
                program["max_loan"],
            )
        )
    elif program.get("min_loan") and loan_amount < program["min_loan"]:
        checks.append(
            _check(
                "amount",
                "Loan amount",
                FAIL,
                f"Below the ${program['min_loan']:,.0f} floor. A conforming loan fits your amount instead.",
                loan_amount,
                program["min_loan"],
            )
        )
    else:
        checks.append(
            _check(
                "amount",
                "Loan amount",
                PASS,
                "Within this program's size limits.",
                loan_amount,
                program.get("max_loan"),
            )
        )

    # ---- Pricing, then the payment the ratios are judged against ------------
    rate = round(benchmark_rate + program["rate_spread"] + credit_adjustment(score), 2)
    rate = max(rate, 0.5)

    base_payment = af.monthly_payment(loan_amount, rate, term_months)

    escrow = mi = 0.0
    if _is_mortgage(program):
        escrow = af.estimate_escrow(asset_value)
        if program.get("mortgage_insurance") == "pmi":
            mi = af.estimate_pmi(loan_amount, ltv)
        elif program.get("mortgage_insurance") == "fha_mip":
            mi = af.estimate_fha_mip(loan_amount)

    total_monthly = round(base_payment + escrow + mi, 2)

    # ---- Debt-to-income ----------------------------------------------------
    dti = af.back_end_dti(total_monthly, existing_debt, monthly_income)
    max_dti = program["max_dti"]
    stretch_dti = program.get("max_dti_stretch", max_dti)

    if dti is None:
        checks.append(
            _check("dti", "Debt-to-income", FAIL, "No income was provided, so this cannot be assessed.")
        )
    elif dti > stretch_dti:
        room = af.payment_budget_at_dti(monthly_income, existing_debt, stretch_dti)
        checks.append(
            _check(
                "dti",
                "Debt-to-income",
                FAIL,
                f"{dti} percent is past the {stretch_dti} percent absolute cap. "
                f"Your payments would need to fit inside ${room:,.0f} a month.",
                f"{dti} percent",
                f"{stretch_dti} percent",
            )
        )
    elif dti > max_dti:
        checks.append(
            _check(
                "dti",
                "Debt-to-income",
                WARN,
                f"{dti} percent is over the {max_dti} percent standard limit but under the "
                f"{stretch_dti} percent exception ceiling. Approval would depend on reserves, "
                "credit history or a co-borrower.",
                f"{dti} percent",
                f"{max_dti} percent",
            )
        )
    else:
        checks.append(
            _check(
                "dti",
                "Debt-to-income",
                PASS,
                f"{dti} percent sits comfortably under the {max_dti} percent limit.",
                f"{dti} percent",
                f"{max_dti} percent",
            )
        )

    # ---- Gates the applicant has to self-declare ---------------------------
    gate = program.get("eligibility_gate")
    if gate == "military_service":
        if applicant.get("military_service"):
            checks.append(
                _check("gate", "Service eligibility", PASS, "You indicated military service. The VA still has to issue a Certificate of Eligibility.")
            )
        else:
            checks.append(
                _check("gate", "Service eligibility", FAIL, "VA loans are limited to service members, veterans and certain surviving spouses.")
            )
    elif gate == "rural_property":
        if applicant.get("rural_property"):
            checks.append(
                _check("gate", "Property location", WARN, "You indicated a rural or eligible area. This has to be confirmed address by address on the USDA map.")
            )
        else:
            checks.append(
                _check("gate", "Property location", FAIL, "USDA lending is limited to designated rural and some suburban areas.")
            )
    elif gate == "business_operating":
        if applicant.get("business_operating"):
            checks.append(
                _check("gate", "Business status", PASS, "You indicated an operating for-profit US business.")
            )
        else:
            checks.append(
                _check("gate", "Business status", FAIL, "SBA 7(a) requires an operating for-profit business in the United States.")
            )

    # ---- Verdict -----------------------------------------------------------
    statuses = [c["status"] for c in checks]
    if FAIL in statuses:
        verdict = NOT_ELIGIBLE
    elif WARN in statuses:
        verdict = POSSIBLE
    else:
        verdict = LIKELY

    return {
        "program_id": program["id"],
        "name": program["name"],
        "summary": program["summary"],
        "authority": program["authority"],
        "verdict": verdict,
        "checks": checks,
        "blocking": [c for c in checks if c["status"] == FAIL],
        "requirements": program.get("requires", []),
        "tradeoffs": program.get("tradeoffs", []),
        "assumption": program.get("assumption"),
        "estimate": {
            "rate_pct": rate,
            "rate_breakdown": {
                "benchmark": round(benchmark_rate, 2),
                "program_spread": program["rate_spread"],
                "credit_adjustment": credit_adjustment(score),
            },
            "term_months": term_months,
            "principal_and_interest": base_payment,
            "escrow_estimate": escrow,
            "mortgage_insurance": mi,
            "total_monthly": total_monthly,
            "total_interest": af.total_interest(loan_amount, rate, term_months),
            "dti_pct": dti,
            "ltv_pct": ltv,
        },
    }


def evaluate(applicant: dict, benchmark_rate: float) -> dict[str, Any]:
    """Run every program for the requested purpose."""
    purpose = applicant["purpose"]
    results = [evaluate_program(p, applicant, benchmark_rate) for p in programs_for(purpose)]

    order = {LIKELY: 0, POSSIBLE: 1, NOT_ELIGIBLE: 2}
    results.sort(key=lambda r: (order[r["verdict"]], r["estimate"]["total_monthly"]))

    eligible = [r for r in results if r["verdict"] != NOT_ELIGIBLE]

    return {
        "programs": results,
        "eligible_count": len(eligible),
        "best": eligible[0] if eligible else None,
        "affordability": affordability_summary(applicant, benchmark_rate, purpose),
    }


def affordability_summary(
    applicant: dict, benchmark_rate: float, purpose: str
) -> dict[str, Any]:
    """The largest loan the applicant could carry on income and debts alone.

    This is a payment-capacity answer, not an eligibility answer: it ignores
    the deposit, because "how much could I borrow" and "can I have the amount
    I asked for" are different questions and a user needs both.

    It must still respect the constraints that make a number impossible rather
    than merely unlikely. A program cannot lend above its own ceiling, cannot
    lend below its floor, and cannot be offered to someone who fails its
    eligibility gate outright. Skipping those checks produced a real
    contradiction: a San Francisco applicant was told they could borrow
    $1.77M "via Conventional conforming loan" on the same page that rejected
    that program for exceeding its $806,500 limit.
    """
    candidates = programs_for(purpose)
    if not candidates:
        return {}

    score = applicant["credit_score"]
    monthly_income = applicant["monthly_income_usd"]
    existing_debt = applicant["monthly_debt_usd"]

    best: dict[str, Any] | None = None
    for program in candidates:
        if score < program.get("min_credit_absolute", program["min_credit"]):
            continue

        # A program the applicant is categorically shut out of cannot be the
        # one quoted back to them as their borrowing ceiling.
        gate = program.get("eligibility_gate")
        if gate and not applicant.get(gate):
            continue

        term = applicant.get("term_months") or program["typical_term_months"]
        rate = max(0.5, benchmark_rate + program["rate_spread"] + credit_adjustment(score))
        budget = af.payment_budget_at_dti(monthly_income, existing_debt, program["max_dti"])

        # For mortgages, escrow and insurance eat into the same budget.
        usable = budget * 0.78 if _is_mortgage(program) else budget
        principal = af.max_principal_for_payment(usable, rate, term)

        limited_by = "your debt-to-income limit"
        ceiling = program.get("max_loan")
        if ceiling and principal > ceiling:
            principal = float(ceiling)
            limited_by = f"this program's ${ceiling:,.0f} ceiling"

        # Below a program's floor the program simply is not available.
        floor = program.get("min_loan")
        if floor and principal < floor:
            continue

        if best is None or principal > best["max_loan_usd"]:
            best = {
                "program_id": program["id"],
                "program_name": program["name"],
                "max_loan_usd": principal,
                "monthly_budget_usd": budget,
                "rate_pct": round(rate, 2),
                "term_months": term,
                "dti_cap_pct": program["max_dti"],
                "limited_by": limited_by,
                "note": (
                    "Roughly 22 percent of the payment budget is reserved for property tax, "
                    "insurance and mortgage insurance."
                    if _is_mortgage(program)
                    else None
                ),
            }

    return best or {}


def all_purposes() -> list[dict[str, str]]:
    from app.engine.programs import PURPOSES

    return [{"id": k, "label": v} for k, v in PURPOSES.items()]


def catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": p["id"],
            "name": p["name"],
            "purposes": p["purposes"],
            "authority": p["authority"],
            "summary": p["summary"],
            "min_credit": p.get("min_credit_absolute", p["min_credit"]),
            "max_dti": p["max_dti"],
            "min_down_pct": p["min_down_pct"],
            "assumption": p.get("assumption"),
        }
        for p in PROGRAMS
    ]
