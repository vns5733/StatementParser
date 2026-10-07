"use client";

import React, { useState, useEffect, useMemo, useCallback } from "react";
import { useSWRConfig } from "swr";
import Sidebar from "@/components/Sidebar";
import DataTools from "@/components/DataTools";
import KpiCards from "@/components/KpiCards";
import CardTiles from "@/components/CardTiles";
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
import { useLLMStatus, useNoteActions } from "@/hooks/useNotes";
import { Filters, GroupBy, GroupCol, Transaction } from "@/types";
import { formatCurrency, formatNumber } from "@/lib/formatters";
import CreditCardsPanel from "@/components/CreditCardsPanel";
import InsightsPanel from "@/components/InsightsPanel";
import DirectionModal, {
  PendingDirectionEdit,
} from "@/components/modals/DirectionModal";
import CascadeModal, { PendingEdit } from "@/components/modals/CascadeModal";
import BulkEditModal from "@/components/modals/BulkEditModal";
import SuggestModal from "@/components/modals/SuggestModal";
import CategoryDefinitionsPanel from "@/components/CategoryDefinitionsPanel";

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState<TabId>("overview");

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
  // Explorer sort. Server-side, so a click re-ranks the whole result set; a new
  // sort resets to page 1, because the page the user was on may no longer exist.
  const [txSortBy, setTxSortBy] = useState("Date");
  const [txSortOrder, setTxSortOrder] = useState<"asc" | "desc">("desc");

  // Chart view states
  const [groupBy, setGroupBy] = useState<GroupBy>("month");
  const [pieGroupBy, setPieGroupBy] = useState<GroupCol>("Category");
  const [selectedPeriod, setSelectedPeriod] = useState<string | null>(null);
  const [selectedCategoryMonth, setSelectedCategoryMonth] = useState<string | null>(null);

  // Transactions tab. "browse" is the row-level ledger (search, sort, export,
  // and both per-row editors); "reassign" is the category-scoped workbench.
  // Both answer the same question - "what is this row, and is it filed right?"
  // - so they are two modes of one tab rather than two tabs.
  const [txView, setTxView] = useState<"browse" | "reassign">("browse");

  // Bulk-reassign state (the workbench half of the Transactions tab)
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

  // Category correction driven from the row-level table. Previously each table
  // that showed transactions carried its own copy of this state and its own
  // CascadeModal; one editor in one tab means the three cannot drift apart.
  const [pendingEdits, setPendingEdits] = useState<PendingEdit[]>([]);
  const [isCascadeOpen, setIsCascadeOpen] = useState(false);

  const handleCategoryChange = useCallback(
    (row: Transaction, newCategory: string, newSub?: string) => {
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
    },
    []
  );

  // Data hooks. These no longer destructure `mutate`: handleDataRefresh
  // revalidates the whole /transactions and /cards keyspace through useSWRConfig.
  const { meta } = useMeta();
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
    definitions,
    upsertDefinition,
    mutate: mutateCategories,
  } = useCategories();

  // Notes, and category suggestions from the local opencode server.
  //
  // The note writer is the only writer, and it revalidates the transaction
  // keyspace itself — notes ride along on the row, so a save that did not
  // invalidate would leave the cell showing the text it was rendered with, which
  // reads as the save having failed.
  const { writeNote, suggest } = useNoteActions();
  const llmStatus = useLLMStatus();

  // Bulk selection. Held here rather than inside TransactionTable because a
  // selection has to survive a page change and a refilter; owned by the table it
  // would silently shrink the moment the user paged.
  const [selectedRefs, setSelectedRefs] = useState<string[]>([]);
  const [bulkMode, setBulkMode] = useState<"category" | "note" | null>(null);
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [definitionsOpen, setDefinitionsOpen] = useState(false);

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
  const { kpis, isLoading: kpisLoading } = useKPIs(filters, ready);

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
  const { kpis: catKpiData } = useKPIs(catKpiFilters, ready);

  // Fetch paginated transactions (for Tab 2 Explorer). Sorting is server-side, so
  // it is part of the query key rather than applied to the returned page.
  const { transactionsPage, isLoading: txLoading } = useTransactions(
    filters,
    page,
    pageSize,
    txSortBy,
    txSortOrder,
    ready
  );

  // Resolves the ticked refs to displayable rows, for the bulk modals' preview.
  //
  // Only rows currently on screen can be resolved, so a selection that outlives a
  // page change resolves to fewer rows than it contains. That is deliberate: acting
  // on rows the user can no longer see is how a bulk edit touches something
  // unintended, and the modals show exactly what they will apply to. The refs stay
  // selected so paging back restores them.
  const selectedRows = useMemo(() => {
    const onScreen = new Map(
      (transactionsPage?.data || []).map((r) => [r.Chq_Ref_Number, r])
    );
    return selectedRefs
      .map((ref) => onScreen.get(ref))
      .filter((r): r is Transaction => Boolean(r));
  }, [selectedRefs, transactionsPage]);

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

  // ---- Legend clicks -------------------------------------------------------
  //
  // A clicked legend entry narrows `Filters`, not the chart it was clicked in.
  // Every panel — the KPI row, all four charts, the summary table and the
  // transaction list — reads the same `Filters`, so a filter is the only way to
  // make "show me just that legend" true everywhere at once. Filtering the
  // chart's own data would leave a header total disagreeing with the rows under
  // it, which is the failure Decision 17 exists to prevent.
  //
  // Clicking the entry that is already applied clears it, so the control is
  // reversible without hunting for a "reset" elsewhere.
  const toggleValue = <T,>(list: T[] | undefined, v: T): T[] =>
    (list ?? []).includes(v) ? (list ?? []).filter((x) => x !== v) : [...(list ?? []), v];

  const applySeries = useCallback(
    (field: "categories" | "broadCategories" | "subCategories" | "txnTypes", value: string) => {
      setFilters((prev) => ({ ...prev, [field]: toggleValue(prev[field], value) }));
      // A narrower result set invalidates the current page, same as a sidebar
      // filter change.
      setPage(1);
      setEditorPage(1);
    },
    []
  );

  // The pie's legend names categories at whichever level is selected, so the
  // same click has to route to a different filter per level.
  const selectPieSeries = useCallback(
    (value: string) => {
      const field =
        pieGroupBy === "Category"
          ? "categories"
          : pieGroupBy === "Broad_Category"
            ? "broadCategories"
            : pieGroupBy === "Sub_Category"
              ? "subCategories"
              : "txnTypes";
      applySeries(field, value);
    },
    [pieGroupBy, applySeries]
  );

  const selectBroadSeries = useCallback(
    (value: string) => applySeries("broadCategories", value),
    [applySeries]
  );

  // Inflow/outflow legends map onto the direction filter. Toggling the direction
  // that is already applied returns to "all" rather than to the other side,
  // because clicking "Debits" twice should undo the click, not flip to credits.
  const selectDirection = useCallback((next: "debits" | "credits") => {
    setFilters((prev) => ({ ...prev, direction: prev.direction === next ? "all" : next }));
    setPage(1);
    setEditorPage(1);
  }, []);

  // Which pie legend entries are currently applied, for the active marker.
  const pieSelected =
    pieGroupBy === "Category"
      ? filters.categories
      : pieGroupBy === "Broad_Category"
        ? filters.broadCategories
        : pieGroupBy === "Sub_Category"
          ? filters.subCategories
          : filters.txnTypes;

  // Global refresh after uploads, recategorization or a direction flip.
  //
  // Every /transactions and /categories key is revalidated, NOT just the ones this
  // component happens to hold a mutate() for. The credit-card panel runs its own
  // useKPIs/useTransactions with card-scoped keys that live in a child component,
  // so enumerating only the parent hooks left the card view showing the old
  // category until something else happened to trigger a re-render. A key filter
  // catches every current and future cache entry, including ones added later.
  const { mutate: mutateAll } = useSWRConfig();
  const handleDataRefresh = useCallback(() => {
    mutateAll(
      (key) =>
        typeof key === "string" &&
        (key.startsWith("/transactions") || key.startsWith("/cards")),
      undefined,
      { revalidate: true }
    );
    mutateCategories();
    setPage(1);
    setEditorPage(1);
    setSelectedPeriod(null);
    setSelectedCategoryMonth(null);
  }, [mutateAll, mutateCategories]);

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
    <div className="app-shell">
      {/* Filter sidebar. Sticky, so it stays reachable as the tab scrolls,
          while the main column keeps the single page scroll. */}
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
      />

      {/* Main Content Area */}
      <main className="app-main">
        {/* App header. The title and the data-maintenance controls live here
            rather than in the sidebar, which is now filters only. */}
        <header className="page-header">
          <div>
            <h1 className="page-title">Bank Statement Intelligence</h1>
            <p className="page-subtitle">
              Interactive Statement Explorer, Monthly/Yearly Grouping, and Categorization
            </p>
          </div>
          <DataTools
            meta={meta}
            customCategories={customCategories}
            onAddCategory={addCategory}
            onDeleteCategory={deleteCategory}
            onDataUploaded={handleDataRefresh}
            onRecategorized={handleDataRefresh}
            onEditDefinitions={() => setDefinitionsOpen(true)}
          />
        </header>

        {/* 4 Key Metrics */}
        <KpiCards kpis={kpis} isLoading={kpisLoading} />

        {/* Navigation Tabs */}
        <TabNav
          activeTab={activeTab}
          onChangeTab={setActiveTab}
          cardCount={cardStatements.length || undefined}
        />

        {/* First run. The import controls moved out of the sidebar, so an empty
            database would otherwise render five empty charts and no signpost
            toward the one action that fixes it. */}
        {meta && meta.years.length === 0 && (
          <div className="glass-panel empty-state">
            <div className="empty-state-title">No statements imported yet</div>
            <p className="empty-state-note">
              Open <strong>Data</strong> in the header to upload a bank statement
              (.xls, .xlsx, .csv or .pdf), or load the bundled sample to explore the
              dashboard with example data.
            </p>
          </div>
        )}

        {/* TAB 1: Overview — the single chart surface. Bank vs card vs both is the
            sidebar's Spend Basis (plus the card picker), not a tab of its own:
            the same components read the same shared ledger either way, so a
            separate card tab was a seven-component clone of this one. */}
        {activeTab === "overview" && (
          <div className="stack">
            {/* Card-framed labels for the same totals. The shared KPI row calls
                them "Credits"/"Debits", which is right for a bank but understates
                a card: a credit there is a refund or a bill payment, not income.
                Shown only when the scope is a card, because that is the only
                reading where these labels are the accurate ones. */}
            {filters.spendBasis === "card_only" && (
              <CardTiles kpis={kpis} isLoading={kpisLoading} cards={meta?.cards ?? []} cardIds={filters.cardIds ?? []} />
            )}

            {/* Timeline bar chart (Credit vs Debit) */}
            <TimelineChart
              data={timeline}
              groupBy={groupBy}
              onChangeGroupBy={setGroupBy}
              isLoading={timelineLoading}
              onSelectDirection={selectDirection}
              activeDirection={filters.direction}
            />

            {/* Monthly cash flow by category stacked bar */}
            <CategoryStackChart
              data={monthlyCategoryData}
              isLoading={catStackLoading}
              onSelectSeries={selectBroadSeries}
              selectedValues={filters.broadCategories}
            />

            {/* Donut and Balance trend row */}
            <div className="split-2">
              <PieChart
                data={categoryBreakdown}
                groupBy={pieGroupBy}
                onChangeGroupBy={setPieGroupBy}
                isLoading={pieLoading}
                onSelectSeries={selectPieSeries}
                selectedValues={pieSelected}
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
                /* Same note writer as the explorer table, so a note written
                   in a drill-down is the note that shows there. */
                onNoteSave={async (ref, note) => {
                  await writeNote({ chq_refs: [ref], note });
                }}
              />
            )}
          </div>
        )}

        {/* TAB 2: Transactions — find a row and correct it, in one place. */}
        {activeTab === "transactions" && (
          <div className="stack">
            <div className="tab-nav" role="tablist">
              <button
                role="tab"
                className="tab-btn"
                aria-selected={txView === "browse"}
                onClick={() => setTxView("browse")}
              >
                <span aria-hidden>🔎</span> Browse
              </button>
              <button
                role="tab"
                className="tab-btn"
                aria-selected={txView === "reassign"}
                onClick={() => setTxView("reassign")}
              >
                <span aria-hidden>✏️</span> Reassign Categories
              </button>
            </div>

            {txView === "browse" && (
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
                /* Both editors on one table. The category dropdowns used to
                   live only on the bulk workbench and the card view, which left
                   this table — the first place anyone looks for a row — unable
                   to correct a mis-filed category. */
                onCategoryChange={handleCategoryChange}
                categories={categories}
                subCategories={subCategories}
                sortBy={txSortBy}
                sortOrder={txSortOrder}
                onSortChange={(col, order) => {
                  setTxSortBy(col);
                  setTxSortOrder(order);
                  setPage(1);
                }}
                onNoteSave={async (ref, note) => {
                  await writeNote({ chq_refs: [ref], note });
                }}
                selectedRefs={selectedRefs}
                onSelectionChange={setSelectedRefs}
                renderBulkActions={() => (
                  <>
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={() => setBulkMode("category")}
                      title="Apply one category to the selected rows, as individual pins"
                    >
                      Reassign
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={() => setBulkMode("note")}
                      title="Write the same note on the selected rows"
                    >
                      Add note
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm btn-primary"
                      onClick={() => setSuggestOpen(true)}
                      disabled={!llmStatus?.available}
                      title={
                        llmStatus?.available
                          ? "Ask the local opencode server to suggest a category for the selected rows"
                          : llmStatus?.detail ||
                            "No opencode server is reachable on OPENCODE_SERVER_URL"
                      }
                    >
                      Suggest
                    </button>
                  </>
                )}
              />
            )}

            {txView === "reassign" && (
              <>
            {/* Category Selector Bar — cascading Parent › Category › Leaf */}
            <div className="glass-panel" style={{ padding: "18px" }}>
              <div className="field-inline-row">
                <div className="field-inline">
                  <label className="field-inline-label" htmlFor="sel-parent">
                    Parent Category
                  </label>
                  <select
                    id="sel-parent"
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
                    style={{ fontWeight: 600 }}
                  >
                    <option value="">All parent categories</option>
                    {parentsForSelector.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="field-inline">
                  <label className="field-inline-label" htmlFor="sel-broad">
                    Broad Category
                  </label>
                  <select
                    id="sel-broad"
                    className="select"
                    value={selectedCategory}
                    onChange={(e) => {
                      setSelectedCategory(e.target.value);
                      setSelectedSubCategory("");
                      setEditorPage(1);
                    }}
                    style={{ fontWeight: 600 }}
                  >
                    <option value="">All broad categories</option>
                    {broadUnderParent.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="field-inline">
                  <label className="field-inline-label" htmlFor="sel-sub">
                    Sub-Category
                  </label>
                  <select
                    id="sel-sub"
                    className="select"
                    value={selectedSubCategory}
                    onChange={(e) => {
                      setSelectedSubCategory(e.target.value);
                      setEditorPage(1);
                    }}
                    style={{ fontWeight: 600 }}
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
              <div className="path-row">
                <span className="path-label">Hierarchy:</span>
                <span className="badge badge-gray">{selectedParentOfCategory || "—"}</span>
                <span className="path-sep">›</span>
                <span className="badge badge-indigo">{selectedCategory || "—"}</span>
                <span className="path-sep">›</span>
                <span className="badge badge-gray">
                  {selectedSubCategory || "All sub-categories"}
                </span>
              </div>

              {/* Category mini KPIs */}
              <div className="stat-row" style={{ marginTop: "14px" }}>
                <div className="stat-tile">
                  <div className="stat-label">Total Debits</div>
                  <div className="stat-value text-outflow">{formatCurrency(catDebits)}</div>
                </div>
                <div className="stat-tile">
                  <div className="stat-label">Total Credits</div>
                  <div className="stat-value text-inflow">{formatCurrency(catCredits)}</div>
                </div>
                <div className="stat-tile">
                  <div className="stat-label">Net Flow</div>
                  <div
                    className={`stat-value ${
                      catCredits - catDebits >= 0 ? "text-inflow" : "text-outflow"
                    }`}
                  >
                    {formatCurrency(catCredits - catDebits)}
                  </div>
                </div>
                <div className="stat-tile">
                  <div className="stat-label">Transactions</div>
                  <div className="stat-value text-primary">{formatNumber(catCount)}</div>
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
              onSelectDirection={selectDirection}
              activeDirection={filters.direction}
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
                /* Same note writer as the explorer table, so a note written
                   in a drill-down is the note that shows there. */
                onNoteSave={async (ref, note) => {
                  await writeNote({ chq_refs: [ref], note });
                }}
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
              </>
            )}
          </div>
        )}

        {/* TAB 3: Cards — what the bank schema cannot hold: the issuer's printed
            cycle totals, its own category, and whether the bank actually paid
            each statement. Card *spend* is not here: it is the Overview tab
            with the sidebar's basis set to Card. */}
        {activeTab === "cards" && (
          <div className="stack">
            <CreditCardsPanel
              onPreviewRule={previewRule}
              onApplyCascade={applyCascadeRule}
              onRefresh={handleDataRefresh}
            />
          </div>
        )}

        {/* TAB 4: Insights — a plain-language read on the same filtered range.
            Reads the shared sidebar filters, so it can never describe a different
            period or scope than the tabs above it. */}
        {activeTab === "insights" && (
          <div className="stack">
            <InsightsPanel
              filters={filters}
              ready={ready}
              txnTypes={meta?.txn_types ?? []}
              categories={categories}
              subCategories={subCategories}
              onPreviewRule={previewRule}
              onApplyCascade={applyCascadeRule}
              onRefresh={handleDataRefresh}
              onNoteSave={async (ref, note) => {
                await writeNote({ chq_refs: [ref], note });
              }}
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

        {/* The one category editor, opened by any table that supplies
            onCategoryChange. A cascade can be scoped to this transaction, the
            same merchant, or a narration keyword, with per-row exclusions. */}
        <CascadeModal
          isOpen={isCascadeOpen}
          pendingEdits={pendingEdits}
          subCategories={subCategories}
          onClose={() => setIsCascadeOpen(false)}
          onPreviewRule={previewRule}
          onApplyCascade={async (req) => {
            await applyCascadeRule(req);
            handleDataRefresh();
          }}
        />

        {/* Bulk edits over the ticked rows. Applying a category goes out as one
            `txn` pin per selected row rather than as a merchant or narration
            rule: the selection is a set of rows the user looked at, and widening
            it to rows they never saw is what CascadeModal is for. */}
        <BulkEditModal
          isOpen={bulkMode !== null}
          mode={bulkMode ?? "category"}
          selectedRows={selectedRows}
          categories={categories}
          leavesOf={meta?.leaves_of ?? {}}
          onClose={() => setBulkMode(null)}
          onApplyCategory={async (category, subCategory) => {
            await applyRules(
              selectedRows.map((r) => ({
                rule_type: "txn" as const,
                rule_key: r.Chq_Ref_Number,
                category,
                sub_category: subCategory,
              }))
            );
            handleDataRefresh();
          }}
          onApplyNote={async (note) => {
            await writeNote({
              chq_refs: selectedRows.map((r) => r.Chq_Ref_Number),
              note,
            });
          }}
        />

        {/* Suggestions. Nothing is applied until a row is ticked here, so a model
            that is confidently wrong cannot change the ledger by itself. */}
        <SuggestModal
          isOpen={suggestOpen}
          rows={selectedRows}
          categories={categories}
          onClose={() => setSuggestOpen(false)}
          onSuggest={(description) =>
            suggest(selectedRows.map((r) => r.Chq_Ref_Number), description)
          }
          onApply={async (entries) => {
            await applyRules(
              entries.map((e) => ({
                rule_type: "txn" as const,
                rule_key: e.chq_ref,
                category: e.category,
                sub_category: e.subCategory,
              }))
            );
            // Notes go in per distinct note rather than per row: the writer takes
            // a list of references and one note, so rows sharing a note are one
            // call instead of one each.
            const byNote = new Map<string | null, string[]>();
            entries.forEach((e) => {
              const list = byNote.get(e.note) || [];
              list.push(e.chq_ref);
              byNote.set(e.note, list);
            });
            await Promise.all(
              Array.from(byNote.entries()).map(([note, refs]) =>
                writeNote({ chq_refs: refs, note, source: note ? "llm" : "user" })
              )
            );
            handleDataRefresh();
            setSelectedRefs([]);
          }}
        />

        <CategoryDefinitionsPanel
          isOpen={definitionsOpen}
          definitions={definitions}
          onClose={() => setDefinitionsOpen(false)}
          onSave={async (payload) => {
            await upsertDefinition(payload);
          }}
        />
      </main>
    </div>
  );
}
