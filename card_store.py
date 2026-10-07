"""
card_store.py — persistence for credit-card statements.

Kept separate from db.py so the bank-statement ledger code stays focused: the
card tables have their own shape (one row per card, one per billing cycle, one
per transaction) and their own lifecycle (a card is re-imported every month,
its identity is stable across statements).

Schema
------
credit_cards
    One row per physical card. Identity is the (Issuer, Last4) pair, which is
    stable across statements even though the full number is masked.

credit_card_statements
    One row per billing cycle. Holds the issuer's own summary figures, which are
    the independent check on the parsed transaction rows: if the sum of the
    parsed debits does not agree with the printed PURCHASES/DEBIT, rows were
    dropped or double counted. `Spend_Mix` stores the issuer's own statement
    level category split (HDFC "Purchase Indicator").

credit_card_transactions
    One row per transaction, with the issuer's category preserved in
    `Statement_Category`. That value is preferred over keyword guessing when
    the ledger layer categorises the row.

Ingestion into the shared ledger
--------------------------------
`to_ledger_rows` projects a parsed statement onto the existing `transactions`
shape so the dashboard aggregates bank and card spend together. Card purchases
become debits and refunds credits. The `Credit_Card_Payment` debit in the bank
ledger is the mirror image of a card settlement row: both are flagged
`Is_Settlement` at read time so neither is counted twice as spend.
"""

import hashlib
import json
import os
import re
import uuid

import pandas as pd
from sqlalchemy import text

from config import (
    TABLE_CREDIT_CARDS,
    TABLE_CREDIT_CARD_STATEMENTS,
    TABLE_CREDIT_CARD_TRANSACTIONS,
)

SOURCE_CARD = "CREDIT_CARD"
SOURCE_BANK = "BANK"

# A bank debit that repays a card. Matched against card statements to prove the
# money that left the bank is the money the issuer billed.
BANK_CC_PAYMENT = re.compile(r"(?i)CREDIT[_\s]*CARD[_\s]*PAYMENT")


def _load_reconciliation_frames(engine):
    """Reads the card statements and the bank-side card payments."""
    with engine.connect() as connection:
        statements = pd.read_sql(
            text(f"""
                SELECT s.Statement_ID, s.Card_ID, s.Issuer, s.Card_Name,
                       s.Statement_Date, s.Due_Date, s.Period_Start, s.Period_End,
                       s.Total_Due, s.Payments_Received, s.Total_Spend,
                       s.Parsed_Spend, s.Txn_Count
                FROM {TABLE_CREDIT_CARD_STATEMENTS} s
            """),
            con=connection,
        )

    # The bank side is read from the SHARED resolved ledger rather than a raw
    # JOIN on narration_details. The stored Broad_Category is the parser's
    # opinion; the user can override it with a category_rules entry, and a row
    # reclassified to Credit_Card_Payment by a rule is just as much a card
    # settlement as one the parser found. Reading the stored column made those
    # payments invisible here while the charts counted them as spend, so the two
    # views of the same payment disagreed. Is_Settlement is derived from the
    # resolved category, so it already encodes exactly this set.
    import db  # lazy: db imports this module

    ledger = db.get_all_transactions_with_details(engine)
    if ledger.empty:
        return statements, pd.DataFrame(
            columns=["Chq_Ref_Number", "Date", "Narration", "Debit_Amount"]
        )

    debits = ledger.loc[
        ledger["Is_Settlement"].fillna(False)
        & ledger["Debit_Amount"].fillna(0).gt(0)
        & (ledger["Account_Source"].fillna("BANK").str.upper() == "BANK"),
        ["Chq_Ref_Number", "Date", "Narration", "Debit_Amount"],
    ].copy()
    return statements, debits.reset_index(drop=True)


def reconcile_card_payments(engine, tolerance=1.0, grace_days=10):
    """
    Matches each card statement to the bank debit that paid it.

    For every card statement, the best candidate is the bank row categorised
    `Credit_Card_Payment` whose amount is closest to the billed total and whose
    date falls between the cycle start and the due date plus a grace window.
    Each bank debit is consumed once, so one large payment cannot be claimed by
    several statements.

    A partial payment will not equal Total_Due, so it surfaces as a variance
    rather than being force-fitted. A card cycle whose payment falls outside the
    imported bank range legitimately shows as unmatched, which is why the result
    reports both directions rather than just the happy path.
    """
    statements, debits = _load_reconciliation_frames(engine)
    return _match_and_summarise(statements, debits, tolerance, grace_days)

