"""Central configuration. Every external endpoint used by Basis is listed here,
so the full outbound surface of the app is auditable from one file."""

import os
from pathlib import Path

APP_NAME = "Basis"
APP_VERSION = "1.0.0"
PORT = int(os.environ.get("PORT", "8767"))

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
CACHE_DIR = BASE_DIR / ".cache"

# Identify ourselves honestly to every public API we call.
USER_AGENT = f"{APP_NAME}/{APP_VERSION} (open-data loan eligibility demo)"

# Outbound timeouts, in seconds. Free public APIs are best-effort, so every
# provider is allowed to fail without taking the request down with it.
HTTP_TIMEOUT = 12.0

# Cache time-to-live per provider, in seconds. These are deliberately long:
# the underlying data changes daily at most, and hammering free endpoints is
# both rude and a good way to get rate limited.
TTL = {
    "fdic_institutions": 60 * 60 * 24,
    "fdic_locations": 60 * 60 * 24,
    "cfpb": 60 * 60 * 12,
    "frankfurter": 60 * 60 * 6,
    "zippopotam": 60 * 60 * 24 * 30,
    "nager": 60 * 60 * 24 * 30,
    "treasury": 60 * 60 * 12,
    "worldbank": 60 * 60 * 24 * 7,
    "ifsc": 60 * 60 * 24 * 30,
}

ENDPOINTS = {
    "fdic_institutions": "https://api.fdic.gov/banks/institutions",
    "fdic_locations": "https://api.fdic.gov/banks/locations",
    "cfpb": "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/",
    "cfpb_suggest": "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/_suggest_company/",
    "frankfurter": "https://api.frankfurter.dev/v1/latest",
    "zippopotam": "https://api.zippopotam.us",
    "nager": "https://date.nager.at/api/v3/PublicHolidays",
    "treasury": "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/avg_interest_rates",
    "worldbank": "https://api.worldbank.org/v2",
    "ifsc": "https://ifsc.razorpay.com",
}

# Credited on the site's Sources page. Every one of these is keyless and was
# verified returning live data before being wired in.
SOURCES = [
    {
        "key": "fdic_institutions",
        "name": "FDIC BankFind - Institutions",
        "publisher": "Federal Deposit Insurance Corporation (US government)",
        "used_for": "The real, currently active FDIC-insured banks in your state, with total assets, domestic office count and website.",
        "auth": "None",
        "docs": "https://banks.data.fdic.gov/docs/",
    },
    {
        "key": "fdic_locations",
        "name": "FDIC BankFind - Locations",
        "publisher": "Federal Deposit Insurance Corporation (US government)",
        "used_for": "Actual branch addresses in your ZIP code, so 'nearby' means a real building and not a guess.",
        "auth": "None",
        "docs": "https://banks.data.fdic.gov/docs/",
    },
    {
        "key": "cfpb",
        "name": "Consumer Complaint Database",
        "publisher": "Consumer Financial Protection Bureau (US government)",
        "used_for": "How many consumer complaints each bank has received, and what share it answered on time.",
        "auth": "None",
        "docs": "https://cfpb.github.io/api/ccdb/",
    },
    {
        "key": "treasury",
        "name": "Fiscal Data - Average Interest Rates",
        "publisher": "US Department of the Treasury",
        "used_for": "The government borrowing rate that consumer loan pricing is benchmarked against.",
        "auth": "None",
        "docs": "https://fiscaldata.treasury.gov/api-documentation/",
    },
    {
        "key": "frankfurter",
        "name": "Frankfurter",
        "publisher": "European Central Bank reference rates",
        "used_for": "Converting income stated in another currency into USD before any ratio is calculated.",
        "auth": "None",
        "docs": "https://www.frankfurter.app/docs",
    },
    {
        "key": "zippopotam",
        "name": "Zippopotam.us",
        "publisher": "Zippopotam.us",
        "used_for": "Turning a ZIP code into a city, state and coordinates.",
        "auth": "None",
        "docs": "https://api.zippopotam.us/",
    },
    {
        "key": "nager",
        "name": "Nager.Date",
        "publisher": "Nager.Date",
        "used_for": "US bank holidays, so the estimated funding date skips days banks are closed.",
        "auth": "None",
        "docs": "https://date.nager.at/Api",
    },
    {
        "key": "worldbank",
        "name": "World Bank Indicators",
        "publisher": "The World Bank",
        "used_for": "The average commercial lending rate for non-US countries.",
        "auth": "None",
        "docs": "https://datahelpdesk.worldbank.org/knowledgebase/articles/889392",
    },
    {
        "key": "ifsc",
        "name": "Razorpay IFSC",
        "publisher": "Razorpay",
        "used_for": "Looking up an Indian bank branch from its IFSC code.",
        "auth": "None",
        "docs": "https://ifsc.razorpay.com/",
    },
]
