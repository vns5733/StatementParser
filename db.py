import threading
import re

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.mysql import insert
from narration_parser import parse_narrations_dataframe
from category_rules import (
    BUILTIN_CATEGORIES,
    BUILTIN_SUB_CATEGORIES,
    CATEGORY_SPECS,
    CATEGORY_DIRECTION,
    DIRECTION_BOTH,
    DIRECTION_VALUES,
    PAYEE_CATEGORY_MAP,
    apply_direction_awareness,
    assign_sub_category,
    category_direction,
    parent_category,
)
from config import (
    DB_USER,
    DB_PASSWORD,
    DB_HOST,
    DB_PORT,
    DB_NAME,
    TABLE_TRANSACTIONS,
    TABLE_NARRATION_DETAILS,
    TABLE_CREDIT_CARDS,
    TABLE_DIRECTION_RULES,
    TABLE_TRANSACTION_NOTES,
)

# Card tables live in their own module so the bank-ledger code above stays
# focused. Imported here (not inside the functions) so init_db_tables can create
# the whole schema in one pass; card_store imports db lazily to avoid a cycle.
from card_store import SETTLEMENT_RE, init_card_tables  # noqa: E402


# ---------------------------------------------------------------------------
# In-process read caches
#
# Every dashboard request re-reads the same joined dataset and re-applies the
# same override rules. Both are pure functions of database state, so the results
# are cached and invalidated explicitly on write. Without this, an 11-request
# page load repeats the same work eleven times.
#
# _base_df_cache  — JOIN result, before override rules
# _final_df_cache — JOIN result with overrides applied (what readers actually want)
# _rules_cache    — parsed rules plus their precompiled match patterns
# ---------------------------------------------------------------------------
_CACHE_LOCK = threading.RLock()  # reentrant: cache fills call each other
_base_df_cache = None
_final_df_cache = None
_rules_cache = None
# User-editable per-category direction, read from category_definitions. Kept
# apart from _rules_cache because a different endpoint writes it (the definitions
# editor) and a different invalidator drops it.
_direction_override_cache = None

# Recurrence detection thresholds: a payee must repeat at least this many times,
# with a median gap no larger than this, to be treated as recurring.
RECURRING_MIN_OCCURRENCES = 3
RECURRING_MAX_GAP_DAYS = 45


def create_mysql_connection(
    user=DB_USER,
    password=DB_PASSWORD,
    host=DB_HOST,
    database=DB_NAME,
    port=DB_PORT,
):
    """
    Creates and returns a SQLAlchemy engine for MySQL.

    The pool is sized for a dashboard: many parallel requests hit the API at
    once, and a pool smaller than the request fan-out serialises them on
    connection checkout.
    """
    return create_engine(
        f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}",
        pool_size=10,
        max_overflow=20,
        pool_recycle=3600,
        pool_pre_ping=True,
    )


def insert_ignore_on_duplicate(table, conn, keys, data_iter):
    """
    Custom insertion method for pandas.to_sql using MySQL 'INSERT IGNORE'.
    Ensures idempotent imports without duplicate key exceptions.
    """
    data = [dict(zip(keys, row)) for row in data_iter]
    stmt = insert(table.table).prefix_with("IGNORE")
    result = conn.execute(stmt, data)
    return result.rowcount


def _column_exists(connection, table, column):
    rows = connection.execute(text(f"DESCRIBE {table}")).fetchall()
    return any(row[0] == column for row in rows)


def init_db_tables(engine, seed=True):
    """
    Verifies that the required tables exist with correct schemas.
    Drops legacy incompatible empty tables if needed.
    """
    with engine.begin() as connection:
        table_check = connection.execute(
            text(f"SHOW TABLES LIKE '{TABLE_TRANSACTIONS}'")
        ).fetchall()
        if table_check:
            cols = [
                row[0]
                for row in connection.execute(
                    text(f"DESCRIBE {TABLE_TRANSACTIONS}")
                ).fetchall()
            ]
            if "Chq_Ref_Number" not in cols:
                row_count = connection.execute(
                    text(f"SELECT COUNT(*) FROM {TABLE_TRANSACTIONS}")
                ).scalar()
                if row_count == 0:
                    print(
                        f"Dropping incompatible empty legacy '{TABLE_TRANSACTIONS}' table to apply current schema..."
                    )
                    connection.execute(text(f"DROP TABLE {TABLE_TRANSACTIONS}"))

        # Create main transactions table
        connection.execute(
            text(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_TRANSACTIONS} (
                Date DATETIME,
                Narration VARCHAR(255),
                Value_Date DATETIME,
                Debit_Amount FLOAT,
                Credit_Amount FLOAT,
                Chq_Ref_Number VARCHAR(250),
                Closing_Balance FLOAT,
                PRIMARY KEY (Chq_Ref_Number)
            );
        """)
        )

        # Create narration details table
        connection.execute(
            text(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_NARRATION_DETAILS} (
                Chq_Ref_Number VARCHAR(250) PRIMARY KEY,
                Transaction_Type VARCHAR(50),
                Details TEXT,
                Reference_ID TEXT,
                Payee_Receiver TEXT,
                Date_Range TEXT,
                Remarks TEXT,
                Other_Info TEXT,
                Broad_Category VARCHAR(50),
                FOREIGN KEY (Chq_Ref_Number) REFERENCES {TABLE_TRANSACTIONS}(Chq_Ref_Number)
            );
        """)
        )

        # Migrate legacy narration_details tables (add Broad_Category if missing)
        if not _column_exists(connection, TABLE_NARRATION_DETAILS, "Broad_Category"):
            connection.execute(
                text(f"ALTER TABLE {TABLE_NARRATION_DETAILS} ADD COLUMN Broad_Category VARCHAR(50) NULL")
            )

        # Add the finer Sub_Category leaf to the two-tier hierarchy
        if not _column_exists(connection, TABLE_NARRATION_DETAILS, "Sub_Category"):
            connection.execute(
                text(f"ALTER TABLE {TABLE_NARRATION_DETAILS} ADD COLUMN Sub_Category VARCHAR(80) NULL")
            )

        # Credit-card provenance on the shared ledger. A card purchase and a bank
        # debit are both money out, so the aggregated view needs to tell them
        # apart to avoid counting a card spend twice (once as the purchase, once
        # as the bank-side Credit_Card_Payment settlement). `Account_Source` is
        # the discriminator; `Is_Settlement` is derived at read time (see
        # _mark_settlement) rather than stored, so it stays correct as new
        # statements arrive without a migration.
        for col, ddl in (
            ("Account_Source", "VARCHAR(20) NULL"),
            ("Card_ID", "VARCHAR(64) NULL"),
            ("Statement_ID", "VARCHAR(64) NULL"),
        ):
            if not _column_exists(connection, TABLE_TRANSACTIONS, col):
                connection.execute(
                    text(f"ALTER TABLE {TABLE_TRANSACTIONS} ADD COLUMN {col} {ddl}")
                )

        # Broad category registry (built-in + user-added categories)
        connection.execute(
            text("""
            CREATE TABLE IF NOT EXISTS broad_categories (
                name VARCHAR(50) PRIMARY KEY,
                is_builtin TINYINT DEFAULT 0
            );
            """)
        )

        # User/cascade override rules (txn-specific, merchant-level, narration-keyword level)
        connection.execute(
            text("""
            CREATE TABLE IF NOT EXISTS category_rules (
                id INT AUTO_INCREMENT PRIMARY KEY,
                rule_type VARCHAR(20) NOT NULL,
                rule_key VARCHAR(255) NOT NULL,
                category VARCHAR(50) NOT NULL,
                UNIQUE KEY uq_rule (rule_type, rule_key)
            );
        """)
        )

        # Sub-category override on the same rules. A rule may set `category`,
        # `sub_category`, or both — both is the normal case, since choosing a leaf
        # implies its parent.
        if not _column_exists(connection, "category_rules", "sub_category"):
            connection.execute(
                text("ALTER TABLE category_rules ADD COLUMN sub_category VARCHAR(80) NULL")
            )

        # Debit/credit overrides. Shaped exactly like category_rules so the same
        # cascade UI works: a rule pins one transaction ('txn'), or matches every
        # transaction whose payee ('merchant') or narration ('narration') contains
        # the key. Applied at read time, so the stored rows are never rewritten
        # and a re-import cannot undo the user's correction.
        connection.execute(
            text(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_DIRECTION_RULES} (
                id INT AUTO_INCREMENT PRIMARY KEY,
                rule_type VARCHAR(20) NOT NULL,
                rule_key VARCHAR(255) NOT NULL,
                direction VARCHAR(10) NOT NULL,
                UNIQUE KEY uq_dir_rule (rule_type, rule_key)
            );
        """)
        )

        # Free-text notes the user attaches to a transaction, plus the last
        # suggestion an LLM made for it. Keyed on Chq_Ref_Number like every other
        # per-transaction table, so it survives a re-import of the same statement
        # (which is INSERT IGNORE) and is not touched by recategorize_all_narrations
        # (which only rewrites narration_details).
        connection.execute(
            text(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_TRANSACTION_NOTES} (
                Chq_Ref_Number VARCHAR(250) PRIMARY KEY,
                Note TEXT,
                Source VARCHAR(20) NULL,
                Suggestion TEXT NULL,
                Updated_At DATETIME NULL,
                FOREIGN KEY (Chq_Ref_Number)
                    REFERENCES {TABLE_TRANSACTIONS}(Chq_Ref_Number)
            );
            """)
        )

        # What each category is *for*, in the user's own words.
        #
        # Direction lives here only as an OVERRIDE; the authoritative value is in
        # code (category_rules.CATEGORY_DIRECTION), because the direction
        # reconciler needs it while classifying and there is no database in that
        # path. A non-null direction_override here wins over the code default at
        # read time, which is how a user re-points a category without a code
        # change.
        connection.execute(
            text("""
            CREATE TABLE IF NOT EXISTS category_definitions (
                name VARCHAR(50) PRIMARY KEY,
                description TEXT NULL,
                examples TEXT NULL,
                direction_override VARCHAR(10) NULL,
                is_builtin TINYINT DEFAULT 0,
                updated_at DATETIME NULL
            );
            """)
        )

        if seed:
            _seed_broad_categories(connection)
            _seed_category_rules(connection)
            _seed_category_definitions(connection)

        _migrate_renamed_categories(connection)

        # Credit-card tables. Created here so a single init_db_tables call sets
        # up the whole schema, matching how the bank tables are handled.
        init_card_tables(connection)

    # Seeding/migration can touch both the stored data and the rules table.
    invalidate_caches()