def _match_and_summarise(statements, debits, tolerance, grace_days):
    """
    Pairs already-loaded frames. Pure: no database access, so the pairing rules
    are testable on their own.
    """
    for col in ("Statement_Date", "Due_Date", "Period_Start", "Period_End"):
        if col in statements.columns:
            statements[col] = pd.to_datetime(statements[col], errors="coerce")
    if not debits.empty:
        debits = debits.copy()
        debits["Date"] = pd.to_datetime(debits["Date"], errors="coerce")
        debits = debits.dropna(subset=["Date", "Debit_Amount"]).reset_index(drop=True)

    used = set()
    matched, unmatched_statements = [], []

    for _, stmt in statements.sort_values("Period_End").iterrows():
        # The amount the bank should have paid for this cycle. Prefer the billed
        # total; fall back to what the issuer recorded as received.
        target = stmt["Total_Due"]
        basis = "total_due"
        if pd.isna(target):
            target = stmt["Payments_Received"]
            basis = "payments_received"
        if pd.isna(target):
            target = stmt["Total_Spend"]
            basis = "total_spend"

        # A missing due date is normal on some statements, so fall back to the
        # cycle end plus a full cycle rather than refusing to match at all.
        start = stmt["Period_Start"] if pd.notna(stmt["Period_Start"]) else stmt["Period_End"]
        anchor = stmt["Due_Date"] if pd.notna(stmt["Due_Date"]) else stmt["Period_End"]
        end = anchor + pd.Timedelta(days=grace_days)
        if pd.isna(start) or pd.isna(end):
            unmatched_statements.append({**stmt.to_dict(), "reason": "no period/due date"})
            continue
        if pd.isna(target):
            unmatched_statements.append({**stmt.to_dict(), "reason": "no billed amount"})
            continue

        window = debits[
            (debits["Date"] >= start)
            & (debits["Date"] <= end)
            & (~debits.index.isin(used))
        ]
        if window.empty:
            unmatched_statements.append({**stmt.to_dict(), "reason": "no bank payment in window"})
            continue

        diffs = (window["Debit_Amount"] - float(target)).abs()
        best = diffs.idxmin()
        variance = float(window.loc[best, "Debit_Amount"]) - float(target)
        if abs(variance) > tolerance:
            unmatched_statements.append({
                **stmt.to_dict(),
                "reason": "closest bank payment differs by more than tolerance",
                "closest_amount": float(window.loc[best, "Debit_Amount"]),
                "variance": round(variance, 2),
            })
            continue

        used.add(best)
        matched.append({
            "Statement_ID": stmt["Statement_ID"],
            "Card_ID": stmt["Card_ID"],
            "Card_Name": stmt["Card_Name"],
            "Issuer": stmt["Issuer"],
            "Statement_Date": stmt["Statement_Date"],
            "Due_Date": stmt["Due_Date"],
            "Bank_Chq_Ref": debits.loc[best, "Chq_Ref_Number"],
            "Bank_Payment_Date": debits.loc[best, "Date"],
            "Bank_Amount": float(debits.loc[best, "Debit_Amount"]),
            "Billed_Amount": float(target),
            "Match_Basis": basis,
            "Variance": round(variance, 2),
            "Statement_Spend": _num(stmt["Total_Spend"]),
            "Parsed_Spend": _num(stmt["Parsed_Spend"]),
        })

    return {
        "matched": matched,
        "unmatched_statements": unmatched_statements,
        "unmatched_bank_debits": debits[~debits.index.isin(used)].to_dict("records"),
        "summary": {
            "statements": len(statements),
            "bank_debits": len(debits),
            "matched": len(matched),
            "unmatched_statements": len(unmatched_statements),
            "unmatched_bank_debits": int((~debits.index.isin(used)).sum()),
            "variance_total": round(sum(m["Variance"] for m in matched), 2),
        },
    }


def _num(value):
    return None if value is None or pd.isna(value) else float(value)


# A bank debit that repays a card. Matched against card statements to prove the
# money that left the bank is the money the issuer billed.
BANK_CC_PAYMENT = re.compile(r"(?i)CREDIT[_\s]*CARD[_\s]*PAYMENT")

