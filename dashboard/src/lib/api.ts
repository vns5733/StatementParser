import axios from "axios";

import type { AccountSource, Filters, SpendBasis } from "@/types";

const api = axios.create({
  baseURL: "/api",
  headers: { "Content-Type": "application/json" },
});

export default api;

/**
 * Builds the query string shared by every filtered endpoint.
 *
 * Takes an object rather than a long positional list: the parameter set has
 * grown past a dozen, and positional args at that length are easy to pass in
 * the wrong order without any error.
 */
export function buildFilterParams(filters: Partial<Filters>): Record<string, string> {
  const params: Record<string, string> = {};
  if (filters.years?.length) params.years = filters.years.join(",");
  if (filters.months?.length) params.months = filters.months.join(",");
  if (filters.txnTypes?.length) params.txn_types = filters.txnTypes.join(",");
  if (filters.broadCategories?.length) params.broad_categories = filters.broadCategories.join(",");
  if (filters.categories?.length) params.categories = filters.categories.join(",");
  if (filters.subCategories?.length) params.sub_categories = filters.subCategories.join(",");
  if (filters.accountSources?.length) params.account_sources = filters.accountSources.join(",");
  if (filters.cardIds?.length) params.card_ids = filters.cardIds.join(",");
  if (filters.payee?.length) params.payee = filters.payee.join(",");
  if (filters.isRecurring === true) params.is_recurring = "true";
  else if (filters.isRecurring === false) params.is_recurring = "false";
  if (filters.direction && filters.direction !== "all") params.direction = filters.direction;
  if (filters.search?.trim()) params.search = filters.search.trim();
  if (filters.amountField) params.amount_field = filters.amountField;
  if (filters.amountMin != null && Number.isFinite(filters.amountMin))
    params.amount_min = String(filters.amountMin);
  if (filters.amountMax != null && Number.isFinite(filters.amountMax))
    params.amount_max = String(filters.amountMax);
  if (filters.yearMonths?.length) params.year_months = filters.yearMonths.join(",");
  if (filters.spendBasis && filters.spendBasis !== "all") params.spend_basis = filters.spendBasis;
  // Tri-state: absent means "both", which must send nothing at all rather than
  // "false" - the server would read false as "only unflagged rows" and the user
  // would be left wondering where the 64 flagged refunds went.
  if (filters.directionMismatch === true) params.direction_mismatch = "true";
  else if (filters.directionMismatch === false) params.direction_mismatch = "false";
  if (filters.hasNote === true) params.has_note = "true";
  else if (filters.hasNote === false) params.has_note = "false";
  return params;
}

/**
 * Downloads the complete filtered set as CSV.
 *
 * The browser-side export in TransactionTable only ever holds the current page,
 * so the full export is served by GET /transactions/export instead. The filename
 * comes from the response's Content-Disposition header when present.
 */
export async function downloadFilteredCSV(filters: Partial<Filters>): Promise<void> {
  const params = new URLSearchParams(buildFilterParams(filters)).toString();
  const res = await api.get(`/transactions/export?${params}`, { responseType: "blob" });

  const disposition = res.headers["content-disposition"] || "";
  const match = /filename="?([^";]+)"?/i.exec(disposition);
  const filename = match
    ? match[1]
    : `statement_filtered_${new Date().toISOString().slice(0, 10)}.csv`;

  const href = URL.createObjectURL(res.data as Blob);
  const link = document.createElement("a");
  link.href = href;
  link.setAttribute("download", filename);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(href);
}
