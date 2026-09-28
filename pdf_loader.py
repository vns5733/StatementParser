"""
PDF bank statement loader for HDFC (and similar) text-based statement PDFs.
Extracts the embedded transaction table into the standard 7-column schema
used by the rest of the pipeline (see config.REQUIRED_COLUMNS).

Primary path uses pdfplumber table detection. A word-coordinate fallback
reconstructs rows when table detection fails on a less-standard layout.
"""

import re
import bisect
import pandas as pd
from config import REQUIRED_COLUMNS

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")

COLUMN_BANDS = {
    "Date": (0, 70),
    "Narration": (70, 285),
    "Ref": (285, 400),
    "Value_Date": (400, 500),
    "Withdrawal": (500, 590),
    "Deposit": (590, 685),
    "Balance": (685, 950),
}

DEFAULT_COLUMN_ORDER = [
    "Date",
    "Narration",
    "Chq_Ref_Number",
    "Value_Date",
    "Debit_Amount",
    "Credit_Amount",
    "Closing_Balance",
]

HEADER_NAME_MAP = {
    "date": "Date",
    "narration": "Narration",
    "chqrefno": "Chq_Ref_Number",
    "chqref": "Chq_Ref_Number",
    "chequeref": "Chq_Ref_Number",
    "valuedate": "Value_Date",
    "valuedt": "Value_Date",
    "withdrawalamount": "Debit_Amount",
    "withdrawalamt": "Debit_Amount",
    "depositamount": "Credit_Amount",
    "depositamt": "Credit_Amount",
    "closingbalance": "Closing_Balance",
    "closingbal": "Closing_Balance",
}


def _normalize_name(value):
    return re.sub(r"[^a-z]", "", (value or "").strip().lower())


def _clean_cell(value):
    if value is None:
        return ""
    return str(value).strip()


def _clean_narration(value):
    if value is None:
        return ""
    text = re.sub(r"\s+", " ", str(value).replace("\n", " ")).strip()
    return text


def _normalize_table_rows(extracted):
    """
    Converts a raw pdfplumber table grid into standard transaction row dicts.
    Drops header rows and any non-transaction (summary/footer) rows.
    """
    if not extracted:
        return []

    header_idx = None
    normalized = [[_clean_cell(c) for c in row] for row in extracted]

    for i, row in enumerate(normalized):
        names = [_normalize_name(c) for c in row[:7]]
        if "date" in names and "narration" in names:
            header_idx = i
            break

    position_map = None
    if header_idx is not None:
        position_map = {}
        for pos, cell in enumerate(normalized[header_idx]):
            mapped = HEADER_NAME_MAP.get(_normalize_name(cell))
            if mapped is not None:
                position_map[pos] = mapped
        start = header_idx + 1
    else:
        start = 0

    rows = []
    for raw in normalized[start:]:
        if not any(raw):
            continue

        if position_map is not None:
            record = {}
            for pos, mapped in position_map.items():
                if pos < len(raw):
                    record[mapped] = raw[pos]
        else:
            record = {}
            for pos, mapped in enumerate(DEFAULT_COLUMN_ORDER):
                if pos < len(raw):
                    record[mapped] = raw[pos]

        record["Date"] = record.get("Date", "")
        record["Narration"] = _clean_narration(record.get("Narration"))

        if not _DATE_RE.match(record["Date"]):
            continue

        for col in DEFAULT_COLUMN_ORDER:
            record.setdefault(col, "")

        rows.append(record)

    return rows


def _page_table_rows(page):
    best = []
    try:
        tables = page.find_tables()
    except Exception:
        tables = []

    for table in tables:
        try:
            extracted = table.extract()
        except Exception:
            continue
        rows = _normalize_table_rows(extracted)
        if len(rows) > len(best):
            best = rows
    return best


def _band_of(word):
    x0 = word["x0"]
    for name, (lo, hi) in COLUMN_BANDS.items():
        if lo <= x0 < hi:
            return name
    return None


