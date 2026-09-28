# AGENTS.md — StatementParser Project Reference

> This file is a comprehensive reference for AI models and developers working on the **StatementParser** project. Read this before making any changes.

---

## Project Overview

**StatementParser** is a Python-based bank statement ingestion, parsing, analysis, and visualization tool. It parses HDFC Bank (and similar Indian bank) `.xls`/`.xlsx`/`.csv`/`.pdf` statements, extracts transaction data, parses narrations into structured fields, stores everything in a MySQL database, and serves an interactive web dashboard from a **FastAPI** backend with a **Next.js** frontend.

**Stack:** Python 3, FastAPI, Uvicorn, Next.js 16 (App Router), React 19, TypeScript, Recharts, SWR, Axios, SQLAlchemy (MySQL via PyMySQL), Pandas, pdfplumber, xlrd, openpyxl.

> **The Streamlit UI has been removed.** `app.py`, `run_app.py`, `visualizer.py`, `main.py`, `statements.py`, and `.streamlit/` were deleted. The FastAPI + Next.js dashboard is the only UI. Do not reintroduce Streamlit, Matplotlib, or Plotly.

---

## Directory Structure

```
StatementParser/
├── api/                          # FastAPI backend
│   ├── main.py                   # App factory, CORS, router mounting, lifespan
│   ├── deps.py                   # Cached SQLAlchemy engine dependency
│   └── routers/
│       ├── transactions.py       # Read/filter/aggregate/upload/export endpoints
│       └── categories.py         # Category CRUD + override rule endpoints
├── config.py                     # DB credentials, table names, column definitions, paths
├── db.py                         # MySQL connection, table creation, CRUD, aggregations
├── loader.py                     # Statement file loading, cleaning, column normalization
├── pdf_loader.py                 # PDF statement table extraction (pdfplumber)
├── narration_parser.py           # Parses raw narration strings into structured fields
├── category_rules.py             # Broad-category rule engine + builtin categories
├── mask_statement.py             # PII masking utility for .xls files
├── start.py                      # Unified launcher: FastAPI :8000 + Next.js :3000
├── dashboard/                    # Next.js frontend
│   ├── next.config.ts            # Rewrites /api/* -> localhost:8000/api/*
│   ├── package.json
│   └── src/
│       ├── app/page.tsx          # Root page: state, tabs, data wiring
│       ├── components/           # Sidebar, KpiCards, TabNav, charts/, tables/, modals/
│       ├── hooks/                # useTransactions.ts (SWR), useCategories.ts (SWR)
│       ├── lib/                  # api.ts (axios + params), formatters.ts
│       └── types/index.ts        # TypeScript mirrors of API response shapes
├── masked/                       # PII-masked .xls statements for dev/testing
└── AGENTS.md
```

---

## Running

```bash
python start.py          # Launches both servers; Ctrl+C stops both
```

Or separately:

```bash
uvicorn api.main:app --reload --port 8000    # API   -> http://localhost:8000/docs
cd dashboard && npm run dev                  # UI    -> http://localhost:3000
```

**Verification commands** (no formal test suite exists):

```bash
python -m py_compile api/main.py api/deps.py api/routers/*.py *.py
python verify_card_view.py                              # card view + shared filter path
python verify_final.py                                  # card ingest end-to-end
cd dashboard && npx tsc --noEmit && npm run build
```

`verify_card_view.py` is the closest thing to a regression suite for the shared
filter path. Against the live database it asserts that each card's category
breakdown sums to its own KPI debits and that each card's timeline row count
equals its own KPI count — i.e. that the card view and the bank view cannot
disagree. It also asserts the three summary endpoints honour `sub_categories`,
`categories` and `spend_basis` (the positional-argument bug noted below) and
that `card_ids` narrows every aggregate. Its section `4b` guards Decision 24:
every `Credit_Card_Payment` row must carry `Is_Settlement`, none may leak into
spend, reconciliation must see the override-created payments too, and the
category breakdown must sum to the KPI. That section includes a
"not a vacuous pass" assertion, because a case-sensitive regex against
`Broad_Category` silently matched zero rows and turned the guard into a no-op.
Section `4b2` is its mirror: a **single-ledger** view must keep its own half of a card payment — as card inflow, as bank outflow — while the combined view drops both. Together they pin the scope rule in Decision 17 from both sides.
Section `4c` guards the other half of Decision 17: a **single-category**
drill-down must still return that category's settlement rows, while the
cross-category breakdown must still exclude them. Extend it when touching
`_get_filtered_df`, `_settlement_handling`, or the derivation order in
`get_all_transactions_with_details`.

---

## Data Flow

```
.xls/.xlsx/.csv/.pdf Statement
        │
        ▼
   loader.py  ──→  Clean DataFrame (7 standard columns)
        │           (pdf_loader.py handles .pdf)
        ▼
   narration_parser.py  ──→  Narration Details DataFrame (9 cols incl. Broad_Category)
        │           (category_rules.assign_broad_category classifies)
        ▼
   db.py  ──→  MySQL (transactions + narration_details + category_rules,
        │           idempotent INSERT IGNORE)
        ▼
   api/  ──→  REST/JSON  ──→  dashboard/ (Next.js + Recharts)
```

Credit-card statements take a parallel path, because they are not bank
statements (no Value Date, no Closing Balance, and the rupee glyph extracts as
the letter `C` on HDFC) and cannot go through `loader.py`:

```
Credit-card statement .pdf
        │
        ▼
   card_loader.py  ──→  per-issuer adapter (HDFC | ICICI | SCAPIA)
        │              + cycle totals + issuer-supplied categories
        ▼
   card_store.py  ──→  MySQL credit_cards / credit_card_statements /
        │              credit_card_transactions  (idempotent)
        │
        ▼
   ingest_cards.py  ──→  projects rows into transactions + narration_details
        │                so the existing dashboard aggregates pick them up
        ▼
   api/  ──→  same REST/JSON  ──→  same dashboard
```

---

## File-by-File Reference

### `config.py`
- **Purpose:** Central configuration — DB credentials (env-var backed), table names, required column definitions, file paths.
- **Key Constants:** `DB_USER`/`DB_PASSWORD`/`DB_HOST`/`DB_PORT`/`DB_NAME` (default `root/root@localhost:3306/statements`), `TABLE_TRANSACTIONS`, `TABLE_NARRATION_DETAILS`, `REQUIRED_COLUMNS` (the 7 standard columns), `DEFAULT_STATEMENT_PATH`.

### `loader.py`
- **Purpose:** Loads and cleans bank statement files. Handles `.xls`, `.xlsx`, `.csv`, `.pdf`.
- **Key Function:** `load_and_clean_statement(file_source, filename=None)` → `pd.DataFrame`
  - Accepts a filepath (`str`) or a file-like object (FastAPI `UploadFile`).
  - Dynamically locates the header row by scanning the first 50 rows for "Date" + ("Narration"/"Description"/"Particulars").
  - Skips separator rows (`*****`) and footer markers ("STATEMENT SUMMARY", "End Of Statement", "Generated On:").
  - Normalizes column names via fuzzy matching (e.g. "Withdrawal Amt" → `Debit_Amount`).
  - Parses dates in `%d/%m/%y` format (with `%d/%m/%Y` fallback).
  - Replaces dummy/empty `Chq_Ref_Number` values (`"000000000000000"`, empty, None) with deterministic UUID5 hashes from a transaction fingerprint, guaranteeing idempotent imports.
