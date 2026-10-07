// TypeScript interfaces matching FastAPI response shapes

export interface Transaction {
  Chq_Ref_Number: string;
  Date: string;
  Narration: string;
  Transaction_Type: string;
  /** Parent rollup, e.g. Housing. */
  Category: string;
  /** Middle level, e.g. Rent. */
  Broad_Category: string;
  /** Leaf, e.g. Residential_Rent / CoLiving_Rent / Rent_Brokerage. */
  Sub_Category: string;
  Payee_Receiver: string | null;
  Debit_Amount: number | null;
  Credit_Amount: number | null;
  Closing_Balance: number | null;
  Details: string | null;
  Reference_ID: string | null;
  Year: number | null;
  Month: number | null;
  Month_Name: string | null;
  Year_Month: string | null;
  /** True when the counterparty repeats on a roughly monthly cadence. */
  is_recurring: boolean;
  /** Which ledger this row came from: a bank account or a credit card. */
  Account_Source: AccountSource;
  /**
   * True when the row moves money between the bank and a card rather than
   * spending it. These rows are kept in the ledger and in this table, but are
   * excluded from spend totals so a card purchase is not counted again when its
   * bill is paid.
   */
  Is_Settlement: boolean;
  /**
   * Resolved direction after any user override. This is the single source of
   * truth: exactly one of Debit_Amount / Credit_Amount is non-zero and the
   * amount has already been moved between them server-side, so a flipped row
   * sums correctly everywhere without the UI doing any arithmetic.
   */
  Direction?: "DEBIT" | "CREDIT" | null;
  /** Where the direction came from: 'parsed' or the rule type that overrode it. */
  Direction_Source?: string | null;
  /** Which card, for rows that came from a card statement. */
  Card_Name?: string | null;
  Card_Issuer?: string | null;
  /** Stable card key; NULL on bank rows. Used by the card view's per-card filter. */
  Card_ID?: string | null;
  /**
   * The user's own free-text note on this transaction - what it was actually for,
   * which a bank narration often does not say.
   */
  Note?: string | null;
  /** Who wrote it: 'user' or 'llm'. An LLM note is a guess, not a confirmation. */
  Note_Source?: string | null;
  Note_Updated_At?: string | null;
  /** The last proposal the LLM made for this row, kept even if rejected. */
  Suggestion?: string | null;
  /**
   * Which side of the ledger this category is about: money in, money out, or both.
   */
  Category_Direction?: CategoryDirection;
  /**
   * True when the row's category disagrees with the side its money actually moved -
   * a credit filed under an expense category, most likely a refund. Flagged rather
   * than moved, because the category is already right for the arithmetic.
   */
  Direction_Mismatch?: boolean;
  Direction_Mismatch_Reason?: string | null;
  /**
   * Set when the direction reconciler re-filed this row (a credit on Investment is
   * money coming back out, so it becomes Investment_Liquidation). Kept so the table
   * can show what changed instead of presenting a label the parser never produced.
   */
  Direction_Reclassified?: string | null;
}

/** Whether a category is about money arriving, money leaving, or either. */
export type CategoryDirection = "IN" | "OUT" | "BOTH";

export interface TransactionPage {
  total: number;
  /** Effective page after server-side clamping to the valid range. */
  page: number;
  page_size: number;
  total_pages: number;
  data: Transaction[];
}

export interface KPIs {
  /**
   * Inflow. Card settlements are EXCLUDED: a card bill payment is a transfer,
   * not income, so counting its card-side half here would report a payment as
   * earnings. See settlement_credits for the excluded amount.
   */
  total_credits: number;
  /** Outflow, on the same basis as total_credits - settlements excluded. */
  total_debits: number;
  net_cashflow: number;
  /** Alias of total_debits; both are spend figures, neither includes settlements. */
  total_spend_debits: number;
  /** Bank-side card payments: money out, reported but not counted. */
  settlement_debits: number;
  /** Card-side card payments: money in, reported but not counted. */
  settlement_credits: number;
  /**
   * Rows in the filtered set, including settlements - this matches the
   * transaction table, which still shows every row.
   */
  filtered_count: number;
  /**
   * Rows the amount tiles and the timeline actually aggregate. Differs from
   * filtered_count by exactly the settlement rows, so a header paired with a
   * spend chart must use this one.
   */
  spend_count: number;
  settlement_count: number;
  total_count: number;
}