# Renames applied to all existing data at every init (self-healing).
#
# `Investment_Liquidation` was REMOVED from this map. It used to fold into
# `Investment`, on the reasoning that the two were the same platforms split only
# by direction and merging them was what made "what did I invest?" answerable.
# That merge is why a Groww payout read as money invested. Both categories roll up
# to Financial, so splitting them changes what a row is called without changing
# what any rollup adds up to, and leaving the entry in would have undone the split
# on every single startup.
CATEGORY_RENAMES = {
    "Business_Income": "Non_Salary_Income",
    "Mobile_Recharge": "Utilities_Bills",
    "Broadband_Internet": "Utilities_Bills",
}


def _migrate_renamed_categories(connection):
    """
    Renames legacy broad categories in stored data (narration_details,
    category_rules, broad_categories) so renamed built-ins stay consistent.
    """
    for old_name, new_name in CATEGORY_RENAMES.items():
        connection.execute(
            text("INSERT IGNORE INTO broad_categories (name, is_builtin) VALUES (:n, 1)"),
            {"n": new_name},
        )
        connection.execute(
            text("UPDATE narration_details SET Broad_Category = :n WHERE Broad_Category = :o"),
            {"n": new_name, "o": old_name},
        )
        connection.execute(
            text("UPDATE category_rules SET category = :n WHERE category = :o"),
            {"n": new_name, "o": old_name},
        )
        connection.execute(
            text("DELETE FROM broad_categories WHERE name = :o"),
            {"o": old_name},
        )


def _seed_category_definitions(connection):
    """
    Seeds category_definitions from category_rules.CATEGORY_SPECS with INSERT
    IGNORE, so an existing row is never overwritten.

    That is the whole point: these are the user's words about a category, and a
    code change must not silently revert an edit. A spec added to CATEGORY_SPECS
    later still lands, because the row does not exist yet. direction_override is
    deliberately NOT seeded - seeding it would pin every category to its code
    default and make the override column permanently dead.
    """
    for name, spec in CATEGORY_SPECS.items():
        connection.execute(
            text("""
                INSERT IGNORE INTO category_definitions
                    (name, description, examples, direction_override, is_builtin, updated_at)
                VALUES (:n, :d, :e, NULL, 1, NOW())
            """),
            {"n": name, "d": spec.get("description"), "e": spec.get("examples")},
        )


def _seed_broad_categories(connection):
    for name in BUILTIN_CATEGORIES:
        connection.execute(
            text("INSERT IGNORE INTO broad_categories (name, is_builtin) VALUES (:n, 1)"),
            {"n": name},
        )


def _seed_category_rules(connection):
    """
    Seeds the payee-level rules from PAYEE_CATEGORY_MAP (INSERT IGNORE).
    Runs on every init so new seed keys added to the map are picked up,
    while preserving user-created rules (existing rows are never touched).
    """
    for key, category in PAYEE_CATEGORY_MAP.items():
        connection.execute(
            text("""
                INSERT IGNORE INTO category_rules (rule_type, rule_key, category)
                VALUES ('merchant', :k, :c)
            """),
            {"k": key.strip().upper(), "c": category},
        )


def store_data_in_db(engine, transaction_data, narration_data):
    """
    Initializes database tables and stores transaction and narration data idempotently.
    """
    init_db_tables(engine)

    print(f"Inserting data into '{TABLE_TRANSACTIONS}' table...")
    transaction_data.to_sql(
        TABLE_TRANSACTIONS,
        con=engine,
        if_exists="append",
        index=False,
        method=insert_ignore_on_duplicate,
    )

    print(f"Inserting data into '{TABLE_NARRATION_DETAILS}' table...")
    narration_data.to_sql(
        TABLE_NARRATION_DETAILS,
        con=engine,
        if_exists="append",
        index=False,
        method=insert_ignore_on_duplicate,
    )
    print("Database storage completed successfully!")

    # New rows are now visible; drop the stale read cache.
    invalidate_transaction_cache()


def _mark_recurring(df):
    """
    Flags transactions paid to a counterparty that repeats on a monthly-ish
    cadence — rent, EMIs, SIPs, subscriptions, salary.

    A payee qualifies when it appears at least RECURRING_MIN_OCCURRENCES times
    and the median gap between its transactions is at most RECURRING_MAX_GAP_DAYS.
    Computed over the whole dataset so it self-updates as statements are imported.
    """
    df["is_recurring"] = False
    if df.empty or "Payee_Receiver" not in df.columns or "Date" not in df.columns:
        return df

    payee = df["Payee_Receiver"].fillna("").astype(str).str.strip().str.upper()
    if not payee.ne("").any():
        return df

    s = pd.DataFrame({"payee": payee, "date": df["Date"]})
    s = s[payee.ne("")].sort_values(["payee", "date"])
    if s.empty:
        return df

    s["gap"] = s.groupby("payee")["date"].diff().dt.days
    median_gap = s.groupby("payee")["gap"].median()
    occurrences = s.groupby("payee")["date"].count()

    qualifying = median_gap[
        (median_gap <= RECURRING_MAX_GAP_DAYS)
        & (occurrences >= RECURRING_MIN_OCCURRENCES)
    ].index

    df["is_recurring"] = payee.isin(set(qualifying))
    return df


