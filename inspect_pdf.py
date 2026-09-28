"""
inspect_pdf.py - dump a PDF statement's raw content exactly as it is stored.

Read-only diagnostic tool. Nothing is written, modified, or masked: the file is
opened and the extractors are printed so the actual layout of a statement can be
examined before a parser is written for it.

Usage:
    python inspect_pdf.py <file.pdf>
    python inspect_pdf.py <file.pdf> --mode text      # raw text only (default)
    python inspect_pdf.py <file.pdf> --mode words     # + word x/y coordinates
    python inspect_pdf.py <file.pdf> --mode tables    # + detected table grids
    python inspect_pdf.py <file.pdf> --mode chars     # + per-character detail
    python inspect_pdf.py <file.pdf> --mode all       # everything
    python inspect_pdf.py <file.pdf> --mode text --page 1
    python inspect_pdf.py <file.pdf> --mode all --json stats.json

Extraction paths are printed in this order under --mode all:
    TEXT   - pdfplumber, the same path the statement loaders use
    WORDS  - every word with its coordinates, for column-band work
    TABLES - pdfplumber table detection
    MUPDF  - PyMuPDF, an independent engine used to cross-check TEXT
    CHARS  - per-character detail including font size
"""

import argparse
import json
import os
import sys

try:
    import pdfplumber
except ImportError:
    print("ERROR: 'pdfplumber' is required. Install it with: pip install pdfplumber")
    sys.exit(1)

try:
    import pymupdf
except ImportError:
    pymupdf = None


def _page_range(spec, total):
    """Parses '1', '2,5', '1-3' or 'all' into a list of 0-based page indices."""
    spec = (spec or "all").strip().lower()
    if spec in ("", "all"):
        return list(range(total))
    pages = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, _, hi = part.partition("-")
            lo, hi = int(lo), int(hi)
            if lo > hi:
                lo, hi = hi, lo
            pages.extend(range(lo - 1, hi))
        else:
            pages.append(int(part) - 1)
    # Clamp and de-duplicate while preserving document order.
    seen, out = set(), []
    for p in pages:
        if 0 <= p < total and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _rule(title, char="-", width=78):
    print("\n" + char * width)
    print(title)
    print(char * width)


def dump_text(pdf, pages, layout=True):
    """Raw text, exactly as the PDF encodes it. No cleanup, no reordering."""
    _rule("TEXT  -  pdfplumber extract_text (layout preserved)")
    for i in pages:
        page = pdf.pages[i]
        text = page.extract_text(layout=layout) or ""
        print(f"\n----- PAGE {i + 1} / {len(pdf.pages)} -----")
        print(text if text.strip() else "(no extractable text on this page)")


def dump_words(pdf, pages):
    """Every word with its bounding box — the raw material for column bands."""
    _rule("WORDS  -  pdfplumber extract_words (x0, x1, top, bottom)")
    for i in pages:
        page = pdf.pages[i]
        words = page.extract_words() or []
        print(f"\n----- PAGE {i + 1} / {len(pdf.pages)}  ({len(words)} words) -----")
        for w in words:
            print(
                f"  x0={w['x0']:8.2f} x1={w['x1']:8.2f} "
                f"top={w['top']:8.2f} bot={w['bottom']:8.2f}  {w['text']}"
            )


def dump_tables(pdf, pages):
    """Detected table grids, plus their cells."""
    _rule("TABLES  -  pdfplumber find_tables / extract")
    for i in pages:
        page = pdf.pages[i]
        tables = page.find_tables()
        print(f"\n----- PAGE {i + 1} / {len(pdf.pages)}  ({len(tables)} table(s)) -----")
        for t_i, table in enumerate(tables):
            rows = table.extract()
            bbox = tuple(round(v, 2) for v in table.bbox)
            print(f"\n  --- table {t_i + 1}: bbox={bbox} rows={len(rows)} ---")
            for row in rows:
                cells = ["" if c is None else str(c).replace("\n", " ") for c in row]
                print("  | " + " | ".join(cells))


def dump_mupdf(pdf_path, pages):
    """Independent extraction, to confirm or contradict the pdfplumber text."""
    if pymupdf is None:
        _rule("MUPDF  -  not installed (pip install pymupdf)")
        print("  Skipped.")
        return
    _rule("MUPDF  -  PyMuPDF get_text (independent engine)")
    with pymupdf.open(pdf_path) as doc:
        for i in pages:
            if i >= doc.page_count:
                continue
            text = doc[i].get_text("text") or ""
            print(f"\n----- PAGE {i + 1} / {doc.page_count} -----")
            print(text if text.strip() else "(no extractable text on this page)")


