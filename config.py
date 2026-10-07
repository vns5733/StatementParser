import os

# Database Connection Settings
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "root")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("DB_NAME", "statements")

# Database Table Names
TABLE_TRANSACTIONS = "transactions"
TABLE_NARRATION_DETAILS = "narration_details"
TABLE_CREDIT_CARDS = "credit_cards"
TABLE_CREDIT_CARD_STATEMENTS = "credit_card_statements"
TABLE_CREDIT_CARD_TRANSACTIONS = "credit_card_transactions"
# User-editable debit/credit overrides. Same shape as category_rules: a rule
# either pins one exact transaction ('txn'), or matches every transaction whose
# payee ('merchant') or narration ('narration') contains the key. Applied at read
# time so the stored rows are never rewritten.
TABLE_DIRECTION_RULES = "direction_rules"

# Free-text notes the user attaches to a transaction, plus the last LLM
# suggestion made for it. Keyed on Chq_Ref_Number, so a re-import (INSERT IGNORE)
# and a recategorize both leave it intact - recategorize only rewrites
# narration_details. 'Source' records who wrote the note ('user' or 'llm'), which
# matters because an LLM-written note is a guess the user has not confirmed.
TABLE_TRANSACTION_NOTES = "transaction_notes"

# Target Standard Columns for Transactions
REQUIRED_COLUMNS = [
    "Date",
    "Narration",
    "Value_Date",
    "Debit_Amount",
    "Credit_Amount",
    "Chq_Ref_Number",
    "Closing_Balance",
]

# Target columns for a parsed credit-card transaction.
# `Statement_Category` is the issuer's own classification when it supplies one
# (ICICI puts the MCC-style category inside the description); it is preferred
# over keyword guessing when categorising. `Card_Ref` is the issuer's own
# transaction reference and is unique within a card.
CREDIT_CARD_COLUMNS = [
    "Txn_Date",
    "Txn_Time",
    "Description",
    "Amount",
    "Direction",
    "Rewards",
    "Card_Ref",
    "Statement_Category",
    "Statement_Category_Raw",
    "Page",
]


# Default File Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_STATEMENT_PATH = os.path.join(
    BASE_DIR, "Acct Statement_6900_08042026_18.53.11.xls"
)

# ---------------------------------------------------------------------------
# LLM (opencode server)
#
# Suggestions are served by the same opencode instance the user already runs,
# started with `opencode serve`. Nothing is sent anywhere else and no third-party
# SDK is involved — narrations contain real names and account details, so the
# transport is loopback and the whole integration is stdlib urllib.
#
# The model is left unset by default, which makes opencode use whatever model the
# user's own config selects. Setting these pins it explicitly, which is what you
# want if you want a cheap fast model for bulk triage rather than the one you
# chat with.
# ---------------------------------------------------------------------------
OPENCODE_SERVER_URL = os.getenv("OPENCODE_SERVER_URL", "http://127.0.0.1:4096")
# Only needed when the server was started with OPENCODE_SERVER_PASSWORD set.
OPENCODE_SERVER_USERNAME = os.getenv("OPENCODE_SERVER_USERNAME", "opencode")
OPENCODE_SERVER_PASSWORD = os.getenv("OPENCODE_SERVER_PASSWORD", "")
OPENCODE_MODEL_PROVIDER = os.getenv("OPENCODE_MODEL_PROVIDER", "")
OPENCODE_MODEL_ID = os.getenv("OPENCODE_MODEL_ID", "")
# Generous, because a cold model download on the first call is slow. A request
# that outlives this is reported as a timeout rather than hanging the UI.
OPENCODE_TIMEOUT_SECONDS = int(os.getenv("OPENCODE_TIMEOUT_SECONDS", "120"))
# Upper bound on rows sent in one suggestion request. Classification is cheap per
# row but the prompt grows with every row, and past a few hundred the model
# starts dropping entries - which would look like rows the tool simply ignored.
LLM_SUGGEST_MAX_ROWS = int(os.getenv("LLM_SUGGEST_MAX_ROWS", "100"))
