"""
category_rules.py — Broad Category classification for StatementParser.

Assigns a purpose-level Broad_Category (Salary, Rent, Investment, ...) on top of
the channel-level Transaction_Type (UPI, NEFT, ATM, ...).

Two stage approach:
  Stage 1 - Hard rules: ordered keyword/direction matchers over narration fields.
  Stage 2 - PA YEE_CATEGORY_MAP override: exact payee name -> category.

The PAYEE_CATEGORY_MAP below is the *seed* for the DB-backed rules table
(broad category_rules). Editing it only affects the seed; runtime overrides made
from the dashboard UI live in the database table `category_rules`.
"""

import re

# ---------------------------------------------------------------------------
# Built-in catalog of broad categories (display order matters in the UI)
# ---------------------------------------------------------------------------
BUILTIN_CATEGORIES = [
    "Salary",
    "Non_Salary_Income",
    "Investment",
    "Dividend_Income",
    "Interest_Income",
    "Interest_Paid",
    "Rent",
    "Credit_Card_Payment",
    "Food_Dining",
    "Groceries",
    "Shopping_Retail",
    "Healthcare",
    "Travel",
    "Utilities_Bills",
    "Tax_Govt",
    "Fees_Charges",
    "ATM_Cash",
    "Switch_Own_Accounts",
    "P2P_Transfer",
    "Uncategorized",
]

