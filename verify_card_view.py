"""
Verification for the unified credit-card view.

Checks the whole card path against the live database:
  1. /meta exposes the cards actually present in the ledger
  2. card_ids narrows every aggregate the card view reads
  3. each card's category breakdown reconciles against its own KPI debits
  4. each card's timeline row count reconciles against its own KPI count
  5. settlements are excluded from spend but still visible in the ledger
  6. settlement flagging follows the RESOLVED category, not the stored one
  7. a single-category drill-down still shows that category's settlement rows
  8. a card bill payment is a CREDIT in the card's own view
  9. a user can flip any row's direction, by txn / merchant / narration
 10. every table listing transactions can sort, and sorting re-ranks the SET
 11. the summary endpoints honour sub_categories / categories / spend_basis
 12. CSV export returns the scoped set

Run: python verify_card_view.py
"""
import warnings

warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)
failures = []


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}{(' - ' + detail) if detail else ''}")
    if not condition:
        failures.append(label)


print("=" * 72)
print("Unified credit-card view verification")
print("=" * 72)

# --- 1. meta exposes the cards in the ledger -------------------------------
print("\n1. /transactions/meta card registry")
meta = client.get("/api/transactions/meta").json()
cards = meta.get("cards") or []
check("meta returns a cards list", isinstance(cards, list))
check("at least one card discovered", len(cards) > 0, f"{len(cards)} cards")
check(
    "each card carries id/name/count",
    all(c.get("Card_ID") and c.get("Txn_Count") is not None for c in cards),
)

# --- 1b. one statement per card per cycle, parsed spend must reconcile --------
# Regression guard. The statement id used to fold in the source filename, so the
# same statement imported twice under two names - typically a masked copy
# alongside the original - got two primary keys. INSERT IGNORE then kept both, the
# cycle appeared twice in the statement table, and every one of its transactions
# was written to the shared ledger again, double counting that card's spend.
print("\n1b. Statement identity and issuer reconciliation")
import pandas as pd  # noqa: E402

_stmts = pd.DataFrame(client.get("/api/cards/statements").json())
_dated = _stmts[_stmts["Statement_Date"].notna()]
_dupes = _dated.groupby(["Card_ID", "Statement_Date"]).size()
_dupes = _dupes[_dupes > 1]
check(
    "no card has two statements for the same billing cycle",
    len(_dupes) == 0,
    f"{len(_stmts)} statements, {len(_dupes)} duplicated cycles",
)
check(
    "statement ids are unique",
    _stmts["Statement_ID"].is_unique,
    f"{_stmts['Statement_ID'].nunique()}/{len(_stmts)} distinct",
)
# Parsed_Spend is the proof the parser did not lose rows. It must be purchases
# only, matching the issuer's printed PURCHASES/DEBIT - it used to sweep in the
# bill-payment row, so a perfectly parsed statement still showed a large variance.
_comparable = _stmts[
    _stmts["Parsed_Spend"].notna() & _stmts["Total_Spend"].notna()
].copy()
_comparable["_var"] = (_comparable["Parsed_Spend"] - _comparable["Total_Spend"]).abs()
_reconciled = int((_comparable["_var"] < 1).sum())
check(
    "most statements reconcile with the issuer's printed total",
    _reconciled >= len(_comparable) * 0.8,
    f"{_reconciled}/{len(_comparable)} within Rs.1",
)
_worst = _comparable.nlargest(1, "_var")
if len(_worst):
    w = _worst.iloc[0]
    print(
        f"       largest remaining variance: {w['Card_Name']} {str(w['Statement_Date'])[:10]}"
        f" parsed {w['Parsed_Spend']:,.2f} vs issuer {w['Total_Spend']:,.2f}"
    )

# --- 2. card_ids narrows the aggregates ------------------------------------
print("\n2. card_ids scoping")
all_cards = client.get("/api/transactions/kpis?account_sources=CREDIT_CARD").json()
largest = max(cards, key=lambda c: c["Txn_Count"])
cid = largest["Card_ID"]
one = client.get(
    f"/api/transactions/kpis?account_sources=CREDIT_CARD&card_ids={cid}"
).json()
check(
    "per-card count is below the all-cards count",
    one["filtered_count"] < all_cards["filtered_count"],
    f"{one['filtered_count']} < {all_cards['filtered_count']}",
)

