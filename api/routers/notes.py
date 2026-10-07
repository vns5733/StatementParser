"""
Notes and category suggestions.

Two features that share a subject — one specific transaction — and nothing else:

  /api/notes    free-text notes the user attaches to a transaction, plus bulk
                writes, because triaging 200 rows one save at a time is not triage
  /api/llm      category suggestions from the user's own opencode server

They are mounted from one module because the interesting behaviour is at the
junction: accepting a suggestion writes BOTH a category rule and a note, in one
action. Splitting them across two routers would put that transaction behind one of
them and leave the other half implied.

Nothing here decides a category. /llm/suggest returns proposals; only the user
turns one into a `category_rules` row, through the same cascade the dashboard
already uses.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.engine import Engine

import db
import llm_client
from api.deps import get_engine
from config import LLM_SUGGEST_MAX_ROWS

notes_router = APIRouter(prefix="/notes", tags=["notes"])
llm_router = APIRouter(prefix="/llm", tags=["llm"])

# The suggestion row payload. `note` is optional and separate from the note
# endpoints on purpose: accepting a suggestion should not silently overwrite text
# the user already wrote, and applying a note should not have to carry a category.
SUGGESTION_COLUMNS = [
    "Chq_Ref_Number", "Date", "Narration", "Payee_Receiver", "Transaction_Type",
    "Broad_Category", "Sub_Category", "Category_Direction", "Debit_Amount",
    "Credit_Amount", "Details", "Reference_ID", "Account_Source",
]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class NoteWrite(BaseModel):
    """One note for one or many transactions."""
    chq_refs: List[str]
    # null clears the note. Not "" - an empty string and no note are different
    # states, and "" is what a textarea holding nothing actually contains.
    note: Optional[str] = None
    # Stored alongside the note so a rejected proposal is still explainable later.
    suggestion: Optional[str] = None
    source: str = "user"


class NotesDelete(BaseModel):
    chq_refs: List[str]


class SuggestRequest(BaseModel):
    chq_refs: List[str]
    description: Optional[str] = None
    # Overrides the DB cap for a one-off large sweep. Unbounded by default on
    # purpose: silently truncating to 100 and reporting success for the first 100
    # is worse than a slow request.
    max_rows: Optional[int] = None


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

@notes_router.get("")
def list_notes(chq_refs: List[str] = Body(..., embed=True), engine: Engine = Depends(get_engine)):
    """
    Returns stored notes for the given references.

    POST with a body rather than a query string: a selection can be hundreds of
    250-character references, which is past what belongs in a URL.
    """
    return db.get_notes(engine, chq_refs)


@notes_router.post("")
def write_note(body: NoteWrite, engine: Engine = Depends(get_engine)):
    """
    Writes one note across every reference in the body.

    This is the single-transaction path and the bulk path: one row selected and
    three hundred both arrive here. Batching per-selection is what makes "note all
    of these" one action rather than three hundred.
    """
    if not body.chq_refs:
        raise HTTPException(status_code=400, detail="chq_refs cannot be empty")
    note = body.note if body.note is None else body.note.strip() or None
    try:
        written = db.set_notes(
            engine, body.chq_refs, note=note,
            suggestion=body.suggestion, source=body.source or "user",
        )
    except ValueError as exc:
        # A reference that does not exist is a client bug (a stale selection), not
        # a server fault, so it is a 400 and the message names the offender.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "written": written, "cleared": note is None}


@notes_router.post("/delete")
def delete_notes(body: NotesDelete, engine: Engine = Depends(get_engine)):
    """Removes the note row outright, including any stored suggestion."""
    deleted = db.clear_notes(engine, body.chq_refs)
    return {"success": True, "deleted": deleted}


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

@llm_router.get("/status")
def llm_status():
    """
    Whether a suggestion can be requested at all, and why not if it cannot.

    Exists so the button is disabled with a reason instead of failing on click.
    A user who has not started `opencode serve` should not have to read a 503 to
    work out that they have not started it.
    """
    return llm_client.server_status()


@llm_router.post("/suggest")
def suggest_categories(body: SuggestRequest, engine: Engine = Depends(get_engine)):
    """
    Suggests a category for each referenced transaction, plus a one-line note.

    The taxonomy handed to the model is the user's own `category_definitions`,
    including each category's direction. Suggesting from the model's idea of what
    a category means, while the UI shows the user's definition, is how a
    suggestion and the screen it was made on come to describe different things.

    Returns suggestions in request order, and never a bare count: rows the model
    skipped come back marked `skipped`, because a row missing from the panel reads
    as "nothing to change here", which is a different claim from "the model did not
    answer".
    """
    if not body.chq_refs:
        raise HTTPException(status_code=400, detail="chq_refs cannot be empty")

    refs = [str(r).strip() for r in body.chq_refs if str(r or "").strip()]
    if not refs:
        raise HTTPException(status_code=400, detail="chq_refs cannot be empty")

    cap = body.max_rows or LLM_SUGGEST_MAX_ROWS
    if cap and len(refs) > cap:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{len(refs)} rows requested but the cap is {cap}. The prompt grows "
                "with every row and past a few hundred the model starts dropping "
                "entries, which would look like rows the tool ignored. Narrow the "
                "selection, or raise LLM_SUGGEST_MAX_ROWS."
            ),
        )

    frame = db.get_all_transactions_with_details(engine)
    if frame.empty:
        raise HTTPException(status_code=404, detail="No transactions loaded")

    wanted = {ref.upper(): ref for ref in refs}
    scoped = frame[frame["Chq_Ref_Number"].astype(str).str.upper().isin(wanted)]
    if scoped.empty:
        raise HTTPException(status_code=404, detail="None of those references exist")

    taxonomy = [
        {
            "name": d["name"],
            "description": d["description"],
            "direction": d["direction"],
            "examples": d["examples"],
        }
        for d in db.get_category_definitions(engine)
    ]
    # Only rows that already have a name can be suggested for, and a category with
    # no definition cannot be proposed — the model would be guessing at it.
    taxonomy = [t for t in taxonomy if t["name"]]

    rows = []
    for _, row in scoped.iterrows():
        amount = float(row.get("Debit_Amount") or 0)
        rows.append({
            "id": str(row["Chq_Ref_Number"]),
            "date": str(row.get("Date"))[:10],
            "narration": row.get("Narration") or "",
            "payee": row.get("Payee_Receiver") or "",
            "transaction_type": row.get("Transaction_Type") or "",
            "side": "DEBIT" if amount > 0 else "CREDIT",
            "amount": amount if amount > 0 else float(row.get("Credit_Amount") or 0),
            "current_category": row.get("Broad_Category") or "Uncategorized",
            # Surfaced so the model can respect the direction rule rather than
            # rediscover it from the narration.
            "category_direction": row.get("Category_Direction") or "BOTH",
        })

    try:
        suggestions = llm_client.suggest(rows, taxonomy, body.description)
    except llm_client.LLMUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except llm_client.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    by_id = {s["id"]: s for s in suggestions}
    returned = {sid for sid in by_id if not by_id[sid].get("skipped")}

    # Only rows the model actually answered are returned with their source data.
    # A skipped row would otherwise carry a payload with nothing in it.
    payload_rows = []
    for rid in by_id:
        match = scoped[scoped["Chq_Ref_Number"].astype(str) == rid]
        if match.empty:
            continue
        payload_rows.append(_row_record(match.iloc[0]))

    return {
        "count": len(rows),
        "answered": len(returned),
        "suggestions": suggestions,
        "transactions": payload_rows,
        "model": llm_client.server_status().get("model"),
    }


def _row_record(row):
    record = {}
    for col in SUGGESTION_COLUMNS:
        if col in row.index:
            value = row[col]
            if hasattr(value, "isoformat"):
                value = value.isoformat()
            elif isinstance(value, float) and value != value:
                value = None
            record[col] = value
    return record