- **Wrapper:** `clean_csv_data(file_path)` — backwards-compat alias.

### `pdf_loader.py`
- **Purpose:** Extracts the transaction table from text-based statement PDFs.
- **Key Function:** `extract_pdf_transactions(file_source, filename=None)` → `pd.DataFrame`
- **Two extraction paths:** primary `pdfplumber` table detection (`_page_table_rows`), with a word-coordinate fallback (`_fallback_page_rows`) that reconstructs rows using hardcoded x-coordinate column bands (`COLUMN_BANDS`). Each page uses whichever path yields more rows.
- Requires `pdfplumber`; raises a clear `RuntimeError` with install instructions if missing.

### `narration_parser.py`
- **Purpose:** Parses raw HDFC-style narration strings into structured fields.
- **Key Function:** `parse_narration(narration, debit_amount=None, credit_amount=None)` → `dict` with `Transaction_Type`, `Details`, `Reference_ID`, `Payee_Receiver`, `Date_Range`, `Remarks`, `Other_Info`, `Broad_Category`.
- **Amount params:** `debit_amount`/`credit_amount` are optional and used by `assign_broad_category` to disambiguate income (Salary/Dividend/Interest) vs. expense flows.
- **Bulk Function:** `parse_narrations_dataframe(transaction_df)` → `pd.DataFrame` keyed by `Chq_Ref_Number`; tolerates missing amount columns.
- **Pattern Matching:** prefix/split detection plus regex for specific formats (ATM date ranges, forex amounts, etc.).

### `category_rules.py`
- **Purpose:** Broad-category rule engine — maps every transaction to a high-level purpose category (`Salary`, `Rent`, `Food_Dining`, …).
- **Key Constants:** `BUILTIN_CATEGORIES` (21 names incl. `Uncategorized`), `PAYEE_CATEGORY_MAP` (seed payee→category overrides; seed for the DB `category_rules` table), `CATEGORY_PARENT` (broad → parent rollup), `SUBCATEGORY_KEYWORD_RULES` (ordered, first match wins), `SUBCATEGORY_DEFAULTS`, `BUILTIN_SUB_CATEGORIES`.
- **Key Function:** `assign_broad_category(narration, transaction_type, details, payee_receiver, reference_id, has_debit=False, has_credit=False)` → `str`
  - Priority: keyword rules (RENT, credit-card, salary, GST, dividend, investments, food, groceries, shopping, travel, utilities, fees) → channel-level fallbacks (ATM, INTEREST income/paid, FOREX) → generic `P2P_Transfer` / `Uncategorized`.
  - DB override rules are applied *at read time* and take precedence over anything this returns.
- **Key Function:** `assign_sub_category(broad_category, narration, details, payee_receiver, reference_id)` → `str` — refines a broad category into a leaf. Returns the broad category unchanged when nothing matches, so every transaction has a leaf and the rollup always totals.
- **Key Function:** `parent_category(broad_category)` → `str` — maps up to the parent rollup, falling back to `Other`.

### `db.py`
- **Purpose:** MySQL operations — connection, table init/migration, storage, querying, and the user-editable broad-category override layer.
- **Key Functions:**
  - `create_mysql_connection(...)` → SQLAlchemy `Engine`
  - `init_db_tables(engine, seed=True)` — creates all four tables, migrates `narration_details` (`ALTER TABLE ADD COLUMN Broad_Category`), drops empty incompatible legacy tables, seeds `broad_categories` + `category_rules` (`INSERT IGNORE` on every init — self-healing, never overwrites user rules), then runs `CATEGORY_RENAMES`.
  - `insert_ignore_on_duplicate(table, conn, keys, data_iter)` — custom `pandas.to_sql` method using MySQL `INSERT IGNORE`
  - `store_data_in_db(engine, transaction_data, narration_data)` — idempotent insert of both frames
  - `get_all_transactions_with_details(engine)` → `pd.DataFrame` — JOINs transactions + narration_details, applies override rules, then derives `Category`, `Sub_Category` and `Is_Settlement` **from the resolved categories**, and adds `is_recurring`, `Year`, `Month`, `Month_Name`, `Year_Month`. **All three category-derived columns are computed after `_apply_category_rule_overrides`**; anything reading `Broad_Category` before that point sees the parser's value, not the user's (see Decision 24). **Served from an in-process cache** (see Design Decision 11); returns a copy, since callers mutate the frame.
  - `recategorize_all_narrations(engine)` → `(old_counts, new_counts)` — re-runs the parser over all rows and rebuilds `narration_details`
  - `apply_category_rules(engine, rules)` / `delete_category_rules(engine, rule_type, rule_keys)` — upsert/delete `category_rules` rows
  - `get_broad_categories(engine)` / `get_custom_broad_categories(engine)` / `get_sub_categories(engine)` / `add_broad_category(engine, name)` / `delete_broad_category(engine, name)`
  - `get_yearly_credit_debit`, `get_monthly_credit_debit`, `get_monthly_category_summary`, `get_category_summary` — DataFrame-level aggregations (currently used by nothing in the API; the routers aggregate inline)
- **Primary Key:** `Chq_Ref_Number` on `transactions`. `narration_details` has an FK to it.

### `api/deps.py`
- **Purpose:** Shared FastAPI dependency. `get_engine()` returns a process-wide `Engine` via `@lru_cache(maxsize=1)`, running `init_db_tables(engine, seed=True)` on first use (which also happens in the `lifespan` startup hook).

### `api/main.py`
- **Purpose:** App factory. Adds the project root to `sys.path` (so `db`, `loader`, `config` import directly), clears `SSLKEYLOGFILE`, mounts both routers under `/api`, enables CORS for `localhost:3000` / `127.0.0.1:3000`, and exposes `GET /api/health`.

### `api/routers/transactions.py`
- **Purpose:** All transaction read/filter/aggregate operations plus upload, export, and recategorize.
- **Shared internals:**
  - `_split_csv(raw)` / `_split_int_csv(raw)` — parse comma-separated query params.
  - `_get_filtered_df(engine, years, months, txn_types, broad_categories, direction, search, amount_field, amount_min, amount_max, year_months, sub_categories, categories, is_recurring)` — the single filtering path. `direction` is `all|debits|credits`; `search` matches Narration / Payee_Receiver / Reference_ID / Details / Chq_Ref_Number; `year_months` is an exact `YYYY-MM` match used for drill-down scoping; `categories` filters the parent rollup, `sub_categories` the leaf, and `is_recurring` splits committed vs one-off.
  - `_df_to_records(df)` / `_safe_val(v)` — JSON-safe serialization (NaN/NaT → `null`, datetimes → ISO).
