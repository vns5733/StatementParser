import useSWR from "swr";
import api, { buildFilterParams } from "@/lib/api";
import {
  TransactionPage,
  KPIs,
  TimelineEntry,
  MonthlyCategoryEntry,
  CategoryBreakdownEntry,
  BalanceTrendEntry,
  CategoryTrendEntry,
  Meta,
  Filters,
  GroupBy,
  GroupCol,
} from "@/types";

const fetcher = (url: string) => api.get(url).then((res) => res.data);

export function useMeta() {
  const { data, error, isLoading, mutate } = useSWR<Meta>(
    "/transactions/meta",
    fetcher,
    { revalidateOnFocus: false }
  );
  return { meta: data, error, isLoading, mutate };
}

/**
 * The shared shape every filtered hook uses: the caller's filters plus whatever
 * endpoint-specific params that endpoint needs. Passing an object keeps the
 * calls readable and removes the risk of a 13-argument list being mis-ordered.
 */
function query(filters: Filters, extra: Record<string, string> = {}): string {
  return new URLSearchParams({ ...buildFilterParams(filters), ...extra }).toString();
}

export function useKPIs(filters: Filters, enabled = true) {
  const key = enabled ? `/transactions/kpis?${query(filters)}` : null;
  const { data, error, isLoading, mutate } = useSWR<KPIs>(key, fetcher);
  return { kpis: data, error, isLoading, mutate };
}

export function useTransactions(
  filters: Filters,
  page = 1,
  pageSize = 50,
  sortBy = "",
  sortOrder: "asc" | "desc" = "asc",
  enabled = true
) {
  const key = enabled
    ? `/transactions?${query(filters, {
        page: String(page),
        page_size: String(pageSize),
        ...(sortBy ? { sort_by: sortBy, sort_order: sortOrder } : {}),
      })}`
    : null;
  const { data, error, isLoading, mutate } = useSWR<TransactionPage>(key, fetcher);
  return { transactionsPage: data, error, isLoading, mutate };
}

export function useTimelineSummary(filters: Filters, groupBy: GroupBy, enabled = true) {
  const key = enabled
    ? `/transactions/summary/timeline?${query(filters, { group_by: groupBy })}`
    : null;
  const { data, error, isLoading } = useSWR<TimelineEntry[]>(key, fetcher);
  return { timeline: data || [], error, isLoading };
}

export function useMonthlyCategorySummary(filters: Filters, groupBy: GroupBy, enabled = true) {
  const key = enabled
    ? `/transactions/summary/monthly-category?${query(filters, { group_by: groupBy })}`
    : null;
  const { data, error, isLoading } = useSWR<MonthlyCategoryEntry[]>(key, fetcher);
  return { monthlyCategoryData: data || [], error, isLoading };
}

export function useCategoryBreakdown(
  filters: Filters,
  groupCol: GroupCol,
  enabled = true
) {
  const key = enabled
    ? `/transactions/summary/category-breakdown?${query(filters, { group_col: groupCol })}`
    : null;
  const { data, error, isLoading } = useSWR<CategoryBreakdownEntry[]>(key, fetcher);
  return { categoryBreakdown: data || [], error, isLoading };
}

export function useBalanceTrend(filters: Filters, enabled = true) {
  // Balance is meaningless for card rows (they carry no closing balance), so
  // the chart is bank-only regardless of the spend basis the user picked.
  const bankOnly: Filters = { ...filters, spendBasis: "bank_only", cardIds: [] };
  const key = enabled ? `/transactions/balance-trend?${query(bankOnly)}` : null;
  const { data, error, isLoading } = useSWR<BalanceTrendEntry[]>(key, fetcher);
  return { balanceTrend: data || [], error, isLoading };
}

export function useCategoryTrend(
  category: string,
  filters: Filters,
  enabled = true,
  groupCol: "Category" | "Broad_Category" | "Sub_Category" = "Broad_Category"
) {
  // An empty category charts the whole filtered set, so the key is valid even
  // before the user picks a level.
  const key = enabled
    ? `/transactions/category-trend?${query(filters, { category, group_col: groupCol })}`
    : null;
  const { data, error, isLoading } = useSWR<CategoryTrendEntry[]>(key, fetcher);
  return { categoryTrend: data || [], error, isLoading };
}