# A card statement row that settles a balance rather than spending. On HDFC
# this is "BPPY CC PAYMENT ... (Ref# ...)"; ICICI shows "BBPS Payment received"
# with a CR marker. These must not be counted as spend, because the underlying
# purchases are already in the ledger as card debits.
#
# NETBANKING TRANSFER / TELE TRANSFER CREDIT are the same event described
# generically: the issuer banks the bill payment without naming the card. They
# were missing here, so 65 rows worth 20.6L of real bill payments were left
# unflagged - they surfaced as card INFLOW, and the combined view's settlement
# exclusion could not remove them because they were never on the list.
SETTLEMENT_RE = re.compile(
    r"(?i)\b(CC\s*PAYMENT|CARD\s*PAYMENT|BPPY|PREPAID\s*LOAD|TOP\s*UP|"
    r"BBPS\s*PAYMENT\s*RECEIVED|PAYMENT\s*RECEIVED|REPAYMENT|"
    r"NETBANKING\s*TRANSFER|TELE\s*TRANSFER\s*CREDIT|"
    r"NET\s*BANKING\s*TRANSFER|NEFT\s*TRANSFER|IB\s*TRANSFER)\b"
)


def init_card_tables(connection):
    """Creates the three card tables. Idempotent."""
    connection.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_CREDIT_CARDS} (
            Card_ID VARCHAR(64) PRIMARY KEY,
            Issuer VARCHAR(30),
            Card_Name VARCHAR(60),
            Last4 VARCHAR(4),
            Credit_Limit FLOAT,
            First_Seen DATETIME,
            Last_Seen DATETIME
        )
    """))

    connection.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_CREDIT_CARD_STATEMENTS} (
            Statement_ID VARCHAR(64) PRIMARY KEY,
            Card_ID VARCHAR(64),
            Issuer VARCHAR(30),
            Card_Name VARCHAR(60),
            Statement_Date DATETIME,
            Due_Date DATETIME,
            Period_Start DATETIME,
            Period_End DATETIME,
            Previous_Dues FLOAT,
            Payments_Received FLOAT,
            Total_Spend FLOAT,
            Finance_Charges FLOAT,
            Total_Due FLOAT,
            Minimum_Due FLOAT,
            Credit_Limit FLOAT,
            Available_Credit_Limit FLOAT,
            Txn_Count INT,
            Parsed_Spend FLOAT,
            Parsed_Refunds FLOAT,
            Spend_Mix TEXT,
            Source_File VARCHAR(255),
            Imported_At DATETIME,
            INDEX idx_cc_stmt_card (Card_ID),
            INDEX idx_cc_stmt_date (Statement_Date),
            FOREIGN KEY (Card_ID) REFERENCES {TABLE_CREDIT_CARDS}(Card_ID)
        )
    """))

    connection.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_CREDIT_CARD_TRANSACTIONS} (
            CC_Txn_ID VARCHAR(64) PRIMARY KEY,
            Statement_ID VARCHAR(64),
            Card_ID VARCHAR(64),
            Txn_Date DATETIME,
            Txn_Time VARCHAR(10),
            Description TEXT,
            Amount FLOAT,
            Direction VARCHAR(10),
            Rewards VARCHAR(20),
            Card_Ref VARCHAR(60),
            Statement_Category VARCHAR(50),
            Statement_Category_Raw VARCHAR(40),
            Is_Settlement TINYINT DEFAULT 0,
            Page INT,
            Ledger_Chq_Ref VARCHAR(250),
            INDEX idx_cc_txn_stmt (Statement_ID),
            INDEX idx_cc_txn_card (Card_ID),
            INDEX idx_cc_txn_date (Txn_Date),
            FOREIGN KEY (Statement_ID)
                REFERENCES {TABLE_CREDIT_CARD_STATEMENTS}(Statement_ID)
        )
    """))


def make_card_id(issuer, last4, fallback_token=None):
    """
    Stable card identity.

    Prefers the issuer plus the last four digits, which is stable across every
    statement for that card. Masked statements usually expose no digits at all
    though, and then two different cards would collapse onto one identity and
    their spend would merge.

    The filename is the fallback, and its FIRST underscore-delimited token is
    what identifies the card: statements are named
    `4854XXXXXXXXXX855_16-09-2026_848.pdf`, where the token carries the issuer's
    BIN plus the masked digits, and only the date varies after it. Using the
    whole stem instead would make every monthly file its own "card", which is
    exactly the mistake this avoided.
    """
    if last4:
        token = f"{str(issuer or '').upper()}:{last4}"
    else:
        stem = os.path.splitext(os.path.basename(str(fallback_token or "unknown")))[0]
        card_token = stem.split("_")[0].upper() or stem.upper() or "UNKNOWN"
        token = f"{str(issuer or '').upper()}:NO-LAST4:{card_token}"
    return "CC_" + hashlib.sha1(token.encode()).hexdigest()[:16].upper()



def make_statement_id(card_id, statement_date, period_end, source_file=None):
    """
    One statement per card per billing cycle.

    The identity is (card, cycle). The source filename is deliberately NOT part
    of the token when the cycle dates are usable, because the same statement is
    often imported twice under two names - most commonly a masked copy
    (`..._masked.pdf`) alongside the original. Folding the filename in gave the
    two copies different primary keys, so `INSERT IGNORE` treated them as two
    distinct statements: the cycle appeared twice in the statement table, and
    every one of its transactions was written to the ledger a second time,
    double counting that card's spend.

    The filename is still the last-resort discriminator, used only when the
    parser could not read a Statement_Date or Billing Period at all. Some layouts
    put those fields where the parser cannot reach them, and collapsing every such
    file for a card onto one key would silently discard all but the first. That
    is the lesser evil precisely because it needs an unreadable statement to
    trigger: a correctly parsed cycle can never hit it.
    """
    stamp = f"{statement_date}|{period_end}"
    if stamp == "None|None":
        name = os.path.basename(str(source_file or "")).upper()
        return "CCS_" + hashlib.sha1(f"{card_id}|NO-DATES|{name}".encode()).hexdigest()[:20].upper()
    return "CCS_" + hashlib.sha1(f"{card_id}|{stamp}".encode()).hexdigest()[:20].upper()



def make_txn_id(statement_id, txn_date, description, amount, index):
    """
    Deterministic per-transaction id.

    Includes the row index so two identical charges on the same day at the same
    merchant (a very common pattern - two fuel stops, two coffee runs) stay
    distinct, while re-importing the same statement is still idempotent.
    """
    token = f"{statement_id}|{txn_date}|{description}|{amount}|{index}"
    return "CCT_" + hashlib.sha1(token.encode()).hexdigest()[:20].upper()


def make_ledger_ref(card_id, cc_txn_id):
    """
    Ledger primary key for a card row.

    Namespaced with a CC: prefix so it can never collide with a bank
    Chq_Ref_Number, and carrying the card id so two cards cannot produce the
    same key for the same underlying transaction.
    """
    return f"CC:{card_id}:{cc_txn_id}"


def _ts(value):
    """NaT/None -> None, so a NULL goes to the DB rather than 'NaT'."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return pd.Timestamp(value).to_pydatetime()


