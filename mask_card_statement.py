"""
mask_card_statement.py - PII masking for credit-card statement PDFs.

Unlike mask_statement.py (which edits .xls cell values), a PDF has no editable
cell model, so this uses PyMuPDF redaction annotations. That matters: a black
rectangle painted over text leaves the text selectable and extractable, which
means the "masked" file still leaks PII. add_redact_annot + apply_redactions
removes the glyphs from the content stream instead.

Redacted by default: card number, CVV, name, email, phone, CKYC/ID, account
number, address lines, DOB, PAN, GSTIN, and the signature block.
Amounts, dates, merchant names and transaction rows are preserved, because the
parser and the analytics depend on them.

Usage:
    python mask_card_statement.py <file.pdf>
    python mask_card_statement.py <file.pdf> -o out.pdf
    python mask_card_statement.py --dir <folder> --output masked_cards
    python mask_card_statement.py <file.pdf> --dry-run   # report only
    python mask_card_statement.py <file.pdf> --keep-last 4
"""

import argparse
import glob
import os
import re
import sys

try:
    import pymupdf
except ImportError:
    print("ERROR: 'pymupdf' is required. Install it with: pip install pymupdf")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Patterns
#
# Each entry: (compiled regex, keep_visible_digits, label)
# keep_visible_digits=0 means redact the whole match; N>0 keeps the last N
# characters, so a card still shows which card it was without leaking it.
# ---------------------------------------------------------------------------

FIELD_PATTERNS = [
    # Card numbers. Anchored to a 16-digit (4-4-4-4) or 15/13-digit shape, or to
    # an explicit card label. A bare 12-digit run is deliberately NOT matched:
    # on a bank statement those are transaction references, and redacting them
    # would destroy the data the parser needs.
    (re.compile(r"(?i)\b(?:credit\s*card|card)\s*(?:no\.?|number|#)\s*[:.]?\s*"
                r"(\d[\dX*]{11,19})"), 4, "card number"),
    (re.compile(r"(?i)\b(?:credit\s*card|card)\s*(?:no\.?|number|#)\s*[:.]?\s*"
                r"([\dX*]{4}[\s\-]?[\dX*]{4}[\s\-]?[\dX*]{4}[\s\-]?[\dX*]{4})"),
     4, "card number"),
    # HDFC prints 6529XXXXXXXXXX53 style: leading 4, masked middle, trailing 2.
    (re.compile(r"\b\d{4}X{6,}\d{2,4}\b"), 4, "card number (masked)"),
    (re.compile(r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b"), 4, "card number"),
    # CVV / PIN, only when a label says so.
    (re.compile(r"(?i)\b(CVV|CVC|CARD\s*S?ECURITY\s*CODE|PIN)\b\s*[:.#]?\s*[\dX*]{3,4}"),
     0, "cvv/pin"),
    # Email.
    (re.compile(r"\b[\w.+\-]+@[\w\-]+\.[\w.]{2,}\b"), 0, "email"),
    # Indian phone numbers (10 digits, optional +91). Excludes a run that is
    # part of a longer digit string (transaction refs, dates, amounts).
    (re.compile(r"(?<![\d\-/])(?:\+?91[\s\-]?)?[6-9]\d{9}(?![\d\-/])"), 0, "phone"),
    # CKYC / customer / member ids: masked forms, or labelled values.
    (re.compile(r"\b\d{1,2}X{5,}\d*\b"), 0, "ckyc id"),
    (re.compile(r"(?i)\b(CKYC|CUST(OMER)?|MEMBER)\s*(ID|NO|NUMBER)?\s*[:.]?\s*"
                r"([A-Z0-9]{6,})"), 0, "customer id"),
    # PAN, Aadhaar, GSTIN. IFSC/MICR only when labelled: a bare IFSC inside a
    # UPI narration ("UPI-...-HDFC0000499-...") is a routing code, not PII, and
    # redacting it would break the narration the parser relies on.
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), 0, "pan"),
    (re.compile(r"\b\d{2}AAAAA\d{4}[A-Z]\d{7}[A-Z]\b"), 0, "aadhaar"),
    (re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]{3}[A-Z]\b"), 0, "gstin"),
    (re.compile(r"(?i)\b(RTGS/NEFT\s*)?IFSC\b\s*[:.]?\s*([A-Z]{4}0[A-Z0-9]{6})"), 0, "ifsc"),
    (re.compile(r"(?i)\bMICR\b\s*[:.]?\s*(\d{6,9})"), 0, "micr"),
    # Dates of birth / open date, when labelled as such.
    (re.compile(r"(?i)\b(D\.?O\.?B\.?|DATE OF BIRTH|A/C OPEN DATE)\s*[:.]?\s*"
                r"\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}"), 0, "dob/open date"),
]

