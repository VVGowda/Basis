"""Tests for institution name matching.

These exist because two separate name-matching bugs shipped in this project and
no test caught either one:

  1. The CFPB stores names in upper case and filters on an exact term match.
     Passing the FDIC's title-case name returned zero for every bank, which
     renders identically to a spotless complaint record.
  2. FDIC writes "First United Bank & Trust"; the CFPB writes "FIRST UNITED
     BANK AND TRUST COMPANY". Discarding "&" as punctuation made one bank look
     like two, and a real complaint record was reported as absent.

Both failed silently and produced a flattering wrong answer rather than an
error. Every pair below is a real name observed from the live APIs.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.providers.cfpb import (
    ORIGINATION_ISSUES,
    _probe_form,
    canonical,
    count_origination,
    names_match,
    probes_for,
    unmatched_profile,
)


# --------------------------------------------------------------------------
# canonical()
# --------------------------------------------------------------------------

def test_case_is_irrelevant():
    assert canonical("Bank of America") == canonical("BANK OF AMERICA")


def test_ampersand_normalises_to_and():
    # The bug: "&" was dropped as punctuation while a literal "AND" survived.
    assert canonical("First United Bank & Trust") == canonical("First United Bank and Trust")
    assert "and" in canonical("M&T Bank")


def test_corporate_suffixes_are_stripped():
    for suffix in [
        "Acme Bank, National Association",
        "Acme Bank, N.A.",
        "Acme Bank Corporation",
        "Acme Bank Inc",
        "Acme Bank Company",
        "Acme Bancorp",
        "Acme Bancshares",
    ]:
        assert canonical(suffix).startswith("acme"), suffix


def test_punctuation_and_spacing_do_not_matter():
    assert canonical("  Acme,  Bank.  ") == canonical("Acme Bank")


def test_trailing_conjunction_is_trimmed():
    # "Wells Fargo & Company" loses "Company" and must not keep a dangling "and".
    assert canonical("Wells Fargo & Company") == "wells fargo"


def test_empty_input_is_safe():
    assert canonical("") == ""
    assert canonical(None) == ""
    assert canonical("   ,,,  ") == ""


def test_canonical_is_idempotent():
    for name in ["Bank of America, National Association", "M&T Bank Corporation", "PNC Bank N.A."]:
        assert canonical(canonical(name)) == canonical(name)


# --------------------------------------------------------------------------
# names_match() - every pair observed from the live FDIC and CFPB APIs
# --------------------------------------------------------------------------

REAL_PAIRS = [
    ("Bank of America, National Association", "BANK OF AMERICA, NATIONAL ASSOCIATION"),
    ("JPMorgan Chase Bank, National Association", "JPMORGAN CHASE & CO."),
    ("PNC Bank, National Association", "PNC Bank N.A."),
    ("First United Bank & Trust", "FIRST UNITED BANK AND TRUST COMPANY"),
    ("Wells Fargo Bank, National Association", "WELLS FARGO & COMPANY"),
    ("Truist Bank", "TRUIST FINANCIAL CORPORATION"),
    ("M&T Bank Corporation", "M&T BANK CORPORATION"),
]


def test_real_name_pairs_all_reconcile():
    for fdic_name, cfpb_name in REAL_PAIRS:
        assert names_match(fdic_name, cfpb_name), f"{fdic_name!r} vs {cfpb_name!r}"


def test_different_banks_do_not_match():
    # The suggest endpoint is a prefix matcher, so these are the collisions
    # that a looser rule would wrongly accept.
    for a, b in [
        ("First United Bank & Trust", "FIRSTBANK"),
        ("Bank of America, National Association", "BANK OF THE WEST"),
        ("Harbor Bank of Maryland", "HARBORONE BANCORP, INC."),
        ("Capital Bank", "CAPITAL ONE FINANCIAL CORPORATION"),
        ("Shore United Bank", "SHORE COMMUNITY BANK"),
    ]:
        assert not names_match(a, b), f"{a!r} wrongly matched {b!r}"


def test_match_is_symmetric():
    for a, b in REAL_PAIRS:
        assert names_match(a, b) == names_match(b, a)


def test_empty_names_never_match():
    assert not names_match("", "BANK OF AMERICA")
    assert not names_match("Bank of America", "")
    assert not names_match("", "")


# --------------------------------------------------------------------------
# probes_for()
# --------------------------------------------------------------------------

def test_probes_go_longest_first():
    probes = probes_for("JPMorgan Chase Bank, National Association")
    assert probes[0] == "jpmorgan chase bank"
    assert "jpmorgan chase" in probes


def test_probes_are_capped():
    assert len(probes_for("One Two Three Four Five Six Bank")) <= 4


def test_very_short_probes_are_dropped():
    # A probe of "m" would match a large share of the database.
    assert all(len(p) >= 3 for p in probes_for("M&T Bank Corporation"))


def test_probes_keep_the_ampersand():
    # The CFPB suggest endpoint stores "M&T BANK CORPORATION" and matches on a
    # literal prefix: "m&t bank" finds it, "m and t bank" finds nothing. The
    # probe therefore has to preserve "&" even though comparison must not.
    assert _probe_form("M&T BANK CORP") == "m&t bank"
    assert "m&t bank" in probes_for("M&T BANK CORP")


def test_probes_cover_both_spellings():
    # Both the "&" form and the "and" form are attempted, because the two
    # sources disagree about which one they store.
    probes = probes_for("M&T BANK CORP", limit=6)
    assert any("&" in p for p in probes)
    assert any("and" in p for p in probes)


def test_probe_form_trims_a_trailing_ampersand():
    # "Wells Fargo & Company" loses "Company" and must not keep a dangling "&".
    assert _probe_form("Wells Fargo & Company") == "wells fargo"


def test_probes_on_empty_name():
    assert probes_for("") == []


def test_jpmorgan_needs_the_backoff():
    # The full canonical name matches nothing upstream; the shorter one works.
    # If this ever becomes a single-probe lookup, JPMorgan silently goes missing.
    probes = probes_for("JPMorgan Chase Bank, National Association")
    assert len(probes) >= 2
    assert names_match(probes[1], "JPMORGAN CHASE & CO.")


# --------------------------------------------------------------------------
# unmatched vs zero - the distinction that caused the original bug
# --------------------------------------------------------------------------

def test_unmatched_profile_carries_none_not_zero():
    p = unmatched_profile("Rosedale Bank", "2023-01-01")
    assert p["matched"] is False
    assert p["complaints"] is None, "unmatched must never look like zero complaints"
    assert p["timely_response_rate"] is None
    assert p["note"]


# --------------------------------------------------------------------------
# count_origination()
# --------------------------------------------------------------------------

def aggs(buckets):
    return {"issue": {"issue": {"buckets": buckets}}}


def test_origination_sums_only_application_stage_issues():
    # Real bucket shape and real counts from Bank of America's mortgage record.
    payload = aggs([
        {"key": "Trouble during payment process", "doc_count": 780},
        {"key": "Struggling to pay mortgage", "doc_count": 521},
        {"key": "Applying for a mortgage or refinancing an existing mortgage", "doc_count": 355},
        {"key": "Closing on a mortgage", "doc_count": 199},
    ])
    assert count_origination(payload, "home_purchase") == 554


def test_origination_is_none_when_not_measurable():
    assert count_origination({}, "home_purchase") is None
    assert count_origination(aggs([{"key": "Getting a loan or lease", "doc_count": 5}]), "small_business") is None


def test_origination_zero_is_distinct_from_none():
    payload = aggs([{"key": "Trouble during payment process", "doc_count": 12}])
    assert count_origination(payload, "home_purchase") == 0


def test_every_purpose_has_an_origination_rule():
    from app.engine.programs import PURPOSES
    for purpose in PURPOSES:
        assert purpose in ORIGINATION_ISSUES, f"{purpose} has no origination issue set"


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