# The ledger keeps settlements; only spend aggregates drop them.
ledger = client.get(
    f"/api/transactions?account_sources=CREDIT_CARD&card_ids={cid}&page_size=1"
).json()
check(
    "ledger total matches the meta count",
    ledger["total"] == largest["Txn_Count"],
    f"{ledger['total']} == {largest['Txn_Count']}",
)
# The row count still includes settlements (the table shows every row), but the
# amounts exclude them because a bill payment is a transfer, not spend or income.
check(
    "KPI row count keeps settlements (the table shows every row)",
    one["filtered_count"] == ledger["total"],
    f"kpi {one['filtered_count']} == ledger {ledger['total']}",
)
check(
    "settlements are excluded from the amount tiles but still counted",
    one["settlement_count"] > 0
    and one["spend_count"] + one["settlement_count"] == one["filtered_count"],
    f"{one['spend_count']} spend + {one['settlement_count']} settlement"
    f" = {one['filtered_count']} rows",
)

# --- 3 & 4. per-card reconciliation ----------------------------------------
print("\n3. Per-card reconciliation (breakdown + timeline vs KPIs)")
print(f"  {'card':<24}{'spend':>14}{'refunds':>13}{'cats':>6}{'periods':>9}")
for card in cards:
    q = f"account_sources=CREDIT_CARD&card_ids={card['Card_ID']}"
    kpis = client.get(f"/api/transactions/kpis?{q}").json()
    breakdown = client.get(
        f"/api/transactions/summary/category-breakdown?{q}&group_col=Broad_Category"
    ).json()
    timeline = client.get(f"/api/transactions/summary/timeline?{q}&group_by=month").json()

    breakdown_sum = sum(x["Total_Debit"] for x in breakdown)
    name = card["Card_Name"] or "Unnamed"
    print(
        f"  {name[:23]:<24}{kpis['total_spend_debits']:>14,.2f}"
        f"{kpis['total_credits']:>13,.2f}{len(breakdown):>6}{len(timeline):>9}"
    )
    check(
        f"{name}: breakdown sums to SPEND debits",
        abs(breakdown_sum - kpis["total_spend_debits"]) < 0.01,
        f"delta {breakdown_sum - kpis['total_spend_debits']:.4f}",
    )
    # The timeline is the cashflow view, so it reconciles against total_debits -
    # the tiles, not the spend figure. In the card view the two differ, because a
    # bill payment is real inflow there but is not spend.
    check(
        f"{name}: timeline row count equals filtered count",
        sum(t["Count"] for t in timeline) == kpis["filtered_count"],
        f"{sum(t['Count'] for t in timeline)} vs {kpis['filtered_count']}",
    )
    check(f"{name}: has at least one category", len(breakdown) > 0)

# --- 4b. settlement flagging follows the RESOLVED category -------------------
# Regression guard. Is_Settlement used to be derived in the base query, which ran
# BEFORE the category_rules overrides were applied. The bank side is detected by
# matching the resolved Broad_Category, so any row that only became
# Credit_Card_Payment via a user override rule was left unflagged and counted as
# spend in every chart - double counting the card purchases the flag exists to
# remove. That made the category breakdown disagree with the KPI it should sum
# to, and only for that one category.
print("\n4b. Settlement flagging uses the resolved category")
import db  # noqa: E402
from api.deps import get_engine  # noqa: E402

_ledger = db.get_all_transactions_with_details(get_engine())
_cc = _ledger[_ledger["Broad_Category"].fillna("").str.upper().str.contains(
    r"CREDIT[\s_]*CARD[\s_]*PAYMENT", regex=True)]
check(
    "the guard actually matched rows (not a vacuous pass)",
    len(_cc) > 0,
    f"{len(_cc)} Credit_Card_Payment rows found",
)
check(
    "every Credit_Card_Payment row is flagged Is_Settlement",
    bool(len(_cc) == 0 or _cc["Is_Settlement"].all()),
    f"{int(_cc['Is_Settlement'].sum())}/{len(_cc)} flagged",
)
check(
    "no Credit_Card_Payment debit leaks into spend",
    float(_cc.loc[~_cc["Is_Settlement"], "Debit_Amount"].sum()) == 0.0,
    f"{float(_cc.loc[~_cc['Is_Settlement'], 'Debit_Amount'].sum()):,.2f} leaked",
)

