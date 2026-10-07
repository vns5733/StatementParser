import re
import pandas as pd
from category_rules import assign_broad_category, assign_sub_category


# ---------------------------------------------------------------------------
# Bare card-descriptor parsing
#
# A card statement prints one un-delimited line per purchase:
#
#     MAXWARE TECHNOLOGIES PRIVBANGALORE 3732
#     BOUTIQUE BALI SWING HO BADUNG IDR 1751000.00 48
#     VERANDALEARINGCHENNAI + 176
#
# There is no "UPI-" / "IMPS-" prefix to split on, so the fallback branch used to
# leave Payee_Receiver null. That was not merely cosmetic: `assign_broad_category`
# matches merchant rules against the payee, `db._mark_recurring` keys recurrence on
# it, and the insights endpoint filters its top-merchants list on it. A null payee
# therefore disabled all three at once, and every one of these rows landed in
# Uncategorized. On the development data the correlation was exact - all 124
# Uncategorized rows had a null payee, and no Uncategorized row had one.
#
# The city is matched as a SUFFIX, not a token, because the issuer strips the space
# between the merchant and the city ("...PRIV" + "BANGALORE" -> "PRIVBANGALORE").
# ---------------------------------------------------------------------------

# Trailing noise: the Tata Neu credit marker, a foreign-amount pair, and a plain
# terminal/reference number. The list is a PRIORITY order and is re-applied until
# the string stops shrinking, because the order varies by issuer and each step can
# expose the next: "BADUNG IDR 1751000.00 48" ends in a number whose removal exposes
# the amount, so a single pass would either miss the amount or mistake it for the
# reference. The marker must precede the digit rule, or "+ 176" loses its 176.
_CARD_TAIL = (
    re.compile(r"\s*\+\s*\d+\s*$"),                              # "+ 176"
    re.compile(r"\s+(?:IDR|USD|EUR|GBP|AED|THB|SGD|MYR|JPY|CNY)\s*[\d,]+(?:\.\d+)?\s*$", re.I),
    re.compile(r"\s+[\d,]{1,12}(?:\.\d+)?\s*$"),               # " 3732"
)
_CARD_MAX_TAIL_PASSES = 4

# Suffixes observed on real statements, longest first so "NEW DELHI" wins over "DELHI".
_CARD_CITIES = (
    "NEW DELHI", "SAN FRANCISCO", "BENGALURU", "BANGALORE", "GURGAON", "NOIDA",
    "MUMBAI", "PUNE", "DELHI", "COCHIN", "ERNAKULAM", "THANE", "LUDHIANA",
    "CHENNAI", "HYDERABAD", "AHMEDABAD", "KOLKATA", "JAIPUR", "TRIVANDRUM",
    "KOZHIKODE", "PATHANAMTH", "ALAPPUZHA", "LITHIRUVALLA", "DAPPALLI", "KOLLAM",
    "LONAVALA", "BADUNG", "DENPASAR", "GIANYAR", "KUTA", "SEMINYAK",
)
_CARD_CITY_RE = re.compile(r"(?:%s)\s*$" % "|".join(re.escape(c) for c in _CARD_CITIES), re.I)


def parse_card_descriptor(narration):
    """
    Splits a bare card descriptor into (merchant, city, reference).

    Deliberately conservative: anything it cannot confidently read comes back as
    `None`, because a wrong merchant is worse than a missing one - a wrong payee
    would silently satisfy a merchant rule and mis-file the row. It returns the
    merchant with its corporate suffix intact ("MAXWARE TECHNOLOGIES PRIV"), which
    is what a merchant rule should match on anyway.
    """
    text = narration.strip()
    if not text:
        return None, None, None

    ref = None
    for _ in range(_CARD_MAX_TAIL_PASSES):
        stripped = False
        for pattern in _CARD_TAIL:
            m = pattern.search(text)
            if m and m.start() > 0:             # must leave a merchant behind
                # Keep the first tail seen: that is the terminal/reference the
                # issuer printed, the amount and the credit marker are noise.
                ref = ref or m.group(0).strip()
                text = text[: m.start()].strip()
                stripped = True
                break
        if not stripped:
            break

    city = None
    m = _CARD_CITY_RE.search(text)
    if m and m.start() > 0:                     # must leave a merchant behind
        city = m.group(0).strip().upper()
        text = text[: m.start()].strip()

    # A descriptor that is nothing but digits or punctuation carries no merchant.
    if not text or not re.search(r"[A-Z]{3}", text.upper()):
        return None, city, ref

    return text.upper(), city, ref