- **Endpoints:**

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/transactions` | Paginated, sortable, filtered list |
| GET | `/api/transactions/meta` | Available years / months / txn types / all three category levels |
| GET | `/api/transactions/kpis` | Credits, debits, net cashflow, filtered/spend/settlement row counts, and the settlement halves |
| GET | `/api/transactions/direction-rules` | The debit/credit overrides currently in force |
| POST | `/api/transactions/direction-rules/preview` | Rows a direction rule would actually change |
| POST | `/api/transactions/direction-rules` | Upsert direction rules |
| POST | `/api/transactions/direction-rules/apply-cascade` | Apply with per-row exclusions |
| POST | `/api/transactions/direction-rules/delete` | Delete rules by key |
| GET | `/api/transactions/summary/timeline` | Grouped by `group_by=month\|year` |
| GET | `/api/transactions/summary/monthly-category` | Grouped by period × `Broad_Category` |
| GET | `/api/transactions/summary/category-breakdown` | Grouped by `group_col=Category\|Broad_Category\|Sub_Category\|Transaction_Type` |
| GET | `/api/transactions/balance-trend` | Closing balance over time |
| GET | `/api/transactions/category-trend` | Monthly trend for one `category` |
| GET | `/api/transactions/export` | **Full** filtered set as CSV (BOM, `Content-Disposition`) |
| POST | `/api/transactions/upload` | Parse + store `.xls`/`.xlsx`/`.csv`/`.pdf` |
| POST | `/api/transactions/load-sample` | Seed an empty DB from the bundled sample |
| POST | `/api/transactions/recategorize` | Re-parse all narrations |

- `SORTABLE_COLUMNS` whitelists server-side sort keys.
- `_apply_spend_basis` implements the `spend_basis` parameter; every endpoint also accepts `account_sources` (`BANK`/`CREDIT_CARD`) and `card_ids` (specific `Card_ID` values). All three are applied at the top of `_get_filtered_df`, so every aggregate inherits them. `spend_basis` = `all` | `bank_only` | `card_only`. `card_ids` is a no-op on bank rows (their `Card_ID` is NULL), which lets the card view reuse the same filter path for both ledgers.
- **`_settlement_handling(spend_basis, account_sources)`** decides whether a *cashflow* total keeps card settlements, because the double count only exists when both halves are in view: combined → drop both; bank-only or card-only → keep the one half actually present. It is why the card view shows a bill payment as inflow and the bank view shows it as outflow. `_get_filtered_df` also takes `include_settlements` (default **False**), used only by `/kpis` so it can report the rows it held out — defaulting it to `True` would silently disable `exclude_settlements` for every other caller.
- **Call `_get_filtered_df` with keyword arguments.** The signature is 17 parameters; three endpoints once passed them positionally with a one-slot offset, silently binding `year_months` to `sub_list` and dropping `account_sources` entirely. An AST check in `verify_card_view.py` guards this.
- `_resolve_sample_statement()` prefers `config.DEFAULT_STATEMENT_PATH`, then falls back to the newest masked statement in `masked/` (the unmasked original is not distributed).

### `api/routers/cards.py`
- **Purpose:** Credit-card endpoints. The aggregated dashboard reads the shared `transactions` table, so these cover only what the bank schema cannot hold: the cycle totals the issuer printed, the issuer's own category, and whether the bank actually paid each statement.
- **Endpoints:**

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/cards` | Card registry with statement count and total parsed spend |
| GET | `/api/cards/statements` | One row per billing cycle, incl. the issuer's `Total_Spend` and the `Spend_Mix` JSON |
| GET | `/api/cards/spend` | Card spend by card × category, read from the shared ledger so it always agrees with the dashboard |
| GET | `/api/cards/reconcile` | Pairs each statement with the bank debit that paid it; reports unmatched in **both** directions |
| GET | `/api/cards/issuer-categories` | How often each issuer supplied its own category (explains accuracy) |

- `reconcile` delegates to the pure `match_statements_to_debits` in `card_store.py` (see below), so the pairing rules are testable without a database.

