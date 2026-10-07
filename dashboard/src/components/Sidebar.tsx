"use client";

import React, { useState } from "react";
import { Filters, Meta } from "@/types";

interface SidebarProps {
  meta?: Meta;
  filters: Filters;
  onChangeFilters: (f: Filters) => void;
  categories: string[];
  subCategories: string[];
}

const MONTH_NAMES = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
];

/**
 * A collapsible filter section. Collapsed by default so the sidebar opens on
 * the search box and nothing else: ten permanently expanded controls were the
 * main source of clutter. The badge keeps a collapsed group's active filters
 * visible, so folding one away never hides that a filter is on.
 */
function FilterGroup({
  title,
  count,
  children,
}: {
  title: string;
  /** Active filters in this group; shown as a badge when collapsed. */
  count?: number;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="filter-group">
      <button
        className="filter-group-head"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span>{title}</span>
        {count ? <span className="filter-count">{count}</span> : null}
        <span className="filter-group-caret">{open ? "▾" : "▸"}</span>
      </button>
      {open && <div className="filter-group-body">{children}</div>}
    </div>
  );
}

function Segmented<T extends string | boolean | null>({
  value,
  options,
  onChange,
  columns,
}: {
  value: T;
  options: { key: T; label: string; title?: string }[];
  onChange: (v: T) => void;
  columns: 2 | 3;
}) {
  return (
    <div className={`segmented segmented-${columns}`}>
      {options.map((opt) => (
        <button
          key={String(opt.key)}
          onClick={() => onChange(opt.key)}
          aria-pressed={value === opt.key}
          title={opt.title}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

export default function Sidebar({
  meta,
  filters,
  onChangeFilters,
  categories,
  subCategories,
}: SidebarProps) {
  const patch = (part: Partial<Filters>) => onChangeFilters({ ...filters, ...part });

  const cardIds = filters.cardIds ?? [];

  const toggleYear = (yr: number) => {
    const exists = filters.years.includes(yr);
    patch({ years: exists ? filters.years.filter((y) => y !== yr) : [...filters.years, yr] });
  };

  const toggleMonth = (m: number) => {
    const exists = filters.months.includes(m);
    patch({ months: exists ? filters.months.filter((v) => v !== m) : [...filters.months, m] });
  };

  const resetFilters = () => {
    onChangeFilters({
      years: meta?.years || [],
      months: meta?.months || [],
      txnTypes: [],
      broadCategories: [],
      categories: [],
      subCategories: [],
      isRecurring: null,
      direction: "all",
      search: "",
      amountField: "any",
      amountMin: null,
      amountMax: null,
      spendBasis: "all",
      accountSources: [],
      cardIds: [],
      directionMismatch: null,
      hasNote: null,
    });
  };

  // Active-filter counts for the collapsed-group badges.
  const dateCount =
    filters.years.length + (filters.months.length === 12 ? 0 : filters.months.length);
  const scopeCount =
    (filters.spendBasis !== "all" ? 1 : 0) + (filters.isRecurring !== null ? 1 : 0);
  const categoryCount =
    filters.categories.length +
    filters.broadCategories.length +
    filters.subCategories.length +
    (filters.directionMismatch !== null && filters.directionMismatch !== undefined ? 1 : 0) +
    (filters.hasNote !== null && filters.hasNote !== undefined ? 1 : 0);
  const channelCount = filters.txnTypes.length;
  const amountCount =
    filters.amountField !== "any" || filters.amountMin !== null || filters.amountMax !== null
      ? 1
      : 0;
  const activeCount =
    (filters.direction !== "all" ? 1 : 0) +
    (filters.search ? 1 : 0) +
    dateCount +
    scopeCount +
    categoryCount +
    channelCount +
    amountCount;

  return (
    <aside className="app-sidebar">
      <div className="app-brand">
        <span aria-hidden>💳</span>
        <span className="app-brand-name">StatementParser</span>
      </div>
      <div className="app-brand-sub">Bank Statement Intelligence</div>

      {/* Pinned: search and direction scope every view, so they stay put
          rather than hiding behind a collapsed header. */}
      <div className="filter-pinned">
        <input
          type="text"
          className="input"
          placeholder="Search narration, payee, ref..."
          value={filters.search}
          onChange={(e) => patch({ search: e.target.value })}
          style={{ fontSize: "0.8rem" }}
        />
        <div className="field" style={{ marginTop: "10px" }}>
          <Segmented
            value={filters.direction}
            onChange={(direction) => patch({ direction })}
            options={[
              { key: "all", label: "All" },
              { key: "debits", label: "Debits" },
              { key: "credits", label: "Credits" },
            ]}
            columns={3}
          />
        </div>
      </div>

      {/* The collapsible groups. This is the only part that can scroll, and only
          on a viewport too short to hold an expanded group — the sidebar above
          is out of flow and cannot scroll away. */}
      <div className="app-sidebar-scroll">
      {/* Date */}
      <FilterGroup title="Date" count={dateCount}>
        {meta?.years && meta.years.length > 0 && (
          <div className="field">
            <span className="field-label">Years</span>
            <div className="pill-row">
              {meta.years.map((yr) => (
                <button
                  key={yr}
                  className="pill"
                  onClick={() => toggleYear(yr)}
                  aria-pressed={filters.years.includes(yr)}
                >
                  {yr}
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="field">
          <span className="field-label">Months</span>
          <div className="month-grid">
            {MONTH_NAMES.map((name, idx) => {
              const mNum = idx + 1;
              return (
                <button
                  key={name}
                  className="pill"
                  onClick={() => toggleMonth(mNum)}
                  aria-pressed={filters.months.includes(mNum)}
                >
                  {name}
                </button>
              );
            })}
          </div>
        </div>
      </FilterGroup>

      {/* Scope */}
      <FilterGroup
        title="Scope"
        count={scopeCount + cardIds.length}
      >
        <div className="field">
          <span className="field-label">Spend Basis</span>
          <Segmented
            value={filters.spendBasis}
            onChange={(spendBasis) => patch({ spendBasis })}
            options={[
              {
                key: "all",
                label: "Combined",
                title: "Bank and card spend combined, with card bill payments excluded",
              },
              { key: "bank_only", label: "Bank", title: "Only transactions paid from the bank account" },
              { key: "card_only", label: "Card", title: "Only credit-card purchases" },
            ]}
            columns={3}
          />
          <p className="field-hint">
            Picks the ledger for every tab. A card purchase and the bank debit that settles it
            are two halves of one transaction, so the server drops the settlement whenever both
            halves are in view.
          </p>
        </div>

        {/* Per-card narrowing, only meaningful on card rows (bank rows carry no
            Card_ID), so it is hidden unless the basis is already Card. This is
            the same picker the card view used to own; it is a filter, so it
            lives with the filters rather than on a tab of its own. */}
        {filters.spendBasis === "card_only" && (meta?.cards?.length ?? 0) > 0 && (
          <div className="field">
            <span className="field-label">Cards</span>
            <div className="pill-row">
              {(meta?.cards ?? []).map((card) => {
                const active = cardIds.includes(card.Card_ID);
                return (
                  <button
                    key={card.Card_ID}
                    className="pill"
                    aria-pressed={active}
                    title={`${card.Card_Issuer ?? "Card"} · ${card.Txn_Count} rows`}
                    onClick={() =>
                      patch({
                        cardIds: active
                          ? cardIds.filter((id) => id !== card.Card_ID)
                          : [...cardIds, card.Card_ID],
                      })
                    }
                  >
                    {card.Card_Name || "Unnamed card"}
                  </button>
                );
              })}
            </div>
            {cardIds.length > 0 && (
              <button className="link-btn link-btn-muted" onClick={() => patch({ cardIds: [] })}>
                Show all cards
              </button>
            )}
          </div>
        )}

        <div className="field">
          <span className="field-label">Recurrence</span>
          <Segmented
            value={filters.isRecurring}
            onChange={(isRecurring) => patch({ isRecurring })}
            options={[
              { key: null, label: "All" },
              {
                key: true,
                label: "Recurring",
                title: "Counterparties that repeat monthly - rent, EMIs, SIPs, subscriptions",
              },
              { key: false, label: "One-off" },
            ]}
            columns={3}
          />
        </div>
      </FilterGroup>

      {/* Category - three levels of the same hierarchy, so they belong in one
          section rather than three separate blocks. */}
      <FilterGroup title="Category" count={categoryCount}>
        <div className="field">
          <span className="field-label">Parent</span>
          <select
            className="select multiselect"
            multiple
            value={filters.categories}
            onChange={(e) =>
              patch({ categories: Array.from(e.target.selectedOptions, (o) => o.value) })
            }
          >
            {(meta?.categories || []).map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <p className="field-hint">Top-level groups that roll up everything beneath them.</p>
        </div>
        <div className="field">
          <span className="field-label">Broad</span>
          <select
            className="select multiselect-tall"
            multiple
            value={filters.broadCategories}
            onChange={(e) =>
              patch({ broadCategories: Array.from(e.target.selectedOptions, (o) => o.value) })
            }
          >
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <span className="field-label">Sub-Category</span>
          <select
            className="select multiselect-tall"
            multiple
            value={filters.subCategories}
            onChange={(e) =>
              patch({ subCategories: Array.from(e.target.selectedOptions, (o) => o.value) })
            }
          >
            {subCategories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <p className="field-hint">
            Finest level - e.g. Residential_Rent vs CoLiving_Rent vs Rent_Brokerage.
          </p>
        </div>

        {/* The rows the direction reconciler could not settle on its own. A credit
            under an expense category is usually a refund, and the category is
            already right for the arithmetic — so it is surfaced rather than
            silently re-filed, and this is where those rows are found. */}
        <div className="field">
          <span className="field-label">Needs review</span>
          <Segmented
            value={
              filters.directionMismatch === true
                ? "flagged"
                : filters.directionMismatch === false
                  ? "clean"
                  : "all"
            }
            onChange={(key) =>
              patch({
                directionMismatch: key === "all" ? null : key === "flagged",
              })
            }
            options={[
              { key: "all", label: "All" },
              { key: "clean", label: "Settled" },
              { key: "flagged", label: "Check side" },
            ]}
            columns={3}
          />
          <p className="field-hint">
            Rows where the category and the direction disagree - a credit filed as an
            expense, most likely a refund.
          </p>
        </div>

        <div className="field">
          <span className="field-label">Notes</span>
          <Segmented
            value={
              filters.hasNote === true ? "with" : filters.hasNote === false ? "without" : "all"
            }
            onChange={(key) => patch({ hasNote: key === "all" ? null : key === "with" })}
            options={[
              { key: "all", label: "All" },
              { key: "with", label: "Noted" },
              { key: "without", label: "Unnoted" },
            ]}
            columns={3}
          />
          <p className="field-hint">Rows you (or the model) have annotated.</p>
        </div>
      </FilterGroup>

      {/* Channel */}
      {meta?.txn_types && (
        <FilterGroup title="Channel" count={channelCount}>
          <select
            className="select multiselect"
            multiple
            value={filters.txnTypes}
            onChange={(e) => patch({ txnTypes: Array.from(e.target.selectedOptions, (o) => o.value) })}
          >
            {meta.txn_types.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </FilterGroup>
      )}

      {/* Amount */}
      <FilterGroup title="Amount" count={amountCount}>
        <select
          className="select"
          value={filters.amountField}
          onChange={(e) => patch({ amountField: e.target.value as Filters["amountField"] })}
          style={{ fontSize: "0.8rem" }}
        >
          <option value="any">Any (Debit or Credit)</option>
          <option value="debit">Debit Amount</option>
          <option value="credit">Credit Amount</option>
        </select>
        <div style={{ display: "flex", gap: "6px" }}>
          <input
            type="number"
            className="input"
            placeholder="Min ≥"
            min={0}
            value={filters.amountMin ?? ""}
            onChange={(e) =>
              patch({ amountMin: e.target.value === "" ? null : Number(e.target.value) })
            }
            style={{ fontSize: "0.8rem" }}
          />
          <input
            type="number"
            className="input"
            placeholder="Max ≤"
            min={0}
            value={filters.amountMax ?? ""}
            onChange={(e) =>
              patch({ amountMax: e.target.value === "" ? null : Number(e.target.value) })
            }
            style={{ fontSize: "0.8rem" }}
          />
        </div>
      </FilterGroup>

      <div className="filter-footer">
        <button className="link-btn" onClick={resetFilters} disabled={activeCount === 0}>
          Reset all{activeCount ? ` (${activeCount})` : ""}
        </button>
      </div>
      </div>
    </aside>
  );
}