def parse_narration(narration, debit_amount=None, credit_amount=None):
    """
    Parses a single bank narration into structured components:
    Transaction_Type, Details, Reference_ID, Payee_Receiver, Date_Range, Remarks, Other_Info,
    plus a purpose-level Broad_Category (Salary, Rent, Investment, ...) and a
    finer Sub_Category within it (Rent -> Residential_Rent / Rent_Brokerage / ...).
    """
    components = {
        "Transaction_Type": None,
        "Details": None,
        "Reference_ID": None,
        "Payee_Receiver": None,
        "Date_Range": None,
        "Remarks": None,
        "Other_Info": None,
        "Broad_Category": None,
        "Sub_Category": None,
    }
    if not isinstance(narration, str) or not narration.strip():
        components["Transaction_Type"] = "UNKNOWN"
        components["Broad_Category"] = "Uncategorized"
        components["Sub_Category"] = "Uncategorized"
        return components

    narration = narration.strip()

    if narration.startswith("UPIRET-"):
        parts = narration.split("-")
        components["Transaction_Type"] = "UPI_RETURN"
        components["Reference_ID"] = parts[1] if len(parts) > 1 else None
        components["Details"] = "UPI Return / Refund"
        components["Remarks"] = parts[2] if len(parts) > 2 else None
    elif narration.startswith("REV-UPI-"):
        parts = narration.split("-")
        components["Transaction_Type"] = "UPI_RETURN"
        components["Reference_ID"] = parts[1] if len(parts) > 1 else None
        components["Details"] = "UPI Reversal"
        components["Payee_Receiver"] = parts[2] if len(parts) > 2 else None
    elif narration.startswith("UPI-") or narration.startswith("UPI/"):
        parts = narration.split("-")
        components["Transaction_Type"] = "UPI"
        components["Payee_Receiver"] = parts[1] if len(parts) > 1 else None
        components["Details"] = parts[2] if len(parts) > 2 else None
        components["Reference_ID"] = parts[-2] if len(parts) > 3 else None
        components["Remarks"] = parts[-1] if len(parts) > 1 and "PHONE" in parts[-1] else None
    elif "ATM FEES" in narration or "NWD" in narration or narration.startswith("ATW-") or narration.startswith("EAW-") or "MICRO ATM CASH W/D" in narration:
        components["Transaction_Type"] = "ATM_WITHDRAWAL"
        match = re.search(r"(\d{6}) (\d{6})", narration)
        if match:
            components["Date_Range"] = f"{match.group(1)} to {match.group(2)}"
        parts = narration.split("-")
        components["Reference_ID"] = parts[-1] if len(parts) > 1 else None
        components["Details"] = parts[1] if len(parts) > 2 else narration
        components["Remarks"] = parts[2] if len(parts) > 2 else None
    elif "MARKUP" in narration or "POS" in narration:
        components["Transaction_Type"] = "INTL_POS/MARKUP"
        match = re.search(r"(\d{6}) (\d{6})", narration)
        if match:
            components["Date_Range"] = f"{match.group(1)} to {match.group(2)}"
        components["Reference_ID"] = narration.split("-")[-1] if "-" in narration else None
    elif "RD INSTALLMENT" in narration or "RD THROUGH MOBILE" in narration or "MATURED RD" in narration:
        components["Transaction_Type"] = "RD"
        if "MATURED RD" in narration:
            components["Details"] = "Matured RD Transfer"
            components["Reference_ID"] = narration.split(" ")[-1] if " " in narration else None
        else:
            components["Details"] = narration.split("-")[1] if "-" in narration else None
            components["Payee_Receiver"] = narration.split(":")[-1] if ":" in narration else None
    elif "FD THROUGH" in narration or "IB FD" in narration or "FD PREMAT" in narration:
        components["Transaction_Type"] = "FD"
        components["Details"] = narration.split("-")[1] if "-" in narration else None
        components["Payee_Receiver"] = narration.split(":")[-1] if ":" in narration else None
    elif re.search(r"\bEMI\b", narration) and "CHQ" in narration:
        components["Transaction_Type"] = "EMI"
        parts = narration.split()
        emi_idx = next((i for i, p in enumerate(parts) if p == "EMI"), None)
        components["Reference_ID"] = parts[emi_idx + 1] if emi_idx is not None and len(parts) > emi_idx + 1 else None
        chq_parts = narration.split("CHQ")
        components["Details"] = chq_parts[0].strip() if chq_parts else narration
        components["Other_Info"] = chq_parts[1].strip() if len(chq_parts) > 1 else None
    elif narration.startswith("FT-") or "IB FUNDS TRANSFER" in narration:
        components["Transaction_Type"] = "FUND_TRANSFER"
        parts = narration.split("-")
        components["Reference_ID"] = parts[1].strip() if len(parts) > 1 else None
        components["Payee_Receiver"] = parts[2].strip() if len(parts) > 2 else None
        components["Details"] = parts[-1].strip() if len(parts) > 3 else None
    elif "IMPS" in narration or "NEFT" in narration or "RTGS" in narration:
        components["Transaction_Type"] = "FUND_TRANSFER"
        parts = narration.split("-")
        components["Reference_ID"] = parts[1] if len(parts) > 1 else None
        components["Payee_Receiver"] = parts[2] if len(parts) > 2 else None
        components["Details"] = parts[-1] if len(parts) > 3 else None
    elif "NET BANKING SI" in narration:
        components["Transaction_Type"] = "STANDING_INSTRUCTION"
        parts = narration.split("-")
        components["Reference_ID"] = parts[0].strip() if len(parts) > 0 else None
        components["Details"] = parts[1].strip() if len(parts) > 1 else narration
        components["Payee_Receiver"] = parts[-1].strip() if len(parts) > 2 else None
    elif "IB BILLPAY" in narration or "BILLPAY" in narration or re.search(r"ZHDF\d+/BILLD", narration):
        components["Transaction_Type"] = "BILLPAY"
        parts = narration.split("-")
        components["Details"] = parts[0].strip()
        components["Payee_Receiver"] = parts[1] if len(parts) > 1 else None
        components["Reference_ID"] = parts[2] if len(parts) > 2 else None
    elif narration.startswith("RFX "):
        components["Transaction_Type"] = "FOREX_REMITTANCE"
        match = re.search(r"RFX\s+(\S+)\s+([A-Z]{3})([\d\.]+)@([\d\.]+)", narration)
        if match:
            components["Reference_ID"] = match.group(1)
            components["Other_Info"] = f"Currency: {match.group(2)}, ForeignAmt: {match.group(3)}, Rate: {match.group(4)}"
        components["Details"] = narration
    elif "IGST" in narration or "GST" in narration:
        components["Transaction_Type"] = "TAX_GST"
        components["Details"] = narration
        parts = narration.split(" ")
        components["Reference_ID"] = parts[0] if len(parts) > 0 else None
    elif "-TPT-" in narration or narration.startswith("TPT-"):
        components["Transaction_Type"] = "TPT_TRANSFER"
        parts = narration.split("-")
        components["Details"] = "Third Party Transfer"
        components["Reference_ID"] = parts[0] if len(parts) > 0 else None
        components["Payee_Receiver"] = parts[-1] if len(parts) > 1 else None
    elif "INSTA ALERT CHARG" in narration or "ALERT CHG" in narration:
        components["Transaction_Type"] = "BANK_CHARGES"
        match = re.search(r"\(([^)]+)\)", narration)
        components["Details"] = narration
        components["Remarks"] = match.group(1) if match else None
        match_ref = re.search(r"([A-Z]{3}\d{10,})", narration)
        components["Reference_ID"] = match_ref.group(1) if match_ref else None
    elif "INTEREST PAID" in narration or "CREDIT INTEREST CAPITALISED" in narration:
        components["Transaction_Type"] = "INTEREST"
        if "TILL" in narration:
            components["Remarks"] = narration.split("TILL")[-1].strip()
        elif "CAPITALISED" in narration:
            components["Details"] = "Interest Capitalised (Credit)"
        else:
            components["Remarks"] = narration
    elif "DIV" in narration:
        components["Transaction_Type"] = "DIVIDEND"
        components["Payee_Receiver"] = narration.split(" ")[1] if len(narration.split(" ")) > 1 else None
    elif "MFSS" in narration or "BSE-" in narration or "FF-" in narration:
        components["Transaction_Type"] = "MUTUAL_FUND"
        parts = narration.split("-")
        components["Reference_ID"] = parts[0].strip() if len(parts) > 0 else None
        components["Payee_Receiver"] = parts[1].strip() if len(parts) > 1 else None
        components["Details"] = "-".join(parts[2:]).strip() if len(parts) > 2 else None
    elif narration.startswith("ACH"):
        components["Transaction_Type"] = "ACH"
        components["Details"] = narration.split("-")[1] if "-" in narration else None
        components["Reference_ID"] = narration.split("-")[-1] if "-" in narration else None
    elif "PAY*" in narration or "UPILITE" in narration:
        components["Transaction_Type"] = "UPI"
        components["Details"] = narration
        parts = narration.split("-")
        components["Payee_Receiver"] = parts[0].strip() if len(parts) > 1 else None
        components["Reference_ID"] = parts[1].strip() if len(parts) > 2 else None
    else:
        components["Transaction_Type"] = "OTHER"
        components["Details"] = narration
        # A bare card descriptor ("MAXWARE TECHNOLOGIES PRIVBANGALORE 3732") has no
        # prefix to split on, so the merchant has to come from the descriptor itself.
        # Without this the payee stayed null, which disabled merchant rules,
        # recurrence detection and the top-merchants chart for every card row.
        payee, city, card_ref = parse_card_descriptor(narration)
        if payee:
            components["Payee_Receiver"] = payee
            if city:
                components["Remarks"] = city
            if card_ref:
                components["Reference_ID"] = card_ref

    has_debit = bool(debit_amount) and float(debit_amount) > 0
    has_credit = bool(credit_amount) and float(credit_amount) > 0
    components["Broad_Category"] = assign_broad_category(
        narration=narration,
        transaction_type=components["Transaction_Type"],
        details=components["Details"],
        payee_receiver=components["Payee_Receiver"],
        reference_id=components["Reference_ID"],
        has_debit=has_debit,
        has_credit=has_credit,
    )
    components["Sub_Category"] = assign_sub_category(
        broad_category=components["Broad_Category"],
        narration=narration,
        details=components["Details"],
        payee_receiver=components["Payee_Receiver"],
        reference_id=components["Reference_ID"],
    )

    return components


def parse_narrations_dataframe(transaction_df):
    """
    Given a transaction dataframe containing 'Narration' and 'Chq_Ref_Number',
    returns a dataframe with structured narration details mapped to 'Chq_Ref_Number'.
    """
    if "Narration" not in transaction_df.columns:
        raise ValueError("Transaction DataFrame must contain a 'Narration' column")

    debits = transaction_df["Debit_Amount"].tolist() if "Debit_Amount" in transaction_df.columns else [None] * len(transaction_df)
    credits = transaction_df["Credit_Amount"].tolist() if "Credit_Amount" in transaction_df.columns else [None] * len(transaction_df)
    details = [
        parse_narration(n, debit_amount=d, credit_amount=c)
        for n, d, c in zip(transaction_df["Narration"], debits, credits)
    ]
    narration_df = pd.DataFrame(details)
    narration_df["Chq_Ref_Number"] = transaction_df["Chq_Ref_Number"].values
    return narration_df
