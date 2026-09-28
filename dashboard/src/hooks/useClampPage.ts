import { useEffect } from "react";

/**
 * Keeps `page` inside the valid range for `total` and returns the page count.
 *
 * Narrowing a filter, switching drill-down period, or re-importing statements can
 * shrink the result set while the user is several pages deep. Without this, the
 * requested page is out of range, the response is empty, and the pagination
 * controls disappear — leaving no way back to the first page.
 *
 * Clamping is skipped while a request is in flight so the transient empty
 * response from a revalidation never forces a premature jump to page 1.
 */
export function useClampPage(
  page: number,
  pageSize: number,
  total: number,
  setPage: (page: number) => void,
  isLoading = false
): number {
  const safeTotal = Number.isFinite(total) ? total : 0;
  const safeSize = pageSize > 0 ? pageSize : 1;
  const totalPages = Math.max(1, Math.ceil(safeTotal / safeSize));

  useEffect(() => {
    if (isLoading) return;
    if (page > totalPages) setPage(totalPages);
    if (page < 1) setPage(1);
  }, [page, totalPages, isLoading, setPage]);

  return totalPages;
}
