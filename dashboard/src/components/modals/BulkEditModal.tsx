"use client";

import { useMemo, useState } from "react";

import type { Transaction } from "@/types";

/**
 * Applies one category or one note to an explicit set of transactions.
 *
 * Bulk category changes go out as per-transaction `txn` rules rather than as a
 * merchant or narration rule. That is a deliberate limit on the blast radius: a
 * selection is a set of rows the user looked at and chose, and a merchant rule
 * built from it would also catch rows they never saw. Widening is available
 * afterwards through CascadeModal, where the widening is what the user is actually
 * asking for.
 */
export default function BulkEditModal({
  isOpen,
  mode,
  selectedRows,
  categories,
  leavesOf,
  onClose,
  onApplyCategory,
  onApplyNote,
}: {
  isOpen: boolean;
  mode: "category" | "note";
  /** The rows behind the selection, so the user can see what they picked. */
  selectedRows: Transaction[];
  categories: string[];
  /** Leaves keyed by broad category, from /transactions/meta. */
  leavesOf: Record<string, string[]>;
  onClose: () => void;
  /** (category, subCategory | null) => Promise<void> */
  onApplyCategory: (category: string, subCategory: string | null) => Promise<void>;
  /** (note | null) => Promise<void> */
  onApplyNote: (note: string | null) => Promise<void>;
}) {
  const [parent, setParent] = useState("");
  const [broad, setBroad] = useState("");
  const [sub, setSub] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refs = useMemo(
    () => selectedRows.map((r) => r.Chq_Ref_Number),
    [selectedRows]
  );

  // Leaves are listed under the broad category actually chosen. Offering every
  // leaf in one flat list would put Residential_Rent next to Bakery_Sweets, which
  // is how a leaf ends up filed under a parent it does not belong to.
  const leafOptions = useMemo(() => (broad ? leavesOf[broad] || [] : []), [
    broad,
    leavesOf,
  ]);

  if (!isOpen) return null;

  const close = () => {
    setError(null);
    onClose();
  };

  const submitCategory = async () => {
    if (!broad) {
      setError("Pick a category first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onApplyCategory(broad, sub || null);
      close();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not apply the change.");
    } finally {
      setBusy(false);
    }
  };

  const submitNote = async () => {
    setBusy(true);
    setError(null);
    try {
      await onApplyNote(note.trim() || null);
      close();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the note.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={close}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={mode === "category" ? "Reassign selected rows" : "Note selected rows"}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="modal-head">
          <h2>
            {mode === "category" ? "Reassign selected" : "Note selected"} ·{" "}
            <span className="muted">{refs.length} row{refs.length === 1 ? "" : "s"}</span>
          </h2>
          <button type="button" className="btn-ghost" onClick={close} aria-label="Close">
            &times;
          </button>
        </header>

        <div className="modal-body">
          {mode === "category" ? (
            <>
              <p className="modal-hint">
                Applies to exactly these rows, as individual pins. It will not touch
                other transactions from the same merchant — widen it afterwards if
                that is what you want.
              </p>
              <div className="field">
                <span className="field-label">Parent</span>
                <select
                  className="select"
                  value={parent}
                  onChange={(e) => {
                    setParent(e.target.value);
                    setBroad("");
                    setSub("");
                  }}
                >
                  <option value="">(any)</option>
                  {categories.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <span className="field-label">Category</span>
                <select
                  className="select"
                  value={broad}
                  onChange={(e) => {
                    setBroad(e.target.value);
                    setSub("");
                  }}
                >
                  <option value="">(choose…)</option>
                  {categories.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <span className="field-label">Sub-Category</span>
                <select
                  className="select"
                  value={sub}
                  disabled={!broad}
                  onChange={(e) => setSub(e.target.value)}
                >
                  <option value="">(let the server derive one)</option>
                  {leafOptions.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
                <p className="field-hint">
                  The server derives a sensible leaf from the category when this is
                  left empty.
                </p>
              </div>
            </>
          ) : (
            <>
              <p className="modal-hint">
                The same text on every selected row. Leave it empty and save to clear
                them.
              </p>
              <div className="field">
                <span className="field-label">Note</span>
                <textarea
                  className="input"
                  rows={4}
                  value={note}
                  autoFocus
                  placeholder="What were these for?"
                  onChange={(e) => setNote(e.target.value)}
                />
              </div>
            </>
          )}

          {error ? <p className="modal-error">{error}</p> : null}

          <div className="selection-preview">
            <span className="field-label">Selected</span>
            <ul className="selection-list">
              {selectedRows.slice(0, 6).map((r) => (
                <li key={r.Chq_Ref_Number} title={r.Narration || ""}>
                  <span className="mono">{String(r.Date).slice(0, 10)}</span>{" "}
                  {(r.Narration || "").slice(0, 64)}
                </li>
              ))}
              {selectedRows.length > 6 ? (
                <li className="muted">+{selectedRows.length - 6} more</li>
              ) : null}
            </ul>
          </div>
        </div>

        <footer className="modal-foot">
          <button type="button" className="btn" onClick={close} disabled={busy}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={mode === "category" ? submitCategory : submitNote}
            disabled={busy}
          >
            {busy
              ? "Saving…"
              : mode === "category"
                ? `Apply to ${refs.length}`
                : note.trim()
                  ? `Save on ${refs.length}`
                  : `Clear ${refs.length} note${refs.length === 1 ? "" : "s"}`}
          </button>
        </footer>
      </div>
    </div>
  );
}