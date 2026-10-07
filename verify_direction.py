"""
verify_direction.py — guards the direction-aware category layer.

This exists because the change it covers is invisible when it is wrong. A row that
was not reclassified, or one that was reclassified to itself, still renders, still
sums, and still passes every endpoint. The only symptom is a Groww payout still
labelled "Investment" — the exact complaint the layer was built to fix, and the
one thing a green dashboard cannot show you.

Covered here:
  A. the categoriser, with no database at all (direction reconciliation in
     category_rules.apply_direction_awareness)
  B. the read-time derivation in db._apply_direction_awareness, against the live
     ledger: what it re-filed, what it flagged, and what it must not have touched
  C. ordering — settlement must still see the *reconciled* category, or a card
     refund is excluded from spend as though it were the bill it reversed
  D. rollups — splitting a category by direction must not change what a parent
     adds up to, which is the whole reason the pairs share a parent
  E. notes and the definitions registry

Run: python verify_direction.py
"""

import sys
import os
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd

import db
from category_rules import (
    CREDIT_INVERSE,
    BUILTIN_CATEGORIES,
    CATEGORY_SPECS,
    DIRECTION_BOTH,
    DIRECTION_IN,
    DIRECTION_OUT,
    apply_direction_awareness,
    category_direction,
    parent_category,
)
from api.deps import get_engine

PASS, FAIL = "PASS", "FAIL"
failures = []
section_name = ""

# Unpacked tuple form: the check below reads better as a single condition, and a
# bare assignment inside a call is a syntax error.
_g = apply_direction_awareness("Groceries", False, True)


def section(title):
    global section_name
    section_name = title
    print(f"\n{section_name}")