# ---------------------------------------------------------------------------
# Payee-level overrides (seed for the DB rules table)
# Keys are matched against Payee_Receiver case-insensitively (exact match).
# ---------------------------------------------------------------------------
PAYEE_CATEGORY_MAP = {
    "SWATI SANTOSH DHAWALE": "Rent",
    "SWATI SANTOSH DHAWAL": "Rent",
    "MS SWATI VIVEK DEOKU": "Rent",
    "SWATIBEN ANILBHAI PA": "Rent",
    "GEETHA S": "Rent",
    "VISHNU NARAYANAN S": "Switch_Own_Accounts",
    "VISHNU  NARAYAN": "Switch_Own_Accounts",
    "VISHNU NARAYAN": "Switch_Own_Accounts",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _u(value):
    """Upper-case normalized string for matching."""
    return str(value or "").strip().upper()


def _has(substr, *fields):
    """True if any field contains the substring."""
    for f in fields:
        if substr in f:
            return True
    return False


def _any_has(substrs, *fields):
    return any(s in f for s in substrs for f in fields)


# ---------------------------------------------------------------------------
# Stage 1 - hard rules. Ordered list of (name, matcher) - first match wins.
# ---------------------------------------------------------------------------
def assign_broad_category(narration, transaction_type, details, payee_receiver,
                          reference_id, has_debit=False, has_credit=False):
    """
    Returns the broad category for one transaction.

    Priority: PAYEE_CATEGORY_MAP > keyword hard rules > channel fallback.
    (Note: DB override rules are applied separately at read time and take
     precedence over everything this function computes.)
    """
    n = _u(narration)
    d = _u(details)
    r = _u(reference_id)
    p = _u(payee_receiver)
    tt = _u(transaction_type)

    # Rent is commonly encoded in the narration remark ('RENT JAN 2026').
    if _has("RENT", n, d, r):
        return "Rent"

    # Credit card bill payments.
    # Debits only: a credit from a card brand (e.g. 'ACH C- SBICARD INT ...')
    # is interest/cashback/refund, not a payment.
    if has_debit and (_has("SBICARD", n, d) or _any_has(
        ("CRED CLUB", "CRED.CLUB", "AMAZONPAYCC", "AMAZON PAY CREDIT",
         "INDMONEY CREDIT CARD", "HDFCYA", "HDFCSI", "HDFC5X", "HDFC1S",
         "CREDIT CARD"),
        n, d)):
        return "Credit_Card_Payment"

    # Salary / payroll credits.
    if has_credit:
        if _any_has(("SALARYINR", "ALLEGIS", "PAYROLL", "SALARY"), n, d, r):
            return "Salary"
        if _has("ITDTAX REFUND", n, d) or _has("TAX REFUND", n, d):
            return "Tax_Govt"

    # GST / government tax payments.
    if _any_has(("IGST", "GST", "INCOME TAX", "ITDTAX", "ETREASURY", "GOVT OF"),
                n, d, r) or _any_has(("_GST", "-GST"), n):
        return "Tax_Govt"

    if has_credit:
        # Dividends (e.g. 'HDFC BANK SPL INT DIV', 'ASIANPAINTSFINDIV').
        if _has("DIVIDEND", n, d, r) or re.search(r"\bDIV\b", n) \
                or _any_has(("ASIANPAINTSFINDIV", "OIL AND NATURAL GAS"), n, d, p):
            return "Dividend_Income"
        # Interest income (capitalised savings interest etc.).
        if "INTEREST" in n or "INTEREST" in d:
            return "Interest_Income"

        # Marketplace / platform payouts (PhonePe, Flipkart, PayPal, ...).
        if _any_has(("PHONEPE PRIVATE LIMITED", "FLIPKART INTERNET PRIVATE",
                     "PAYPAL PAYMENTS", "NEXTBILLION TECHNOLOGY PRIVATE",
                     "AXIS MUTUAL FUND REDEMPTION"),
                    n, d, p, r):
            return "Non_Salary_Income"

    # Investments (broking, mutual funds, RD/FD, chit funds).
    # Checked BEFORE self-transfers so own-account RD/FD placements like
    # "FD THROUGH MOBILE-...:VISHNU NARAYANAN S" classify as investments.
    # Credits from these platforms (sell proceeds, FD/RD maturity) are the same
    # activity as the debit side, so both land in Investment - direction is
    # visible from the Credit/Debit columns, and splitting the category by
    # direction made "how much did I invest?" unanswerable.
    if _any_has(("GROWW", "ZERODHA", "MOTILAL", "KSFE", "KSFEL", "RD INSTALLMENT",
                 "RD THROUGH", "FD THROUGH", "FD PREMAT", "MATURED RD",
                 "MFSS", "BSE-", "NSE CLEARING", "INDMONEY", "MUTUAL FUND",
                 "SHAREMARKET", "CHITTY", "CHIT FUND", "RD. TRANSFER"),
                n, d, p, r):
        return "Investment"

    # Own / family account switches (self transfers).
    if _has("VISHNU NARAYAN", n, d, p) or _has("VNS5733", n, d, r):
        return "Switch_Own_Accounts"

    # Health.
    if _any_has(("PHARMACY", "CHEMIST", "HOSPITAL", "CLINIC", "AYURVEDA",
                 "MEDICAL", "DENTAL", "DOCTOR", "LABS"), n, d, p):
        return "Healthcare"

    # Food & dining.
    if _any_has(("SWIGGY", "ZOMATO", "EATCLUB", "SWEETS", "CAFE", "BAKERY",
                 "LADDOS", "PIZZA", "TEA STALL", "LASSI", "HOTEL", "RESTAURANT",
                 "FOODS", "TANDOOR", "BIRYANI"), n, d, p):
        return "Food_Dining"

    # Groceries / supermarkets.
    if _any_has(("SUPER MARKET", "SUPER STORE", "LAVANYA", "ZEPTO", "BLINKIT",
                 "BIGBASKET", "SPICES", "VEGETABLE", "FRUITS", "GROCERY"),
                n, d, p):
        return "Groceries"

    # Retail / shopping.
    if _any_has(("AMAZON", "FLIPKART", "MEESHO", "HYLO", "MYNTRA", "AJIO",
                 "ICONIC AUTOMOTIVE"), n, d, p):
        return "Shopping_Retail"

    # Travel.
    if _any_has(("IRCTC", "GOIBIBO", "MAKEMYTRIP", "RAILWAY", "INDIGO",
                 "AIR INDIA", "OYO", "MMT"), n, d, p):
        return "Travel"

    # Utilities (broadband / internet, mobile recharge / telecom,
    # electricity / water / LPG / bill desk) — merged into Utilities_Bills.
    if _any_has(("ASIANET", "BROADBAND", "INTERNET", "FIBER",
                 "RECHARGE", "VODAFONE", "AIRTEL", "JIO", "BSNL", "PREPAID",
                 "POSTPAID", "VI PREPAID", "VI RECHARGE",
                 "AIRTELPREDIRECT", "VIPREIDEA",
                 "BBPS", "ELECTRICITY", "WATER AUTHORITY", "SIBWLPG", "LPG",
                 "BILLDESK", "SEWERAGE", "GAS BILL", "KWAU", "ETREASURYKERALA"),
                n, d, p, r):
        return "Utilities_Bills"

    # Bank / service charges.
    if _any_has(("INSTA ALERT", "ALERT CHG", "ATM FEES", "SERVICE CHARGE",
                 "FEES", "COMMISSION"), n, d):
        return "Fees_Charges"

    # Channel-level fallbacks.
    if tt == "ATM_WITHDRAWAL":
        return "ATM_Cash"
    if tt in ("INTEREST",) and has_credit:
        return "Interest_Income"
    if tt == "INTEREST" and has_debit:
        return "Interest_Paid"
    if tt == "FOREX_REMITTANCE":
        return "P2P_Transfer"
    if tt in ("UNKNOWN",):
        return "Uncategorized"

    # EMIs on loans that are not credit-card related.
    if tt == "EMI":
        return "Investment"

    # Everything that reached here is an unidentified person-to-person or
    # generic flow -> let Payee map / user overrides / generic bucket handle it.
    if p:
        return "P2P_Transfer"
    return "Uncategorized"


# ---------------------------------------------------------------------------
# Two-tier hierarchy
#
#   Category (parent)  ->  Broad_Category (existing)  ->  Sub_Category (child)
#
# Broad_Category is left exactly as it was, so every existing rule, filter and
# stored value keeps working. Category gives charts something that rolls up, and
# Sub_Category splits the broad buckets that hide several unrelated things.
# A Sub_Category with no rule simply equals its Broad_Category, so the rollup
# chain is always complete and totals always sum.
# ---------------------------------------------------------------------------

# Broad_Category -> parent Category. Anything unlisted falls back to
# OTHER_CATEGORY so an unknown value can never silently disappear from a rollup.
HOUSING = "Housing"
FOOD = "Food"
TRANSPORT = "Transport"
SHOPPING = "Shopping"
HEALTH = "Health"
FINANCIAL = "Financial"
UTILITIES = "Utilities"
LIFESTYLE = "Lifestyle"
TRANSFERS = "Transfers"
CASH = "Cash"
INCOME = "Income"
OTHER_CATEGORY = "Other"

CATEGORY_PARENT = {
    # Housing
    "Rent": HOUSING,
    "Home_Improvement": HOUSING,
    "Brokerage": HOUSING,
    # Food
    "Food_Dining": FOOD,
    "Groceries": FOOD,
    # Transport
    "Travel": TRANSPORT,
    "Vehicle": TRANSPORT,
    "Fuel": TRANSPORT,
    # Shopping
    "Shopping_Retail": SHOPPING,
    "Shopping_Online": SHOPPING,
    # Health
    "Healthcare": HEALTH,
    "Insurance": HEALTH,
    # Money in
    "Salary": INCOME,
    "Non_Salary_Income": INCOME,
    "Dividend_Income": INCOME,
    "Interest_Income": INCOME,
    # Money out / financial
    "Investment": FINANCIAL,
    "Investment_Liquidation": FINANCIAL,
    "Interest_Paid": FINANCIAL,
    "Loan": FINANCIAL,
    "Credit_Card_Payment": FINANCIAL,
    "Tax_Govt": FINANCIAL,
    "IT_Return": FINANCIAL,
    "Fees_Charges": FINANCIAL,
    # Utilities
    "Utilities_Bills": UTILITIES,
    # Lifestyle
    "Entertainment": LIFESTYLE,
    "Education": LIFESTYLE,
    "Gifts": LIFESTYLE,
    "Personal_Care": LIFESTYLE,
    # Transfers
    "P2P_Transfer": TRANSFERS,
    "Merchant_Transfer": TRANSFERS,
    "Friends_And_Family": TRANSFERS,
    "Switch_Own_Accounts": TRANSFERS,
    "Sending_Home": TRANSFERS,
    "Money_Wasted": TRANSFERS,
    # Cash
    "ATM_Cash": CASH,
}

# Sub-categories are refinements *within* a Broad_Category — they never move a
# transaction between broad categories. Order matters: first match wins.
#   (Broad_Category, keywords, Sub_Category)
SUBCATEGORY_KEYWORD_RULES = [
    # ---- Rent: the motivating case. One label was covering four unrelated
    # things: the landlord, a co-living platform, a deposit and brokerage.
    ("Rent", ("HYLO", "CHALLENGER", "COLIVING", "CO-LIVING", "OYO", "ZOLO", "NOOK"),
     "CoLiving_Rent"),
    ("Rent", ("BROKER", "COMMISSION", "AGREEMENT", "RAZPHYLOBIZ", "RAZPAY", "PROPERTY BROKER"),
     "Rent_Brokerage"),
    ("Rent", ("ADVANCE FOR ROOM", "SECURITY DEPOSIT", "DEPOSIT", "TOKEN", "BROKERAGE"),
     "Rent_Deposit"),
    ("Rent", ("MAINTENANCE", "REPAIR", "SOCIETY", "CORPORATION"), "Rent_Maintenance"),

    # ---- Food
    ("Food_Dining", ("SWIGGY", "ZOMATO", "FOODPANDA", "EATSMEE", "DELIVERY"),
     "Food_Delivery"),
    ("Food_Dining", ("CAFE", "COFFEE", "STARBUCKS", "CCD", "BLUE TOKAI", "LOYAL CAFE"),
     "Cafe"),
    ("Food_Dining", ("SWEETS", "BAKERY", "LADDOOS", "KESAR", "CONFECTION", "MITHI"),
     "Bakery_Sweets"),
    ("Food_Dining", ("HOTEL", "RESTAURANT", "BIRYANI", "DHABA", "TANDOOR", "PIZZA"),
     "Restaurant"),
    ("Groceries", ("BIGBASKET", "ZEPTO", "BLINKIT", "INSTAMART", "DMART", "SUPER"),
     "Grocery_Online" ),

    # ---- Transport
    ("Travel", ("PETROL", "DIESEL", "HP ", "IOC", "BHARAT PETRO", "FUEL", "PUMP"),
     "Fuel"),
    ("Travel", ("IRCTC", "RAILWAY", "INDIAN RAILWAYS", "TRAIN", "SLEEPER"), "Rail"),
    ("Travel", ("FLY", "AIR INDIA", "INDIGO", "AKASA", "SPICEJET", "AIRPORT"), "Flights"),
    ("Travel", ("OYO", "HOTEL", "TRIP.COM", "MAKEMYTRIP", "GOIBIBO", "HOSTEL"),
     "Accommodation"),
    ("Travel", ("UBER", "OLA ", "RAPIDO", "Namma Yatri", "AUTO ", "CAB "), "Ride_Hailing"),
    ("Vehicle", ("SERVICE", "WORKSHOP", "GARAGE", "PETROL PUMP", "CAR WASH", "TYRE"),
     "Vehicle_Service"),

    # ---- Shopping
    ("Shopping_Retail", ("AMAZON", "FLIPKART", "MYNTRA", "MEESHO", "AJIO", "SNIPES",
                         "AJIO", "MYNTR"), "Online_Retail"),
    ("Shopping_Retail", ("ELECTRONIC", "MOBILE PHONE", "LAPTOP", "APPLIANCE"),
     "Electronics"),
    ("Shopping_Retail", ("CLOTH", "APPAREL", "SAREE", "KURTA", "TRENDS", "ZARA"),
     "Apparel"),

    # ---- Health
    ("Healthcare", ("PHARMACY", "CHEMIST", "MEDICAL", "DRUG", "PLATINUM CHEMIST"),
     "Pharmacy"),
    ("Healthcare", ("HOSPITAL", "CLINIC", "DENTAL", "DOCTOR", "LAB ", "DIAGNOSTIC"),
     "Hospital"),
    ("Healthcare", ("GYM", "FITNESS", "YOGA", "SPORT"), "Fitness"),

    # ---- Utilities
    ("Utilities_Bills", ("RECHARGE", "AIRTEL", "JIO", "VODAFONE", "BSNL", "MOBILE",
                         "POSTPAID", "PREPAID", "DTH"), "Mobile_Recharge"),
    ("Utilities_Bills", ("BROADBAND", "FIBER", "INTERNET", "ASIANET", "ACT FIBER"),
     "Broadband"),
    ("Utilities_Bills", ("ELECTRIC", "ELECTRICITY", "KSEB", "MSEB", "TANGEDCO"),
     "Electricity"),
    ("Utilities_Bills", ("WATER", "SEWERAGE", "MUNICIPAL"), "Water"),
    ("Utilities_Bills", ("LPG", "GAS ", "INDANE", "HP GAS"), "LPG"),

    # ---- Investment
    ("Investment", ("SIP", "MUTUAL FUND", "MFSS", "FUND"), "Mutual_Fund"),
    ("Investment", ("GROWW", "ZERODHA", "NSE", "BSE", "SHARE", "DEMAT", "TRADING"),
     "Equity_Trading"),
    ("Investment", ("FD ", "FD THROUGH", "RD ", "RD THROUGH", "RECURRING DEPOSIT",
                    "IB FD", "MATURED RD"), "FD_RD"),
]

# Sub-categories that exist purely as defaults, so a parent bucket still reads
# sensibly when no keyword rule matches.
SUBCATEGORY_DEFAULTS = {
    "Rent": "Residential_Rent",
    "Food_Dining": "Restaurant",
    "Groceries": "Grocery_Store",
    "Travel": "Travel_General",
    "Shopping_Retail": "Retail_General",
    "Healthcare": "General_Healthcare",
    "Utilities_Bills": "Other_Utility",
    "Investment": "Investment_General",
    "Loan": "Loan_Repayment",
    "Vehicle": "Vehicle_Expense",
}

BUILTIN_SUB_CATEGORIES = sorted(
    {r[2] for r in SUBCATEGORY_KEYWORD_RULES} | set(SUBCATEGORY_DEFAULTS.values())
)


# Names that are both a parent rollup and (occasionally) a broad category in their
# own right. A category named after a parent must roll up to itself, not to Other.
_PARENT_NAMES = {
    HOUSING, FOOD, TRANSPORT, SHOPPING, HEALTH, FINANCIAL,
    UTILITIES, LIFESTYLE, TRANSFERS, CASH, INCOME, OTHER_CATEGORY,
}


def parent_category(broad_category):
    """
    Maps a Broad_Category up to its parent Category.

    Unknown values (including user-created custom categories) fall back to
    OTHER_CATEGORY rather than disappearing, so a rollup always covers 100% of
    transactions. A broad category that shares a name with a parent (Lifestyle,
    Income) maps to itself rather than to Other.
    """
    key = str(broad_category or "").strip()
    if key in _PARENT_NAMES:
        return key
    return CATEGORY_PARENT.get(key, OTHER_CATEGORY)


def assign_sub_category(broad_category, narration, details, payee_receiver,
                        reference_id):
    """
    Refines a Broad_Category into a Sub_Category.

    Returns the Broad_Category unchanged when no rule matches, so the parent ->
    child rollup is always well defined and every transaction belongs to exactly
    one leaf. Like the broad layer, this only splits within a category; it never
    moves a transaction between categories.
    """
    broad = str(broad_category or "").strip()
    fields = (
        _u(narration),
        _u(details),
        _u(payee_receiver),
        _u(reference_id),
    )

    for rule_broad, keywords, sub in SUBCATEGORY_KEYWORD_RULES:
        if rule_broad != broad:
            continue
        if any(keyword.upper() in field for keyword in keywords for field in fields):
            return sub

    return SUBCATEGORY_DEFAULTS.get(broad, broad)
