"use client";

import { useState } from "react";

import type { CategorySuggestion, SuggestResponse, Transaction } from "@/types";
import { formatCurrency, formatDate } from "@/lib/formatters";

/**
 * Reviews LLM category suggestions before any of them are applied.
 *
 * Nothing here is applied automatically, and that is the design rather than an
 * oversight. The deterministic parser is right most of the time and a model will
 * be confidently wrong about the rest — a wedding gift filed as groceries is worse
 * than an Uncategorized row, because nothing downstream can tell it apart from a
 * correct one. So the model proposes, the user disposes, per row.
 *
 * Two things are applied together when a row is accepted: the category becomes a
 * per-transaction pin, and the model's one-line note becomes the transaction's
 * note. They are one judgement ("this was a wedding gift, so it is a gift"), and
 * splitting them across two confirmations would ask the same question twice.
 */
export default function SuggestModal({
  isOpen,
  rows,
  categories,
  onClose,
  onSuggest,
  onApply,
}: {
  isOpen: boolean;
  rows: Transaction[];
  categories: string[];
  onClose: () => void;
  /** (description: string) => Promise<SuggestResponse> */
  onSuggest: (description: string) => Promise<SuggestResponse>;
  /**
   * Applies the accepted rows in one action.
   * entries: { chq_ref: string; category: string; subCategory: string | null; note: string | null }[]
   */
  onApply: (
    entries: {
      chq_ref: string;
      category: string;
      subCategory: string | null;
      note: string | null;
    }[]
  ) => Promise<void>;
}) {
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SuggestResponse | null>(null);
  const [model, setModel] = useState<string | null>(null);

  // Per-row acceptance and per-row category override. Overriding is not a
  // nicety: the panel exists partly to be disagreed with, and a dropdown that can
  // only be accepted or rejected forces a rejection where an edit would do.
  const [accepted, setAccepted] = useState<Record<string, boolean>>({});
  const [override, setOverride] = useState<Record<string, string>>({});
  const [applyNotes, setApplyNotes] = useState(true);
  const [applying, setApplying] = useState(false);

  if (!isOpen) return null;

  const byId = new Map<string, Partial<Transaction>>(
    (result?.transactions || []).map((t) => [String(t.Chq_Ref_Number), t])
  );
  const suggestions: CategorySuggestion[] = result?.suggestions || [];
  const usable = suggestions.filter(
    (s) => !s.skipped && (override[s.id] || s.category)
  );

  const reset = () => {
    setResult(null);
    setAccepted({});
    setOverride({});
    setError(null);
    setStatus("idle");
    setDescription("");
  };

  const close = () => {
    reset();
    onClose();
  };

  const run = async () => {
    setStatus("loading");
    setError(null);
    try {
      const res = await onSuggest(description);
      setResult(res);
      setModel(res.model);
      // Pre-accept the confident ones and leave the rest to the user. Anything at
      // or below 0.6 is a guess, and a guess should need a tick.
      const seed: Record<string, boolean> = {};
      suggestionsFrom(res).forEach((s) => {
        if (!s.skipped && s.category && (s.confidence ?? 0) >= 0.6) seed[s.id] = true;
      });
      setAccepted(seed);
      setStatus("idle");
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "The suggestion request failed."
      );
      setStatus("error");
    }
  };

  const apply = async () => {
    const entries = usable
      .filter((s) => accepted[s.id])
      .map((s) => ({
        chq_ref: s.id,
        category: override[s.id] || s.category || "",
        subCategory: s.sub_category || null,
        note: applyNotes ? s.note || null : null,
      }));
    if (!entries.length) return;
    setApplying(true);
    try {
      await onApply(entries);
      close();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not apply the suggestions.");
    } finally {
      setApplying(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={close}>
      <div
        className="modal modal-wide"
        role="dialog"
        aria-modal="true"
        aria-label="Category suggestions"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="modal-head">
          <h2>
            Suggest categories ·{" "}
            <span className="muted">
              {rows.length} row{rows.length === 1 ? "" : "s"}
            </span>
          </h2>
          <button type="button" className="btn-ghost" onClick={close} aria-label="Close">
            &times;
          </button>
        </header>

        <div className="modal-body">
          <div className="field">
            <span className="field-label">
              What were these for? (optional, but it is the strongest signal you
              have)
            </span>
            <textarea
              className="input"
              rows={3}
              value={description}
              placeholder="e.g. The four Travel ones are the Bali trip — flights and hotels. The last one is a wedding gift."
              onChange={(e) => setDescription(e.target.value)}
            />
            <p className="field-hint">
              Sent as context to interpret, never as instructions. The model is given
              your own category definitions and each category&apos;s direction, so it
              is asked to choose inside your taxonomy rather than invent one.
            </p>
          </div>

          <div className="modal-actions">
            <button
              type="button"
              className="btn btn-primary"
              onClick={run}
              disabled={status === "loading" || rows.length === 0}
            >
              {status === "loading"
                ? "Asking…"
                : result
                  ? "Ask again"
                  : "Suggest"}
            </button>
            {result ? (
              <label className="checkbox-inline">
                <input
                  type="checkbox"
                  checked={applyNotes}
                  onChange={(e) => setApplyNotes(e.target.checked)}
                />
                also save each note
              </label>
            ) : null}
            {result ? (
              <span className="muted">
                {result.answered}/{result.count} answered
                {model ? ` · ${model}` : ""}
              </span>
            ) : null}
          </div>

          {error ? <p className="modal-error">{error}</p> : null}

          {result ? (
            <table className="table suggest-table">
              <thead>
                <tr>
                  <th style={{ width: 34 }} aria-label="Apply" />
                  <th>Transaction</th>
                  <th style={{ width: 190 }}>Suggestion</th>
                  <th style={{ width: 92 }}>Confidence</th>
                </tr>
              </thead>
              <tbody>
                {suggestions.map((s) => {
                  const row = byId.get(s.id);
                  const amount =
                    (row?.Debit_Amount ?? 0) > 0
                      ? (row?.Debit_Amount as number)
                      : ((row?.Credit_Amount as number) ?? 0);
                  const chosen = override[s.id] ?? s.category ?? "";
                  return (
                    <tr key={s.id} className={s.skipped ? "row-skipped" : undefined}>
                      <td>
                        <input
                          type="checkbox"
                          disabled={s.skipped || !chosen}
                          checked={!!accepted[s.id] && !s.skipped}
                          aria-label={`Apply suggestion for ${s.id}`}
                          onChange={(e) =>
                            setAccepted((prev) => ({ ...prev, [s.id]: e.target.checked }))
                          }
                        />
                      </td>
                      <td>
                        <div className="cell-main">
                          <span className="mono">{formatDate(row?.Date as string)}</span>{" "}
                          <strong>{formatCurrency(amount)}</strong>
                        </div>
                        <div className="cell-sub" title={row?.Narration || ""}>
                          {(row?.Narration || "").slice(0, 78)}
                        </div>
                        {s.note ? (
                          <div className="cell-sub cell-sub-note">{s.note}</div>
                        ) : null}
                        {s.reason ? (
                          <div className="cell-sub cell-sub-reason">{s.reason}</div>
                        ) : null}
                      </td>
                      <td>
                        {s.skipped ? (
                          <span className="muted">no answer</span>
                        ) : (
                          <select
                            className="select"
                            value={chosen}
                            onChange={(e) =>
                              setOverride((prev) => ({ ...prev, [s.id]: e.target.value }))
                            }
                          >
                            {!s.category ? (
                              <option value="">(no suggestion)</option>
                            ) : null}
                            {s.invalid_category ? (
                              <option value="" disabled>
                                rejected: {s.invalid_category}
                              </option>
                            ) : null}
                            {categories.map((c) => (
                              <option key={c} value={c}>
                                {c}
                              </option>
                            ))}
                          </select>
                        )}
                      </td>
                      <td>
                        {s.skipped || s.confidence == null ? (
                          <span className="muted">&mdash;</span>
                        ) : (
                          <span
                            className={
                              s.confidence >= 0.8
                                ? "conf-high"
                                : s.confidence >= 0.6
                                  ? "conf-mid"
                                  : "conf-low"
                            }
                          >
                            {Math.round(s.confidence * 100)}%
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : null}

          {result && result.answered < result.count ? (
            <p className="field-hint">
              {result.count - result.answered} row
              {result.count - result.answered === 1 ? "" : "s"} got no answer and{" "}
              {result.count - result.answered === 1 ? "is" : "are"} left unapplied —
              the model skipped {result.count - result.answered === 1 ? "it" : "them"},
              which is not the same as there being nothing to change.
            </p>
          ) : null}
        </div>

        <footer className="modal-foot">
          <button type="button" className="btn" onClick={close}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={apply}
            disabled={applying || Object.values(accepted).filter(Boolean).length === 0}
          >
            {applying
              ? "Applying…"
              : `Apply ${Object.values(accepted).filter(Boolean).length}`}
          </button>
        </footer>
      </div>
    </div>
  );
}

function suggestionsFrom(res: SuggestResponse): CategorySuggestion[] {
  return res.suggestions || [];
}