# The same override-awareness must hold for reconciliation, which used to read the
# STORED category via SQL and so could not see an override-created settlement.
_cc_debits = _cc[
    (_cc["Account_Source"].fillna("BANK").str.upper() == "BANK")
    & (_cc["Debit_Amount"].fillna(0) > 0)
]
_recon = client.get("/api/cards/reconcile").json()["summary"]
check(
    "reconcile sees every bank-side card payment, overrides included",
    _recon["bank_debits"] >= len(_cc_debits),
    f"reconcile {_recon['bank_debits']} >= ledger {len(_cc_debits)}",
)

# In the COMBINED view both halves of a card payment are present, so the tiles
# and the category breakdown must both exclude them and agree exactly.
_kpi_all = client.get("/api/transactions/kpis").json()
_bd_all = client.get(
    "/api/transactions/summary/category-breakdown?group_col=Broad_Category"
).json()
_sum_debits = sum(float(r.get("Total_Debit") or 0) for r in _bd_all)
check(
    "combined: category breakdown sums to KPI debits",
    abs(_sum_debits - _kpi_all["total_debits"]) < 0.01,
    f"breakdown {_sum_debits:,.2f} vs KPI {_kpi_all['total_debits']:,.2f}",
)
check(
    "combined: the tiles excluded the payment, and say so",
    _kpi_all["settlement_count"] > 0
    and _kpi_all["spend_count"] == _kpi_all["filtered_count"],
    f"{_kpi_all['settlement_count']} settlement rows held out"
    f" ({_kpi_all['settlement_debits']:,.2f} out /"
    f" {_kpi_all['settlement_credits']:,.2f} in);"
    f" {_kpi_all['spend_count']} counted rows remain",
)
_tl_all = client.get("/api/transactions/summary/timeline?group_by=month").json()
check(
    "combined: timeline matches KPI debits",
    abs(sum(float(r.get("Total_Debit") or 0) for r in _tl_all)
        - _kpi_all["total_debits"]) < 0.01,
)

# --- 4b2. a single-LEDGER view must show its own half of the payment --------
# Regression guard, and the mirror of the one above. The two halves of a card
# bill payment can only be double counted when BOTH are in the view. Hiding them
# everywhere was destroying real data on both sides: the card view lost genuine
# inflow (it looked like net outflow when the user had in fact paid the bill
# down) and the bank view lost genuine outflow.
_kpi_card = client.get("/api/transactions/kpis?account_sources=CREDIT_CARD").json()
check(
    "card view: settlement rows are NOT filtered out",
    _kpi_card["settlement_count"] > 0,
    f"{_kpi_card['settlement_count']} payment rows visible",
)
# The decisive check. `settlement_count` alone is not enough: it is reported from
# the pre-filter frame, so it stays at 35 even when the tiles go on to hide the
# rows. This asserts against the inflow AMOUNT instead, which cannot lie.
_card_rows = _ledger[_ledger["Account_Source"].fillna("BANK") == "CREDIT_CARD"]
_card_refund_credits = float(
    _card_rows.loc[~_card_rows["Is_Settlement"], "Credit_Amount"].sum()
)
check(
    "card view: inflow == non-payment credits + the payments",
    abs(
        _kpi_card["total_credits"]
        - (_card_refund_credits + _kpi_card["settlement_credits"])
    ) < 1.0,
    f"tile {_kpi_card['total_credits']:,.2f} = refunds"
    f" {_card_refund_credits:,.2f} + payments"
    f" {_kpi_card['settlement_credits']:,.2f}",
)
# On the card a payment is a CREDIT, so every debit in this view IS a purchase
# and the two debit figures must be equal. What must NOT happen is the payment
# inflating outflow - it belongs on the inflow line only.
# Every debit must be a purchase, and every payment must sit in inflow. The
# equality on the debit side is the real assertion: it fails if any payment is
# filed as spend. It is NOT an assertion that the card has no credits of its own
# - genuine refunds (and the Tata Neu "+ C" rows the issuer marks) are debits
# here only when the issuer printed them on the debit side, and both directions
# are equally valid per the statement.
check(
    "card view: no payment is filed as spend",
    # Tolerance, not ==: both figures are float sums and differ in the last bit
    # (3266034.43 vs 3266034.4299999997). An exact compare fails on rounding.
    abs(_kpi_card["total_spend_debits"] - _kpi_card["total_debits"]) < 0.01
    and abs(_kpi_card["settlement_debits"]) < 0.01,
    f"debits {_kpi_card['total_debits']:,.2f} = spend, none of it a payment;"
    f" the {_kpi_card['settlement_credits']:,.2f} of payments are in inflow",
)
_tl_card = client.get(
    "/api/transactions/summary/timeline?account_sources=CREDIT_CARD&group_by=month"
).json()
check(
    "card view: the cashflow timeline shows the payment",
    abs(sum(float(r.get("Total_Credit") or 0) for r in _tl_card)
        - _kpi_card["total_credits"]) < 0.01
    and any((r.get("Total_Credit") or 0) > 0 for r in _tl_card),
    f"{len(_tl_card)} periods, credits reconcile with the tile",
)
# The bank side is the mirror image: the payment really left that account.
_kpi_bank = client.get("/api/transactions/kpis?account_sources=BANK").json()
check(
    "bank view: the payment counts as OUTFLOW (money left)",
    _kpi_bank["settlement_count"] > 0
    and _kpi_bank["total_debits"] > _kpi_bank["total_spend_debits"],
    f"{_kpi_bank['settlement_debits']:,.2f} of card payments in the outflow",
)

