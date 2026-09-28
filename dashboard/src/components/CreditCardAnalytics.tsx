"use client";

/**
 * Unified credit-card analytics — the card equivalent of the bank statement view.
 *
 * Card purchases are projected into the shared `transactions` table with
 * Account_Source='CREDIT_CARD' (Design Decision 16), so this deliberately reuses
 * the same hooks and chart components as the bank tabs rather than building a
 * parallel aggregate. That is what makes the two views agree by construction: a
 * card purchase charts here with the same numbers, under the same category
 * hierarchy, as it does in the bank view.
 *
 * Two scoping rules matter:
 *
 *  - Settlements are excluded from spend. A card bill payment is the same money
 *    as the purchases it settles, so counting both would report every purchase
 *    twice. The API excludes them for every aggregate this panel reads.
 *  - Refunds are real inflows on a card, so the inflow/outflow charts are shown
 *    as-is rather than netted. Net is still reported, as spend minus refunds.
 */
import React, { useMemo, useState, useEffect } from "react";

import KpiCards from "@/components/KpiCards";
import TimelineChart from "@/components/charts/TimelineChart";
import CategoryStackChart from "@/components/charts/CategoryStackChart";
import PieChart from "@/components/charts/PieChart";
import SummaryTable from "@/components/tables/SummaryTable";
import DrilldownPanel from "@/components/tables/DrilldownPanel";
import TransactionTable from "@/components/tables/TransactionTable";
import CascadeModal, { PendingEdit } from "@/components/modals/CascadeModal";

import {
  useKPIs,
  useTimelineSummary,
  useMonthlyCategorySummary,
  useCategoryBreakdown,
  useTransactions,
} from "@/hooks/useTransactions";
import type {
  CascadeMode,
  Filters,
  GroupBy,
  GroupCol,
  Meta,
  PreviewRuleResponse,
  ApplyCascadeRequest,
  Transaction,
} from "@/types";
import { formatCurrency, formatNumber } from "@/lib/formatters";

interface CreditCardAnalyticsProps {
  /** The shared sidebar filters (years, months, categories, search, ...). */
  baseFilters: Filters;
  meta: Meta | undefined;
  categories: string[];
  subCategories: string[];
  onPreviewRule: (mode: CascadeMode, key: string) => Promise<PreviewRuleResponse>;
  onApplyCascade: (request: ApplyCascadeRequest) => Promise<any>;
  onRefresh: () => void;
}

/** Metric tile for the card-specific KPIs below the shared KPI row. */
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
    <div
      className="glass-panel"
      style={{ padding: "16px", borderTop: `3px solid ${color}` }}
    >
      <div
        style={{
          fontSize: "0.75rem",
          fontWeight: 600,
          color: "var(--text-muted)",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
        }}
      >
        {label}
      </div>
      <div style={{ fontSize: "1.4rem", fontWeight: 700, color, marginTop: "6px" }}>
        {value}
      </div>
      {hint && (
        <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "4px" }}>
          {hint}
        </div>
      )}
    </div>
  );
}