def _is_settlement(description, amount, payments_received, tolerance=1.0):
    """
    True when a row repays the card rather than spending on it.

    Two independent signals, because either alone is insufficient:

    * the narration matches SETTLEMENT_RE ("BPPY CC PAYMENT", "BBPS Payment
      received", ...); but on a masked statement the merchant text can be
      redacted down to a bare reference, leaving nothing for the pattern to
      match;
    * the amount equals what the issuer printed as received this cycle. The
      statement states its own payments figure, so a row of exactly that value
      is the payment by definition, whatever the narration says.

    Without the second signal a card payment whose narration was redacted is
    counted as spend, and the cycle total comes out overstated by exactly the
    size of the bill.
    """
    if SETTLEMENT_RE.search(str(description or "")):
        return True
    if payments_received is not None and amount is not None:
        try:
            return abs(float(amount) - float(payments_received)) <= tolerance
        except (TypeError, ValueError):
            return False
    return False


def _prepare_rows(statement_id, card_id, df, payments_received=None):
    """Builds the credit_card_transactions rows, with a settlement flag."""
    rows = []
    for idx, row in df.reset_index(drop=True).iterrows():
        cc_txn_id = make_txn_id(
            statement_id, _ts(row["Txn_Date"]), row["Description"], row["Amount"], idx
        )
        # A settlement repays the card; it is not spend and would otherwise be
        # counted twice alongside the purchases it settles.
        is_settlement = int(_is_settlement(
            row["Description"], row["Amount"], payments_received
        ))
        # From the CARD's point of view a bill payment is money coming IN - it
        # reduces the balance owed. The statement prints it in the debit column,
        # so Direction arrives as DEBIT and a transfer was being reported as an
        # expense. A settlement is therefore always CREDIT here, whatever column
        # the issuer laid it out in. A purchase stays a DEBIT and a refund a
        # CREDIT, exactly as printed.
        direction = "CREDIT" if is_settlement else row["Direction"]
        rows.append({
            "CC_Txn_ID": cc_txn_id,
            "Statement_ID": statement_id,
            "Card_ID": card_id,
            "Txn_Date": _ts(row["Txn_Date"]),
            "Txn_Time": str(row.get("Txn_Time") or "") or None,
            "Description": row["Description"],
            "Amount": float(row["Amount"]),
            "Direction": direction,
            "Rewards": str(row.get("Rewards") or "") or None,
            "Card_Ref": str(row.get("Card_Ref") or "") or None,
            "Statement_Category": row.get("Statement_Category") or None,
            "Statement_Category_Raw": row.get("Statement_Category_Raw") or None,
            "Is_Settlement": is_settlement,
            "Page": int(row["Page"]) if pd.notna(row.get("Page")) else None,
            "Ledger_Chq_Ref": make_ledger_ref(card_id, cc_txn_id),
        })
    return pd.DataFrame(rows)