def _card_side_settlement_mask(df):
    """
    True for the CARD half of a bank<->card settlement: a row on the credit-card
    ledger whose narration names a payment.

    Shared by _mark_settlement and _apply_direction_awareness on purpose. The two
    must agree exactly, because awareness has to be able to ask "is this row a
    settlement?" without relying on Is_Settlement — which does not exist yet at
    that point in the pipeline, since settlement is marked after awareness (a
    refund reconciled into Card_Refund must not be mistaken for a bill payment).
    Duplicating the pattern instead of sharing it is how the two would drift.
    """
    if df.empty or "Account_Source" not in df.columns:
        return pd.Series(False, index=df.index)

    source = df["Account_Source"].fillna("BANK").astype(str).str.upper()
    narration = _upper_series(df, "Narration")
    if narration is None:
        return pd.Series(False, index=df.index)

    # SETTLEMENT_RE is an inline-flag regex; the pattern is used, not its capture
    # groups, so pandas' group warning is expected and harmless.
    card_side = narration.str.contains(SETTLEMENT_RE, regex=True, na=False)
    return (source == "CREDIT_CARD") & card_side


def _mark_settlement(df):
    """
    Flags rows that move money between the bank and a card rather than spending
    it, in BOTH ledgers:

      * card side  - "BPPY CC PAYMENT ...", "BBPS Payment received"
      * bank side  - any debit already categorised as Credit_Card_Payment

    These are the two halves of the same transaction. Counting both as spend
    would report every card purchase twice, once at the merchant and once when
    the card bill is paid. Spend aggregations therefore subtract them; cashflow
    still includes them, because the money really did leave the bank account.

    Derived at read time, like `is_recurring`, so it stays correct as statements
    are re-imported without a migration.

    Must be called on the frame whose Broad_Category has already had the category
    rules AND the direction reconciliation applied - i.e. after
    _apply_category_rule_overrides and after _apply_direction_awareness. The
    bank-side test reads that column, so running this earlier would only see the
    stored category, miss any row a rule reclassified, and count a card refund as
    the bill payment it is not (see Decision 24 and Decision 37).
    _mark_recurring has no such constraint: it reads Payee_Receiver/Date, which
    no rule changes.
    """
    df["Is_Settlement"] = False
    if df.empty:
        return df

    broad = _upper_series(df, "Broad_Category")
    # Matched on separators as well as underscores so a renamed or
    # user-created variant ("Credit Card Payment", "CreditCardPayment")
    # is still recognised as the bank half of a settlement.
    bank_side = (
        broad.str.contains(r"CREDIT[\s_]*CARD[\s_]*PAYMENT", regex=True, na=False)
        if broad is not None
        else pd.Series(False, index=df.index)
    )

    df["Is_Settlement"] = _card_side_settlement_mask(df) | bank_side
    return df


def _load_direction_overrides(engine):
    """
    User-editable direction per category, from category_definitions.

    Returned as {name: 'IN'|'OUT'|'BOTH'} containing ONLY the names that have an
    explicit override, because category_direction falls back to the code-level map
    for anything absent. Cached alongside the other rules because it feeds the
    final-frame build, so re-reading it per request would defeat the point.
    """
    global _direction_override_cache
    if _direction_override_cache is not None:
        return _direction_override_cache

    overrides = {}
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text("""
                    SELECT name, direction_override
                    FROM category_definitions
                    WHERE direction_override IS NOT NULL
                      AND direction_override <> ''
                """)
            ).fetchall()
        for name, value in rows:
            token = str(value or "").strip().upper()
            if token in DIRECTION_VALUES:
                overrides[str(name)] = token
    except Exception:
        # A missing table (first run before migration) simply means no overrides.
        overrides = {}

    _direction_override_cache = overrides
    return overrides


def _apply_direction_awareness(df, engine):
    """
    Reconciles every row's category against the side its money actually moved, and
    records the result in three columns:

      Category_Direction  - the direction the category is about (IN / OUT / BOTH)
      Direction_Mismatch  - True when the row's amount side disagrees with that
      Direction_Reclassified - the category it was BEFORE this correction, so the
                            UI can say what changed rather than presenting a label
                            the parser never produced

    Runs AFTER _apply_direction_overrides, and that ordering is the whole point:
    a direction rule moves the amount between Debit_Amount and Credit_Amount, so a
    row flipped from debit to credit is only discoverable as a mismatch once the
    flip has happened. Running earlier would compare against the amount the user
    explicitly corrected away from. This is the same lesson as Decision 24 — a
    derived column that reads another derived column has to come after it.

    Sub_Category is re-derived only for rows whose parent actually changed.
    Otherwise a Groww sale would keep the Mutual_Fund leaf it picked up while it
    was still an Investment debit.
    """
    df["Category_Direction"] = DIRECTION_BOTH
    df["Direction_Mismatch"] = False
    df["Direction_Reclassified"] = None
    df["Direction_Mismatch_Reason"] = None
    if df.empty:
        return df

    overrides = _load_direction_overrides(engine)
    debit = pd.to_numeric(df["Debit_Amount"], errors="coerce").fillna(0) > 0
    credit = pd.to_numeric(df["Credit_Amount"], errors="coerce").fillna(0) > 0

    # A settlement is not a refund and not a disbursement, whatever direction it
    # runs. Excluding these rows is not a detail: 95 card-side credits printed as
    # "NETBANKING TRANSFER" were being relabelled Credit_Card_Payment ->
    # Card_Refund, which is the one thing Decision 27 went to some trouble to
    # establish they are not. A settlement keeps whatever category it had.
    settled = _card_side_settlement_mask(df)

    categories = df["Broad_Category"].fillna("Uncategorized").astype(str)

    # Two series, because they answer different questions: `recat` is where the row
    # now IS, `from_cat` is where it was. Masking Broad_Category with `from_cat`
    # would put the old value straight back — a reclassification that reclassifies
    # nothing, which is exactly what it looked like.
    recat = pd.Series([None] * len(df), index=df.index, dtype=object)
    from_cat = pd.Series([None] * len(df), index=df.index, dtype=object)
    mismatch = pd.Series(False, index=df.index)
    reasons = pd.Series([None] * len(df), index=df.index, dtype=object)

    for idx in df.index:
        if settled.at[idx]:
            continue
        has_debit, has_credit = bool(debit.at[idx]), bool(credit.at[idx])
        new_cat, reason, corrected_from = apply_direction_awareness(
            df.at[idx, "Broad_Category"], has_debit, has_credit, direction_map=overrides
        )
        if corrected_from:
            recat.at[idx] = new_cat
            from_cat.at[idx] = corrected_from
        elif reason:
            mismatch.at[idx] = True
            reasons.at[idx] = reason

    df["Broad_Category"] = categories.mask(recat.notna(), recat)

    if recat.notna().any():
        changed = recat.notna()
        # Re-derive the leaf from the NEW parent, but only where the parent moved,
        # so an unchanged row keeps whatever leaf the override layer resolved.
        for idx in df.index[changed]:
            df.at[idx, "Sub_Category"] = assign_sub_category(
                df.at[idx, "Broad_Category"],
                df.at[idx, "Narration"],
                df.at[idx, "Details"],
                df.at[idx, "Payee_Receiver"],
                df.at[idx, "Reference_ID"],
            )

    # Derived last, from the category each row ACTUALLY ended up in. Computing it
    # before the reclassification left every reclassified row advertising the
    # direction of the category it used to be, so Card_Refund reported OUT and
    # every invariant test against it failed.
    df["Category_Direction"] = pd.Series(
        [category_direction(c, overrides) for c in df["Broad_Category"]],
        index=df.index,
    )
    # The rollup parent follows the category, or a reclassified row keeps the
    # parent of the category it no longer is.
    df["Category"] = df["Broad_Category"].map(parent_category)

    df["Direction_Mismatch"] = mismatch
    df["Direction_Mismatch_Reason"] = reasons
    df["Direction_Reclassified"] = from_cat
    return df