export type DirectionMode = "txn" | "merchant" | "narration";
export type TxnDirection = "DEBIT" | "CREDIT";

export interface DirectionRule {
  id?: number;
  rule_type: DirectionMode;
  rule_key: string;
  direction: TxnDirection;
}

export interface PreviewDirectionResponse {
  /** Rows the rule matches, including ones already in the requested direction. */
  total_matched: number;
  /** Rows that would actually change. This is what the user acts on. */
  total: number;
  transactions: Transaction[];
}

export interface ApplyDirectionCascadeRequest {
  rule_type: DirectionMode;
  rule_key: string;
  direction: TxnDirection;
  excluded_chq_refs?: string[];
}

export interface TimelineEntry {
  label: string;
  Year?: number;
  Year_Month?: string;
  Month_Name?: string;
  Total_Credit: number;
  Total_Debit: number;
  Count: number;
}

export interface MonthlyCategoryEntry {
  label: string;
  Year_Month?: string;
  Year?: number;
  Broad_Category: string;
  Total_Credit: number;
  Total_Debit: number;
  Count: number;
}

export interface CategoryBreakdownEntry {
  Category: string;
  Total_Debit: number;
  Total_Credit: number;
}

export interface BalanceTrendEntry {
  Date: string;
  Closing_Balance: number;
}

export interface CategoryTrendEntry {
  Year_Month: string;
  Total_Debit: number;
  Total_Credit: number;
}

export interface Meta {
  years: number[];
  months: number[];
  txn_types: string[];
  /** Parent rollup level, e.g. Housing / Food / Transfers. */
  categories: string[];
  broad_categories: string[];
  /** Leaf level, e.g. Residential_Rent / Rent_Brokerage. */
  sub_categories: string[];
  /** Broad_Category -> parent Category lookup, for showing the full path. */
  parent_of: Record<string, string>;
  /** Broad_Category -> its leaves, for cascading the pickers. */
  leaves_of: Record<string, string[]>;
  /** Ledgers that actually hold data, e.g. ["BANK", "CREDIT_CARD"]. */
  account_sources: AccountSource[];
  /**
   * Cards that actually have rows in the ledger. Built from the rows rather than
   * the card registry, so a card that parsed zero transactions is not offered.
   */
  cards?: MetaCard[];
}

/** A card as it appears in the shared ledger, for the per-card picker. */
export interface MetaCard {
  Card_ID: string;
  Card_Name: string | null;
  Card_Issuer: string | null;
  Txn_Count: number;
}

export interface Filters {
  years: number[];
  months: number[];
  txnTypes: string[];
  broadCategories: string[];
  /** Parent level filter. */
  categories: string[];
  /** Leaf level filter. */
  subCategories: string[];
  /** null = both, otherwise only recurring or only one-off. */
  isRecurring: boolean | null;
  direction: "all" | "debits" | "credits";
  search: string;
  amountField: "debit" | "credit" | "any";
  amountMin: number | null;
  amountMax: number | null;
  /** Exact "YYYY-MM" periods, used to scope summary-table drill-downs. */
  yearMonths?: string[];
  /**
   * Which ledger to read spend from. Card settlements (the bank debit that pays
   * the card bill) are excluded from every basis, so a card purchase is counted
   * once - at the merchant - rather than again when the bill is paid.
   */
  spendBasis: SpendBasis;
  /** Empty = both ledgers. */
  accountSources: AccountSource[];
  /**
   * Narrows to specific physical cards. Empty = every card. Only meaningful for
   * card rows (bank rows carry no Card_ID), so it is a no-op on the bank side
   * rather than an error - which lets the card view reuse the same filter path.
   */
  cardIds?: string[];
  /**
   * Exact `Payee_Receiver` values, used to drill into one merchant from the
   * Insights top-merchants list. Exact rather than reusing `search`, which would
   * also match the same text inside a Narration or Reference_ID and so could
   * surface another merchant's rows. Not a sidebar control.
   */
  payee?: string[];
  /**
   * null = both, otherwise only rows whose category disagrees with the side their
   * money moved (a credit under an expense category, and so on). This is how the
   * rows the reconciler could NOT fix on its own get found.
   */
  directionMismatch?: boolean | null;
  /** null = both, otherwise only rows with (or without) a user note. */
  hasNote?: boolean | null;
}

