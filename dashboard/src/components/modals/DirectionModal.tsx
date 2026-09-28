"use client";

import React, { useState, useEffect, useMemo } from "react";
import type {
  ApplyDirectionCascadeRequest,
  DirectionMode,
  PreviewDirectionResponse,
  Transaction,
  TxnDirection,
} from "@/types";
import { formatCurrency, formatDate } from "@/lib/formatters";

export interface PendingDirectionEdit {
  chq_ref: string;
  payee: string | null;
  narration: string;
  old_direction: TxnDirection;
  amount: number;
}

interface DirectionModalProps {
  isOpen: boolean;
  edit: PendingDirectionEdit | null;
  onClose: () => void;
  onPreview: (
    rule_type: DirectionMode,
    rule_key: string,
    direction: TxnDirection
  ) => Promise<PreviewDirectionResponse>;
  onApply: (request: ApplyDirectionCascadeRequest) => Promise<any>;
}

const MODES: { key: DirectionMode; label: string; hint: string }[] = [
  { key: "txn", label: "Only this transaction", hint: "Pins one exact reference" },
  { key: "merchant", label: "Same merchant", hint: "Every row with this payee" },
  { key: "narration", label: "Same narration keyword", hint: "Narration contains the text" },
];

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "8px 11px",
  background: "var(--bg-input, rgba(255,255,255,0.05))",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  color: "var(--text-primary)",
  fontSize: "0.82rem",
  boxSizing: "border-box",
};

/**
 * Flips a transaction between debit and credit, with the same three cascade
 * scopes the category editor offers.
 *
 * The amount is moved between the two amount columns server-side, so a flipped
 * row sums correctly in the KPI, the charts and the CSV export without the UI
 * doing any arithmetic. A card bill payment is the motivating case: it prints
 * in the statement's debit column but is money coming in on the card.
 */
