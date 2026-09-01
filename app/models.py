"""Request and response schemas.

Input validation is deliberately strict. A loan calculator that silently
accepts a negative income or a credit score of 9000 will happily return a
confident, meaningless answer.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Purpose = Literal["home_purchase", "home_refinance", "auto", "personal", "small_business"]

CURRENCIES = ["USD", "EUR", "GBP", "INR", "CAD", "AUD", "JPY", "SGD", "CHF", "MXN", "BRL", "ZAR"]


class MatchRequest(BaseModel):
    purpose: Purpose = Field(description="What the loan is for.")

    annual_income: float = Field(gt=0, le=100_000_000, description="Gross annual income, before tax.")
    income_currency: str = Field(default="USD", description="Currency the income figure is in.")
    monthly_debt: float = Field(default=0, ge=0, le=1_000_000, description="Existing monthly debt payments, excluding the new loan.")

    credit_score: int = Field(ge=300, le=850, description="FICO-scale credit score, self-reported.")

    loan_amount: float = Field(gt=0, le=50_000_000, description="Amount you want to borrow.")
    down_payment: float = Field(default=0, ge=0, le=50_000_000)
    asset_value: float | None = Field(default=None, ge=0, le=100_000_000, description="Price of the home or vehicle. Defaults to loan plus down payment.")
    term_months: int | None = Field(default=None, ge=6, le=480)

    zip_code: str | None = Field(default=None, description="US ZIP, used to find real lenders near you.")

    military_service: bool = False
    rural_property: bool = False
    business_operating: bool = False

    @field_validator("income_currency")
    @classmethod
    def known_currency(cls, v: str) -> str:
        v = (v or "USD").upper()
        if v not in CURRENCIES:
            raise ValueError(f"Unsupported currency. Choose one of: {', '.join(CURRENCIES)}")
        return v

    @field_validator("zip_code")
    @classmethod
    def clean_zip(cls, v: str | None) -> str | None:
        if not v:
            return None
        v = v.strip()
        if not (v.isdigit() and len(v) == 5):
            raise ValueError("ZIP code must be exactly 5 digits.")
        return v

    @model_validator(mode="after")
    def coherent_amounts(self) -> "MatchRequest":
        if self.asset_value is not None and self.asset_value > 0:
            if self.loan_amount > self.asset_value:
                raise ValueError("Loan amount cannot exceed the value of what you are buying.")
            if self.down_payment > self.asset_value:
                raise ValueError("Down payment cannot exceed the value of what you are buying.")
        return self


class MatchResponse(BaseModel):
    applicant: dict[str, Any]
    location: dict[str, Any] | None
    benchmark: dict[str, Any]
    eligibility: dict[str, Any]
    lenders: dict[str, Any]
    funding_estimate: dict[str, Any] | None
    sources_used: list[dict[str, Any]]
    disclaimer: str
