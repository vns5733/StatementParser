"""Ad-hoc check of the ledger-scope wiring behind the four-tab layout.

The card view used to be a separate component that forced accountSources and
cardIds itself. It is now the sidebar's Spend Basis plus the card picker, so the
scope has to behave identically driven from Filters. Everything here asserts
what Decision 17 / 23 require of each basis.
"""
import os
import warnings

os.environ.pop("SSLKEYLOGFILE", None)
warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402

c = TestClient(app)
meta = c.get("/api/transactions/meta").json()
cards = meta["cards"]


def kpis(**q):
    return c.get("/api/transactions/kpis", params=q).json()


both = kpis(spend_basis="all")
bank = kpis(spend_basis="bank_only")
card = kpis(spend_basis="card_only")
one = next(x for x in cards if x["Card_Name"] == "Amazon Pay")
one_card = kpis(spend_basis="card_only", card_ids=one["Card_ID"])


def show(name, d):
    print(
        f"{name:20} debits={d['total_debits']:>14,.0f} credits={d['total_credits']:>14,.0f} "
        f"spend={d['total_spend_debits']:>14,.0f} setl_deb={d['settlement_debits']:>11,.0f} "
        f"setl_cred={d['settlement_credits']:>11,.0f} rows={d['filtered_count']:>6}"
    )


show("combined", both)
show("bank only", bank)
show("card only", card)
show(f"card only / {one['Card_Name']}", one_card)

# The invariant that actually matters: each basis keeps the half of the card
# payment that is genuinely its own outflow/inflow, and only the combined view
# drops both. So combined must equal the sum of the two single-ledger views,
# minus exactly the settlement half that double counting would otherwise add.
TOL = 1.0
checks = [
    (
        "combined credits == bank + card - the card settlement half",
        abs(both["total_credits"] - (bank["total_credits"] + card["total_credits"]
                                      - both["settlement_credits"])) < TOL,
    ),
    (
        "combined debits == bank + card - the bank settlement half",
        abs(both["total_debits"] - (bank["total_debits"] + card["total_debits"]
                                    - both["settlement_debits"])) < TOL,
    ),
    (
        "combined SPEND excludes both halves (no double count)",
        abs(both["total_spend_debits"]
            - (bank["total_spend_debits"] + card["total_spend_debits"])) < TOL,
    ),
    ("bank-only keeps the bank half as outflow",
     bank["settlement_credits"] == 0 and bank["settlement_debits"] > 0),
    ("card-only keeps the card half as inflow",
     card["settlement_debits"] == 0 and card["settlement_credits"] > 0),
    ("card-only spend excludes the bill payment (it is not a purchase)",
     abs(card["total_spend_debits"] - card["total_debits"]) < TOL
     and card["spend_count"] < card["filtered_count"]),
    ("bank-only spends less than it debits (settlement is out of spend)",
     bank["total_spend_debits"] < bank["total_debits"]),
    ("card rows all carry Account_Source=CREDIT_CARD",
     all(r["Account_Source"] == "CREDIT_CARD"
         for r in c.get("/api/transactions",
                        params={"spend_basis": "card_only", "page_size": 200}).json()["data"])),
    ("card_ids is a strict subset of card_only",
     0 < one_card["filtered_count"] < card["filtered_count"]),
    ("single-card spend is a subset of all-card spend",
     one_card["total_spend_debits"] <= card["total_spend_debits"]),
]

# card_ids narrows CARD rows and is inert on bank rows (their Card_ID is NULL).
# Under the combined basis it therefore leaves only that one card, and it leaves
# only the NON-settlement rows, because the combined view is the one scope that
# hides settlements. So the expected count is the card-only count less that
# card's settlement rows -- not the card-only count, and not the combined count.
combined_with_card = kpis(spend_basis="all", card_ids=one["Card_ID"])
checks.append((
    "card_ids narrows to one card, minus its settlements (combined hides them)",
    abs(combined_with_card["filtered_count"]
        - (one_card["filtered_count"] - one_card["settlement_count"])) < TOL
    and combined_with_card["filtered_count"] < both["filtered_count"],
))

print()
for name, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
print()
print("FAILURES:", sum(1 for _, ok in checks if not ok))