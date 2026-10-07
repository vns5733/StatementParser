"use client";

import { useEffect, useRef, useState } from "react";

import type { Transaction } from "@/types";

/**
 * A transaction's note, editable in place.
 *
 * Shared by TransactionTable and DrilldownPanel rather than written twice. Those
 * two tables list the same rows for the same reason, and a note that could be
 * written in one and not the other would make the missing one look like a
 * read-only view of something that is not.
 *
 * Saves on blur and on Enter, and never on every keystroke: each save is a POST
 * that invalidates the transaction keyspace, so a keystroke-per-request editor
 * would refetch the whole table several times a second.
 *
 * Uncontrolled while focused. Controlled-by-props would fight the cursor - the
 * server round-trip is slower than typing, so each render would restore stale
 * text mid-word. The local value is adopted on mount and on external change.
 */
export default function NoteCell({
  row,
  onSave,
  readOnly = false,
}: {
  row: Transaction;
  onSave?: (ref: string, note: string | null) => void;
  readOnly?: boolean;
}) {
  const stored = row.Note ?? "";
  const [value, setValue] = useState(stored);
  const [editing, setEditing] = useState(false);
  const ref = useRef<HTMLInputElement | null>(null);

  // Adopt the server's value whenever it changes underneath us, but never while
  // the field is being typed into.
  useEffect(() => {
    if (!editing) setValue(stored);
  }, [stored, editing]);

  const commit = () => {
    setEditing(false);
    const next = value.trim() || null;
    // No-op writes are skipped so blurring an untouched field does not invalidate
    // every cached transaction in the app.
    if (next === (stored.trim() || null)) return;
    onSave?.(row.Chq_Ref_Number, next);
  };

  if (readOnly) {
    return stored ? (
      <span className="note-cell note-cell-read">{stored}</span>
    ) : (
      <span className="note-cell note-cell-empty">&mdash;</span>
    );
  }

  return (
    <span className="note-cell-wrap">
      <input
        ref={ref}
        className="note-cell"
        type="text"
        value={value}
        placeholder="Add a note…"
        aria-label={`Note for transaction ${row.Chq_Ref_Number}`}
        onFocus={() => setEditing(true)}
        onChange={(e) => setValue(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.currentTarget.blur();
          } else if (e.key === "Escape") {
            // Abandon the edit: restore what the server has and do not save.
            setValue(stored);
            setEditing(false);
            e.currentTarget.blur();
          }
        }}
      />
      {stored ? (
        <button
          type="button"
          className="note-clear"
          title="Clear this note"
          aria-label="Clear this note"
          onClick={() => {
            setValue("");
            onSave?.(row.Chq_Ref_Number, null);
          }}
        >
          &times;
        </button>
      ) : null}
      {/* An LLM-written note is a guess the user has not confirmed, so it is
          marked as such. Nothing else in the UI distinguishes the two, and an
      unattributed note would read as something the user themselves wrote. */}
      {row.Note_Source === "llm" && stored ? (
        <span className="note-source" title="Written by the LLM, not confirmed by you">
          AI
        </span>
      ) : null}
    </span>
  );
}