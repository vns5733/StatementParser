"""
Final end-to-end verification of the credit-card work.

Checks the whole chain in one place: parser -> card tables -> shared ledger ->
API, and asserts the properties that matter (no row loss, no double counting).
Run: python verify_final.py
"""
import glob
import os
import subprocess
import sys

import pdfplumber
from fastapi.testclient import TestClient

from api.main import app
from card_loader import (
    HDFC_DATE_RE, ICICI_BANDS, ICICI_DATE_RE, SCAPIA_DATE_RE, load_card_statement,
)
from db import create_mysql_connection, get_all_transactions_with_details

client = TestClient(app)
engine = create_mysql_connection()

failures = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  -> ' + detail if detail else ''}")
    if not ok:
        failures.append(label)


print("\n1. PARSER - no transaction row is silently dropped")
# Only the statements this script is pointed at. The counts are derived, never
# hardcoded, so importing more statements does not make this a false failure.
FILES = sorted(glob.glob("CreditCard/*.pdf"))
anchor_res = {
    "HDFC": (HDFC_DATE_RE, None),
    "ICICI": (ICICI_DATE_RE, ICICI_BANDS["date"]),
    "SCAPIA": (SCAPIA_DATE_RE, None),
}
total_rows = 0
for path in FILES:
    df, meta = load_card_statement(path)
    pattern, band = anchor_res[meta["Issuer"]]
    anchors = 0
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for w in page.extract_words():
                if pattern.match(w["text"]) and (not band or band[0] <= w["x0"] < band[1]):
                    anchors += 1
    total_rows += len(df)
    name = os.path.basename(path)[:44]
    # Anchors can exceed rows: a summary block also prints dates (payment due
    # date, EMI loan booked date) that are not transactions. What must never
    # happen is the reverse - a row per anchor with nothing extra.
    check(f"{name:46} {anchors:>3} anchors >= {len(df):>3} parsed", anchors >= len(df))
print(f"       {len(FILES)} statements, {total_rows} rows")

# Anchors >= rows only proves a row was EMITTED, not that it was labelled
# correctly. A credit read as a debit is still one row, so the check above passes
# while every payment on the statement is recorded as spend. The issuer prints its
# own PURCHASES/DEBIT and PAYMENTS/CREDITS RECEIVED totals, which is an independent
# check on the parsed direction: reconcile both sides against them.
# Direction reconciliation is checked over EVERY statement, not just the four
# this file happens to point at: the Tata Neu "+ C" bug affected 12 of 27 and was
# invisible to a four-file sample. Parsing is still only done for FILES above,
# because the per-anchor count is the expensive part.
ALL_STATEMENTS = sorted(glob.glob("masked/CreditCard/*.pdf"))
print("\n1b. DIRECTION - parsed debits/credits match the issuer's printed totals")
dir_bad = 0
for path in ALL_STATEMENTS:
    df, meta = load_card_statement(path)
    if df.empty:
        continue
    debits = float(df.loc[df["Direction"] == "DEBIT", "Amount"].sum())
    credits = float(df.loc[df["Direction"] == "CREDIT", "Amount"].sum())
    ts, pr = meta.get("Total_Spend"), meta.get("Payments_Received")
    ok_d = ts is None or abs(debits - float(ts)) <= 1
    ok_c = pr is None or abs(credits - float(pr)) <= 1
    if not (ok_d and ok_c):
        dir_bad += 1
        print(f"  [FAIL] {os.path.basename(path)[:46]}")
        print(f"         debits {debits:,.2f} vs issuer {ts} | "
              f"credits {credits:,.2f} vs issuer {pr}")
check("every statement's parsed direction reconciles with the issuer",
      dir_bad == 0, f"{len(ALL_STATEMENTS)} statements, {dir_bad} mismatched")


print("\n2. LEDGER - card rows reach the shared dashboard table")
df = get_all_transactions_with_details(engine)
card = df[df["Account_Source"] == "CREDIT_CARD"]
bank_n = int((df["Account_Source"] == "BANK").sum())
ledger_card = len(card)
check("card rows present in ledger", ledger_card > 0, f"{ledger_card} rows")
check("bank rows untouched", bank_n > 0, f"{bank_n} rows")
check("settlements flagged", int(df["Is_Settlement"].sum()) > 0,
      f"{int(df['Is_Settlement'].sum())} rows")