def _cluster_lines(words, tolerance=4.0):
    lines = []
    for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(word["top"] - lines[-1]["top"]) <= tolerance:
            lines[-1]["words"].append(word)
        else:
            lines.append({"top": word["top"], "words": [word]})
    return lines


def _fallback_page_rows(page):
    """
    Reconstructs transaction rows from word coordinates when pdfplumber
    cannot detect the table. Uses the measured column x-bands and anchors
    each row on the line carrying both the Date and Value Date tokens.
    """
    words = page.extract_words()
    lines = _cluster_lines(words)

    anchors = []
    for line in lines:
        tokens = {"Date": None, "Value_Date": None, "Ref": None,
                  "Withdrawal": None, "Deposit": None, "Balance": None}
        for word in line["words"]:
            band = _band_of(word)
            if band in tokens and tokens[band] is None:
                tokens[band] = word["text"]
        if tokens["Date"] is None or not _DATE_RE.match(tokens["Date"]):
            continue
        if tokens["Value_Date"] is None or not _DATE_RE.match(tokens["Value_Date"]):
            continue
        anchor = {"top": line["top"], "narr_words": []}
        anchor.update(tokens)
        anchors.append(anchor)

    if not anchors:
        return []

    head_cap = 30.0
    tail_cap = 12.0
    narr_tokens = []
    for line in lines:
        line_bands = [(_band_of(w), w) for w in line["words"]]
        date_labels = {w["text"] for b, w in line_bands if b == "Date"}
        narr_labels = {w["text"] for b, w in line_bands if b == "Narration"}
        if "Date" in date_labels and "Narration" in narr_labels:
            continue
        if line["top"] < anchors[0]["top"] - head_cap:
            continue
        if line["top"] > anchors[-1]["top"] + tail_cap:
            continue
        for band, word in line_bands:
            if band == "Narration":
                narr_tokens.append(word)

    tops = [a["top"] for a in anchors]
    for word in narr_tokens:
        idx = bisect.bisect_left(tops, word["top"])
        if idx == 0:
            nearest = 0
        elif idx == len(tops):
            nearest = len(tops) - 1
        else:
            nearest = idx if (tops[idx] - word["top"]) < (word["top"] - tops[idx - 1]) else idx - 1
        anchors[nearest]["narr_words"].append(word)

    rows = []
    for anchor in anchors:
        narr_words = sorted(anchor["narr_words"], key=lambda w: (w["top"], w["x0"]))
        narration = ""
        if narr_words:
            narration = _clean_narration(" ".join(w["text"] for w in narr_words))
        rows.append({
            "Date": anchor["Date"],
            "Narration": narration,
            "Chq_Ref_Number": anchor["Ref"] or "",
            "Value_Date": anchor["Value_Date"],
            "Debit_Amount": anchor["Withdrawal"] or "0.00",
            "Credit_Amount": anchor["Deposit"] or "0.00",
            "Closing_Balance": anchor["Balance"] or "",
        })

    return rows


def extract_pdf_transactions(file_source, filename=None):
    """
    Loads transaction rows from a text-based HDFC statement PDF.
    Accepts a filepath (str) or a file-like object (e.g. a FastAPI UploadFile).

    Returns a pandas DataFrame with the standard REQUIRED_COLUMNS columns.
    """
    if pdfplumber is None:
        raise RuntimeError(
            "PDF support requires 'pdfplumber'. Install it with: pip install pdfplumber"
        )

    with pdfplumber.open(file_source) as pdf:
        rows = []
        for page in pdf.pages:
            page_rows = _page_table_rows(page)
            if not page_rows:
                page_rows = _fallback_page_rows(page)
            rows.extend(page_rows)

    if not rows:
        raise ValueError(
            "Could not locate a transaction table in the PDF statement file."
        )

    return pd.DataFrame(rows, columns=REQUIRED_COLUMNS)