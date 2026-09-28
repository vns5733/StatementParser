"""
Transaction endpoints — all read/filter/aggregate operations plus file upload.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import io
from typing import Optional, List
from datetime import datetime

import pandas as pd
from fastapi import APIRouter, Depends, Query, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.engine import Engine

from api.deps import get_engine
from config import DEFAULT_STATEMENT_PATH, TABLE_DIRECTION_RULES
from db import (
    get_all_transactions_with_details,
    get_total_transaction_count,
    store_data_in_db,
    recategorize_all_narrations,
    apply_direction_rules,
    delete_direction_rules,
)
from loader import load_and_clean_statement
from narration_parser import parse_narrations_dataframe

router = APIRouter(prefix="/transactions", tags=["transactions"])

# Columns that may be used for server-side sorting
SORTABLE_COLUMNS = {
    "Date": "Date",
    "Narration": "Narration",
    "Payee_Receiver": "Payee_Receiver",
    "Debit_Amount": "Debit_Amount",
    "Credit_Amount": "Credit_Amount",
    "Category": "Category",
    "Broad_Category": "Broad_Category",
    "Sub_Category": "Sub_Category",
    "is_recurring": "is_recurring",
}


def _safe_val(v):
    """Convert NaN/NaT/None to None for JSON serialisation."""
    if v is None:
        return None
    try:
        import math
        if isinstance(v, float) and math.isnan(v):
            return None
    except Exception:
        pass
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def _df_to_records(df: pd.DataFrame) -> List[dict]:
    """
    Convert DataFrame to JSON-safe list of dicts.

    Datetime columns and nulls are normalised with vectorised column ops; a
    per-cell Python loop over every value is costly for endpoints that return
    thousands of rows (e.g. balance-trend).

    The frame is cast to object BEFORE the null replacement. On a float64 column
    `where(notna, None)` is a no-op: pandas coerces None straight back to NaN, so
    the NaN survives into the response and JSON encoding fails with "Out of range
    float values are not JSON compliant". Card rows have no closing balance, so
    this is reached in normal use rather than only on malformed data.
    """
    if df.empty:
        return []

    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%dT%H:%M:%S")

    out = out.astype(object)
    return out.where(pd.notna(out), None).to_dict(orient="records")


def _split_csv(raw: Optional[str]) -> Optional[List[str]]:
    """Parses a comma-separated query param into a list of non-empty tokens."""
    if not raw:
        return None
    items = [t.strip() for t in raw.split(",") if t.strip()]
    return items or None


def _split_int_csv(raw: Optional[str]) -> Optional[List[int]]:
    """Same as _split_csv but coerces every token to int, dropping unparseable ones."""
    items = _split_csv(raw)
    if not items:
        return None
    parsed = []
    for token in items:
        try:
            parsed.append(int(token))
        except ValueError:
            continue
    return parsed or None


def _settlement_handling(spend_basis, account_sources):
    """
    Decides whether card settlements belong in the CASHFLOW totals for this view.

    A card bill payment is two halves of one transfer: the bank-side debit and
    the card-side credit. They can only be double counted if BOTH are in the same
    view, so the correction belongs to the combined view and nowhere else:

      * combined (`all`, or both sources)  -> exclude both halves. This is the
        only place the double count is real.
      * bank only  -> the bank half IS the outflow; it really left the account.
        Hiding it understates what the bank account spent.
      * card only  -> the card half IS the inflow; it really reduced the balance
        owed. Hiding it made the card look like net outflow when the user had in
        fact paid down the bill.

    So the correction is keyed on the SCOPE, not on a fixed endpoint list. An
    earlier version hid settlements everywhere, which removed genuine inflow
    from the card view and genuine outflow from the bank view - the exact
    opposite of what the flag is for.
    """
    basis = (spend_basis or "all").lower()
    sources = {s.upper() for s in (account_sources or []) if s}
    if basis in ("bank_only", "card_only"):
        return False
    if sources and sources <= {"CREDIT_CARD"}:
        return False
    if sources and sources <= {"BANK"}:
        return False
    return True


def _apply_spend_basis(df, spend_basis, exclude_settlements=True):
    """
    Scopes a frame to a spend basis.

    `spend_basis` picks the ledger: `all` (both), `bank_only` (BANK),
    `card_only` (CREDIT_CARD). `card_only` is a filter on which rows count, so it
    always applies.

    `exclude_settlements` is a *calculation* concern, not a visibility one. A card
    purchase and the bank debit that settles the card are two halves of one
    transaction, so summing both as spend double counts - but that is a reason to
    adjust a total, never a reason to hide a row from the transaction table. The
    ledger and the explorer therefore keep settlements and only the spend
    aggregates drop them. See _settlement_handling for when the correction applies.
    """
    if df.empty:
        return df

    keep = pd.Series(True, index=df.index)
    if "Account_Source" in df.columns:
        source = df["Account_Source"].fillna("BANK")
        if spend_basis == "bank_only":
            keep &= source != "CREDIT_CARD"
        elif spend_basis == "card_only":
            keep &= source == "CREDIT_CARD"

    if exclude_settlements and "Is_Settlement" in df.columns:
        keep &= ~df["Is_Settlement"].fillna(False)

    return df[keep]



def _get_filtered_df(
    engine: Engine,
    years: Optional[List[int]] = None,
    months: Optional[List[int]] = None,
    txn_types: Optional[List[str]] = None,
    broad_categories: Optional[List[str]] = None,
    direction: Optional[str] = None,
    search: Optional[str] = None,
    amount_field: Optional[str] = None,
    amount_min: Optional[float] = None,
    amount_max: Optional[float] = None,
    year_months: Optional[List[str]] = None,
    sub_categories: Optional[List[str]] = None,
    categories: Optional[List[str]] = None,
    is_recurring: Optional[bool] = None,
    spend_basis: str = "all",
    account_sources: Optional[List[str]] = None,
    card_ids: Optional[List[str]] = None,
    exclude_settlements: bool = False,
    include_settlements: bool = False,
) -> pd.DataFrame:
    """
    Shared filter path for every endpoint.

    `exclude_settlements` defaults to False so list-style endpoints return the
    ledger as stored. Spend aggregates opt in, because only they are summing
    debit amounts and therefore need the double-count correction.

    `include_settlements=True` forces them back in, for the one caller that
    wants to *report* the correction rather than apply it - `/kpis` needs to name
    the rows and rupees it held out, which it cannot do if the filter already
    deleted them. It defaults to False: an opt-in override, because defaulting it
    on would silently disable `exclude_settlements` for every other caller.

    `card_ids` narrows to specific cards. It is meaningless on bank rows (their
    Card_ID is NULL), so it is a no-op there rather than an error - which lets
    the card view reuse this same path for both ledgers.

    Callers should pass keyword arguments. The signature is long enough that
    positional calls silently mis-bind (see the timeline/monthly-category/
    category-breakdown endpoints, which shipped with year_months bound to
    sub_list and account_sources dropped entirely).
    """
    df = get_all_transactions_with_details(engine)
    if df.empty:
        return df

    # Scoped before the other filters so every downstream aggregate inherits it.
    if account_sources:
        df = df[df["Account_Source"].isin([s.upper() for s in account_sources])]
    if card_ids and "Card_ID" in df.columns:
        # Bank rows carry no Card_ID, so this simply matches nothing there.
        df = df[df["Card_ID"].isin(card_ids)]
    df = _apply_spend_basis(
        df,
        spend_basis,
        exclude_settlements=exclude_settlements and not include_settlements,
    )

    df["Broad_Category"] = df["Broad_Category"].fillna("Uncategorized")
    if "Sub_Category" not in df.columns:
        df["Sub_Category"] = df["Broad_Category"]

    # Exact "YYYY-MM" match — used for summary-table drill-down so a month
    # resolves within a single year rather than every March on record.
    if year_months:
        df = df[df["Year_Month"].astype(str).isin(year_months)]

    if categories:
        df = df[df["Category"].isin(categories)]
    if sub_categories:
        df = df[df["Sub_Category"].isin(sub_categories)]

    if years:
        df = df[df["Year"].isin(years)]
    if months:
        df = df[df["Month"].isin(months)]

    if is_recurring is not None and "is_recurring" in df.columns:
        df = df[df["is_recurring"].astype(bool) == bool(is_recurring)]
    if txn_types:
        df = df[df["Transaction_Type"].isin(txn_types)]
    if broad_categories:
        df = df[df["Broad_Category"].isin(broad_categories)]
    if direction == "debits":
        df = df[df["Debit_Amount"] > 0]
    elif direction == "credits":
        df = df[df["Credit_Amount"] > 0]
    if search and search.strip():
        q = search.strip().lower()
        mask = (
            df["Narration"].astype(str).str.lower().str.contains(q, na=False)
            | df["Payee_Receiver"].astype(str).str.lower().str.contains(q, na=False)
            | df["Reference_ID"].astype(str).str.lower().str.contains(q, na=False)
            | df["Details"].astype(str).str.lower().str.contains(q, na=False)
            | df["Chq_Ref_Number"].astype(str).str.lower().str.contains(q, na=False)
        )
        df = df[mask]
    if amount_field in ("debit", "credit", "any"):
        if amount_field == "debit":
            amt = df["Debit_Amount"].fillna(0)
        elif amount_field == "credit":
            amt = df["Credit_Amount"].fillna(0)
        else:
            amt = df[["Debit_Amount", "Credit_Amount"]].max(axis=1).fillna(0)
        if amount_min is not None:
            df = df[amt >= amount_min]
        if amount_max is not None:
            df = df[amt <= amount_max]
    return df


# ---------------------------------------------------------------------------
# GET /api/transactions — filtered transaction list
# ---------------------------------------------------------------------------
@router.get("")
def list_transactions(
    years: Optional[str] = Query(None, description="Comma-separated years, e.g. 2023,2024"),
    months: Optional[str] = Query(None, description="Comma-separated month numbers 1-12"),
    txn_types: Optional[str] = Query(None),
    broad_categories: Optional[str] = Query(None),
    direction: Optional[str] = Query(None, description="all | debits | credits"),
    search: Optional[str] = Query(None),
    amount_field: Optional[str] = Query(None, description="debit | credit | any"),
    amount_min: Optional[float] = Query(None, description="Minimum amount"),
    amount_max: Optional[float] = Query(None, description="Maximum amount"),
    sub_categories: Optional[str] = Query(None, description="Comma-separated Sub_Category values"),
    categories: Optional[str] = Query(None, description="Comma-separated parent Category values (rollup)"),
    is_recurring: Optional[bool] = Query(None, description="Filter by recurring / one-off"),
    spend_basis: str = Query("all", description="all | bank_only | card_only"),
    account_sources: Optional[str] = Query(None, description="Comma-separated BANK,CREDIT_CARD"),
    card_ids: Optional[str] = Query(None, description="Comma-separated Card_ID values"),
    year_months: Optional[str] = Query(None, description="Comma-separated YYYY-MM periods, e.g. 2024-03"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
    sort_by: Optional[str] = Query(None, description="Column to sort by (Date, Narration, Payee_Receiver, Debit_Amount, Credit_Amount, Broad_Category)"),
    sort_order: str = Query("asc", description="asc or desc"),
    engine: Engine = Depends(get_engine),
):
    year_list = _split_int_csv(years)
    month_list = _split_int_csv(months)
    type_list = _split_csv(txn_types)
    cat_list = _split_csv(broad_categories)
    sub_list = _split_csv(sub_categories)
    cat_parent_list = _split_csv(categories)
    ym_list = _split_csv(year_months)
    src_list = _split_csv(account_sources)
    card_list = _split_csv(card_ids)

    df = _get_filtered_df(
        engine,
        years=year_list,
        months=month_list,
        txn_types=type_list,
        broad_categories=cat_list,
        direction=direction,
        search=search,
        amount_field=amount_field,
        amount_min=amount_min,
        amount_max=amount_max,
        year_months=ym_list,
        sub_categories=sub_list,
        categories=cat_parent_list,
        is_recurring=is_recurring,
        spend_basis=spend_basis,
        account_sources=src_list,
        card_ids=card_list,
    )

    if sort_by and sort_by in SORTABLE_COLUMNS and sort_by in df.columns:
        ascending = sort_order.lower() != "desc"
        df = df.sort_values(by=sort_by, ascending=ascending, na_position="last")

    total = len(df)

    # Clamp out-of-range pages instead of returning an empty one. A client that is
    # several pages deep can narrow its filters (or switch drill-down period) and
    # land past the end; an empty response with no way back strands the user on a
    # permanently blank table. The echoed `page` is the effective page.
    total_pages = max(1, (total + page_size - 1) // page_size)
    if page > total_pages:
        page = total_pages

    start = (page - 1) * page_size
    df_page = df.iloc[start: start + page_size]

    cols = [
        "Chq_Ref_Number", "Date", "Narration", "Transaction_Type",
        "Category", "Broad_Category", "Sub_Category", "Payee_Receiver",
        "Debit_Amount", "Credit_Amount", "Closing_Balance", "Details",
        "Reference_ID", "Year", "Month", "Month_Name", "Year_Month",
        "is_recurring",
        # Ledger provenance. The UI needs these to tell a card purchase from a
        # bank debit, and to mark the rows that pay a card bill (which are real
        # ledger rows, deliberately kept here, just not counted as spend).
        "Account_Source", "Is_Settlement", "Card_ID", "Card_Name", "Card_Issuer",
        # Resolved direction (DEBIT / CREDIT) after any user override, plus where
        # it came from, so the UI can show and toggle a correction.
        "Direction", "Direction_Source",
    ]
    display_cols = [c for c in cols if c in df_page.columns]
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "data": _df_to_records(df_page[display_cols]),
    }


# ---------------------------------------------------------------------------
# GET /api/transactions/meta — available filter options
# ---------------------------------------------------------------------------
@router.get("/meta")
def get_meta(engine: Engine = Depends(get_engine)):
    df = get_all_transactions_with_details(engine)
    if df.empty:
        return {
            "years": [], "months": [], "txn_types": [],
            "categories": [], "broad_categories": [], "sub_categories": [],
            "parent_of": {}, "leaves_of": {}, "cards": [],
        }
    df["Broad_Category"] = df["Broad_Category"].fillna("Uncategorized")
    if "Sub_Category" not in df.columns:
        df["Sub_Category"] = df["Broad_Category"]
    pairs = (
        df[["Broad_Category", "Category"]]
        .dropna()
        .drop_duplicates()
        .set_index("Broad_Category")["Category"]
        .astype(str)
        .to_dict()
    )
    # Leaves can legitimately appear under more than one broad category, so the
    # leaf -> broad map is built as broad -> [leaves] instead of being flattened.
    leaves_of: dict[str, list[str]] = {}
    for broad, leaf in (
        df[["Broad_Category", "Sub_Category"]]
        .dropna()
        .drop_duplicates()
        .itertuples(index=False)
    ):
        leaves_of.setdefault(str(broad), []).append(str(leaf))
    return {
        "years": sorted(df["Year"].dropna().unique().astype(int).tolist()),
        "months": sorted(df["Month"].dropna().unique().astype(int).tolist()),
        "txn_types": sorted(df["Transaction_Type"].dropna().unique().tolist()),
        # Three levels of the hierarchy: parent rollup, broad bucket, leaf.
        "categories": sorted(df["Category"].dropna().unique().tolist()),
        "broad_categories": sorted(df["Broad_Category"].dropna().unique().tolist()),
        "sub_categories": sorted(df["Sub_Category"].dropna().unique().tolist()),
        # Which ledgers actually hold data, so the UI can offer the account-source
        # filter only when there is something on both sides of it.
        "account_sources": sorted(
            df["Account_Source"].fillna("BANK").unique().tolist()
        ) if "Account_Source" in df.columns else ["BANK"],
        # Broad -> parent lookup, so the UI can show the full path without
        # shipping the mapping in the bundle.
        "parent_of": pairs,
        # Broad -> its leaves, used to cascade the Tab 3 pickers.
        "leaves_of": leaves_of,
        # The cards actually present in the ledger, so the card view can offer a
        # per-card picker without a second round trip. Taken from the rows rather
        # than the card registry, so a card with no parsed transactions is not
        # offered (it would only ever select an empty result set).
        "cards": _cards_in_ledger(df),
    }


def _cards_in_ledger(df: pd.DataFrame) -> List[dict]:
    """
    The distinct cards that actually have rows in the joined frame.

    Built from the ledger rather than the credit_cards registry so the picker
    cannot offer a card whose statement parsed zero transactions - selecting it
    would show an empty dashboard with no indication of why.
    """
    if df.empty or "Card_ID" not in df.columns:
        return []
    card_rows = df[df["Card_ID"].notna()]
    if card_rows.empty:
        return []
    grouped = (
        card_rows.groupby("Card_ID")
        .agg(
            Card_Name=("Card_Name", "first"),
            Card_Issuer=("Card_Issuer", "first"),
            Txn_Count=("Chq_Ref_Number", "size"),
        )
        .reset_index()
        .sort_values(["Card_Issuer", "Card_Name"], na_position="last")
    )
    return _df_to_records(grouped)



# ---------------------------------------------------------------------------
# GET /api/transactions/kpis — KPI totals for filtered data
# ---------------------------------------------------------------------------
@router.get("/kpis")
def get_kpis(
    years: Optional[str] = Query(None),
    months: Optional[str] = Query(None),
    txn_types: Optional[str] = Query(None),
    broad_categories: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    amount_field: Optional[str] = Query(None, description="debit | credit | any"),
    amount_min: Optional[float] = Query(None, description="Minimum amount"),
    amount_max: Optional[float] = Query(None, description="Maximum amount"),
    sub_categories: Optional[str] = Query(None, description="Comma-separated Sub_Category values"),
    categories: Optional[str] = Query(None, description="Comma-separated parent Category values (rollup)"),
    is_recurring: Optional[bool] = Query(None, description="Filter by recurring / one-off"),
    spend_basis: str = Query("all", description="all | bank_only | card_only"),
    account_sources: Optional[str] = Query(None, description="Comma-separated BANK,CREDIT_CARD"),
    card_ids: Optional[str] = Query(None, description="Comma-separated Card_ID values"),
    year_months: Optional[str] = Query(None, description="Comma-separated YYYY-MM periods, e.g. 2024-03"),
    engine: Engine = Depends(get_engine),
):
    year_list = _split_int_csv(years)
    month_list = _split_int_csv(months)
    type_list = _split_csv(txn_types)
    cat_list = _split_csv(broad_categories)
    sub_list = _split_csv(sub_categories)
    cat_parent_list = _split_csv(categories)
    ym_list = _split_csv(year_months)
    src_list = _split_csv(account_sources)
    card_list = _split_csv(card_ids)

    df = _get_filtered_df(
        engine,
        years=year_list,
        months=month_list,
        txn_types=type_list,
        broad_categories=cat_list,
        direction=direction,
        search=search,
        amount_field=amount_field,
        amount_min=amount_min,
        amount_max=amount_max,
        year_months=ym_list,
        sub_categories=sub_list,
        categories=cat_parent_list,
        is_recurring=is_recurring,
        spend_basis=spend_basis,
        account_sources=src_list,
        card_ids=card_list,
        # A card bill payment is two halves of one transfer, and they can only be
        # double counted when BOTH are in view. The cashflow tiles therefore keep
        # whichever half this view actually contains, and drop the pair only in
        # the combined view. The three spend endpoints below always exclude them,
        # because a cross-CATEGORY total is where the double count bites.
        #
        # The frame is fetched WITH settlements and the correction applied here,
        # so the endpoint can report the rows and rupees that were held out. A
        # filter that dropped them first would make the exclusion invisible.
        include_settlements=True,
    )
    _hide_settlements = _settlement_handling(spend_basis, src_list)
    # Kept so the response can name the settlements it held out. `df` is filtered
    # below for the cashflow totals, but the reporting figures must describe the
    # rows the view matched, not the survivors.
    _frame = df
    if df.empty:
        return {
            "total_credits": 0.0,
            "total_debits": 0.0,
            "net_cashflow": 0.0,
            "settlement_credits": 0.0,
            "settlement_debits": 0.0,
            "total_spend_debits": 0.0,
            "settlement_count": 0,
            "spend_count": 0,
            "filtered_count": 0,
            "total_count": get_total_transaction_count(engine),
        }

    # The CASHFLOW tiles sum every row the view contains, minus the settlements
    # this view's scope requires hiding. A card bill payment is two halves of one
    # transfer and can only be double counted when BOTH are in view, so the
    # correction is keyed on the scope: the combined view drops the pair, while a
    # single-ledger view keeps the one half it actually contains - as inflow on
    # the card, as outflow on the bank.
    _settled_here = (
        df["Is_Settlement"].fillna(False) if "Is_Settlement" in df.columns else False
    )
    if _hide_settlements and bool(_settled_here.any()):
        df = df[~_settled_here]

    total_credits = float(df["Credit_Amount"].sum())
    total_debits = float(df["Debit_Amount"].sum())

    # The SPEND figure always drops settlements, because the category charts do
    # too: paying a card bill is a transfer, not a purchase.
    _all_settled = (
        _frame["Is_Settlement"].fillna(False) if "Is_Settlement" in _frame.columns
        else pd.Series(False, index=_frame.index)
    )
    spend_debits = float(
        _frame.loc[~_all_settled, "Debit_Amount"].sum()
    )
    # The settlement halves are reported for THIS view, not the whole ledger, so
    # the client can label them without a second request. Using global totals
    # would tell the card view about bank-side payments it cannot see.
    settlement_debits = float(_frame.loc[_all_settled, "Debit_Amount"].sum())
    settlement_credits = float(_frame.loc[_all_settled, "Credit_Amount"].sum())
    total_count = get_total_transaction_count(engine)

    return {
        # Cashflow: this view's scope, less the correction where it applies.
        "total_credits": total_credits,
        "total_debits": total_debits,
        "net_cashflow": total_credits - total_debits,
        # Spend: settlements always out, matching the category charts.
        "total_spend_debits": spend_debits,
        "settlement_credits": settlement_credits,
        "settlement_debits": settlement_debits,
        # Row counts mirror the amounts: filtered_count is every row the view
        # holds after the correction (what the tiles add up), spend_count the
        # subset the category charts aggregate, and settlement_count what was
        # held out.
        "settlement_count": int(_all_settled.sum()),
        "spend_count": int((~_all_settled).sum()),
        "filtered_count": len(df),
        "total_count": total_count,
    }


# ---------------------------------------------------------------------------
# GET /api/transactions/summary/timeline — grouped bar data (monthly or yearly)
# ---------------------------------------------------------------------------
@router.get("/summary/timeline")
def get_timeline_summary(
    group_by: str = Query("month", description="month | year"),
    years: Optional[str] = Query(None),
    months: Optional[str] = Query(None),
    txn_types: Optional[str] = Query(None),
    broad_categories: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    amount_field: Optional[str] = Query(None, description="debit | credit | any"),
    amount_min: Optional[float] = Query(None, description="Minimum amount"),
    amount_max: Optional[float] = Query(None, description="Maximum amount"),
    sub_categories: Optional[str] = Query(None, description="Comma-separated Sub_Category values"),
    categories: Optional[str] = Query(None, description="Comma-separated parent Category values (rollup)"),
    is_recurring: Optional[bool] = Query(None, description="Filter by recurring / one-off"),
    spend_basis: str = Query("all", description="all | bank_only | card_only"),
    account_sources: Optional[str] = Query(None, description="Comma-separated BANK,CREDIT_CARD"),
    card_ids: Optional[str] = Query(None, description="Comma-separated Card_ID values"),
    engine: Engine = Depends(get_engine),
):
    year_list = _split_int_csv(years)
    month_list = _split_int_csv(months)
    type_list = _split_csv(txn_types)
    cat_list = _split_csv(broad_categories)
    sub_list = _split_csv(sub_categories)
    cat_parent_list = _split_csv(categories)
    src_list = _split_csv(account_sources)
    card_list = _split_csv(card_ids)

    df = _get_filtered_df(
        engine,
        years=year_list,
        months=month_list,
        txn_types=type_list,
        broad_categories=cat_list,
        direction=direction,
        search=search,
        amount_field=amount_field,
        amount_min=amount_min,
        amount_max=amount_max,
        sub_categories=sub_list,
        categories=cat_parent_list,
        is_recurring=is_recurring,
        spend_basis=spend_basis,
        account_sources=src_list,
        card_ids=card_list,
        # Must agree with the KPI tiles, which is why it uses the same
        # scope-aware rule: a card bill payment is invisible only in the combined
        # view. Scoped to the card, the payment is real inflow and belongs on the
        # credit line; scoped to the bank, it is real outflow on the debit line.
        exclude_settlements=_settlement_handling(spend_basis, src_list),
    )
    if df.empty:
        return []

    if group_by == "year":
        grp = (
            df.groupby("Year")
            .agg(Total_Credit=("Credit_Amount", "sum"), Total_Debit=("Debit_Amount", "sum"), Count=("Date", "count"))
            .reset_index()
        )
        grp["label"] = grp["Year"].astype(str)
    else:
        grp = (
            df.groupby(["Year_Month", "Month_Name"])
            .agg(Total_Credit=("Credit_Amount", "sum"), Total_Debit=("Debit_Amount", "sum"), Count=("Date", "count"))
            .reset_index()
            .sort_values("Year_Month")
        )
        grp["label"] = grp["Year_Month"]

    return _df_to_records(grp)


# ---------------------------------------------------------------------------
# GET /api/transactions/summary/monthly-category — stacked category breakdown
# ---------------------------------------------------------------------------
@router.get("/summary/monthly-category")
def get_monthly_category_summary(
    group_by: str = Query("month", description="month | year"),
    years: Optional[str] = Query(None),
    months: Optional[str] = Query(None),
    txn_types: Optional[str] = Query(None),
    broad_categories: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    amount_field: Optional[str] = Query(None, description="debit | credit | any"),
    amount_min: Optional[float] = Query(None, description="Minimum amount"),
    amount_max: Optional[float] = Query(None, description="Maximum amount"),
    sub_categories: Optional[str] = Query(None, description="Comma-separated Sub_Category values"),
    categories: Optional[str] = Query(None, description="Comma-separated parent Category values (rollup)"),
    is_recurring: Optional[bool] = Query(None, description="Filter by recurring / one-off"),
    spend_basis: str = Query("all", description="all | bank_only | card_only"),
    account_sources: Optional[str] = Query(None, description="Comma-separated BANK,CREDIT_CARD"),
    card_ids: Optional[str] = Query(None, description="Comma-separated Card_ID values"),
    engine: Engine = Depends(get_engine),
):
    year_list = _split_int_csv(years)
    month_list = _split_int_csv(months)
    type_list = _split_csv(txn_types)
    cat_list = _split_csv(broad_categories)
    sub_list = _split_csv(sub_categories)
    cat_parent_list = _split_csv(categories)
    src_list = _split_csv(account_sources)
    card_list = _split_csv(card_ids)

    df = _get_filtered_df(
        engine,
        years=year_list,
        months=month_list,
        txn_types=type_list,
        broad_categories=cat_list,
        direction=direction,
        search=search,
        amount_field=amount_field,
        amount_min=amount_min,
        amount_max=amount_max,
        sub_categories=sub_list,
        categories=cat_parent_list,
        is_recurring=is_recurring,
        spend_basis=spend_basis,
        account_sources=src_list,
        card_ids=card_list,
        # Stacked spend view across categories, so the correction applies. BUT if
        # the caller has already narrowed to a single category, this is a
        # drill-down on that category rather than a cross-category total, so the
        # other half of any settlement is not in view and excluding it would
        # blank the series (Credit_Card_Payment is entirely settlements). Same
        # rule as get_category_trend.
        exclude_settlements=not (
            bool(cat_list) or bool(sub_list) or bool(cat_parent_list)
        ),
    )
    if df.empty:
        return []

    group_col = "Year_Month" if group_by == "month" else "Year"
    grp = (
        df.groupby([group_col, "Broad_Category"])
        .agg(Total_Credit=("Credit_Amount", "sum"), Total_Debit=("Debit_Amount", "sum"), Count=("Date", "count"))
        .reset_index()
        .sort_values(group_col)
    )
    grp["label"] = grp[group_col].astype(str)
    return _df_to_records(grp)


# ---------------------------------------------------------------------------
# GET /api/transactions/summary/category-breakdown — donut chart data
# ---------------------------------------------------------------------------
@router.get("/summary/category-breakdown")
def get_category_breakdown(
    group_col: str = Query("Broad_Category", description="Category | Broad_Category | Sub_Category | Transaction_Type"),
    years: Optional[str] = Query(None),
    months: Optional[str] = Query(None),
    txn_types: Optional[str] = Query(None),
    broad_categories: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    amount_field: Optional[str] = Query(None, description="debit | credit | any"),
    amount_min: Optional[float] = Query(None, description="Minimum amount"),
    amount_max: Optional[float] = Query(None, description="Maximum amount"),
    sub_categories: Optional[str] = Query(None, description="Comma-separated Sub_Category values"),
    categories: Optional[str] = Query(None, description="Comma-separated parent Category values (rollup)"),
    is_recurring: Optional[bool] = Query(None, description="Filter by recurring / one-off"),
    spend_basis: str = Query("all", description="all | bank_only | card_only"),
    account_sources: Optional[str] = Query(None, description="Comma-separated BANK,CREDIT_CARD"),
    card_ids: Optional[str] = Query(None, description="Comma-separated Card_ID values"),
    year_months: Optional[str] = Query(None, description="Comma-separated YYYY-MM periods, e.g. 2024-03"),
    engine: Engine = Depends(get_engine),
):
    year_list = _split_int_csv(years)
    month_list = _split_int_csv(months)
    type_list = _split_csv(txn_types)
    cat_list = _split_csv(broad_categories)
    sub_list = _split_csv(sub_categories)
    cat_parent_list = _split_csv(categories)
    src_list = _split_csv(account_sources)
    ym_list = _split_csv(year_months)
    card_list = _split_csv(card_ids)

    allowed_group_cols = ("Category", "Broad_Category", "Sub_Category", "Transaction_Type")
    if group_col not in allowed_group_cols:
        raise HTTPException(
            status_code=400,
            detail="group_col must be one of: " + ", ".join(allowed_group_cols),
        )

    df = _get_filtered_df(
        engine,
        years=year_list,
        months=month_list,
        txn_types=type_list,
        broad_categories=cat_list,
        direction=direction,
        search=search,
        amount_field=amount_field,
        amount_min=amount_min,
        amount_max=amount_max,
        year_months=ym_list,
        sub_categories=sub_list,
        categories=cat_parent_list,
        is_recurring=is_recurring,
        spend_basis=spend_basis,
        account_sources=src_list,
        card_ids=card_list,
        exclude_settlements=True,
    )
    if df.empty:
        return []

    grp = (
        df.groupby(group_col)
        .agg(Total_Debit=("Debit_Amount", "sum"), Total_Credit=("Credit_Amount", "sum"))
        .reset_index()
        .rename(columns={group_col: "Category"})
    )
    return _df_to_records(grp)


# ---------------------------------------------------------------------------
# GET /api/transactions/balance-trend — closing balance over time
# ---------------------------------------------------------------------------
@router.get("/balance-trend")
def get_balance_trend(
    years: Optional[str] = Query(None),
    months: Optional[str] = Query(None),
    year_months: Optional[str] = Query(None, description="Comma-separated YYYY-MM periods, e.g. 2024-03"),
    sub_categories: Optional[str] = Query(None, description="Comma-separated Sub_Category values"),
    categories: Optional[str] = Query(None, description="Comma-separated parent Category values (rollup)"),
    is_recurring: Optional[bool] = Query(None, description="Filter by recurring / one-off"),
    spend_basis: str = Query("all", description="all | bank_only | card_only"),
    account_sources: Optional[str] = Query(None, description="Comma-separated BANK,CREDIT_CARD"),
    card_ids: Optional[str] = Query(None, description="Comma-separated Card_ID values"),
    engine: Engine = Depends(get_engine),
):
    year_list = _split_int_csv(years)
    month_list = _split_int_csv(months)
    ym_list = _split_csv(year_months)
    src_list = _split_csv(account_sources)
    sub_list = _split_csv(sub_categories)
    cat_parent_list = _split_csv(categories)
    card_list = _split_csv(card_ids)

    df = _get_filtered_df(engine, year_list, month_list, year_months=ym_list, sub_categories=sub_list, categories=cat_parent_list, is_recurring=is_recurring, spend_basis=spend_basis, account_sources=src_list, card_ids=card_list)
    if df.empty or "Closing_Balance" not in df.columns:
        return []

    df_sorted = df.sort_values("Date")[["Date", "Closing_Balance"]].copy()
    df_sorted["Date"] = pd.to_datetime(df_sorted["Date"]).dt.strftime("%Y-%m-%d")
    return _df_to_records(df_sorted)


# ---------------------------------------------------------------------------
# GET /api/transactions/category-trend — single category monthly trend
# ---------------------------------------------------------------------------
@router.get("/category-trend")
def get_category_trend(
    category: str = Query(""),
    group_col: str = Query("Broad_Category", description="Category | Broad_Category | Sub_Category"),
    years: Optional[str] = Query(None),
    months: Optional[str] = Query(None),
    year_months: Optional[str] = Query(None, description="Comma-separated YYYY-MM periods, e.g. 2024-03"),
    sub_categories: Optional[str] = Query(None, description="Comma-separated Sub_Category values"),
    categories: Optional[str] = Query(None, description="Comma-separated parent Category values (rollup)"),
    is_recurring: Optional[bool] = Query(None, description="Filter by recurring / one-off"),
    spend_basis: str = Query("all", description="all | bank_only | card_only"),
    account_sources: Optional[str] = Query(None, description="Comma-separated BANK,CREDIT_CARD"),
    card_ids: Optional[str] = Query(None, description="Comma-separated Card_ID values"),
    engine: Engine = Depends(get_engine),
):
    """
    Monthly trend for one level of the category hierarchy. `category` is a value
    in the column named by `group_col`, so selecting a parent (e.g. Housing) can
    be charted just as a leaf (e.g. Rent_Brokerage) can. An empty `category`
    charts the whole filtered set.
    """
    year_list = _split_int_csv(years)
    month_list = _split_int_csv(months)
    ym_list = _split_csv(year_months)
    src_list = _split_csv(account_sources)
    sub_list = _split_csv(sub_categories)
    cat_parent_list = _split_csv(categories)
    card_list = _split_csv(card_ids)

    df = _get_filtered_df(
        engine, year_list, month_list, year_months=ym_list,
        sub_categories=sub_list, categories=cat_parent_list,
        is_recurring=is_recurring, spend_basis=spend_basis,
        account_sources=src_list, card_ids=card_list,
        # SINGLE-CATEGORY DRILL-DOWN, so settlements are kept. The double-count
        # correction exists to stop a card purchase appearing alongside the bill
        # that paid for it - which only happens when several categories are
        # aggregated together. Scoped to one category the other half is not in
        # view, so excluding settlements would simply delete the whole series:
        # Credit_Card_Payment is 100% settlement, so the trend came back empty
        # for it. An empty `category` still charts everything at once, and that
        # IS a multi-category total, so it keeps the correction.
        exclude_settlements=not bool(category),
    )
    if df.empty:
        return []

    if group_col not in ("Category", "Broad_Category", "Sub_Category"):
        raise HTTPException(
            status_code=400,
            detail="group_col must be Category, Broad_Category, or Sub_Category",
        )

    scope = df
    if category:
        if group_col not in scope.columns:
            return []
        scope = scope[scope[group_col] == category]
    if scope.empty:
        return []

    trend = (
        scope.groupby("Year_Month")
        .agg(Total_Debit=("Debit_Amount", "sum"), Total_Credit=("Credit_Amount", "sum"))
        .reset_index()
        .sort_values("Year_Month")
    )
    return _df_to_records(trend)


# ---------------------------------------------------------------------------
# POST /api/transactions/upload — parse and store an uploaded statement file
# ---------------------------------------------------------------------------
@router.post("/upload")
async def upload_statement(
    file: UploadFile = File(...),
    engine: Engine = Depends(get_engine),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    allowed_exts = {".xls", ".xlsx", ".csv", ".pdf"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_exts:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}. Use .xls, .xlsx, .csv, or .pdf")

    try:
        contents = await file.read()
        file_obj = io.BytesIO(contents)
        tx_df = load_and_clean_statement(file_obj, filename=file.filename)
        narr_df = parse_narrations_dataframe(tx_df)
        store_data_in_db(engine, tx_df, narr_df)
        return {
            "success": True,
            "imported": len(tx_df),
            "filename": file.filename,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# GET /api/transactions/export — full filtered set as CSV
# ---------------------------------------------------------------------------
@router.get("/export")
def export_transactions(
    years: Optional[str] = Query(None),
    months: Optional[str] = Query(None),
    txn_types: Optional[str] = Query(None),
    broad_categories: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    amount_field: Optional[str] = Query(None, description="debit | credit | any"),
    amount_min: Optional[float] = Query(None),
    amount_max: Optional[float] = Query(None),
    sub_categories: Optional[str] = Query(None, description="Comma-separated Sub_Category values"),
    categories: Optional[str] = Query(None, description="Comma-separated parent Category values (rollup)"),
    is_recurring: Optional[bool] = Query(None, description="Filter by recurring / one-off"),
    spend_basis: str = Query("all", description="all | bank_only | card_only"),
    account_sources: Optional[str] = Query(None, description="Comma-separated BANK,CREDIT_CARD"),
    card_ids: Optional[str] = Query(None, description="Comma-separated Card_ID values"),
    year_months: Optional[str] = Query(None, description="Comma-separated YYYY-MM periods"),
    engine: Engine = Depends(get_engine),
):
    """
    Streams every row matching the active filters as CSV — not just the current
    page — so exports match what the user sees across the whole filtered set.
    """
    df = _get_filtered_df(
        engine,
        years=_split_int_csv(years),
        months=_split_int_csv(months),
        txn_types=_split_csv(txn_types),
        broad_categories=_split_csv(broad_categories),
        direction=direction,
        search=search,
        amount_field=amount_field,
        amount_min=amount_min,
        amount_max=amount_max,
        year_months=_split_csv(year_months),
        sub_categories=_split_csv(sub_categories),
        categories=_split_csv(categories),
        is_recurring=is_recurring,
        spend_basis=spend_basis,
        account_sources=_split_csv(account_sources),
        card_ids=_split_csv(card_ids),
    )

    if "Date" in df.columns:
        df = df.copy()
        df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
        if "Value_Date" in df.columns:
            df["Value_Date"] = pd.to_datetime(df["Value_Date"], errors="coerce").dt.strftime("%Y-%m-%d")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"statement_filtered_{stamp}.csv"
    return StreamingResponse(
        iter([df.to_csv(index=False).encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# POST /api/transactions/load-sample — ingest a bundled sample statement
# ---------------------------------------------------------------------------
def _resolve_sample_statement():
    """
    Locates a statement file to seed an empty database with.

    Prefers config.DEFAULT_STATEMENT_PATH, then falls back to the most recently
    modified PII-masked statement under masked/ so the sample loader works on a
    fresh clone (the unmasked original is not distributed).
    """
    if os.path.exists(DEFAULT_STATEMENT_PATH):
        return DEFAULT_STATEMENT_PATH

    masked_dir = os.path.join(os.path.dirname(DEFAULT_STATEMENT_PATH), "masked")
    if os.path.isdir(masked_dir):
        candidates = [
            os.path.join(masked_dir, name)
            for name in os.listdir(masked_dir)
            if name.lower().endswith((".xls", ".xlsx"))
        ]
        if candidates:
            return max(candidates, key=os.path.getmtime)
    return None


@router.post("/load-sample")
def load_sample_statement(engine: Engine = Depends(get_engine)):
    """
    Parses and stores a bundled sample statement so a fresh install has data to
    explore.
    """
    sample_path = _resolve_sample_statement()
    if not sample_path:
        raise HTTPException(
            status_code=404,
            detail=(
                "No sample statement found. Upload a statement manually, or place "
                f"one at {DEFAULT_STATEMENT_PATH} (or in masked/)."
            ),
        )
    try:
        tx_df = load_and_clean_statement(sample_path)
        narr_df = parse_narrations_dataframe(tx_df)
        store_data_in_db(engine, tx_df, narr_df)
        return {
            "success": True,
            "imported": len(tx_df),
            "filename": os.path.basename(sample_path),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Debit/credit overrides
#
# Deliberately a mirror of the category cascade (same rule types, same priority,
# same exclude-and-pin behaviour) so the same UI drives both. The correction is
# stored in direction_rules and applied at read time, which means a re-import of
# the statement cannot silently undo it.
# ---------------------------------------------------------------------------
_DIRECTION_MATCHERS = {"txn", "merchant", "narration"}


def _find_direction_matches(df, rule_type, rule_key):
    """Rows a direction rule would affect. Same semantics as the category rule
    matcher: 'txn' is an exact reference, 'merchant' a payee substring and
    'narration' a Narration/Details substring. All case-insensitive."""
    key = str(rule_key or "").strip().upper()
    if not key:
        return df.iloc[0:0]

    def _col(name):
        if name not in df.columns:
            return None
        return df[name].fillna("").astype(str).str.strip().str.upper()

    chq = _col("Chq_Ref_Number")
    if rule_type == "txn":
        mask = chq.eq(key) if chq is not None else pd.Series(False, index=df.index)
    elif rule_type == "merchant":
        payee = _col("Payee_Receiver")
        mask = (
            payee.str.contains(key, regex=False, na=False)
            if payee is not None
            else pd.Series(False, index=df.index)
        )
    else:
        narr = _col("Narration")
        details = _col("Details")
        mask = (
            narr.str.contains(key, regex=False, na=False)
            if narr is not None
            else pd.Series(False, index=df.index)
        )
        if details is not None:
            mask = mask | details.str.contains(key, regex=False, na=False)
    return df[mask]


class DirectionRule(BaseModel):
    rule_type: str
    rule_key: str
    direction: str


class ApplyDirectionRulesRequest(BaseModel):
    rules: List[DirectionRule]


class PreviewDirectionRequest(BaseModel):
    rule_type: str
    rule_key: str
    direction: str = "CREDIT"


class ApplyDirectionCascadeRequest(BaseModel):
    rule_type: str
    rule_key: str
    direction: str
    excluded_chq_refs: List[str] = []


class DeleteDirectionRulesRequest(BaseModel):
    rule_type: str
    rule_keys: List[str]


def _check_direction(direction):
    value = str(direction or "").strip().upper()
    if value not in ("CREDIT", "DEBIT"):
        raise HTTPException(
            status_code=400, detail="direction must be 'CREDIT' or 'DEBIT'"
        )
    return value


def _check_rule_type(rule_type):
    if rule_type not in _DIRECTION_MATCHERS:
        raise HTTPException(
            status_code=400,
            detail=f"rule_type must be one of {sorted(_DIRECTION_MATCHERS)}",
        )
    return rule_type


# GET /api/transactions/direction-rules — the rules currently in force
@router.get("/direction-rules")
def list_direction_rules(engine: Engine = Depends(get_engine)):
    with engine.connect() as connection:
        rows = connection.execute(
            text(f"SELECT id, rule_type, rule_key, direction FROM {TABLE_DIRECTION_RULES}")
        ).fetchall()
    return [
        {"id": r[0], "rule_type": r[1], "rule_key": r[2], "direction": r[3]}
        for r in rows
    ]


# POST /api/transactions/direction-rules/preview — what a rule would affect
@router.post("/direction-rules/preview")
def preview_direction_rule(body: PreviewDirectionRequest, engine: Engine = Depends(get_engine)):
    rule_type = _check_rule_type(body.rule_type)
    direction = _check_direction(body.direction)
    df = get_all_transactions_with_details(engine)
    matched = _find_direction_matches(df, rule_type, body.rule_key)
    # Only rows that would actually CHANGE are worth showing: a rule that already
    # agrees with the current value is a no-op, and listing it would mislead the
    # user into thinking something will happen.
    current = (
        matched["Direction"].fillna("").astype(str).str.upper()
        if "Direction" in matched.columns
        else pd.Series("", index=matched.index)
    )
    changing = matched[current.ne(direction)]
    cols = [
        "Chq_Ref_Number", "Date", "Narration", "Broad_Category", "Sub_Category",
        "Payee_Receiver", "Debit_Amount", "Credit_Amount", "Direction",
        "Is_Settlement", "Card_Name", "Account_Source",
    ]
    display_cols = [c for c in cols if c in changing.columns]
    return {
        "total_matched": len(matched),
        "total": len(changing),
        "transactions": _df_to_records(changing[display_cols]),
    }


# POST /api/transactions/direction-rules — upsert override rules
@router.post("/direction-rules")
def apply_direction_rule_list(
    body: ApplyDirectionRulesRequest, engine: Engine = Depends(get_engine)
):
    rules = [
        (_check_rule_type(r.rule_type), r.rule_key, _check_direction(r.direction))
        for r in body.rules
    ]
    applied = apply_direction_rules(engine, rules)
    return {"success": True, "applied": applied}


# POST /api/transactions/direction-rules/apply-cascade — with per-row exclusions
@router.post("/direction-rules/apply-cascade")
def apply_direction_cascade(
    body: ApplyDirectionCascadeRequest, engine: Engine = Depends(get_engine)
):
    rule_type = _check_rule_type(body.rule_type)
    rule_key = body.rule_key.strip()
    direction = _check_direction(body.direction)
    if not rule_key:
        raise HTTPException(status_code=400, detail="rule_key cannot be empty")

    df = get_all_transactions_with_details(engine)
    matched = _find_direction_matches(df, rule_type, rule_key)
    excluded_set = {str(r).strip().upper() for r in body.excluded_chq_refs}

    if rule_type == "txn":
        applied = apply_direction_rules(engine, [("txn", rule_key, direction)])
        return {"success": True, "applied": applied}

    included_refs = [
        str(r).strip()
        for r in matched["Chq_Ref_Number"].tolist()
        if str(r).strip().upper() not in excluded_set
    ]

    # Clear stale per-transaction pins on the included rows so the broader rule
    # wins cleanly, exactly as the category cascade does.
    if rule_type == "narration" and included_refs:
        delete_direction_rules(engine, "txn", included_refs)

    rules = [(rule_type, rule_key, direction)]

    # An excluded row is pinned back to the direction it has right now, so it
    # cannot be swept up by the broader rule and cannot drift.
    for ref in body.excluded_chq_refs:
        ref_str = str(ref).strip()
        row = matched[
            matched["Chq_Ref_Number"].astype(str).str.strip().str.upper()
            == ref_str.upper()
        ]
        if not row.empty:
            current = str(row.iloc[0].get("Direction") or "DEBIT").upper()
            if current in ("CREDIT", "DEBIT"):
                rules.append(("txn", ref_str, current))

    applied = apply_direction_rules(engine, rules)
    return {"success": True, "applied": applied, "included": len(included_refs)}


# POST /api/transactions/direction-rules/delete — delete rules by key
@router.post("/direction-rules/delete")
def delete_direction_rule_list(
    body: DeleteDirectionRulesRequest, engine: Engine = Depends(get_engine)
):
    deleted = delete_direction_rules(engine, body.rule_type, body.rule_keys)
    return {"success": True, "deleted": deleted}


# ---------------------------------------------------------------------------
# POST /api/transactions/recategorize — re-run parser over all stored rows
# ---------------------------------------------------------------------------
@router.post("/recategorize")
def recategorize(engine: Engine = Depends(get_engine)):
    try:
        old_counts, new_counts = recategorize_all_narrations(engine)
        return {
            "success": True,
            "old_counts": old_counts,
            "new_counts": new_counts,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