export default function CreditCardAnalytics({
  baseFilters,
  meta,
  categories,
  subCategories,
  onPreviewRule,
  onApplyCascade,
  onRefresh,
}: CreditCardAnalyticsProps) {
  // Empty = every card. This picker is the only filter the panel owns; the
  // sidebar's filters still apply, so the two compose rather than conflict.
  const [cardIds, setCardIds] = useState<string[]>([]);
  const [groupBy, setGroupBy] = useState<GroupBy>("month");
  const [pieGroupBy, setPieGroupBy] = useState<GroupCol>("Broad_Category");
  const [selectedPeriod, setSelectedPeriod] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  // Category correction on the card ledger. The drill-down panel has its own
  // editor, but it only appears once a period is selected - so without this the
  // main card table was read-only, and a mis-categorised card row (the issuer's
  // description is often truncated, so the parser guesses) could not be fixed
  // from the view the user was already looking at.
  const [pendingEdits, setPendingEdits] = useState<PendingEdit[]>([]);
  const [isCascadeOpen, setIsCascadeOpen] = useState(false);

  const handleCategoryChange = (
    row: Transaction,
    newCategory: string,
    newSub?: string
  ) => {
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
    setIsCascadeOpen(true);
  };

  const cards = meta?.cards ?? [];

  // The card ledger only.
  //
  // `spendBasis` is deliberately forced to "all" rather than inherited. The
  // sidebar's basis is a *combined-view* control: picking "bank only" there means
  // "show me my bank spending", and honouring it here would empty this panel of
  // every row, because account_sources=CREDIT_CARD and spend_basis=bank_only
  // select disjoint sets. Settlement exclusion is unaffected - the aggregates
  // pass exclude_settlements=True independently of spend_basis, so card spend
  // still excludes bill payments.
  //
  // Every other sidebar filter (years, months, categories, search, amount range)
  // is inherited, so the two scopes compose instead of fighting.
  const filters: Filters = useMemo(
    () => ({ ...baseFilters, spendBasis: "all", accountSources: ["CREDIT_CARD"], cardIds }),
    [baseFilters, cardIds]
  );

  // Changing the card replaces the result set, so a deep page number from the
  // previous scope would otherwise land on an empty table.
  const scopeKey = cardIds.join(",");
  useEffect(() => {
    setPage(1);
    setSelectedPeriod(null);
  }, [scopeKey]);

  const ready = Boolean(meta);
  const { kpis, isLoading: kpisLoading } = useKPIs(filters, ready);
  const { timeline, isLoading: timelineLoading } = useTimelineSummary(filters, groupBy, ready);
  const { monthlyCategoryData, isLoading: catStackLoading } =
    useMonthlyCategorySummary(filters, groupBy, ready);
  const { categoryBreakdown, isLoading: pieLoading } = useCategoryBreakdown(
    filters,
    pieGroupBy,
    ready
  );
  const { transactionsPage, isLoading: txLoading } = useTransactions(
    filters,
    page,
    pageSize,
    "",
    "desc",
    ready
  );

  // Scope a drill-down to the clicked period. A "2024-03" label resolves to an
  // exact Year_Month so it does not bleed across every March on record.
  const drillFilters: Filters = useMemo(() => {
    if (!selectedPeriod) return filters;
    if (/^\d{4}-\d{2}$/.test(selectedPeriod)) {
      return { ...filters, yearMonths: [selectedPeriod] };
    }
    if (/^\d{4}$/.test(selectedPeriod)) {
      return { ...filters, years: [Number(selectedPeriod)], yearMonths: undefined };
    }
    return filters;
  }, [selectedPeriod, filters]);

  // "Card Spend" must match the category charts beside it, so it is the
  // settlement-excluded figure. The other tiles describe the card's cash flow,
  // where a bill payment IS a credit and belongs - so they use the
  // settlement-inclusive credits the KPI reports.
  const spend = kpis?.total_spend_debits ?? 0;
  const refunds = kpis?.total_credits ?? 0;
  // Card-side bill payments. In this view the bank-side half is not present, so
  // there is no double count and the payment is genuine inflow.
  const payments = kpis?.settlement_credits ?? 0;
  const selectedLabel =
    cardIds.length === 0
      ? "All cards"
      : cards.find((c) => c.Card_ID === cardIds[0])?.Card_Name || "1 card";

  // No card rows at all: say so explicitly rather than rendering an empty set of
  // charts, which is indistinguishable from a broken filter.
  if (ready && cards.length === 0) {
    return (
      <div className="glass-panel" style={{ padding: "32px", textAlign: "center" }}>
        <div style={{ fontSize: "1.1rem", fontWeight: 700, color: "var(--text-primary)" }}>
          No credit-card transactions found
        </div>
        <p style={{ fontSize: "0.875rem", color: "var(--text-muted)", marginTop: "8px" }}>
          Import card statement PDFs with <code>python ingest_cards.py</code>, then this
          view fills in automatically alongside the bank statement data.
        </p>
      </div>
    );
  }

  return (
    <div>
      {/* Card picker. Multi-select via toggle buttons so several cards can be
          compared in one view; each chip shows how many rows it contributes. */}
      <div className="glass-panel" style={{ padding: "20px", marginBottom: "24px" }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: "14px",
            flexWrap: "wrap",
            gap: "10px",
          }}
        >
          <div>
            <h3
              style={{ fontSize: "1.1rem", fontWeight: 700, color: "var(--text-primary)" }}
            >
              Credit Card Intelligence
            </h3>
            <p style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
              Spend, refunds and category breakdown — read from the same ledger as the
              bank statement view
            </p>
          </div>
          {cardIds.length > 0 && (
            <button
              className="btn btn-secondary"
              onClick={() => setCardIds([])}
              style={{ padding: "4px 10px", fontSize: "0.75rem" }}
            >
              Show all cards ✕
            </button>
          )}
        </div>

        <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
          {cards.map((card) => {
            const active = cardIds.includes(card.Card_ID);
            return (
              <button
                key={card.Card_ID}
                onClick={() =>
                  setCardIds((prev) =>
                    prev.includes(card.Card_ID)
                      ? prev.filter((id) => id !== card.Card_ID)
                      : [...prev, card.Card_ID]
                  )
                }
                style={{
                  padding: "8px 14px",
                  fontSize: "0.825rem",
                  fontWeight: 600,
                  borderRadius: "var(--radius-md)",
                  cursor: "pointer",
                  background: active ? "var(--accent-indigo)" : "rgba(255, 255, 255, 0.05)",
                  color: active ? "#fff" : "var(--text-secondary)",
                  border: "1px solid",
                  borderColor: active ? "var(--accent-indigo)" : "var(--border-subtle)",
                }}
              >
                {card.Card_Name || "Unnamed card"}
                {card.Card_Issuer ? (
                  <span style={{ opacity: 0.75, fontWeight: 400, marginLeft: "6px" }}>
                    {card.Card_Issuer}
                  </span>
                ) : null}
                <span
                  style={{
                    marginLeft: "8px",
                    fontSize: "0.7rem",
                    opacity: 0.75,
                    fontWeight: 400,
                  }}
                >
                  {formatNumber(card.Txn_Count)}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Shared KPI row, scoped to cards. */}
      <KpiCards kpis={kpis} isLoading={kpisLoading} />

      {/* Card-specific framing of the same totals. The shared KPI row labels
          these "Credits"/"Debits", which is right for a bank but understates
          what a card's two sides mean: a credit is a refund or a bill payment,
          not income. */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: "16px",
          marginBottom: "24px",
        }}
      >
        <StatTile
          label="Card Spend"
          value={kpisLoading ? "..." : formatCurrency(spend)}
          hint={`${selectedLabel} · purchases only`}
          tone="outflow"
        />
        <StatTile
          label="Refunds & Reversals"
          value={kpisLoading ? "..." : formatCurrency(refunds)}
          hint="Credits posted back to the card"
          tone="inflow"
        />
        {/* New in the card view: paying the bill is money coming IN on the card.
            It is excluded from Card Spend (it is a transfer, not a purchase) but
            it is real inflow, so it gets its own tile rather than being hidden. */}
        <StatTile
          label="Bill Payments"
          value={kpisLoading ? "..." : formatCurrency(payments)}
          hint="Paid toward the card balance"
          tone="inflow"
        />
        <StatTile
          label="Net Card Spend"
          value={kpisLoading ? "..." : formatCurrency(spend - refunds)}
          hint="Spend minus refunds"
          tone={spend - refunds >= 0 ? "outflow" : "inflow"}
        />
        <StatTile
          label="Rows Analysed"
          value={kpisLoading ? "..." : formatNumber(kpis?.filtered_count ?? 0)}
          hint={
            (kpis?.settlement_count ?? 0) > 0
              ? `${kpis?.spend_count} purchases + ${kpis?.settlement_count} payments`
              : "Purchases only"
          }
        />
      </div>

      {/* Inflow vs outflow over time */}
      <TimelineChart
        data={timeline}
        groupBy={groupBy}
        onChangeGroupBy={setGroupBy}
        isLoading={timelineLoading}
      />

      {/* Category-wise breakdown */}
      <CategoryStackChart data={monthlyCategoryData} isLoading={catStackLoading} />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(400px, 1fr))",
          gap: "20px",
          marginBottom: "24px",
        }}
      >
        <PieChart
          data={categoryBreakdown}
          groupBy={pieGroupBy}
          onChangeGroupBy={setPieGroupBy}
          isLoading={pieLoading}
        />
      </div>

      <SummaryTable
        data={timeline}
        groupBy={groupBy}
        selectedLabel={selectedPeriod}
        onSelectPeriod={setSelectedPeriod}
      />

      {selectedPeriod && (
        <DrilldownPanel
          periodLabel={selectedPeriod}
          periodFilters={drillFilters}
          availableTxnTypes={meta?.txn_types ?? []}
          categories={categories}
          subCategories={subCategories}
          onPreviewRule={onPreviewRule}
          onApplyCascade={onApplyCascade}
          onRefresh={onRefresh}
        />
      )}

      {/* Full card transaction list, exported through the same server-side CSV
          endpoint the bank explorer uses, so the download is the whole filtered
          set rather than the visible page. */}
      <TransactionTable
        data={transactionsPage?.data || []}
        total={transactionsPage?.total || 0}
        page={page}
        pageSize={pageSize}
        onChangePage={setPage}
        onChangePageSize={(sz) => {
          setPageSize(sz);
          setPage(1);
        }}
        isLoading={txLoading}
        exportFilters={filters}
        exportLabel="Download Card CSV"
        onCategoryChange={handleCategoryChange}
        categories={categories}
        subCategories={subCategories}
      />

      {/* Same cascade modal the bank-side editors use, so a card correction can
          be scoped to this transaction, the same merchant, or a narration
          keyword, with per-row exclusions. */}
      <CascadeModal
        isOpen={isCascadeOpen}
        pendingEdits={pendingEdits}
        subCategories={subCategories}
        onClose={() => setIsCascadeOpen(false)}
        onPreviewRule={onPreviewRule}
        onApplyCascade={async (req) => {
          await onApplyCascade(req);
          onRefresh();
        }}
      />
    </div>
  );
}
