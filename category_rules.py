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

Every category also declares a *direction* (money in, money out, or both) and a
prose definition — see CATEGORY_SPECS. Direction is behaviour, not prose: it lets
a credit that lands in an outflow category be recognised as the different event it
actually is (a Groww payout is not "investment"), and it lets the UI flag a row
whose category disagrees with its own amount column. The definitions are seeded
to `category_definitions` and are editable from the dashboard; they are also the
taxonomy handed to the LLM when it suggests a category, so what the model is
told about a category is the same text the user reads.
"""

import re

# ---------------------------------------------------------------------------
# Direction vocabulary
#
# A category is only *about* one direction for some categories and legitimately
# both for others. `Investment` was previously direction-agnostic on purpose: a
# Groww debit and a Groww credit were filed alike because splitting them "made
# how much did I invest unanswerable". It does not — the parent rollup still
# totals both, and the split is what makes "did this money come back?" askable
# at all. Only genuinely paired categories are split; the rest keep one name.
# ---------------------------------------------------------------------------
DIRECTION_IN = "IN"      # money arriving - income, a repayment received, a refund
DIRECTION_OUT = "OUT"    # money leaving - spending, saving, an obligation paid
DIRECTION_BOTH = "BOTH"  # direction-agnostic: a transfer is the same event either way

DIRECTION_VALUES = (DIRECTION_IN, DIRECTION_OUT, DIRECTION_BOTH)

# ---------------------------------------------------------------------------
# Built-in catalog of broad categories (display order matters in the UI)
# ---------------------------------------------------------------------------
BUILTIN_CATEGORIES = [
    # ---- Money in
    "Salary",
    "Non_Salary_Income",
    "Dividend_Income",
    "Interest_Income",
    "Investment_Liquidation",
    "Loan_Disbursal",
    "Cash_Deposit",
    "Card_Refund",
    "Tax_Refund",
    # ---- Money out
    "Investment",
    "Interest_Paid",
    "Rent",
    "Credit_Card_Payment",
    # Loan EMIs. It already had an entry in CATEGORY_PARENT (-> FINANCIAL) and in
    # SUBCATEGORY_DEFAULTS (-> Loan_Repayment), but was missing from this registry,
    # which is what db seeds `broad_categories` from. So the parser could emit it and
    # a fresh database would not know the name.
    "Loan",
    "Food_Dining",
    "Groceries",
    "Shopping_Retail",
    "Healthcare",
    "Travel",
    "Utilities_Bills",
    "Tax_Govt",
    "Fees_Charges",
    "ATM_Cash",
    # ---- Either way
    "Switch_Own_Accounts",
    "P2P_Transfer",
    "P2P_Received",
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
# Category definitions
#
# Three jobs, one table per concern:
#   direction    - behaviour. Read by apply_direction_awareness, so it must be a
#                  constant in code: a category whose meaning depends on a row
#                  that has not been written yet cannot be defined by a row that
#                  has not been written yet.
#   description  - prose. Seeded into `category_definitions`, editable in the UI,
#                  and sent to the LLM so its suggestions are argued in the user's
#                  own taxonomy rather than the model's.
#   examples     - concrete merchant/keyword hints, same treatment.
#
# A direction of BOTH is a deliberate statement: the category names the *event*
# and the event is the same whichever way the money ran.
# ---------------------------------------------------------------------------
CATEGORY_SPECS = {
    # ---------------- Money in
    "Salary": {
        "direction": DIRECTION_IN,
        "description": "Payroll credited by an employer. The regular take-home "
                       "payment, not a bonus or a reimbursement.",
        "examples": "SALARYINR, ALLEGIS, PAYROLL, monthly credit from a company",
    },
    "Non_Salary_Income": {
        "direction": DIRECTION_IN,
        "description": "Money received that is not a salary and not investment "
                       "return - freelance or marketplace payouts, refunds of "
                       "service, reseller income.",
        "examples": "PHONEPE PRIVATE LIMITED, FLIPKART INTERNET, PAYPAL PAYMENTS",
    },
    "Dividend_Income": {
        "direction": DIRECTION_IN,
        "description": "A dividend distribution from a company you hold shares in.",
        "examples": "HDFC BANK SPL INT DIV, ASIANPAINTSFINDIV, ONGS DIV",
    },
    "Interest_Income": {
        "direction": DIRECTION_IN,
        "description": "Interest earned on money you already hold - a savings "
                       "account, a balance, capitalised credit interest.",
        "examples": "CREDIT INTEREST CAPITALISED, savings interest credit",
    },
    "Investment_Liquidation": {
        "direction": DIRECTION_IN,
        "description": "Money coming BACK out of an investment: shares sold, an "
                       "FD or RD matured, a mutual fund redeemed. The credit-side "
                       "counterpart of Investment - the same platform and the same "
                       "intent, with the direction reversed.",
        "examples": "GROWW credit, ZERODHA sell proceeds, MATURED RD, AXIS MUTUAL FUND REDEMPTION",
    },
    "Loan_Disbursal": {
        "direction": DIRECTION_IN,
        "description": "A loan arriving - the amount the lender actually paid out. "
                       "Distinct from Loan, which is you paying an instalment.",
        "examples": "EMI loan sanction credit, lender disbursement",
    },
    "Cash_Deposit": {
        "direction": DIRECTION_IN,
        "description": "Cash paid into the account over a counter. The credit-side "
                       "counterpart of ATM_Cash.",
        "examples": "ATM cash deposit credit, counter deposit at a branch",
    },
    "Card_Refund": {
        "direction": DIRECTION_IN,
        "description": "A credit-card issuer returning money - a purchase refund, "
                       "a cashback credit or a statement credit. Not income and "
                       "not a bill payment.",
        "examples": "ACH C- SBICARD INT, card refund credit",
    },
    "Tax_Refund": {
        "direction": DIRECTION_IN,
        "description": "Income tax or GST refunded to you by the government.",
        "examples": "ITDTAX REFUND, TAX REFUND",
    },
    # ---------------- Money out
    "Investment": {
        "direction": DIRECTION_OUT,
        "description": "Money moving into an asset you expect to be worth more "
                       "later - equity, mutual funds, a fixed or recurring deposit. "
                       "Excludes loan repayments.",
        "examples": "GROWW, ZERODHA, MOTILAL, RD/FD placements, SIP instalments",
    },
    "Interest_Paid": {
        "direction": DIRECTION_OUT,
        "description": "Interest the bank charged you - overdraft interest, "
                       "default charges on a credit facility.",
        "examples": "INTEREST PAID, debit interest on overdraft",
    },
    "Rent": {
        "direction": DIRECTION_OUT,
        "description": "Paying for the right to occupy a home - the landlord, a "
                       "co-living platform, or a deposit or brokerage to obtain one.",
        "examples": "landlord transfer, HYLO/ZOLO co-living, RENT in the narration remark",
    },
    "Credit_Card_Payment": {
        "direction": DIRECTION_OUT,
        "description": "Paying a credit-card bill from the bank account. This "
                       "settles previous spending rather than spending anything "
                       "new, which is why it is excluded from spend totals.",
        "examples": "ACH DEBIT SBICARD, HDFC CREDIT CARD, CRED CLUB",
    },
    "Loan": {
        "direction": DIRECTION_OUT,
        "description": "Repaying a loan - principal or interest on an instalment. "
                       "Excludes credit-card bill payments.",
        "examples": "EMI,PRIN, EMI,INT NBR, EMI,PROCNG FEE",
    },
    "Food_Dining": {
        "direction": DIRECTION_OUT,
        "description": "Eating out or ordering in - restaurants, cafes, delivery "
                       "apps, sweets and bakeries.",
        "examples": "SWIGGY, ZOMATO, CAFE, SWIGGY ORDER, bakery",
    },
    "Groceries": {
        "direction": DIRECTION_OUT,
        "description": "Food and household supplies to bring home - supermarkets "
                       "and quick-commerce grocery apps.",
        "examples": "BIGBASKET, ZEPTO, BLINKIT, DMART, SUPER MARKET",
    },
    "Shopping_Retail": {
        "direction": DIRECTION_OUT,
        "description": "Buying things you keep - clothing, electronics, household "
                       "goods, online or offline.",
        "examples": "AMAZON, FLIPKART, MYNTRA, RELIANCE DIGITAL, DECATHLON",
    },
    "Healthcare": {
        "direction": DIRECTION_OUT,
        "description": "Medical and health spending - pharmacy, hospital, dental, "
                       "diagnostics, gym and fitness.",
        "examples": "PHARMACY, HOSPITAL, DENTAL, GYM",
    },
    "Travel": {
        "direction": DIRECTION_OUT,
        "description": "Getting somewhere - rail, air, bus, ride-hailing, hotels "
                       "and fuel. Overseas spending while on a trip lands here.",
        "examples": "IRCTC, INDIGO, MAKEMYTRIP, UBER, PETROL",
    },
    "Utilities_Bills": {
        "direction": DIRECTION_OUT,
        "description": "Standing household services - electricity, water, LPG, "
                       "broadband, mobile recharge, DTH.",
        "examples": "ELECTRICITY, AIRTEL RECHARGE, ASIANET, BBPS, INDANE",
    },
    "Tax_Govt": {
        "direction": DIRECTION_OUT,
        "description": "Tax paid to the government - GST, income tax, TDS.",
        "examples": "IGST, GST, INCOME TAX, ETREASURY",
    },
    "Fees_Charges": {
        "direction": DIRECTION_OUT,
        "description": "The bank or a card issuer charging you - service fees, "
                       "alert charges, ATM fees, foreign-currency markup, finance "
                       "charges on a card.",
        "examples": "INSTA ALERT CHG, ATM FEES, FCY MARKUP, FINANCE CHARGES",
    },
    "ATM_Cash": {
        "direction": DIRECTION_OUT,
        "description": "Withdrawing physical cash from an ATM. Kept distinct from "
                       "Travel even when the withdrawal happens abroad, because "
                       "the money is cash rather than a purchase.",
        "examples": "ATW-, EAW-, NWD, ATM FEES",
    },
    # ---------------- Either way
    "Switch_Own_Accounts": {
        "direction": DIRECTION_BOTH,
        "description": "Moving your own money between accounts you control. It is "
                       "the same event whichever direction it runs, and it is not "
                       "income or spending.",
        "examples": "own-name transfer, own-account switch",
    },
    "P2P_Transfer": {
        "direction": DIRECTION_OUT,
        "description": "Money sent directly to another person, and nothing more "
                       "specific could be identified about it.",
        "examples": "UPI to an unidentified person, NEFT/IMPS to a person",
    },
    "P2P_Received": {
        "direction": DIRECTION_IN,
        "description": "Money received directly from another person, where the "
                       "sender could not be identified more specifically.",
        "examples": "UPI credit from an unidentified person",
    },
    "Uncategorized": {
        "direction": DIRECTION_BOTH,
        "description": "Not enough was identified to say what this was. Deliberately "
                       "honest rather than confidently wrong - a missing bucket is "
                       "visible, a wrong one is indistinguishable from a right one.",
        "examples": "unrecognised narration, truncated card descriptor",
    },
}

# The credit-side counterpart of an outflow category, but ONLY where the two
# directions are different events that a person would name differently.
#
# A refund from a grocery store is deliberately absent. Re-labelling it would
# destroy the one thing the category was doing: netting the refund off the
# original spend. So groceries refunds stay Groceries and are flagged instead —
# see apply_direction_awareness.
CREDIT_INVERSE = {
    "Investment": "Investment_Liquidation",
    "ATM_Cash": "Cash_Deposit",
    "Loan": "Loan_Disbursal",
    "Credit_Card_Payment": "Card_Refund",
    "Tax_Govt": "Tax_Refund",
    "P2P_Transfer": "P2P_Received",
}

# code-level direction, keyed by category. Derived from CATEGORY_SPECS so the two
# can never disagree; users may override a direction at read time through
# `category_definitions.direction_override`.
CATEGORY_DIRECTION = {
    name: spec["direction"] for name, spec in CATEGORY_SPECS.items()
}


def category_direction(category, overrides=None):
    """
    The direction a category is about: IN, OUT, or BOTH.

    `overrides` is the user-editable map from `category_definitions`; it wins over
    the code default so a category can be re-pointed without a code change. An
    unlisted category is BOTH, which is the safe answer: it produces no split and
    no mismatch flag rather than guessing at a category nobody has described.
    """
    name = str(category or "").strip()
    if overrides:
        override = overrides.get(name)
        if override in DIRECTION_VALUES:
            return override
    return CATEGORY_DIRECTION.get(name, DIRECTION_BOTH)


def apply_direction_awareness(category, has_debit, has_credit, direction_map=None):
    """
    Reconciles a category against the side its money actually moved.

    Three outcomes, in order:

      1. A paired category is corrected. A credit on Investment is money coming
         back out of an investment, which is a different event with a different
         name, so it is re-filed as Investment_Liquidation. This is the whole
         reason CREDIT_INVERSE exists.

      2. Anything else is flagged, not moved. A credit on Groceries is a refund,
         and the category is already correct for the arithmetic — re-filing it
         would stop it netting off the original spend. So it keeps its category
         and reports why the two disagree.

      3. A row with money on both sides, or a BOTH category, is left alone.
         There is nothing to disagree with, and guessing would be worse than
         saying nothing.

    Returns (category, mismatch_reason, corrected_from). `corrected_from` is the
    category that was replaced, so the UI can say what it changed rather than
    silently presenting a label the parser never produced.
    """
    if category is None:
        return category, None, None

    expected = category_direction(category, direction_map)
    if expected == DIRECTION_BOTH:
        return category, None, None

    # Money on both sides is already ambiguous; the direction normaliser in
    # db._apply_direction_overrides resolves it before this runs at read time.
    if has_debit and has_credit:
        return category, None, None

    corrected_from = None
    if expected == DIRECTION_OUT and has_credit:
        inverse = CREDIT_INVERSE.get(category)
        if inverse:
            category, corrected_from = inverse, category
        else:
            return category, "credit in an expense category (most likely a refund)", None
    elif expected == DIRECTION_IN and has_debit:
        return category, "debit in an income category", None

    return category, None, corrected_from

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
def _assign_broad_category_raw(narration, transaction_type, details, payee_receiver,
                               reference_id, has_debit=False, has_credit=False):
    """
    The keyword/channel rules alone, with no regard for which side the money moved.

    Split out from assign_broad_category so that the direction reconciliation in
    apply_direction_awareness has exactly one exit point to run at. Folding it into
    each of the twenty-odd `return` statements here would mean twenty-odd chances to
    forget one.
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
    #
    # Debits only, and the brand list is shared with the Card_Refund branch below:
    # a credit from the same issuer is the opposite event, and reading one as the
    # other is exactly the mistake this split exists to stop.
    _CARD_BRANDS = ("CRED CLUB", "CRED.CLUB", "AMAZONPAYCC", "AMAZON PAY CREDIT",
                    "INDMONEY CREDIT CARD", "HDFCYA", "HDFCSI", "HDFC5X", "HDFC1S",
                    "CREDIT CARD")
    if has_debit and (_has("SBICARD", n, d) or _any_has(_CARD_BRANDS, n, d)):
        return "Credit_Card_Payment"

    # A credit from a card brand is the issuer giving money back - a purchase
    # refund, a cashback credit, a statement credit. The original comment here
    # already said so ("is interest/cashback/refund, not a payment") but had
    # nowhere to file it, so the row fell through to Uncategorized.
    if has_credit and (_has("SBICARD", n, d) or _any_has(_CARD_BRANDS, n, d)):
        return "Card_Refund"

    # Salary / payroll credits.
    if has_credit:
        if _any_has(("SALARYINR", "ALLEGIS", "PAYROLL", "SALARY"), n, d, r):
            return "Salary"
        if _has("ITDTAX REFUND", n, d) or _has("TAX REFUND", n, d):
            return "Tax_Refund"

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
    #
    # This returns Investment for BOTH directions and lets
    # apply_direction_awareness split them: a credit from these platforms is sell
    # proceeds or a maturity, which is money coming back rather than going in.
    # They used to be filed alike on the reasoning that splitting them made "how
    # much did I invest?" unanswerable - it does not, because both sides still roll
    # up to Financial, and leaving them together is what made a payout read as an
    # investment you made.
    if _any_has(("GROWW", "ZERODHA", "MOTILAL", "KSFE", "KSFEL", "RD INSTALLMENT",
                 "RD THROUGH", "FD THROUGH", "FD PREMAT", "MATURED RD",
                 "MFSS", "BSE-", "NSE CLEARING", "INDMONEY", "MUTUAL FUND",
                 "SHAREMARKET", "CHITTY", "CHIT FUND", "RD. TRANSFER"),
                n, d, p, r):
        return "Investment"

    # Own / family account switches (self transfers).
    if _has("VISHNU NARAYAN", n, d, p) or _has("VNS5733", n, d, r):
        return "Switch_Own_Accounts"

    # Cash paid in over a counter or an ATM, as opposed to cash taken out. This is
    # the mirror of the ATM_WITHDRAWAL fallback at the bottom, and it is a credit,
    # so it can never reach that branch.
    #
    # Kept to phrases that name the deposit rather than the bare word DEPOSIT. A
    # landlord's security deposit and an FD placement are both deposits, and both
    # are outflows - "DEPOSIT" on its own would pull them in here and relabel a
    # real expense as an inflow.
    if has_credit and _any_has(("CASH DEPOSIT", "CDM DEPOSIT", "CASHDEP",
                                "CASH DEP CR", "DEPOSIT BY CASH",
                                "DEPOSIT CASH", "CASH IN DEPOSIT"), n, d):
        return "Cash_Deposit"

    # Health.
    if _any_has(("PHARMACY", "CHEMIST", "HOSPITAL", "CLINIC", "AYURVEDA",
                 "MEDICAL", "DENTAL", "DOCTOR", "LABS"), n, d, p):
        return "Healthcare"

    # Food & dining.
    if _any_has(("SWIGGY", "ZOMATO", "EATCLUB", "SWEETS", "CAFE", "BAKERY",
                 "LADDOS", "PIZZA", "TEA STALL", "LASSI", "HOTEL", "RESTAURANT",
                 "FOODS", "TANDOOR", "BIRYANI"), n, d, p):
        return "Food_Dining"

    # Card-descriptor dining. These narrations truncate the brand to a fragment
    # ("UTOPIA DINE", "SMOKE THE SIZZLER"), so each token was taken from the
    # descriptor as printed.
    if _any_has(("BURGER KING", "SHAWARMA", "SIZZLER", "UTOPIA DINE",
                 "SEMOLINA KITCHENS", "CHOICE BAKERS", "JUST SHAWARMA"),
                n, d, p):
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

    # ---- Card-descriptor merchants -------------------------------------
    # A card statement prints one un-delimited line per purchase and names no
    # channel, so none of the rules above can see it. Each group below is a set of
    # descriptors that were verified by hand against the parsed rows; they are
    # deliberately restricted to BUILTIN_CATEGORIES so a fresh database resolves
    # them, and every keyword is specific enough not to fire on an unrelated
    # narration. Anything not named here stays Uncategorized on purpose - an
    # honest bucket beats a confident wrong one.

    # Flights and travel booking. "AIR IND" (with the space) already matched
    # above, but the issuer also prints the un-spaced "AIRINDXPRESS".
    if _any_has(("AIRIND", "AKASA AIR", "REDBUS", "EASY TRIP", "AKASA AIR",
                 "AIRPORT SERV", "TRIP.COM"), n, d, p):
        return "Travel"

    # Overseas travel. The currency token is the reliable signal; the place names
    # are the Indonesian resorts those statements actually name.
    #
    # Guarded on ATM_WITHDRAWAL because these keywords match the LOCATION, not a
    # merchant: "ATW-416021XXXXXX3942-S1AWADE3-DENPASAR FB" is a cash withdrawal at
    # an ATM in Bali. It is travel spending in reality, but it is also cash, and
    # re-filing it away from ATM_Cash would silently drop two rows out of the Cash
    # rollup to re-file them under Travel.
    if tt != "ATM_WITHDRAWAL" and _any_has(
            (" IDR ", "BADUNG", "DENPASAR", "GIANYAR"), n, d, p):
        return "Travel"

    # Electronics and appliance retail.
    if _any_has(("RELIANCE DIGITAL", "RELIANCEDIGITAL", "ACER INDIA",
                 "DECATHLON", "DIGITAL STORE", "Croma", "CROMA"), n, d, p):
        return "Shopping_Retail"

    # Textiles and clothing. "SILKS" plus the Kerala wedding-season retailers that
    # were individually verified (five rows, Rs 1.77L, all in one season).
    #
    # "SAREE" is deliberately NOT here even though the sub-category rule uses it:
    # sareen is a common surname, and it matched the person "ANGAD SAREEN" - a
    # transfer to a human, filed as a clothing purchase. A keyword that can read a
    # surname is not a keyword.
    if _any_has(("SILKS", "AIYAPPAS", "PITTAPPILLIL", "PULIMOOTTIL",
                 "ZARA", "FIRSTCRY", "PRAXIS HOME", "ISHAARA", "POSSA DIA",
                 "PANKAJ HOME"), n, d, p):
        return "Shopping_Retail"

    # Gifting platforms - bought through a corporate gifting desk, so the amount
    # is a gift rather than a personal purchase.
    if _any_has(("SMARTBUY", "GYFTR", "GIFTCARD", "GIFT CARD"), n, d, p):
        return "Shopping_Retail"

    # DTH recharge. "SPAY" is the Sky DTH abbreviation the issuer prints; the
    # merchant itself is truncated to "SPAY 1183338639 TATASKYDTH", so the token
    # has to be matched on its own.
    if _any_has(("SPAY ", "TATASKY", "DTH "), n, d, p):
        return "Utilities_Bills"

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

    # Card FX markup and the issuer's own finance charge. Checked after the generic
    # "FEES"/"COMMISSION" rule above, which already catches "FINANCE CHARGES" via
    # its CHARGE token on other issuers' wording.
    if _any_has(("FINANCE CHARGES", "FCY MARKUP", "CONSOLIDATED FCY"), n, d):
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

    # Loan EMIs.
    #
    # The `EMI` transaction type is only detected when a narration carries BOTH
    # "EMI" and "CHQ" (see narration_parser). Some lenders print the instalment
    # breakdown instead and omit the CHQ token entirely:
    #
    #     OFFUS EMI,PRIN NB:09,00000105683840 (REF# ...)
    #     OFFUS EMI,INT NBR:01,00000105683840 (REF# ...)
    #     OFFUS EMI,PROCNG FEE,00000000001056 (REF# ...)
    #
    # Those rows never became EMI type, so they fell past the branch below to
    # Uncategorized - 20 rows and Rs 1,26,214 of a perfectly ordinary loan, none of
    # it visible under any category. Matched on the "EMI," shape rather than on the
    # lender name so a new issuer is caught without a code change; the presence of
    # "PRIN" / "INT NBR" / "PROCNG FEE" keeps it off an unrelated narration that
    # merely mentions EMI.
    if _any_has(("EMI,PRIN", "EMI,INT NBR", "EMI,PROCNG", "EMI PRIN"), n, d, p):
        return "Loan"

    # EMIs on loans that are not credit-card related.
    if tt == "EMI":
        return "Investment"

    # Everything that reached here is an unidentified person-to-person or
    # generic flow -> let Payee map / user overrides / generic bucket handle it.
    #
    # The `tt != "OTHER"` guard is load-bearing. Every branch of parse_narration that
    # sets a payee also sets a real channel type (UPI, IMPS, NEFT, ACH, ...), and the
    # fallback branch sets OTHER - so "OTHER and has a payee" was unreachable until
    # that branch began deriving a merchant from a bare card descriptor. Without the
    # guard, reading a descriptor as a merchant was enough to file the purchase as a
    # person-to-person transfer: 416 rows worth Rs 16.7L moved from Uncategorized to
    # P2P_Transfer, and not one of them improved. A card descriptor is a merchant,
    # so an unidentified one stays honestly Uncategorized until a rule names it.
    if p and tt != "OTHER":
        return "P2P_Transfer"
    return "Uncategorized"