export default function DirectionModal({
  isOpen,
  edit,
  onClose,
  onPreview,
  onApply,
}: DirectionModalProps) {
  const [mode, setMode] = useState<DirectionMode>("txn");
  const [keyword, setKeyword] = useState("");
  const [direction, setDirection] = useState<TxnDirection>("CREDIT");
  const [previewList, setPreviewList] = useState<Transaction[]>([]);
  const [previewTotal, setPreviewTotal] = useState(0);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [filterSearch, setFilterSearch] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Default to the opposite of what the row currently is - that is what the
  // user is trying to do when they open this.
  useEffect(() => {
    if (!isOpen || !edit) return;
    setError(null);
    setExcluded(new Set());
    setFilterSearch("");
    setDirection(edit.old_direction === "DEBIT" ? "CREDIT" : "DEBIT");
    setMode(edit.payee && edit.payee.trim() ? "merchant" : "txn");
  }, [isOpen, edit]);

  const activeRuleKey = useMemo(() => {
    if (!edit) return "";
    if (mode === "txn") return edit.chq_ref;
    if (mode === "merchant") return (edit.payee || "").trim();
    return keyword.trim();
  }, [mode, keyword, edit]);

  useEffect(() => {
    if (!isOpen || !edit) return;
    const needsKeyword = mode === "narration" && !keyword.trim();
    const needsPayee = mode === "merchant" && !edit.payee?.trim();
    if (!activeRuleKey || needsKeyword || needsPayee) {
      setPreviewList([]);
      setPreviewTotal(0);
      return;
    }
    let isMounted = true;
    const fetchPreview = async () => {
      try {
        setIsLoadingPreview(true);
        const res = await onPreview(mode, activeRuleKey, direction);
        if (isMounted) {
          setPreviewList(res.transactions || []);
          setPreviewTotal(res.total || 0);
          setExcluded(new Set());
        }
      } catch {
        if (isMounted) setPreviewList([]);
      } finally {
        if (isMounted) setIsLoadingPreview(false);
      }
    };
    const timer = setTimeout(fetchPreview, mode === "narration" ? 300 : 0);
    return () => {
      isMounted = false;
      clearTimeout(timer);
    };
  }, [isOpen, mode, activeRuleKey, direction, edit, onPreview]);

  if (!isOpen || !edit) return null;

  const displayList = previewList.filter((tx) => {
    if (!filterSearch.trim()) return true;
    const q = filterSearch.toLowerCase();
    return (
      (tx.Narration || "").toLowerCase().includes(q) ||
      (tx.Payee_Receiver || "").toLowerCase().includes(q) ||
      (tx.Chq_Ref_Number || "").toLowerCase().includes(q)
    );
  });

  const includedCount = previewList.length - excluded.size;

  const toggleRow = (ref: string) =>
    setExcluded((prev) => {
      const next = new Set(prev);
      if (next.has(ref)) next.delete(ref);
      else next.add(ref);
      return next;
    });

  const selectAllVisible = () =>
    setExcluded((prev) => {
      const next = new Set(prev);
      displayList.forEach((tx) => next.delete(tx.Chq_Ref_Number));
      return next;
    });

  const deselectAllVisible = () =>
    setExcluded((prev) => {
      const next = new Set(prev);
      displayList.forEach((tx) => next.add(tx.Chq_Ref_Number));
      return next;
    });

  const handleConfirm = async () => {
    setError(null);
    if (mode === "narration" && !keyword.trim()) {
      setError("Please provide a keyword to match for narration cascading.");
      return;
    }
    if (includedCount <= 0) {
      setError("All transactions are excluded - nothing to apply.");
      return;
    }
    try {
      setIsSubmitting(true);
      await onApply({
        rule_type: mode,
        rule_key: activeRuleKey,
        direction,
        excluded_chq_refs: Array.from(excluded),
      });
      onClose();
    } catch (err: any) {
      setError(
        err?.response?.data?.detail || err.message || "Failed to apply direction rule"
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const modeEnabled = (m: DirectionMode) => m !== "merchant" || Boolean(edit.payee?.trim());
  const currentColor =
    edit.old_direction === "DEBIT" ? "var(--rose-outflow)" : "var(--emerald-inflow)";

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0, 0, 0, 0.78)",
        backdropFilter: "blur(8px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 9999,
        padding: "20px",
      }}
    >
      <div
        className="glass-panel"
        style={{
          maxWidth: "920px",
          width: "100%",
          maxHeight: "90vh",
          display: "flex",
          flexDirection: "column",
          padding: "24px 28px",
          background: "var(--bg-card-solid)",
          border: "1px solid var(--border-card)",
          borderRadius: "var(--radius-lg)",
          boxShadow: "0 24px 48px rgba(0,0,0,0.6)",
        }}
      >
        <Header edit={edit} currentColor={currentColor} onClose={onClose} />

        <DirectionPicker
          current={edit.old_direction}
          value={direction}
          onChange={setDirection}
        />

        <ScopePicker
          mode={mode}
          payee={edit.payee}
          enabled={modeEnabled}
          onChange={setMode}
        />

        {mode === "narration" && (
          <input
            type="text"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="Narration keyword, e.g. BPPY CC PAYMENT"
            style={{ ...inputStyle, marginBottom: "14px" }}
          />
        )}

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: "8px",
          }}
        >
          <div style={{ fontSize: "0.8rem", color: "var(--text-secondary)", fontWeight: 600 }}>
            {isLoadingPreview
              ? "Loading preview..."
              : `${previewTotal} transaction${previewTotal === 1 ? "" : "s"} will change`}
            {previewTotal > 0 && ` (${includedCount} included)`}
          </div>
          <div style={{ display: "flex", gap: "6px" }}>
            <button
              className="btn btn-secondary"
              onClick={selectAllVisible}
              style={{ fontSize: "0.72rem", padding: "4px 8px" }}
            >
              Select all
            </button>
            <button
              className="btn btn-secondary"
              onClick={deselectAllVisible}
              style={{ fontSize: "0.72rem", padding: "4px 8px" }}
            >
              Exclude all
            </button>
          </div>
        </div>

        <input
          type="text"
          value={filterSearch}
          onChange={(e) => setFilterSearch(e.target.value)}
          placeholder="Filter preview..."
          style={{ ...inputStyle, marginBottom: "8px" }}
        />

        <div
          style={{
            overflowY: "auto",
            maxHeight: "260px",
            border: "1px solid var(--border-subtle)",
            borderRadius: "var(--radius-md)",
          }}
        >
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.78rem" }}>
            <thead>
              <tr
                style={{
                  borderBottom: "1px solid var(--border-subtle)",
                  background: "rgba(255,255,255,0.03)",
                }}
              >
                <th style={{ padding: "8px 10px", textAlign: "left" }}>Apply</th>
                <th style={{ padding: "8px 10px", textAlign: "left" }}>Date</th>
                <th style={{ padding: "8px 10px", textAlign: "left" }}>Narration</th>
                <th style={{ padding: "8px 10px", textAlign: "right" }}>Amount</th>
              </tr>
            </thead>
            <tbody>
              {displayList.map((tx) => {
                const amt = (tx.Debit_Amount || 0) + (tx.Credit_Amount || 0);
                return (
                  <tr
                    key={tx.Chq_Ref_Number}
                    style={{ borderBottom: "1px solid rgba(255,255,255,0.03)" }}
                  >
                    <td style={{ padding: "7px 10px" }}>
                      <input
                        type="checkbox"
                        checked={!excluded.has(tx.Chq_Ref_Number)}
                        onChange={() => toggleRow(tx.Chq_Ref_Number)}
                      />
                    </td>
                    <td
                      style={{
                        padding: "7px 10px",
                        color: "var(--text-muted)",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {formatDate(tx.Date)}
                    </td>
                    <td style={{ padding: "7px 10px", color: "var(--text-secondary)" }}>
                      {tx.Narration}
                      {tx.Is_Settlement && (
                        <span
                          className="badge badge-gray"
                          style={{ marginLeft: "6px", fontSize: "0.65rem" }}
                        >
                          settlement
                        </span>
                      )}
                    </td>
                    <td
                      style={{ padding: "7px 10px", textAlign: "right", whiteSpace: "nowrap" }}
                    >
                      {formatCurrency(amt)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {displayList.length === 0 && !isLoadingPreview && (
            <p
              style={{
                padding: "18px",
                textAlign: "center",
                color: "var(--text-muted)",
                fontSize: "0.8rem",
                margin: 0,
              }}
            >
              No transactions match this scope.
            </p>
          )}
        </div>

        {error && (
          <p style={{ color: "var(--rose-outflow)", fontSize: "0.8rem", marginTop: "10px" }}>
            {error}
          </p>
        )}

        <div
          style={{ display: "flex", justifyContent: "flex-end", gap: "10px", marginTop: "16px" }}
        >
          <button className="btn btn-secondary" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            onClick={handleConfirm}
            disabled={isSubmitting || includedCount <= 0}
          >
            {isSubmitting
              ? "Applying..."
              : `Apply to ${includedCount} transaction${includedCount === 1 ? "" : "s"}`}
          </button>
        </div>
      </div>
    </div>
  );
}
// Small presentational pieces, kept out of the main component so the flow above
// reads top-to-bottom: pick a direction, pick a scope, check the preview, apply.

function Header({
  edit,
  currentColor,
  onClose,
}: {
  edit: PendingDirectionEdit;
  currentColor: string;
  onClose: () => void;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "flex-start",
        marginBottom: "12px",
      }}
    >
      <div>
        <h3 style={{ fontSize: "1.25rem", fontWeight: 700, color: "var(--text-primary)" }}>
          Change Debit / Credit
        </h3>
        <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginTop: "2px" }}>
          {formatCurrency(edit.amount)} · currently{" "}
          <strong style={{ color: currentColor }}>
            {edit.old_direction === "DEBIT" ? "Debit (outflow)" : "Credit (inflow)"}
          </strong>
        </p>
        <p style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginTop: "2px" }}>
          {edit.narration}
        </p>
      </div>
      <button
        onClick={onClose}
        style={{
          background: "transparent",
          border: "none",
          color: "var(--text-muted)",
          fontSize: "1.3rem",
          cursor: "pointer",
          padding: "4px",
        }}
      >
        ✕
      </button>
    </div>
  );
}