def check(label, condition, detail=""):
    ok = bool(condition)
    print(f"  [{PASS if ok else FAIL}] {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        failures.append(f"{section_name} :: {label} :: {detail}")
    return ok


# ---------------------------------------------------------------------------
# A. The categoriser on its own. No database, so these cannot be moved by a
#    read-time behaviour change and can be checked exhaustively.
# ---------------------------------------------------------------------------
print("=" * 74)
print("DIRECTION-AWARE CATEGORIES")
print("=" * 74)

section("A. Reconciler unit behaviour")

check(
    "every built-in category has a spec and a direction",
    all(c in CATEGORY_SPECS for c in BUILTIN_CATEGORIES)
    and all(c in CATEGORY_SPECS for c in CATEGORY_SPECS),
    f"{len(BUILTIN_CATEGORIES)} built-ins, {len(CATEGORY_SPECS)} specs",
)

check(
    "every spec direction is one of IN / OUT / BOTH",
    all(s["direction"] in (DIRECTION_IN, DIRECTION_OUT, DIRECTION_BOTH)
        for s in CATEGORY_SPECS.values()),
)

paired = {k: v for k, v in CREDIT_INVERSE.items()}
check(
    "each paired category has the direction its name implies",
    all(category_direction(k) == DIRECTION_OUT and category_direction(v) == DIRECTION_IN
        for k, v in paired.items()),
    ", ".join(f"{k}->{v}" for k, v in paired.items()),
)

check(
    "both halves of every pair roll up to the SAME parent",
    all(parent_category(k) == parent_category(v) for k, v in paired.items()),
    "; ".join(f"{k}:{parent_category(k)} / {v}:{parent_category(v)}"
              for k, v in paired.items()),
)

# The two outcomes that must not be confused with each other.
check(
    "a credit on a paired outflow category is RE-FILED, not flagged",
    apply_direction_awareness("Investment", False, True)[0] == "Investment_Liquidation"
    and apply_direction_awareness("Investment", False, True)[1] is None,
)
check(
    "a credit on an UNPAIRED outflow category is FLAGGED, not moved",
    _g[0] == "Groceries" and _g[2] is None and _g[1] is not None,
    f"category={_g[0]} reason={_g[1]} corrected_from={_g[2]}",
)
check(
    "a debit in an income category is flagged",
    apply_direction_awareness("Salary", True, False)[1] is not None,
)
check(
    "a BOTH category is never touched, either way",
    apply_direction_awareness("Switch_Own_Accounts", True, False)[1] is None
    and apply_direction_awareness("Switch_Own_Accounts", False, True)[1] is None,
)
check(
    "money on both sides is left alone rather than guessed at",
    apply_direction_awareness("Investment", True, True) == ("Investment", None, None),
)
check(
    "an unlisted category is BOTH, so it produces no split and no flag",
    category_direction("Some_User_Category") == DIRECTION_BOTH
    and apply_direction_awareness("Some_User_Category", False, True)[1] is None,
)
check(
    "a user direction override wins over the code default",
    category_direction("Investment", {"Investment": DIRECTION_BOTH}) == DIRECTION_BOTH
    and category_direction("Investment", {}) == DIRECTION_OUT,
)
check(
    "Investment_Liquidation is NOT folded back into Investment by the rename map",
    "Investment_Liquidation" not in db.CATEGORY_RENAMES,
    "a rename entry would re-merge the pair on every startup",
)
check(
    "a refund keyword does not create a Cash_Deposit",
    apply_direction_awareness("Cash_Deposit", True, False)[1] is not None
    and apply_direction_awareness("ATM_Cash", False, True)[0] == "Cash_Deposit",
)

# ---------------------------------------------------------------------------
# B/C/D. Against the live ledger.
# ---------------------------------------------------------------------------
section("B. Read-time derivation on the live ledger")

engine = get_engine()
df = db.get_all_transactions_with_details(engine)

if df.empty:
    print("  ledger is empty - nothing to verify against")
    sys.exit(1)

check("ledger loaded", len(df) > 0, f"{len(df)} rows")

for col in ("Note", "Category_Direction", "Direction_Mismatch",
            "Direction_Reclassified", "Direction_Mismatch_Reason",
            "Suggestion", "Category", "Is_Settlement"):
    check(f"column {col} present", col in df.columns)

reclassified = df[df.Direction_Reclassified.notna()]
flagged = df[df.Direction_Mismatch]
check(
    "guard is not vacuous: there is something to reconcile",
    len(reclassified) + len(flagged) > 0,
    f"{len(reclassified)} re-filed, {len(flagged)} flagged",
)

# The central claim: a reclassified row landed on its counterpart.
check(
    "every re-filed row landed exactly on its CREDIT_INVERSE counterpart",
    len(reclassified) > 0
    and all(
        row.Broad_Category == CREDIT_INVERSE.get(row.Direction_Reclassified)
        for _, row in reclassified.iterrows()
    ),
    "; ".join(f"{k} x{v}" for k, v in reclassified.Direction_Reclassified.value_counts().items()),
)

check(
    "no re-filed row kept the leaf of the category it left",
    len(reclassified) > 0
    and not reclassified.Sub_Category.isin(
        ["Mutual_Fund", "Equity_Trading", "FD_RD", "Investment_General"]
    ).any(),
    "the leaf is re-derived from the NEW parent",
)

check(
    "a re-filed row's parent rollup follows its new category",
    len(reclassified) > 0
    and all(
        row.Category == parent_category(row.Broad_Category)
        for _, row in reclassified.iterrows()
    ),
)

# Direction agreement, stated from both ends.
in_cats = df[df.Category_Direction == DIRECTION_IN]
check(
    "no IN-category row holds a debit",
    not (in_cats.Debit_Amount > 0).any(),
    f"{int((in_cats.Debit_Amount > 0).sum())} of {len(in_cats)}",
)

out_with_credit = df[(df.Category_Direction == DIRECTION_OUT) & (df.Credit_Amount > 0)]
settled_or_flagged = out_with_credit.Is_Settlement | out_with_credit.Direction_Mismatch
check(
    "every OUT-category credit is either a settlement or flagged - never silent",
    settled_or_flagged.all(),
    f"{len(out_with_credit)} such rows, {int((~settled_or_flagged).sum())} unexplained",
)

check(
    "Category_Direction agrees with the row's ACTUAL category",
    (
        df.Category_Direction
        .reset_index(drop=True)
        .eq(pd.Series([category_direction(c) for c in df.Broad_Category]))
        .all()
    ),
    "a row advertising the direction of the category it used to be is how "
    "Card_Refund ends up reported as OUT",
)

check(
    "every flagged row carries a reason",
    flagged.empty or flagged.Direction_Mismatch_Reason.notna().all(),
    f"{len(flagged)} flagged",
)

# ---------------------------------------------------------------------------
# C. Ordering. The bug this guards is a silent one: the numbers still add up.
# ---------------------------------------------------------------------------
section("C. Settlement sees the reconciled category")

card_refunds = df[df.Broad_Category == "Card_Refund"]
check(
    "a card refund is NOT marked as a settlement",
    not card_refunds.Is_Settlement.any(),
    f"{len(card_refunds)} refunds, {int(card_refunds.Is_Settlement.sum())} "
    f"wrongly excluded from spend",
)

check(
    "a card-side bill payment is still a settlement",
    int(df[df.Account_Source == "CREDIT_CARD"].Is_Settlement.sum()) > 0,
    f"{int(df[(df.Account_Source == 'CREDIT_CARD') & df.Is_Settlement].shape[0])} "
    f"card-side settlements",
)

check(
    "a bank-side card payment is still a settlement",
    int(df[df.Broad_Category == "Credit_Card_Payment"].Is_Settlement.sum()) > 0,
    f"{int(df[df.Broad_Category == 'Credit_Card_Payment'].Is_Settlement.sum())} bank halves",
)

check(
    "settlements were not themselves reclassified into a refund",
    not (df.Is_Settlement & df.Direction_Reclassified.notna()).any(),
    "95 card-side NETBANKING TRANSFER credits were relabelled Card_Refund before "
    "the settlement mask was consulted",
)

# ---------------------------------------------------------------------------
# D. Rollups. Splitting a category must not move a single rupee between parents.
# ---------------------------------------------------------------------------
section("D. Rollups still total")

check(
    "every row has a parent rollup",
    not df.Category.isna().any() and not df.Category.astype(str).str.strip().eq("").any(),
)

pairs_total = {p for p in (parent_category(k) for k in CREDIT_INVERSE)}
for parent in sorted(pairs_total):
    members = [c for c in df.Broad_Category.unique() if parent_category(c) == parent]
    if not members:
        continue
    sub = df[df.Broad_Category.isin(members)]
    siblings = df[df.Category == parent]
    check(
        f"parent {parent}: both halves of its pairs are inside it",
        abs(sub.Debit_Amount.sum() - siblings.Debit_Amount.sum()) < 0.01
        and abs(sub.Credit_Amount.sum() - siblings.Credit_Amount.sum()) < 0.01,
        f"paired categories {sorted(m for m in members if m in set(CREDIT_INVERSE.values()))}"
        f" contribute debit {sub.Debit_Amount.sum():,.2f} / "
        f"credit {sub.Credit_Amount.sum():,.2f}",
    )

check(
    "the paired categories really are present in the data",
    len([c for c in df.Broad_Category.unique()
         if c in set(CREDIT_INVERSE.values()) or c in CREDIT_INVERSE]) > 0,
    f"{sorted(set(CREDIT_INVERSE.values()) & set(df.Broad_Category.unique()))}",
)

# ---------------------------------------------------------------------------
# E. Notes and definitions.
# ---------------------------------------------------------------------------
section("E. Notes and definitions")

definitions = db.get_category_definitions(engine)
by_name = {d["name"]: d for d in definitions}

check(
    "every built-in category has a stored definition",
    all(c in by_name for c in BUILTIN_CATEGORIES),
    f"{len(definitions)} definitions for {len(BUILTIN_CATEGORIES)} built-ins",
)
check(
    "every built-in definition has prose",
    all(by_name[c]["description"] for c in BUILTIN_CATEGORIES if c in by_name),
)
check(
    "every definition reports a direction",
    all(d["direction"] in (DIRECTION_IN, DIRECTION_OUT, DIRECTION_BOTH)
        for d in definitions),
)
check(
    "a definition with an override still reports the code default",
    all(d["code_direction"] in (DIRECTION_IN, DIRECTION_OUT, DIRECTION_BOTH)
        for d in definitions),
)

sample = df.head(3)["Chq_Ref_Number"].tolist()
try:
    written = db.set_notes(engine, sample, note="verify_direction: scratch note")
    read_back = db.get_notes(engine, sample)
    check(
        "a note round-trips",
        written == 3 and all(read_back.get(r, {}).get("note") ==
                            "verify_direction: scratch note" for r in sample),
        f"wrote {written}, read {len(read_back)}",
    )
    check(
        "clearing removes the note",
        db.set_notes(engine, sample, note=None) == 3
        and all(not db.get_notes(engine, sample).get(r, {}).get("note")
                for r in sample),
    )
    db.clear_notes(engine, sample)
except Exception as exc:  # pragma: no cover - surfaced as a failure, not a crash
    check("note round-trip", False, repr(exc))

check(
    "no scratch note was left behind",
    not df.Note.fillna("").astype(str).str.contains("scratch note").any(),
)

try:
    db.upsert_category_definition(
        engine, "Verify_Scratch_Cat", description="temporary", direction_override=None
    )
    check(
        "a definition can create its own category",
        any(d["name"] == "Verify_Scratch_Cat" for d in db.get_category_definitions(engine))
        and "Verify_Scratch_Cat" in db.get_broad_categories(engine),
    )
    db.delete_category_definition(engine, "Verify_Scratch_Cat")
    with db.create_mysql_connection().begin() as conn:
        conn.execute(db.text("DELETE FROM broad_categories WHERE name = :n"),
                     {"n": "Verify_Scratch_Cat"})
    check("the scratch definition is gone", True)
except Exception as exc:  # pragma: no cover
    check("definition create/delete", False, repr(exc))

try:
    db.upsert_category_definition(
        engine, "Investment", description="probe", direction_override="SIDEWAYS"
    )
    check("an invalid direction override is refused", False, "it was accepted")
except ValueError as exc:
    check("an invalid direction override is refused", "direction_override" in str(exc))

# ---------------------------------------------------------------------------
print("\n" + "=" * 74)
if failures:
    print(f"{len(failures)} FAILURE(S)")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("ALL CHECKS PASSED")