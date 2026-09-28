"use client";

import React, { useState, useEffect } from "react";
import {
  Filters,
  Transaction,
  CascadeMode,
  PreviewRuleResponse,
  ApplyCascadeRequest,
} from "@/types";
import { useKPIs, useTransactions } from "@/hooks/useTransactions";
import { useClampPage } from "@/hooks/useClampPage";
import { formatCurrency, formatDate, formatNumber } from "@/lib/formatters";
import CascadeModal, { PendingEdit } from "@/components/modals/CascadeModal";

const CATEGORY_SELECT = {
  padding: "6px 10px",
  fontSize: "0.825rem",
  background: "rgba(99, 102, 241, 0.12)",
  borderColor: "rgba(99, 102, 241, 0.35)",
  fontWeight: 600,
  cursor: "pointer",
  width: "100%",
} as const;

interface DrilldownPanelProps {
  /** Human-readable period, e.g. "2024-03". */
  periodLabel: string;
  /** Filters already scoped to the drilled-into period (yearMonths set). */
  periodFilters: Filters;
  availableTxnTypes: string[];
  categories: string[];
  /** All known leaves for the inline sub-category dropdown. */
  subCategories: string[];
  onPreviewRule: (mode: CascadeMode, key: string) => Promise<PreviewRuleResponse>;
  onApplyCascade: (request: ApplyCascadeRequest) => Promise<any>;
  onRefresh: () => void;
}

const MetricCard = ({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "inflow" | "outflow" | "default";
}) => {
  const color =
    tone === "inflow"
      ? "var(--emerald-inflow)"
      : tone === "outflow"
      ? "var(--rose-outflow)"
      : "var(--text-primary)";
  return (
    <div
      style={{
        padding: "12px",
        background: "rgba(255, 255, 255, 0.02)",
        borderRadius: "var(--radius-md)",
      }}
    >
      <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>{label}</div>
      <div style={{ fontSize: "1.15rem", fontWeight: 700, color }}>{value}</div>
    </div>
  );
};