def _query_transactions_with_details(engine):
    """
    Runs the transactions + narration_details JOIN and derives the temporal
    helper columns plus the recurring flag. This is the expensive part of every
    read request, so the result is cached in-process (see _get_cached_base_df).
    """
    query = f"""
        SELECT
            t.Date,
            t.Narration,
            t.Value_Date,
            t.Debit_Amount,
            t.Credit_Amount,
            t.Closing_Balance,
            t.Chq_Ref_Number,
            t.Account_Source,
            t.Card_ID,
            t.Statement_ID,
            n.Transaction_Type,
            n.Details,
            n.Reference_ID,
            n.Payee_Receiver,
            n.Remarks,
            n.Other_Info,
            n.Broad_Category,
            n.Sub_Category,
            c.Card_Name,
            c.Issuer AS Card_Issuer,
            nt.Note,
            nt.Source AS Note_Source,
            nt.Suggestion,
            nt.Updated_At AS Note_Updated_At
        FROM {TABLE_TRANSACTIONS} t
        LEFT JOIN {TABLE_NARRATION_DETAILS} n
            ON t.Chq_Ref_Number = n.Chq_Ref_Number
        LEFT JOIN {TABLE_CREDIT_CARDS} c
            ON t.Card_ID = c.Card_ID
        LEFT JOIN {TABLE_TRANSACTION_NOTES} nt
            ON t.Chq_Ref_Number = nt.Chq_Ref_Number
        ORDER BY t.Date ASC, t.Chq_Ref_Number ASC;
    """
    with engine.connect() as connection:
        df = pd.read_sql(text(query), con=connection)

    if not df.empty and "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"])
        df["Year"] = df["Date"].dt.year
        df["Month"] = df["Date"].dt.month
        df["Month_Name"] = df["Date"].dt.strftime("%b")
        df["Year_Month"] = df["Date"].dt.strftime("%Y-%m")
    else:
        df["Year"] = None
        df["Month"] = None
        df["Month_Name"] = None
        df["Year_Month"] = None

    # Rows imported before the card work have no Account_Source; they are bank
    # rows by definition.
    if "Account_Source" in df.columns:
        df["Account_Source"] = df["Account_Source"].fillna("BANK")

    # Recurrence depends only on Payee_Receiver/Date, which override rules never
    # touch, so it can be settled here. Settlement does NOT: the bank side is
    # identified by its resolved Broad_Category, and that is only final after
    # _apply_category_rule_overrides has run. It is marked in
    # _get_cached_final_df instead - see the note there.
    _mark_recurring(df)
    return df



def _get_cached_base_df(engine):
    """
    Returns the cached JOIN result *without* copying.

    Callers must not mutate the returned frame. The lock is held across the
    initial query on purpose: it makes a cold start single-flight, so eleven
    concurrent dashboard requests trigger one query instead of eleven.
    """
    global _base_df_cache
    with _CACHE_LOCK:
        if _base_df_cache is None:
            _base_df_cache = _query_transactions_with_details(engine)
        return _base_df_cache


def _get_cached_final_df(engine):
    """
    Returns the cached post-override frame *without* copying.

    Applying the override rules is deterministic given the base frame and the
    rules, so the composed result is cached too — making the read path a lookup
    plus a copy instead of a full recomputation per request.
    """
    global _final_df_cache
    with _CACHE_LOCK:
        if _final_df_cache is None:
            base = _get_cached_base_df(engine)
            if base.empty:
                _final_df_cache = base
            else:
                df = _apply_category_rule_overrides(engine, base.copy())
                # Rollup parent, derived from the *resolved* broad category so the
                # hierarchy always reflects the user's overrides.
                df["Category"] = df["Broad_Category"].map(parent_category)

                # Order matters here, and the dependency chain is the reason:
                #
                #   direction overrides -> direction awareness -> settlement
                #
                # Direction has to be resolved first because awareness compares a
                # category against the side its money moved, and a direction rule
                # is what decides that side (Decision 28). Awareness then has to
                # come before settlement, because settlement's bank-side test
                # matches on Broad_Category - and a card refund reconciled into
                # Card_Refund is no longer a card bill payment. Marking settlement
                # first let a refund be excluded from spend as though it were the
                # payment, deleting it from the totals instead of counting it as
                # money back.
                _apply_direction_overrides(engine, df)
                _apply_direction_awareness(df, engine)
                _mark_settlement(df)
                _final_df_cache = df
        return _final_df_cache


def invalidate_transaction_cache():
    """Drops the cached JOIN and overridden frames. Call after any data write."""
    global _base_df_cache, _final_df_cache
    with _CACHE_LOCK:
        _base_df_cache = None
        _final_df_cache = None


def invalidate_rules_cache():
    """
    Drops the cached rules and the overridden frame. The base JOIN stays valid
    because a rule change does not touch the stored data.
    """
    global _rules_cache, _final_df_cache
    with _CACHE_LOCK:
        _rules_cache = None
        _final_df_cache = None


def invalidate_direction_override_cache():
    """
    Drops the user-editable per-category direction map and the frame built from it.

    Separate from invalidate_rules_cache because a definitions edit touches neither
    the rules nor the stored data — but it does change which rows get flagged as a
    mismatch, so the frame built on top of it is stale.
    """
    global _direction_override_cache, _final_df_cache
    with _CACHE_LOCK:
        _direction_override_cache = None
        _final_df_cache = None


def invalidate_caches():
    """Drops both caches."""
    invalidate_transaction_cache()
    invalidate_rules_cache()
    invalidate_direction_override_cache()


def get_all_transactions_with_details(engine):
    """
    Fetches all transactions joined with their structured narration details,
    with read-time category overrides applied.

    Reads from the in-process cache and returns a copy, because callers routinely
    mutate the frame (routers fillna Broad_Category, filter, aggregate).
    """
    return _get_cached_final_df(engine).copy()


def get_total_transaction_count(engine):
    """Row count of the full transaction set, served from cache (no copy)."""
    return len(_get_cached_final_df(engine))


def get_yearly_credit_debit(engine):
    """
    Aggregates total Credit and Debit amounts per year.
    """
    df_all = get_all_transactions_with_details(engine)
    if df_all.empty:
        return pd.DataFrame(columns=["Year", "Total_Credit", "Total_Debit"])

    yearly = (
        df_all.groupby("Year")
        .agg(
            Total_Credit=("Credit_Amount", "sum"),
            Total_Debit=("Debit_Amount", "sum"),
        )
        .reset_index()
        .sort_values("Year")
    )
    return yearly


def get_monthly_credit_debit(engine):
    """
    Aggregates total Credit and Debit amounts per Year-Month.
    """
    df_all = get_all_transactions_with_details(engine)
    if df_all.empty:
        return pd.DataFrame(
            columns=["Year_Month", "Year", "Month", "Month_Label", "Total_Credit", "Total_Debit", "Transaction_Count"]
        )

    monthly = (
        df_all.groupby(["Year_Month", "Year", "Month"])
        .agg(
            Total_Credit=("Credit_Amount", "sum"),
            Total_Debit=("Debit_Amount", "sum"),
            Transaction_Count=("Date", "count"),
        )
        .reset_index()
        .sort_values("Year_Month")
    )
    monthly["Month_Label"] = monthly["Year_Month"]
    return monthly


def get_monthly_category_summary(engine):
    """
    Aggregates total Debits and Credits per Year-Month and Broad_Category.
    Use as the data source for the category-layered monthly credit/debit chart.
    """
    df_all = get_all_transactions_with_details(engine)
    if df_all.empty:
        return pd.DataFrame(
            columns=["Year_Month", "Broad_Category", "Total_Credit", "Total_Debit", "Transaction_Count"]
        )

    summary = (
        df_all.groupby(["Year_Month", "Broad_Category"])
        .agg(
            Total_Credit=("Credit_Amount", "sum"),
            Total_Debit=("Debit_Amount", "sum"),
            Transaction_Count=("Date", "count"),
        )
        .reset_index()
        .sort_values(["Year_Month", "Broad_Category"])
    )
    return summary