def dump_chars(pdf, pages):
    """Per-character detail including font size — reveals headings and totals."""
    _rule("CHARS  -  pdfplumber extract_chars (text, size, font, colour)")
    for i in pages:
        page = pdf.pages[i]
        chars = page.chars or []
        print(f"\n----- PAGE {i + 1} / {len(pdf.pages)}  ({len(chars)} chars) -----")
        for c in chars:
            size = c.get("size", 0)
            font = c.get("fontname", "")
            rgb = c.get("non_stroking_color")
            print(
                f"  x0={c['x0']:8.2f} top={c['top']:8.2f} size={size:5.2f} "
                f"font={font:<28} color={rgb}  {c['text']!r}"
            )


def build_stats(pdf, pdf_path, pages, out_path=None):
    """Machine-readable summary, useful for comparing statements across issuers."""
    stats = {
        "file": os.path.basename(pdf_path),
        "pages": len(pdf.pages),
        "page_detail": [],
    }
    for i in pages:
        page = pdf.pages[i]
        words = page.extract_words() or []
        tables = page.find_tables()
        numeric = [w for w in words if w["text"].replace(",", "").replace(".", "").isdigit()]
        dates = [
            w["text"] for w in words
            if len(w["text"]) >= 8 and w["text"][2] == "/" and w["text"][5] == "/"
        ]
        stats["page_detail"].append({
            "page": i + 1,
            "width": round(page.width, 2),
            "height": round(page.height, 2),
            "word_count": len(words),
            "char_count": len(page.chars or []),
            "table_count": len(tables),
            "table_bboxes": [[round(v, 2) for v in t.bbox] for t in tables],
            "numeric_tokens": len(numeric),
            "date_like_tokens": dates[:5],
        })

    if pymupdf is not None:
        with pymupdf.open(pdf_path) as doc:
            stats["metadata"] = {k: str(v) for k, v in (doc.metadata or {}).items()}

    _rule("STATS  -  structural summary")
    print(json.dumps(stats, indent=2))

    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(stats, fh, indent=2)
        print(f"\n  Stats written to: {out_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Dump a PDF statement's raw content, exactly as stored.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("file", help="Path to the PDF file to inspect.")
    parser.add_argument(
        "--mode",
        default="text",
        choices=["text", "words", "tables", "chars", "all"],
        help="Which extractor(s) to print. Default: text",
    )
    parser.add_argument(
        "--page",
        default="all",
        help="Pages to dump: '1', '1,3', '1-4' or 'all' (default: all)",
    )
    parser.add_argument(
        "--no-layout",
        action="store_true",
        help="Disable layout-preserving text mode (words are not re-aligned).",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Also print a structural summary of the pages.",
    )
    parser.add_argument(
        "--json",
        metavar="PATH",
        default=None,
        help="Write the structural summary to this JSON file.",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.file):
        print(f"ERROR: file not found: {args.file}")
        sys.exit(1)
    if not args.file.lower().endswith(".pdf"):
        print(f"WARNING: {args.file} does not have a .pdf extension.")

    with pdfplumber.open(args.file) as pdf:
        print("=" * 78)
        print(f"FILE   : {args.file}")
        print(f"SIZE   : {os.path.getsize(args.file):,} bytes")
        print(f"PAGES  : {len(pdf.pages)}")
        _rule("INFO  -  document-level metadata")
        for key, value in (pdf.metadata or {}).items():
            print(f"  {key:<22}: {value}")

        pages = _page_range(args.page, len(pdf.pages))
        if not pages:
            print(f"ERROR: no valid pages selected from '{args.page}'.")
            sys.exit(1)
        if len(pages) < len(pdf.pages):
            print(f"\nShowing page(s): {', '.join(str(p + 1) for p in pages)}")

        if args.mode == "all":
            dump_text(pdf, pages, layout=not args.no_layout)
            dump_words(pdf, pages)
            dump_tables(pdf, pages)
            dump_mupdf(args.file, pages)
            dump_chars(pdf, pages)
        elif args.mode == "text":
            dump_text(pdf, pages, layout=not args.no_layout)
        elif args.mode == "words":
            dump_words(pdf, pages)
        elif args.mode == "tables":
            dump_tables(pdf, pages)
        elif args.mode == "chars":
            dump_chars(pdf, pages)

        if args.stats or args.json:
            build_stats(pdf, args.file, pages, out_path=args.json)


if __name__ == "__main__":
    main()
