"""Loan arithmetic: amortization, ratios and the affordability ceiling.

Pure functions, no I/O. Everything the eligibility engine decides is built on
these, so they are unit tested directly.
"""

from __future__ import annotations


def monthly_payment(principal: float, annual_rate_pct: float, term_months: int) -> float:
    """Standard fixed-rate amortized payment."""
    if principal <= 0 or term_months <= 0:
        return 0.0

    monthly_rate = annual_rate_pct / 100.0 / 12.0
    if monthly_rate == 0:
        return round(principal / term_months, 2)

    factor = (1 + monthly_rate) ** term_months
    return round(principal * monthly_rate * factor / (factor - 1), 2)


def total_interest(principal: float, annual_rate_pct: float, term_months: int) -> float:
    return round(monthly_payment(principal, annual_rate_pct, term_months) * term_months - principal, 2)


def max_principal_for_payment(
    payment: float, annual_rate_pct: float, term_months: int
) -> float:
    """Invert the amortization formula: the largest loan a given monthly
    payment can carry. This is what sets the affordability ceiling."""
    if payment <= 0 or term_months <= 0:
        return 0.0

    monthly_rate = annual_rate_pct / 100.0 / 12.0
    if monthly_rate == 0:
        return round(payment * term_months, 2)

    factor = (1 + monthly_rate) ** term_months
    return round(payment * (factor - 1) / (monthly_rate * factor), 2)


def front_end_dti(housing_payment: float, monthly_income: float) -> float | None:
    """Housing cost as a share of gross monthly income."""
    if monthly_income <= 0:
        return None
    return round(housing_payment / monthly_income * 100, 2)


def back_end_dti(
    new_payment: float, existing_monthly_debt: float, monthly_income: float
) -> float | None:
    """All monthly debt obligations, including the new loan, as a share of
    gross monthly income. This is the ratio underwriters actually cap."""
    if monthly_income <= 0:
        return None
    return round((new_payment + existing_monthly_debt) / monthly_income * 100, 2)


def loan_to_value(loan_amount: float, property_value: float) -> float | None:
    if property_value <= 0:
        return None
    return round(loan_amount / property_value * 100, 2)


def payment_budget_at_dti(
    monthly_income: float, existing_monthly_debt: float, max_dti_pct: float
) -> float:
    """How much room is left for a new monthly payment before hitting a
    DTI cap. Returns 0 when existing debt already exceeds the cap."""
    ceiling = monthly_income * max_dti_pct / 100.0
    return round(max(0.0, ceiling - existing_monthly_debt), 2)


def estimate_escrow(property_value: float) -> float:
    """Rough monthly property tax plus homeowner's insurance.

    Uses 1.1% of value per year for tax and 0.5% for insurance - close to the
    US national average. Real figures vary enormously by county, which is why
    this is surfaced to the user as a separate, labelled line rather than being
    folded silently into the payment.
    """
    if property_value <= 0:
        return 0.0
    return round(property_value * 0.016 / 12, 2)


def estimate_pmi(loan_amount: float, ltv_pct: float | None) -> float:
    """Private mortgage insurance, charged on conventional loans above 80% LTV.

    0.5% of the loan per year is a mid-range rate; actual PMI is priced on
    credit score and LTV together.
    """
    if ltv_pct is None or ltv_pct <= 80:
        return 0.0
    return round(loan_amount * 0.005 / 12, 2)


def estimate_fha_mip(loan_amount: float) -> float:
    """FHA annual mortgage insurance premium, 0.55% for most 30-year loans.

    Unlike PMI this generally cannot be cancelled when the loan is above 90%
    LTV at origination, which is the main long-run cost of choosing FHA.
    """
    return round(loan_amount * 0.0055 / 12, 2)