def to_ledger_rows(txn_df, meta):
    """
    Projects card transactions onto the shared `transactions` schema so the
    dashboard can aggregate bank and card spend in one place.

    A purchase becomes a debit and a refund a credit. The issuer's own category
    is carried through as `Statement_Category`, which the categorisation step
    prefers over keyword matching.
    """
    out = pd.DataFrame({
        "Date": txn_df["Txn_Date"],
        "Narration": txn_df["Description"],
        "Value_Date": None,
        "Debit_Amount": [
            float(a) if d == "DEBIT" else 0.0
            for a, d in zip(txn_df["Amount"], txn_df["Direction"])
        ],
        "Credit_Amount": [
            float(a) if d == "CREDIT" else 0.0
            for a, d in zip(txn_df["Amount"], txn_df["Direction"])
        ],
        "Chq_Ref_Number": txn_df["Ledger_Chq_Ref"],
        "Closing_Balance": None,
        "Account_Source": SOURCE_CARD,
        "Card_ID": txn_df["Card_ID"],
        "Statement_ID": txn_df["Statement_ID"],
        "Is_Settlement": txn_df["Is_Settlement"],
        "Statement_Category": txn_df["Statement_Category"],
        "Card_Ref": txn_df["Card_Ref"],
    })
    out["Issuer"] = meta.get("Issuer")
    out["Card_Name"] = meta.get("Card_Name")
    return out