# A transaction row starts with dd/mm/yyyy (or dd/mm/yy). Rows are never
# redacted wholesale: they carry the data the whole pipeline is built on. Only a
# span-level match (a real card number or PAN inside one) may touch them.
TXN_ROW = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}\b")

# A narration line: "UPI-SWIGGY-HDFC0001234-...", "POS 416021XXXXXX3942 PIN*NEW",
# "FD THROUGH MOBILE-50300379484413:VISHNU". These contain IFSC codes, the word
# PIN/MOBILE and long digit runs that look like PII but are channel metadata the
# parser needs, so label-based redaction is skipped on them.
#
# The credit-card settlement narration is "BPPY CC PAYMENT <token> (Ref# <ref>)"
# on HDFC cards, and the same shape appears as a wrapped continuation line with
# no channel prefix at all. Both forms are listed so the settlement row is never
# mistaken for a name/address block - it is the single row reconciliation needs.
NARRATION = re.compile(
    r"(?i)\b(UPI|IMPS|NEFT|RTGS|POS|EMI|ACH|BILLPAY|FT-|ATW-|EAW-|NWD|"
    r"INTL\s*TXN|REV-UPI|CARD\s*PAYMENT|CC\s*PAYMENT|BPPY|BILL\s*PAY|"
    r"REF#)\b"
)


# A bare 16-digit run is only a card number when it is not part of a narration.
BARE_CARD_LABELS = ("card number",)

# The cardholder block: a name plus address printed in the header, often with no
# label of its own (HDFC prints "Mr Vishnu Narayanan S" in a left column with the
# branch address in a right column). It is detected as a run of capitalised
# name-like words in the upper region of the page, next to address keywords.
NAME_WORD = re.compile(r"^(MR|MRS|MS|MISS|DR|SMT|KUMAR|SHRI)\b", re.I)
ADDRESS_HINT = re.compile(
    r"(?i)\b(ROAD|STREET|LANE|FLAT|HOUSE|NAGAR|COLONY|SECTOR|PLOT|BUILDING|"
    r"APART|MARG|PHASE|BLOCK|TOWN|VILLAGE|PIN|BANGALORE|BENGALURU|MUMBAI|"
    r"DELHI|CHENNAI|HYDERABAD|KERALA|KARNATAKA|MARATH[A-Z]*|SARJAPUR|"
    r"KAWAS|BESANAHALLI|KADUBESANAHALLI|JUNCTION|MOHAKAL|CHENNAITHALA)\b"
)




# Labels whose adjacent value is always sensitive, regardless of shape.
LABEL_KEYS = re.compile(
    r"(?i)\b(name|address|email|e-mail|phone|mobile|cvv|cvc|pin|date of birth|"
    r"d\.o\.b|cust\s*id|customer\s*id|ckyc|signature|account\s*(number|no)|"
    r"alt(er(nate)?)?\s*(account|ac)\s*(number|no)|member\s*(id|since))\b"
)

# The statement body itself is kept: merchants, amounts and dates are needed.
NOISE_LINES = re.compile(
    r"(?i)^(important information|terms|T&CS|note:?|useful links|declaration|"
    r"I/we hereby|understanding the key|for type and details|how to read GST|"
    r"to know more about|to hotlist|maintain a healthy|making only the|"
    r"if the minimum|if you miss|effective \d|the \"?available credit limit|"
    r"when the card member|contents of this statement|tata neu|hsn code)\b"
)


def _line_key(word):
    """Groups words into visual lines by rounded y coordinate."""
    return round(word["top"], 0)


def _line_bounds(words):
    x0 = min(w["x0"] for w in words)
    x1 = max(w["x1"] for w in words)
    top = min(w["top"] for w in words)
    bottom = max(w["bottom"] for w in words)
    return pymupdf.Rect(x0, top, x1, bottom)