export default function DrilldownPanel({
  periodLabel,
  periodFilters,
  availableTxnTypes,
  categories,
  subCategories,
  onPreviewRule,
  onApplyCascade,
  onRefresh,
}: DrilldownPanelProps) {
  // In-view filters layered on top of the period scope
  const [direction, setDirection] = useState<"all" | "debits" | "credits">("all");
  const [search, setSearch] = useState("");
  const [txnTypes, setTxnTypes] = useState<string[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  const [pendingEdits, setPendingEdits] = useState<PendingEdit[]>([]);
  const [isModalOpen, setIsModalOpen] = useState(false);

  const filters: Filters = {
    ...periodFilters,
    direction,
    search: search.trim(),
    txnTypes,
  };

  const { kpis, isLoading: kpiLoading } = useKPIs(filters);
  const { transactionsPage, isLoading } = useTransactions(filters, page, pageSize);

  const totalPages = useClampPage(
    page,
    pageSize,
    transactionsPage?.total ?? 0,
    setPage,
    isLoading
  );

  // Switching periods replaces the whole result set. Carry over neither the page
  // number nor the in-view filters — they belonged to the previous period and
  // would otherwise show an out-of-range (or wrongly filtered) page.
  useEffect(() => {
    setPage(1);
    setSearch("");
    setDirection("all");
    setTxnTypes([]);
  }, [periodLabel]);

  const resetPaging = () => setPage(1);

  const handleCategorySelect = (row: Transaction, newCategory: string, newSub?: string) => {
    const sub = newSub === undefined ? row.Sub_Category : newSub;
    if (newCategory === row.Broad_Category && sub === row.Sub_Category) return;
    setPendingEdits([
      {
        chq_ref: row.Chq_Ref_Number,
        payee: row.Payee_Receiver,
        narration: row.Narration,
        new_category: newCategory,
        new_sub_category: sub,
        old_category: row.Broad_Category,
        old_sub_category: row.Sub_Category,
      },
    ]);
    setIsModalOpen(true);
  };

  // The drill-down table below lists spend rows, so the period debits must be the
  // spend figure too, or the header will not add up to its own table. Both
  // exclude card settlements, which this period view does not show.
  const credits = kpis?.total_credits ?? 0;
  const debits = kpis?.total_spend_debits ?? 0;

  return (
    <div className="glass-panel" style={{ padding: "20px", marginTop: "16px" }}>
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "10px",
          marginBottom: "14px",
        }}
      >
        <div>
          <h3 style={{ fontSize: "1.1rem", fontWeight: 700, color: "var(--text-primary)" }}>
            🔎 Transactions for {periodLabel}
          </h3>
          <p style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
            Narrow this period further, edit any category inline, or export the whole set.
          </p>
        </div>
        <TransactionTableCsv filters={filters} periodLabel={periodLabel} />
      </div>

      {/* In-view filters */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: "12px",
          marginBottom: "14px",
        }}
      >
        <div>
          <label
            style={{
              display: "block",
              fontSize: "0.75rem",
              color: "var(--text-muted)",
              marginBottom: "6px",
            }}
          >
            Direction
          </label>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr 1fr",
              gap: "4px",
              background: "var(--bg-input)",
              padding: "3px",
              borderRadius: "var(--radius-md)",
              border: "1px solid var(--border-subtle)",
            }}
          >
            {(["all", "debits", "credits"] as const).map((dir) => (
              <button
                key={dir}
                onClick={() => {
                  setDirection(dir);
                  resetPaging();
                }}
                style={{
                  padding: "5px 0",
                  fontSize: "0.75rem",
                  fontWeight: 600,
                  border: "none",
                  borderRadius: "var(--radius-sm)",
                  cursor: "pointer",
                  background: direction === dir ? "var(--accent-indigo)" : "transparent",
                  color: direction === dir ? "#fff" : "var(--text-muted)",
                }}
              >
                {dir === "all" ? "All" : dir === "debits" ? "Debits" : "Credits"}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label
            style={{
              display: "block",
              fontSize: "0.75rem",
              color: "var(--text-muted)",
              marginBottom: "6px",
            }}
          >
            Transaction Type
          </label>
          <select
            className="select"
            multiple
            value={txnTypes}
            onChange={(e) => {
              setTxnTypes(Array.from(e.target.selectedOptions, (o) => o.value));
              resetPaging();
            }}
            style={{ height: "84px", fontSize: "0.8rem" }}
          >
            {availableTxnTypes.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label
            style={{
              display: "block",
              fontSize: "0.75rem",
              color: "var(--text-muted)",
              marginBottom: "6px",
            }}
          >
            Search Narration / Payee / Ref
          </label>
          <input
            type="text"
            className="input"
            placeholder="e.g. UPI, Amazon, Rent..."
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              resetPaging();
            }}
            style={{ fontSize: "0.8rem" }}
          />
        </div>
      </div>

      {/* Period KPIs */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
          gap: "12px",
          marginBottom: "16px",
        }}
      >
        <MetricCard label="Credits" value={formatCurrency(credits)} tone="inflow" />
        <MetricCard label="Debits" value={formatCurrency(debits)} tone="outflow" />
        <MetricCard
          label="Net Flow"
          value={formatCurrency(credits - debits)}
          tone={credits - debits >= 0 ? "inflow" : "outflow"}
        />
        <MetricCard
          label="Transactions"
          value={kpiLoading ? "…" : formatNumber(kpis?.filtered_count ?? 0)}
        />
      </div>

      {/* Table */}
      <div style={{ overflowX: "auto", minHeight: "200px" }}>
        {isLoading ? (
          <div style={{ padding: "40px 0", textAlign: "center", color: "var(--text-muted)" }}>
            Loading transactions...
          </div>
        ) : (transactionsPage?.data.length ?? 0) === 0 ? (
          <div style={{ padding: "40px 0", textAlign: "center", color: "var(--text-muted)" }}>
            No transactions in {periodLabel} match the current filters.
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border-subtle)", textAlign: "left" }}>
                <th style={{ padding: "10px 12px", color: "var(--text-muted)", fontWeight: 600, width: "110px" }}>
                  Date
                </th>
                <th style={{ padding: "10px 12px", color: "var(--text-muted)", fontWeight: 600 }}>
                  Narration
                </th>
                <th style={{ padding: "10px 12px", color: "var(--text-muted)", fontWeight: 600 }}>
                  Type
                </th>
                <th style={{ padding: "10px 12px", color: "var(--text-muted)", fontWeight: 600, width: "180px" }}>
                  Payee / Entity
                </th>
                <th
                  style={{
                    padding: "10px 12px",
                    color: "var(--text-muted)",
                    fontWeight: 600,
                    textAlign: "right",
                  }}
                >
                  Debit (₹)
                </th>
                <th
                  style={{
                    padding: "10px 12px",
                    color: "var(--text-muted)",
                    fontWeight: 600,
                    textAlign: "right",
                  }}
                >
                  Credit (₹)
                </th>
                <th style={{ padding: "10px 12px", color: "var(--text-muted)", fontWeight: 600, width: "180px" }}>
                  Category
                </th>
              </tr>
            </thead>
            <tbody>
              {(transactionsPage?.data ?? []).map((row) => (
                <tr key={row.Chq_Ref_Number} style={{ borderBottom: "1px solid rgba(255, 255, 255, 0.03)" }}>
                  <td style={{ padding: "10px 12px", whiteSpace: "nowrap", color: "var(--text-secondary)" }}>
                    {formatDate(row.Date)}
                  </td>
                  <td style={{ padding: "10px 12px", maxWidth: "280px", color: "var(--text-primary)" }}>
                    <div style={{ wordBreak: "break-word" }}>{row.Narration}</div>
                  </td>
                  <td style={{ padding: "10px 12px", whiteSpace: "nowrap" }}>
                    <span className="badge badge-indigo">{row.Transaction_Type || "UNKNOWN"}</span>
                  </td>
                  <td style={{ padding: "10px 12px", color: "var(--text-secondary)", maxWidth: "180px" }}>
                    <div
                      style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                      title={row.Payee_Receiver || ""}
                    >
                      {row.Payee_Receiver || "—"}
                    </div>
                  </td>
                  <td
                    style={{
                      padding: "10px 12px",
                      textAlign: "right",
                      fontWeight: 600,
                      whiteSpace: "nowrap",
                      color: row.Debit_Amount && row.Debit_Amount > 0 ? "var(--rose-outflow)" : "var(--text-muted)",
                    }}
                  >
                    {row.Debit_Amount && row.Debit_Amount > 0 ? formatCurrency(row.Debit_Amount) : "—"}
                  </td>
                  <td
                    style={{
                      padding: "10px 12px",
                      textAlign: "right",
                      fontWeight: 600,
                      whiteSpace: "nowrap",
                      color:
                        row.Credit_Amount && row.Credit_Amount > 0
                          ? "var(--emerald-inflow)"
                          : "var(--text-muted)",
                    }}
                  >
                    {row.Credit_Amount && row.Credit_Amount > 0 ? formatCurrency(row.Credit_Amount) : "—"}
                  </td>
                  <td style={{ padding: "10px 12px" }}>
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

      {/* Pagination */}
      <div
        style={{
          marginTop: "14px",
          paddingTop: "12px",
          borderTop: "1px solid var(--border-subtle)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "10px",
        }}
      >
        <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
          Page {page} of {totalPages} ({formatNumber(transactionsPage?.total ?? 0)} transactions)
        </span>
        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          <select
            className="select"
            value={pageSize}
            onChange={(e) => {
              setPageSize(Number(e.target.value));
              setPage(1);
            }}
            style={{ width: "auto", fontSize: "0.8rem", padding: "6px 10px" }}
          >
            <option value={25}>25 / page</option>
            <option value={50}>50 / page</option>
            <option value={100}>100 / page</option>
          </select>
          <button
            className="btn btn-secondary"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1 || isLoading}
            style={{ padding: "6px 12px", fontSize: "0.8rem" }}
          >
            ‹ Previous
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages || isLoading}
            style={{ padding: "6px 12px", fontSize: "0.8rem" }}
          >
            Next ›
          </button>
        </div>
      </div>

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

/**
 * CSV export button bound to the drill-down's own (narrowed) filter set, so the
 * file contains exactly the rows visible in the panel.
 */
function TransactionTableCsv({ filters, periodLabel }: { filters: Filters; periodLabel: string }) {
  const [isExporting, setIsExporting] = React.useState(false);

  const handleExport = async () => {
    setIsExporting(true);
    try {
      const { downloadFilteredCSV } = await import("@/lib/api");
      await downloadFilteredCSV(filters);
    } catch (err: any) {
      alert(err?.response?.data?.detail || err?.message || "CSV export failed");
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <button
      className="btn btn-secondary"
      onClick={handleExport}
      disabled={isExporting}
      style={{ fontSize: "0.8rem" }}
      title={`Export the ${periodLabel} transactions as CSV`}
    >
      {isExporting ? "Preparing..." : `📥 Download ${periodLabel} CSV`}
    </button>
  );
}
