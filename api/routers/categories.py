"""
Category endpoints — broad category CRUD and override rule management.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pandas as pd
from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.engine import Engine

from api.deps import get_engine
from db import (
    get_broad_categories,
    get_custom_broad_categories,
    get_sub_categories,
    add_broad_category,
    delete_broad_category,
    apply_category_rules,
    delete_category_rules,
    get_all_transactions_with_details,
)

router = APIRouter(prefix="/categories", tags=["categories"])


class AddCategoryRequest(BaseModel):
    name: str


class CategoryRule(BaseModel):
    rule_type: str   # "txn" | "merchant" | "narration"
    rule_key: str
    category: str
    # Optional leaf. When omitted the leaf is derived from `category`, so a rule
    # that only names a broad bucket leaves sub-categorisation to the parser.
    sub_category: Optional[str] = None


class ApplyRulesRequest(BaseModel):
    rules: List[CategoryRule]


class DeleteRulesRequest(BaseModel):
    rule_type: str
    rule_keys: List[str]


class PreviewRuleRequest(BaseModel):
    rule_type: str   # "txn" | "merchant" | "narration"
    rule_key: str


class ApplyCascadeRequest(BaseModel):
    rule_type: str   # "txn" | "merchant" | "narration"
    rule_key: str
    category: str
    sub_category: Optional[str] = None
    excluded_chq_refs: List[str] = []


def _safe_val(v):
    if v is None:
        return None
    try:
        import math
        if isinstance(v, float) and math.isnan(v):
            return None
    except Exception:
        pass
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def _df_to_records(df: pd.DataFrame) -> List[dict]:
    records = []
    for row in df.to_dict(orient="records"):
        records.append({k: _safe_val(v) for k, v in row.items()})
    return records


def _find_matching_transactions(df: pd.DataFrame, rule_type: str, rule_key: str) -> pd.DataFrame:
    if df.empty or not rule_key or not rule_key.strip():
        return df.iloc[0:0]
    
    key = rule_key.strip().upper()
    if rule_type == "txn":
        mask = df["Chq_Ref_Number"].astype(str).str.strip().str.upper() == key
    elif rule_type == "merchant":
        mask = df["Payee_Receiver"].astype(str).str.strip().str.upper().str.contains(key, regex=False, na=False)
    elif rule_type == "narration":
        mask = (
            df["Narration"].astype(str).str.strip().str.upper().str.contains(key, regex=False, na=False)
            | df["Details"].astype(str).str.strip().str.upper().str.contains(key, regex=False, na=False)
        )
    else:
        mask = pd.Series(False, index=df.index)
    return df[mask]


# ---------------------------------------------------------------------------
# GET /api/categories — all broad categories (built-in + user)
# ---------------------------------------------------------------------------
@router.get("")
def list_categories(engine: Engine = Depends(get_engine)):
    return get_broad_categories(engine)


# ---------------------------------------------------------------------------
# GET /api/categories/custom — only user-added categories
# ---------------------------------------------------------------------------
@router.get("/custom")
def list_custom_categories(engine: Engine = Depends(get_engine)):
    return get_custom_broad_categories(engine)


# ---------------------------------------------------------------------------
# GET /api/categories/sub — every sub-category (leaf) in the hierarchy
# ---------------------------------------------------------------------------
@router.get("/sub")
def list_sub_categories(engine: Engine = Depends(get_engine)):
    return get_sub_categories(engine)


# ---------------------------------------------------------------------------
# POST /api/categories — add a new category
# ---------------------------------------------------------------------------
@router.post("")
def create_category(body: AddCategoryRequest, engine: Engine = Depends(get_engine)):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Category name cannot be empty")
    result = add_broad_category(engine, name)
    if not result:
        raise HTTPException(status_code=400, detail="Failed to add category (name may be invalid)")
    return {"success": True, "name": name}


# ---------------------------------------------------------------------------
# DELETE /api/categories/{name} — delete a custom category
# ---------------------------------------------------------------------------
@router.delete("/{name}")
def remove_category(name: str, engine: Engine = Depends(get_engine)):
    result = delete_broad_category(engine, name)
    if result is False:
        raise HTTPException(status_code=400, detail=f"Cannot delete '{name}' — it is a built-in category")
    return {"success": True, "deleted": name}


# ---------------------------------------------------------------------------
# POST /api/categories/preview — preview transactions affected by a rule
# ---------------------------------------------------------------------------
@router.post("/preview")
def preview_rule_impact(body: PreviewRuleRequest, engine: Engine = Depends(get_engine)):
    df = get_all_transactions_with_details(engine)
    matched = _find_matching_transactions(df, body.rule_type, body.rule_key)
    cols = [
        "Chq_Ref_Number", "Date", "Narration", "Transaction_Type",
        "Broad_Category", "Payee_Receiver", "Debit_Amount", "Credit_Amount",
        "Closing_Balance"
    ]
    display_cols = [c for c in cols if c in matched.columns]
    return {
        "total": len(matched),
        "transactions": _df_to_records(matched[display_cols]),
    }


# ---------------------------------------------------------------------------
# POST /api/categories/rules — upsert override rules
# ---------------------------------------------------------------------------
@router.post("/rules")
def apply_rules(body: ApplyRulesRequest, engine: Engine = Depends(get_engine)):
    rules = [
        (r.rule_type, r.rule_key, r.category, r.sub_category)
        for r in body.rules
    ]
    applied = apply_category_rules(engine, rules)
    return {"success": True, "applied": applied}


# ---------------------------------------------------------------------------
# POST /api/categories/rules/apply-cascade — cascade rule with per-txn exclusions
# ---------------------------------------------------------------------------
@router.post("/rules/apply-cascade")
def apply_cascade_rules(body: ApplyCascadeRequest, engine: Engine = Depends(get_engine)):
    df = get_all_transactions_with_details(engine)
    rule_type = body.rule_type
    rule_key = body.rule_key.strip()
    category = body.category.strip()
    sub_category = (body.sub_category or "").strip() or None
    excluded_set = set(str(ref).strip().upper() for ref in body.excluded_chq_refs)

    if rule_type == "txn":
        rules = [("txn", rule_key, category, sub_category)]
        applied = apply_category_rules(engine, rules)
        return {"success": True, "applied": applied}

    matched = _find_matching_transactions(df, rule_type, rule_key)
    included_refs = [
        str(r).strip() for r in matched["Chq_Ref_Number"].tolist()
        if str(r).strip().upper() not in excluded_set
    ]

    # For narration rules, clear any old txn overrides on included transactions
    # so the new narration rule takes effect cleanly (matching the dashboard UX)
    if rule_type == "narration" and included_refs:
        delete_category_rules(engine, "txn", included_refs)

    rules = [(rule_type, rule_key, category, sub_category)]

    # For excluded transactions, pin their original category with a 'txn' override
    for chq in body.excluded_chq_refs:
        chq_str = str(chq).strip()
        orig_row = df[df["Chq_Ref_Number"].astype(str).str.strip().str.upper() == chq_str.upper()]
        if not orig_row.empty:
            orig_row = orig_row.iloc[0]
            orig_cat = orig_row["Broad_Category"] or "Uncategorized"
            # Pin the leaf too, otherwise the exclusion would drift to whatever
            # leaf the parser derives for its new parent.
            orig_sub = orig_row.get("Sub_Category") or orig_cat
            rules.append(("txn", chq_str, orig_cat, orig_sub))

    applied = apply_category_rules(engine, rules)
    return {"success": True, "applied": applied}


# ---------------------------------------------------------------------------
# POST /api/categories/rules/delete — delete specific rules by key
# ---------------------------------------------------------------------------
@router.post("/rules/delete")
def delete_rules(body: DeleteRulesRequest, engine: Engine = Depends(get_engine)):
    deleted = delete_category_rules(engine, body.rule_type, body.rule_keys)
    return {"success": True, "deleted": deleted}