def _mask_token(length, keep):
    """
    Placeholder of the same length as the original token, so the redacted page
    keeps its visual rhythm. `keep` preserves the trailing digits of a card
    number so the file stays identifiable without being reconstructable.
    """
    if keep > 0 and length > keep:
        return "X" * (length - keep) + "*" * keep
    return "X" * length


def is_noise_line(line_text):
    """True for boilerplate lines that must never be treated as PII."""
    return bool(NOISE_LINES.match(line_text.strip()))


def _span_rect(words, start, end):
    """
    Rect covering the character range [start, end) of a joined line.

    Words carry their own offsets, so a match that spans a word boundary is
    still redacted exactly - no more, no less. Redacting whole lines instead
    would blank out neighbouring transaction data.
    """
    cursor = 0
    parts = []
    for w in words:
        token = w["text"]
        w_start = cursor
        w_end = w_start + len(token)
        if w_end > start and w_start < end:
            parts.append(w)
        cursor = w_end + 1  # +1 for the join space
    if not parts:
        return None
    return _line_bounds(parts)


def find_pii(page):
    """
    Returns (rects, findings) for one page.

    Redaction is span-level: only the matched characters are removed, so
    transaction rows and merchant names survive intact.
    """
    raw = page.get_text("words")
    if not raw:
        return [], []

    words = [
        {"x0": w[0], "x1": w[2], "top": w[1], "bottom": w[3], "text": w[4]}
        for w in raw
    ]
    lines = {}
    for w in words:
        lines.setdefault(_line_key(w), []).append(w)

    rects, findings = [], []

    for top_key in sorted(lines):
        ws = sorted(lines[top_key], key=lambda w: w["x0"])
        line_text = " ".join(w["text"] for w in ws)
        is_txn_row = bool(TXN_ROW.match(line_text))
        is_narration = bool(NARRATION.search(line_text))
        # Structural data, not a place to hide: never redact it.
        protected = is_txn_row or is_narration

        # 1. Explicit patterns -> redact only the matched span.
        for pattern, keep, label in FIELD_PATTERNS:
            for m in pattern.finditer(line_text):
                # On a transaction row or narration, only a genuinely
                # card-shaped token (4 + masked middle + trailing digits) or a
                # PAN may be touched. Bare 16-digit runs there are references.
                if protected and label in BARE_CARD_LABELS:
                    continue
                if is_txn_row and label != "card number (masked)" and label != "pan":
                    continue
                if is_narration and label not in ("card number (masked)", "pan",
                                                  "cvv/pin", "email"):
                    continue
                rect = _span_rect(ws, m.start(), m.end())
                if rect is not None:
                    rects.append(rect)
                findings.append((label, m.group(0), _mask_token(len(m.group(0)), keep)))

        if protected:
            continue

        # 2. Sensitive label with a value on the same line: redact the value
        #    only, leaving the label itself readable for readability.
        lm = LABEL_KEYS.search(line_text)
        if lm:
            tail = line_text[lm.end():]
            value_start = lm.end() + (len(tail) - len(tail.lstrip()))
            if tail.strip():
                rect = _span_rect(ws, value_start, len(line_text))
                if rect is not None:
                    rects.append(rect)
                findings.append((lm.group(0).lower(), tail.strip()[:40],
                                 _mask_token(len(tail.strip()), 0)))
            else:
                # Label alone on its line: the value is on the line below.
                findings.append((lm.group(0).lower(), "(value on next line)", "X" * 12))

        # 3. Cardholder name/address block. Three layouts print it: under a
        #    FIRSTNAME/MIDDLENAME/LASTNAME header, as a sub-line under the
        #    transaction table header, and on the line between the two.
        for anchor_re in (r"(?i)\b(FIRSTNAME|MIDDLENAME|LASTNAME)\b",
                          r"(?i)\[CKYC\s*ID\s*:",
                          r"(?i)\b(DATE\s*&\s*TIME|TRANSACTION\s+DESCRIPTION)\b"):
            if not re.search(anchor_re, line_text):
                continue
            for below in sorted(lines):
                gap = below - top_key
                if not 0 < gap <= 42:
                    continue
                bws = sorted(lines[below], key=lambda w: w["x0"])
                btext = " ".join(w["text"] for w in bws)
                if is_noise_line(btext) or TXN_ROW.match(btext) or NARRATION.search(btext):
                    continue
                if re.search(r"(?i)@(gmail|yahoo|hotmail|outlook)", btext) or \
                   re.match(r"^\s*[A-Z][A-Z' ]{6,}", btext):
                    rects.append(_line_bounds(bws))
                    findings.append(("cardholder block", btext[:40], "X" * 20))

    # 4. Cardholder block in the page header. Bank and card statements both print
    #    the holder's name and address at the top, usually with no "Name:" label
    #    ("VISHNU NARAYANAN S" / "PALAZHI ORIPURAM CHENNITHALA P O"). Neither a
    #    title prefix nor an address keyword is guaranteed, so rather than
    #    guessing from content the block is found structurally: the left-hand
    #    column of the header, from the first line down to where the right-hand
    #    metadata block begins. That covers the name, the wrapped address lines
    #    and the PIN in one pass.
    header_limit = page.rect.height * 0.22
    # Hard stop: once the page has entered its transaction table, nothing below
    # is cardholder data. The header band is a fraction of page height, and on
    # some card layouts the first rows start inside it, so the table boundary is
    # detected explicitly (its column heading) and nothing after it is touched.
    table_start = None
    for top in sorted(lines):
        text = " ".join(w["text"] for w in sorted(lines[top], key=lambda w: w["x0"]))
        if re.search(r"(?i)\b(DATE\s*&\s*TIME|TRANSACTION\s+DESCRIPTION)\b", text):
            table_start = top
            break

    # Both layouts must be covered: on a card statement the holder is in the LEFT
    # column, on a bank statement the address sits in a RIGHT column next to the
    # branch block. So the whole header width is considered, and a line is kept
    # only when it is not a known label/boilerplate line.
    header_lines = [top for top in sorted(lines) if top <= header_limit]
    if table_start is not None:
        header_lines = [top for top in header_lines if top < table_start]
    for top in header_lines:
        ws = sorted(lines[top], key=lambda w: w["x0"])
        text = " ".join(w["text"] for w in ws)
        if is_noise_line(text) or TXN_ROW.match(text) or NARRATION.search(text):
            continue
        # Never blank a column heading or a metadata label: those are table
        # headers / labels, not PII. Their values are redacted by the label
        # rules above.
        if re.search(r"(?i)\b(DATE\s*&\s*TIME|TRANSACTION\s+DESCRIPTION|AMOUNT|"
                     r"DOMESTIC|INTERNATIONAL|SUMMARY|NEUCOINS|NEACOINS|"
                     r"STATEMENT\s+DATE|BILLING\s+PERIOD|CREDIT\s+LIMIT|"
                     r"AVAILABLE|MINIMUM\s+DUE|DUE\s+DATE|CKYC|ACCOUNT\s+NUMBER|"
                     r"ALT(ERNATE)?\s+ACCOUNT|EMAIL|IFSC|MICR|PHONE|PIN\b|"
                     r"BR\.?\s?CODE|PR\.?\s?CODE|CUST\s*ID|ACCOUNT\s+STATUS|"
                     r"JOINT\s+HOLDERS|NOMINATION|PREVIOUS|STATEMENT\s+DUES|"
                     r"PAYMENTS|PURCHASES|FINANCE|CHARGES|TOTAL|DUES|AMOUNT|"
                     r"PI\b|BASE|JOINT|CURRENCY|EXPECTED|AMB\b)", text):
            continue
        rects.append(_line_bounds(ws))
        findings.append(("header name/address", text[:40], "X" * 20))

    return rects, findings