/** What each category is for, in the user's own words. */
export interface CategoryDefinition {
  name: string;
  description: string | null;
  /** Concrete merchant or keyword hints. */
  examples: string | null;
  /** The direction in force: the user's override, or the code default. */
  direction: CategoryDirection;
  /** The user's override, or null when there is none. */
  direction_override: CategoryDirection | null;
  /** The code-level default, so a "reset to default" control has something to reset to. */
  code_direction: CategoryDirection;
  is_builtin: boolean;
}

export interface DefinitionsResponse {
  definitions: CategoryDefinition[];
}

/** Whether the local opencode server can serve a suggestion, and why not if not. */
export interface LLMStatus {
  available: boolean;
  version: string | null;
  model: string;
  detail: string | null;
}

/** One row's proposal. `category` is null when the model named something off-taxonomy. */
export interface CategorySuggestion {
  id: string;
  category: string | null;
  sub_category?: string | null;
  confidence: number | null;
  note?: string | null;
  reason?: string | null;
  /** The off-taxonomy name the model invented, shown so the rejection is visible. */
  invalid_category?: string | null;
  /** True when the model returned no entry for this row. */
  skipped?: boolean;
}

export interface SuggestResponse {
  count: number;
  /** How many rows the model actually answered; count - answered were skipped. */
  answered: number;
  suggestions: CategorySuggestion[];
  /** Source data per answered row, keyed by the same Chq_Ref_Number as `id`. */
  transactions: Partial<Transaction>[];
  model: string | null;
}

/** "all" combines bank and card spend with settlements removed. */
export type SpendBasis = "all" | "bank_only" | "card_only";

export type AccountSource = "BANK" | "CREDIT_CARD";

// ---------------------------------------------------------------------------
// Credit cards
// ---------------------------------------------------------------------------

export interface CardSummary {
  Card_ID: string;
  Issuer: string | null;
  Card_Name: string | null;
  Last4: string | null;
  Credit_Limit: number | null;
  First_Seen: string | null;
  Last_Seen: string | null;
  Statement_Count: number;
  Total_Parsed_Spend: number;
}

export interface CardStatement {
  Statement_ID: string;
  Card_ID: string;
  Issuer: string | null;
  Card_Name: string | null;
  Statement_Date: string | null;
  Due_Date: string | null;
  Period_Start: string | null;
  Period_End: string | null;
  Previous_Dues: number | null;
  Payments_Received: number | null;
  /** The issuer's printed PURCHASES/DEBIT - purchases only. */
  Total_Spend: number | null;
  Finance_Charges: number | null;
  Total_Due: number | null;
  Minimum_Due: number | null;
  Credit_Limit: number | null;
  Available_Credit_Limit: number | null;
  Txn_Count: number;
  /** Sum of the parsed debit rows; should agree with Total_Spend. */
  Parsed_Spend: number | null;
  Parsed_Refunds: number | null;
  /** The issuer's own statement-level category split, e.g. HDFC's PI block. */
  Spend_Mix: Record<string, number> | null;
  Source_File: string | null;
  Imported_At: string | null;
}

export interface CardSpendEntry {
  Card_Name: string | null;
  Issuer: string | null;
  Category: string;
  Spend: number;
  Refunds: number;
  Count: number;
}

export interface ReconcileMatch {
  Statement_ID: string;
  Card_ID: string | null;
  Card_Name: string | null;
  Issuer: string | null;
  Statement_Date: string | null;
  Due_Date: string | null;
  Bank_Chq_Ref: string;
  Bank_Payment_Date: string | null;
  Bank_Amount: number;
  Billed_Amount: number;
  Match_Basis: string;
  Variance: number;
  Statement_Spend: number | null;
  Parsed_Spend: number | null;
}

export interface ReconcileUnmatched {
  Statement_ID: string;
  Card_Name: string | null;
  Issuer: string | null;
  Statement_Date: string | null;
  Total_Due: number | null;
  Total_Spend: number | null;
  reason: string;
  closest_amount: number | null;
  variance: number | null;
}

