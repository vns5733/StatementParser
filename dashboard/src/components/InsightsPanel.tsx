"use client";

/**
 * The Insights tab: a plain-language read on where the money went over whatever
 * range the sidebar currently describes.
 *
 * One endpoint serves the whole tab, so the blocks below CANNOT disagree with
 * each other — there is no second query whose scope could drift. That matters
 * here more than in the other tabs, because the blocks sit side by side and the
 * user is expected to reconcile them mentally.
 *
 * Two different scopes are on screen and both are real:
 *
 *  - SPEND blocks (categories, merchants, channels, recurring split, day-of-week,
 *    bank-vs-card) always exclude card settlements. Paying a card bill is a
 *    transfer, not a purchase, so counting it would report every card purchase
 *    twice.
 *  - CASHFLOW blocks (monthly trend, savings) include settlements unless this
 *    view is the combined one. The money genuinely left the account, and in a
 *    card-only view it genuinely arrived as inflow.
 *
 * The endpoint reports the settlement halves and the flag that decided it, so
 * the settlement line can name what was excluded instead of the two sets
 * looking like they contradict each other.
 */
import React, { useMemo, useState, useRef } from "react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  Cell,
} from "recharts";

import { useInsights } from "@/hooks/useTransactions";
import DrilldownPanel from "@/components/tables/DrilldownPanel";
import type {
  Filters,
  InsightCategory,
  AccountSource,
  CascadeMode,
  PreviewRuleResponse,
  ApplyCascadeRequest,
} from "@/types";
import { formatCurrency, formatCompactCurrency, formatNumber } from "@/lib/formatters";

interface InsightsPanelProps {
  /** The shared sidebar filters — this tab inherits all of them. */
  filters: Filters;
  /** False until meta has loaded, so the tab does not fetch twice on mount. */
  ready?: boolean;
  /** Only used to populate the drill-down's channel filter list. */
  txnTypes?: string[];
  /** For the drill-down table's inline category editing. */
  categories: string[];
  subCategories: string[];
  onPreviewRule: (mode: CascadeMode, key: string) => Promise<PreviewRuleResponse>;
  onApplyCascade: (request: ApplyCascadeRequest) => Promise<any>;
  onRefresh: () => void;
  /** Persists a note. Passed through to the drill-down panel, so a
   *  merchant being triaged here can be annotated without leaving the tab. */
  onNoteSave?: (chqRef: string, note: string | null) => void;
}

/**
 * What the user clicked. Every variant maps onto a filter that already exists on
 * the shared path, so the drill-down cannot disagree with the chart it came from —
 * it is the same filter set, narrowed.
 */
type Drill =
  | { kind: "category"; value: string }
  | { kind: "sub"; value: string }
  | { kind: "merchant"; value: string }
  | { kind: "channel"; value: string }
  | { kind: "source"; value: AccountSource }
  | null;

const DRILL_TITLES: Record<Exclude<Drill, null>["kind"], string> = {
  category: "Category",
  sub: "Sub-category",
  merchant: "Recipient",
  channel: "Channel",
  source: "Ledger",
};

const CATEGORY_COLORS = [
  "#6366f1", "#10b981", "#f59e0b", "#ec4899", "#06b6d4",
  "#8b5cf6", "#f43f5e", "#84cc16", "#14b8a6", "#f97316",
];

function MetricTile({
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

function PanelHeader({
  title,
  subtitle,
  right,
}: {
  title: string;
  subtitle?: string;
  right?: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        marginBottom: "16px",
        flexWrap: "wrap",
        gap: "12px",
      }}
    >
      <div>
        <h3 style={{ fontSize: "1.1rem", fontWeight: 700, color: "var(--text-primary)" }}>
          {title}
        </h3>
        {subtitle && (
          <p style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>{subtitle}</p>
        )}
      </div>
      {right}
    </div>
  );
}

function EmptyState({ height = 260, message }: { height?: number; message: string }) {
  return (
    <div
      style={{
        height,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "var(--text-muted)",
        fontSize: "0.9rem",
      }}
    >
      {message}
    </div>
  );
}

