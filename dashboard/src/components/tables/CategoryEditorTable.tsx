"use client";

import React, { useState } from "react";
import { Transaction, CascadeMode, PreviewRuleResponse, ApplyCascadeRequest } from "@/types";
import { formatCurrency, formatDate, formatNumber } from "@/lib/formatters";
import { useClampPage } from "@/hooks/useClampPage";
import CascadeModal, { PendingEdit } from "@/components/modals/CascadeModal";
import SortableHeader from "@/components/tables/SortableHeader";

const CATEGORY_SELECT = {
  padding: "6px 10px",
  fontSize: "0.825rem",
  background: "rgba(99, 102, 241, 0.12)",
  borderColor: "rgba(99, 102, 241, 0.35)",
  fontWeight: 600,
  cursor: "pointer",
  width: "100%",
} as const;

interface CategoryEditorTableProps {
  transactions: Transaction[];
  total: number;
  page: number;
  pageSize: number;
  onChangePage: (p: number) => void;
  selectedCategory: string;
  onlySelectedCategory: boolean;
  onToggleOnlyCategory: (val: boolean) => void;
  categories: string[];
  /** All known leaves for the sub-category dropdown. */
  subCategories: string[];
  search: string;
  onSearchChange: (q: string) => void;
  sortBy: string;
  sortOrder: "asc" | "desc";
  onSortChange: (col: string, order: "asc" | "desc") => void;
  onPreviewRule: (mode: CascadeMode, key: string) => Promise<PreviewRuleResponse>;
  onApplyCascade: (request: ApplyCascadeRequest) => Promise<any>;
  onRefresh: () => void;
  isLoading?: boolean;
}