function DirectionPicker({
  current,
  value,
  onChange,
}: {
  current: TxnDirection;
  value: TxnDirection;
  onChange: (d: TxnDirection) => void;
}) {
  return (
    <div style={{ display: "flex", gap: "10px", marginBottom: "14px" }}>
      {(["CREDIT", "DEBIT"] as TxnDirection[]).map((d) => {
        const isCurrent = d === current;
        const accent = d === "CREDIT" ? "var(--emerald-inflow)" : "var(--rose-outflow)";
        return (
          <button
            key={d}
            onClick={() => onChange(d)}
            disabled={isCurrent}
            style={{
              flex: 1,
              padding: "10px",
              borderRadius: "var(--radius-md)",
              border: `1px solid ${value === d ? accent : "var(--border-subtle)"}`,
              background:
                value === d
                  ? d === "CREDIT"
                    ? "rgba(16,185,129,0.15)"
                    : "rgba(244,63,94,0.15)"
                  : "rgba(255,255,255,0.02)",
              color: isCurrent ? "var(--text-muted)" : "var(--text-primary)",
              cursor: isCurrent ? "not-allowed" : "pointer",
              fontWeight: 600,
              fontSize: "0.85rem",
              opacity: isCurrent ? 0.5 : 1,
            }}
          >
            {d === "CREDIT" ? "Credit (inflow)" : "Debit (outflow)"}
            {isCurrent ? " — current" : ""}
          </button>
        );
      })}
    </div>
  );
}

function ScopePicker({
  mode,
  payee,
  enabled,
  onChange,
}: {
  mode: DirectionMode;
  payee: string | null;
  enabled: (m: DirectionMode) => boolean;
  onChange: (m: DirectionMode) => void;
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
        gap: "10px",
        marginBottom: "14px",
      }}
    >
      {MODES.map((m) => {
        const ok = enabled(m.key);
        return (
          <label
            key={m.key}
            style={{
              display: "flex",
              alignItems: "flex-start",
              gap: "10px",
              padding: "10px 12px",
              background:
                mode === m.key ? "rgba(99,102,241,0.15)" : "rgba(255,255,255,0.02)",
              border: `1px solid ${mode === m.key ? "var(--accent-indigo)" : "var(--border-subtle)"}`,
              borderRadius: "var(--radius-md)",
              cursor: ok ? "pointer" : "not-allowed",
              opacity: ok ? 1 : 0.5,
            }}
          >
            <input
              type="radio"
              name="direction_mode"
              checked={mode === m.key}
              onChange={() => ok && onChange(m.key)}
              disabled={!ok}
              style={{ marginTop: "3px" }}
            />
            <div>
              <div style={{ fontWeight: 600, fontSize: "0.85rem" }}>{m.label}</div>
              <div style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>
                {m.key === "merchant" ? payee || "No merchant detected" : m.hint}
              </div>
            </div>
          </label>
        );
      })}
    </div>
  );
}

