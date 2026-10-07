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
  const settlementsHidden = settlements > 0 && (kpis?.settlement_count ?? 0) === 0;
  const count = kpis?.filtered_count ?? 0;
  const totalCount = kpis?.total_count ?? 0;
  const netColor = net >= 0 ? "var(--emerald-inflow)" : "var(--rose-outflow)";

  return (
    <div className="kpi-grid">
      <div className="glass-panel kpi-tile" style={{ borderTopColor: "var(--emerald-inflow)" }}>
        <div className="kpi-head">
          <span className="kpi-label">Total Credits (Inflow)</span>
          <span className="kpi-icon" style={{ background: "rgba(16, 185, 129, 0.15)", color: "var(--emerald-inflow)" }}>
            ↓
          </span>
        </div>
        <div className="kpi-value text-inflow">
          {isLoading ? "..." : formatCurrency(credits)}
        </div>
        <div className="kpi-note">Total deposits &amp; income inflows</div>
      </div>

      <div className="glass-panel kpi-tile" style={{ borderTopColor: "var(--rose-outflow)" }}>
        <div className="kpi-head">
          <span className="kpi-label">Total Debits (Outflow)</span>
          <span className="kpi-icon" style={{ background: "rgba(244, 63, 94, 0.15)", color: "var(--rose-outflow)" }}>
            ↑
          </span>
        </div>
        <div className="kpi-value text-outflow">
          {isLoading ? "..." : formatCurrency(debits)}
        </div>
        <div className="kpi-note">Withdrawals, expenses &amp; card bill payments</div>
        {/* In the combined view the card payment's two halves are both present,
            so they are left out of the tiles (and out of the category charts) to
            avoid counting the same purchase twice. Scoped to one ledger only one
            half exists, so it is counted above and no note is needed. */}
        {settlementsHidden && (
          <div
            className="kpi-excluded"
            title="Card bill payments are a transfer between your bank and the card. Both halves are in this view, so they are excluded from the totals and from the category charts to avoid counting the purchase twice."
          >
            excl. {formatCurrency(settlements)} card bill payments
          </div>
        )}
      </div>

      <div className="glass-panel kpi-tile" style={{ borderTopColor: netColor }}>
        <div className="kpi-head">
          <span className="kpi-label">Net Cash Flow</span>
          <span
            className="kpi-icon"
            style={{
              background: net >= 0 ? "rgba(16, 185, 129, 0.15)" : "rgba(244, 63, 94, 0.15)",
              color: netColor,
            }}
          >
            {net >= 0 ? "▲" : "▼"}
          </span>
        </div>
        <div className="kpi-value" style={{ color: netColor }}>
          {isLoading ? "..." : formatCurrency(net)}
        </div>
        <div className="kpi-note">
          {net >= 0 ? "Net surplus for selected range" : "Net deficit for selected range"}
        </div>
      </div>

      <div className="glass-panel kpi-tile" style={{ borderTopColor: "var(--accent-indigo)" }}>
        <div className="kpi-head">
          <span className="kpi-label">Transactions Found</span>
          <span className="kpi-icon" style={{ background: "rgba(99, 102, 241, 0.15)", color: "var(--accent-indigo)" }}>
            📄
          </span>
        </div>
        <div className="kpi-value text-primary">
          {isLoading ? "..." : formatNumber(count)}
        </div>
        <div className="kpi-note">
          {formatNumber(count)} of {formatNumber(totalCount)} total stored
        </div>
      </div>
    </div>
  );
}