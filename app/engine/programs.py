"""The loan program catalog.

Every threshold here is a published underwriting standard from a federal
agency or a government-sponsored enterprise, not a number this project made
up. Each program carries the authority it comes from so a user can go and
check it. Where a figure is a market convention rather than a published rule
it is marked as such in `assumption`.

Dollar limits are revised annually. LIMIT_VINTAGE records which year's
figures are encoded, so a stale limit shows up as stale instead of silently
producing a wrong answer.
"""

from __future__ import annotations

LIMIT_VINTAGE = 2025

# FHFA baseline conforming loan limit for a one-unit property.
CONFORMING_LIMIT = 806_500
# FHA floor is 65% of the conforming limit, ceiling is 150% (high-cost counties).
FHA_FLOOR = 524_225
FHA_CEILING = 1_209_750

PURPOSES = {
    "home_purchase": "Buying a home",
    "home_refinance": "Refinancing a mortgage",
    "auto": "Buying a vehicle",
    "personal": "Personal loan",
    "small_business": "Small business loan",
}

# rate_spread is the margin over the Treasury benchmark, in percentage points.
# Those spreads are market conventions, not published rules, and are labelled
# as estimates everywhere they surface.
PROGRAMS = [
    {
        "id": "fha",
        "name": "FHA loan",
        "purposes": ["home_purchase", "home_refinance"],
        "authority": "US Department of Housing and Urban Development, HUD Handbook 4000.1",
        "summary": "Government-insured mortgage built for buyers with a smaller down payment or a thinner credit file.",
        "min_credit": 580,
        "min_credit_absolute": 500,
        "min_down_pct": 3.5,
        "min_down_pct_low_credit": 10.0,
        "low_credit_threshold": 580,
        "max_dti": 43.0,
        "max_dti_stretch": 50.0,
        "max_ltv": 96.5,
        "max_loan": FHA_CEILING,
        "typical_term_months": 360,
        "rate_spread": 2.8,
        "mortgage_insurance": "fha_mip",
        "requires": [
            "Property must be your primary residence",
            "FHA-approved appraisal",
        ],
        "tradeoffs": [
            "Mortgage insurance usually lasts the life of the loan when you put down less than 10 percent.",
            "Loan limits are set per county, so the ceiling in your area may be lower than the national maximum.",
        ],
    },
    {
        "id": "va",
        "name": "VA loan",
        "purposes": ["home_purchase", "home_refinance"],
        "authority": "US Department of Veterans Affairs, VA Lenders Handbook M26-7",
        "summary": "No down payment and no monthly mortgage insurance, for eligible service members, veterans and surviving spouses.",
        "min_credit": 0,
        "min_credit_absolute": 0,
        "min_credit_lender_overlay": 580,
        "min_down_pct": 0.0,
        "max_dti": 41.0,
        "max_dti_stretch": 60.0,
        "max_ltv": 100.0,
        "max_loan": None,
        "typical_term_months": 360,
        "rate_spread": 2.6,
        "mortgage_insurance": None,
        "eligibility_gate": "military_service",
        "requires": [
            "Certificate of Eligibility from the VA",
            "Property must be your primary residence",
        ],
        "tradeoffs": [
            "The VA sets no minimum credit score, but individual lenders impose their own floor, commonly around 580 to 620.",
            "A one-time funding fee applies unless you have a service-connected disability exemption.",
            "Above 41 percent DTI the VA relies on a residual income test, which this estimate does not model.",
        ],
        "assumption": "The 580 floor shown is a common lender overlay, not a VA rule.",
    },
    {
        "id": "usda",
        "name": "USDA rural development loan",
        "purposes": ["home_purchase"],
        "authority": "US Department of Agriculture, Single Family Housing Guaranteed Loan Program",
        "summary": "No down payment for moderate-income buyers in eligible rural and many suburban areas.",
        "min_credit": 640,
        "min_credit_absolute": 580,
        "min_down_pct": 0.0,
        "max_dti": 41.0,
        "max_dti_stretch": 44.0,
        "max_ltv": 100.0,
        "max_loan": None,
        "typical_term_months": 360,
        "rate_spread": 2.8,
        "mortgage_insurance": None,
        "eligibility_gate": "rural_property",
        "income_cap_pct_of_median": 115,
        "requires": [
            "Property must sit inside a USDA-eligible area",
            "Household income at or below 115 percent of the area median",
            "Primary residence only",
        ],
        "tradeoffs": [
            "Area eligibility is decided address by address and has to be checked on the USDA map.",
            "An upfront and an annual guarantee fee both apply.",
        ],
    },
    {
        "id": "conventional",
        "name": "Conventional conforming loan",
        "purposes": ["home_purchase", "home_refinance"],
        "authority": "Fannie Mae Selling Guide and Freddie Mac Seller Servicer Guide",
        "summary": "The standard mortgage. Best pricing if your credit is strong, and mortgage insurance falls away once you reach 20 percent equity.",
        "min_credit": 620,
        "min_credit_absolute": 620,
        "min_down_pct": 3.0,
        "max_dti": 45.0,
        "max_dti_stretch": 50.0,
        "max_ltv": 97.0,
        "max_loan": CONFORMING_LIMIT,
        "typical_term_months": 360,
        "rate_spread": 3.0,
        "mortgage_insurance": "pmi",
        "requires": [],
        "tradeoffs": [
            "Pricing is far more sensitive to your credit score than FHA pricing is.",
            "97 percent financing is generally reserved for first-time buyers or income-qualified programs.",
        ],
    },
    {
        "id": "jumbo",
        "name": "Jumbo loan",
        "purposes": ["home_purchase", "home_refinance"],
        "authority": "Portfolio lender underwriting, above FHFA conforming limits",
        "summary": "For loan amounts above the conforming limit. The lender keeps it on its own books, so the bar is higher.",
        "min_credit": 700,
        "min_credit_absolute": 680,
        "min_down_pct": 10.0,
        "max_dti": 43.0,
        "max_dti_stretch": 45.0,
        "max_ltv": 90.0,
        "min_loan": CONFORMING_LIMIT,
        "max_loan": None,
        "typical_term_months": 360,
        "rate_spread": 3.2,
        "mortgage_insurance": None,
        "requires": ["Cash reserves, commonly six to twelve months of payments"],
        "tradeoffs": [
            "There is no standard rulebook. Every jumbo lender writes its own, so terms vary widely.",
        ],
        "assumption": "Jumbo criteria are lender-specific. The thresholds shown are a common market pattern.",
    },
    {
        "id": "auto_prime",
        "name": "Auto loan, prime",
        "purposes": ["auto"],
        "authority": "Standard bank and credit union auto lending practice",
        "summary": "Secured by the vehicle, which is why the rate sits far below an unsecured loan.",
        "min_credit": 660,
        "min_credit_absolute": 660,
        "min_down_pct": 0.0,
        "max_dti": 45.0,
        "max_dti_stretch": 50.0,
        "max_ltv": 120.0,
        "max_loan": None,
        "typical_term_months": 60,
        "rate_spread": 3.4,
        "requires": [],
        "tradeoffs": [
            "Financing above the value of the vehicle leaves you owing more than the car is worth from day one.",
        ],
        "assumption": "Auto lending has no published federal underwriting standard. These are common bank criteria.",
    },
    {
        "id": "auto_subprime",
        "name": "Auto loan, credit-building",
        "purposes": ["auto"],
        "authority": "Standard subprime auto lending practice",
        "summary": "Available well below prime credit, at a materially higher rate.",
        "min_credit": 500,
        "min_credit_absolute": 500,
        "min_down_pct": 10.0,
        "max_dti": 50.0,
        "max_dti_stretch": 55.0,
        "max_ltv": 115.0,
        "max_loan": None,
        "typical_term_months": 60,
        "rate_spread": 9.0,
        "requires": ["Proof of steady income", "Down payment usually required"],
        "tradeoffs": [
            "Total interest can approach the price of the vehicle on a long term.",
            "Compare against a credit union before accepting dealer financing.",
        ],
        "assumption": "Subprime auto terms vary sharply by lender. Treat this as an order of magnitude.",
    },
    {
        "id": "personal_unsecured",
        "name": "Personal loan, unsecured",
        "purposes": ["personal"],
        "authority": "Standard bank, credit union and online lender practice",
        "summary": "No collateral, fixed term, fixed payment. Priced almost entirely on credit score.",
        "min_credit": 580,
        "min_credit_absolute": 580,
        "min_down_pct": 0.0,
        "max_dti": 40.0,
        "max_dti_stretch": 50.0,
        "max_loan": 100_000,
        "typical_term_months": 60,
        "rate_spread": 8.0,
        "requires": ["Verifiable income"],
        "tradeoffs": [
            "If the purpose is consolidating credit card debt, check the new rate really is lower than what you pay now.",
            "Origination fees of 1 to 8 percent are common and come out of the amount you receive.",
        ],
        "assumption": "Unsecured lending has no published standard. These reflect common criteria.",
    },
    {
        "id": "sba_7a",
        "name": "SBA 7(a) loan",
        "purposes": ["small_business"],
        "authority": "US Small Business Administration, SOP 50 10",
        "summary": "Government-guaranteed business lending, which lets banks approve borrowers they would otherwise decline.",
        "min_credit": 650,
        "min_credit_absolute": 620,
        "min_down_pct": 10.0,
        "max_dti": 50.0,
        "max_dti_stretch": 55.0,
        "max_loan": 5_000_000,
        "typical_term_months": 120,
        "rate_spread": 3.0,
        "eligibility_gate": "business_operating",
        "requires": [
            "For-profit business operating in the United States",
            "Demonstrated inability to get credit on reasonable terms elsewhere",
            "Owner equity injection, commonly 10 percent",
        ],
        "tradeoffs": [
            "Paperwork and closing timelines run far longer than consumer lending.",
            "A personal guarantee is required from anyone owning 20 percent or more.",
        ],
    },
]


def programs_for(purpose: str) -> list[dict]:
    return [p for p in PROGRAMS if purpose in p["purposes"]]


def get_program(program_id: str) -> dict | None:
    return next((p for p in PROGRAMS if p["id"] == program_id), None)