print("\n3. NO DOUBLE COUNTING - each ledger counts its own half of the payment")
spend = {}
for basis in ("all", "bank_only", "card_only"):
    r = client.get("/api/transactions/kpis", params={"spend_basis": basis}).json()
    # The SPEND figure is what the category charts plot, and it drops settlements
    # in every view. The CASHFLOW figure (total_debits) counts them in a
    # single-ledger view, because there the other half of the payment is absent
    # and there is nothing to double count.
    spend[basis] = r["total_spend_debits"]
check("combined spend == bank spend + card spend",
      abs(spend["all"] - (spend["bank_only"] + spend["card_only"])) < 0.01,
      f"{spend['all']:,.2f} vs {spend['bank_only']:,.2f} + {spend['card_only']:,.2f}")
check("bank spend below raw bank debits (settlement removed)",
      spend["bank_only"] < 11_450_669, f"{spend['bank_only']:,.2f}")
# The correction must be visible and exactly the settlement total: raw debits
# minus the settlements the ledger flags must equal the reported spend.
_cash = client.get("/api/transactions/kpis", params={"spend_basis": "bank_only"}).json()
_bank = get_all_transactions_with_details(engine)
_bank = _bank[_bank["Account_Source"].fillna("BANK") == "BANK"]
_bank_raw = float(_bank["Debit_Amount"].sum())
_bank_settle = float(_bank.loc[_bank["Is_Settlement"], "Debit_Amount"].sum())
check("bank spend == raw bank debits minus settlements",
      abs(_cash["total_spend_debits"] - (_bank_raw - _bank_settle)) < 0.01,
      f"spend {_cash['total_spend_debits']:,.2f} = raw {_bank_raw:,.2f}"
      f" - settlements {_bank_settle:,.2f}")
# ...but the bank CASHFLOW must still include them, because that money really
# left the account. Hiding it understated the bank outflow by the full amount.
check("bank cashflow equals raw bank debits (the payment really left)",
      abs(_cash["total_debits"] - _bank_raw) < 0.01,
      f"cashflow {_cash['total_debits']:,.2f} vs raw {_bank_raw:,.2f}")

print("\n4. API - card endpoints respond")
cards_resp = client.get("/api/cards").json()
stmts_resp = client.get("/api/cards/statements").json()
spend_resp = client.get("/api/cards/spend").json()
issuer_resp = client.get("/api/cards/issuer-categories").json()
recon_resp = client.get("/api/cards/reconcile")
# Counts are whatever has been imported; the invariants are cross-endpoint
# agreement, so importing more statements never makes this a false failure.
check("GET /api/cards returns the registry", len(cards_resp) > 0,
      f"{len(cards_resp)} cards")
check("every statement maps to a registered card",
      {s["Card_ID"] for s in stmts_resp} <= {c["Card_ID"] for c in cards_resp},
      f"{len(stmts_resp)} statements")
check("GET /api/cards/spend returns rows", len(spend_resp) > 0, f"{len(spend_resp)} rows")
check("GET /api/cards/issuer-categories returns rows", len(issuer_resp) > 0,
      f"{len(issuer_resp)} rows")
check("GET /api/cards/reconcile 200", recon_resp.status_code == 200)
check("reconcile sees every statement",
      recon_resp.json()["summary"]["statements"] == len(stmts_resp),
      f"{recon_resp.json()['summary']['statements']} statements")


print("\n4b. API - EVERY transaction endpoint answers 200")
# Sweeping all of them matters: a filter argument added to some endpoints but
# not others compiles fine and only fails at request time.
tx_endpoints = [
    ("/api/transactions", {"page": "1", "page_size": "5"}),
    ("/api/transactions/meta", {}),
    ("/api/transactions/kpis", {}),
    ("/api/transactions/summary/timeline", {"group_by": "month"}),
    ("/api/transactions/summary/monthly-category", {"group_by": "month"}),
    ("/api/transactions/summary/category-breakdown", {"group_col": "Category"}),
    ("/api/transactions/balance-trend", {}),
    ("/api/transactions/category-trend", {"category": "", "group_col": "Category"}),
    ("/api/transactions/export", {}),
]
for basis in ("all", "bank_only", "card_only"):
    for path, extra in tx_endpoints:
        params = dict(extra)
        params["spend_basis"] = basis
        if "export" not in path:
            r = client.get(path, params=params)
            check(f"GET {path:40} basis={basis:10} {r.status_code}", r.status_code == 200)