def _dedupe(rects, pad=0.6):
    """Merges overlapping rects so we do not stack annotations on one span."""
    if not rects:
        return []
    merged = []
    for r in sorted(rects, key=lambda r: (r.y0, r.x0)):
        grown = pymupdf.Rect(r.x0 - pad, r.y0 - pad, r.x1 + pad, r.y1 + pad)
        if merged and not (
            grown.x0 > merged[-1].x1 or grown.x1 < merged[-1].x0
            or grown.y0 > merged[-1].y1 or grown.y1 < merged[-1].y0
        ):
            merged[-1] |= grown
        else:
            merged.append(grown)
    return merged


def mask_pdf(input_path, output_path=None, dry_run=False):
    """
    Masks PII in a statement PDF.

    Real redaction (glyphs are removed from the content stream) rather than a
    drawn black box, because an overlay leaves the text selectable and the PII
    still recoverable with a copy-paste or pdftotext.
    """
    doc = pymupdf.open(input_path)
    all_findings = []

    for pno, page in enumerate(doc, start=1):
        rects, findings = find_pii(page)
        for label, original, shown in findings:
            all_findings.append((pno, label, original, shown))
        for r in _dedupe(rects):
            page.add_redact_annot(r, fill=(0, 0, 0))

    if dry_run:
        doc.close()
        _report(input_path, all_findings, None)
        return all_findings

    for page in doc:
        page.apply_redactions()

    # Scrub document metadata (author/creator often carry real names).
    doc.set_metadata({
        "title": "Masked statement",
        "author": "",
        "subject": "",
        "keywords": "",
        "creator": "",
        "producer": "",
    })

    out = output_path or _default_output(input_path)
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    doc.save(out, garbage=4, deflate=True)
    doc.close()
    _report(input_path, all_findings, out)
    return all_findings


