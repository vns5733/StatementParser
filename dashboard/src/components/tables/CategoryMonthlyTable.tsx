"use client";

import React, { useMemo } from "react";
import { MonthlyCategoryEntry } from "@/types";
import { formatCurrency, formatNumber } from "@/lib/formatters";

interface CategoryMonthlyTableProps {
  /** Month-by-month aggregates, as returned by the monthly-category summary. */
  data: MonthlyCategoryEntry[];
  category: string;
  selectedPeriod: string | null;
  onSelectPeriod: (period: string | null) => void;
  isLoading?: boolean;
}

interface MonthRow {
  label: string;
  Total_Credit: number;
  Total_Debit: number;
  Count: number;
}

export default function CategoryMonthlyTable({
  data,
  category,
  selectedPeriod,
  onSelectPeriod,
  isLoading,
}: CategoryMonthlyTableProps) {
  // The summary endpoint groups by (period × Broad_Category), so each month comes
  // back once per category — 16 rows for 2026-07 alone. This table is a *monthly*
  // breakdown, so fold the categories into one row per month first. Keying the raw
  // rows by month would also collide, and React drops or duplicates them.
  const months = useMemo<MonthRow[]>(() => {
    const totals = new Map<string, MonthRow>();
    for (const entry of data || []) {
      const current = totals.get(entry.label);
      if (current) {
        current.Total_Credit += entry.Total_Credit || 0;
        current.Total_Debit += entry.Total_Debit || 0;
        current.Count += entry.Count || 0;
      } else {
        totals.set(entry.label, {
          label: entry.label,
          Total_Credit: entry.Total_Credit || 0,
          Total_Debit: entry.Total_Debit || 0,
          Count: entry.Count || 0,
        });
      }
    }
    return Array.from(totals.values()).sort((a, b) => a.label.localeCompare(b.label));
  }, [data]);

  if (isLoading) {
    return (
<div className="glass-panel" style={{ padding: "20px" }}>
        <div style={{ padding: "30px 0", textAlign: "center", color: "var(--text-muted)" }}>
          Loading monthly breakdown...
        </div>
      </div>
    );
  }

  if (!months.length) return null;

  return (
    <div className="glass-panel" style={{ padding: "20px", marginTop: "16px" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "12px",
          flexWrap: "wrap",
          gap: "10px",
        }}
      >
        <div>
          <h4 style={{ fontSize: "1rem", fontWeight: 700, color: "var(--text-primary)" }}>
            ##### Monthly Breakdown — {category}
          </h4>
          <p style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
            Click a month to list its transactions below.
          </p>
        </div>
        {selectedPeriod && (
          <button
            className="btn btn-secondary"
            onClick={() => onSelectPeriod(null)}
            style={{ padding: "4px 10px", fontSize: "0.75rem" }}
          >
            Clear selection ✕
          </button>
        )}
      </div>

      <div style={{ overflowX: "auto", maxHeight: "360px", overflowY: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border-subtle)", textAlign: "left", position: "sticky", top: 0, background: "var(--bg-card-solid)" }}>
              <th style={{ padding: "10px", color: "var(--text-muted)", fontWeight: 600 }}>Month</th>
              <th style={{ padding: "10px", color: "var(--text-muted)", fontWeight: 600, textAlign: "right" }}>
                Debit (₹)
              </th>
              <th style={{ padding: "10px", color: "var(--text-muted)", fontWeight: 600, textAlign: "right" }}>
                Credit (₹)
              </th>
              <th style={{ padding: "10px", color: "var(--text-muted)", fontWeight: 600, textAlign: "right" }}>
                Net Flow
              </th>
              <th style={{ padding: "10px", color: "var(--text-muted)", fontWeight: 600, textAlign: "right" }}>
                Count
              </th>
            </tr>
          </thead>
          <tbody>
            {months.map((row) => {
              const isSelected = selectedPeriod === row.label;
              const net = row.Total_Credit - row.Total_Debit;
              return (
                <tr
                  key={row.label}
                  onClick={() => onSelectPeriod(isSelected ? null : row.label)}
                  style={{
                    borderBottom: "1px solid rgba(255, 255, 255, 0.03)",
                    cursor: "pointer",
                    background: isSelected ? "rgba(99, 102, 241, 0.2)" : "transparent",
                    transition: "background 0.15s ease",
                  }}
                  onMouseEnter={(e) => {
                    if (!isSelected) e.currentTarget.style.background = "rgba(255, 255, 255, 0.03)";
                  }}
                  onMouseLeave={(e) => {
                    if (!isSelected) e.currentTarget.style.background = "transparent";
                  }}
                >
                  <td style={{ padding: "10px", fontWeight: 600, color: "var(--text-primary)" }}>
                    {row.label}
                  </td>
                  <td style={{ padding: "10px", textAlign: "right", color: "var(--rose-outflow)", fontWeight: 600 }}>
                    {formatCurrency(row.Total_Debit)}
                  </td>
                  <td style={{ padding: "10px", textAlign: "right", color: "var(--emerald-inflow)", fontWeight: 600 }}>
                    {formatCurrency(row.Total_Credit)}
                  </td>
                  <td
                    style={{
                      padding: "10px",
                      textAlign: "right",
                      fontWeight: 700,
                      color: net >= 0 ? "var(--emerald-inflow)" : "var(--rose-outflow)",
                    }}
                  >
                    {formatCurrency(net)}
                  </td>
                  <td style={{ padding: "10px", textAlign: "right", color: "var(--text-muted)" }}>
                    {formatNumber(row.Count)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