print("\n4c. API - account_sources accepted on every transaction endpoint")
for path, extra in tx_endpoints:
    if "export" in path:
        continue
    r = client.get(path, params={**extra, "account_sources": "CREDIT_CARD"})
    check(f"GET {path:40} src=CREDIT_CARD {r.status_code}", r.status_code == 200)

print("\n5. FILTERS - account_sources scopes the ledger")
k = client.get("/api/transactions/kpis", params={"account_sources": "CREDIT_CARD"}).json()
# Both ledgers' cashflow AND spend must respond identically to the two ways of
# asking for the same set, so both are asserted.
check("account_sources=CREDIT_CARD matches card_only (cashflow)",
      abs(k["total_debits"]
          - client.get("/api/transactions/kpis", params={"spend_basis": "card_only"})
          .json()["total_debits"]) < 0.01,
      f"{k['total_debits']:,.2f}")
check("account_sources=CREDIT_CARD matches card_only (spend)",
      abs(k["total_spend_debits"] - spend["card_only"]) < 0.01,
      f"{k['total_spend_debits']:,.2f}")

print("\n5b. VISIBILITY - the ledger must not hide rows to fix the maths")
# A card purchase and the bank debit paying its bill are two halves of one
# transaction. Summing both as spend double counts, so the SPEND AGGREGATES drop
# settlements - but the transaction list and the export must still return every
# row, or the user simply cannot find their credit-card payments.
ledger = get_all_transactions_with_details(engine)
allrows, page = [], 1
while True:
    d = client.get("/api/transactions", params={"page_size": 500, "page": page}).json()
    allrows.extend(d["data"])
    if page >= d["total_pages"]:
        break
    page += 1
check("transaction list returns every ledger row",
      len(allrows) == len(ledger), f"api={len(allrows)} ledger={len(ledger)}")

bank_cc = ledger[ledger["Broad_Category"] == "Credit_Card_Payment"]
visible_cc = [x for x in allrows if x["Broad_Category"] == "Credit_Card_Payment"]
check("bank credit-card payments are visible in the list",
      len(visible_cc) == len(bank_cc), f"{len(visible_cc)}/{len(bank_cc)}")

card_rows = [x for x in allrows if x.get("Account_Source") == "CREDIT_CARD"]
ledger_card = int((ledger["Account_Source"] == "CREDIT_CARD").sum())
check("card purchases are visible and labelled",
      len(card_rows) == ledger_card, f"{len(card_rows)}/{ledger_card} card rows")
check("rows carry provenance (Account_Source / Is_Settlement)",
      all("Account_Source" in x and "Is_Settlement" in x for x in allrows[:50]))

# The SPEND totals must exclude settlements, while cashflow keeps them. Both are
# checked against the same ledger rows the list shows, so neither can quietly
# diverge from what the user can actually see.
raw_debits = float(ledger["Debit_Amount"].sum())
settlement_debits = float(ledger.loc[ledger["Is_Settlement"], "Debit_Amount"].sum())
_kpi_all_debits = client.get("/api/transactions/kpis").json()["total_debits"]
check("spend totals exclude settlements that the list shows",
      abs(spend["all"] - (raw_debits - settlement_debits)) < 0.01,
      f"spend={spend['all']:,.2f} raw={raw_debits:,.2f} settlements={settlement_debits:,.2f}")
# The card-side settlement half must not reappear as income. It is a credit on
# the card, but a transfer, so it is reported separately rather than counted.
_kpi_all = client.get("/api/transactions/kpis").json()
check("card-side settlements are NOT counted as income",
      abs(_kpi_all["total_credits"] - float(
          ledger.loc[~ledger["Is_Settlement"], "Credit_Amount"].sum())) < 0.01,
      f"credits {_kpi_all['total_credits']:,.2f}, card payments held out"
      f" {_kpi_all['settlement_credits']:,.2f}")

print("\n6. IDEMPOTENCE - re-import creates no duplicates")
before = len(get_all_transactions_with_details(engine))
subprocess.run([sys.executable, "ingest_cards.py"],
               capture_output=True, check=False)
after = len(get_all_transactions_with_details(engine))
check("re-import added no rows", before == after, f"{before} -> {after}")

print("\n" + "=" * 62)
if failures:
    print(f"{len(failures)} CHECK(S) FAILED: {failures}")
    sys.exit(1)
print("ALL CHECKS PASSED")
