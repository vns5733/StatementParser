"use client";

import React from "react";
import { KPIs, MetaCard } from "@/types";
import { formatCurrency, formatNumber } from "@/lib/formatters";

/**
 * Card-framed labels for the shared KPI figures.
 *
 * The shared `KpiCards` row calls them "Total Credits" and "Total Debits",
 * which is right for a bank. On a card it is not: a credit is a refund or a bill
 * payment, never income, and a debit is a purchase, never an expense plus the
 * bill that settles it. Rather than swap the shared component out for a bespoke
 * one - which would let the two views drift - the shared row is kept and these
 * tiles sit directly beneath it, re-labelling the same numbers honestly.
 *
 * Rendered only when the ledger scope is a card, because that is the only
 * reading in which these labels are the accurate ones.
 */
function StatTile({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "inflow" | "outflow" | "default";
}) {
  const color =
    tone === "inflow"
      ? "var(--emerald-inflow)"
      : tone === "outflow"
        ? "var(--rose-outflow)"
        : "var(--text-primary)";
  return (
    <div className="glass-panel" style={{ padding: "16px", borderTop: `3px solid ${color}` }}>
      <div className="kpi-label">{label}</div>
      <div style={{ fontSize: "1.4rem", fontWeight: 700, color, marginTop: "6px" }}>
        {value}
      </div>
      {hint && <div className="kpi-note">{hint}</div>}
    </div>
  );
}

export default function CardTiles({
  kpis,
  isLoading,
  cards,
  cardIds,
}: {
  kpis?: KPIs;
  isLoading?: boolean;
  cards: MetaCard[];
  cardIds: string[];
}) {
  // "Card Spend" must match the category charts beside it, so it is the
  // settlement-excluded figure. The other tiles describe the card's cash flow,
  // where a bill payment IS a credit and belongs - so they use the
  // settlement-inclusive credits the KPI reports.
  const spend = kpis?.total_spend_debits ?? 0;
  const refunds = kpis?.total_credits ?? 0;
  // Card-side bill payments. In this view the bank-side half is not present, so
  // there is no double count and the payment is genuine inflow.
  const payments = kpis?.settlement_credits ?? 0;

  const label =
    cardIds.length === 0
      ? "All cards"
      : cardIds.length === 1
        ? cards.find((c) => c.Card_ID === cardIds[0])?.Card_Name || "1 card"
        : `${cardIds.length} cards`;

  const val = (n: number) => (isLoading ? "..." : n);

  return (
    <div className="kpi-grid">
      <StatTile
        label="Card Spend"
        value={val(spend) === "..." ? "..." : formatCurrency(spend)}
        hint={`${label} · purchases only`}
        tone="outflow"
      />
      <StatTile
        label="Refunds & Reversals"
        value={val(refunds) === "..." ? "..." : formatCurrency(refunds)}
        hint="Credits posted back to the card"
        tone="inflow"
      />
      {/* Paying the bill is money coming IN on a card. It is excluded from Card
          Spend (it is a transfer, not a purchase) but it is real inflow, so it
          gets its own tile rather than being hidden. */}
      <StatTile
        label="Bill Payments"
        value={val(payments) === "..." ? "..." : formatCurrency(payments)}
        hint="Paid toward the card balance"
        tone="inflow"
      />
      <StatTile
        label="Net Card Spend"
        value={val(spend - refunds) === "..." ? "..." : formatCurrency(spend - refunds)}
        hint="Spend minus refunds"
        tone={spend - refunds >= 0 ? "outflow" : "inflow"}
      />
      <StatTile
        label="Rows Analysed"
        value={val(kpis?.filtered_count ?? 0) === "..." ? "..." : formatNumber(kpis?.filtered_count ?? 0)}
        hint={
          (kpis?.settlement_count ?? 0) > 0
            ? `${kpis?.spend_count} purchases + ${kpis?.settlement_count} payments`
            : "Purchases only"
        }
      />
    </div>
  );
}