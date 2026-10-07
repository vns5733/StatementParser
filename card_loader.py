"""
card_loader.py — parsers for credit-card statement PDFs.

Credit-card statements are NOT bank statements and cannot be fed through
loader.load_and_clean_statement: there is no Value Date, no Closing Balance, no
Chq/Ref column, and the rupee glyph extracts as the letter "C" on HDFC
(the embedded font is ITFRupee). Each issuer also uses a different transaction
table shape, so this module holds one adapter per issuer family.

Layouts verified against the four statements in CreditCard/:
  HDFC   (Regalia, Tata Neu Infinity)  A4, date anchor x0=25.5, 14.2pt pitch,
                                       description cell is VERTICALLY CENTRED so
                                       a wrapped description renders one line
                                       above the anchor and the rest below it.
                                       Rupee glyph extracts as "C".
  ICICI  (Amazon Pay)                 date anchor x0=207.8, a "25%" reward-rate
                                       column at x0=146 (which precedes the date,
                                       so the row must be grouped by the date,
                                       not by the left-most token), and credits
                                       marked with a trailing "CR".
  SCAPIA (Federal)                   "13-08-2026·21:21" in ONE token (the
                                       separator is U+00B7), description in the
                                       middle, right-aligned "₹445.00" as a
                                       single token.

Issuer-provided categories
--------------------------
Some issuers classify the spend for us, which is far more reliable than keyword
matching. Both signals are captured:
  * ICICI puts the category inside the description ("AMAZON PAY IN GROCERY
    BANGALORE IN", "Swiggy BENGALURU IN") -> extracted as `Statement_Category`.
  * HDFC prints a statement-level "Purchase Indicator / Insights" block
    (GROCERIES 21%, RESTAURANT 19%, ...) -> captured as `Spend_Mix` on the
    statement. It is a cycle-level breakdown, so it validates the parser's own
    category totals rather than tagging individual rows.
The per-transaction value wins; `Spend_Mix` is the fallback for issuer-level
consistency checking.
"""

import os
import re
import uuid

import pandas as pd

from config import CREDIT_CARD_COLUMNS

try:
    import pdfplumber
except ImportError:  # pragma: no cover
    pdfplumber = None

# Rows are 14.2pt apart on HDFC cards but a wrapped description renders up to
# ~4.3pt off the anchor because the cell is vertically centred. Grouping must
# therefore use a tolerance that admits those lines without merging the next row.
ROW_TOLERANCE = 5.5

AMOUNT_RE = re.compile(r"^([\d,]+\.\d{2})$")
RUPEE_PREFIX_RE = re.compile(r"^[₹C]\s*", re.IGNORECASE)
HDFC_DATE_RE = re.compile(r"^(\d{2}/\d{2}/\d{4})\|?$")
ICICI_DATE_RE = re.compile(r"^(\d{2}/\d{2}/\d{4})$")
SCAPIA_DATE_RE = re.compile(r"^(\d{2}-\d{2}-\d{4})[·•](\d{1,2}:\d{2})")

# HDFC emits the rupee sign from the "ITFRupee" font, which pdfminer maps to "C".
RUPEE_GLYPH = "C"


def _words(page):
    return [
        {"x0": w["x0"], "x1": w["x1"], "top": w["top"], "bottom": w["bottom"], "text": w["text"]}
        for w in page.extract_words()
    ]


