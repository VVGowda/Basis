"""Consumer complaint history per bank, via the CFPB Consumer Complaint Database.

No public API says whether a bank will approve you. This one does say how many
people complained about it, what they complained about, and how often it
responded on time, which is a real, checkable signal about what dealing with
that lender is like.

Name matching is the whole difficulty here. The CFPB `company` filter is an
exact, case-sensitive term match, and the two governments spell the same bank
three different ways:

    FDIC charter name      Bank of America, National Association
    FDIC holding company   BANK OF AMERICA CORPORATION
    CFPB company           BANK OF AMERICA, NATIONAL ASSOCIATION

A failed lookup returns zero, which renders identically to a spotless record.
That is the dangerous failure mode, so every lookup goes through
`resolve_company`, an unresolvable name is reported as unmatched rather than as
zero, and the matching primitives below are unit tested directly.
"""

from __future__ import annotations

import re
from typing import Any

from app.cache import SourceLog, fetch_json
from app.config import ENDPOINTS, TTL

# Product filters that map to how this site groups loans.
PRODUCT_FILTER = {
    "home_purchase": "Mortgage",
    "home_refinance": "Mortgage",
    "auto": "Vehicle loan or lease",
    "personal": "Payday loan, title loan, personal loan, or advance loan",
    "small_business": None,
}

# Issues raised while getting a loan, as opposed to while paying one back.
# Someone choosing a lender to apply to cares about the first kind. Verified
# against the live issue taxonomy rather than assumed.
ORIGINATION_ISSUES = {
    "home_purchase": {
        "Applying for a mortgage or refinancing an existing mortgage",
        "Closing on a mortgage",
    },
    "home_refinance": {
        "Applying for a mortgage or refinancing an existing mortgage",
        "Closing on a mortgage",
    },
    "auto": {"Getting a loan or lease"},
    "personal": {"Getting the loan", "Getting a line of credit"},
    "small_business": set(),
}

_SUFFIXES = re.compile(
    r",?\s*\b(national association|n\.?a\.?|federal savings bank|fsb|"
    r"savings bank|state bank|bancorp|bancshares|holdings?|financial|"
    r"corporation|corp|incorporated|inc|company|co|llc|ltd|the)\b\.?",
    re.IGNORECASE,
)


