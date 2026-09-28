import os
import uuid
import pandas as pd
from config import REQUIRED_COLUMNS
from pdf_loader import extract_pdf_transactions


def load_and_clean_statement(file_source, filename=None):
    """
    Loads and cleans bank statement data from CSV, XLS, or XLSX.
    Accepts a filepath (str) or a file-like object (such as a FastAPI UploadFile).

    Dynamically locates header row, extracts transactions, normalizes column names,
    formats dates, standardizes amounts, and assigns deterministic UUIDs to dummy
    reference numbers ('000000000000000' or empty).
    """
    if isinstance(file_source, str):
        if not os.path.exists(file_source):
            raise FileNotFoundError(f"Statement file not found: {file_source}")
        ext = os.path.splitext(file_source)[1].lower()
    else:
        # File-like object (e.g., FastAPI upload)
        name = filename or getattr(file_source, "name", "")
        ext = os.path.splitext(name)[1].lower()

    if ext in [".xls", ".xlsx"]:
        engine_name = "xlrd" if ext == ".xls" else "openpyxl"
        raw_df = pd.read_excel(file_source, header=None, engine=engine_name)

        # 1. Locate header row dynamically (look for row containing 'Date' and 'Narration')
        header_idx = None
        for i in range(min(50, len(raw_df))):
            row_vals = [str(x).strip() for x in raw_df.iloc[i].dropna().tolist()]
            if "Date" in row_vals and any(
                col in row_vals for col in ["Narration", "Description", "Particulars"]
            ):
                header_idx = i
                break

        if header_idx is None:
            raise ValueError("Could not locate transaction header row in statement file.")

        raw_headers = [str(x).strip() for x in raw_df.iloc[header_idx].values]

        # 2. Find start of transaction rows (skip following separator rows like '********')
        start_idx = header_idx + 1
        while start_idx < len(raw_df):
            row_str = raw_df.iloc[start_idx].astype(str)
            if row_str.str.contains(r"^\*+$").all() or raw_df.iloc[start_idx].isna().all():
                start_idx += 1
            else:
                break

        # 3. Find end of transaction rows (stop before summary or footer markers)
        end_idx = len(raw_df)
        for i in range(start_idx, len(raw_df)):
            first_val = str(raw_df.iloc[i, 0]).strip()
            row_str = raw_df.iloc[i].astype(str)
            if (
                raw_df.iloc[i].isna().all()
                or row_str.str.contains(r"^\*+$").all()
                or "STATEMENT SUMMARY" in first_val
                or "End Of Statement" in first_val
                or "Generated On:" in first_val
            ):
                end_idx = i
                break

        df = raw_df.iloc[start_idx:end_idx].copy().reset_index(drop=True)
        df.columns = raw_headers

    elif ext == ".csv":
        df = pd.read_csv(file_source)
    elif ext == ".pdf":
        df = extract_pdf_transactions(file_source, filename=filename)
    else:
        raise ValueError(f"Unsupported statement file format: {ext}")

    # Standardize column mapping to database schema
    column_mapping = {}
    for col in df.columns:
        clean_col = str(col).strip()
        col_lower = (
            clean_col.lower()
            .replace(" ", "")
            .replace("_", "")
            .replace(".", "")
            .replace("/", "")
        )

        if col_lower == "date":
            column_mapping[col] = "Date"
        elif col_lower in ["narration", "description", "particulars"]:
            column_mapping[col] = "Narration"
        elif col_lower in ["chqrefno", "chqrefnumber", "chequerefno", "chqno", "referenceno"]:
            column_mapping[col] = "Chq_Ref_Number"
        elif col_lower in ["valuedt", "valuedate", "valdate"]:
            column_mapping[col] = "Value_Date"
        elif col_lower in [
            "withdrawalamt",
            "withdrawalamount",
            "debitamount",
            "debitamt",
            "withdrawal",
        ]:
            column_mapping[col] = "Debit_Amount"
        elif col_lower in [
            "depositamt",
            "depositamount",
            "creditamount",
            "creditamt",
            "deposit",
        ]:
            column_mapping[col] = "Credit_Amount"
        elif col_lower in ["closingbalance", "balance"]:
            column_mapping[col] = "Closing_Balance"

    df.rename(columns=column_mapping, inplace=True)

    # Ensure required target columns exist
    for req in REQUIRED_COLUMNS:
        if req not in df.columns:
            df[req] = None

    # Filter to standard columns
    df = df[REQUIRED_COLUMNS].copy()

    # Strip whitespace from string values
    for col in df.columns:
        if df[col].dtype == "object":
            df[col] = df[col].apply(lambda x: str(x).strip() if pd.notna(x) else x)

    # Convert Date and Value_Date to datetime
    for date_col in ["Date", "Value_Date"]:
        df[date_col] = df[date_col].map(_parse_statement_date)

    # Clean and convert numeric columns
    for num_col in ["Debit_Amount", "Credit_Amount", "Closing_Balance"]:
        df[num_col] = (
            pd.to_numeric(df[num_col].astype(str).str.replace(",", ""), errors="coerce")
            .fillna(0.0)
        )

    # Replace dummy/empty reference numbers ('000000000000000', empty, None) with deterministic UUIDs
    # based on transaction fingerprint to guarantee idempotency across multiple loads.
    def resolve_ref_number(row):
        val = str(row["Chq_Ref_Number"]).strip() if pd.notna(row["Chq_Ref_Number"]) else ""
        if val in ["", "000000000000000", "nan", "None"]:
            fingerprint = f"{row['Date']}_{row['Narration']}_{row['Debit_Amount']:.2f}_{row['Credit_Amount']:.2f}_{row['Closing_Balance']:.2f}"
            return str(uuid.uuid5(uuid.NAMESPACE_OID, fingerprint))
        return val

    df["Chq_Ref_Number"] = df.apply(resolve_ref_number, axis=1)

    return df


def _parse_statement_date(value):
    """
    Parses a single statement date cell into a pandas Timestamp.
    Accepts dd/mm/YYYY, dd/mm/yy, ISO strings, and already-converted Timestamps.
    """
    if isinstance(value, pd.Timestamp) or pd.isna(value):
        return value
    text = str(value).strip()
    if not text:
        return pd.NaT
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return pd.to_datetime(text, format=fmt)
        except (ValueError, TypeError):
            continue
    return pd.to_datetime(text, errors="coerce", dayfirst=True)


def clean_csv_data(file_path):
    """
    Backwards-compatible wrapper around load_and_clean_statement.
    """
    return load_and_clean_statement(file_path)
