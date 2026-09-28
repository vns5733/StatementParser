# Implementation Plan — Fix Category Reassignment & Add Affected Transactions Preview

The user reported two key issues in the Next.js UI regarding **Reassign Transaction Categories** (Tab 3):
1. **Category Filtering:** In "Reassign Transaction Categories", the user expects to see transactions for the selected category by default, with an option/toggle to filter to the selected category only (currently it shows page 1 of all transactions).
2. **Affected Transactions Preview:** When reassigning and cascading (by txn, merchant, or narration keyword), the user should see which transactions will get affected, with the ability to review and exclude specific transactions before confirming (as was present in the Streamlit version).

---

## User Review Required

> [!NOTE]
> - By default, opening Tab 3 ("Broad Categories") will show transactions for the selected category with a visible toggle: **"Only show '{selectedCategory}' transactions in the editor"**.
> - When reassigning a category, the cascade modal will query and display all matching transactions in real-time with checkboxes to include or exclude specific rows before applying.

---

## Proposed Changes

### 1. Python Backend (`api/routers/categories.py`)

#### [MODIFY] [`api/routers/categories.py`](file:///d:/My%20Projects/StatementParser/api/routers/categories.py)
- Add `POST /api/categories/preview`:
  - Request: `{ rule_type: "txn" | "merchant" | "narration", rule_key: string }`
  - Response: `{ total: int, transactions: [...] }`
  - Matches across all transactions using the exact precedence and pattern matching logic in `db.py`.
- Add `POST /api/categories/rules/apply-cascade`:
  - Request: `{ rule_type: string, rule_key: string, category: string, excluded_chq_refs: list[str] }`
  - Applies the rule, clears any stale transaction overrides on included items, and pins excluded transactions to their current categories with `txn` rules (exact Streamlit behavior).

---

### 2. Frontend Hooks & Types (`dashboard/src/`)

#### [MODIFY] [`dashboard/src/types/index.ts`](file:///d:/My%20Projects/StatementParser/dashboard/src/types/index.ts)
- Add types for `PreviewRuleRequest`, `PreviewRuleResponse`, and `ApplyCascadeRequest`.

#### [MODIFY] [`dashboard/src/hooks/useCategories.ts`](file:///d:/My%20Projects/StatementParser/dashboard/src/hooks/useCategories.ts)
- Add helper methods `previewRule(rule_type, rule_key)` and `applyCascadeRule({ rule_type, rule_key, category, excluded_chq_refs })`.

---

### 3. Frontend Dashboard Page & Tables (`dashboard/src/app/page.tsx`, `CategoryEditorTable.tsx`)

#### [MODIFY] [`dashboard/src/app/page.tsx`](file:///d:/My%20Projects/StatementParser/dashboard/src/app/page.tsx)
- In Tab 3:
  - Fetch accurate category KPIs using `useKPIs` scoped to `selectedCategory`.
  - Maintain `onlySelectedCategory` state (default `true`).
  - Fetch dedicated paginated transactions for `selectedCategory` when `onlySelectedCategory` is enabled.
  - Pass `selectedCategory`, `onlySelectedCategory`, `onToggleOnlyCategory`, and pagination controls to `CategoryEditorTable`.

#### [MODIFY] [`dashboard/src/components/tables/CategoryEditorTable.tsx`](file:///d:/My%20Projects/StatementParser/dashboard/src/components/tables/CategoryEditorTable.tsx)
- Add header controls:
  - Checkbox toggle: `Only show "${selectedCategory}" transactions in the editor`
  - Transaction count badge
  - Search input for quick filtering within the table
  - Pagination controls (Page X of Y, Previous / Next)
- Pass edited transaction info to the enhanced `CascadeModal`.

---

### 4. Cascade Modal with Live Affected Transactions Preview

#### [MODIFY] [`dashboard/src/components/modals/CascadeModal.tsx`](file:///d:/My%20Projects/StatementParser/dashboard/src/components/modals/CascadeModal.tsx)
- Re-architect modal to include:
  1. Rule mode selection (`txn`, `merchant`, `narration`)
  2. Real-time preview query fetching affected transactions
  3. Interactive affected transactions table:
     - Checkbox per row (`_Include`, default checked)
     - Date, Narration, Payee / Entity, Debit/Credit, Current Category, Reference
     - `Select All Visible` / `Deselect All` buttons
  4. Impact summary (`✓ X will be recategorized · ✗ Y excluded`)
  5. Confirm & Apply invoking `applyCascadeRule`

---

## Verification Plan

### Automated / API Verification
1. Test `POST /api/categories/preview`:
   - Test with `rule_type: "merchant", rule_key: "ZOMATO"`
   - Test with `rule_type: "narration", rule_key: "RENT"`
   - Test with `rule_type: "txn", rule_key: "..."`
   Verify returned JSON includes correct `total` and `transactions` list.
2. Test `POST /api/categories/rules/apply-cascade` with exclusions:
   - Verify excluded items retain their category while included items get recategorized.

### Frontend Verification via Browser Subagent / Inspection
1. Open http://localhost:3000 in browser subagent.
2. Navigate to Tab 3 ("🏷️ Broad Categories").
3. Verify:
   - Only transactions for the selected category appear when "Only show transactions in the editor" is checked.
   - Unchecking the box shows all transactions.
   - Category KPIs show accurate database totals for the selected category.
4. Change a category in the table:
   - Verify modal opens with affected transactions preview.
   - Switch between "Only these transactions", "Same merchant", and "Same narration keyword".
   - Verify the preview updates to show the affected transactions for each choice.
   - Uncheck one transaction to exclude it, click Confirm & Apply, and verify it updates correctly.
