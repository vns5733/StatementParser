"""
ingest_cards.py — import credit-card statement PDFs into the database.

    python ingest_cards.py                       # every PDF in CreditCard/
    python ingest_cards.py --dir CreditCard
    python ingest_cards.py CreditCard/one.pdf    # a single file
    python ingest_cards.py --no-ledger           # card tables only, no projection

For each statement this writes three things:
  * credit_cards / credit_card_statements / credit_card_transactions
  * the projected rows in the shared `transactions` + `narration_details`
    tables, so card spend appears in the existing dashboard aggregates

Re-running is safe: every key is deterministic, so a statement imported twice
produces the same rows. The printed spend variance compares the sum of the
parsed rows against the cycle total the issuer printed - a non-zero value means
rows were dropped or double counted and is worth looking at.
"""

import argparse
import glob
import os
import sys

import pandas as pd

from card_loader import load_card_statement
from card_store import store_card_statement, to_ledger_rows, _prepare_rows
from db import (
    create_mysql_connection,
    init_db_tables,
    insert_ignore_on_duplicate,
    invalidate_transaction_cache,
)
from narration_parser import parse_narrations_dataframe

DEFAULT_DIR = "CreditCard"


def _ingest_ledger(engine, ledger_df, meta):
    """
    Writes the projected card rows into the shared ledger so the existing
    dashboard aggregates pick them up unchanged.
    """
    if ledger_df.empty:
        return 0

    tx_cols = [
        "Date", "Narration", "Value_Date", "Debit_Amount", "Credit_Amount",
        "Chq_Ref_Number", "Closing_Balance", "Account_Source", "Card_ID",
        "Statement_ID",
    ]
    tx_df = ledger_df[tx_cols].copy()
    tx_df["Date"] = pd.to_datetime(tx_df["Date"])

    narr_df = parse_narrations_dataframe(tx_df)

    # The issuer's own category wins over the keyword parser: it is the card
    # network's classification, not a guess from the merchant string.
    issuer_cat = (
        ledger_df["Statement_Category"].fillna("").astype(str).str.strip()
    )
    if issuer_cat.ne("").any():
        apply_mask = issuer_cat.ne("")
        narr_df.loc[apply_mask, "Broad_Category"] = issuer_cat[apply_mask]
        # Re-derive the leaf so it belongs to the issuer's parent bucket; a leaf
        # chosen for the keyword-derived parent would contradict the new one.
        from category_rules import assign_sub_category
        masked_narr = ledger_df["Narration"].fillna("").tolist()
        narr_df.loc[apply_mask, "Sub_Category"] = [
            assign_sub_category(broad, masked_narr[i], d, p, r)
            for i, (broad, d, p, r) in enumerate(zip(
                narr_df.loc[apply_mask, "Broad_Category"],
                narr_df.loc[apply_mask, "Details"].fillna(""),
                narr_df.loc[apply_mask, "Payee_Receiver"].fillna(""),
                narr_df.loc[apply_mask, "Reference_ID"].fillna(""),
            ))
        ]

    with engine.begin() as connection:
        tx_df.to_sql("transactions", con=connection, if_exists="append",
                     index=False, method=insert_ignore_on_duplicate)
        narr_df.to_sql("narration_details", con=connection, if_exists="append",
                       index=False, method=insert_ignore_on_duplicate)

    invalidate_transaction_cache()
    return len(tx_df)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("files", nargs="*", help="Specific statement PDFs.")
    parser.add_argument("--dir", default=DEFAULT_DIR, help=f"Folder to scan (default: {DEFAULT_DIR})")
    parser.add_argument("--no-ledger", action="store_true",
                        help="Populate only the card tables, not the shared ledger.")
    args = parser.parse_args()

    paths = args.files or sorted(glob.glob(os.path.join(args.dir, "*.pdf")))
    if not paths:
        print(f"No PDFs found in '{args.dir}'.")
        sys.exit(1)

    engine = create_mysql_connection()
    init_db_tables(engine)

    print(f"{'FILE':56} {'ISSUER':7} {'CARD':18} {'ROWS':>5} {'SPEND':>13} {'VARIANCE':>10}")
    print("-" * 118)

    failures = 0
    for path in paths:
        name = os.path.basename(path)
        try:
            df, meta = load_card_statement(path)
            result = store_card_statement(engine, df, meta)

            if not args.no_ledger:
                txn_df = _prepare_rows(
                    result["Statement_ID"], result["Card_ID"], df,
                    payments_received=meta.get("Payments_Received"),
                )
                ledger_df = to_ledger_rows(txn_df, meta)
                result["Ledger_Rows"] = _ingest_ledger(engine, ledger_df, meta)

            variance = result["Spend_Variance"]
            var_text = f"{variance:+,.2f}" if variance is not None else "n/a"
            print(f"{name[:56]:56} {result['Issuer']:7} {str(result['Card_Name'])[:18]:18} "
                  f"{result['Transactions']:>5} {result['Parsed_Spend']:>13,.2f} {var_text:>10}")
            if result.get("Settlement_Rows"):
                print(f"{'':56}   settlements: {result['Settlement_Rows']} "
                      f"(excluded from spend)")
            if result.get("Issuer_Categorised"):
                print(f"{'':56}   issuer-categorised rows: {result['Issuer_Categorised']}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"{name[:56]:56} ERROR: {type(exc).__name__}: {exc}")

    print()
    print(f"Done: {len(paths) - failures} imported, {failures} failed.")


if __name__ == "__main__":
    main()