def get_category_summary(engine):
    """
    Aggregates total Debits and Credits by Transaction_Type.
    """
    df_all = get_all_transactions_with_details(engine)
    if df_all.empty:
        return pd.DataFrame(
            columns=["Category", "Transaction_Count", "Total_Debit", "Total_Credit"]
        )

    summary = (
        df_all.groupby("Transaction_Type")
        .agg(
            Transaction_Count=("Date", "count"),
            Total_Debit=("Debit_Amount", "sum"),
            Total_Credit=("Credit_Amount", "sum"),
        )
        .reset_index()
        .rename(columns={"Transaction_Type": "Category"})
        .sort_values("Total_Debit", ascending=False)
    )
    return summary


def _restore_issuer_categories(narr_df, issuer_cat, narration_map=None):
    """
    Re-applies the card issuer's own classification over a freshly parsed frame.

    Mirrors what ingest_cards.py does at import time: the issuer's category wins,
    and the Sub_Category leaf is re-derived from it so the two levels cannot
    disagree. Mutates `narr_df` in place; returns the number of rows corrected.
    """
    if issuer_cat is None or issuer_cat.empty:
        return 0

    from category_rules import assign_sub_category

    mapping = dict(zip(
        issuer_cat["Chq_Ref_Number"].astype(str),
        issuer_cat["Statement_Category"].astype(str).str.strip(),
    ))
    refs = narr_df["Chq_Ref_Number"].astype(str)
    mask = refs.isin(mapping.keys())
    if not mask.any():
        return 0

    narr_df.loc[mask, "Broad_Category"] = refs[mask].map(mapping)
    # assign_sub_category wants the ORIGINAL narration, and narration_details has no
    # such column - only the parsed Details. Fall back to Details, which for a card
    # descriptor is the narration verbatim.
    if narration_map is None:
        narrations = narr_df["Details"].fillna("")
    else:
        narrations = refs.map(narration_map).fillna(narr_df["Details"].fillna(""))
    narr_df.loc[mask, "Sub_Category"] = [
        assign_sub_category(broad, narr, d, p, r)
        for broad, narr, d, p, r in zip(
            narr_df.loc[mask, "Broad_Category"],
            narrations[mask],
            narr_df.loc[mask, "Details"].fillna(""),
            narr_df.loc[mask, "Payee_Receiver"].fillna(""),
            narr_df.loc[mask, "Reference_ID"].fillna(""),
        )
    ]
    return int(mask.sum())


def recategorize_all_narrations(engine):
    """
    Re-parses all existing transaction narrations using the current narration_parser rules
    and replaces the narration_details table entirely.
    UI override rules (category_rules) are preserved and still apply on read.
    Returns (old_counts, new_counts) dicts for before/after comparison.
    """
    init_db_tables(engine)

    with engine.begin() as connection:
        tx_df = pd.read_sql(
            text(f"SELECT Chq_Ref_Number, Narration, Debit_Amount, Credit_Amount FROM {TABLE_TRANSACTIONS}"),
            con=connection,
        )
        if tx_df.empty:
            return {}, {}

        old_type_dist = pd.read_sql(
            text(f"SELECT Broad_Category as cat, COUNT(*) as cnt FROM {TABLE_NARRATION_DETAILS} GROUP BY Broad_Category"),
            con=connection,
        )
        old_counts = dict(zip(old_type_dist["cat"], old_type_dist["cnt"])) if not old_type_dist.empty else {}

        # Issuer-supplied card categories, read BEFORE the rewrite. The parser only
        # sees the narration text, so it cannot know the card network classified the
        # purchase itself, and Design Decision 18 gives that value precedence over
        # keyword guessing. Recategorising without restoring it silently downgraded
        # every issuer-classified row to whatever the merchant string implied - on
        # the development data that turned one row from the issuer's Utilities_Bills
        # into Shopping_Retail purely because the descriptor began "AMAZON". The
        # 18 Groceries rows happened to survive only because the description also
        # contained the word GROCERY; nothing was protecting them.
        try:
            issuer_cat = pd.read_sql(
                text("""SELECT Ledger_Chq_Ref AS Chq_Ref_Number, Statement_Category
                        FROM credit_card_transactions
                        WHERE Statement_Category IS NOT NULL
                          AND Statement_Category <> ''
                          AND Ledger_Chq_Ref IS NOT NULL"""),
                con=connection,
            )
        except Exception:
            # Card tables absent (a bank-only database). Nothing to restore.
            issuer_cat = pd.DataFrame(columns=["Chq_Ref_Number", "Statement_Category"])

        connection.execute(text(f"DELETE FROM {TABLE_NARRATION_DETAILS}"))

    new_narr_df = parse_narrations_dataframe(tx_df)

    if not issuer_cat.empty:
        _restore_issuer_categories(
            new_narr_df,
            issuer_cat,
            narration_map=dict(zip(tx_df["Chq_Ref_Number"].astype(str),
                                   tx_df["Narration"].fillna("").astype(str))),
        )

    new_narr_df.to_sql(
        TABLE_NARRATION_DETAILS,
        con=engine,
        if_exists="append",
        index=False,
        method=insert_ignore_on_duplicate,
    )

    new_counts = dict(new_narr_df["Broad_Category"].value_counts())

    # narration_details was rewritten wholesale.
    invalidate_transaction_cache()

    return old_counts, new_counts


# ---------------------------------------------------------------------------
# Broad Category registry + override rules
# ---------------------------------------------------------------------------

def _combined_pattern(keys):
    """
    One alternation regex matching any of `keys`, or None if there are none.

    `Series.str.contains` walks elements in Python, so N rules means N full
    passes over the column. Folding escaped keys into a single alternation turns
    that into one pass.
    """
    usable = [re.escape(k) for k in keys if k]
    if not usable:
        return None
    return "|".join(usable)


def _load_category_rules(engine):
    """
    Returns (txn_rules, merchant_rules, narration_rules) for override application.

    Each rule is (category, sub_category) so a rule can refine the broad bucket,
    the leaf, or both. Cached, because every read request needs this and the
    result only changes when a rule is written.
    """
    global _rules_cache
    with _CACHE_LOCK:
        if _rules_cache is None:
            with engine.connect() as connection:
                rows = connection.execute(
                    text("SELECT rule_type, rule_key, category, sub_category FROM category_rules")
                ).fetchall()

            txn_rules, merchant_rules, narration_rules = {}, [], []
            for rule_type, rule_key, category, sub_category in rows:
                key = str(rule_key).strip().upper()
                value = (category, sub_category)
                if rule_type == "txn":
                    txn_rules[key] = value
                elif rule_type == "merchant":
                    merchant_rules.append((key, value))
                elif rule_type == "narration":
                    narration_rules.append((key, value))
            _rules_cache = (txn_rules, merchant_rules, narration_rules)
        return _rules_cache


def _load_direction_rules(engine):
    """
    Returns (txn_rules, merchant_rules, narration_rules) for direction overrides.

    Each rule is a single 'CREDIT' / 'DEBIT' string. Cached for the same reason the
    category rules are: every read needs it and it only changes on a write.
    """
    with engine.connect() as connection:
        rows = connection.execute(
            text(f"SELECT rule_type, rule_key, direction FROM {TABLE_DIRECTION_RULES}")
        ).fetchall()

    txn_rules, merchant_rules, narration_rules = {}, [], []
    for rule_type, rule_key, direction in rows:
        key = str(rule_key).strip().upper()
        value = str(direction).strip().upper()
        if value not in ("CREDIT", "DEBIT"):
            continue
        if rule_type == "txn":
            txn_rules[key] = value
        elif rule_type == "merchant":
            merchant_rules.append((key, value))
        elif rule_type == "narration":
            narration_rules.append((key, value))
    return txn_rules, merchant_rules, narration_rules


