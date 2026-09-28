import useSWR from "swr";
import api from "@/lib/api";
import type {
  CardSummary,
  CardStatement,
  CardSpendEntry,
  ReconcileResponse,
  IssuerCategoryStat,
} from "@/types";

const fetcher = (url: string) => api.get(url).then((res) => res.data);

export function useCards() {
  const { data, error, isLoading } = useSWR<CardSummary[]>(
    "/cards",
    fetcher,
    { revalidateOnFocus: false }
  );
  return { cards: data || [], error, isLoading };
}

export function useCardStatements() {
  const { data, error, isLoading } = useSWR<CardStatement[]>(
    "/cards/statements",
    fetcher,
    { revalidateOnFocus: false }
  );
  return { cardStatements: data || [], error, isLoading };
}

export function useCardSpend() {
  const { data, error, isLoading } = useSWR<CardSpendEntry[]>(
    "/cards/spend",
    fetcher,
    { revalidateOnFocus: false }
  );
  return { cardSpend: data || [], error, isLoading };
}

export function useIssuerCategoryStats() {
  const { data, error, isLoading } = useSWR<IssuerCategoryStat[]>(
    "/cards/issuer-categories",
    fetcher,
    { revalidateOnFocus: false }
  );
  return { issuerCategoryStats: data || [], error, isLoading };
}

export function useReconcile() {
  const { data, error, isLoading } = useSWR<ReconcileResponse>(
    "/cards/reconcile",
    fetcher,
    { revalidateOnFocus: false }
  );
  return { reconcile: data, error, isLoading };
}