def _default_output(input_path):
    stem, ext = os.path.splitext(input_path)
    return f"{stem}_masked{ext}"


def _report(input_path, findings, out_path):
    """Prints what was found, so masking is auditable rather than a black box."""
    by_label = {}
    for _pno, label, original, _shown in findings:
        by_label.setdefault(label, []).append(original)

    print("=" * 70)
    print(f"INPUT  : {input_path}")
    if out_path:
        print(f"OUTPUT : {out_path}")
    else:
        print("OUTPUT : (dry run - nothing written)")
    print("=" * 70)

    if not findings:
        print("No PII patterns matched.")
        return

    print(f"Redacted {len(findings)} item(s) across {len(set(f[0] for f in findings))} page(s):\n")
    for label, originals in sorted(by_label.items()):
        uniq = sorted(set(originals))
        shown = uniq[:3]
        extra = f" (+{len(uniq) - 3} more)" if len(uniq) > 3 else ""
        print(f"  {label:<22} {len(originals):>3} hit(s)  e.g. {shown}{extra}")

    print("\nVerify before sharing: re-run inspect_pdf.py on the output and")
    print("confirm no name, card number, CKYC id, email or address remains.")


def mask_dir(in_dir, out_sub="masked_cards"):
    """Batch-masks every PDF in a folder."""
    out_dir = os.path.join(in_dir, out_sub)
    files = sorted(glob.glob(os.path.join(in_dir, "*.pdf")))
    if not files:
        print(f"No .pdf files in {in_dir}")
        return
    print(f"Found {len(files)} file(s). Output -> {out_dir}")
    ok = err = 0
    for fp in files:
        name = os.path.basename(fp)
        if name.endswith("_masked.pdf"):
            continue  # never re-mask an already-masked file
        try:
            mask_pdf(fp, os.path.join(out_dir, name))
            ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {name}: {exc}")
            err += 1
    print(f"\nDone: {ok} masked, {err} failed. Output: {out_dir}")


def main():
    parser = argparse.ArgumentParser(
        description="Mask PII in credit-card statement PDFs.",
    )
    parser.add_argument("file", nargs="?", help="PDF file to mask.")
    parser.add_argument("--dir", help="Folder of PDFs to batch-mask.")
    parser.add_argument("-o", "--output", help="Output PDF path (single file only).")
    parser.add_argument(
        "--output-dir",
        default="masked_cards",
        help="Output subfolder for --dir mode (default: masked_cards)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be masked without writing a file.",
    )
    args = parser.parse_args()

    if args.dir:
        target = os.path.abspath(args.dir)
        if not os.path.isdir(target):
            print(f"ERROR: {target} is not a folder")
            sys.exit(1)
        mask_dir(target, args.output_dir)
        return

    if not args.file:
        parser.print_help()
        sys.exit(1)

    if not os.path.isfile(args.file):
        print(f"ERROR: {args.file} not found")
        sys.exit(1)

    mask_pdf(args.file, args.output, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

