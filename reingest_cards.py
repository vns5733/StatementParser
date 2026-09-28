"""
Re-ingest every card statement from scratch.

Card identity is derived from the filename, so changing that rule changes the
generated ids. The card tables therefore have to be cleared before a re-run,
otherwise the old rows survive as orphans alongside the new ones.

Usage: python reingest_cards.py [--dir CreditCard]
"""
import argparse
import glob
import os
import subprocess
import sys

from sqlalchemy import text

from db import create_mysql_connection


def clear_card_data():
    engine = create_mysql_connection()
    with engine.begin() as c:
        # narration_details references transactions, so children go first.
        c.execute(text("DELETE FROM narration_details WHERE Chq_Ref_Number LIKE 'CC:%'"))
        c.execute(text("DELETE FROM transactions WHERE Account_Source IS NOT NULL"))
        c.execute(text("DELETE FROM credit_card_transactions"))
        c.execute(text("DELETE FROM credit_card_statements"))
        c.execute(text("DELETE FROM credit_cards"))
    print("cleared existing card data")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="masked/CreditCard")
    ap.add_argument("--keep", action="store_true",
                    help="Do not clear first (only safe if the identity rule is unchanged)")
    args = ap.parse_args()

    n = len(glob.glob(os.path.join(args.dir, "*.pdf")))
    if n == 0:
        print(f"No PDFs in {args.dir}")
        sys.exit(1)

    if not args.keep:
        clear_card_data()

    print(f"ingesting {n} statement(s) from {args.dir}...\n")
    result = subprocess.run(
        [sys.executable, "ingest_cards.py", "--dir", args.dir],
        capture_output=True, text=True,
    )
    tail = [ln for ln in result.stdout.splitlines()
            if "ERROR" in ln or ln.startswith("Done:")]
    for ln in tail[-20:]:
        print(ln)
    if result.returncode != 0:
        print(result.stderr[-2000:])


if __name__ == "__main__":
    main()
