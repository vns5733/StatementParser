"use client";

import { useState } from "react";

import type { CategoryDefinition, CategoryDirection } from "@/types";

const DIRECTIONS: { value: CategoryDirection; label: string; blurb: string }[] = [
  {
    value: "IN",
    label: "Money in",
    blurb: "Income, a repayment received, a refund.",
  },
  {
    value: "OUT",
    label: "Money out",
    blurb: "Spending, saving, an obligation being paid.",
  },
  {
    value: "BOTH",
    label: "Either",
    blurb: "The event is the same whichever way the money ran.",
  },
];

/**
 * What each category is for, in the user's own words.
 *
 * The direction control is here because it is behaviour, not just prose: it decides
 * which rows the reconciler re-files and which it flags. It is presented next to
 * the code default (rather than instead of it) because an override with no visible
 * original is a value nobody can undo.
 */
export default function CategoryDefinitionsPanel({
  isOpen,
  definitions,
  onSave,
  onClose,
}: {
  isOpen: boolean;
  definitions: CategoryDefinition[];
  onSave: (payload: {
    name: string;
    description: string | null;
    examples: string | null;
    direction_override: CategoryDirection | null;
  }) => Promise<void>;
  onClose: () => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<Partial<CategoryDefinition>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const start = (d: CategoryDefinition) => {
    setEditing(d.name);
    setDraft({
      description: d.description || "",
      examples: d.examples || "",
      direction_override: d.direction_override,
    });
    setError(null);
  };

  const save = async (name: string) => {
    setBusy(true);
    setError(null);
    try {
      await onSave({
        name,
        description: (draft.description || "").trim() || null,
        examples: (draft.examples || "").trim() || null,
        direction_override: draft.direction_override ?? null,
      });
      setEditing(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save that definition.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal modal-wide"
        role="dialog"
        aria-modal="true"
        aria-label="Category definitions"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="modal-head">
          <h2>
            Category definitions{" "}
            <span className="muted">
              · {definitions.length} categor{definitions.length === 1 ? "y" : "ies"}
            </span>
          </h2>
          <button type="button" className="btn-ghost" onClick={onClose} aria-label="Close">
            &times;
          </button>
        </header>

        <div className="modal-body">
          <p className="modal-hint">
            These are shown to you while you categorise, and sent to the model when
            it suggests a category — so it argues in your taxonomy, not its own. The
            direction decides behaviour: a credit in an{" "}
            <strong>out</strong> category is re-filed to its counterpart where one
            exists, and flagged where one does not.
          </p>

          {error ? <p className="modal-error">{error}</p> : null}

          <table className="table">
            <thead>
              <tr>
                <th style={{ width: 190 }}>Category</th>
                <th style={{ width: 128 }}>Direction</th>
                <th>Definition</th>
                <th style={{ width: 120 }} />
              </tr>
            </thead>
            <tbody>
              {definitions.map((d) => {
                const isEditing = editing === d.name;
                return (
                  <tr key={d.name}>
                    <td>
                      <div className="cell-main mono">{d.name}</div>
                      {d.is_builtin ? (
                        <div className="cell-sub">built-in</div>
                      ) : null}
                    </td>
                    <td>
                      {isEditing ? (
                        <select
                          className="select"
                          value={draft.direction_override ?? ""}
                          onChange={(e) =>
                            setDraft((p) => ({
                              ...p,
                              direction_override: (e.target.value ||
                                null) as CategoryDirection | null,
                            }))
                          }
                        >
                          <option value="">
                            default: {d.code_direction}
                          </option>
                          {DIRECTIONS.map((o) => (
                            <option key={o.value} value={o.value}>
                              {o.label}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <span className={`dir-chip dir-${d.direction}`}>
                          {d.direction}
                        </span>
                      )}
                      {!isEditing && d.direction_override ? (
                        <div
                          className="cell-sub"
                          title={`Overriding the built-in direction (${d.code_direction})`}
                        >
                          overridden
                        </div>
                      ) : null}
                    </td>
                    <td>
                      {isEditing ? (
                        <>
                          <textarea
                            className="input"
                            rows={3}
                            placeholder="What belongs in this category?"
                            value={draft.description || ""}
                            onChange={(e) =>
                              setDraft((p) => ({ ...p, description: e.target.value }))
                            }
                          />
                          <input
                            className="input"
                            placeholder="Examples — merchants, keywords"
                            value={draft.examples || ""}
                            onChange={(e) =>
                              setDraft((p) => ({ ...p, examples: e.target.value }))
                            }
                          />
                        </>
                      ) : (
                        <>
                          <div>{d.description || <em className="muted">undefined</em>}</div>
                          {d.examples ? (
                            <div className="cell-sub">e.g. {d.examples}</div>
                          ) : null}
                        </>
                      )}
                    </td>
                    <td>
                      {isEditing ? (
                        <div className="row-actions">
                          <button
                            type="button"
                            className="btn btn-primary btn-sm"
                            disabled={busy}
                            onClick={() => save(d.name)}
                          >
                            Save
                          </button>
                          <button
                            type="button"
                            className="btn btn-sm"
                            disabled={busy}
                            onClick={() => setEditing(null)}
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          className="btn btn-sm"
                          onClick={() => start(d)}
                        >
                          Edit
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <footer className="modal-foot">
          <p className="field-hint modal-foot-hint">
            Editing a definition never rewrites stored transactions, and a re-import
            of the same statement never rewrites your wording.
          </p>
          <button type="button" className="btn btn-primary" onClick={onClose}>
            Done
          </button>
        </footer>
      </div>
    </div>
  );
}