def _clean(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def parse_amount(token, allow_credit_suffix=False, allow_sign_prefix=False):
    """
    Turns an extracted amount token into a float.

    Handles the shapes seen in the wild:
        "1,455.00"     plain
        "C1,60.82"     HDFC, the ITFRupee glyph rendering as "C"
        "Rs445.00"     SCAPIA, rupee preserved
        "2,751.61 CR"  ICICI credit, which is money coming back
    Returns (amount, is_credit) or (None, False).

    `allow_sign_prefix` accepts a leading "+" or "-" as the sign, which is how
    Tata Neu marks a credit on recent statements: it prints "+ C 498.00" as its
    own token, to the LEFT of the amount band. Without this that token parses to
    None, the loop moves on to the bare "C 498.00", and the credit is read as a
    DEBIT - so 12 of 27 statements recorded every payment as spend.
    """
    if token is None:
        return None, False
    raw = _clean(token)
    raw = raw.replace("₹", "").replace("Rs.", "").replace("Rs", "")
    is_credit = False
    if allow_sign_prefix:
        # "+" is the issuer's credit marker; "-" is a reversal, still a debit.
        if re.match(r"^\+", raw):
            is_credit = True
            raw = raw.lstrip("+")
        elif re.match(r"^-", raw):
            raw = raw.lstrip("-")
    # Only strip a leading "C" when it is the HDFC rupee glyph: a token that is
    # just "CR" is a credit marker, not an amount.
    raw = re.sub(rf"^{RUPEE_GLYPH}\s*(?=[\d])", "", raw)
    if allow_credit_suffix:
        m = re.match(r"^(.*?)\s*(CR|CR\.)$", raw, re.IGNORECASE)
        if m:
            raw, is_credit = m.group(1), True
    raw = raw.strip().replace(",", "")
    if not re.match(r"^-?\d+(\.\d+)?$", raw):
        return None, False
    try:
        # Credit limits are printed without decimals ("6,38,000"), so a bare
        # integer is valid here even though transactions always carry paise.
        return float(raw), is_credit
    except ValueError:
        return None, False


def _row_tokens(words, anchor_top, tolerance=ROW_TOLERANCE):
    """Every token on the visual row belonging to one date anchor."""
    return [w for w in words if abs(w["top"] - anchor_top) <= tolerance]


def _joined(words):
    """Joins word dicts (or plain strings) into one whitespace-cleaned string."""
    parts = [w["text"] if isinstance(w, dict) else str(w) for w in words]
    return _clean(" ".join(parts))


def _parse_date(text):
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y"):
        try:
            return pd.to_datetime(_clean(text), format=fmt)
        except (ValueError, TypeError):
            continue
    return pd.NaT


def _parse_hdfc_long_date(text):
    """'01 Sep, 2026' / '21 Sep, 2026' as printed in the HDFC summary block."""
    cleaned = _clean(text).replace(",", "")
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return pd.to_datetime(cleaned, format=fmt)
        except (ValueError, TypeError):
            continue
    return pd.NaT


# ---------------------------------------------------------------------------
# HDFC  (Regalia, Tata Neu Infinity, Diners)
# ---------------------------------------------------------------------------

# HDFC column bands. The two HDFC cards do NOT share a column layout: Tata Neu
# starts the date at x=25.5 while Regalia indents the whole table to x=169.5,
# a ~144pt shift. Hardcoding either would drop one card entirely, so the bands
# are derived from each page's own column header instead (see _hdfc_bands).
# These defaults are only the fallback when no header row is found.
HDFC_BANDS = {
    "date": (0, 100),
    "time": (100, 120),
    "desc": (120, 505),
    "rewards": (505, 522),
    "amount": (522, 562),
    "pi": (562, 600),
}


def _hdfc_bands(words, page_width):
    """
    Derives the column x-bands from the page's own table header.

    The header reads "DATE & TIME TRANSACTION DESCRIPTION [REWARDS] AMOUNT PI",
    but Tata Neu omits REWARDS (it prints "Base NeuCoins*" instead), so the
    description/rewards boundary has to fall back to the amount column. Getting
    that wrong lets the description band run past the amount column and swallow
    the value, so every boundary is clamped to stay ordered.
    """
    lines = {}
    for w in words:
        lines.setdefault(round(w["top"], 0), []).append(w)

    for top in sorted(lines):
        ws = sorted(lines[top], key=lambda w: w["x0"])
        text = " ".join(w["text"] for w in ws).upper()
        if "DATE" not in text or "AMOUNT" not in text or "DESCRIPTION" not in text:
            continue

        def x_of(label):
            for w in ws:
                if w["text"].upper().startswith(label):
                    return w["x0"]
            return None

        date_x = x_of("DATE")
        desc_x = x_of("TRANSACTION") or x_of("DESCRIPTION")
        rewards_x = x_of("REWARDS")
        amount_x = x_of("AMOUNT")
        pi_x = x_of("PI")
        if date_x is None or desc_x is None or amount_x is None:
            continue

        # Boundary between description and rewards. With no REWARDS header that
        # column is unlabelled, so stop short of the amount column by a margin
        # wide enough for the widest right-aligned value.
        desc_end = (rewards_x - 4) if rewards_x is not None else (amount_x - 30)
        desc_end = min(max(desc_end, desc_x + 20), amount_x - 8)
        amount_hi = (pi_x - 4) if pi_x is not None else page_width

        return {
            "date": (0, date_x + 40),
            "desc": (desc_x - 6, desc_end),
            "rewards": (desc_end, amount_x - 4),
            "amount": (amount_x - 30, amount_hi),
            "pi": (amount_hi, page_width),
        }
    return HDFC_BANDS



def parse_hdfc_card(pdf):
    """
    'dd/mm/yyyy| hh:mm  DESC  [+ N]  C amount  l'

    The description cell is vertically centred, so a wrapped description renders
    one line ABOVE the date anchor and the remainder below. Both are captured by
    the +/-5.5pt row tolerance and re-joined into one description.
    """
    rows, summary = [], {}
    # Rewards print as "+ 210" or a bare count. Matched by shape because the
    # column is unlabelled on the HDFC cards that use "Base NeuCoins*".
    reward_token = re.compile(r"^\+?\s*\d+$")

    for page_no, page in enumerate(pdf.pages, start=1):
        words = _words(page)
        if not words:
            continue
        if page_no == 1:
            summary.update(_hdfc_summary(page.extract_text() or ""))

        bands = _hdfc_bands(words, page.width)
        anchors = sorted(
            (w for w in words if HDFC_DATE_RE.match(w["text"])),
            key=lambda w: w["top"],
        )
        for anchor in anchors:
            if not bands["date"][0] <= anchor["x0"] < bands["date"][1]:
                continue
            row = _row_tokens(words, anchor["top"])

            # Time sits between the end of the date token and the description
            # column, so it is read relative to the anchor rather than from a
            # fixed band, which would clip it on the indented Regalia layout.
            time_text = _joined([w for w in row
                                 if w["x0"] >= anchor["x1"] and w["x0"] < bands["desc"][0]])

            desc_words = sorted(
                (w for w in row if bands["desc"][0] <= w["x0"] < bands["desc"][1]),
                key=lambda w: (round(w["top"], 0), w["x0"]),
            )
            desc = _joined(desc_words)

            amount, is_credit = None, False
            # Tata Neu prints a leading "+"/"-" as its OWN token, left of the
            # value. It carries the credit flag and nothing else, so it must be
            # read for that flag and then stepped over - trying to parse it as an
            # amount returns None and the loop would fall through to the bare
            # "C 498.00", turning every payment into a debit.
            sign_credit = None
            for w in sorted((w for w in row
                             if bands["amount"][0] <= w["x0"] < bands["amount"][1]),
                            key=lambda w: w["x0"]):
                token = w["text"]
                if token in ("+", "-"):
                    sign_credit = token == "+"
                    continue
                value, credit = parse_amount(token, allow_credit_suffix=True)
                if value is not None:
                    amount = value
                    is_credit = credit or bool(sign_credit)
                    break
            if not desc or amount is None:
                continue

            rewards = _joined([w["text"] for w in row
                               if bands["rewards"][0] <= w["x0"] < bands["rewards"][1]
                               and reward_token.match(w["text"])])
            rows.append({
                "Txn_Date": _parse_date(HDFC_DATE_RE.match(anchor["text"]).group(1)),
                "Txn_Time": time_text,
                "Description": desc,
                "Amount": amount,
                "Direction": "CREDIT" if is_credit else "DEBIT",
                "Rewards": rewards,
                "Statement_Category": None,
                "Page": page_no,
            })

    return rows, summary



def _hdfc_summary(page_text):
    """
    Cycle totals from the page-1 summary block.

    HDFC lays the block out as a two-row grid: every label first, then a line of
    bare values. Because the values are positional
    (PREVIOUS STATEMENT DUES, PAYMENTS RECEIVED, PURCHASES/DEBIT, FINANCE
    CHARGES) the line is read left to right rather than label-adjacent, which a
    per-label regex cannot do.
    """
    out = {}

    def grab(pattern, source):
        m = re.search(pattern, source, re.IGNORECASE)
        if not m:
            return None
        value, _ = parse_amount(m.group(1))
        return value

    # TOTAL AMOUNT DUE is printed on the line ABOVE the four-figure value line.
    # Not every statement lays the block out this way, so both are optional here
    # and a statement that matches neither simply reports no cycle totals rather
    # than failing the whole import.
    value_line = None
    value_line_idx = None
    for i, line in enumerate(page_text.splitlines()):
        amounts = re.findall(r"[C₹]?[\d,]+\.\d{2}", line)
        if len(amounts) >= 4 and "+" in line:
            value_line_idx = i
            value_line = amounts
            break

    if value_line:
        out["Previous_Dues"] = _val(value_line[0])
        out["Payments_Received"] = _val(value_line[1])
        out["Total_Spend"] = _val(value_line[2])
        out["Finance_Charges"] = _val(value_line[3])

    lines = page_text.splitlines()
    if value_line_idx is not None and value_line_idx > 0:
        above = re.findall(r"[C₹]?[\d,]+\.\d{2}", lines[value_line_idx - 1])
        if above:
            out["Total_Due"] = _val(above[-1])

    # The limits block is another two-row grid: the header line names the
    # columns and the two following lines carry, in order,
    #   [minimum due, due date] then [credit limit, available limit, cash limit].
    # Reading label-adjacent is impossible here, so it is read positionally.
    # Limits are printed WITHOUT decimals ("C6,38,000"), unlike the due figures,
    # so this deliberately allows the decimal part to be absent.
    limit_amount = r"[C₹]?[\d,]+(?:\.\d{2})?"
    for i, line in enumerate(lines):
        if "AVAILABLE CREDIT LIMIT" in line.upper():
            after = lines[i + 1: i + 4]
            if after:
                first = re.findall(limit_amount, after[0])
                if first:
                    out["Minimum_Due"] = _val(first[0])
                due = re.search(r"(\d{1,2}\s+\w{3},?\s*\d{4})", after[0])
                if due:
                    out["Due_Date"] = _parse_hdfc_long_date(due.group(1))
            if len(after) > 1:
                limits = re.findall(limit_amount, after[1])
                if len(limits) >= 1:
                    out["Credit_Limit"] = _val(limits[0])
                if len(limits) >= 2:
                    out["Available_Credit_Limit"] = _val(limits[1])
                if len(limits) >= 3:
                    out["Cash_Limit"] = _val(limits[2])
            break


    m = re.search(
        r"Billing Period\s*(\d{1,2}\s+\w{3},?\s*\d{4})\s*-\s*(\d{1,2}\s+\w{3},?\s*\d{4})",
        page_text, re.IGNORECASE)
    if m:
        out["Period_Start"] = _parse_hdfc_long_date(m.group(1))
        out["Period_End"] = _parse_hdfc_long_date(m.group(2))

    m = re.search(r"Statement Date\s*(\d{1,2}\s+\w{3},?\s*\d{4})", page_text, re.IGNORECASE)
    if m:
        out["Statement_Date"] = _parse_hdfc_long_date(m.group(1))

    out["Spend_Mix"] = _parse_spend_mix(page_text)
    return out


def _val(token):
    value, _ = parse_amount(token)
    return value



def _parse_spend_mix(page_text):
    """
    HDFC's statement-level category split, e.g.
        "l GROCERIES l RESTAURANT l PETROL l APPARELS l MISC" then "21% 19% ..."
    Labels and percentages sit on consecutive lines, so they are zipped.
    """
    block = re.search(r"Purchase Indicator\s*/\s*Insights.*?\n(.*?)(?:\n\s*\n|\Z)",
                      page_text, re.IGNORECASE | re.DOTALL)
    if not block:
        return {}
    body = block.group(1)
    labels = [_clean(x) for x in re.findall(r"\bl\s+([A-Z][A-Z ]*?)\s*(?=\bl\s|\d{1,3}%|\Z)", body)]
    pcts = [int(x) for x in re.findall(r"(\d{1,3})%", body)]
    if not labels or len(labels) != len(pcts):
        return {}
    return {label.title(): pct for label, pct in zip(labels, pcts) if label}


# ---------------------------------------------------------------------------
# ICICI  (Amazon Pay and siblings)
# ---------------------------------------------------------------------------

# The "25%" reward-rate column sits at x0=146, i.e. LEFT of the date anchor at
# x0=207.8, so rows are grouped by the date anchor and never by the left-most
# token on the line.
ICICI_BANDS = {
    "date": (190, 245),
    "ref": (245, 300),
    # The points column starts at x=450, so the description must stop before
    # it or the reward count is swallowed into the merchant name.
    "desc": (300, 445),
    "points": (445, 500),
    "amount": (500, 560),
}

# ICICI embeds the merchant category in the description itself:
#   "AMAZON PAY IN GROCERY BANGALORE IN"   -> GROCERY
# These are issuer-supplied and more reliable than keyword guessing.
ICICI_DESC_CATEGORY = re.compile(
    r"\bIN\s+(GROCERY|GROCERIES|SUPERMARKET|RESTAURANT|DINING|APPAREL|APPARELS|"
    r"FASHION|PHARMACY|HEALTHCARE|PETROL|FUEL|TRAVEL|AIR|HOTEL|TELECOM|BILL|"
    r"UTILITY|ENTERTAINMENT|BOOKS?|ELECTRONICS?|FURNISHING|EDUCATION|"
    r"INSURANCE|GAMING|CHARITY|STATIONERY)\b",
    re.IGNORECASE,
)

ICICI_CATEGORY_MAP = {
    "GROCERY": "Groceries", "GROCERIES": "Groceries", "SUPERMARKET": "Groceries",
    "RESTAURANT": "Food_Dining", "DINING": "Food_Dining",
    "APPAREL": "Shopping_Retail", "APPARELS": "Shopping_Retail", "FASHION": "Shopping_Retail",
    "PHARMACY": "Healthcare", "HEALTHCARE": "Healthcare",
    "PETROL": "Travel", "FUEL": "Travel", "TRAVEL": "Travel", "AIR": "Travel",
    "HOTEL": "Travel", "TELECOM": "Utilities_Bills", "BILL": "Utilities_Bills",
    "UTILITY": "Utilities_Bills", "ENTERTAINMENT": "Entertainment",
    "BOOK": "Education", "BOOKS": "Education", "EDUCATION": "Education",
    "ELECTRONIC": "Shopping_Retail", "ELECTRONICS": "Shopping_Retail",
    "FURNISHING": "Shopping_Retail", "INSURANCE": "Fees_Charges",
    "GAMING": "Entertainment", "CHARITY": "Gifts", "STATIONERY": "Shopping_Retail",
}


def parse_icici_card(pdf):
    """
    'dd/mm/yyyy  <11-digit ref>  DESCRIPTION  <points>  amount [CR]'

    Transactions live only on page 1; the remaining pages are terms and
    conditions containing illustrative tables, which have no date anchor at
    x=207 and so are skipped naturally.
    """
    rows, summary = [], {}

    for page_no, page in enumerate(pdf.pages, start=1):
        words = _words(page)
        if not words:
            continue
        if page_no == 1:
            summary.update(_icici_summary(page.extract_text() or ""))

        anchors = sorted((w for w in words if ICICI_DATE_RE.match(w["text"])),
                         key=lambda w: w["top"])
        for anchor in anchors:
            if not ICICI_BANDS["date"][0] <= anchor["x0"] < ICICI_BANDS["date"][1]:
                continue
            row = _row_tokens(words, anchor["top"], tolerance=3.0)

            desc = _joined([w for w in row
                            if ICICI_BANDS["desc"][0] <= w["x0"] < ICICI_BANDS["desc"][1]])
            ref = _joined([w for w in row
                           if ICICI_BANDS["ref"][0] <= w["x0"] < ICICI_BANDS["ref"][1]])
            points = _joined([w for w in row
                              if ICICI_BANDS["points"][0] <= w["x0"] < ICICI_BANDS["points"][1]])

            # The amount and a trailing "CR" marker are separate tokens in one
            # band. Both must be read: breaking on the amount first would miss
            # the credit flag and mark a refund as spend.
            amount, is_credit = None, False
            band_tokens = sorted(
                (w for w in row
                 if ICICI_BANDS["amount"][0] <= w["x0"] < ICICI_BANDS["amount"][1]),
                key=lambda w: w["x0"],
            )
            for w in band_tokens:
                value, credit = parse_amount(w["text"], allow_credit_suffix=True)
                if value is not None:
                    amount = value
                    is_credit = is_credit or credit
                elif w["text"].upper().startswith("CR"):
                    is_credit = True
            if not desc or amount is None:
                continue

            cat = ICICI_DESC_CATEGORY.search(desc)
            rows.append({
                "Txn_Date": _parse_date(ICICI_DATE_RE.match(anchor["text"]).group(1)),
                "Txn_Time": "",
                "Description": desc,
                "Amount": amount,
                "Direction": "CREDIT" if is_credit else "DEBIT",
                "Rewards": points,
                "Card_Ref": ref,
                "Statement_Category": ICICI_CATEGORY_MAP.get(cat.group(1).upper()) if cat else None,
                "Statement_Category_Raw": cat.group(1).upper() if cat else None,
                "Page": page_no,
            })

    return rows, summary


def _icici_summary(page_text):
    """Cycle totals. ICICI's headers are heavily spaced, so `\s*` is generous."""
    out = {}

    def grab(pattern):
        m = re.search(pattern, page_text, re.IGNORECASE)
        if not m:
            return None
        value, _ = parse_amount(m.group(1))
        return value

    out["Total_Due"] = grab(r"Total Amount due\s*[`\s]*([\d,]+\.\d{2})")
    out["Minimum_Due"] = grab(r"Minimum Amount due\s*[`\s]*([\d,]+\.\d{2})")
    out["Credit_Limit"] = grab(r"Credit Limit \(Including cash\)\s*[`\s]*([\d,]+\.\d{2})")
    out["Available_Credit_Limit"] = grab(
        r"Available Credit \(Including cash\)\s*[`\s]*([\d,]+\.\d{2})")
    out["Cash_Limit"] = grab(r"Cash Limit\s*[`\s]*([\d,]+\.\d{2})")

    m = re.search(r"Statement period\s*:\s*([A-Za-z]+ \d{1,2}, \d{4})\s*to\s*"
                  r"([A-Za-z]+ \d{1,2}, \d{4})", page_text, re.IGNORECASE)
    if m:
        out["Period_Start"] = pd.to_datetime(m.group(1), format="%B %d, %Y", errors="coerce")
        out["Period_End"] = pd.to_datetime(m.group(2), format="%B %d, %Y", errors="coerce")
        out["Statement_Date"] = out["Period_End"]

    m = re.search(r"PPAAYYMMEENNTT DDUUEE DDAATTEE\s*\n\s*([A-Za-z]+ \d{1,2}, \d{4})", page_text)
    if m:
        out["Due_Date"] = pd.to_datetime(m.group(1), format="%B %d, %Y", errors="coerce")

    out["Spend_Mix"] = {}
    return out


# ---------------------------------------------------------------------------
# SCAPIA (Federal Bank)
# ---------------------------------------------------------------------------

# SCAPIA packs the date and time into ONE token: "13-08-2026·21:21", where the
# separator is U+00B7 MIDDLE DOT (sometimes U+2022). The amount is a single
# right-aligned token at x=441. Verified on Scapia_August_2026.
SCAPIA_BANDS = {"desc": (165, 430), "amount": (430, 520)}


def parse_scapia_card(pdf):
    """
    'dd-mm-yyyy·hh:mm  DESCRIPTION  Rs445.00'

    SCAPIA prints no transaction table on the cover page; rows appear under a
    "Your Transactions" heading on the following pages.
    """
    rows, summary = [], {}

    for page_no, page in enumerate(pdf.pages, start=1):
        words = _words(page)
        if not words:
            continue
        if page_no == 1:
            summary.update(_scapia_summary(page.extract_text() or ""))

        anchors = sorted((w for w in words if SCAPIA_DATE_RE.match(w["text"])),
                         key=lambda w: w["top"])
        for anchor in anchors:
            row = _row_tokens(words, anchor["top"], tolerance=3.0)
            desc = _joined([w for w in row
                            if SCAPIA_BANDS["desc"][0] <= w["x0"] < SCAPIA_BANDS["desc"][1]])
            amount, is_credit = None, False
            for w in row:
                if not SCAPIA_BANDS["amount"][0] <= w["x0"] < SCAPIA_BANDS["amount"][1]:
                    continue
                amount, is_credit = parse_amount(w["text"], allow_credit_suffix=True)
                if amount is not None:
                    break
            if not desc or amount is None:
                continue

            m = SCAPIA_DATE_RE.match(anchor["text"])
            rows.append({
                "Txn_Date": _parse_date(m.group(1)),
                "Txn_Time": m.group(2),
                "Description": desc,
                "Amount": amount,
                "Direction": "CREDIT" if is_credit else "DEBIT",
                "Rewards": "",
                "Statement_Category": None,
                "Page": page_no,
            })

    return rows, summary


def _scapia_summary(page_text):
    """
    SCAPIA's cover page is typeset without spaces, and pdfplumber additionally
    hard-wraps mid-word ("Transact" / "ions"). All whitespace is therefore
    squashed away before matching, so labels are found intact.
    """
    out = {}
    squash = re.sub(r"\s+", "", page_text)

    def grab(pattern, source=None):
        m = re.search(pattern, source if source is not None else squash, re.IGNORECASE)
        if not m:
            return None
        value, _ = parse_amount(m.group(1))
        return value

    out["Total_Due"] = grab(r"TotalDueMinimumDue.*?₹([\d,]+\.\d{2})")
    out["Minimum_Due"] = grab(r"TotalDueMinimumDue₹[\d,]+\.\d{2}₹([\d,]+\.\d{2})")
    out["Previous_Dues"] = grab(r"Previousbalance₹([\d,]+\.\d{2})")
    out["Payments_Received"] = grab(r"Paymentsandrefunds\+?₹([\d,]+\.\d{2})")
    out["Total_Spend"] = grab(r"Transactions\+?₹([\d,]+\.\d{2})")
    out["Cash_Withdrawal"] = grab(r"Cashwithdrawal\+?₹([\d,]+\.\d{2})")
    out["Fees_And_Interest"] = grab(r"Feesandinterest\+?₹([\d,]+\.\d{2})")
    out["New_Balance"] = grab(r"Newbalance₹([\d,]+\.\d{2})")
    out["Available_Credit_Limit"] = grab(r"AvailableLimit₹([\d,]+\.\d{2})")
    out["Credit_Limit"] = grab(r"TotalLimit₹([\d,]+\.\d{2})")
    out["Cash_Limit"] = grab(r"Cashwithdrawallimit₹([\d,]+\.\d{2})")

    m = re.search(r"(\d{1,2}[A-Za-z]{3}\d{4})-(\d{1,2}[A-Za-z]{3}\d{4})", squash)
    if m:
        out["Period_Start"] = _parse_scapia_date(m.group(1))
        out["Period_End"] = _parse_scapia_date(m.group(2))

    # "StatementDate DueDate" is a header; the two dates follow it, but the
    # account-summary block is interleaved, so the scan has to look past it.
    m = re.search(r"StatementDateDueDate.*?(\d{1,2}[A-Za-z]{3}\d{4})"
                  r".*?(\d{1,2}[A-Za-z]{3}\d{4})", squash)
    if m:
        out["Statement_Date"] = _parse_scapia_date(m.group(1))
        out["Due_Date"] = _parse_scapia_date(m.group(2))

    out["Card_Token"] = (re.search(r"•(X{6,}\d{4})", squash) or [None, None])[1] \
        if re.search(r"•(X{6,}\d{4})", squash) else None
    out["Spend_Mix"] = {}
    return out



def _parse_scapia_date(text):
    """'21Jul2026' / '21 Aug 2026' as printed by SCAPIA (often space-stripped)."""
    cleaned = _clean(text)
    for fmt in ("%d%b%Y", "%d %b %Y", "%d%B%Y", "%d %B %Y"):
        try:
            return pd.to_datetime(cleaned, format=fmt)
        except (ValueError, TypeError):
            continue
    return pd.NaT


# ---------------------------------------------------------------------------
# Issuer detection + public entry point
# ---------------------------------------------------------------------------

# Order matters: SCAPIA's cover page mentions "Federal" and "Visa/Rupay" but
# not the other banks, and ICICI's T&C pages are long, so detection uses the
# first page only.
ISSUER_SIGNATURES = [
    ("SCAPIA", re.compile(r"SCAPIA", re.IGNORECASE)),
    ("ICICI", re.compile(r"ICICI\s+BANK", re.IGNORECASE)),
    ("HDFC", re.compile(r"HDFC\s+BANK", re.IGNORECASE)),
]

# Card product names, matched against the first page so the card can be
# identified without the user naming it.
CARD_PRODUCTS = [
    ("Tata Neu Infinity", re.compile(r"TATA\s+NEU\s+INFINITY", re.IGNORECASE)),
    ("Regalia Gold", re.compile(r"REGALIA", re.IGNORECASE)),
    ("Amazon Pay", re.compile(r"AMAZON\s*PAY", re.IGNORECASE)),
    ("Diners Club", re.compile(r"DINERS", re.IGNORECASE)),
]


def detect_issuer(first_page_text):
    for name, pattern in ISSUER_SIGNATURES:
        if pattern.search(first_page_text):
            return name
    return None


def detect_card_name(first_page_text, issuer, source_file=None):
    """
    Product name, falling back to the issuer so the card is still labelled.

    A masked HDFC statement often no longer prints the product name at all, and
    two cards from the same issuer would then be indistinguishable. The filename
    is used as a last resort because HDFC embeds the card's leading digits there
    ("4854XXXX..._848_masked.pdf"), which keeps the cards apart.
    """
    for name, pattern in CARD_PRODUCTS:
        if pattern.search(first_page_text):
            return name
    if issuer and issuer != "HDFC":
        return issuer
    stem = os.path.splitext(os.path.basename(str(source_file or "")))[0]
    digits = "".join(ch for ch in stem.split("_")[0] if ch.isdigit())
    return f"HDFC card ...{digits[-4:]}" if len(digits) >= 4 else (issuer or "Unknown card")


def detect_card_last4(first_page_text):
    """
    Best-effort last-4. Masked statements usually expose only the trailing
    digits, which is exactly what is wanted for identifying a card anyway.
    """
    patterns = [
        r"Credit Card No\.?\s*[:.]?\s*([\dX\*\. ]{6,30})",
        r"•\s*(X{6,}(\d{4}))\b",
    ]
    for pattern in patterns:
        m = re.search(pattern, first_page_text, re.IGNORECASE)
        if not m:
            continue
        token = m.group(1)
        tail = re.search(r"[X\*\.]{2,}\s*(\d{4})\b", token)
        if tail:
            return tail.group(1)
        digits = re.findall(r"\d", token)
        if len(digits) >= 4:
            return "".join(digits[-4:])
    return None



ADAPTERS = {
    "HDFC": parse_hdfc_card,
    "ICICI": parse_icici_card,
    "SCAPIA": parse_scapia_card,
}


def load_card_statement(file_source, filename=None):
    """
    Parses a credit-card statement PDF into (DataFrame, metadata).

    `file_source` may be a path or a binary stream. The returned DataFrame has
    one row per transaction using CREDIT_CARD_COLUMNS; the metadata dict carries
    the cycle totals, the detected card identity and any issuer-supplied
    category mix.

    Raises ValueError when the issuer is not recognised, so an unexpected
    format fails loudly rather than importing an empty ledger.
    """
    if pdfplumber is None:
        raise RuntimeError(
            "Credit-card PDF support requires 'pdfplumber'. Install with: pip install pdfplumber"
        )

    with pdfplumber.open(file_source) as pdf:
        if not pdf.pages:
            raise ValueError("The PDF has no pages.")

        # Issuer detection reads the cover first, then widens. Plenty of
        # statements print no bank name on page 1 (some name the city and dates
        # only), and failing those would discard months of history over a
        # detail that appears on page 2.
        first_text = pdf.pages[0].extract_text() or ""
        issuer = detect_issuer(first_text)
        scanned = 1
        if issuer is None:
            for page in pdf.pages[1:5]:
                issuer = detect_issuer(page.extract_text() or "")
                scanned += 1
                if issuer is not None:
                    break
        if issuer is None:
            raise ValueError(
                "Could not detect the card issuer in the first pages. "
                "Supported: HDFC, ICICI, SCAPIA (Federal)."
            )

        rows, summary = ADAPTERS[issuer](pdf)

    if not rows:
        raise ValueError(
            f"No transactions found in this {issuer} statement. "
            "The layout may differ from the ones verified in CreditCard/."
        )

    df = pd.DataFrame(rows)
    for col in CREDIT_CARD_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df[CREDIT_CARD_COLUMNS]

    # The source name is what identifies a card when the statement is masked and
    # exposes no card digits, so it must not come out empty for a plain path.
    if filename:
        source_name = filename
    elif isinstance(file_source, str):
        source_name = file_source
    else:
        source_name = getattr(file_source, "name", "")

    meta = {
        "Issuer": issuer,
        "Card_Name": detect_card_name(first_text, issuer, source_name),
        "Card_Last4": detect_card_last4(first_text),
        "Source_File": os.path.basename(source_name or ""),
        "Pages_Scanned_For_Issuer": scanned,
        "Txn_Count": len(df),
        "Total_Spend": round(
            float(df.loc[df["Direction"] == "DEBIT", "Amount"].sum()), 2
        ),
        "Total_Refunds": round(
            float(df.loc[df["Direction"] == "CREDIT", "Amount"].sum()), 2
        ),
    }
    meta.update(summary)
    return df, meta