### `api/routers/categories.py`
- **Purpose:** Broad-category CRUD and override-rule management.
- **Endpoints:**

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/categories` | All known categories (built-in + custom + in use) |
| GET | `/api/categories/custom` | User-added only |
| GET | `/api/categories/sub` | All known sub-categories (leaves) |
| POST | `/api/categories` | Add a custom category |
| DELETE | `/api/categories/{name}` | Delete a custom category (built-ins rejected with 400) |
| POST | `/api/categories/preview` | Transactions a rule would affect |
| POST | `/api/categories/rules` | Upsert rules |
| POST | `/api/categories/rules/apply-cascade` | Apply a rule with per-transaction exclusions |
| POST | `/api/categories/rules/delete` | Delete rules by key |

- `_find_matching_transactions(df, rule_type, rule_key)` implements the match semantics per `rule_type` (`txn` = exact ref, `merchant` = payee substring, `narration` = Narration/Details substring), all case-insensitive.
- **Exclusion handling in `apply-cascade`:** excluded refs are *pinned* with synthetic `txn` rules at their current category **and leaf**, and stale `txn` overrides on included rows are cleared so the broader rule takes effect cleanly.

### `start.py`
- **Purpose:** Unified launcher. Starts Uvicorn (`:8000`, `--reload`) and `npm run dev` (`:3000`) as subprocesses, waits, and terminates both on SIGINT/SIGTERM.

### `mask_statement.py`
- **Purpose:** PII masking for HDFC `.xls` files (names, account numbers, emails, branch names, MICR codes, open dates in the first 19 rows of each sheet).
- **Usage:** `python mask_statement.py <file.xls>` or `python mask_statement.py --dir <folder> --output masked`
- **Dependencies:** `xlrd`, `xlwt`, `xlutils`

### `mask_card_statement.py`
- **Purpose:** PII masking for credit-card statement **PDFs**. Uses PyMuPDF redaction annotations (`add_redact_annot` + `apply_redactions`) so glyphs are **removed from the content stream** — a black box drawn over text leaves it selectable and recoverable via `pdftotext`. Document metadata is scrubbed too.
- **Usage:** `python mask_card_statement.py <file.pdf> [-o out.pdf] [--dry-run]` or `--dir <folder> [--output-dir masked_cards]`
- **What it protects:** transaction rows, narrations, amounts and dates. A parser depends on them, so masking must never blank a data row.
- **Why it is not line-based:** redaction is span-level (`_span_rect` locates the exact matched characters) and `TXN_ROW`/`NARRATION` guards protect data lines. Redacting whole lines — the first version — silently destroyed transaction references whenever an IFSC or a long digit run matched.
- **Depends on:** `pymupdf` only.

### `card_loader.py`
- **Purpose:** Parses credit-card statement PDFs. One adapter per issuer family; the issuer is detected from page 1 and an unknown issuer raises rather than importing an empty ledger.
- **Key function:** `load_card_statement(file_source, filename=None)` → `(DataFrame, meta)`, using `config.CREDIT_CARD_COLUMNS`.
- **Layouts (all verified against the four files in `CreditCard/`):**
  - **HDFC** (Regalia, Tata Neu Infinity) — the two cards do **not** share a column layout: Tata Neu starts the date at x=25.5 while Regalia indents the whole table to x=169.5. Bands are therefore **derived per page** from that page's own column header (`_hdfc_bands`), never hardcoded. The description cell is **vertically centred**, so a wrapped description renders one line *above* the date anchor and the rest below; `ROW_TOLERANCE = 5.5` captures both while the 14.2pt row pitch keeps neighbouring rows apart. The rupee glyph comes from the `ITFRupee` font and extracts as `C`.
  - **ICICI** (Amazon Pay) — transactions exist only on page 1; the other 8 pages are T&C with illustrative tables. A `25%` reward-rate column sits at x=146, i.e. **left of** the date anchor at x=207.8, so rows are grouped by the date anchor and never by the left-most token. Credits are marked with a trailing `CR` that is a **separate token** — breaking on the amount first loses the credit flag.
  - **SCAPIA** (Federal) — date and time share one token (`13-08-2026·21:21`, U+00B7), and the cover page is typeset without spaces and additionally hard-wrapped mid-word (`Transact`/`ions`), so summary matching runs against whitespace-squashed text.
- **Issuer-supplied categories:** ICICI prints the merchant category inside the description (`AMAZON PAY IN GROCERY BANGALORE IN`), captured as `Statement_Category` via `ICICI_DESC_CATEGORY` + `ICICI_CATEGORY_MAP`. HDFC instead prints a **cycle-level** mix (`GROCERIES 21% / RESTAURANT 19% …`) captured as `Spend_Mix` on the statement — it validates the parser's own totals but cannot tag individual rows.

### `card_store.py`
- **Purpose:** Persistence for the three card tables, plus the projection into the shared ledger. Separate from `db.py` so the bank-ledger code stays focused; `db.py` calls `init_card_tables` from its own `init_db_tables`.
- **Key functions:** `store_card_statement(engine, df, meta)`, `to_ledger_rows(txn_df, meta)`, `make_card_id` / `make_statement_id` / `make_txn_id` / `make_ledger_ref`, `reconcile_card_payments(engine)` and the pure `match_statements_to_debits(statements, debits)`.
- **Card identity is `(Issuer, Last4)` when available.** Masked statements often expose no digits, and two masked HDFC cards would then collapse onto one identity and merge their spend, so the source filename is used as the fallback token.
- **Reconciliation reads the shared resolved ledger, not raw SQL.** `_load_reconciliation_frames` takes the bank side from `db.get_all_transactions_with_details` and filters on the derived `Is_Settlement`, rather than re-querying `narration_details` for the *stored* `Broad_Category`. It previously did the latter, so it could not see a payment a user had reclassified to `Credit_Card_Payment` via a `category_rules` entry — the two views of the same payment disagreed. It imports `db` lazily to avoid the circular import.
- **Ledger keys are namespaced** `CC:<Card_ID>:<CC_Txn_ID>`, so a card row can never collide with a bank `Chq_Ref_Number`. Transaction ids include a row index so two identical same-day charges stay distinct while a re-import stays idempotent.

### `ingest_cards.py`
- **Purpose:** CLI to import statement PDFs — `python ingest_cards.py [--dir CreditCard] [--no-ledger]`.
- **Reports `Spend_Variance`** = (parsed debits − settlement rows) − the issuer's printed cycle total. The settlement row is excluded because the issuer's `PURCHASES/DEBIT` counts purchases only; comparing the raw debit sum reports a variance equal to the card payment on *every* statement, which is correct behaviour mislabelled as a parsing error.
- **Issuer categories win over the keyword parser** in the projection, and the `Sub_Category` leaf is re-derived from the issuer's parent so the two levels cannot disagree.
- **Depends on:** `pymupdf`, `pdfplumber`.

### Frontend — `dashboard/src/`
- **`app/page.tsx`** — Owns all filter/chart/tab state and wires the hooks. Four tabs: Time & Group Analytics, Interactive Search & Table, Broad Categories, Credit Cards.
- **`components/Sidebar.tsx`** — Upload (incl. `.pdf`), Recategorize All, add/delete broad categories, and all filters (search, direction, **spend basis**, year pills, month grid, parent-Category multiselect, broad-Category multiselect, sub-Category multiselect, channel-type multiselect, amount range, All/Recurring/One-off toggle). Shows a "Load Sample Statement" button when `meta.years` is empty.
- **`components/CreditCardsPanel.tsx`** — The Credit Cards tab. Four sub-tabs: **Overview** (default), Cards & Statements, Spend by Category, Bank Reconciliation. The card registry loading/empty states gate only the three detail sub-tabs; Overview reads the shared ledger, so the tab strip stays reachable either way.
- **`components/CreditCardAnalytics.tsx`** — The Overview sub-tab: the card equivalent of the bank statement view. Renders the shared `KpiCards`, `TimelineChart` (inflow vs outflow), `CategoryStackChart`, `PieChart`, `SummaryTable` and `DrilldownPanel`, plus card-framed tiles (Card Spend / Refunds / **Bill Payments** / Net / Rows) and a full card transaction table with server-side CSV export **and inline category editing**. Adds a multi-select card picker driven by `meta.cards`. It forces `accountSources: ["CREDIT_CARD"]` **and `spendBasis: "all"`** (see Decision 23) but inherits every other sidebar filter, so the two compose.
- **`components/KpiCards.tsx`** — Credits, debits, net cashflow, filtered/total count. The amount tiles are the **cashflow** figures and follow the view's scope: a bill payment shows as card **inflow** and bank **outflow**. Only the combined view hides it, and a sub-line names the excluded total so the category charts below don't look like they disagree.
- **`components/charts/*`** — `TimelineChart`, `CategoryStackChart`, `PieChart` (groupable by Top / Category / Sub / Channel), `BalanceTrendChart`, `CategoryTrendChart` (all Recharts).
- **`components/tables/SummaryTable.tsx`** — Period summary; clicking a row sets the drill-down period.
- **`components/tables/DrilldownPanel.tsx`** — Drill-down for a clicked period: in-view direction/type/search filters, period KPIs, paginated table, **inline category and sub-category editing**, and CSV export of the narrowed set. Reused for both the Tab-1 period drill-down and the Tab-3 category-month drill-down.
- **`components/tables/TransactionTable.tsx`** — Explorer table with pagination; `exportFilters` prop enables full-set CSV export via the API. Shows the parent/leaf pair and a ↻ marker on recurring rows. Two optional props turn it into an editor: `onCategoryChange` (+ `categories`/`subCategories`) renders the category and sub-category as dropdowns, and `onEditDirection` renders the ↔ debit/credit flip. Omitting either leaves that cell read-only. **The credit-card view relies on `onCategoryChange`** — it has no other way to correct a mis-categorised card row, because its drill-down editor only appears once a period is selected. Card descriptions are often truncated by the issuer, so the parser guesses on them and the user needs a correction path in the view they are already looking at.
- **`components/tables/CategoryEditorTable.tsx`** — Bulk category reassignment editor with sorting, search, and a "only show selected category" toggle.
- **`components/tables/CategoryMonthlyTable.tsx`** — Clickable month-by-month breakdown for one category.
- **`components/modals/CascadeModal.tsx`** — Cascade scope picker (this txn / same merchant / same narration keyword) with a live preview of affected transactions, per-row include/exclude checkboxes, select/deselect-all-visible, and a free-text preview filter.
- **`components/modals/DirectionModal.tsx`** — The same cascade UI for a debit/credit flip: pick the target direction (defaulting to the opposite of the current one), pick the scope, review the rows that will actually change, then apply. Excluded rows are pinned by the server.
- **`hooks/useTransactions.ts`** — SWR hooks: `useMeta`, `useKPIs`, `useTransactions`, `useTimelineSummary`, `useMonthlyCategorySummary`, `useCategoryBreakdown`, `useBalanceTrend`, `useCategoryTrend`. All accept `Filters` (including `yearMonths`). A shared `query(filters, extra)` helper builds the query string, so a new filter is added in one place rather than in a 13-argument call per hook. `useBalanceTrend` forces `spendBasis: "bank_only"` because card rows carry no closing balance.
- **`hooks/useCards.ts`** — `useCards`, `useCardStatements`, `useCardSpend`, `useIssuerCategoryStats`, `useReconcile`.
- **`hooks/useCategories.ts`** — SWR hooks + mutations for category CRUD, rule upsert (carrying `sub_category`), preview, and cascade. Exposes `subCategories`.
- **`lib/api.ts`** — Axios instance (`baseURL: "/api"`, proxied by `next.config.ts`), `buildFilterParams(...)`, and `downloadFilteredCSV(...)` which pulls the filename from `Content-Disposition`.
- **`lib/formatters.ts`** — `formatCurrency` (en-IN), `formatCompactCurrency` (Cr/L/k), `formatDate`, `formatNumber`.
- **`types/index.ts`** — TypeScript mirrors of the API response shapes. `Filters.categories`/`subCategories`/`isRecurring` drive the hierarchy filters; `GroupCol` is the pie-chart grouping axis. `Filters.yearMonths` scopes to exact `YYYY-MM` periods.

---

## Database Schema

```sql
-- transactions (PK: Chq_Ref_Number)
CREATE TABLE transactions (
    Date DATETIME,
    Narration VARCHAR(255),
    Value_Date DATETIME,
    Debit_Amount FLOAT,
    Credit_Amount FLOAT,
    Chq_Ref_Number VARCHAR(250) PRIMARY KEY,
    Closing_Balance FLOAT,
    -- Credit-card provenance (added for the card work; NULL on bank rows,
    -- backfilled to 'BANK' at read time)
    Account_Source VARCHAR(20),   -- 'BANK' | 'CREDIT_CARD'
    Card_ID VARCHAR(64),
    Statement_ID VARCHAR(64)
);

-- narration_details (PK: Chq_Ref_Number, FK → transactions)
CREATE TABLE narration_details (
    Chq_Ref_Number VARCHAR(250) PRIMARY KEY,
    Transaction_Type VARCHAR(50),
    Details TEXT,
    Reference_ID TEXT,
    Payee_Receiver TEXT,
    Date_Range TEXT,
    Remarks TEXT,
    Other_Info TEXT,
    Broad_Category VARCHAR(50),   -- parser-computed; overridden at read time by category_rules
    Sub_Category VARCHAR(80),     -- leaf within Broad_Category (added by Design Decision 13)
    FOREIGN KEY (Chq_Ref_Number) REFERENCES transactions(Chq_Ref_Number)
);

-- broad_categories (user-editable category registry; also holds sub-categories)
CREATE TABLE broad_categories (
    name VARCHAR(50) PRIMARY KEY,
    is_builtin TINYINT DEFAULT 0
);

-- category_rules (user-editable override rules, applied at read time)
-- rule_type: 'txn' (rule_key = Chq_Ref_Number), 'merchant' (Payee_Receiver substring),
--            'narration' (keyword matched against Narration/Details)
-- A rule may set `category`, `sub_category`, or both.
CREATE TABLE category_rules (
    id INT AUTO_INCREMENT PRIMARY KEY,
    rule_type VARCHAR(20) NOT NULL,
    rule_key VARCHAR(255) NOT NULL,
    category VARCHAR(50) NOT NULL,
    sub_category VARCHAR(80) NULL,
    UNIQUE KEY uq_rule (rule_type, rule_key)
);

-- direction_rules (user-editable debit/credit overrides). Deliberately the same
-- shape as category_rules, so the same cascade UI drives both. Applied at read
-- time by _apply_direction_overrides, which moves the amount between
-- Debit_Amount and Credit_Amount - the stored rows are never rewritten, so a
-- re-import cannot undo the user's correction.
CREATE TABLE direction_rules (
    id INT AUTO_INCREMENT PRIMARY KEY,
    rule_type VARCHAR(20) NOT NULL,
    rule_key VARCHAR(255) NOT NULL,
    direction VARCHAR(10) NOT NULL,   -- 'CREDIT' | 'DEBIT'
    UNIQUE KEY uq_dir_rule (rule_type, rule_key)
);

-- credit_cards (one row per physical card; identity is Issuer + Last4)
CREATE TABLE credit_cards (
    Card_ID VARCHAR(64) PRIMARY KEY,
    Issuer VARCHAR(30),
    Card_Name VARCHAR(60),
    Last4 VARCHAR(4),
    Credit_Limit FLOAT,
    First_Seen DATETIME,
    Last_Seen DATETIME
);

-- credit_card_statements (one row per billing cycle)
-- Holds the issuer's own printed figures, which are the independent check on
-- the parsed rows: Parsed_Spend vs Total_Spend must agree, or rows were lost.
CREATE TABLE credit_card_statements (
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
    Total_Spend FLOAT,          -- issuer's PURCHASES/DEBIT (purchases only)
    Finance_Charges FLOAT,
    Total_Due FLOAT,
    Minimum_Due FLOAT,
    Credit_Limit FLOAT,
    Available_Credit_Limit FLOAT,
    Txn_Count INT,
    Parsed_Spend FLOAT,         -- sum of parsed DEBIT rows
    Parsed_Refunds FLOAT,
    Spend_Mix TEXT,             -- JSON of the issuer's own category split
    Source_File VARCHAR(255),
    Imported_At DATETIME,
    FOREIGN KEY (Card_ID) REFERENCES credit_cards(Card_ID)
);

-- credit_card_transactions (one row per transaction)
-- Statement_Category is the ISSUER's classification where it supplies one
-- (ICICI embeds it in the description); it outranks keyword guessing.
CREATE TABLE credit_card_transactions (
    CC_Txn_ID VARCHAR(64) PRIMARY KEY,
    Statement_ID VARCHAR(64),
    Card_ID VARCHAR(64),
    Txn_Date DATETIME,
    Txn_Time VARCHAR(10),
    Description TEXT,
    Amount FLOAT,
    Direction VARCHAR(10),      -- 'DEBIT' (a purchase) | 'CREDIT' (a refund)
    Rewards VARCHAR(20),
    Card_Ref VARCHAR(60),
    Statement_Category VARCHAR(50),
    Statement_Category_Raw VARCHAR(40),
    Is_Settlement TINYINT DEFAULT 0,   -- repays the card; not spend
    Page INT,
    Ledger_Chq_Ref VARCHAR(250),       -- namespaced CC:<Card_ID>:<CC_Txn_ID>
    FOREIGN KEY (Statement_ID) REFERENCES credit_card_statements(Statement_ID)
);
```

> `Category` (the top-level rollup), `is_recurring` and `Is_Settlement` are **not** stored. All
> three are derived at read time inside `get_all_transactions_with_details` and live in the
> cached frame, so they stay correct as new statements are imported without a migration.

---

## Key Design Decisions

1. **Idempotent Imports:** Duplicate reference numbers are handled via `INSERT IGNORE` and deterministic UUID5 generation for dummy `Chq_Ref_Number` values. Re-importing the same file will not create duplicates.
2. **Dynamic Header Detection:** The loader scans the first 50 rows to find the header, handling varying HDFC statement formats.
3. **Narration Parsing:** Pattern-matched by prefix/keyword, not ML. Unknown narrations fall to `OTHER`/`UNKNOWN`.
4. **Two-Table Schema:** Raw transaction data is separated from parsed narration metadata, joined via the `Chq_Ref_Number` foreign key.
5. **Environment-Based Config:** All DB credentials read from environment variables with sensible local defaults.
6. **Broad Categories — Two Layers:** The parser computes a `Broad_Category` stored in `narration_details`. At read time, user-editable `category_rules` overrides are layered on top with priority: `txn` rule > `narration` (keyword substring) > `merchant` (payee substring) > parser value. Narration keywords outrank merchant rules because an explicit keyword is a more deliberate match; this lets a keyword like `FD THROUGH MOBILE` (Investment) win over a broad own-account merchant rule.
7. **Overrides Persist, Recategorize Doesn't Clobber Them:** `recategorize_all_narrations` rewrites only the parser-computed column; configured `category_rules` are untouched and re-applied at read time.
8. **Self-Healing Seeds:** `init_db_tables(seed=True)` uses `INSERT IGNORE` for payee rules, so new seed keys added to `PAYEE_CATEGORY_MAP` are picked up on the next init without ever overwriting user rules.
9. **Filtering Lives Server-Side:** Every table and chart goes through `db.get_all_transactions_with_details` + the router's `_get_filtered_df`, then aggregates in Pandas. There is no SQL-level filtering layer, so filter changes re-query the full table.
10. **Exports Are Server-Side:** CSV export calls `GET /api/transactions/export` so the file contains the *entire* filtered set, not just the rows on the current page.
11. **Reads Are Cached; Writes Must Invalidate:** The joined dataset, the override-applied result, and the parsed rules are cached in-process (`db._base_df_cache` / `_final_df_cache` / `_rules_cache`). A dashboard page load fires ~10 endpoints concurrently, and without the cache each one re-ran the same ~100ms of work — roughly 1s per page load versus ~0.1s now. **Any function that writes to the database must call `db.invalidate_transaction_cache()`, `db.invalidate_rules_cache()`, or `db.invalidate_caches()`.** `store_data_in_db` and `recategorize_all_narrations` invalidate the data cache; `apply_category_rules` and `delete_category_rules` invalidate only the rules cache (the stored data is untouched). Forgetting this serves stale categories until restart. Rows written by anything *outside* the API (a manual SQL insert) will not be seen — restart the server or call the invalidator.
12. **Pagination Is Clamped Server-Side:** `GET /api/transactions` clamps `page` into `[1, total_pages]` and returns the effective `page` plus `total_pages`. Clients use the shared `useClampPage` hook to clamp the same way, so a filter change that shrinks the result set cannot strand the user on a blank page with no pagination controls.
13. **Three-Level Category Hierarchy:** `Category` (parent rollup, ~11) → `Broad_Category` (existing 29) → `Sub_Category` (leaf, ~48). A hierarchy was chosen over a tag system because every level is single-valued: tags would make the parent total a set union, so grouped totals would stop summing to 100% and break every chart. `Sub_Category` always exists — it falls back to `Broad_Category` when no keyword rule matches, so the rollup chain covers 100% of rows. **Sub-categories only split *within* a broad category; they never move a transaction between categories.** `CATEGORY_PARENT` maps a broad category to its parent and falls back to `Other` for unknown values, so a custom category can never silently vanish from a rollup.
14. **Sub_Category Is Derived From the *Resolved* Broad Category:** `_apply_category_rule_overrides` resolves `Broad_Category` first, then derives the leaf from that result, then lets an explicit `category_rules.sub_category` win. Deriving it in the other order is a bug: a rule moving a transaction from `Shopping_Retail` to `Rent` would leave the leaf at `Retail_General` under `Housing`.
15. **Recurrence Is Derived, Not Stored:** `is_recurring` is computed at read time by `_mark_recurring` (a counterparty qualifies with ≥3 transactions and a median gap ≤45 days). It is a flag rather than a tag namespace because it cuts across every category — rent, ATM and loan EMI are all recurring. Storing it would require a migration each time the threshold or data changes.
16. **Card Spend Is Projected Into the Shared Ledger, Not a Parallel Aggregate:** `ingest_cards.py` writes card rows into `transactions`/`narration_details` with namespaced keys (`CC:<Card_ID>:<CC_Txn_ID>`) and `Account_Source='CREDIT_CARD'`. Every existing chart, filter and CSV export then covers card spend with no API or frontend change. The card tables remain the source of truth for card-specific detail (rewards, issuer category, cycle totals) that the bank schema has no column for.
17. **Settlements Are Excluded From *Spend*, Not From *Cashflow*:** `Is_Settlement` is derived at read time by `_mark_settlement` and flags **both** halves of a card settlement — the bank-side debit already categorised `Credit_Card_Payment`, and the card-side row (`BPPY CC PAYMENT …`, `BBPS Payment received`). Without this, every card purchase is counted twice: once at the merchant and once when the bill is paid. Cashflow still includes them, because the money genuinely left the bank account. This is the same derived-not-stored pattern as `is_recurring`. **The flag is derived from the *resolved* `Broad_Category`, so it is computed in `_get_cached_final_df` — after `_apply_category_rule_overrides`, not in the base query.** Deriving it earlier used the *stored* category, so any row reclassified to `Credit_Card_Payment` by a `narration`/`merchant` rule escaped the flag and was counted as spend in every chart. See Decision 24.

    **The two views are separate numbers, not one number.** `/kpis` reports the spend totals alongside the settlement halves so the excluded money is visible rather than silently dropped. The correction is applied on the three **spend** endpoints — `monthly-category`, `category-breakdown`, `category-trend` — and on `/kpis` and `/summary/timeline`. It was not always so: for a while `/kpis` and the timeline included settlements while the spend endpoints excluded them, which made the KPI and the pie disagree by the full settlement total (₹38.1L on the development data) and left no `Credit_Card_Payment` series in the cashflow view. **Consequence for the UI: any total shown beside a category table or chart, and both amount tiles, use the settlement-excluded figures.** Mixing them up makes a header disagree with the rows beneath it.

    **The correction applies to CROSS-CATEGORY totals, not to single-category drill-downs.** The double count only occurs when a purchase and the bill that paid for it are summed in the same view — which needs two categories. Once the view is scoped to one category the other half is not in view, so excluding settlements only destroys data: `Credit_Card_Payment` is 100% settlement, so `category-trend` and `monthly-category` returned **zero rows** for it while the transaction table listed all 124. Both endpoints therefore pass `exclude_settlements=not <narrowed to one category>`. An empty `category` still means "chart everything", which *is* a multi-category total, and keeps the correction. `category-breakdown` is unaffected — it is always a cross-category breakdown.
18. **Issuer Categories Beat Keyword Matching:** where an issuer classifies the spend itself (ICICI embeds the merchant category in the description, e.g. `AMAZON PAY IN GROCERY BANGALORE IN`), that value is written to `Broad_Category` at ingest and the `Sub_Category` leaf is re-derived from it. The card network's own classification is more reliable than inferring a category from a merchant string that the PDF may truncate mid-word. Keyword rules still fill the gaps where the issuer is silent (HDFC).
19. **Card Column Bands Are Derived Per Page, Never Hardcoded:** the two HDFC cards indent the same table by ~144pt relative to each other, so a fixed band parses one card and silently drops the other. `_hdfc_bands` reads each page's own column header instead. This is a direct consequence of Design Decision 2 applied to cards: a parser must find the header, not assume a layout.
20. **Reconciliation Reports Both Directions, Never Force-Fits:** the bank ledger and the card statements do not necessarily cover the same period, so a cycle whose payment falls outside the imported bank range is *correctly* unmatched. `match_statements_to_debits` consumes each bank debit once, applies a ₹1 tolerance, and returns unmatched statements *and* unmatched bank debits with a reason. A partial payment surfaces as a variance instead of being paired with the wrong cycle — forcing it would hide exactly the discrepancy the check exists to find. The matcher is a pure function so its rules can be tested without a database.
21. **The Card View Reuses the Bank View, Including Its Components:** `CreditCardAnalytics` renders the same `KpiCards` / `TimelineChart` / `CategoryStackChart` / `PieChart` / `SummaryTable` / `DrilldownPanel` as the bank tabs, scoped by `accountSources=["CREDIT_CARD"]` plus the new `card_ids` filter. This is the payoff of Decision 16: because card rows are already in the shared ledger, the card view is a *filter over* the bank view rather than a second implementation. The two therefore cannot disagree — a purchase shows the same category and the same rupee amount in both — and any future change to the shared charts improves both at once. `card_ids` was the one genuinely missing piece; it is a no-op on bank rows, so the same filter path serves both ledgers.
22. **Card Refunds Are Shown as Inflow, Not Netted Away:** the shared KPI and timeline components label the credit side generically ("Credits"), which is right for a bank but misleading for a card, where a credit is a refund or reversal rather than income. The card view therefore renders the shared totals *and* card-framed tiles (Card Spend / Refunds & Reversals / Net Card Spend / Rows) rather than swapping the shared component out for a bespoke one — keeping the numbers identical while labelling them honestly.
23. **The Card View Forces `spendBasis="all"`; Only It Does:** the sidebar's spend-basis toggle is a *combined-view* control — "show me my bank spending", "show me my card spending", "show me everything". `account_sources=CREDIT_CARD` and `spend_basis=bank_only` select **disjoint** sets, so inheriting the sidebar basis meant that choosing "bank only" silently blanked the entire card panel. The card view is a dedicated surface for one ledger, so it pins the basis to `all` and lets `accountSources` do the narrowing; every other sidebar filter is still inherited. Settlement exclusion is untouched, because the aggregates pass `exclude_settlements=True` independently of `spend_basis`. `verify_card_view.py` asserts both halves of this.

24. **Every Column Derived From a Category Must Be Derived From the *Resolved* Category:** `Category`, `Sub_Category` and `Is_Settlement` all read `Broad_Category`, so all three must be computed *after* `_apply_category_rule_overrides`. `_mark_settlement` was the outlier — it ran inside `_query_transactions_with_details` (the cached base frame), which is built before the overrides run. Its bank-side test `Broad_Category LIKE 'CREDIT_CARD_PAYMENT'` therefore saw only the *parser's* opinion, so a row a user had reclassified to `Credit_Card_Payment` via a `narration` or `merchant` rule was never flagged, and its amount was counted as spend in the pie, the stacked chart and the KPI — precisely the double count the flag exists to prevent. The symptom was narrow and misleading: only that one category was wrong, and only by the rows a rule had touched. The matching SQL in `card_store._load_reconciliation_frames` had the same blind spot (it re-queried `narration_details` for the stored value), so reconciliation reported fewer bank-side payments than the charts counted as spend; it now reads the shared resolved ledger and reuses the derived `Is_Settlement`. `_mark_recurring` stays in the base query because it depends only on `Payee_Receiver`/`Date`, which no rule can change. The lesson generalises: **if a derived column is a function of an overridable column, it belongs after the override step, not before it.**

25. **A Statement Is Identified by Its Billing Cycle, Not Its Filename:** `make_statement_id` hashes `(Card_ID, Statement_Date, Period_End)`; the source filename is **not** part of the token. It used to be, on the reasoning that "one file is one statement." But the same statement is routinely imported twice under two names — a masked copy (`..._masked.pdf`) beside the original — and the filename then produced two different primary keys. `INSERT IGNORE` kept both, so the cycle appeared **twice** in the statement table and every one of its transactions was written to the shared ledger a second time, **double counting that card's spend**. Two cycles were affected on the development data (₹42,141 and 107 phantom rows). The filename survives only as the fallback when `Statement_Date` and `Period_End` are both unreadable — some layouts put them out of the parser's reach, and collapsing every such file onto one key would silently discard all but the first. That is the safer trade because it needs a *failed parse* to trigger, and a correctly parsed cycle can never reach it.

26. **`Parsed_Spend` Is Purchases Only, Because That Is What the Issuer Prints:** the variance check is `Parsed_Spend − Total_Spend`, and the issuer's `PURCHASES/DEBIT` counts purchases, not the bill-payment row. Summing every `DEBIT` swept the settlement in, so a statement parsed *perfectly* still reported a large variance — one cycle read ₹195,951 against an issuer total of ₹12,233 when the purchases alone summed to exactly ₹12,233. The exclusion now happens once, where `parsed_spend` is computed, so `Spend_Variance` and `Purchase_Spend` must **not** subtract `settlement_spend` a second time. Before the fix that double subtraction hid the problem in the CLI while the stored column stayed wrong. With both corrections, 104 of 117 statements reconcile to within ₹1.

    **A settlement is a TRANSFER, and the correction is keyed on VIEW SCOPE, not on the endpoint.** A card bill payment is two halves of one transfer: the bank-side debit and the card-side credit. They can only be double counted when **both** are in the same view, so `_settlement_handling(spend_basis, account_sources)` decides it: **combined** view → exclude both halves (the only place the double count is real); **bank only** → the bank half *is* the outflow, it really left the account; **card only** → the card half *is* the inflow, it really reduced the balance owed. `/kpis` and `/summary/timeline` pass that decision; the three **spend** endpoints always exclude, because a cross-CATEGORY total is where the double count bites.

    An earlier version excluded settlements from *every* view, on the reasoning that a transfer is "neither income nor spend". That was wrong twice over: it removed ₹7.78L of genuine card **inflow** (the card view read as −₹9.5L net outflow when the user had in fact paid the bill down) and ₹28.51L of genuine bank **outflow** (the bank view under-reported what the account actually spent). A correction that only ever deletes data is a bug, not a correction. `/kpis` therefore reports both halves (`settlement_debits`, `settlement_credits`) plus the row split (`spend_count` / `settlement_count`), so nothing is dropped silently. It fetches the frame with `include_settlements=True` and applies the correction itself, because a filter that deleted the rows first would make the exclusion impossible to report.

27. **A Card Settlement Is a CREDIT on the Card, and the User Can Override Either:** from the *card's* point of view a bill payment is money coming **in** — it reduces the balance owed. The issuer prints it in the debit column, so `Direction` arrived as `DEBIT` and the projection filed it as an expense: a transfer was being reported as a purchase. `_prepare_rows` therefore forces `Direction = "CREDIT"` for any settlement, whatever column the issuer laid it out in. The bank-side half is deliberately left a `DEBIT`, because that money really did leave the account. The two rows are mirror images of one payment, which is exactly why neither belongs in a spend or income total (Decision 17).

    **Direction is a derived column, overridable like a category.** `direction_rules` has the identical shape to `category_rules` — `txn` (exact reference) / `merchant` (payee substring) / `narration` (keyword) — with the same priority order, the same `apply-cascade` endpoint semantics and the same exclude-and-pin behaviour, so the category UI drives both. `_apply_direction_overrides` runs in `_get_cached_final_df` and applies an override by **moving the amount between `Debit_Amount` and `Credit_Amount`**, so every downstream sum (KPI, charts, CSV export) follows without knowing about the rules. It also normalises each row to exactly one side first, which makes `Direction` trustworthy and gives the UI a single source of truth. Rules are applied at read time, so re-importing a statement cannot undo the user's correction. `/transactions/direction-rules/preview` returns only rows that would actually *change*, because a rule that already agrees with the current value is a no-op and listing it would suggest otherwise.

---

## Category Hierarchy

`Transaction_Type` (channel, e.g. `UPI`, `NEFT`, `ATM_WITHDRAWAL`) → **`Category`** (parent rollup) → **`Broad_Category`** → **`Sub_Category`** (leaf).

- **Parent rollups (11):** `Housing`, `Food`, `Transport`, `Shopping`, `Health`, `Financial`, `Utilities`, `Lifestyle`, `Transfers`, `Cash`, `Income`, `Other` (fallback for unknown values).
- **21 built-in broad categories** (`category_rules.BUILTIN_CATEGORIES`) plus any user-added ones.
- **~48 built-in leaves** (`category_rules.BUILTIN_SUB_CATEGORIES`), driven by `SUBCATEGORY_KEYWORD_RULES` (ordered, first match wins) with `SUBCATEGORY_DEFAULTS` for the remaining rows of a broad category. Worked example — `Rent` splits into `Residential_Rent`, `CoLiving_Rent`, `Rent_Brokerage`, `Rent_Deposit`, `Rent_Maintenance` while all of them still total under `Housing`.
- **Assignment path:** parser rule engine → stored in `narration_details.Broad_Category`/`Sub_Category` → read-time override by matching `category_rules` → final value shown in the UI.
- **Category merges/renames** are self-healing via `db.CATEGORY_RENAMES` (`_migrate_renamed_categories` runs on every `init_db_tables`). Applied: `Business_Income → Non_Salary_Income`, `Mobile_Recharge → Utilities_Bills`, `Broadband_Internet → Utilities_Bills`.
- **Direction-aware investments:** the Investment rule is credit-sensitive — debits to investment platforms (GROWW, ZERODHA, MOTILAL, FD/RD, MFSS, NSE…) become `Investment`, while credits from them (sell proceeds, FD/RD maturity) become `Investment_Liquidation`.
- **User editing:** change the category *and* the sub-category in the editor or drill-down table; then scope the change to those exact transactions (`txn`), the same merchant (`merchant`), or a narration keyword (`narration`). Excluded rows are pinned with synthetic `txn` rules carrying **both** their broad category and their leaf, so an exclusion cannot drift to a different leaf. All persisted to `category_rules` and applied instantly.
- **New categories:** added in the sidebar; they appear in every dropdown/filter immediately and roll up under `Other` until mapped in `CATEGORY_PARENT`.

---

## Known Transaction Types (from narration_parser)

| Transaction_Type    | Trigger Pattern                              |
|--------------------|----------------------------------------------|
| `UPI`              | Starts with `UPI-` or `UPI/`                 |
| `UPI_RETURN`       | Starts with `UPIRET-` or `REV-UPI-`          |
| `ATM_WITHDRAWAL`   | Contains `ATM FEES`, `NWD`, starts `ATW-`/`EAW-` |
| `INTL_POS/MARKUP`  | Contains `MARKUP` or `POS`                   |
| `RD`               | Contains `RD INSTALLMENT`, `RD THROUGH MOBILE`, `MATURED RD` |
| `FD`               | Contains `FD THROUGH`, `IB FD`, `FD PREMAT`  |
| `FUND_TRANSFER`    | Starts `FT-`, or contains `IMPS`/`NEFT`/`RTGS` |
| `BILLPAY`          | Contains `IB BILLPAY` or `BILLPAY`           |
| `FOREX_REMITTANCE` | Starts with `RFX `                           |
| `TAX_GST`          | Contains `IGST` or `GST`                     |
| `TPT_TRANSFER`     | Contains `-TPT-` or starts with `TPT-`       |
| `INTEREST`         | Contains `INTEREST PAID` / `CREDIT INTEREST CAPITALISED` |
| `DIVIDEND`         | Contains `DIV`                               |
| `ACH`              | Starts with `ACH`                            |
| `EMI`              | Contains `EMI` + `CHQ`                       |
| `BANK_CHARGES`     | Contains `INSTA ALERT CHARG` or `ALERT CHG`  |
| `STANDING_INSTRUCTION` | Contains `NET BANKING SI`               |
| `MUTUAL_FUND`      | Contains `MFSS`, `BSE-`, or `FF-`            |
| `OTHER`            | Fallback for unmatched narrations            |
| `UNKNOWN`          | Empty/null narrations                        |

---

## Masked Statement Files

The `masked/` directory contains PII-masked `.xls` versions of real HDFC statements for development/testing:
- `Acct Statement_6900_08042026_18.53.11.xls` — Recent statement (Apr 2026)
- `Acct_Statement_XXXXXXXX6900_JAN-1st-to-DEC-31st-YYYY.xls` — Yearly consolidated (2021–2025)
- `Acct_Statement_XXXXXXXX6900_YEAR-YYYY.xls` — Year-specific (2023–2025)
- `Acct_Statement_XXXXXXXX6900_YEAR-2026_till_AUG.xls` — Partial year 2026

---

## Development Notes

- **No test suite exists.** There is no `tests/` directory. Verify changes with `py_compile`, `npx tsc --noEmit`, and `npm run build`; for behavior changes, exercise endpoints with `fastapi.testclient.TestClient` against the local MySQL instance.
- **No `requirements.txt` or `pyproject.toml`** — dependencies must be inferred: `fastapi`, `uvicorn`, `python-multipart` (file uploads), `pandas`, `sqlalchemy`, `pymysql`, `pdfplumber`, `xlrd`, `openpyxl`, `xlwt`, `xlutils`.
- **No git repository** and no `.gitignore` at the project root. (`dashboard/.gitignore` exists and covers `node_modules`/`.next`.)
- **All amounts are in Indian Rupees (₹/INR).**
- **`SSLKEYLOGFILE` is cleared at startup** in both `api/main.py` and `start.py` to avoid Windows SSL issues.
- **Legacy artifacts:** `walkthrough.md`, `implementation_plan.md`, and `implementation_plan-fix-Reassign Transaction Categories .md` are historical records of the Streamlit → Next.js migration. They are kept for reference only and describe the removed Streamlit UI.
