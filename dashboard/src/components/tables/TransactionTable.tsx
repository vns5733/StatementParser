"use client";

import React, { useState } from "react";
import { Filters, Transaction } from "@/types";
import { downloadFilteredCSV } from "@/lib/api";
import { useClampPage } from "@/hooks/useClampPage";
import { formatCurrency, formatDate, formatNumber } from "@/lib/formatters";

const CATEGORY_SELECT = {
  padding: "6px 10px",
  fontSize: "0.8rem",
  background: "rgba(99, 102, 241, 0.12)",
  borderColor: "rgba(99, 102, 241, 0.35)",
  fontWeight: 600,
  cursor: "pointer",
  width: "100%",
} as const;

interface TransactionTableProps {
  data: Transaction[];
  total: number;
  page: number;
  pageSize: number;
  onChangePage: (page: number) => void;
  onChangePageSize: (size: number) => void;
  isLoading?: boolean;
  /** When provided, the CSV button exports this full filter set via the API. */
  exportFilters?: Filters;
  /** Label for the CSV button, e.g. "Download March 2024 CSV". */
  exportLabel?: string;
  /**
   * Opens the debit/credit flip editor for a row. Optional so a read-only
   * embedding can simply omit it and lose only the toggle buttons.
   */
  onEditDirection?: (row: Transaction) => void;
  /**
   * Called when the category or sub-category dropdown changes. Supplying this
   * turns the category cells into editable dropdowns, matching
   * CategoryEditorTable and DrilldownPanel.
   *
   * This is a prop rather than built in because the table is reused by the
   * credit-card view, which has no other way to correct a mis-categorised card
   * row: its own category editor lives on a different table. Omitting the prop
   * leaves the cells as read-only text, which is what a read-only embedding
   * wants.
   */
  onCategoryChange?: (row: Transaction, newCategory: string, newSub?: string) => void;
  /** Known broad categories, for the dropdown. */
  categories?: string[];
  /** Known leaves, for the sub-category dropdown. */
  subCategories?: string[];
}