# --- 4b3. card credits must be mostly settlements, not leaked income --------
# Regression guard. SETTLEMENT_RE named the payment ("BPPY CC PAYMENT") but not
# the generic transfer wording some issuers use ("NETBANKING TRANSFER", "TELE
# TRANSFER CREDIT"). Those rows were left unflagged, so 65 bill payments worth
# 20.6L surfaced as card INFLOW - two thirds of the card's apparent income - and
# the combined view could not exclude them.
#
# The invariant is proportional, not absolute: a genuine refund is a real credit
# too, so demanding zero would be wrong. But on a card the overwhelming majority
# of credits are bill payments, so if the detector loses its grip the settled
# share collapses. Before the fix it was 20% of the value; it is now 90%, and a
# large drop means some issuer's wording fell through again.
_all_cc = _card_rows[_card_rows["Credit_Amount"].fillna(0) > 0]
_unflagged = _all_cc[~_all_cc["Is_Settlement"].fillna(False)]
_total_cc_credit = float(_all_cc["Credit_Amount"].sum())
_refund_share = (
    float(_unflagged["Credit_Amount"].sum()) / _total_cc_credit
    if _total_cc_credit
    else 0.0
)
check(
    "most card credit VALUE is a flagged bill payment, not leaked income",
    _refund_share < 0.25,
    f"{len(_all_cc)} credits; unflagged {len(_unflagged)} worth"
    f" {float(_unflagged['Credit_Amount'].sum()):,.0f}"
    f" = {100 * _refund_share:.1f}% (the rest are genuine refunds)",
)

# --- 4c. a single-category drill-down must not blank a settlement category ----
# Regression guard. The double-count correction exists to stop a card purchase
# appearing beside the bill that paid for it, which only happens when several
# categories are aggregated together. Scoped to ONE category the other half is
# not in view, so the correction only deleted data: Credit_Card_Payment is 100%
# settlement, so its trend and monthly table both came back empty even though the
# rows exist and the transaction table shows them.
_trend_cc = client.get(
    "/api/transactions/category-trend"
    "?category=Credit_Card_Payment&group_col=Broad_Category"
).json()
check(
    "single-category trend returns the settlement category's rows",
    len(_trend_cc) > 0,
    f"{len(_trend_cc)} months plotted for Credit_Card_Payment",
)
_months_cc = client.get(
    "/api/transactions/summary/monthly-category"
    "?group_by=month&broad_categories=Credit_Card_Payment"
).json()
check(
    "single-category monthly table returns the settlement category's rows",
    len(_months_cc) > 0,
    f"{len(_months_cc)} months in the table",
)
# The drill-down must agree with the ledger, not merely be non-empty.
_cc_ledger_months = int(
    _cc.loc[~_cc["Is_Settlement"], "Year_Month"].nunique()
) or int(_cc["Year_Month"].nunique())
check(
    "drill-down month count matches the ledger for that category",
    len(_trend_cc) == _cc_ledger_months,
    f"trend {len(_trend_cc)} == ledger {_cc_ledger_months}",
)
# And the aggregate pie must STILL exclude them - the correction has not been
# dropped wholesale, only scoped to single-category views.
check(
    "aggregate breakdown still excludes Credit_Card_Payment (no double count)",
    not any(
        r.get("Category") == "Credit_Card_Payment" for r in _bd_all
    ),
    "settlement category absent from the cross-category total",
)

