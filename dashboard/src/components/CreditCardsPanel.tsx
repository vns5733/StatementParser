"use client";

import { useMemo, useState } from "react";
import { formatCurrency } from "@/lib/formatters";
import {
  useCards,
  useCardSpend,
  useCardStatements,
  useIssuerCategoryStats,
  useReconcile,
} from "@/hooks/useCards";
import CreditCardAnalytics from "@/components/CreditCardAnalytics";
import type {
  ApplyCascadeRequest,
  CardSpendEntry,
  CascadeMode,
  Filters,
  Meta,
  PreviewRuleResponse,
} from "@/types";

/**
 * Credit-card panel: which cards exist, how the issuer's own printed cycle total
 * compares with what was parsed, how card spend splits by category, and whether
 * the bank actually paid each statement.
 *
 * The parse check is the important one. A statement can look fine row by row and
 * still have lost rows, and the only way to see that is to compare the sum of
 * the parsed rows against the total the issuer printed.
 *
 * The "Overview" sub-tab is the card equivalent of the bank statement view
 * (KPIs, inflow/outflow timeline, category breakdown, drill-down). It reuses
 * the shared ledger rather than re-deriving card aggregates, so the two views
 * always report the same purchase with the same category.
 */
type Tab = "overview" | "cards" | "spend" | "reconcile";

const TABS: { key: Tab; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "cards", label: "Cards & Statements" },
  { key: "spend", label: "Spend by Category" },
  { key: "reconcile", label: "Bank Reconciliation" },
];

function day(value: string | null): string {
  return value ? value.slice(0, 10) : "—";
}

const th: React.CSSProperties = {
  padding: "10px",
  color: "var(--text-muted)",
  fontWeight: 600,
  textAlign: "left",
  whiteSpace: "nowrap",
};
const thNum: React.CSSProperties = { ...th, textAlign: "right" };
const td: React.CSSProperties = { padding: "10px", whiteSpace: "nowrap" };
const tdNum: React.CSSProperties = { ...td, textAlign: "right" };
const rowHover = (e: React.MouseEvent<HTMLTableRowElement>) => {
  e.currentTarget.style.background = "rgba(255, 255, 255, 0.03)";
};
const rowLeave = (e: React.MouseEvent<HTMLTableRowElement>) => {
  e.currentTarget.style.background = "transparent";
};

/** Green when the parsed rows agree with the issuer, amber when they don't. */
function varianceColor(v: number | null): string {
  if (v == null) return "var(--text-muted)";
  return Math.abs(v) < 1 ? "var(--emerald-inflow)" : "var(--amber-warn)";
}

interface CreditCardsPanelProps {
  /** Sidebar filters, so the card view respects the same year/month/category scope. */
  filters: Filters;
  meta: Meta | undefined;
  categories: string[];
  subCategories: string[];
  onPreviewRule: (mode: CascadeMode, key: string) => Promise<PreviewRuleResponse>;
  onApplyCascade: (request: ApplyCascadeRequest) => Promise<any>;
  onRefresh: () => void;
}