export default function TransactionTable({
  data,
  total,
  page,
  pageSize,
  onChangePage,
  onChangePageSize,
  isLoading,
  exportFilters,
  exportLabel = "Download CSV",
  onEditDirection,
  onCategoryChange,
  categories = [],
  subCategories = [],
}: TransactionTableProps) {
  const [isExporting, setIsExporting] = useState(false);
  const totalPages = useClampPage(page, pageSize, total, onChangePage, isLoading);

  // Export the entire filtered set from the server so the download is not
  // silently capped at the rows currently on screen.
  const handleDownloadCSV = async () => {
    if (!exportFilters) return;
    setIsExporting(true);
    try {
      await downloadFilteredCSV(exportFilters);
    } catch (err: any) {
      alert(err?.response?.data?.detail || err?.message || "CSV export failed");
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <div className="glass-panel" style={{ padding: "20px" }}>
      {/* Table Header controls */}
      <div style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        marginBottom: "16px",
        flexWrap: "wrap",
        gap: "12px",
      }}>
        <div>
          <h3 style={{ fontSize: "1.1rem", fontWeight: 700, color: "var(--text-primary)" }}>
            Transactions Explorer
          </h3>
          <p style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
            Showing {data.length} of {total} total filtered records
          </p>
        </div>

        <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
          {exportFilters && (
            <button
              className="btn btn-secondary"
              onClick={handleDownloadCSV}
              disabled={total === 0 || isExporting}
              style={{ fontSize: "0.8rem" }}
              title={`Export all ${total} matching transactions as CSV`}
            >
              {isExporting ? "Preparing..." : `📥 ${exportLabel}`}
            </button>
          )}

          <select
            className="select"
            value={pageSize}
            onChange={(e) => onChangePageSize(Number(e.target.value))}
            style={{ width: "auto", fontSize: "0.8rem", padding: "6px 10px" }}
          >
            <option value={25}>25 / page</option>
            <option value={50}>50 / page</option>
            <option value={100}>100 / page</option>
          </select>
        </div>
      </div>

      {/* Table Container */}
      <div style={{ overflowX: "auto", minHeight: "300px" }}>
        {isLoading ? (
          <div style={{ padding: "60px 0", textAlign: "center", color: "var(--text-muted)" }}>
            Loading transactions...
          </div>
        ) : data.length === 0 ? (
          <div style={{ padding: "60px 0", textAlign: "center", color: "var(--text-muted)" }}>
            No transactions match the selected filters.
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border-subtle)", textAlign: "left" }}>
                <th style={{ padding: "10px 12px", color: "var(--text-muted)", fontWeight: 600, width: "110px" }}>Date</th>
                <th style={{ padding: "10px 12px", color: "var(--text-muted)", fontWeight: 600 }}>Narration</th>
                <th style={{ padding: "10px 12px", color: "var(--text-muted)", fontWeight: 600 }}>Type</th>
                <th style={{ padding: "10px 12px", color: "var(--text-muted)", fontWeight: 600, width: "190px" }}>
                  Category
                </th>
                <th style={{ padding: "10px 12px", color: "var(--text-muted)", fontWeight: 600, width: "95px" }}>
                  Payee / Entity
                </th>
                <th style={{ padding: "10px 12px", color: "var(--text-muted)", fontWeight: 600, textAlign: "right" }}>Debit (₹)</th>
                <th style={{ padding: "10px 12px", color: "var(--text-muted)", fontWeight: 600, textAlign: "right" }}>Credit (₹)</th>
                <th style={{ padding: "10px 12px", color: "var(--text-muted)", fontWeight: 600, textAlign: "right" }}>Balance (₹)</th>
                <th style={{ padding: "10px 12px", color: "var(--text-muted)", fontWeight: 600 }}>Reference</th>
              </tr>
            </thead>
            <tbody>
              {data.map((row) => (
                <tr
                  key={row.Chq_Ref_Number}
                  style={{
                    borderBottom: "1px solid rgba(255, 255, 255, 0.03)",
                    transition: "background 0.15s ease",
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255, 255, 255, 0.02)")}
                  onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                >
                  <td style={{ padding: "12px", whiteSpace: "nowrap", color: "var(--text-secondary)" }}>
                    {formatDate(row.Date)}
                  </td>
                  <td style={{ padding: "12px", maxWidth: "260px", color: "var(--text-primary)" }}>
                    <div style={{ wordBreak: "break-word" }}>{row.Narration}</div>
                  </td>
                  <td style={{ padding: "12px", whiteSpace: "nowrap" }}>
                    <span className="badge badge-indigo">
                      {row.Transaction_Type || "UNKNOWN"}
                    </span>
                  </td>
                  <td style={{ padding: "12px", whiteSpace: "nowrap" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                      {row.is_recurring && (
                        <span
                          title="Recurring — this counterparty repeats on a monthly cadence"
                          style={{ color: "var(--accent-indigo)", fontSize: "0.8rem" }}
                        >
                          ↻
                        </span>
                      )}
                      <span
                        style={{
                          fontSize: "0.68rem",
                          color: "var(--text-muted)",
                          textTransform: "uppercase",
                          letterSpacing: "0.04em",
                        }}
                      >
                        {row.Category || "—"}
                      </span>
                    </div>
                    <div
                      style={{
                        fontSize: "0.8rem",
                        color: "var(--text-primary)",
                        fontWeight: 600,
                        marginTop: "1px",
                      }}
                      title={`${row.Category} › ${row.Broad_Category} › ${row.Sub_Category}`}
                    >
                      {onCategoryChange ? (
                        <select
                          className="select"
                          value={row.Broad_Category || "Uncategorized"}
                          onChange={(e) =>
                            onCategoryChange(row, e.target.value, row.Sub_Category)
                          }
                          style={CATEGORY_SELECT}
                          title="Reassign this transaction's category"
                        >
                          {!categories.includes(row.Broad_Category || "") && (
                            <option value={row.Broad_Category || "Uncategorized"}>
                              {row.Broad_Category || "Uncategorized"}
                            </option>
                          )}
                          {categories.map((c) => (
                            <option key={c} value={c}>
                              {c}
                            </option>
                          ))}
                        </select>
                      ) : (
                        row.Sub_Category || row.Broad_Category || "Uncategorized"
                      )}
                    </div>
                    {/* The leaf gets its own control, mirroring the other two
                        editors. A sub-category must follow its parent, so changing
                        it re-sends the row's current broad category. */}
                    {onCategoryChange && (
                      <div style={{ marginTop: "2px" }}>
                        <select
                          className="select"
                          value={row.Sub_Category || row.Broad_Category || "Uncategorized"}
                          onChange={(e) =>
                            onCategoryChange(row, row.Broad_Category, e.target.value)
                          }
                          style={{ ...CATEGORY_SELECT, fontSize: "0.7rem", fontWeight: 500 }}
                          title="Reassign this transaction's sub-category"
                        >
                          <option value={row.Broad_Category || "Uncategorized"}>
                            (auto)
                          </option>
                          {subCategories.map((c) => (
                            <option key={c} value={c}>
                              {c}
                            </option>
                          ))}
                        </select>
                      </div>
                    )}
                    {/* Ledger provenance: a card purchase and the bank debit that
                        pays its bill are both real rows, and both belong here. The
                        settlement badge is the reason the amount looks like spend
                        but is not counted as such. */}
                    <div
                      style={{ display: "flex", gap: "4px", marginTop: "4px" }}
                    >
                      {row.Account_Source === "CREDIT_CARD" && (
                        <span
                          className="badge badge-indigo"
                          title={`Credit-card purchase${row.Card_Name ? ` on ${row.Card_Name}` : ""}`}
                        >
                          {row.Card_Name || "Card"}
                        </span>
                      )}
                      {row.Is_Settlement && (
                        <span
                          className="badge badge-gray"
                          title={
                            row.Account_Source === "CREDIT_CARD"
                              ? "Repays the card balance — not spend"
                              : "Bank payment that settles a credit-card bill — not spend, since the purchases are already counted"
                          }
                        >
                          Card bill payment
                        </span>
                      )}
                    </div>
                  </td>
                  <td style={{ padding: "12px", color: "var(--text-secondary)", maxWidth: "160px" }}>
                    <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {row.Payee_Receiver || "—"}
                    </div>
                  </td>
                  <td style={{
                    padding: "12px",
                    textAlign: "right",
                    whiteSpace: "nowrap",
                    fontWeight: 600,
                    color: row.Debit_Amount && row.Debit_Amount > 0 ? "var(--rose-outflow)" : "var(--text-muted)",
                  }}>
                    {row.Debit_Amount && row.Debit_Amount > 0 ? formatCurrency(row.Debit_Amount) : "—"}
                    {onEditDirection && ((row.Debit_Amount || 0) > 0 || (row.Credit_Amount || 0) > 0) && (
                      <button
                        onClick={() => onEditDirection(row)}
                        title="Flip this transaction between debit and credit. You can then scope the change to this transaction, its merchant, or a narration keyword."
                        style={{
                          marginLeft: "8px",
                          padding: "1px 6px",
                          fontSize: "0.68rem",
                          background: "transparent",
                          border: "1px solid var(--border-subtle)",
                          borderRadius: "4px",
                          color: "var(--text-muted)",
                          cursor: "pointer",
                        }}
                      >
                        ↔
                      </button>
                    )}
                  </td>
                  <td style={{
                    padding: "12px",
                    textAlign: "right",
                    whiteSpace: "nowrap",
                    fontWeight: 600,
                    color: row.Credit_Amount && row.Credit_Amount > 0 ? "var(--emerald-inflow)" : "var(--text-muted)",
                  }}>
                    {row.Credit_Amount && row.Credit_Amount > 0 ? formatCurrency(row.Credit_Amount) : "—"}
                    {onEditDirection && (row.Debit_Amount || 0) > 0 && (
                      <button
                        onClick={() => onEditDirection(row)}
                        title="Flip this transaction between debit and credit"
                        style={{
                          marginLeft: "8px",
                          padding: "1px 6px",
                          fontSize: "0.68rem",
                          background: "transparent",
                          border: "1px solid var(--border-subtle)",
                          borderRadius: "4px",
                          color: "var(--text-muted)",
                          cursor: "pointer",
                        }}
                      >
                        ↔
                      </button>
                    )}
                  </td>
                  <td style={{
                    padding: "12px",
                    textAlign: "right",
                    whiteSpace: "nowrap",
                    color: "var(--blue-balance)",
                    fontWeight: 500,
                  }}>
                    {row.Closing_Balance !== null ? formatCurrency(row.Closing_Balance) : "—"}
                  </td>
                  <td style={{
                    padding: "12px",
                    fontFamily: "monospace",
                    fontSize: "0.75rem",
                    color: "var(--text-muted)",
                    maxWidth: "140px",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}>
                    {row.Chq_Ref_Number}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination Bar — shown whenever there is anything to page through, so
          the controls never vanish while the user is on a non-first page. */}
      {total > 0 && (
        <div style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginTop: "16px",
          paddingTop: "12px",
          borderTop: "1px solid var(--border-subtle)",
          flexWrap: "wrap",
          gap: "12px",
        }}>
          <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
            Page {page} of {totalPages} ({formatNumber(total)} items)
          </span>

          <div style={{ display: "flex", gap: "6px" }}>
            <button
              className="btn btn-secondary"
              onClick={() => onChangePage(Math.max(1, page - 1))}
              disabled={page <= 1 || isLoading}
              style={{ padding: "4px 10px", fontSize: "0.8rem" }}
            >
              ← Previous
            </button>
            <button
              className="btn btn-secondary"
              onClick={() => onChangePage(Math.min(totalPages, page + 1))}
              disabled={page >= totalPages || isLoading}
              style={{ padding: "4px 10px", fontSize: "0.8rem" }}
            >
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