def store_card_statement(engine, df, meta):
    """
    Writes one parsed statement and its transactions. Idempotent.

    Returns a summary including the reconciliation between the issuer's printed
    cycle total and the sum of the parsed rows. A non-zero variance is the
    signal that rows were dropped or double counted, so it is reported rather
    than swallowed.
    """
    from db import init_db_tables, insert_ignore_on_duplicate

    init_db_tables(engine)

    card_id = make_card_id(
        meta.get("Issuer"), meta.get("Card_Last4"), meta.get("Source_File")
    )
    statement_date = _ts(meta.get("Statement_Date") or meta.get("Period_End"))
    period_end = _ts(meta.get("Period_End"))
    statement_id = make_statement_id(
        card_id, statement_date, period_end, meta.get("Source_File")
    )
    now = pd.Timestamp.utcnow().to_pydatetime()

    txn_df = _prepare_rows(statement_id, card_id, df,
                           payments_received=meta.get("Payments_Received"))
    ledger_df = to_ledger_rows(txn_df, meta)

    # Parsed_Spend is the comparison against the issuer's printed Total_Spend, and
    # that figure counts PURCHASES ONLY. Summing every DEBIT here swept in the
    # bill payment row as well, so a statement parsed perfectly still reported a
    # huge variance - on one cycle the parsed total read 195,951 against an issuer
    # total of 12,233, when the purchases alone summed to exactly 12,233. The
    # settlement row is real cash, but it repays a prior cycle and is already
    # counted on the statement that carries the original purchases.
    is_settlement = (
        txn_df["Is_Settlement"] if "Is_Settlement" in txn_df.columns else False
    )
    parsed_spend = float(
        txn_df.loc[(txn_df["Direction"] == "DEBIT") & ~is_settlement, "Amount"].sum()
    )
    parsed_refunds = float(txn_df.loc[txn_df["Direction"] == "CREDIT", "Amount"].sum())

    # Reported for transparency only: the settlement is already excluded from
    # parsed_spend above, so it must NOT be subtracted again downstream.
    settlement_spend = float(
        txn_df.loc[txn_df["Is_Settlement"] == 1, "Amount"].sum()
    )

    with engine.begin() as connection:
        init_card_tables(connection)

        connection.execute(
            text(f"""
                INSERT INTO {TABLE_CREDIT_CARDS}
                    (Card_ID, Issuer, Card_Name, Last4, Credit_Limit, First_Seen, Last_Seen)
                VALUES (:cid, :issuer, :name, :last4, :limit, :seen, :seen)
                ON DUPLICATE KEY UPDATE
                    Card_Name = VALUES(Card_Name),
                    Credit_Limit = COALESCE(VALUES(Credit_Limit), Credit_Limit),
                    Last_Seen = VALUES(Last_Seen)
            """),
            {
                "cid": card_id,
                "issuer": meta.get("Issuer"),
                "name": meta.get("Card_Name"),
                "last4": meta.get("Card_Last4"),
                "limit": meta.get("Credit_Limit"),
                "seen": statement_date or now,
            },
        )

        connection.execute(
            text(f"""
                INSERT INTO {TABLE_CREDIT_CARD_STATEMENTS}
                    (Statement_ID, Card_ID, Issuer, Card_Name, Statement_Date, Due_Date,
                     Period_Start, Period_End, Previous_Dues, Payments_Received, Total_Spend,
                     Finance_Charges, Total_Due, Minimum_Due, Credit_Limit,
                     Available_Credit_Limit, Txn_Count, Parsed_Spend, Parsed_Refunds,
                     Spend_Mix, Source_File, Imported_At)
                VALUES (:sid, :cid, :issuer, :name, :stmt_date, :due_date,
                        :p_start, :p_end, :prev_dues, :payments, :total_spend,
                        :finance, :total_due, :min_due, :limit,
                        :avail, :count, :spend, :refunds,
                        :mix, :src, :now)
                ON DUPLICATE KEY UPDATE
                    Parsed_Spend = VALUES(Parsed_Spend),
                    Parsed_Refunds = VALUES(Parsed_Refunds),
                    Txn_Count = VALUES(Txn_Count),
                    Imported_At = VALUES(Imported_At)
            """),
            {
                "sid": statement_id, "cid": card_id,
                "issuer": meta.get("Issuer"), "name": meta.get("Card_Name"),
                "stmt_date": statement_date, "due_date": _ts(meta.get("Due_Date")),
                "p_start": _ts(meta.get("Period_Start")), "p_end": period_end,
                "prev_dues": meta.get("Previous_Dues"),
                "payments": meta.get("Payments_Received"),
                "total_spend": meta.get("Total_Spend"),
                "finance": meta.get("Finance_Charges"),
                "total_due": meta.get("Total_Due"),
                "min_due": meta.get("Minimum_Due"),
                "limit": meta.get("Credit_Limit"),
                "avail": meta.get("Available_Credit_Limit"),
                "count": len(txn_df), "spend": parsed_spend, "refunds": parsed_refunds,
                "mix": json.dumps(meta.get("Spend_Mix") or {}),
                "src": meta.get("Source_File"), "now": now,
            },
        )

        # Transaction rows are immutable, so INSERT IGNORE keeps a re-import of
        # the same statement from duplicating anything.
        txn_df.to_sql(
            TABLE_CREDIT_CARD_TRANSACTIONS,
            con=connection, if_exists="append", index=False,
            method=insert_ignore_on_duplicate,
        )

    variance = None
    if meta.get("Total_Spend") is not None:
        # parsed_spend is already purchases-only, so this is a like-for-like
        # comparison against the issuer's printed cycle total.
        variance = round(parsed_spend - float(meta["Total_Spend"]), 2)

    return {
        "Card_ID": card_id,
        "Statement_ID": statement_id,
        "Issuer": meta.get("Issuer"),
        "Card_Name": meta.get("Card_Name"),
        "Card_Last4": meta.get("Card_Last4"),
        "Transactions": len(txn_df),
        "Settlement_Rows": int(txn_df["Is_Settlement"].sum()),
        "Settlement_Amount": round(settlement_spend, 2),
        "Issuer_Categorised": int(txn_df["Statement_Category"].notna().sum()),
        "Parsed_Spend": round(parsed_spend, 2),
        "Purchase_Spend": round(parsed_spend, 2),
        "Parsed_Refunds": round(parsed_refunds, 2),
        "Statement_Spend": meta.get("Total_Spend"),
        "Spend_Variance": variance,
        "Ledger_Rows": len(ledger_df),
    }