export default function CreditCardsPanel({
  filters,
  meta,
  categories,
  subCategories,
  onPreviewRule,
  onApplyCascade,
  onRefresh,
}: CreditCardsPanelProps) {
  // "overview" is the default: it is the card equivalent of the bank statement
  // view, and the other three sub-tabs are the card-specific detail behind it.
  const [tab, setTab] = useState<Tab>("overview");
  const { cards, isLoading: loadingCards } = useCards();
  const { cardStatements } = useCardStatements();
  const { cardSpend } = useCardSpend();
  const { issuerCategoryStats } = useIssuerCategoryStats();
  const { reconcile, isLoading: loadingRecon } = useReconcile();

  // Spend rolled up per card, so the summary tiles can be read at a glance.
  const byCard = useMemo(() => {
    const out = new Map<string, CardSpendEntry>();
    for (const row of cardSpend) {
      const key = row.Card_Name || "Unknown card";
      const prev = out.get(key);
      if (prev) {
        prev.Spend += row.Spend;
        prev.Refunds += row.Refunds;
        prev.Count += row.Count;
      } else {
        out.set(key, { ...row, Card_Name: key });
      }
    }
    return Array.from(out.values()).sort((a, b) => b.Spend - a.Spend);
  }, [cardSpend]);

  // The visible card history is bounded by the statements actually imported:
  // one statement per card covers a single cycle, so without this the panel
  // looks empty for every earlier month and reads like a broken filter.
  const coverage = useMemo(() => {
    const starts = cardStatements.map((s) => s.Period_Start).filter(Boolean).sort();
    const ends = cardStatements.map((s) => s.Period_End).filter(Boolean).sort();
    return {
      from: starts.length ? day(starts[0]) : null,
      to: ends.length ? day(ends[ends.length - 1]) : null,
      count: cardStatements.length,
    };
  }, [cardStatements]);

  // The registry loading/empty states only gate the three card-detail sub-tabs.
  // "overview" reads the shared ledger, so it has its own empty state and must
  // stay reachable (and switchable away from) in both cases — otherwise the tab
  // strip would vanish along with the content and trap the user.
  const registryPending = loadingCards;
  const registryEmpty = !loadingCards && cards.length === 0;

  return (
    <div>
      {/* Tab strip. Rendered outside the glass panel so the overview's own
          charts can be full-bleed panels rather than nested inside one. */}
      <div
        className="glass-panel"
        style={{ padding: "20px", marginBottom: "20px" }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            flexWrap: "wrap",
            gap: "10px",
          }}
        >
          <div>
            <h3 style={{ fontSize: "1.1rem", fontWeight: 700, color: "var(--text-primary)" }}>
              Credit Cards
            </h3>
            <p style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
              Spend analytics, cycle statements, and whether the bank paid each bill
            </p>
            {coverage.from && (
              <p style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "6px" }}>
                <span className="badge badge-gray" style={{ marginRight: "6px" }}>
                  {coverage.count} statement{coverage.count === 1 ? "" : "s"}
                </span>
                Card history covers {coverage.from} to {coverage.to}. Older months are
                empty because those statements have not been imported yet.
              </p>
            )}
          </div>
          <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
            {TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={tab === t.key ? "btn btn-primary" : "btn btn-secondary"}
                style={{ padding: "5px 12px", fontSize: "0.75rem" }}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {tab === "overview" && (
        <CreditCardAnalytics
          baseFilters={filters}
          meta={meta}
          categories={categories}
          subCategories={subCategories}
          onPreviewRule={onPreviewRule}
          onApplyCascade={onApplyCascade}
          onRefresh={onRefresh}
        />
      )}

      {tab !== "overview" && registryPending && (
        <div className="glass-panel" style={{ padding: "20px" }}>
          <p style={{ color: "var(--text-muted)", fontSize: "0.875rem" }}>
            Loading credit cards…
          </p>
        </div>
      )}

      {tab !== "overview" && registryEmpty && (
        <div className="glass-panel" style={{ padding: "20px" }}>
          <p style={{ color: "var(--text-primary)", fontWeight: 700, fontSize: "1.1rem" }}>
            No card detail available
          </p>
          <p style={{ color: "var(--text-muted)", fontSize: "0.875rem", marginTop: "6px" }}>
            No credit-card statements imported yet. Run{" "}
            <code style={{ color: "var(--text-secondary)" }}>python ingest_cards.py</code>{" "}
            to import the PDFs in the{" "}
            <code style={{ color: "var(--text-secondary)" }}>CreditCard/</code> folder.
          </p>
        </div>
      )}

      {/* The three detail sub-tabs. All read the card registry directly, so they
          are gated on it having loaded; the overview above is independent. */}
      {!registryPending && !registryEmpty && (
      <>
      {tab === "cards" && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.875rem" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                <th style={th}>Card</th>
                <th style={th}>Issuer</th>
                <th style={thNum}>Credit limit</th>
                <th style={th}>Statement</th>
                <th style={th}>Due</th>
                <th style={thNum}>Txn</th>
                <th style={thNum}>Issuer total</th>
                <th style={thNum}>Parsed</th>
                <th style={thNum}>Variance</th>
              </tr>
            </thead>
            <tbody>
              {cardStatements.map((s) => {
                const variance =
                  s.Parsed_Spend != null && s.Total_Spend != null
                    ? s.Parsed_Spend - s.Total_Spend
                    : null;
                return (
                  <tr
                    key={s.Statement_ID}
                    onMouseEnter={rowHover}
                    onMouseLeave={rowLeave}
                    style={{
                      borderBottom: "1px solid rgba(255, 255, 255, 0.03)",
                      transition: "background 0.15s ease",
                    }}
                  >
                    <td style={{ ...td, fontWeight: 600, color: "var(--text-primary)" }}>
                      {s.Card_Name}
                    </td>
                    <td style={td}>
                      <span className="badge badge-indigo">{s.Issuer}</span>
                    </td>
                    <td style={tdNum}>
                      {s.Credit_Limit ? formatCurrency(s.Credit_Limit) : "—"}
                    </td>
                    <td style={td}>{day(s.Statement_Date)}</td>
                    <td style={td}>{day(s.Due_Date)}</td>
                    <td style={{ ...tdNum, color: "var(--text-secondary)" }}>
                      {s.Txn_Count ?? 0}
                    </td>
                    <td style={tdNum}>
                      {s.Total_Spend != null ? formatCurrency(s.Total_Spend) : "—"}
                    </td>
                    <td style={tdNum}>
                      {s.Parsed_Spend != null ? formatCurrency(s.Parsed_Spend) : "—"}
                    </td>
                    <td style={{ ...tdNum, color: varianceColor(variance), fontWeight: 600 }}>
                      {variance == null ? "—" : variance.toFixed(2)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {issuerCategoryStats.some((s) => s.Issuer_Categorised > 0) && (
            <p
              style={{
                marginTop: "12px",
                fontSize: "0.75rem",
                color: "var(--text-muted)",
              }}
            >
              <span style={{ color: "var(--text-secondary)" }}>
                Issuer-supplied categories
              </span>{" "}
              (used instead of keyword guessing):{" "}
              {issuerCategoryStats
                .filter((s) => s.Issuer_Categorised > 0)
                .map((s) => `${s.Card_Name} ${s.Issuer_Categorised}/${s.Txn_Count}`)
                .join(", ")}
              . Cards not listed fall back to keyword rules.
            </p>
          )}
        </div>
      )}

      {tab === "spend" && (
        <div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
              gap: "12px",
              marginBottom: "18px",
            }}
          >
            {byCard.map((c) => (
              <div
                key={c.Card_Name || ""}
                className="glass-panel-subtle"
                style={{ padding: "14px 16px" }}
              >
                <div
                  style={{
                    fontSize: "0.75rem",
                    color: "var(--text-muted)",
                    marginBottom: "4px",
                  }}
                >
                  {c.Issuer || "Card"}
                </div>
                <div
                  style={{
                    fontSize: "1.25rem",
                    fontWeight: 700,
                    color: "var(--text-primary)",
                    lineHeight: 1.2,
                  }}
                >
                  {formatCurrency(c.Spend)}
                </div>
                <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)" }}>
                  {c.Card_Name || "Unknown card"}
                </div>
                <div style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}>
                  {c.Count} transactions
                </div>
              </div>
            ))}
          </div>

          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.875rem" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                  <th style={th}>Card</th>
                  <th style={th}>Category</th>
                  <th style={thNum}>Txn</th>
                  <th style={thNum}>Spend</th>
                </tr>
              </thead>
              <tbody>
                {cardSpend.map((row, i) => (
                  <tr
                    key={`${row.Card_Name}-${row.Category}-${i}`}
                    onMouseEnter={rowHover}
                    onMouseLeave={rowLeave}
                    style={{
                      borderBottom: "1px solid rgba(255, 255, 255, 0.03)",
                      transition: "background 0.15s ease",
                    }}
                  >
                    <td style={{ ...td, color: "var(--text-secondary)" }}>
                      {row.Card_Name || "—"}
                    </td>
                    <td style={{ ...td, fontWeight: 600, color: "var(--text-primary)" }}>
                      {row.Category}
                    </td>
                    <td style={{ ...tdNum, color: "var(--text-muted)" }}>{row.Count}</td>
                    <td style={tdNum}>{formatCurrency(row.Spend)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "reconcile" && (
        <div>
          {loadingRecon && (
            <p style={{ fontSize: "0.875rem", color: "var(--text-muted)" }}>
              Reconciling…
            </p>
          )}
          {reconcile && (
            <>
              <div
                style={{
                  display: "flex",
                  gap: "10px",
                  flexWrap: "wrap",
                  marginBottom: "16px",
                }}
              >
                <span className="badge badge-gray">
                  {reconcile.summary.statements} statements
                </span>
                <span
                  className={
                    reconcile.summary.matched === reconcile.summary.statements
                      ? "badge badge-emerald"
                      : "badge badge-indigo"
                  }
                >
                  {reconcile.summary.matched} matched
                </span>
                {reconcile.summary.unmatched_statements > 0 && (
                  <span className="badge badge-gray">
                    {reconcile.summary.unmatched_statements} unmatched
                  </span>
                )}
                <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
                  {reconcile.summary.unmatched_bank_debits} bank card payments have
                  no statement held for them
                </span>
              </div>

              {reconcile.matched.length > 0 && (
                <div style={{ overflowX: "auto" }}>
                  <table
                    style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.875rem" }}
                  >
                    <thead>
                      <tr style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                        <th style={th}>Card</th>
                        <th style={th}>Bank ref</th>
                        <th style={th}>Paid on</th>
                        <th style={thNum}>Billed</th>
                        <th style={thNum}>Variance</th>
                      </tr>
                    </thead>
                    <tbody>
                      {reconcile.matched.map((m) => (
                        <tr
                          key={m.Statement_ID}
                          onMouseEnter={rowHover}
                          onMouseLeave={rowLeave}
                          style={{
                            borderBottom: "1px solid rgba(255, 255, 255, 0.03)",
                            transition: "background 0.15s ease",
                          }}
                        >
                          <td style={{ ...td, color: "var(--text-primary)" }}>
                            {m.Card_Name}
                          </td>
                          <td
                            style={{
                              ...td,
                              fontFamily: "ui-monospace, monospace",
                              fontSize: "0.75rem",
                              color: "var(--text-muted)",
                            }}
                          >
                            {m.Bank_Chq_Ref}
                          </td>
                          <td style={{ ...td, color: "var(--text-secondary)" }}>
                            {day(m.Bank_Payment_Date)}
                          </td>
                          <td style={tdNum}>{formatCurrency(m.Billed_Amount)}</td>
                          <td
                            style={{
                              ...tdNum,
                              color: varianceColor(m.Variance),
                              fontWeight: 600,
                            }}
                          >
                            {m.Variance.toFixed(2)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {reconcile.unmatched_statements.length > 0 && (
                <div style={{ marginTop: "18px" }}>
                  <h4
                    style={{
                      fontSize: "0.8rem",
                      fontWeight: 600,
                      color: "var(--text-secondary)",
                      marginBottom: "8px",
                    }}
                  >
                    Unmatched statements
                  </h4>
                  <ul
                    style={{
                      listStyle: "none",
                      padding: 0,
                      fontSize: "0.8rem",
                      color: "var(--text-muted)",
                      display: "flex",
                      flexDirection: "column",
                      gap: "6px",
                    }}
                  >
                    {reconcile.unmatched_statements.map((u) => (
                      <li key={u.Statement_ID}>
                        <span
                          className="badge badge-gray"
                          style={{ marginRight: "8px" }}
                        >
                          {u.Card_Name}
                        </span>
                        {day(u.Statement_Date)} — {u.reason}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      )}
      </>
      )}
    </div>
  );
}