def _apply_direction_overrides(engine, df):
    """
    Normalises every row onto exactly one amount column, then applies the user's
    debit/credit overrides.

    The stored shape is two columns, Debit_Amount and Credit_Amount. A card row
    arrives as a single `Amount` plus a `Direction`, and the projection decides
    which column it fills — so a card bill payment was filed as a DEBIT because
    the statement printed it in the debit column. From the card's own point of
    view a payment is money coming *in*: it reduces the balance owed. Filing it as
    a debit made a transfer look like an expense.

    Overrides are the only place a row's direction is changed, and they are
    applied by moving the amount between the two columns, so every downstream sum
    (KPI, charts, CSV export) follows without needing to know about them. Priority
    matches the category rules: txn > narration > merchant.
    """
    if "Debit_Amount" not in df.columns or "Credit_Amount" not in df.columns:
        return df

    # Coerce and make each row single-sided first. A row that somehow carries
    # both amounts is a debit (the rarer case), and a row with neither is left
    # alone so it still shows up with its category and date.
    debit = pd.to_numeric(df["Debit_Amount"], errors="coerce").fillna(0).astype(float)
    credit = pd.to_numeric(df["Credit_Amount"], errors="coerce").fillna(0).astype(float)
    has_both = debit.gt(0) & credit.gt(0)
    if has_both.any():
        # Both sides present: keep the debit side and drop the duplicate credit.
        credit = credit.mask(has_both, 0.0)

    df["Debit_Amount"] = debit
    df["Credit_Amount"] = credit

    resolved = pd.Series("DEBIT", index=df.index, dtype=object)
    resolved = resolved.mask(debit.le(0) & credit.gt(0), "CREDIT")
    # Rows with no amount at all keep the neutral default rather than claiming a
    # direction they do not have.
    resolved = resolved.mask(debit.le(0) & credit.le(0), None)

    txn_rules, merchant_rules, narration_rules = _load_direction_rules(engine)
    if not (txn_rules or merchant_rules or narration_rules):
        df["Direction"] = resolved
        df["Direction_Source"] = "parsed"
        return df

    narr = _upper_series(df, "Narration")
    details = _upper_series(df, "Details")
    payee = _upper_series(df, "Payee_Receiver")
    chq = _upper_series(df, "Chq_Ref_Number")

    override = pd.Series([None] * len(df), index=df.index, dtype=object)
    source = pd.Series([None] * len(df), index=df.index, dtype=object)

    # Lowest priority first. Within a type the *first* matching rule wins, so each
    # list is applied in reverse - the earliest rule is written last and survives.
    for rule_type, rules in (("merchant", merchant_rules), ("narration", narration_rules)):
        for key, direction in reversed(rules):
            hit = _rule_hit_mask(df, rule_type, key, narr, details, payee, chq)
            if hit is None:
                continue
            hit = hit & override.isna()
            override = override.mask(hit, direction)
            source = source.mask(hit, rule_type)
    for key, direction in txn_rules.items():
        hit = _rule_hit_mask(df, "txn", key, narr, details, payee, chq)
        if hit is None:
            continue
        override = override.mask(hit, direction)
        source = source.mask(hit, "txn")

    changed = override.notna() & override.ne(resolved)
    if changed.any():
        amount = debit + credit
        to_credit = changed & override.eq("CREDIT")
        to_debit = changed & override.eq("DEBIT")
        df.loc[to_credit, "Debit_Amount"] = 0.0
        df.loc[to_credit, "Credit_Amount"] = amount[to_credit]
        df.loc[to_debit, "Credit_Amount"] = 0.0
        df.loc[to_debit, "Debit_Amount"] = amount[to_debit]
        resolved = resolved.mask(override.notna(), override)

    df["Direction"] = resolved
    df["Direction_Source"] = source.where(source.notna(), "parsed")
    return df


def _upper_series(df, column):
    """Normalised (NaN-safe, upper-cased, stripped) string Series, or None."""
    if column not in df.columns:
        return None
    return df[column].fillna("").astype(str).str.strip().str.upper()


def _rule_hit_mask(df, rule_type, key, narr, details, payee, chq):
    """Boolean mask of rows matched by one rule, or None when it cannot match."""
    if not key:
        return None
    if rule_type == "txn":
        return chq == key
    if rule_type == "merchant":
        return payee.str.contains(key, regex=False, na=False) if payee is not None else None
    # narration matches Narration or Details
    hit = narr.str.contains(key, regex=False, na=False) if narr is not None else None
    if details is not None:
        d = details.str.contains(key, regex=False, na=False)
        hit = d if hit is None else (hit | d)
    return hit


def _apply_category_rule_overrides(engine, df):
    """
    Applies DB override rules on top of the parser-computed Broad_Category.
    Priority: txn rule > narration (keyword substring) > merchant (payee substring) > parser value.
    Narration rules outrank merchant rules because an explicitly configured
    narration keyword is a more specific, deliberate match than a broad payee.

    Vectorised with column masks rather than a per-row apply. Within a rule type
    the *first* matching rule wins, so each list is applied in reverse — the
    earliest rule is written last and therefore survives.

    Sub_Category is then derived from the *resolved* Broad_Category and only
    overwritten where a rule names one explicitly. Deriving it after the broad
    pass is what keeps the two levels consistent: a rule that moves a transaction
    from Shopping_Retail to Rent must yield Residential_Rent, not the leaf the
    parser picked for Shopping_Retail.
    """
    txn_rules, merchant_rules, narration_rules = _load_category_rules(engine)

    if "Broad_Category" not in df.columns:
        df["Broad_Category"] = None
    broad = df["Broad_Category"].copy()

    narr = _upper_series(df, "Narration")
    details = _upper_series(df, "Details")
    payee = _upper_series(df, "Payee_Receiver")
    chq = _upper_series(df, "Chq_Ref_Number")

    empty = pd.Series([None] * len(df), index=df.index, dtype=object)
    sub_txn, sub_narration, sub_merchant = empty.copy(), empty.copy(), empty.copy()

    # Lowest priority first; each later layer overwrites the broad category.
    # Sub-categories are captured per layer and coalesced afterwards, because a
    # leaf is only meaningful once the parent is known.
    #
    # Each branch writes back to its OWN accumulator: rebinding a loop variable
    # here would leave the named series untouched and silently drop every
    # rule-supplied leaf.
    for rule_type, rules in (("merchant", merchant_rules), ("narration", narration_rules)):
        for key, (cat, subcat) in reversed(rules):
            hit = _rule_hit_mask(df, rule_type, key, narr, details, payee, chq)
            if hit is None or not hit.any():
                continue
            broad = broad.mask(hit, cat)
            if subcat:
                if rule_type == "merchant":
                    sub_merchant = sub_merchant.mask(hit, subcat)
                else:
                    sub_narration = sub_narration.mask(hit, subcat)

    # Highest priority: exact per-transaction pins, applied last.
    if txn_rules and chq is not None:
        # Non-matching keys map to NaN, so both projections must ignore NaN.
        mapped = chq.map(txn_rules)
        is_txn = mapped.notna()
        if is_txn.any():
            cats = mapped.map(lambda v: v[0] if isinstance(v, tuple) else None,
                              na_action="ignore")
            broad = broad.where(~is_txn, cats)
            subs = mapped.map(lambda v: v[1] if isinstance(v, tuple) else None,
                              na_action="ignore")
            has_sub = is_txn & subs.notna()
            if has_sub.any():
                sub_txn = sub_txn.mask(has_sub, subs)

    df["Broad_Category"] = broad

    # Derive the leaf from the resolved parent, then let explicit rules win.
    derived = pd.Series(
        [assign_sub_category(b, n, d, p, r)
         for b, n, d, p, r in zip(broad, df.get("Narration"), df.get("Details"),
                                  df.get("Payee_Receiver"), df.get("Reference_ID"))],
        index=df.index,
        dtype=object,
    )
    explicit = sub_txn.combine_first(sub_narration).combine_first(sub_merchant)
    df["Sub_Category"] = derived.where(explicit.isna(), explicit)
    return df


