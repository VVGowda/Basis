"""Ten realistic applicants, run end to end and printed as the user would read them.

This is the pass that catches what unit tests cannot: an answer that is
arithmetically correct and still misleading, contradictory or cruel. Read the
output as if you were the applicant.

    venv\\Scripts\\python.exe scripts\\scenarios.py
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = "http://127.0.0.1:8767"

SCENARIOS = [
    (
        "Solid first-time buyer, Baltimore",
        {"purpose": "home_purchase", "annual_income": 95000, "monthly_debt": 450,
         "credit_score": 712, "loan_amount": 340000, "down_payment": 60000,
         "asset_value": 400000, "zip_code": "21201"},
    ),
    (
        "Thin credit, small deposit, high debt",
        {"purpose": "home_purchase", "annual_income": 52000, "monthly_debt": 900,
         "credit_score": 565, "loan_amount": 210000, "down_payment": 8000,
         "asset_value": 218000, "zip_code": "21201"},
    ),
    (
        "Veteran, no deposit at all, Texas",
        {"purpose": "home_purchase", "annual_income": 88000, "monthly_debt": 200,
         "credit_score": 700, "loan_amount": 330000, "down_payment": 0,
         "asset_value": 330000, "zip_code": "78701", "military_service": True},
    ),
    (
        "Rural buyer on a modest income, Iowa",
        {"purpose": "home_purchase", "annual_income": 61000, "monthly_debt": 260,
         "credit_score": 668, "loan_amount": 185000, "down_payment": 0,
         "asset_value": 185000, "zip_code": "50501", "rural_property": True},
    ),
    (
        "High earner, expensive market, San Francisco",
        {"purpose": "home_purchase", "annual_income": 410000, "monthly_debt": 1800,
         "credit_score": 780, "loan_amount": 1250000, "down_payment": 350000,
         "asset_value": 1600000, "zip_code": "94110"},
    ),
    (
        "Fair credit buying a used car, Detroit",
        {"purpose": "auto", "annual_income": 68000, "monthly_debt": 300,
         "credit_score": 640, "loan_amount": 28000, "down_payment": 3000,
         "asset_value": 31000, "zip_code": "48226"},
    ),
    (
        "Consolidating card debt with a personal loan, Phoenix",
        {"purpose": "personal", "annual_income": 58000, "monthly_debt": 780,
         "credit_score": 655, "loan_amount": 22000, "zip_code": "85004"},
    ),
    (
        "Income in rupees, US personal loan",
        {"purpose": "personal", "annual_income": 2400000, "income_currency": "INR",
         "monthly_debt": 12000, "credit_score": 690, "loan_amount": 800000,
         "zip_code": "07302"},
    ),
    (
        "Small business owner seeking SBA, Miami",
        {"purpose": "small_business", "annual_income": 145000, "monthly_debt": 1100,
         "credit_score": 690, "loan_amount": 250000, "down_payment": 30000,
         "zip_code": "33101", "business_operating": True},
    ),
    (
        "Refinancing, very little equity, Ohio",
        {"purpose": "home_refinance", "annual_income": 74000, "monthly_debt": 620,
         "credit_score": 705, "loan_amount": 232000, "down_payment": 0,
         "asset_value": 240000, "zip_code": "43215"},
    ),
]


def post(body):
    req = urllib.request.Request(
        f"{BASE}/api/match",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.load(r), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode()[:300]}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def money(n):
    return f"${n:,.0f}" if n is not None else "n/a"


def show(title, body):
    print("\n" + "=" * 78)
    print(f"  {title}")
    print("=" * 78)

    data, err = post(body)
    if err:
        print(f"  REQUEST FAILED  {err}")
        return False

    a, e = data["applicant"], data["eligibility"]
    loc = data["location"]

    conv = a["currency_conversion"]
    if conv.get("converted"):
        print(f"  Currency   {conv['currency']} at {conv['rate']} -> income {money(a['annual_income_usd'])}, "
              f"loan {money(a['loan_amount_usd'])}, debt {money(a['monthly_debt_usd'])}/mo")

    print(f"  Applicant  {a['credit_band']} credit ({a['credit_score']}), "
          f"{money(a['monthly_income_usd'])}/mo income, {money(a['monthly_debt_usd'])}/mo debt")
    print(f"  Location   {loc['city'] + ', ' + loc['state_abbr'] if loc else 'not resolved'}")
    print(f"  Benchmark  {data['benchmark']['rate']}%"
          f"{'  (ESTIMATED, source down)' if data['benchmark']['estimated'] else ''}")

    print(f"\n  Programs   {e['eligible_count']} of {len(e['programs'])} open")
    for p in e["programs"]:
        est = p["estimate"]
        flag = {"likely_eligible": "YES", "possible": "MAYBE", "not_eligible": "no "}[p["verdict"]]
        print(f"    [{flag}] {p['name']:<32} {money(est['total_monthly']):>10}/mo @ {est['rate_pct']:>5}%"
              f"   DTI {est['dti_pct']}%")
        for c in p["checks"]:
            if c["status"] != "pass":
                print(f"           {c['status'].upper():<5} {c['label']}: {c['detail']}")

    af = e.get("affordability") or {}
    if af.get("max_loan_usd"):
        print(f"\n  Ceiling    {money(af['max_loan_usd'])} via {af['program_name']} "
              f"({money(af['monthly_budget_usd'])}/mo of room)")
    else:
        print("\n  Ceiling    none, no program can carry any loan at these numbers")

    L = data["lenders"]
    lenders = L.get("lenders", [])
    if lenders:
        matched = sum(1 for b in lenders if (b.get("complaints") or {}).get("matched"))
        print(f"\n  Lenders    {len(lenders)} shown, {matched} with a CFPB record")
        for b in lenders[:4]:
            c = b.get("complaints") or {}
            rate = b.get("complaint_rate")
            note = (f"{rate['per_billion_assets']}/B" if rate else "no CFPB match")
            print(f"    {b['name'][:44]:<46} {b['scale']:<10} zip={b['branches_in_zip']}  {note}")
    else:
        print(f"\n  Lenders    none. {L.get('note', '')[:100]}")

    fund = data.get("funding_estimate")
    if fund:
        print(f"  Funding    {fund['date']} ({fund['typical_business_days']} business days)")

    failed = [s["source"] for s in data["sources_used"] if not s["ok"]]
    if failed:
        print(f"  DEGRADED   {sorted(set(failed))}")

    return True


def main():
    ok = 0
    for title, body in SCENARIOS:
        if show(title, body):
            ok += 1

    print("\n" + "=" * 78)
    print(f"  {ok} of {len(SCENARIOS)} scenarios completed")
    print("=" * 78 + "\n")
    return 0 if ok == len(SCENARIOS) else 1


if __name__ == "__main__":
    sys.exit(main())