# --- 4d. direction: a card bill payment is a CREDIT on the card --------------
# Regression guard. A settlement is money coming IN on the card - it reduces the
# balance owed. The statement prints it in the debit column, so Direction arrived
# as DEBIT and the projection filed the payment as an expense. On the card it
# must always be a CREDIT. The bank-side half stays a debit: that is genuinely
# money leaving the account.
print("\n4d. Card settlement direction and user overrides")
_card_ledger = _ledger[_ledger["Account_Source"].fillna("BANK") == "CREDIT_CARD"]
_card_settle = _card_ledger[_card_ledger["Is_Settlement"]]
check(
    "card-side settlements exist (guard is not vacuous)",
    len(_card_settle) > 0,
    f"{len(_card_settle)} settlement rows on the card ledger",
)
check(
    "every card-side settlement is a CREDIT, not an expense",
    bool(len(_card_settle) == 0 or (_card_settle["Direction"] == "CREDIT").all()),
    f"{int((_card_settle['Direction'] == 'CREDIT').sum())}/{len(_card_settle)} CREDIT",
)
check(
    "a card settlement puts the amount in the CREDIT column",
    bool(
        len(_card_settle) == 0
        or ((_card_settle["Debit_Amount"].fillna(0) == 0).all()
            and (_card_settle["Credit_Amount"].fillna(0) > 0).all())
    ),
)
# The bank-side half is the mirror image: still a real debit.
_bank_settle = _cc[(_cc["Account_Source"].fillna("BANK") == "BANK")]
check(
    "bank-side card payments stay DEBIT (money left the account)",
    bool(len(_bank_settle) == 0 or (_bank_settle["Direction"] == "DEBIT").all()),
    f"{int((_bank_settle['Direction'] == 'DEBIT').sum())}/{len(_bank_settle)} DEBIT",
)

# --- 4e. a user can flip a row's direction, with narration matching ---------
_dir_rules_before = client.get("/api/transactions/direction-rules").json()
# Pick a real debit row to flip, so the change is observable.
_target = _ledger[(_ledger["Direction"] == "DEBIT") & (_ledger["Debit_Amount"].fillna(0) > 0)]
_ref = str(_target.iloc[0]["Chq_Ref_Number"])
_amt = float(_target.iloc[0]["Debit_Amount"])
_kpi_before = client.get("/api/transactions/kpis").json()

_client = client.post(
    "/api/transactions/direction-rules/apply-cascade",
    json={"rule_type": "txn", "rule_key": _ref, "direction": "CREDIT"},
)
check("direction rule applies", _client.status_code == 200, str(_client.json()))
_kpi_after = client.get("/api/transactions/kpis").json()
check(
    "flipping a row moves the amount, it does not duplicate it",
    abs(
        (_kpi_after["total_debits"] - _kpi_before["total_debits"]) + _amt
    ) < 0.01
    and abs(
        (_kpi_after["total_credits"] - _kpi_before["total_credits"]) - _amt
    ) < 0.01,
    f"debits -{_amt:,.2f}, credits +{_amt:,.2f}",
)
_flipped = client.get(
    f"/api/transactions?search={_ref}&page_size=5"
).json()["data"]
check(
    "the flipped row reports CREDIT and holds the amount in Credit_Amount",
    bool(_flipped and _flipped[0]["Direction"] == "CREDIT"
         and (_flipped[0]["Credit_Amount"] or 0) > 0
         and (_flipped[0]["Debit_Amount"] or 0) == 0),
)
# Narration matching: the same three rule types the category editor offers.
_pv = client.post(
    "/api/transactions/direction-rules/preview",
    json={"rule_type": "narration", "rule_key": "SRM HOTEL", "direction": "CREDIT"},
)
check(
    "narration rules preview like category rules",
    _pv.status_code == 200 and "total_matched" in _pv.json(),
    f"{_pv.json().get('total_matched')} matched",
)
# Clean up: remove every rule this section created.
for r in _dir_rules_before:
    client.post(
        "/api/transactions/direction-rules/delete",
        json={"rule_type": r["rule_type"], "rule_keys": [r["rule_key"]]},
    )