export default function CategoryEditorTable({
  transactions,
  total,
  page,
  pageSize,
  onChangePage,
  selectedCategory,
  onlySelectedCategory,
  onToggleOnlyCategory,
  categories,
  subCategories,
  search,
  onSearchChange,
  sortBy,
  sortOrder,
  onSortChange,
  onPreviewRule,
  onApplyCascade,
  onRefresh,
  isLoading,
}: CategoryEditorTableProps) {
  const [pendingEdits, setPendingEdits] = useState<PendingEdit[]>([]);
  const [isModalOpen, setIsModalOpen] = useState(false);

  const totalPages = useClampPage(page, pageSize, total, onChangePage, isLoading);

  const handleCategorySelect = (row: Transaction, newCategory: string, newSub?: string) => {
    const sub = newSub === undefined ? row.Sub_Category : newSub;
    if (newCategory === row.Broad_Category && sub === row.Sub_Category) return;

    const edit: PendingEdit = {
      chq_ref: row.Chq_Ref_Number,
      payee: row.Payee_Receiver,
      narration: row.Narration,
      new_category: newCategory,
      new_sub_category: sub,
      old_category: row.Broad_Category,
      old_sub_category: row.Sub_Category,
    };

    setPendingEdits([edit]);
    setIsModalOpen(true);
  };

  const SortHeader = ({
    col,
    label,
    align = "left",
  }: {
    col: string;
    label: string;
    align?: "left" | "right";
  }) => (
    <SortableHeader
      col={col}
      label={label}
      align={align}
      sortBy={sortBy}
      sortOrder={sortOrder}
      onSortChange={onSortChange}
    />
  );

  return (
    <div className="glass-panel" style={{ padding: "24px" }}>
      {/* Header and Toolbar */}
      <div style={{ marginBottom: "18px" }}>
        <div style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          flexWrap: "wrap",
          gap: "14px",
          marginBottom: "12px",
        }}>
          <div>
            <h3 style={{ fontSize: "1.15rem", fontWeight: 700, color: "var(--text-primary)" }}>
              ✏️ Reassign Transaction Categories
            </h3>
            <p style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginTop: "2px" }}>
              Edit the category dropdown for any row. A preview dialog will show all affected transactions before applying.
            </p>
          </div>

          {/* Quick search input */}
          <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
            <input
              type="text"
              placeholder="Search narration / payee..."
              className="input"
              style={{ width: "240px", fontSize: "0.85rem" }}
              value={search}
              onChange={(e) => onSearchChange(e.target.value)}
            />
          </div>
        </div>

        {/* Filter Toggle Row */}
        <div style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "10px 14px",
          background: "rgba(99, 102, 241, 0.08)",
          border: "1px solid rgba(99, 102, 241, 0.2)",
          borderRadius: "var(--radius-md)",
          flexWrap: "wrap",
          gap: "12px",
        }}>
          <label style={{
            display: "flex",
            alignItems: "center",
            gap: "10px",
            cursor: "pointer",
            fontWeight: 600,
            fontSize: "0.875rem",
            color: "var(--text-primary)",
          }}>
            <input
              type="checkbox"
              checked={onlySelectedCategory}
              onChange={(e) => onToggleOnlyCategory(e.target.checked)}
              style={{ width: "16px", height: "16px", cursor: "pointer", accentColor: "var(--accent-indigo)" }}
            />
            <span>
              Only show{" "}
              {selectedCategory ? (
                <>
                  <strong style={{ color: "var(--accent-indigo)" }}>"{selectedCategory}"</strong>{" "}
                  transactions
                </>
              ) : (
                <>
                  <strong style={{ color: "var(--text-muted)" }}>a selected category&apos;s</strong>{" "}
                  transactions
                </>
              )}{" "}
              in the editor
            </span>
          </label>

          <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
            Showing <strong>{transactions.length}</strong> of <strong>{total}</strong> matching transaction(s)
          </span>
        </div>
      </div>

      {/* Transactions Table */}
      <div style={{ overflowX: "auto", minHeight: "280px" }}>
        {isLoading ? (
          <div style={{ padding: "50px 0", textAlign: "center", color: "var(--text-muted)", fontSize: "0.9rem" }}>
            ⏳ Loading transactions...
          </div>
        ) : transactions.length === 0 ? (
          <div style={{ padding: "50px 0", textAlign: "center", color: "var(--text-muted)", fontSize: "0.9rem" }}>
            No transactions found {onlySelectedCategory && selectedCategory ? `for category "${selectedCategory}"` : ""}.
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border-subtle)", textAlign: "left" }}>
                <SortHeader col="Date" label="Date" />
                <SortHeader col="Narration" label="Narration" />
                <SortHeader col="Payee_Receiver" label="Payee / Entity" />
                <SortHeader col="Debit_Amount" label="Debit (₹)" align="right" />
                <SortHeader col="Credit_Amount" label="Credit (₹)" align="right" />
                <th style={{ padding: "10px 12px", color: "var(--text-muted)", fontWeight: 600, width: "180px" }}>
                  Parent / Category
                </th>
                <th style={{ padding: "10px 12px", color: "var(--text-muted)", fontWeight: 600, width: "170px" }}>
                  Sub-Category
                </th>
              </tr>
            </thead>
            <tbody>
              {transactions.map((row) => (
                <tr
                  key={row.Chq_Ref_Number}
                  style={{ borderBottom: "1px solid rgba(255, 255, 255, 0.03)" }}
                >
                  <td style={{ padding: "10px 12px", whiteSpace: "nowrap", color: "var(--text-secondary)" }}>
                    {formatDate(row.Date)}
                  </td>
                  <td style={{ padding: "10px 12px", maxWidth: "300px", color: "var(--text-primary)" }}>
                    <div style={{ wordBreak: "break-word" }}>{row.Narration}</div>
                  </td>
                  <td style={{ padding: "10px 12px", color: "var(--text-secondary)", maxWidth: "180px" }}>
                    <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={row.Payee_Receiver || ""}>
                      {row.Payee_Receiver || "—"}
                    </div>
                  </td>
                  <td style={{
                    padding: "10px 12px",
                    textAlign: "right",
                    fontWeight: 600,
                    color: row.Debit_Amount && row.Debit_Amount > 0 ? "var(--rose-outflow)" : "var(--text-muted)",
                  }}>
                    {row.Debit_Amount && row.Debit_Amount > 0 ? formatCurrency(row.Debit_Amount) : "—"}
                  </td>
                  <td style={{
                    padding: "10px 12px",
                    textAlign: "right",
                    fontWeight: 600,
                    color: row.Credit_Amount && row.Credit_Amount > 0 ? "var(--emerald-inflow)" : "var(--text-muted)",
                  }}>
                    {row.Credit_Amount && row.Credit_Amount > 0 ? formatCurrency(row.Credit_Amount) : "—"}
                  </td>
                  <td style={{ padding: "10px 12px" }}>
                    <div
                      style={{
                        fontSize: "0.65rem",
                        color: "var(--text-muted)",
                        textTransform: "uppercase",
                        letterSpacing: "0.04em",
                      }}
                      title={`Parent rollup: ${row.Category}`}
                    >
                      {row.Category || "—"}
                    </div>
                    <select
                      className="select"
                      value={row.Broad_Category || "Uncategorized"}
                      onChange={(e) =>
                        handleCategorySelect(row, e.target.value, row.Sub_Category)
                      }
                      style={CATEGORY_SELECT}
                    >
                      {categories.map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td style={{ padding: "10px 12px" }}>
                    <select
                      className="select"
                      value={row.Sub_Category || row.Broad_Category || "Uncategorized"}
                      onChange={(e) =>
                        handleCategorySelect(row, row.Broad_Category, e.target.value)
                      }
                      style={CATEGORY_SELECT}
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
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination Footer */}
      <div style={{
        marginTop: "16px",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        flexWrap: "wrap",
        gap: "10px",
      }}>
        <div style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>
          Page {page} of {totalPages} ({formatNumber(total)} total transactions)
        </div>
        <div style={{ display: "flex", gap: "8px" }}>
          <button
            className="btn btn-secondary"
            style={{ padding: "6px 14px", fontSize: "0.85rem" }}
            onClick={() => onChangePage(Math.max(1, page - 1))}
            disabled={page <= 1 || isLoading}
          >
            ‹ Previous
          </button>
          <button
            className="btn btn-secondary"
            style={{ padding: "6px 14px", fontSize: "0.85rem" }}
            onClick={() => onChangePage(Math.min(totalPages, page + 1))}
            disabled={page >= totalPages || isLoading}
          >
            Next ›
          </button>
        </div>
      </div>

      {/* Cascade Modal with Preview */}
      <CascadeModal
        isOpen={isModalOpen}
        pendingEdits={pendingEdits}
        subCategories={subCategories}
        onClose={() => setIsModalOpen(false)}
        onPreviewRule={onPreviewRule}
        onApplyCascade={async (req) => {
          await onApplyCascade(req);
          onRefresh();
        }}
      />
    </div>
  );
}