def canonical(name: str) -> str:
    """Reduce an institution name to a comparable key.

    An ampersand has to normalise to the word "and". FDIC writes "First United
    Bank & Trust" while the CFPB writes "FIRST UNITED BANK AND TRUST COMPANY".
    Discarding "&" as punctuation leaves "first united bank trust" against
    "first united bank and trust", so one bank reads as two and a real
    complaint record is reported as absent.
    """
    text = (name or "").replace("&", " and ")
    cleaned = _SUFFIXES.sub(" ", text)
    cleaned = re.sub(r"[^a-z0-9 ]", " ", cleaned.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Stripping a suffix can leave a dangling conjunction, as "Wells Fargo &
    # Company" becomes "wells fargo and".
    return re.sub(r"\s+and$", "", cleaned)


def names_match(a: str, b: str) -> bool:
    """Whether two institution names refer to the same institution.

    One name must contain the other from the start. The CFPB suggest endpoint
    is a prefix matcher, so requiring only a shared opening word would happily
    accept a different bank; requiring exact equality would reject every case
    where one source carries an extra trailing word.
    """
    ca, cb = canonical(a), canonical(b)
    if not ca or not cb:
        return False
    return ca == cb or ca.startswith(cb) or cb.startswith(ca)


def _probe_form(name: str) -> str:
    """Like `canonical`, but keeps the ampersand.

    Comparison and probing need opposite treatments of "&". The suggest
    endpoint matches a literal prefix of the string the CFPB stores, and it
    stores "M&T BANK CORPORATION". Searching "m and t bank" returns nothing
    while "m&t bank" returns the company, so the probe has to look like the
    stored name even though the comparison afterwards must not.
    """
    cleaned = _SUFFIXES.sub(" ", name or "")
    cleaned = re.sub(r"[^a-z0-9& ]", " ", cleaned.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return re.sub(r"\s*&\s*$", "", cleaned).strip()


def probes_for(name: str, limit: int = 4) -> list[str]:
    """Progressively shorter prefixes of a name, longest first.

    Two families are tried: the ampersand-preserving form, which is what the
    CFPB actually stores, and the canonical form, which covers the reverse
    spelling. A legal name longer than the CFPB's own matches nothing until the
    extra words are dropped, which is why the prefixes shorten:
    "jpmorgan chase bank" finds no company because the CFPB files it as
    "JPMORGAN CHASE & CO." and the word "bank" runs past the end.
    """
    out: list[str] = []
    for text in (_probe_form(name), canonical(name)):
        if not text:
            continue
        words = text.split()
        for i in range(len(words), 0, -1):
            probe = " ".join(words[:i])
            # Anything shorter than three characters matches far too much of
            # the database to be worth a request.
            if len(probe) >= 3 and probe not in out:
                out.append(probe)
    return out[:limit]


async def resolve_company(
    name: str,
    alt_names: list[str] | None = None,
    slog: SourceLog | None = None,
) -> str | None:
    """Map an institution onto the exact string the CFPB files it under.

    Tries the charter name first, then any alternates such as the FDIC-reported
    holding company. Many banks file with the CFPB under a parent name that
    shares no words with the charter name at all: M&T Bank is chartered as
    "Manufacturers and Traders Trust Company" and no prefix of that will ever
    reach "M&T BANK CORPORATION".

    Returns None when nothing resolves, which for a small community bank is
    the ordinary case and must not be read as a clean record.
    """
    candidates_to_try = [name] + [a for a in (alt_names or []) if a]

    seen_probes: set[str] = set()
    for candidate_name in candidates_to_try:
        for probe in probes_for(candidate_name):
            if probe in seen_probes:
                continue
            seen_probes.add(probe)

            suggestions = await fetch_json(
                "cfpb",
                ENDPOINTS["cfpb_suggest"],
                params={"text": probe},
                ttl=TTL["cfpb"],
                slog=slog,
            )
            if not isinstance(suggestions, list) or not suggestions:
                continue

            for suggestion in suggestions:
                if names_match(candidate_name, suggestion):
                    return suggestion

    return None


def unmatched_profile(bank_name: str, since: str) -> dict[str, Any]:
    """The record returned when no CFPB company matches. Deliberately carries
    None rather than 0 so nothing downstream can mistake it for a clean record."""
    return {
        "matched": False,
        "company_queried": bank_name,
        "company_matched": None,
        "complaints": None,
        "origination_complaints": None,
        "timely_response_rate": None,
        "since": since,
        "note": (
            "No CFPB record matched this name. Either the institution has no "
            "complaints on file, or the CFPB files it under a name that does not "
            "resemble its charter or holding-company name."
        ),
    }


async def complaint_profile(
    bank_name: str,
    purpose: str,
    alt_names: list[str] | None = None,
    since: str = "2023-01-01",
    slog: SourceLog | None = None,
) -> dict[str, Any] | None:
    """Complaint record for one institution.

    Four distinct outcomes, kept distinct on purpose:
      None                     the source itself was unreachable
      matched False            no CFPB company matches this name
      matched True, count 0    the company exists with no complaints in range
      matched True, count > 0  a real record

    A single request carries both numbers: `hits.total` gives the product
    total, and the issue aggregation in the same response is summed locally to
    give the origination-stage subset. Filtering by issue upstream would need a
    second round trip per bank for no extra information.
    """
    if not bank_name:
        return None

    resolved = await resolve_company(bank_name, alt_names, slog)
    if resolved is None:
        return unmatched_profile(bank_name, since)

    params: dict[str, Any] = {
        "size": 0,
        "company": resolved,
        "date_received_min": since,
    }
    product = PRODUCT_FILTER.get(purpose)
    if product:
        params["product"] = product

    data = await fetch_json(
        "cfpb", ENDPOINTS["cfpb"], params=params, ttl=TTL["cfpb"], slog=slog
    )
    if not data or "hits" not in data:
        return None

    total = (data.get("hits", {}).get("total") or {}).get("value", 0)
    aggs = data.get("aggregations", {})

    timely_buckets = (aggs.get("timely", {}).get("timely", {}) or {}).get("buckets", [])
    yes = sum(b.get("doc_count", 0) for b in timely_buckets if b.get("key") == "Yes")
    no = sum(b.get("doc_count", 0) for b in timely_buckets if b.get("key") == "No")
    answered = yes + no

    origination = count_origination(aggs, purpose)

    return {
        "matched": True,
        "company_queried": bank_name,
        "company_matched": resolved,
        "complaints": total,
        "origination_complaints": origination,
        "timely_response_rate": round(yes / answered, 4) if answered else None,
        "since": since,
        "product_filter": product or "all products",
    }


def count_origination(aggregations: dict[str, Any], purpose: str) -> int | None:
    """Sum the issue buckets that describe getting a loan rather than repaying one.

    Returns None when the purpose has no defined origination issues or the
    aggregation is absent, so 'not measured' stays distinct from 'zero'.
    """
    wanted = ORIGINATION_ISSUES.get(purpose)
    if not wanted:
        return None

    buckets = (aggregations.get("issue", {}).get("issue", {}) or {}).get("buckets", [])
    if not buckets:
        return None

    return sum(b.get("doc_count", 0) for b in buckets if b.get("key") in wanted)
