import useSWR from "swr";
import api from "@/lib/api";
import { CascadeMode, PreviewRuleResponse, ApplyCascadeRequest } from "@/types";
import type {
  ApplyDirectionCascadeRequest,
  DirectionMode,
  DirectionRule,
  PreviewDirectionResponse,
  TxnDirection,
} from "@/types";

const fetcher = (url: string) => api.get(url).then((res) => res.data);

export interface CategoryRulePayload {
  rule_type: CascadeMode;
  rule_key: string;
  category: string;
  /** Optional leaf. Omit to let the server derive one from the parent. */
  sub_category?: string | null;
}

export function useCategories() {
  const { data, error, isLoading, mutate } = useSWR<string[]>(
    "/categories",
    fetcher
  );

  const {
    data: customData,
    error: customError,
    mutate: mutateCustom,
  } = useSWR<string[]>("/categories/custom", fetcher);

  // Every leaf in the hierarchy, for the sub-category dropdowns and filters.
  const { data: subData, mutate: mutateSubs } = useSWR<string[]>(
    "/categories/sub",
    fetcher
  );

  const addCategory = async (name: string) => {
    await api.post("/categories", { name });
    mutate();
    mutateCustom();
  };

  const deleteCategory = async (name: string) => {
    await api.delete(`/categories/${encodeURIComponent(name)}`);
    mutate();
    mutateCustom();
  };

  const applyRules = async (rules: CategoryRulePayload[]) => {
    const res = await api.post("/categories/rules", { rules });
    mutate();
    mutateSubs();
    return res.data;
  };

  const previewRule = async (rule_type: CascadeMode, rule_key: string): Promise<PreviewRuleResponse> => {
    const res = await api.post("/categories/preview", { rule_type, rule_key });
    return res.data;
  };

  const applyCascadeRule = async (payload: ApplyCascadeRequest) => {
    const res = await api.post("/categories/rules/apply-cascade", payload);
    mutate();
    mutateSubs();
    return res.data;
  };

  const deleteRules = async (rule_type: string, rule_keys: string[]) => {
    const res = await api.post("/categories/rules/delete", {
      rule_type,
      rule_keys,
    });
    mutate();
    mutateSubs();
    return res.data;
  };

  // ---- Debit/credit overrides -------------------------------------------
  // The same three rule types as categories, so a correction can be scoped to
  // one transaction, a merchant, or a narration keyword. `onApplied` lets the
  // caller refresh whatever it renders, since flipping a direction moves the
  // amount between the two amount columns and therefore changes every total.
  const listDirectionRules = async () => {
    const res = await api.get("/transactions/direction-rules");
    return res.data as DirectionRule[];
  };

  const previewDirection = async (
    rule_type: DirectionMode,
    rule_key: string,
    direction: TxnDirection
  ): Promise<PreviewDirectionResponse> => {
    const res = await api.post("/transactions/direction-rules/preview", {
      rule_type,
      rule_key,
      direction,
    });
    return res.data;
  };

  const applyDirectionCascade = async (payload: ApplyDirectionCascadeRequest) => {
    const res = await api.post("/transactions/direction-rules/apply-cascade", payload);
    return res.data;
  };

  const applyDirectionRule = async (rule: DirectionRule) => {
    const res = await api.post("/transactions/direction-rules", { rules: [rule] });
    return res.data;
  };

  const deleteDirectionRules = async (
    rule_type: DirectionMode,
    rule_keys: string[]
  ) => {
    const res = await api.post("/transactions/direction-rules/delete", {
      rule_type,
      rule_keys,
    });
    return res.data;
  };

  return {
    categories: data || [],
    customCategories: customData || [],
    subCategories: subData || [],
    isLoading,
    error,
    addCategory,
    deleteCategory,
    applyRules,
    previewRule,
    applyCascadeRule,
    deleteRules,
    mutate,
    mutateSubs,
    listDirectionRules,
    previewDirection,
    applyDirectionCascade,
    applyDirectionRule,
    deleteDirectionRules,
  };
}

