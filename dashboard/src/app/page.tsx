"use client";

import React, { useState, useEffect, useMemo, useCallback } from "react";
import Sidebar from "@/components/Sidebar";
import KpiCards from "@/components/KpiCards";
import TabNav, { TabId } from "@/components/TabNav";
import TimelineChart from "@/components/charts/TimelineChart";
import CategoryStackChart from "@/components/charts/CategoryStackChart";
import PieChart from "@/components/charts/PieChart";
import BalanceTrendChart from "@/components/charts/BalanceTrendChart";
import CategoryTrendChart from "@/components/charts/CategoryTrendChart";
import SummaryTable from "@/components/tables/SummaryTable";
import TransactionTable from "@/components/tables/TransactionTable";
import CategoryEditorTable from "@/components/tables/CategoryEditorTable";
import DrilldownPanel from "@/components/tables/DrilldownPanel";
import CategoryMonthlyTable from "@/components/tables/CategoryMonthlyTable";

import {
  useMeta,
  useKPIs,
  useTransactions,
  useTimelineSummary,
  useMonthlyCategorySummary,
  useCategoryBreakdown,
  useBalanceTrend,
  useCategoryTrend,
} from "@/hooks/useTransactions";
import { useCategories } from "@/hooks/useCategories";
import { useCardStatements } from "@/hooks/useCards";
import { Filters, GroupBy, GroupCol, Transaction } from "@/types";
import { formatCurrency, formatNumber } from "@/lib/formatters";
import CreditCardsPanel from "@/components/CreditCardsPanel";
import DirectionModal, {
  PendingDirectionEdit,
} from "@/components/modals/DirectionModal";

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState<TabId>("analytics");

  // Filter state
  const [filters, setFilters] = useState<Filters>({
    years: [],
    months: [],
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
    // Combined spend by default, with card settlements excluded server-side so
    // a card purchase is not counted again when its bill is paid.
    spendBasis: "all",
    accountSources: [],
  });

  // Table pagination state
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  // Chart view states
  const [groupBy, setGroupBy] = useState<GroupBy>("month");
  const [pieGroupBy, setPieGroupBy] = useState<GroupCol>("Category");
  const [selectedPeriod, setSelectedPeriod] = useState<string | null>(null);
  const [selectedCategoryMonth, setSelectedCategoryMonth] = useState<string | null>(null);

  // Tab 3 state
  const [selectedCategory, setSelectedCategory] = useState<string>("");
  // Leaf within the selected broad category; empty means "all leaves".
  const [selectedSubCategory, setSelectedSubCategory] = useState<string>("");
  // Top-level rollup. Selecting it narrows the broad/leaf pickers below it.
  const [selectedParent, setSelectedParent] = useState<string>("");
  const [onlySelectedCategory, setOnlySelectedCategory] = useState<boolean>(true);
  const [editorPage, setEditorPage] = useState<number>(1);
  const [editorPageSize, setEditorPageSize] = useState<number>(50);
  const [editorSearch, setEditorSearch] = useState<string>("");
  const [editorSortBy, setEditorSortBy] = useState<string>("Date");
  const [editorSortOrder, setEditorSortOrder] = useState<"asc" | "desc">("asc");

  // Data hooks
  const { meta, mutate: mutateMeta } = useMeta();
  const {
    categories,
    customCategories,
    subCategories,
    addCategory,
    deleteCategory,
    applyRules,
    previewRule,
    applyCascadeRule,
    previewDirection,
    applyDirectionCascade,
    mutate: mutateCategories,
  } = useCategories();

  // Debit/credit corrections. The modal lives here so every table that shows
  // transactions can offer the same flip control, and one refresh invalidates
  // every view at once - a flipped row changes the KPI, the charts and the
  // tables simultaneously, so they must all be re-read.
  const [directionEdit, setDirectionEdit] = useState<PendingDirectionEdit | null>(null);
  const openDirectionEditor = useCallback((row: Transaction) => {
    const isCredit = (row.Credit_Amount || 0) > 0;
    setDirectionEdit({
      chq_ref: row.Chq_Ref_Number,
      payee: row.Payee_Receiver,
      narration: row.Narration,
      old_direction: isCredit ? "CREDIT" : "DEBIT",
      amount: (row.Debit_Amount || 0) + (row.Credit_Amount || 0),
    });
  }, []);

  // Data hooks stay disabled until metadata arrives. The initial filter state has
  // no years selected, so firing them immediately would fetch the unfiltered set
  // and then fetch everything again a moment later once this populates.
  const ready = Boolean(meta);

  // Populate initial filters once metadata loads
  useEffect(() => {
    if (meta?.years && filters.years.length === 0) {
      setFilters((prev) => ({
        ...prev,
        years: meta.years,
        months: meta.months.length ? meta.months : Array.from({ length: 12 }, (_, i) => i + 1),
      }));
    }
  }, [meta]);

  // A month picked under one category is meaningless under the next one
  useEffect(() => {
    setSelectedCategoryMonth(null);
    setSelectedSubCategory("");
  }, [selectedCategory]);

  // Leaves available at the current selection: the chosen broad category's, else
  // every leaf under the chosen parent, else all of them.
  const leavesForSelectedCategory = useMemo(() => {
    const all = subCategories;
    const leavesOf = meta?.leaves_of ?? {};
    if (selectedCategory) {
      return all.filter((leaf) => (leavesOf[selectedCategory] ?? []).includes(leaf));
    }
    if (selectedParent) {
      const broads = Object.keys(meta?.parent_of ?? {}).filter(
        (b) => meta?.parent_of?.[b] === selectedParent
      );
      return all.filter((leaf) => broads.some((b) => (leavesOf[b] ?? []).includes(leaf)));
    }
    return all;
  }, [subCategories, selectedCategory, selectedParent, meta]);

  // Parent rollup for the selected broad category, so Tab 3 can show the path.
  const selectedParentOfCategory = meta?.parent_of?.[selectedCategory] || "";

  // Option lists for the cascading Parent > Category > Leaf pickers. Built from
  // the parent_of map the API exposes, so no mapping is duplicated in the bundle.
  const parentsForSelector = useMemo(
    () => meta?.categories ?? [],
    [meta]
  );

  const broadUnderParent = useMemo(() => {
    const all = meta?.broad_categories ?? [];
    if (!selectedParent) return all;
    return all.filter((b) => meta?.parent_of?.[b] === selectedParent);
  }, [meta, selectedParent]);

  // Keep the broad picker valid when the parent changes from elsewhere.
  useEffect(() => {
    if (selectedCategory && !broadUnderParent.includes(selectedCategory)) {
      setSelectedCategory("");
      setSelectedSubCategory("");
    }
  }, [selectedCategory, broadUnderParent]);

  // Fetch KPI metrics (global)
  const { kpis, isLoading: kpisLoading, mutate: mutateKPIs } = useKPIs(filters, ready);

  // Statement count for the Credit Cards tab badge. SWR dedupes this against
  // the same request the panel makes, so it costs no extra round trip.
  const { cardStatements } = useCardStatements();

  // Tab 3 accurate category KPIs — scoped to the selected broad category and,
  // when one is chosen, the selected leaf.
  const catKpiFilters: Filters = {
    ...filters,
    categories: selectedParent ? [selectedParent] : [],
    broadCategories: selectedCategory ? [selectedCategory] : [],
    subCategories: selectedSubCategory ? [selectedSubCategory] : [],
  };
  const { kpis: catKpiData, mutate: mutateCatKPIs } = useKPIs(catKpiFilters, ready);

  // Fetch paginated transactions (for Tab 2 Explorer)
  const {
    transactionsPage,
    isLoading: txLoading,
    mutate: mutateTransactions,
  } = useTransactions(filters, page, pageSize, "", "asc", ready);

  // Dedicated paginated transactions for Tab 3 Category Editor
  const editorFilters: Filters = {
    ...filters,
    categories: selectedParent ? [selectedParent] : filters.categories,
    broadCategories: onlySelectedCategory && selectedCategory ? [selectedCategory] : filters.broadCategories,
    subCategories: selectedSubCategory ? [selectedSubCategory] : filters.subCategories,
    search: editorSearch.trim() ? editorSearch.trim() : filters.search,
  };
  const {
    transactionsPage: editorTxPage,
    isLoading: editorTxLoading,
    mutate: mutateEditorTx,
  } = useTransactions(editorFilters, editorPage, editorPageSize, editorSortBy, editorSortOrder, ready);

  // Scope a drill-down to the clicked period. A month label ("2024-03") resolves
  // to an exact Year_Month so it no longer bleeds across every March on record;
  // a year label ("2024") narrows to that year.
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

  // Month-by-month breakdown for the category selected in Tab 3
  const catMonthFilters: Filters = useMemo(
    () => ({
      ...filters,
      categories: selectedParent ? [selectedParent] : [],
      broadCategories: selectedCategory ? [selectedCategory] : [],
      subCategories: selectedSubCategory ? [selectedSubCategory] : [],
    }),
    [filters, selectedParent, selectedCategory, selectedSubCategory]
  );

  // Fetch charts data
  const { timeline, isLoading: timelineLoading } = useTimelineSummary(filters, groupBy, ready);
  const { monthlyCategoryData, isLoading: catStackLoading } = useMonthlyCategorySummary(filters, groupBy, ready);
  const { categoryBreakdown, isLoading: pieLoading } = useCategoryBreakdown(filters, pieGroupBy, ready);
  const { balanceTrend, isLoading: balanceLoading } = useBalanceTrend(filters, ready);
  // Chart the deepest level the user has actually selected, falling back to the
  // parent and then to the whole filtered set.
  const trendLevel: { col: "Category" | "Broad_Category" | "Sub_Category"; value: string } =
    selectedSubCategory
      ? { col: "Sub_Category", value: selectedSubCategory }
      : selectedCategory
      ? { col: "Broad_Category", value: selectedCategory }
      : { col: "Category", value: selectedParent };
  const { categoryTrend, isLoading: trendLoading } = useCategoryTrend(
    trendLevel.value,
    filters,
    ready,
    trendLevel.col
  );
  const { monthlyCategoryData: catMonthlyData, isLoading: catMonthlyLoading } =
    useMonthlyCategorySummary(catMonthFilters, "month", ready);

  // Global refresh after uploads or recategorization
  const handleDataRefresh = () => {
    mutateMeta();
    mutateKPIs();
    mutateCatKPIs();
    mutateTransactions();
    setPage(1);
    setEditorPage(1);
    setSelectedPeriod(null);
    setSelectedCategoryMonth(null);
    mutateEditorTx();
    mutateCategories();
  };

  // Tab 3 category metrics. These sit beside the category tables, so they use
  // the spend debits - the same figure the pie and stacked charts plot. Both
  // exclude card settlements, so the header agrees with the category rows
  // listed underneath it.
  const catDebits = catKpiData?.total_spend_debits || 0;
  const catCredits = catKpiData?.total_credits || 0;
  // spend_count is the row count the charts actually aggregate. filtered_count
  // still includes the settlement rows, which the category table does not show
  // when scoped to one category.
  const catCount = catKpiData?.spend_count || 0;


  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>
      {/* Sidebar Controls */}
      <Sidebar
        meta={meta}
        filters={filters}
        onChangeFilters={(f) => {
          setFilters(f);
          setPage(1);
          setEditorPage(1);
        }}
        categories={categories}
        subCategories={subCategories}
        customCategories={customCategories}
        onAddCategory={addCategory}
        onDeleteCategory={deleteCategory}
        onDataUploaded={handleDataRefresh}
        onRecategorized={handleDataRefresh}
      />

      {/* Main Content Area */}
      <main style={{
        flex: 1,
        padding: "32px 36px",
        overflowY: "auto",
        maxWidth: "1600px",
        margin: "0 auto",
        width: "100%",
      }}>
        {/* App Header */}
        <div style={{ marginBottom: "28px" }}>
          <h2 style={{
            fontSize: "2rem",
            fontWeight: 800,
            color: "var(--text-primary)",
            letterSpacing: "-0.03em",
            marginBottom: "6px",
          }}>
            💳 Bank Statement Intelligence
          </h2>
          <p style={{ fontSize: "0.95rem", color: "var(--text-muted)" }}>
            Interactive Statement Explorer, Monthly/Yearly Grouping, and Categorization
          </p>
        </div>

        {/* 4 Key Metrics */}
        <KpiCards kpis={kpis} isLoading={kpisLoading} />

        {/* Navigation Tabs */}
        <TabNav
          activeTab={activeTab}
          onChangeTab={setActiveTab}
          cardCount={cardStatements.length || undefined}
        />

        {/* TAB 1: Time & Group Analytics */}
        {activeTab === "analytics" && (
          <div>
            {/* Timeline bar chart (Credit vs Debit) */}
            <TimelineChart
              data={timeline}
              groupBy={groupBy}
              onChangeGroupBy={setGroupBy}
              isLoading={timelineLoading}
            />

            {/* Monthly cash flow by category stacked bar */}
            <CategoryStackChart
              data={monthlyCategoryData}
              isLoading={catStackLoading}
            />

            {/* Donut and Balance trend row */}
            <div style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(400px, 1fr))",
              gap: "20px",
              marginBottom: "24px",
            }}>
              <PieChart
                data={categoryBreakdown}
                groupBy={pieGroupBy}
                onChangeGroupBy={setPieGroupBy}
                isLoading={pieLoading}
              />
              <BalanceTrendChart
                data={balanceTrend}
                isLoading={balanceLoading}
              />
            </div>

            {/* Grouped Summary Table with click drill-down */}
            <SummaryTable
              data={timeline}
              groupBy={groupBy}
              selectedLabel={selectedPeriod}
              onSelectPeriod={setSelectedPeriod}
            />

            {/* Drilldown panel if a period is clicked */}
            {selectedPeriod && (
              <DrilldownPanel
                periodLabel={selectedPeriod}
                periodFilters={drillFilters}
                availableTxnTypes={meta?.txn_types ?? []}
                categories={categories}
                subCategories={subCategories}
                onPreviewRule={previewRule}
                onApplyCascade={applyCascadeRule}
                onRefresh={handleDataRefresh}
              />
            )}
          </div>
        )}

        {/* TAB 2: Interactive Search & Table */}
        {activeTab === "explorer" && (
          <div>
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
              exportLabel="Download Filtered CSV"
              onEditDirection={openDirectionEditor}
            />
          </div>
        )}

        {/* TAB 3: Broad Categories */}
        {activeTab === "categories" && (
          <div>
            {/* Category Selector Bar — cascading Parent › Category › Leaf */}
            <div className="glass-panel" style={{ padding: "20px", marginBottom: "24px" }}>
              <div style={{ display: "flex", alignItems: "flex-end", gap: "16px", flexWrap: "wrap" }}>
                <div>
                  <label
                    style={{
                      display: "block",
                      fontWeight: 700,
                      fontSize: "0.75rem",
                      color: "var(--text-muted)",
                      marginBottom: "4px",
                      textTransform: "uppercase",
                      letterSpacing: "0.05em",
                    }}
                  >
                    Parent Category
                  </label>
                  <select
                    className="select"
                    value={selectedParent}
                    onChange={(e) => {
                      const next = e.target.value;
                      setSelectedParent(next);
                      setEditorPage(1);
                      // A broad category outside the newly chosen parent is no
                      // longer reachable, so clear the downstream levels.
                      if (next && meta?.parent_of?.[selectedCategory] !== next) {
                        setSelectedCategory("");
                        setSelectedSubCategory("");
                      } else {
                        setSelectedSubCategory("");
                      }
                    }}
                    style={{ width: "auto", minWidth: "180px", fontWeight: 600 }}
                  >
                    <option value="">All parent categories</option>
                    {parentsForSelector.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label
                    style={{
                      display: "block",
                      fontWeight: 700,
                      fontSize: "0.75rem",
                      color: "var(--text-muted)",
                      marginBottom: "4px",
                      textTransform: "uppercase",
                      letterSpacing: "0.05em",
                    }}
                  >
                    Broad Category
                  </label>
                  <select
                    className="select"
                    value={selectedCategory}
                    onChange={(e) => {
                      setSelectedCategory(e.target.value);
                      setSelectedSubCategory("");
                      setEditorPage(1);
                    }}
                    style={{ width: "auto", minWidth: "200px", fontWeight: 600 }}
                  >
                    <option value="">All broad categories</option>
                    {broadUnderParent.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label
                    style={{
                      display: "block",
                      fontWeight: 700,
                      fontSize: "0.75rem",
                      color: "var(--text-muted)",
                      marginBottom: "4px",
                      textTransform: "uppercase",
                      letterSpacing: "0.05em",
                    }}
                  >
                    Sub-Category
                  </label>
                  <select
                    className="select"
                    value={selectedSubCategory}
                    onChange={(e) => {
                      setSelectedSubCategory(e.target.value);
                      setEditorPage(1);
                    }}
                    style={{ width: "auto", minWidth: "200px", fontWeight: 600 }}
                  >
                    <option value="">All sub-categories</option>
                    {leavesForSelectedCategory.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Full hierarchy path for the current selection */}
              <div style={{
                marginTop: "14px",
                paddingTop: "12px",
                borderTop: "1px solid var(--border-subtle)",
                display: "flex",
                alignItems: "center",
                gap: "8px",
                flexWrap: "wrap",
                fontSize: "0.85rem",
              }}>
                <span style={{ color: "var(--text-muted)", fontWeight: 600 }}>Hierarchy:</span>
                <span className="badge badge-gray">{selectedParentOfCategory || "—"}</span>
                <span style={{ color: "var(--text-muted)" }}>›</span>
                <span className="badge badge-indigo">{selectedCategory || "—"}</span>
                <span style={{ color: "var(--text-muted)" }}>›</span>
                <span className="badge badge-gray">
                  {selectedSubCategory || "All sub-categories"}
                </span>
              </div>
              {/* Category mini KPIs */}
              <div style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                gap: "12px",
                marginTop: "16px",
              }}>
                <div style={{ padding: "12px", background: "rgba(255, 255, 255, 0.02)", borderRadius: "var(--radius-md)" }}>
                  <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>Total Debits</div>
                  <div style={{ fontSize: "1.2rem", fontWeight: 700, color: "var(--rose-outflow)" }}>
                    {formatCurrency(catDebits)}
                  </div>
                </div>
                <div style={{ padding: "12px", background: "rgba(255, 255, 255, 0.02)", borderRadius: "var(--radius-md)" }}>
                  <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>Total Credits</div>
                  <div style={{ fontSize: "1.2rem", fontWeight: 700, color: "var(--emerald-inflow)" }}>
                    {formatCurrency(catCredits)}
                  </div>
                </div>
                <div style={{ padding: "12px", background: "rgba(255, 255, 255, 0.02)", borderRadius: "var(--radius-md)" }}>
                  <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>Net Flow</div>
                  <div style={{
                    fontSize: "1.2rem",
                    fontWeight: 700,
                    color: catCredits - catDebits >= 0 ? "var(--emerald-inflow)" : "var(--rose-outflow)",
                  }}>
                    {formatCurrency(catCredits - catDebits)}
                  </div>
                </div>
                <div style={{ padding: "12px", background: "rgba(255, 255, 255, 0.02)", borderRadius: "var(--radius-md)" }}>
                  <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>Transactions</div>
                  <div style={{ fontSize: "1.2rem", fontWeight: 700, color: "var(--text-primary)" }}>
                    {formatNumber(catCount)}
                  </div>
                </div>
              </div>
            </div>

            {/* Monthly Trend for selected category */}
            <CategoryTrendChart
              data={categoryTrend}
              category={
                selectedSubCategory || selectedCategory || selectedParent || "All categories"
              }
              isLoading={trendLoading}
            />

            {/* Clickable month-by-month breakdown for the selected category */}
            <CategoryMonthlyTable
              data={catMonthlyData}
              category={selectedCategory}
              selectedPeriod={selectedCategoryMonth}
              onSelectPeriod={setSelectedCategoryMonth}
              isLoading={catMonthlyLoading}
            />

            {/* Transactions behind the selected category month */}
            {selectedCategoryMonth && (
              <DrilldownPanel
                periodLabel={`${selectedSubCategory || selectedCategory || selectedParent || "All categories"} · ${selectedCategoryMonth}`}
                periodFilters={{
                  ...filters,
                  broadCategories: selectedCategory ? [selectedCategory] : [],
                  yearMonths: [selectedCategoryMonth],
                }}
                availableTxnTypes={meta?.txn_types ?? []}
                categories={categories}
                subCategories={subCategories}
                onPreviewRule={previewRule}
                onApplyCascade={applyCascadeRule}
                onRefresh={handleDataRefresh}
              />
            )}

            {/* Reassign categories editor table */}
            <CategoryEditorTable
              transactions={editorTxPage?.data || []}
              total={editorTxPage?.total || 0}
              page={editorPage}
              pageSize={editorPageSize}
              onChangePage={setEditorPage}
              selectedCategory={selectedCategory}
              onlySelectedCategory={onlySelectedCategory}
              onToggleOnlyCategory={(val) => {
                setOnlySelectedCategory(val);
                setEditorPage(1);
              }}
              categories={categories}
              subCategories={subCategories}
              search={editorSearch}
              onSearchChange={(q) => {
                setEditorSearch(q);
                setEditorPage(1);
              }}
              sortBy={editorSortBy}
              sortOrder={editorSortOrder}
              onSortChange={(col, order) => {
                setEditorSortBy(col);
                setEditorSortOrder(order);
                setEditorPage(1);
              }}
              onPreviewRule={previewRule}
              onApplyCascade={applyCascadeRule}
              onRefresh={handleDataRefresh}
              isLoading={editorTxLoading}
            />
          </div>
        )}

        {/* TAB 4: Credit Cards
            Cycle statements, card spend by category, and the bank reconciliation.
            The sidebar's spend-basis toggle still governs what the other three
            tabs report; this tab is the card-specific detail behind it. */}
        {activeTab === "cards" && (
          <div>
            <CreditCardsPanel
              filters={filters}
              meta={meta}
              categories={categories}
              subCategories={subCategories}
              onPreviewRule={previewRule}
              onApplyCascade={applyCascadeRule}
              onRefresh={handleDataRefresh}
            />
          </div>
        )}

        {/* Debit/credit flip editor. Rendered once, at the top level, so any
            table can open it. handleDataRefresh re-reads the KPI, the charts and
            the transaction lists together - the amount has moved between the two
            amount columns server-side, so every one of those numbers changes. */}
        <DirectionModal
          isOpen={directionEdit !== null}
          edit={directionEdit}
          onClose={() => setDirectionEdit(null)}
          onPreview={previewDirection}
          onApply={async (req) => {
            await applyDirectionCascade(req);
            handleDataRefresh();
          }}
        />

      </main>
    </div>
  );
}
