"use client";

import React from "react";
import { KPIs } from "@/types";
import { formatCurrency, formatNumber } from "@/lib/formatters";

interface KpiCardsProps {
  kpis?: KPIs;
  isLoading?: boolean;
}

export default function KpiCards({ kpis, isLoading }: KpiCardsProps) {
  const credits = kpis?.total_credits ?? 0;
  const debits = kpis?.total_debits ?? 0;
  const net = kpis?.net_cashflow ?? 0;
  // A card bill payment is two halves of one transfer. They are only dropped
  // from these tiles in the COMBINED view, where both halves are present and
  // counting them would double count. Scoped to one ledger the other half is
  // absent, so the one here is counted - as inflow on the card, as outflow on
  // the bank - and the tiles agree with the cashflow chart.
  const settlements =
    Math.abs(kpis?.settlement_debits ?? 0) + Math.abs(kpis?.settlement_credits ?? 0);
  // True when these tiles excluded them, which the category charts always do.
  const settlementsHidden =
    settlements > 0 && (kpis?.settlement_count ?? 0) === 0;
  const count = kpis?.filtered_count ?? 0;
  const totalCount = kpis?.total_count ?? 0;

  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
      gap: "16px",
      marginBottom: "24px"
    }}>
      {/* Total Credits */}
      <div className="glass-panel" style={{
        padding: "20px",
        position: "relative",
        overflow: "hidden",
        borderTop: "3px solid var(--emerald-inflow)"
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
          <span style={{ fontSize: "0.825rem", fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Total Credits (Inflow)
          </span>
          <span style={{
            background: "rgba(16, 185, 129, 0.15)",
            color: "var(--emerald-inflow)",
            borderRadius: "50%",
            width: "32px",
            height: "32px",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: "1rem"
          }}>
            ↓
          </span>
        </div>
        <div style={{ fontSize: "1.75rem", fontWeight: 700, color: "var(--emerald-inflow)", letterSpacing: "-0.02em" }}>
          {isLoading ? "..." : formatCurrency(credits)}
        </div>
        <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "4px" }}>
          Total deposits & income inflows
        </div>
      </div>

      {/* Total Debits */}
      <div className="glass-panel" style={{
        padding: "20px",
        position: "relative",
        overflow: "hidden",
        borderTop: "3px solid var(--rose-outflow)"
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
          <span style={{ fontSize: "0.825rem", fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Total Debits (Outflow)
          </span>
          <span style={{
            background: "rgba(244, 63, 94, 0.15)",
            color: "var(--rose-outflow)",
            borderRadius: "50%",
            width: "32px",
            height: "32px",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: "1rem"
          }}>
            ↑
          </span>
        </div>
        <div style={{ fontSize: "1.75rem", fontWeight: 700, color: "var(--rose-outflow)", letterSpacing: "-0.02em" }}>
          {isLoading ? "..." : formatCurrency(debits)}
        </div>
        <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "4px" }}>
          Withdrawals, expenses & card bill payments
        </div>
        {/* In the combined view the card payment's two halves are both present,
            so they are left out of the tiles (and out of the category charts) to
            avoid counting the same purchase twice. Scoped to one ledger only one
            half exists, so it is counted above and no note is needed. */}
        {settlementsHidden && (
          <div
            style={{
              fontSize: "0.7rem",
              color: "var(--text-muted)",
              marginTop: "6px",
              paddingTop: "6px",
              borderTop: "1px solid rgba(255,255,255,0.08)",
            }}
            title="Card bill payments are a transfer between your bank and the card. Both halves are in this view, so they are excluded from the totals and from the category charts to avoid counting the purchase twice."
          >
            excl. {formatCurrency(settlements)} card bill payments
          </div>
        )}
      </div>

      {/* Net Cash Flow */}
      <div className="glass-panel" style={{
        padding: "20px",
        position: "relative",
        overflow: "hidden",
        borderTop: `3px solid ${net >= 0 ? "var(--emerald-inflow)" : "var(--rose-outflow)"}`
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
          <span style={{ fontSize: "0.825rem", fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Net Cash Flow
          </span>
          <span style={{
            background: net >= 0 ? "rgba(16, 185, 129, 0.15)" : "rgba(244, 63, 94, 0.15)",
            color: net >= 0 ? "var(--emerald-inflow)" : "var(--rose-outflow)",
            borderRadius: "50%",
            width: "32px",
            height: "32px",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: "1rem"
          }}>
            {net >= 0 ? "▲" : "▼"}
          </span>
        </div>
        <div style={{
          fontSize: "1.75rem",
          fontWeight: 700,
          color: net >= 0 ? "var(--emerald-inflow)" : "var(--rose-outflow)",
          letterSpacing: "-0.02em"
        }}>
          {isLoading ? "..." : formatCurrency(net)}
        </div>
        <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "4px" }}>
          {net >= 0 ? "Net surplus for selected range" : "Net deficit for selected range"}
        </div>
      </div>

      {/* Transaction Count */}
      <div className="glass-panel" style={{
        padding: "20px",
        position: "relative",
        overflow: "hidden",
        borderTop: "3px solid var(--accent-indigo)"
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
          <span style={{ fontSize: "0.825rem", fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Transactions Found
          </span>
          <span style={{
            background: "rgba(99, 102, 241, 0.15)",
            color: "var(--accent-indigo)",
            borderRadius: "50%",
            width: "32px",
            height: "32px",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: "1rem"
          }}>
            📄
          </span>
        </div>
        <div style={{ fontSize: "1.75rem", fontWeight: 700, color: "var(--text-primary)", letterSpacing: "-0.02em" }}>
          {isLoading ? "..." : formatNumber(count)}
        </div>
        <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "4px" }}>
          {formatNumber(count)} of {formatNumber(totalCount)} total stored
        </div>
      </div>
    </div>
  );
}