export interface ReconcileResponse {
  summary: {
    statements: number;
    bank_debits: number;
    matched: number;
    unmatched_statements: number;
    unmatched_bank_debits: number;
    variance_total: number;
  };
  matched: ReconcileMatch[];
  unmatched_statements: ReconcileUnmatched[];
  unmatched_bank_debits: { Chq_Ref_Number: string; Date: string | null; Debit_Amount: number }[];
  unmatched_bank_debit_count: number;
}

export interface IssuerCategoryStat {
  Issuer: string | null;
  Card_Name: string | null;
  Txn_Count: number;
  Issuer_Categorised: number;
  Coverage_Pct: number;
}

// ---------------------------------------------------------------------------
// Insights
// ---------------------------------------------------------------------------

/** One month of the cash-flow trend. `Year_Month` is the label (YYYY-MM). */
export interface InsightMonth {
  Year_Month: string;
  Total_Debit: number;
  Total_Credit: number;
  /** Credit minus debit for the month. */
  Net: number;
  Txn_Count: number;
}

/** A parent-rollup category, with its leaves nested underneath. */
export interface InsightCategory {
  Category: string;
  Spend: number;
  Count: number;
  /**
   * Recurring and one-off halves of `Spend`, from the same settlement-excluded
   * frame, so the two always add back up to the total.
   */
  Recurring: number;
  "One-off": number;
  sub_breakdown: InsightSubCategory[];
}

export interface InsightSubCategory {
  Sub_Category: string;
  Spend: number;
  Count: number;
}

export interface InsightMerchant {
  Payee_Receiver: string;
  Spend: number;
  Count: number;
  Avg_Amount: number;
}

export interface InsightTxnType {
  Transaction_Type: string;
  Spend: number;
  Count: number;
  Avg_Amount: number;
}

export interface InsightDayOfWeek {
  /** 0 = Monday. */
  DayOfWeek: number;
  DayOfWeekName: string;
  Spend: number;
  Count: number;
  Avg_Amount: number;
}

export interface InsightSourceSplit {
  Account_Source: AccountSource;
  Spend: number;
  Count: number;
  Avg_Amount: number;
}

/**
 * Settlements are reported rather than silently dropped, alongside the scope flag
 * that decided the correction. `excluded_from_cashflow` is false for a
 * single-ledger view, where a bill payment is real inflow (card) or real outflow
 * (bank) and therefore belongs in the cash-flow blocks.
 */
export interface InsightSettlements {
  settlement_debits: number;
  settlement_credits: number;
  settlement_count: number;
  excluded_from_cashflow: boolean;
}

export interface InsightsResponse {
  /** Cash-flow scoped: debits, credits and net per month. */
  monthly_trend: InsightMonth[];
  /** Spend scoped: settlements always excluded. */
  top_categories: InsightCategory[];
  top_merchants: InsightMerchant[];
  txn_type_breakdown: InsightTxnType[];
  recurring_vs_oneoff: {
    recurring_spend: number;
    oneoff_spend: number;
    recurring_count: number;
    oneoff_count: number;
  };
  /** Cash-flow scoped, so savings means what actually moved. */
  savings_analysis: {
    total_income: number;
    total_expenses: number;
    savings: number;
    /** Percent of income kept. */
    savings_rate: number;
  };
  dow_pattern: InsightDayOfWeek[];
  account_source_breakdown: InsightSourceSplit[];
  settlements: InsightSettlements;
  period: {
    start: string | null;
    end: string | null;
    /** Inclusive month count between start and end. */
    months: number;
  };
}

export type GroupBy = "month" | "year";

/** Any level of the category hierarchy, or the raw channel type. */
export type GroupCol = "Category" | "Broad_Category" | "Sub_Category" | "Transaction_Type";

export type CascadeMode = "txn" | "merchant" | "narration";

export interface PreviewRuleRequest {
  rule_type: CascadeMode;
  rule_key: string;
}

export interface PreviewRuleResponse {
  total: number;
  transactions: Transaction[];
}

export interface ApplyCascadeRequest {
  rule_type: CascadeMode;
  rule_key: string;
  category: string;
  /** Optional leaf; the server derives one when omitted. */
  sub_category?: string | null;
  excluded_chq_refs: string[];
}