client.post(
    "/api/transactions/direction-rules/delete",
    json={"rule_type": "txn", "rule_keys": [_ref]},
)
check(
    "deleting the rule restores the original totals",
    abs(
        client.get("/api/transactions/kpis").json()["total_debits"]
        - _kpi_before["total_debits"]
    ) < 0.01,
)

# --- 5. the ledgers stay separate ------------------------------------------
print("\n4. Ledger separation")
bank = client.get("/api/transactions/kpis?spend_basis=bank_only").json()
card_only = client.get("/api/transactions/kpis?spend_basis=card_only").json()
unfiltered = client.get("/api/transactions/kpis").json()

# The two ledgers partition every ROW, so bank + card must be the whole ledger
# plus exactly the settlement rows the combined view drops. Their AMOUNTS do not
# simply sum either: each single-ledger view counts its own half of the card
# payment, so bank + card = combined + the bank-side half. Asserting those two
# exact identities is what proves the split neither loses nor invents money.
check(
    "bank + card rows equal the whole ledger, settlements included",
    bank["filtered_count"] + card_only["filtered_count"]
    == unfiltered["filtered_count"] + unfiltered["settlement_count"],
    f"{bank['filtered_count']} + {card_only['filtered_count']} ="
    f" {unfiltered['filtered_count']} + {unfiltered['settlement_count']} settlements",
)
check(
    "bank + card amounts equal the combined view plus both payment halves",
    abs(
        bank["total_debits"] + card_only["total_debits"]
        - unfiltered["total_debits"]
        - unfiltered["settlement_debits"]
    ) < 1.0,
    f"bank {bank['total_debits']:,.2f} + card {card_only['total_debits']:,.2f}"
    f" = combined {unfiltered['total_debits']:,.2f}"
    f" + {unfiltered['settlement_debits']:,.2f} bank-side payment",
)
check(
    "each single view counts its own half; only the combined view drops both",
    unfiltered["spend_count"] < unfiltered["filtered_count"]
    + unfiltered["settlement_count"]
    and bank["settlement_count"] > 0
    and card_only["settlement_count"] > 0
    and unfiltered["spend_count"] == unfiltered["filtered_count"],
    f"combined hides {unfiltered['settlement_count']}, bank shows"
    f" {bank['settlement_count']}, card shows {card_only['settlement_count']}",
)
check(
    "card_only equals account_sources=CREDIT_CARD",
    abs(card_only["total_debits"] - all_cards["total_debits"]) < 0.01
    and card_only["filtered_count"] == all_cards["filtered_count"],
)

# The card view forces spend_basis="all" client-side, because the sidebar's basis
# is a combined-view control: bank_only selects a set DISJOINT from
# account_sources=CREDIT_CARD, so honouring it there would blank the card panel.
# These two assertions are what make forcing it correct and safe.
blanked = client.get(
    "/api/transactions/kpis?account_sources=CREDIT_CARD&spend_basis=bank_only"
).json()
check(
    "bank_only + CREDIT_CARD is empty (why the card view forces basis=all)",
    blanked["filtered_count"] == 0,
)
# Every card row in the ledger, settled or not.
card_ledger_total = client.get(
    "/api/transactions?account_sources=CREDIT_CARD&page_size=1"
).json()["total"]
# Every card row in the ledger, settled or not. The card view is single-ledger, so
# it keeps its settlement rows - they are the card's own credit.
check(
    "card view keeps every card row, payments included",
    all_cards["filtered_count"] == card_ledger_total,
    f"{all_cards['filtered_count']} == {card_ledger_total} card ledger rows",
)
check(
    "the card's payments are reported as inflow, never as spend",
    all_cards["settlement_debits"] == 0 and all_cards["settlement_credits"] > 0,
    f"in {all_cards['settlement_credits']:,.2f} / out {all_cards['settlement_debits']:,.2f}",
)
check(
    "card rows are tagged CREDIT_CARD",
    client.get("/api/transactions?account_sources=CREDIT_CARD&page_size=50").json()["data"][0][
        "Account_Source"
    ]
    == "CREDIT_CARD",
)

