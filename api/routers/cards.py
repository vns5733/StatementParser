"""
Credit-card endpoints — card registry, cycle statements, card-level spend and
the reconciliation against the bank ledger.

The aggregated dashboard reads the shared `transactions` table, so most card
spend analysis needs no endpoint here. What lives here is the detail the bank
schema has no column for: rewards, the issuer's own category, the cycle totals
the issuer printed, and whether the bank actually paid that statement.
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pandas as pd
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.engine import Engine

from api.deps import get_engine
from card_store import reconcile_card_payments
from config import (
    TABLE_CREDIT_CARDS,
    TABLE_CREDIT_CARD_STATEMENTS,
    TABLE_CREDIT_CARD_TRANSACTIONS,
)
from db import get_all_transactions_with_details

router = APIRouter(prefix="/cards", tags=["cards"])


def _clean(value):
    """NaN/NaT/None -> None for JSON serialisation."""
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.isoformat()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def _records(df):
    if df is None or df.empty:
        return []
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%dT%H:%M:%S")
    return [{k: _clean(v) for k, v in row.items()} for row in out.to_dict("records")]


# ---------------------------------------------------------------------------
# GET /api/cards — the card registry
# ---------------------------------------------------------------------------
@router.get("")
def list_cards(engine: Engine = Depends(get_engine)):
    with engine.connect() as c:
        cards = pd.read_sql(
            text(f"""
                SELECT k.Card_ID, k.Issuer, k.Card_Name, k.Last4, k.Credit_Limit,
                       k.First_Seen, k.Last_Seen,
                       COUNT(DISTINCT s.Statement_ID) AS Statement_Count,
                       COALESCE(SUM(s.Parsed_Spend), 0) AS Total_Parsed_Spend
                FROM {TABLE_CREDIT_CARDS} k
                LEFT JOIN {TABLE_CREDIT_CARD_STATEMENTS} s ON s.Card_ID = k.Card_ID
                GROUP BY k.Card_ID, k.Issuer, k.Card_Name, k.Last4, k.Credit_Limit,
                         k.First_Seen, k.Last_Seen
                ORDER BY k.Issuer, k.Card_Name
            """),
            con=c,
        )
    return _records(cards)


# ---------------------------------------------------------------------------
# GET /api/cards/statements — one row per billing cycle
# ---------------------------------------------------------------------------
@router.get("/statements")
def list_statements(
    card_id: str = Query(None),
    engine: Engine = Depends(get_engine),
):
    sql = text(f"""
        SELECT s.Statement_ID, s.Card_ID, s.Issuer, s.Card_Name, s.Statement_Date,
               s.Due_Date, s.Period_Start, s.Period_End, s.Previous_Dues,
               s.Payments_Received, s.Total_Spend, s.Finance_Charges, s.Total_Due,
               s.Minimum_Due, s.Credit_Limit, s.Available_Credit_Limit, s.Txn_Count,
               s.Parsed_Spend, s.Parsed_Refunds, s.Spend_Mix, s.Source_File,
               s.Imported_At
        FROM {TABLE_CREDIT_CARD_STATEMENTS} s
        {("WHERE s.Card_ID = :cid" if card_id else "")}
        ORDER BY s.Statement_Date DESC
    """)
    with engine.connect() as c:
        df = pd.read_sql(sql, con=c, params={"cid": card_id} if card_id else None)

    records = _records(df)
    # Spend_Mix is JSON text in the DB; the dashboard wants an object.
    for r in records:
        mix = r.get("Spend_Mix")
        if isinstance(mix, str):
            try:
                r["Spend_Mix"] = json.loads(mix)
            except ValueError:
                r["Spend_Mix"] = {}
    return records


# ---------------------------------------------------------------------------
# GET /api/cards/spend — card spend by category, from the shared ledger
# ---------------------------------------------------------------------------
@router.get("/spend")
def card_spend(engine: Engine = Depends(get_engine)):
    """
    Card spend grouped by card and category.

    Reads the shared ledger rather than the card table so this always agrees
    with the dashboard totals, and drops settlement rows: paying a card bill is
    not spend, and counting it would double count the purchases it settles.
    """
    df = get_all_transactions_with_details(engine)
    card = df[(df["Account_Source"] == "CREDIT_CARD") & (~df["Is_Settlement"])]
    if card.empty:
        return []

    grouped = (
        card.groupby(["Card_Name", "Card_Issuer", "Category"], dropna=False)
        .agg(Spend=("Debit_Amount", "sum"),
             Refunds=("Credit_Amount", "sum"),
             Count=("Debit_Amount", "size"))
        .reset_index()
        .rename(columns={"Card_Issuer": "Issuer"})
        .sort_values("Spend", ascending=False)
    )
    return _records(grouped)


# ---------------------------------------------------------------------------
# GET /api/cards/reconcile — match each statement to the bank debit that paid it
# ---------------------------------------------------------------------------
@router.get("/reconcile")
def reconcile(
    tolerance: float = Query(1.0, ge=0),
    grace_days: int = Query(10, ge=0, le=90),
    engine: Engine = Depends(get_engine),
):
    result = reconcile_card_payments(engine, tolerance=tolerance, grace_days=grace_days)
    return {
        "summary": result["summary"],
        "matched": [{k: _clean(v) for k, v in m.items()} for m in result["matched"]],
        "unmatched_statements": [
            {
                "Statement_ID": u.get("Statement_ID"),
                "Card_Name": u.get("Card_Name"),
                "Issuer": u.get("Issuer"),
                "Statement_Date": _clean(u.get("Statement_Date")),
                "Total_Due": _clean(u.get("Total_Due")),
                "Total_Spend": _clean(u.get("Total_Spend")),
                "reason": u.get("reason"),
                "closest_amount": _clean(u.get("closest_amount")),
                "variance": _clean(u.get("variance")),
            }
            for u in result["unmatched_statements"]
        ],
        # Capped: the bank ledger spans years and the vast majority of these
        # legitimately have no statement held for them.
        "unmatched_bank_debits": [
            {
                "Chq_Ref_Number": d.get("Chq_Ref_Number"),
                "Date": _clean(d.get("Date")),
                "Debit_Amount": _clean(d.get("Debit_Amount")),
            }
            for d in result["unmatched_bank_debits"][:200]
        ],
        "unmatched_bank_debit_count": len(result["unmatched_bank_debits"]),
    }


# ---------------------------------------------------------------------------
# GET /api/cards/issuer-categories — how often the issuer supplied a category
# ---------------------------------------------------------------------------
@router.get("/issuer-categories")
def issuer_category_stats(engine: Engine = Depends(get_engine)):
    """
    Coverage of issuer-supplied categories per card.

    Worth surfacing because it explains accuracy: where the issuer classified
    the transaction itself, the category is the card network's own judgement
    rather than a keyword guess. HDFC supplies none at row level (it only prints
    a cycle-level mix), so its rows fall back to the keyword parser.
    """
    with engine.connect() as c:
        df = pd.read_sql(
            text(f"""
                SELECT s.Issuer, s.Card_Name,
                       COUNT(*) AS Txn_Count,
                       SUM(CASE WHEN t.Statement_Category IS NOT NULL THEN 1 ELSE 0 END)
                           AS Issuer_Categorised
                FROM {TABLE_CREDIT_CARD_TRANSACTIONS} t
                JOIN {TABLE_CREDIT_CARD_STATEMENTS} s
                    ON s.Statement_ID = t.Statement_ID
                GROUP BY s.Issuer, s.Card_Name
                ORDER BY s.Issuer, s.Card_Name
            """),
            con=c,
        )
    if df.empty:
        return []

    out = []
    for _, row in df.iterrows():
        total = int(row["Txn_Count"] or 0)
        covered = int(row["Issuer_Categorised"] or 0)
        out.append({
            "Issuer": _clean(row["Issuer"]),
            "Card_Name": _clean(row["Card_Name"]),
            "Txn_Count": total,
            "Issuer_Categorised": covered,
            "Coverage_Pct": round(covered * 100.0 / total, 1) if total else 0.0,
        })
    return out


