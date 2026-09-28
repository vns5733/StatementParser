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
