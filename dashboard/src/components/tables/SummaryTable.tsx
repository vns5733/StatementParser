"use client";

import React from "react";
import { TimelineEntry, GroupBy } from "@/types";
import { formatCurrency, formatNumber } from "@/lib/formatters";

interface SummaryTableProps {
  data: TimelineEntry[];
  groupBy: GroupBy;
  selectedLabel: string | null;
  onSelectPeriod: (label: string | null) => void;
}

export default function SummaryTable({
  data,
  groupBy,
  selectedLabel,
  onSelectPeriod,
}: SummaryTableProps) {
  if (!data || data.length === 0) return null;

  return (
    <div className="glass-panel" style={{ padding: "20px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
        <div>
          <h3 style={{ fontSize: "1.1rem", fontWeight: 700, color: "var(--text-primary)" }}>
            Summary by {groupBy === "month" ? "Month" : "Year"}
          </h3>
          <p style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
            Click on any row below to drill down into its individual transactions
          </p>
        </div>
        {selectedLabel && (
          <button
            className="btn btn-secondary"
            onClick={() => onSelectPeriod(null)}
            style={{ padding: "4px 10px", fontSize: "0.75rem" }}
          >
            Clear selection ✕
          </button>
        )}
      </div>

      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.875rem" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border-subtle)", textAlign: "left" }}>
              <th style={{ padding: "10px", color: "var(--text-muted)", fontWeight: 600 }}>Period</th>
              <th style={{ padding: "10px", color: "var(--text-muted)", fontWeight: 600, textAlign: "right" }}>Total Credit</th>
              <th style={{ padding: "10px", color: "var(--text-muted)", fontWeight: 600, textAlign: "right" }}>Total Debit</th>
              <th style={{ padding: "10px", color: "var(--text-muted)", fontWeight: 600, textAlign: "right" }}>Net Flow</th>
              <th style={{ padding: "10px", color: "var(--text-muted)", fontWeight: 600, textAlign: "right" }}>Count</th>
            </tr>
          </thead>
          <tbody>
            {data.map((row) => {
              const isSelected = selectedLabel === row.label;
              const net = row.Total_Credit - row.Total_Debit;

              return (
                <tr
                  key={row.label}
                  onClick={() => onSelectPeriod(isSelected ? null : row.label)}
                  style={{
                    borderBottom: "1px solid rgba(255, 255, 255, 0.03)",
                    cursor: "pointer",
                    background: isSelected
                      ? "rgba(99, 102, 241, 0.2)"
                      : "transparent",
                    transition: "background 0.15s ease",
                  }}
                  onMouseEnter={(e) => {
                    if (!isSelected) e.currentTarget.style.background = "rgba(255, 255, 255, 0.03)";
                  }}
                  onMouseLeave={(e) => {
                    if (!isSelected) e.currentTarget.style.background = "transparent";
                  }}
                >
                  <td style={{ padding: "12px 10px", fontWeight: 600, color: "var(--text-primary)" }}>
                    {row.label}
                  </td>
                  <td style={{ padding: "12px 10px", textAlign: "right", color: "var(--emerald-inflow)", fontWeight: 600 }}>
                    {formatCurrency(row.Total_Credit)}
                  </td>
                  <td style={{ padding: "12px 10px", textAlign: "right", color: "var(--rose-outflow)", fontWeight: 600 }}>
                    {formatCurrency(row.Total_Debit)}
                  </td>
                  <td style={{
                    padding: "12px 10px",
                    textAlign: "right",
                    fontWeight: 700,
                    color: net >= 0 ? "var(--emerald-inflow)" : "var(--rose-outflow)"
                  }}>
                    {formatCurrency(net)}
                  </td>
                  <td style={{ padding: "12px 10px", textAlign: "right", color: "var(--text-muted)" }}>
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