def assign_broad_category(narration, transaction_type, details, payee_receiver,
                          reference_id, has_debit=False, has_credit=False,
                          direction_map=None):
    """
    Returns the broad category for one transaction.

    Priority: keyword hard rules > channel fallback, then reconciled against the
    direction the money actually moved. (DB override rules are applied separately
    at read time and take precedence over everything this function computes.)

    `direction_map` is the optional user override for category directions, applied
    at read time only - the parser has no database to consult, so a stored value
    always falls back to the code-level CATEGORY_DIRECTION.
    """
    category = _assign_broad_category_raw(
        narration=narration,
        transaction_type=transaction_type,
        details=details,
        payee_receiver=payee_receiver,
        reference_id=reference_id,
        has_debit=has_debit,
        has_credit=has_credit,
    )
    category, _mismatch, _corrected = apply_direction_awareness(
        category, has_debit, has_credit, direction_map=direction_map
    )
    return category


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
    # Money out / financial. Each paired category rolls up to the SAME parent as its
    # counterpart, so splitting a category by direction changes what a row is
    # called without changing what any rollup adds up to.
    "Investment": FINANCIAL,
    "Investment_Liquidation": FINANCIAL,
    "Loan": FINANCIAL,
    "Loan_Disbursal": FINANCIAL,
    "Interest_Paid": FINANCIAL,
    "Credit_Card_Payment": FINANCIAL,
    "Card_Refund": FINANCIAL,
    "Tax_Govt": FINANCIAL,
    "Tax_Refund": FINANCIAL,
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
    "P2P_Received": TRANSFERS,
    "Merchant_Transfer": TRANSFERS,
    "Friends_And_Family": TRANSFERS,
    "Switch_Own_Accounts": TRANSFERS,
    "Sending_Home": TRANSFERS,
    "Money_Wasted": TRANSFERS,
    # Cash
    "ATM_Cash": CASH,
    "Cash_Deposit": CASH,
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

    # ---- The credit-side counterparts. The leaf has to be re-derived from the new
    # parent, or a Groww sale would keep the Mutual_Fund leaf it picked up as an
    # Investment debit. Same keywords, opposite meaning, so the leaf names the
    # vehicle and the parent names which way the money ran.
    ("Investment_Liquidation", ("MUTUAL FUND", "REDEMPTION"), "Mutual_Fund_Redemption"),
    ("Investment_Liquidation", ("GROWW", "ZERODHA", "NSE", "BSE", "DEMAT", "SELL"),
     "Equity_Sale"),
    ("Investment_Liquidation", ("FD ", "FD THROUGH", "RD ", "RD THROUGH",
                                "RECURRING DEPOSIT", "MATURED RD", "IB FD"),
     "FD_RD_Maturity"),
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
    "Investment_Liquidation": "Investment_Liquidation_General",
    "Loan": "Loan_Repayment",
    "Loan_Disbursal": "Loan_Disbursal_General",
    "Cash_Deposit": "Cash_Deposit_General",
    "Card_Refund": "Card_Refund_General",
    "Tax_Refund": "Tax_Refund_General",
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