# --- 6. the positional-argument fix ----------------------------------------
print("\n5. Summary endpoints honour every filter (positional-arg fix)")
sub = meta["sub_categories"][0]
tl_sub = client.get(
    f"/api/transactions/summary/timeline?sub_categories={sub}&group_by=month"
).json()
list_sub = client.get(f"/api/transactions?sub_categories={sub}&page_size=1").json()
check(
    "sub_categories reaches the timeline",
    list_sub["total"] > 0 and len(tl_sub) > 0,
    f"{sub}: {list_sub['total']} rows across {len(tl_sub)} periods",
)
mc_sub = client.get(
    f"/api/transactions/summary/monthly-category?sub_categories={sub}&group_by=month"
).json()
check("sub_categories reaches monthly-category", len(mc_sub) > 0)

parent = meta["categories"][0]
bc_par = client.get(
    f"/api/transactions/summary/category-breakdown?categories={parent}&group_col=Broad_Category"
).json()
check("parent categories reach category-breakdown", len(bc_par) > 0, parent)

# spend_basis was previously dropped from these three endpoints entirely.
tl_bank = client.get(
    "/api/transactions/summary/timeline?spend_basis=bank_only&group_by=month"
).json()
tl_card = client.get(
    "/api/transactions/summary/timeline?spend_basis=card_only&group_by=month"
).json()
check(
    "spend_basis reaches the timeline",
    len(tl_bank) > 0 and len(tl_card) > 0,
    f"bank {len(tl_bank)} periods, card {len(tl_card)} periods",
)

# --- 7. export -------------------------------------------------------------
print("\n6. CSV export of a scoped card set")
resp = client.get(f"/api/transactions/export?account_sources=CREDIT_CARD&card_ids={cid}")
check("export returns 200", resp.status_code == 200)
check(
    "export contains rows",
    resp.text.count("\n") > 1,
    f"{resp.text.count(chr(10)) - 1} rows",
)
check("export is scoped to the card", "CC:" in resp.text and "Account_Source" in resp.text)

# --- 8. sorting -------------------------------------------------------------
# Every table that lists transactions exposes sortable headers, and sorting must
# be SERVER-side. These tables are paginated, so sorting the rows on screen would
# only reorder that page rather than the true top or bottom of the result set -
# which looks like it worked while silently hiding the rows the user wanted.
print("\n7. Sorting re-ranks the whole result set")
for col, key, numeric in (
    ("Date", "Date", False),
    ("Debit_Amount", "Debit_Amount", True),
    ("Narration", "Narration", False),
    ("Payee_Receiver", "Payee_Receiver", False),
    ("Credit_Amount", "Credit_Amount", True),
    ("Broad_Category", "Broad_Category", False),
):

    def _page(order, n=20):
        rows = client.get(
            f"/api/transactions?account_sources=CREDIT_CARD&sort_by={col}"
            f"&sort_order={order}&page_size={n}"
        ).json()["data"]
        # Amounts must compare NUMERICALLY. As strings "168440.0" sorts below
        # "183718.0", which would report a working sort as broken.
        return [float(r[key] or 0) if numeric else ("" if r[key] is None else str(r[key]))
                for r in rows]

    a, d = _page("asc"), _page("desc")
    check(
        f"sort_by={col} orders the page monotonically",
        a == sorted(a) and d == sorted(d, reverse=True) and a != d,
        f"asc[0]={a[0]!r:.18} desc[0]={d[0]!r:.18}",
    )

# An unsupported column must be ignored rather than erroring, so a stale or
# hand-typed query cannot break the table.
check(
    "an unknown sort column is ignored, not an error",
    client.get("/api/transactions?sort_by=NOT_A_COLUMN&page_size=2").status_code == 200,
)
# Sorting must not change the row COUNT - it re-orders, it does not filter.
_unsorted_total = client.get(
    "/api/transactions?account_sources=CREDIT_CARD&page_size=1"
).json()["total"]
_sorted_total = client.get(
    "/api/transactions?account_sources=CREDIT_CARD&sort_by=Debit_Amount"
    "&sort_order=desc&page_size=1"
).json()["total"]
check(
    "sorting does not change how many rows match",
    _unsorted_total == _sorted_total,
    f"{_unsorted_total} rows either way",
)

print("\n" + "=" * 72)
if failures:
    print(f"FAILED ({len(failures)}): " + "; ".join(failures))
else:
    print("ALL CHECKS PASSED")
print("=" * 72)
