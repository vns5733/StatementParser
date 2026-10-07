import useSWR, { useSWRConfig } from "swr";
import api from "@/lib/api";
import type { LLMStatus, SuggestResponse } from "@/types";

const fetcher = (url: string) => api.get(url).then((res) => res.data);

export interface StoredNote {
  note: string | null;
  source: string | null;
  suggestion: string | null;
  updated_at: string | null;
}

export interface NoteWritePayload {
  chq_refs: string[];
  /** null clears the note. "" is normalised to null server-side. */
  note: string | null;
  suggestion?: string | null;
  source?: string;
}

/**
 * Whether the local opencode server can serve a suggestion.
 *
 * Polled on a slow interval and paused by default rather than fetched once on
 * mount. The server's availability is a property of the user's machine, not of
 * this page: someone who has not started `opencode serve` should see a disabled
 * button with the reason on it, and should not pay for a request on every render
 * just to be told no.
 */
export function useLLMStatus() {
  const { data } = useSWR<LLMStatus>("/llm/status", fetcher, {
    refreshInterval: 60_000,
    revalidateOnFocus: true,
  });
  return data || null;
}

/**
 * Writes or clears notes for many transactions in one request.
 *
 * Notes ride along in the transaction row rather than being fetched per row, so
 * the table always shows the current text. That makes this the only writer, and
 * it must revalidate the transaction keyspace afterwards or the row will keep
 * displaying the value it was rendered with until something else happens to
 * refetch - a save that looks like it did nothing.
 */
export function useNoteActions() {
  const { mutate } = useSWRConfig();

  const revalidateTransactions = () =>
    mutate(
      (key) =>
        typeof key === "string" &&
        (key.startsWith("/transactions") || key.startsWith("/cards")),
      undefined,
      { revalidate: true }
    );

  const writeNote = async (payload: NoteWritePayload) => {
    const res = await api.post("/notes", payload);
    await revalidateTransactions();
    return res.data;
  };

  const deleteNotes = async (chq_refs: string[]) => {
    const res = await api.post("/notes/delete", { chq_refs });
    await revalidateTransactions();
    return res.data;
  };

  /**
   * Asks the local opencode server to suggest a category for each row.
   *
   * Never revalidates on its own: a suggestion changes nothing until the user
   * accepts one, and accepting goes through the same rule writer the rest of the
   * app uses. Refetching here would show the suggestion as though it were already
   * applied.
   */
  const suggest = async (chq_refs: string[], description?: string) => {
    const res = await api.post<SuggestResponse>("/llm/suggest", {
      chq_refs,
      description: description?.trim() || null,
    });
    return res.data;
  };

  return { writeNote, deleteNotes, suggest, revalidateTransactions };
}