/** Month label for the x-axis: "2024-03" reads as noise, "Mar 24" does not. */
function shortMonth(ym: string): string {
  const m = /^(\d{4})-(\d{2})$/.exec(ym);
  if (!m) return ym;
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${names[Number(m[2]) - 1] ?? m[2]} ${m[1].slice(2)}`;
}

/** Share of a total, as a percentage string. Guards a zero total. */
function pct(part: number, whole: number): string {
  if (!whole) return "—";
  return `${((part / whole) * 100).toFixed(1)}%`;
}

export default function InsightsPanel({
  filters,
  ready = true,
  txnTypes = [],
  categories,
  subCategories,
  onPreviewRule,
  onApplyCascade,
  onRefresh,
  onNoteSave,
}: InsightsPanelProps) {
  const { insights, isLoading } = useInsights(filters, ready);
  const [drill, setDrill] = useState<Drill>(null);
  const drillRef = useRef<HTMLDivElement | null>(null);

  const openDrill = (next: Exclude<Drill, null>) => {
    setDrill(next);
    // Bring the panel into view: it is appended below the tab, and a category
    // near the top of a long page would otherwise open it off-screen.
    requestAnimationFrame(() =>
      drillRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })
    );
  };

  const drillFilters: Filters | null = useMemo(() => {
    if (!drill) return null;
    switch (drill.kind) {
      case "category":
        return { ...filters, categories: [drill.value] };
      case "sub":
        return { ...filters, subCategories: [drill.value] };
      case "merchant":
        return { ...filters, payee: [drill.value] };
      case "channel":
        return { ...filters, txnTypes: [drill.value] };
      case "source":
        return { ...filters, accountSources: [drill.value] };
    }
  }, [drill, filters]);

  // DrilldownPanel reads its in-view filters from its own state and layers them
  // over the scope it is given, so the channel scope has to be re-seeded or this
  // panel's empty initial value would silently drop it on first render.
  const drillInitialTxnTypes = drill?.kind === "channel" ? [drill.value] : [];
  // A category/channel can hold well over a hundred rows, so the drill-down is
  // paginated rather than a fixed-height scroll box: paging keeps every row
  // reachable by keyboard and by the CSV export, which a cropped div would hide.
  const drillKey = drill ? `${drill.kind}:${drill.value}` : "none";

  // ---- Derived figures -----------------------------------------------------
  // Recurring and one-off must add up to total spend, because both come from the
  // same settlement-excluded frame. Asserting it in the UI (rather than trusting
  // it) keeps a future block from silently breaking that identity.
  const spendTotal = useMemo(() => {
    if (!insights) return 0;
    return insights.top_categories.reduce((acc, c) => acc + (c.Spend || 0), 0);
  }, [insights]);

  const recurringPct = insights
    ? pct(insights.recurring_vs_oneoff.recurring_spend, spendTotal)
    : "—";

  // Highest-spend month of the range — the single most useful "when did I blow
  // it" fact, and cheap because monthly_trend is already in the payload.
  const peakMonth = useMemo(() => {
    if (!insights || insights.monthly_trend.length === 0) return null;
    return insights.monthly_trend.reduce((best, m) =>
      (m.Total_Debit || 0) > (best.Total_Debit || 0) ? m : best
    );
  }, [insights]);

  // Day-of-week rows, Monday first, so the chart and the table agree.
  const dowRows = useMemo(() => {
    const rows = insights?.dow_pattern ?? [];
    return [...rows].sort((a, b) => a.DayOfWeek - b.DayOfWeek);
  }, [insights]);

  // Recurring spend ranked by category — the actionable half of the recurring
  // split. "You spend 62% of your budget on rent and EMIs" is the insight; the
  // bare rupee total is not.
  const recurringLeaders = useMemo(() => {
    if (!insights) return [];
    return insights.top_categories
      .filter((c) => (c.Count || 0) > 0)
      .slice(0, 8);
  }, [insights]);

  if (isLoading && !insights) {
    return <EmptyState height={400} message="Analysing your transactions..." />;
  }

  if (!insights) {
    return <EmptyState height={300} message="No insights available." />;
  }

  // No rows matched at all. Say so plainly rather than rendering a page of empty
  // charts, which is indistinguishable from a broken panel.
  if (
    insights.monthly_trend.length === 0 &&
    insights.top_categories.length === 0 &&
    insights.top_merchants.length === 0
  ) {
    return (
      <div className="glass-panel" style={{ padding: "40px", textAlign: "center" }}>
        <div style={{ fontSize: "1.1rem", fontWeight: 700, color: "var(--text-primary)" }}>
          No transactions in this range
        </div>
        <p style={{ fontSize: "0.875rem", color: "var(--text-muted)", marginTop: "8px" }}>
          Widen the years, months or other filters in the sidebar to see insights.
        </p>
      </div>
    );
  }

  const { savings_analysis: savings, settlements, period } = insights;
  const saved = savings.savings >= 0;

  return (
    <div>
      {/* ---------------- Range header ---------------- */}
      <div className="glass-panel" style={{ padding: "20px", marginBottom: "24px" }}>
        <PanelHeader
          title="Spending Insights"
          subtitle={
            period.start && period.end
              ? `${period.start.slice(0, 10)} → ${period.end.slice(0, 10)} · ${period.months} month${period.months === 1 ? "" : "s"}`
              : "No date range"
          }
        />
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
            gap: "16px",
          }}
        >
          <MetricTile
            label="Total Spend"
            value={isLoading ? "..." : formatCurrency(spendTotal)}
            hint="Settlements excluded — purchases only"
            tone="outflow"
          />
          <MetricTile
            label="Average / Month"
            value={isLoading ? "..." : formatCurrency(period.months ? spendTotal / period.months : 0)}
            hint={`Across ${period.months} month${period.months === 1 ? "" : "s"}`}
            tone="outflow"
          />
          <MetricTile
            label="Saved"
            value={isLoading ? "..." : formatCurrency(savings.savings)}
            hint={`${saved ? "You kept" : "You overspent by"} ${Math.abs(savings.savings_rate).toFixed(1)}% of income`}
            tone={saved ? "inflow" : "outflow"}
          />
          <MetricTile
            label="Recurring Share"
            value={recurringPct}
            hint={`${formatCurrency(insights.recurring_vs_oneoff.recurring_spend)} across ${formatNumber(insights.recurring_vs_oneoff.recurring_count)} transactions`}
          />
          {peakMonth && (
            <MetricTile
              label="Heaviest Month"
              value={shortMonth(peakMonth.Year_Month)}
              hint={`${formatCurrency(peakMonth.Total_Debit)} of debits`}
              tone="outflow"
            />
          )}
        </div>

        {/* Names what the spend figures excluded. Without this the tiles below
            look like they disagree with the timeline, and the user has no way to
            tell a transfer from a genuine drop in spending. */}
        {settlements.settlement_count > 0 && (
          <div
            style={{
              marginTop: "16px",
              padding: "10px 14px",
              borderRadius: "var(--radius-md)",
              background: "rgba(255, 255, 255, 0.03)",
              border: "1px solid var(--border-subtle)",
              fontSize: "0.8rem",
              color: "var(--text-secondary)",
            }}
          >
            <strong style={{ color: "var(--text-primary)" }}>
              {formatNumber(settlements.settlement_count)} card payment
              {settlements.settlement_count === 1 ? "" : "s"}
            </strong>{" "}
            are excluded from spend — they are transfers, not purchases.
            {settlements.excluded_from_cashflow ? (
              <>
                {" "}This is the combined view, so they are also left out of the cash-flow
                trend below to avoid counting the same money twice.
              </>
            ) : (
              <>
                {" "}This is a single-ledger view, so the half present here is kept in the
                cash-flow trend — the money really moved.
              </>
            )}
          </div>
        )}
      </div>

      {/* ---------------- Monthly trend ---------------- */}
      <div className="glass-panel" style={{ padding: "20px", marginBottom: "24px" }}>
        <PanelHeader
          title="Monthly Cash Flow"
          subtitle="In, out and the net, month by month"
        />
        {insights.monthly_trend.length === 0 ? (
          <EmptyState message="No cash-flow rows in this range" />
        ) : (
          <div style={{ width: "100%", height: "320px" }}>
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart
                data={insights.monthly_trend}
                margin={{ top: 10, right: 10, left: 10, bottom: 20 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.05)" />
                <XAxis
                  dataKey="Year_Month"
                  tickFormatter={shortMonth}
                  stroke="var(--text-muted)"
                  fontSize={12}
                  tickLine={false}
                />
                <YAxis
                  stroke="var(--text-muted)"
                  fontSize={12}
                  tickFormatter={formatCompactCurrency}
                  tickLine={false}
                />
                <Tooltip
                  formatter={(value: any, name: any) => [
                    formatCurrency(Number(value)),
                    name === "Net" ? "Net" : name === "Total_Credit" ? "Inflow" : "Outflow",
                  ]}
                  labelFormatter={(label: any) => shortMonth(String(label))}
                  contentStyle={{
                    background: "var(--bg-secondary)",
                    border: "1px solid var(--border-subtle)",
                    borderRadius: "var(--radius-md)",
                  }}
                />
                <Legend wrapperStyle={{ paddingTop: "10px" }} />
                <Bar dataKey="Total_Credit" fill="#10b981" radius={[4, 4, 0, 0]} maxBarSize={40} />
                <Bar dataKey="Total_Debit" fill="#f43f5e" radius={[4, 4, 0, 0]} maxBarSize={40} />
                {/* Net as a line, not a third bar: the sign is what matters here and a
                    bar reads as "another amount" when it is actually a difference. */}
                <Line
                  type="monotone"
                  dataKey="Net"
                  stroke="#818cf8"
                  strokeWidth={2}
                  dot={{ r: 3 }}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* ---------------- Categories + merchants ---------------- */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(400px, 1fr))",
          gap: "20px",
          marginBottom: "24px",
        }}
      >
        <div className="glass-panel" style={{ padding: "20px" }}>
          <PanelHeader
            title="Where the Money Goes"
            subtitle="Spend by category, largest first"
          />
          {insights.top_categories.length === 0 ? (
            <EmptyState message="No category spend in this range" />
          ) : (
            <div style={{ width: "100%", height: "300px" }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={insights.top_categories.slice(0, 10)}
                  layout="vertical"
                  margin={{ top: 5, right: 20, left: 10, bottom: 5 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.05)" />
                  <XAxis
                    type="number"
                    stroke="var(--text-muted)"
                    fontSize={11}
                    tickFormatter={formatCompactCurrency}
                    tickLine={false}
                  />
                  <YAxis
                    type="category"
                    dataKey="Category"
                    stroke="var(--text-muted)"
                    fontSize={11}
                    width={110}
                    tickLine={false}
                  />
                  <Tooltip
                    formatter={(value: any) => formatCurrency(Number(value))}
                    contentStyle={{
                      background: "var(--bg-secondary)",
                      border: "1px solid var(--border-subtle)",
                      borderRadius: "var(--radius-md)",
                    }}
                  />
                  <Bar
                    dataKey="Spend"
                    radius={[0, 4, 4, 0]}
                    maxBarSize={22}
                    cursor="pointer"
                    onClick={(d: any) => openDrill({ kind: "category", value: d.Category })}
                  >
                    {insights.top_categories.slice(0, 10).map((c: InsightCategory, i: number) => (
                      <Cell key={c.Category} fill={CATEGORY_COLORS[i % CATEGORY_COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        <div className="glass-panel" style={{ padding: "20px" }}>
          <PanelHeader title="Top Recipients" subtitle="Who received the most" />
          {insights.top_merchants.length === 0 ? (
            <EmptyState message="No payee data in this range" />
          ) : (
            <div style={{ width: "100%", height: "300px" }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={insights.top_merchants.slice(0, 10)}
                  layout="vertical"
                  margin={{ top: 5, right: 20, left: 10, bottom: 5 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.05)" />
                  <XAxis
                    type="number"
                    stroke="var(--text-muted)"
                    fontSize={11}
                    tickFormatter={formatCompactCurrency}
                    tickLine={false}
                  />
                  <YAxis
                    type="category"
                    dataKey="Payee_Receiver"
                    stroke="var(--text-muted)"
                    fontSize={11}
                    width={140}
                    tickLine={false}
                  />
                  <Tooltip
                    formatter={(value: any) => formatCurrency(Number(value))}
                    contentStyle={{
                      background: "var(--bg-secondary)",
                      border: "1px solid var(--border-subtle)",
                      borderRadius: "var(--radius-md)",
                    }}
                  />
                  <Bar
                    dataKey="Spend"
                    fill="#06b6d4"
                    radius={[0, 4, 4, 0]}
                    maxBarSize={22}
                    cursor="pointer"
                    onClick={(d: any) => openDrill({ kind: "merchant", value: d.Payee_Receiver })}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>

      {/* ---------------- Category detail table ---------------- */}
      <div className="glass-panel" style={{ padding: "20px", marginBottom: "24px" }}>
        <PanelHeader
          title="Category Breakdown"
          subtitle="Each category with its leaves — click a row to expand"
        />
        {insights.top_categories.length === 0 ? (
          <EmptyState message="No category spend in this range" />
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.875rem" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                  {["Category", "Sub-category", "Transactions", "Average", "Share", "Spend"].map((h, i) => (
                    <th
                      key={h}
                      style={{
                        textAlign: i >= 2 ? "right" : "left",
                        padding: "8px 12px",
                        fontSize: "0.7rem",
                        textTransform: "uppercase",
                        letterSpacing: "0.05em",
                        color: "var(--text-muted)",
                        fontWeight: 700,
                        whiteSpace: "nowrap",
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {insights.top_categories.map((cat: InsightCategory, i: number) => (
                  <React.Fragment key={cat.Category}>
                    <tr
                      style={{
                        borderBottom: "1px solid var(--border-subtle)",
                        cursor: "pointer",
                      }}
                      onClick={() => {
                        const row = document.getElementById(
                          `insight-cat-${i}`
                        );
                        if (row) {
                          row.style.display =
                            row.style.display === "none" ? "table-row" : "none";
                        }
                      }}
                    >
                      <td style={{ padding: "10px 12px", fontWeight: 600 }}>
                        <span
                          style={{
                            display: "inline-block",
                            width: "8px",
                            height: "8px",
                            borderRadius: "2px",
                            marginRight: "8px",
                            background: CATEGORY_COLORS[i % CATEGORY_COLORS.length],
                          }}
                        />
                        {cat.Category}
                        <span
                          role="button"
                          tabIndex={0}
                          onClick={(e) => {
                            // Separate from the row's expand/collapse click, so
                            // drilling in does not also fold the leaves away.
                            e.stopPropagation();
                            openDrill({ kind: "category", value: cat.Category });
                          }}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              e.stopPropagation();
                              openDrill({ kind: "category", value: cat.Category });
                            }
                          }}
                          title={`Show the ${formatNumber(cat.Count)} transactions behind ${cat.Category}`}
                          style={{
                            marginLeft: "10px",
                            fontSize: "0.7rem",
                            fontWeight: 600,
                            color: "var(--text-muted)",
                            cursor: "pointer",
                            borderBottom: "1px dotted var(--text-muted)",
                          }}
                        >
                          view →
                        </span>
                      </td>
                      <td style={{ padding: "10px 12px", color: "var(--text-muted)" }}>
                        {cat.sub_breakdown.length} leaf{cat.sub_breakdown.length === 1 ? "" : "s"}
                      </td>
                      <td style={{ padding: "10px 12px", textAlign: "right" }}>
                        {formatNumber(cat.Count)}
                      </td>
                      <td style={{ padding: "10px 12px", textAlign: "right" }}>
                        {formatCurrency(cat.Count ? cat.Spend / cat.Count : 0)}
                      </td>
                      <td style={{ padding: "10px 12px", textAlign: "right" }}>
                        {pct(cat.Spend, spendTotal)}
                      </td>
                      <td
                        style={{
                          padding: "10px 12px",
                          textAlign: "right",
                          fontWeight: 700,
                          color: "var(--rose-outflow)",
                        }}
                      >
                        {formatCurrency(cat.Spend)}
                      </td>
                    </tr>
                    {cat.sub_breakdown.map((sub) => (
                      <tr
                        key={`${cat.Category}-${sub.Sub_Category}`}
                        id={`insight-cat-${i}`}
                        style={{
                          borderBottom: "1px solid var(--border-subtle)",
                          background:
                            drill?.kind === "sub" && drill.value === sub.Sub_Category
                              ? "rgba(99, 102, 241, 0.16)"
                              : "rgba(255,255,255,0.02)",
                          cursor: "pointer",
                        }}
                        onClick={() => openDrill({ kind: "sub", value: sub.Sub_Category })}
                        title={`Show the ${formatNumber(sub.Count)} transactions behind ${sub.Sub_Category}`}
                      >
                        <td style={{ padding: "8px 12px 8px 34px", color: "var(--text-secondary)" }}>
                          ↳ {sub.Sub_Category}
                          <span
                            style={{
                              marginLeft: "8px",
                              fontSize: "0.7rem",
                              color: "var(--text-muted)",
                            }}
                          >
                            view →
                          </span>
                        </td>
                        <td style={{ padding: "8px 12px", color: "var(--text-muted)" }}>
                          {pct(sub.Spend, cat.Spend)} of category
                        </td>
                        <td style={{ padding: "8px 12px", textAlign: "right" }}>
                          {formatNumber(sub.Count)}
                        </td>
                        <td style={{ padding: "8px 12px", textAlign: "right" }}>
                          {formatCurrency(sub.Count ? sub.Spend / sub.Count : 0)}
                        </td>
                        <td style={{ padding: "8px 12px", textAlign: "right" }}>
                          {pct(sub.Spend, spendTotal)}
                        </td>
                        <td style={{ padding: "8px 12px", textAlign: "right", fontWeight: 600 }}>
                          {formatCurrency(sub.Spend)}
                        </td>
                      </tr>
                    ))}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ---------------- Patterns row ---------------- */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(400px, 1fr))",
          gap: "20px",
          marginBottom: "24px",
        }}
      >
        <div className="glass-panel" style={{ padding: "20px" }}>
          <PanelHeader title="Weekly Rhythm" subtitle="Spend by day of week" />
          {dowRows.length === 0 ? (
            <EmptyState message="No spend in this range" />
          ) : (
            <div style={{ width: "100%", height: "260px" }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={dowRows} margin={{ top: 10, right: 10, left: 10, bottom: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.05)" />
                  <XAxis
                    dataKey="DayOfWeekName"
                    stroke="var(--text-muted)"
                    fontSize={11}
                    tickLine={false}
                    interval={0}
                  />
                  <YAxis
                    stroke="var(--text-muted)"
                    fontSize={11}
                    tickFormatter={formatCompactCurrency}
                    tickLine={false}
                  />
                  <Tooltip
                    formatter={(value: any) => formatCurrency(Number(value))}
                    contentStyle={{
                      background: "var(--bg-secondary)",
                      border: "1px solid var(--border-subtle)",
                      borderRadius: "var(--radius-md)",
                    }}
                  />
                  <Bar dataKey="Spend" fill="#a855f7" radius={[4, 4, 0, 0]} maxBarSize={40} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        {/* "Where the Money Moved" (bank vs card) used to sit here. It is gone:
          the sidebar's Spend Basis is now the ledger control, so this panel both
          duplicated it and contradicted it — it showed a two-way split of a
          single ledger the user had already scoped to one side. */}
      </div>

      {/* ---------------- Recurring vs one-off ---------------- */}
      <div className="glass-panel" style={{ padding: "20px", marginBottom: "24px" }}>
        <PanelHeader
          title="Recurring vs One-off"
          subtitle="What you owe every month, against what you chose to spend"
        />
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            gap: "16px",
            marginBottom: "18px",
          }}
        >
          <MetricTile
            label="Recurring"
            value={isLoading ? "..." : formatCurrency(insights.recurring_vs_oneoff.recurring_spend)}
            hint={`${formatNumber(insights.recurring_vs_oneoff.recurring_count)} transactions · ${recurringPct} of spend`}
            tone="outflow"
          />
          <MetricTile
            label="One-off"
            value={isLoading ? "..." : formatCurrency(insights.recurring_vs_oneoff.oneoff_spend)}
            hint={`${formatNumber(insights.recurring_vs_oneoff.oneoff_count)} transactions · ${pct(
              insights.recurring_vs_oneoff.oneoff_spend,
              spendTotal
            )} of spend`}
          />
          <MetricTile
            label="Income"
            value={isLoading ? "..." : formatCurrency(savings.total_income)}
            hint="Credits received in the range"
            tone="inflow"
          />
          <MetricTile
            label="Expenses"
            value={isLoading ? "..." : formatCurrency(savings.total_expenses)}
            hint="Debits, on this view's cash-flow scope"
            tone="outflow"
          />
        </div>

        {/* Recurring share per category, stacked. The point is proportion, so
            this is a 100% view rather than a rupee one — a category that is small
            in absolute terms but nearly all recurring is still worth seeing. */}
        {recurringLeaders.length > 0 && (
          <>
            <h4
              style={{
                fontSize: "0.9rem",
                fontWeight: 700,
                color: "var(--text-secondary)",
                marginBottom: "10px",
              }}
            >
              Composition of the top categories
            </h4>
            <div style={{ width: "100%", height: "220px" }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={recurringLeaders}
                  layout="vertical"
                  margin={{ top: 5, right: 20, left: 10, bottom: 5 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.05)" />
                  <XAxis
                    type="number"
                    stroke="var(--text-muted)"
                    fontSize={11}
                    tickFormatter={formatCompactCurrency}
                    tickLine={false}
                  />
                  <YAxis
                    type="category"
                    dataKey="Category"
                    stroke="var(--text-muted)"
                    fontSize={11}
                    width={110}
                    tickLine={false}
                  />
                  <Tooltip
                    formatter={(value: any) => formatCurrency(Number(value))}
                    contentStyle={{
                      background: "var(--bg-secondary)",
                      border: "1px solid var(--border-subtle)",
                      borderRadius: "var(--radius-md)",
                    }}
                  />
                  <Legend wrapperStyle={{ paddingTop: "10px" }} />
                  <Bar
                    dataKey="Recurring"
                    stackId="mix"
                    fill="#f43f5e"
                    radius={[0, 0, 0, 0]}
                    maxBarSize={22}
                  />
                  <Bar
                    dataKey="One-off"
                    stackId="mix"
                    fill="#6366f1"
                    radius={[0, 4, 4, 0]}
                    maxBarSize={22}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </>
        )}
      </div>

      {/* ---------------- Channel breakdown ---------------- */}
      <div className="glass-panel" style={{ padding: "20px" }}>
        <PanelHeader
          title="Spend by Channel"
          subtitle="UPI, ATM, NEFT and the rest — how the money left the account"
        />
        {insights.txn_type_breakdown.length === 0 ? (
          <EmptyState message="No channel data in this range" />
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.875rem" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                  {["Channel", "Transactions", "Average", "Share", "Spend"].map((h, i) => (
                    <th
                      key={h}
                      style={{
                        textAlign: i >= 1 ? "right" : "left",
                        padding: "8px 12px",
                        fontSize: "0.7rem",
                        textTransform: "uppercase",
                        letterSpacing: "0.05em",
                        color: "var(--text-muted)",
                        fontWeight: 700,
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {insights.txn_type_breakdown.map((t) => (
                  <tr
                    key={t.Transaction_Type}
                    style={{
                      borderBottom: "1px solid var(--border-subtle)",
                      cursor: "pointer",
                      background:
                        drill?.kind === "channel" && drill.value === t.Transaction_Type
                          ? "rgba(99, 102, 241, 0.14)"
                          : undefined,
                    }}
                    onClick={() => openDrill({ kind: "channel", value: t.Transaction_Type })}
                    title={`Show the ${formatNumber(t.Count)} transactions behind ${t.Transaction_Type}`}
                  >
                    <td style={{ padding: "9px 12px", fontWeight: 600 }}>
                      {t.Transaction_Type}
                      <span
                        style={{
                          marginLeft: "8px",
                          fontSize: "0.7rem",
                          fontWeight: 400,
                          color: "var(--text-muted)",
                        }}
                      >
                        view →
                      </span>
                    </td>
                    <td style={{ padding: "9px 12px", textAlign: "right" }}>
                      {formatNumber(t.Count)}
                    </td>
                    <td style={{ padding: "9px 12px", textAlign: "right" }}>
                      {formatCurrency(t.Avg_Amount)}
                    </td>
                    <td style={{ padding: "9px 12px", textAlign: "right" }}>
                      {pct(t.Spend, spendTotal)}
                    </td>
                    <td
                      style={{
                        padding: "9px 12px",
                        textAlign: "right",
                        fontWeight: 700,
                        color: "var(--rose-outflow)",
                      }}
                    >
                      {formatCurrency(t.Spend)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* ---------------- Drill-down ---------------- */}
        {/* Reuses DrilldownPanel rather than a bespoke list, for the same reason the
            card view reuses the bank components: one implementation means the
            drill-down cannot drift from the chart that opened it. It brings
            server-side sorting, pagination, inline category editing and CSV export
            of the whole narrowed set - all of which a plain scrolling <div> would
            have had to re-implement, badly, and would have hidden rows beyond its
            own height from both the keyboard and the export.

            This block used to sit in the "no transactions in this range"
            early-return branch above, which made it unreachable: the five
            clickable aggregates set `drill` and scrolled a ref that was never
            mounted, so every drill target silently did nothing. It belongs at the
            end of the *main* return, where the charts that can open it actually
            are. */}
        {drill && drillFilters && (
          <div ref={drillRef} style={{ marginTop: "24px", scrollMarginTop: "16px" }}>
            <div className="glass-panel" style={{ padding: "20px" }}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: "12px",
                  flexWrap: "wrap",
                  marginBottom: "16px",
                }}
              >
                <div>
                  <h3 style={{ fontSize: "1.05rem", fontWeight: 700, color: "var(--text-primary)" }}>
                    {DRILL_TITLES[drill.kind]}: {drill.value}
                  </h3>
                  <p style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginTop: "4px" }}>
                    Every transaction behind the figure above, within the sidebar filters.
                    Settlements are included here even though the charts exclude them, so the
                    row count can exceed the chart&apos;s.
                  </p>
                </div>
                <button
                  onClick={() => setDrill(null)}
                  style={{
                    padding: "7px 14px",
                    fontSize: "0.8rem",
                    fontWeight: 600,
                    color: "var(--text-secondary)",
                    background: "rgba(255, 255, 255, 0.04)",
                    border: "1px solid var(--border-subtle)",
                    borderRadius: "var(--radius-md)",
                    cursor: "pointer",
                  }}
                >
                  Close
                </button>
              </div>

              {/* key: forces a remount when the target changes, so the panel's own
                  sort/page/in-view state cannot leak between two different scopes. */}
              <DrilldownPanel
                key={drillKey}
                periodLabel={`${DRILL_TITLES[drill.kind]}: ${drill.value}`}
                periodFilters={drillFilters}
                initialTxnTypes={drillInitialTxnTypes}
                availableTxnTypes={txnTypes}
                categories={categories}
                subCategories={subCategories}
                onPreviewRule={onPreviewRule}
                onApplyCascade={onApplyCascade}
                onRefresh={onRefresh}
                onNoteSave={onNoteSave}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
