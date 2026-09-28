"use client";

import React, { useState, useEffect, useMemo } from "react";
import { CascadeMode, Transaction, PreviewRuleResponse, ApplyCascadeRequest } from "@/types";
import { formatCurrency, formatDate } from "@/lib/formatters";

export interface PendingEdit {
  chq_ref: string;
  payee: string | null;
  narration: string;
  new_category: string;
  new_sub_category: string;
  old_category: string;
  old_sub_category: string;
}

interface CascadeModalProps {
  isOpen: boolean;
  pendingEdits: PendingEdit[];
  /** All known leaves, for the sub-category selector. */
  subCategories?: string[];
  onClose: () => void;
  onPreviewRule: (mode: CascadeMode, key: string) => Promise<PreviewRuleResponse>;
  onApplyCascade: (request: ApplyCascadeRequest) => Promise<any>;
}

export default function CascadeModal({
  isOpen,
  pendingEdits,
  subCategories = [],
  onClose,
  onPreviewRule,
  onApplyCascade,
}: CascadeModalProps) {
  const [mode, setMode] = useState<CascadeMode>("merchant");
  const [keyword, setKeyword] = useState("");
  const [newSub, setNewSub] = useState("");
  const [previewList, setPreviewList] = useState<Transaction[]>([]);
  const [previewTotal, setPreviewTotal] = useState(0);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);
  const [excludedChqRefs, setExcludedChqRefs] = useState<Set<string>>(new Set());
  const [filterSearch, setFilterSearch] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const edit = pendingEdits[0];

  // Set initial mode & keyword when modal opens
  useEffect(() => {
    if (!isOpen || !edit) return;
    setError(null);
    setExcludedChqRefs(new Set());
    setFilterSearch("");
    setNewSub(edit.new_sub_category || "");

    if (edit.payee && edit.payee.trim()) {
      setMode("merchant");
      setKeyword(edit.payee.trim());
    } else {
      setMode("txn");
      setKeyword("");
    }
  }, [isOpen, edit]);

  // Determine active rule key based on current mode
  const activeRuleKey = useMemo(() => {
    if (!edit) return "";
    if (mode === "txn") return edit.chq_ref;
    if (mode === "merchant") return (edit.payee || "").trim();
    if (mode === "narration") return keyword.trim();
    return "";
  }, [mode, keyword, edit]);

  // Query preview of affected transactions
  useEffect(() => {
    if (!isOpen || !edit) return;

    if (mode === "narration" && !keyword.trim()) {
      setPreviewList([]);
      setPreviewTotal(0);
      return;
    }

    if (mode === "merchant" && !edit.payee?.trim()) {
      setPreviewList([]);
      setPreviewTotal(0);
      return;
    }

    let isMounted = true;
    const fetchPreview = async () => {
      try {
        setIsLoadingPreview(true);
        const res = await onPreviewRule(mode, activeRuleKey);
        if (isMounted) {
          setPreviewList(res.transactions || []);
          setPreviewTotal(res.total || 0);
          setExcludedChqRefs(new Set());
        }
      } catch (err: any) {
        if (isMounted) {
          console.error("Preview error:", err);
        }
      } finally {
        if (isMounted) {
          setIsLoadingPreview(false);
        }
      }
    };

    const timer = setTimeout(fetchPreview, mode === "narration" ? 300 : 0);
    return () => {
      isMounted = false;
      clearTimeout(timer);
    };
  }, [isOpen, mode, activeRuleKey, edit]);

  if (!isOpen || pendingEdits.length === 0 || !edit) return null;

  // Filter preview list by search query if present
  const displayList = previewList.filter((tx) => {
    if (!filterSearch.trim()) return true;
    const q = filterSearch.toLowerCase();
    return (
      tx.Narration.toLowerCase().includes(q) ||
      (tx.Payee_Receiver || "").toLowerCase().includes(q) ||
      tx.Chq_Ref_Number.toLowerCase().includes(q) ||
      tx.Broad_Category.toLowerCase().includes(q)
    );
  });

  const includedCount = previewList.length - excludedChqRefs.size;

  const handleToggleRow = (chqRef: string) => {
    setExcludedChqRefs((prev) => {
      const next = new Set(prev);
      if (next.has(chqRef)) {
        next.delete(chqRef);
      } else {
        next.add(chqRef);
      }
      return next;
    });
  };

  const handleSelectAllVisible = () => {
    setExcludedChqRefs((prev) => {
      const next = new Set(prev);
      for (const tx of displayList) {
        next.delete(tx.Chq_Ref_Number);
      }
      return next;
    });
  };

  const handleDeselectAllVisible = () => {
    setExcludedChqRefs((prev) => {
      const next = new Set(prev);
      for (const tx of displayList) {
        next.add(tx.Chq_Ref_Number);
      }
      return next;
    });
  };

  const handleConfirm = async () => {
    setError(null);
    if (mode === "narration" && !keyword.trim()) {
      setError("Please provide a keyword to match for narration cascading.");
      return;
    }

    if (includedCount <= 0) {
      setError("All transactions are excluded — nothing to apply. Check at least one transaction.");
      return;
    }

    try {
      setIsSubmitting(true);
      await onApplyCascade({
        rule_type: mode,
        rule_key: activeRuleKey,
        category: edit.new_category,
        sub_category: newSub || null,
        excluded_chq_refs: Array.from(excludedChqRefs),
      });
      onClose();
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || "Failed to apply category rule");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div style={{
      position: "fixed",
      inset: 0,
      background: "rgba(0, 0, 0, 0.78)",
      backdropFilter: "blur(8px)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      zIndex: 9999,
      padding: "20px",
    }}>
      <div className="glass-panel" style={{
        maxWidth: "920px",
        width: "100%",
        maxHeight: "90vh",
        display: "flex",
        flexDirection: "column",
        padding: "24px 28px",
        background: "var(--bg-card-solid)",
        border: "1px solid var(--border-card)",
        borderRadius: "var(--radius-lg)",
        boxShadow: "0 24px 48px rgba(0, 0, 0, 0.6)",
      }}>
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
          <div>
            <h3 style={{ fontSize: "1.25rem", fontWeight: 700, color: "var(--text-primary)" }}>
              ⚙️ Reassign & Cascade Category Rule
            </h3>
            <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginTop: "2px" }}>
              Reassigning to <strong style={{ color: "var(--accent-indigo)" }}>{edit.new_category}</strong>{" "}
              (previously <em>{edit.old_category}</em>). Choose the cascade scope below:
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

        {/* Radio options */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "10px", marginBottom: "14px" }}>
          <label style={{
            display: "flex",
            alignItems: "flex-start",
            gap: "10px",
            padding: "10px 12px",
            background: mode === "txn" ? "rgba(99, 102, 241, 0.15)" : "rgba(255, 255, 255, 0.02)",
            border: `1px solid ${mode === "txn" ? "var(--accent-indigo)" : "var(--border-subtle)"}`,
            borderRadius: "var(--radius-md)",
            cursor: "pointer",
          }}>
            <input
              type="radio"
              name="cascade_mode"
              checked={mode === "txn"}
              onChange={() => setMode("txn")}
              style={{ marginTop: "3px" }}
            />
            <div>
              <div style={{ fontWeight: 600, fontSize: "0.85rem" }}>Only this transaction</div>
              <div style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>
                Affects only reference {edit.chq_ref.slice(0, 10)}...
              </div>
            </div>
          </label>

          <label style={{
            display: "flex",
            alignItems: "flex-start",
            gap: "10px",
            padding: "10px 12px",
            background: mode === "merchant" ? "rgba(99, 102, 241, 0.15)" : "rgba(255, 255, 255, 0.02)",
            border: `1px solid ${mode === "merchant" ? "var(--accent-indigo)" : "var(--border-subtle)"}`,
            borderRadius: "var(--radius-md)",
            cursor: edit.payee ? "pointer" : "not-allowed",
            opacity: edit.payee ? 1 : 0.5,
          }}>
            <input
              type="radio"
              name="cascade_mode"
              checked={mode === "merchant"}
              onChange={() => edit.payee && setMode("merchant")}
              disabled={!edit.payee}
              style={{ marginTop: "3px" }}
            />
            <div>
              <div style={{ fontWeight: 600, fontSize: "0.85rem" }}>Same Merchant</div>
              <div style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>
                Entity "{edit.payee || "No merchant detected"}"
              </div>
            </div>
          </label>

          <label style={{
            display: "flex",
            alignItems: "flex-start",
            gap: "10px",
            padding: "10px 12px",
            background: mode === "narration" ? "rgba(99, 102, 241, 0.15)" : "rgba(255, 255, 255, 0.02)",
            border: `1px solid ${mode === "narration" ? "var(--accent-indigo)" : "var(--border-subtle)"}`,
            borderRadius: "var(--radius-md)",
            cursor: "pointer",
          }}>
            <input
              type="radio"
              name="cascade_mode"
              checked={mode === "narration"}
              onChange={() => setMode("narration")}
              style={{ marginTop: "3px" }}
            />
            <div>
              <div style={{ fontWeight: 600, fontSize: "0.85rem" }}>Same Narration Keyword</div>
              <div style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>
                Matches keyword in Narration / Details
              </div>
            </div>
          </label>
        </div>

        {/* Sub-category (leaf) selector */}
        <div style={{ marginBottom: "14px" }}>
          <label
            style={{
              display: "block",
              fontSize: "0.825rem",
              color: "var(--text-secondary)",
              fontWeight: 600,
              marginBottom: "6px",
            }}
          >
            Sub-category within {edit.new_category}:
          </label>
          <select
            className="select"
            value={newSub}
            onChange={(e) => setNewSub(e.target.value)}
            style={{ width: "100%", fontWeight: 600 }}
          >
            <option value="">
              Auto (derive from {edit.new_category})
            </option>
            {subCategories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <p style={{ fontSize: "0.7rem", color: "var(--text-muted)", marginTop: "5px" }}>
            Pick a leaf to split {edit.new_category} further — e.g. separate Rent_Brokerage
            from Residential_Rent while both still total under Housing.
          </p>
        </div>

        {/* Narration Keyword Input */}
        {mode === "narration" && (
          <div style={{ marginBottom: "14px", display: "flex", gap: "10px", alignItems: "center" }}>
            <label style={{ fontSize: "0.825rem", color: "var(--text-secondary)", fontWeight: 600, whiteSpace: "nowrap" }}>
              Keyword to match:
            </label>
            <input
              type="text"
              className="input"
              style={{ flex: 1 }}
              placeholder="e.g. RENT, GROWW, SWIGGY, ZOMATO..."
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              autoFocus
            />
          </div>
        )}

        {/* Live Affected Transactions Preview Box */}
        <div style={{
          flex: 1,
          minHeight: "220px",
          display: "flex",
          flexDirection: "column",
          background: "rgba(0, 0, 0, 0.25)",
          border: "1px solid var(--border-subtle)",
          borderRadius: "var(--radius-md)",
          padding: "14px",
          marginBottom: "14px",
          overflow: "hidden",
        }}>
          {/* Preview Toolbar */}
          <div style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: "10px",
            marginBottom: "10px",
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span style={{ fontWeight: 700, fontSize: "0.875rem", color: "var(--text-primary)" }}>
                🎯 Affected Transactions Preview:
              </span>
              <span style={{
                background: "rgba(99, 102, 241, 0.2)",
                color: "var(--accent-indigo)",
                padding: "2px 8px",
                borderRadius: "12px",
                fontSize: "0.75rem",
                fontWeight: 600,
              }}>
                {isLoadingPreview ? "Scanning..." : `${previewTotal} matching`}
              </span>
            </div>

            <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
              <input
                type="text"
                placeholder="Filter preview..."
                className="input"
                style={{ padding: "4px 8px", fontSize: "0.75rem", width: "160px" }}
                value={filterSearch}
                onChange={(e) => setFilterSearch(e.target.value)}
              />
              <button
                type="button"
                className="btn btn-secondary"
                style={{ padding: "4px 8px", fontSize: "0.72rem" }}
                onClick={handleSelectAllVisible}
                title="Include all visible rows in this rule"
              >
                ✓ Select All
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                style={{ padding: "4px 8px", fontSize: "0.72rem" }}
                onClick={handleDeselectAllVisible}
                title="Exclude all visible rows from this rule"
              >
                ✗ Deselect All
              </button>
            </div>
          </div>

          {/* Table Container */}
          <div style={{ flex: 1, overflowY: "auto", minHeight: "150px" }}>
            {isLoadingPreview ? (
              <div style={{ padding: "30px", textAlign: "center", color: "var(--text-muted)", fontSize: "0.85rem" }}>
                ⏳ Scanning statement transactions for matches...
              </div>
            ) : previewList.length === 0 ? (
              <div style={{ padding: "30px", textAlign: "center", color: "var(--text-muted)", fontSize: "0.85rem" }}>
                {mode === "narration" && !keyword.trim()
                  ? "Enter a narration keyword above to scan for matching transactions."
                  : "No matching transactions found for this scope."}
              </div>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.78rem" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid var(--border-subtle)", textAlign: "left", position: "sticky", top: 0, background: "rgba(15, 23, 42, 0.95)" }}>
                    <th style={{ padding: "6px 8px", width: "40px", textAlign: "center" }}>Include?</th>
                    <th style={{ padding: "6px 8px", width: "85px" }}>Date</th>
                    <th style={{ padding: "6px 8px" }}>Narration</th>
                    <th style={{ padding: "6px 8px", width: "140px" }}>Payee / Entity</th>
                    <th style={{ padding: "6px 8px", width: "95px", textAlign: "right" }}>Debit (₹)</th>
                    <th style={{ padding: "6px 8px", width: "95px", textAlign: "right" }}>Credit (₹)</th>
                    <th style={{ padding: "6px 8px", width: "130px" }}>Current Category</th>
                  </tr>
                </thead>
                <tbody>
                  {displayList.map((tx) => {
                    const isIncluded = !excludedChqRefs.has(tx.Chq_Ref_Number);
                    return (
                      <tr
                        key={tx.Chq_Ref_Number}
                        style={{
                          borderBottom: "1px solid rgba(255, 255, 255, 0.03)",
                          background: isIncluded ? "transparent" : "rgba(244, 63, 94, 0.05)",
                          opacity: isIncluded ? 1 : 0.65,
                        }}
                      >
                        <td style={{ padding: "6px 8px", textAlign: "center" }}>
                          <input
                            type="checkbox"
                            checked={isIncluded}
                            onChange={() => handleToggleRow(tx.Chq_Ref_Number)}
                            style={{ cursor: "pointer" }}
                          />
                        </td>
                        <td style={{ padding: "6px 8px", whiteSpace: "nowrap", color: "var(--text-secondary)" }}>
                          {formatDate(tx.Date)}
                        </td>
                        <td style={{ padding: "6px 8px", color: "var(--text-primary)", maxWidth: "260px" }}>
                          <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={tx.Narration}>
                            {tx.Narration}
                          </div>
                        </td>
                        <td style={{ padding: "6px 8px", color: "var(--text-secondary)", maxWidth: "140px" }}>
                          <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={tx.Payee_Receiver || ""}>
                            {tx.Payee_Receiver || "—"}
                          </div>
                        </td>
                        <td style={{
                          padding: "6px 8px",
                          textAlign: "right",
                          fontWeight: 600,
                          color: tx.Debit_Amount && tx.Debit_Amount > 0 ? "var(--rose-outflow)" : "var(--text-muted)",
                        }}>
                          {tx.Debit_Amount && tx.Debit_Amount > 0 ? formatCurrency(tx.Debit_Amount) : "—"}
                        </td>
                        <td style={{
                          padding: "6px 8px",
                          textAlign: "right",
                          fontWeight: 600,
                          color: tx.Credit_Amount && tx.Credit_Amount > 0 ? "var(--emerald-inflow)" : "var(--text-muted)",
                        }}>
                          {tx.Credit_Amount && tx.Credit_Amount > 0 ? formatCurrency(tx.Credit_Amount) : "—"}
                        </td>
                        <td style={{ padding: "6px 8px" }}>
                          <span style={{
                            fontSize: "0.72rem",
                            padding: "2px 6px",
                            borderRadius: "4px",
                            background: "rgba(255, 255, 255, 0.05)",
                            color: "var(--text-muted)",
                          }}>
                            {tx.Broad_Category || "Uncategorized"}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>

          {/* Footer count summary */}
          <div style={{
            marginTop: "10px",
            paddingTop: "8px",
            borderTop: "1px solid var(--border-subtle)",
            display: "flex",
            justifyContent: "space-between",
            fontSize: "0.78rem",
            color: "var(--text-secondary)",
          }}>
            <span>
              ✓ <strong style={{ color: "var(--emerald-inflow)" }}>{includedCount}</strong> will be recategorized to{" "}
              <strong>{edit.new_category}</strong>
            </span>
            {excludedChqRefs.size > 0 && (
              <span style={{ color: "var(--rose-outflow)" }}>
                ✗ <strong>{excludedChqRefs.size}</strong> excluded (will be pinned at their current category)
              </span>
            )}
          </div>
        </div>

        {error && (
          <div style={{
            padding: "8px 12px",
            background: "rgba(244, 63, 94, 0.15)",
            border: "1px solid rgba(244, 63, 94, 0.3)",
            borderRadius: "var(--radius-md)",
            color: "#fb7185",
            fontSize: "0.8rem",
            marginBottom: "12px",
          }}>
            {error}
          </div>
        )}

        {/* Buttons */}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px" }}>
          <button
            className="btn btn-secondary"
            onClick={onClose}
            disabled={isSubmitting}
          >
            Cancel
          </button>
          <button
            className="btn btn-primary"
            onClick={handleConfirm}
            disabled={isSubmitting || includedCount <= 0}
            style={{ minWidth: "150px" }}
          >
            {isSubmitting ? "Applying..." : `Confirm & Apply (${includedCount})`}
          </button>
        </div>
      </div>
    </div>
  );
}