def get_sub_categories(engine):
    """All known sub-categories: built-in, user-added, and any in use."""
    names = set(BUILTIN_SUB_CATEGORIES)
    try:
        with engine.connect() as connection:
            names.update(
                str(r[0]) for r in connection.execute(
                    text(f"SELECT DISTINCT Sub_Category FROM {TABLE_NARRATION_DETAILS} WHERE Sub_Category IS NOT NULL")
                ).fetchall()
            )
            names.update(
                str(r[0]) for r in connection.execute(
                    text("SELECT DISTINCT sub_category FROM category_rules WHERE sub_category IS NOT NULL")
                ).fetchall()
            )
    except Exception:
        pass
    return sorted(n for n in names if n)


def get_broad_categories(engine):
    """All known broad categories (built-in + user-added + any in use)."""
    names = set(BUILTIN_CATEGORIES + ["Uncategorized"])
    try:
        with engine.connect() as connection:
            names.update(r[0] for r in connection.execute(
                text("SELECT name FROM broad_categories")
            ).fetchall())
            names.update(r[0] for r in connection.execute(
                text(f"SELECT DISTINCT Broad_Category FROM {TABLE_NARRATION_DETAILS} WHERE Broad_Category IS NOT NULL")
            ).fetchall())
            names.update(r[0] for r in connection.execute(
                text("SELECT DISTINCT category FROM category_rules")
            ).fetchall())
    except Exception:
        pass
    return sorted(names)


def add_broad_category(engine, name):
    """Registers a new (custom) broad category. Idempotent."""
    name = (name or "").strip()
    if not name:
        return False
    init_db_tables(engine)
    with engine.begin() as connection:
        connection.execute(
            text("INSERT IGNORE INTO broad_categories (name, is_builtin) VALUES (:n, 0)"),
            {"n": name},
        )
    return True


def delete_broad_category(engine, name):
    """
    Deletes a custom category together with all override rules that reference it.
    Built-in categories are protected.
    """
    name = (name or "").strip()
    init_db_tables(engine)
    with engine.begin() as connection:
        builtin = connection.execute(
            text("SELECT is_builtin FROM broad_categories WHERE name = :n"), {"n": name}
        ).fetchone()
        if builtin and builtin[0] == 1:
            return False
        connection.execute(text("DELETE FROM category_rules WHERE category = :n"), {"n": name})
        connection.execute(text("DELETE FROM broad_categories WHERE name = :n"), {"n": name})
    # Referencing rules were removed.
    invalidate_rules_cache()
    return True


def get_custom_broad_categories(engine):
    """Categories added from the UI (is_builtin = 0)."""
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text("SELECT name FROM broad_categories WHERE is_builtin = 0 ORDER BY name")
            ).fetchall()
        return [str(r[0]) for r in rows]
    except Exception:
        return []


def apply_category_rules(engine, rules):
    """
    Upserts override rules. `rules` is a list of (rule_type, rule_key, category)
    or (rule_type, rule_key, category, sub_category) tuples.
    rule_type: 'txn' | 'merchant' | 'narration'.
    Also registers any new category in the broad_categories registry.

    When a sub_category is supplied and no explicit broad category is, the
    sub-category's parent is used, so a leaf never ends up under the wrong
    parent.
    """
    if not rules:
        return 0
    init_db_tables(engine)
    applied = 0
    with engine.begin() as connection:
        for rule in rules:
            rule_type, rule_key, category = rule[0], rule[1], rule[2]
            sub_category = rule[3] if len(rule) > 3 else None

            rule_key = str(rule_key or "").strip()
            category = str(category or "").strip()
            sub_category = str(sub_category or "").strip() or None
            if not rule_key or not category:
                continue

            for name, builtin in ((category, 0), (sub_category, 0)):
                if name:
                    connection.execute(
                        text("INSERT IGNORE INTO broad_categories (name, is_builtin) VALUES (:n, :b)"),
                        {"n": name, "b": builtin},
                    )

            connection.execute(
                text("""
                    INSERT INTO category_rules (rule_type, rule_key, category, sub_category)
                    VALUES (:t, :k, :c, :s)
                    ON DUPLICATE KEY UPDATE category = VALUES(category),
                                            sub_category = VALUES(sub_category)
                """),
                {
                    "t": rule_type,
                    "k": rule_key.strip().upper(),
                    "c": category,
                    "s": sub_category,
                },
            )
            applied += 1
    # Only the rules changed; the cached JOIN result stays valid.
    invalidate_rules_cache()
    return applied


def apply_direction_rules(engine, rules):
    """
    Upserts debit/credit overrides. `rules` is a list of
    (rule_type, rule_key, direction) tuples, rule_type being
    'txn' | 'merchant' | 'narration' and direction 'CREDIT' | 'DEBIT'.
    Returns the number of rules written.
    """
    if not rules:
        return 0
    init_db_tables(engine)
    applied = 0
    with engine.begin() as connection:
        for rule in rules:
            rule_type, rule_key, direction = rule[0], rule[1], rule[2]
            rule_key = str(rule_key or "").strip()
            direction = str(direction or "").strip().upper()
            if not rule_key or direction not in ("CREDIT", "DEBIT"):
                continue
            connection.execute(
                text(f"""
                    INSERT INTO {TABLE_DIRECTION_RULES} (rule_type, rule_key, direction)
                    VALUES (:t, :k, :d)
                    ON DUPLICATE KEY UPDATE direction = VALUES(direction)
                """),
                {"t": rule_type, "k": rule_key.upper(), "d": direction},
            )
            applied += 1
    # Only the rules changed; the cached JOIN result stays valid.
    invalidate_rules_cache()
    return applied


def delete_direction_rules(engine, rule_type, rule_keys):
    """
    Deletes debit/credit overrides of the given type for specific keys
    (case-insensitive). Used to clear stale per-transaction pins so a narration
    rule can take effect cleanly.
    """
    keys = [str(k).strip().upper() for k in rule_keys if str(k or "").strip()]
    if not keys or not rule_type:
        return 0
    deleted = 0
    with engine.begin() as connection:
        for k in keys:
            result = connection.execute(
                text(
                    f"DELETE FROM {TABLE_DIRECTION_RULES} "
                    "WHERE rule_type = :t AND rule_key = :k"
                ),
                {"t": rule_type, "k": k},
            )
            deleted += result.rowcount
    invalidate_rules_cache()
    return deleted


# ---------------------------------------------------------------------------
# Transaction notes
#
# Notes are stored per transaction rather than derived, so this is the one place a
# write is neither a rule nor a re-parse: it is user data that has to survive both.
# ---------------------------------------------------------------------------

def get_notes(engine, chq_refs=None):
    """
    Returns {Chq_Ref_Number: {note, source, suggestion, updated_at}} for the given
    references, or an empty dict when chq_refs is None.

    Read straight from the table rather than from the cached frame, because these
    are the very endpoints that invalidate that cache — a reader sharing it would
    be serving the frame the writer just dropped, and the user would watch their own
    save fail to appear.
    """
    refs = [str(r).strip() for r in (chq_refs or []) if str(r or "").strip()]
    if not refs:
        return {}

    placeholders = ",".join(f":r{i}" for i in range(len(refs)))
    params = {f"r{i}": ref for i, ref in enumerate(refs)}
    with engine.connect() as connection:
        rows = connection.execute(
            text(f"""
                SELECT Chq_Ref_Number, Note, Source, Suggestion, Updated_At
                FROM {TABLE_TRANSACTION_NOTES}
                WHERE Chq_Ref_Number IN ({placeholders})
            """),
            params,
        ).fetchall()

    return {
        str(row[0]): {
            "note": row[1],
            "source": row[2],
            "suggestion": row[3],
            "updated_at": row[4].isoformat() if hasattr(row[4], "isoformat") else row[4],
        }
        for row in rows
    }


def set_notes(engine, refs, note=None, suggestion=None, source="user"):
    """
    Writes one note across many transactions inside a single DB transaction.

    `note=None` CLEARS the note on those references. An empty note and an absent
    note are different states, and only one of them means "the user wrote nothing
    here", so clearing removes the row rather than storing ''.

    `suggestion` is stored separately from `note`, so the last thing the LLM
    proposed for a row survives even when the user rejected it. Keeping the rejected
    proposal is what lets the UI say "we suggested X, you kept Y" instead of
    throwing away the machine's reasoning with nothing to show for it.

    Returns the number of references written or cleared.

    Unknown references are rejected rather than skipped. A note against a row that
    does not exist is indistinguishable from a note that saved, and would surface
    either later as a foreign-key error or not at all.
    """
    clean = [str(r).strip() for r in (refs or []) if str(r or "").strip()]
    if not clean:
        return 0

    with engine.begin() as connection:
        placeholders = ",".join(f":r{i}" for i in range(len(clean)))
        params = {f"r{i}": ref for i, ref in enumerate(clean)}
        known = {
            str(row[0])
            for row in connection.execute(
                text(f"SELECT Chq_Ref_Number FROM {TABLE_TRANSACTIONS} "
                     f"WHERE Chq_Ref_Number IN ({placeholders})"),
                params,
            ).fetchall()
        }
        unknown = [ref for ref in clean if ref not in known]
        if unknown:
            shown = ", ".join(unknown[:10])
            raise ValueError(
                f"Unknown transaction reference(s): {shown}"
                + (f" (+{len(unknown) - 10} more)" if len(unknown) > 10 else "")
            )

        if note is None:
            # Clearing keeps any stored suggestion, so the UI can still explain
            # where the last machine proposal came from.
            connection.execute(
                text(f"""
                    UPDATE {TABLE_TRANSACTION_NOTES}
                    SET Note = NULL, Updated_At = NOW()
                    WHERE Chq_Ref_Number IN ({placeholders}) AND Note IS NOT NULL
                """),
                params,
            )
            # ...then drop the rows that are now note-less AND never had a
            # suggestion, so they stop shadowing the editor.
            connection.execute(
                text(f"DELETE FROM {TABLE_TRANSACTION_NOTES} "
                     f"WHERE Chq_Ref_Number IN ({placeholders}) "
                     f"AND Note IS NULL AND Suggestion IS NULL"),
                params,
            )
            invalidate_transaction_cache()
            return len(clean)

        for ref in clean:
            connection.execute(
                text(f"""
                    INSERT INTO {TABLE_TRANSACTION_NOTES}
                        (Chq_Ref_Number, Note, Source, Suggestion, Updated_At)
                    VALUES (:r, :n, :s, :g, NOW())
                    ON DUPLICATE KEY UPDATE
                        Note = VALUES(Note),
                        Source = VALUES(Source),
                        Suggestion = COALESCE(VALUES(Suggestion), Suggestion),
                        Updated_At = NOW()
                """),
                {"r": ref, "n": note, "s": source, "g": suggestion},
            )

    # Notes are JOINed into the cached frame, so this is a data write, not a rules
    # write: the cache is stale until it is dropped.
    invalidate_transaction_cache()
    return len(clean)


def clear_notes(engine, refs):
    """
    Removes the note row outright for the given references, including any stored
    suggestion. Returns the count. Returns 0 and touches nothing when the
    references do not exist.
    """
    clean = [str(r).strip() for r in (refs or []) if str(r or "").strip()]
    if not clean:
        return 0
    placeholders = ",".join(f":r{i}" for i in range(len(clean)))
    params = {f"r{i}": ref for i, ref in enumerate(clean)}
    with engine.begin() as connection:
        result = connection.execute(
            text(f"DELETE FROM {TABLE_TRANSACTION_NOTES} "
                 f"WHERE Chq_Ref_Number IN ({placeholders})"),
            params,
        )
        deleted = result.rowcount
    invalidate_transaction_cache()
    return deleted


# ---------------------------------------------------------------------------
# Category definitions
# ---------------------------------------------------------------------------

def get_category_definitions(engine):
    """
    Every category's definition, in display order, with the direction already
    resolved against the user's override.

    The registry (broad_categories) is the authority on WHICH names exist, so a
    user-added category with no definition row still appears — reported as
    undefined rather than omitted. Omitting it would make a custom category
    invisible in the one screen whose entire job is to explain the categories.
    """
    with engine.connect() as connection:
        def_rows = connection.execute(
            text("""
                SELECT name, description, examples, direction_override, is_builtin
                FROM category_definitions
            """)
        ).fetchall()

    definitions = {
        str(r[0]): {
            "description": r[1],
            "examples": r[2],
            "direction_override": r[3],
            "is_builtin": bool(r[4]),
        }
        for r in def_rows
    }
    overrides = {k: v["direction_override"] for k, v in definitions.items()}

    def sort_key(item):
        name = item[0]
        try:
            return (0, BUILTIN_CATEGORIES.index(name), name)
        except ValueError:
            return (1, 0, name)

    return [
        {
            "name": name,
            "description": entry.get("description"),
            "examples": entry.get("examples"),
            "direction": category_direction(name, overrides),
            "direction_override": entry.get("direction_override"),
            "code_direction": CATEGORY_DIRECTION.get(name, DIRECTION_BOTH),
            "is_builtin": entry.get("is_builtin", False),
        }
        for name, entry in sorted(definitions.items(), key=sort_key)
    ]


def upsert_category_definition(engine, name, description=None, examples=None,
                               direction_override=None):
    """
    Creates or updates one category's definition and returns the full list.

    The name is registered in broad_categories too if it is new, so defining a
    category and using one are the same act from the user's side — a definition for
    a name no dropdown offers is a note to self.

    is_builtin is intentionally NOT overwritten on update. This table can reword a
    built-in, but not demote it out of the protected set: is_builtin is what makes
    DELETE /categories/{name} refuse to remove it.
    """
    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("Category name cannot be empty")

    override = str(direction_override or "").strip().upper() or None
    if override and override not in DIRECTION_VALUES:
        raise ValueError(
            f"direction_override must be one of {', '.join(DIRECTION_VALUES)}"
        )

    with engine.begin() as connection:
        connection.execute(
            text("INSERT IGNORE INTO broad_categories (name, is_builtin) VALUES (:n, 0)"),
            {"n": clean_name},
        )
        connection.execute(
            text("""
                INSERT INTO category_definitions
                    (name, description, examples, direction_override, is_builtin, updated_at)
                VALUES (:n, :d, :e, :o, 0, NOW())
                ON DUPLICATE KEY UPDATE
                    description = VALUES(description),
                    examples = VALUES(examples),
                    direction_override = VALUES(direction_override),
                    updated_at = NOW()
            """),
            {"n": clean_name, "d": description, "e": examples, "o": override},
        )

    invalidate_direction_override_cache()
    return get_category_definitions(engine)


def delete_category_definition(engine, name):
    """
    Removes one definition, leaving the category itself registered. Returns count.

    Only the definition goes: the name is still referenced by rules and by stored
    rows, and dropping the registry entry would break every dropdown that lists it.
    A built-in's definition returns on the next init, seeded from CATEGORY_SPECS —
    which is the right outcome, because a code-owned definition should not be
    permanently deletable.
    """
    clean_name = str(name or "").strip()
    if not clean_name:
        return 0
    with engine.begin() as connection:
        result = connection.execute(
            text("DELETE FROM category_definitions WHERE name = :n"),
            {"n": clean_name},
        )
        deleted = result.rowcount
    invalidate_direction_override_cache()
    return deleted
def delete_category_rules(engine, rule_type, rule_keys):
    """
    Deletes override rules of the given type ('txn' | 'merchant' | 'narration')
    for specific keys (case-insensitive). Returns the number of rows deleted.
    Used to clear stale per-transaction pins so a narration rule can take effect.
    """
    keys = [str(k).strip().upper() for k in rule_keys if str(k or "").strip()]
    if not keys or not rule_type:
        return 0
    deleted = 0
    with engine.begin() as connection:
        for k in keys:
            result = connection.execute(
                text("DELETE FROM category_rules WHERE rule_type = :t AND rule_key = :k"),
                {"t": rule_type, "k": k},
            )
            deleted += result.rowcount
    invalidate_rules_cache()
    return deleted
