# StatementParser: Next.js + FastAPI Migration Walkthrough

The Streamlit UI has been replaced with a modern, high-performance **Next.js 15 (React 19, TypeScript, App Router)** dashboard backed by a **FastAPI** REST backend. All existing Python modules (`db.py`, `loader.py`, `narration_parser.py`, `category_rules.py`, `config.py`) were reused directly without modifications.

---

## 🏗️ Architecture

```
Browser (Next.js 15 Client)
    │  http://localhost:3000
    │  (Axios / SWR / Recharts)
    ▼
Next.js Proxy (`next.config.ts` rewrites `/api/*`)
    ▼
FastAPI Server (`api/main.py`)
    │  http://localhost:8000
    │  - /api/transactions
    │  - /api/categories
    ▼
Existing Python Engine (`db.py`, `loader.py`, `narration_parser.py`, `category_rules.py`)
    ▼
MySQL Database (`statements`)
```

---

## 📦 What Was Built

### 1. Python REST Backend (`api/`)
- [`api/deps.py`](file:///D:/My%20Projects/StatementParser/api/deps.py) — Singleton SQLAlchemy engine dependency with schema auto-migrations.
- [`api/routers/transactions.py`](file:///D:/My%20Projects/StatementParser/api/routers/transactions.py) — Comprehensive endpoints for:
  - `GET /api/transactions`: Filtered & paginated transactions table
  - `GET /api/transactions/meta`: Available filter options (years, months, types, categories)
  - `GET /api/transactions/kpis`: Total Credits, Total Debits, Net Cash Flow, Counts
  - `GET /api/transactions/summary/timeline`: Monthly and yearly Credit vs Debit aggregates
  - `GET /api/transactions/summary/monthly-category`: Category-layered monthly cash flows
  - `GET /api/transactions/summary/category-breakdown`: Donut breakdown by channel or category
  - `GET /api/transactions/balance-trend`: Historical closing balance trajectory
  - `GET /api/transactions/category-trend`: Single category monthly inflow/outflow trend
  - `POST /api/transactions/upload`: Multipart statement file ingestion (`.xls`, `.xlsx`, `.csv`)
  - `POST /api/transactions/recategorize`: Bulk narration re-parsing
- [`api/routers/categories.py`](file:///D:/My%20Projects/StatementParser/api/routers/categories.py) — Full CRUD for broad categories + override rules (txn, merchant, narration).
- [`api/main.py`](file:///D:/My%20Projects/StatementParser/api/main.py) — FastAPI app with CORS middleware and startup hooks.

---

### 2. Next.js 15 Frontend (`dashboard/`)
- **Aesthetic Design System**:
  - Deep dark slate/navy theme (`#090d16`) with radial glow meshes.
  - Glassmorphic panels (`backdrop-filter: blur(16px)` with subtle borders and shadows).
  - Curated financial colors: Emerald `#10b981` (Credits), Crimson `#f43f5e` (Debits), Sky Blue `#38bdf8` (Balances), Indigo `#6366f1` (Accents).
  - Modern typography using Google Font `Inter`.
- **Components Built**:
  - [`KpiCards.tsx`](file:///D:/My%20Projects/StatementParser/dashboard/src/components/KpiCards.tsx): 4-card hero metric bar with glowing borders and formatted INR currency.
  - [`Sidebar.tsx`](file:///D:/My%20Projects/StatementParser/dashboard/src/components/Sidebar.tsx): Drag-and-drop / file input upload, bulk recategorize button, custom category management, reactive filter pills (Years, Months Jan–Dec, Category multiselect, Channel type multiselect, Direction toggle, Search input).
  - [`TabNav.tsx`](file:///D:/My%20Projects/StatementParser/dashboard/src/components/TabNav.tsx): Sleek tab switcher for the 3 main views.
  - **Charts** (built with Recharts):
    - [`TimelineChart.tsx`](file:///D:/My%20Projects/StatementParser/dashboard/src/components/charts/TimelineChart.tsx): Credit vs Debit grouped bar with Monthly/Yearly toggle and custom tooltip.
    - [`CategoryStackChart.tsx`](file:///D:/My%20Projects/StatementParser/dashboard/src/components/charts/CategoryStackChart.tsx): Stacked monthly cash flow layered by broad categories.
    - [`PieChart.tsx`](file:///D:/My%20Projects/StatementParser/dashboard/src/components/charts/PieChart.tsx): Donut distribution chart with Channel/Category toggle and Debit/Credit toggle.
    - [`BalanceTrendChart.tsx`](file:///D:/My%20Projects/StatementParser/dashboard/src/components/charts/BalanceTrendChart.tsx): Closing balance area chart with gradient fill.
    - [`CategoryTrendChart.tsx`](file:///D:/My%20Projects/StatementParser/dashboard/src/components/charts/CategoryTrendChart.tsx): Single-category monthly trend line.
  - **Tables & Modals**:
    - [`SummaryTable.tsx`](file:///D:/My%20Projects/StatementParser/dashboard/src/components/tables/SummaryTable.tsx): Click-to-drilldown timeline summary table.
    - [`TransactionTable.tsx`](file:///D:/My%20Projects/StatementParser/dashboard/src/components/tables/TransactionTable.tsx): Paginated transaction explorer with type badges and client-side instant CSV export.
    - [`CategoryEditorTable.tsx`](file:///D:/My%20Projects/StatementParser/dashboard/src/components/tables/CategoryEditorTable.tsx): Inline category dropdown editor.
    - [`CascadeModal.tsx`](file:///D:/My%20Projects/StatementParser/dashboard/src/components/modals/CascadeModal.tsx): Dialog to cascade category changes (Only this txn, Same merchant, or Same narration keyword).

---

### 3. Unified Launcher (`start.py`)
- [`start.py`](file:///D:/My%20Projects/StatementParser/start.py) — Starts both FastAPI (`uvicorn`) and Next.js (`npm run dev`) concurrently and handles clean shutdown on `Ctrl+C`.

---

## 🚀 How to Run

To run the unified stack:
```bash
python start.py
```
Then visit **http://localhost:3000** in your browser.

- **Frontend:** http://localhost:3000
- **FastAPI Docs / Swagger:** http://localhost:8000/docs
- **Streamlit:** Remains available via `python run_app.py` if you ever want to compare them.

---

## ✅ Verification
1. **Node.js**: Detected v24.21.0 & npm v11.19.0.
2. **FastAPI**: Loaded successfully and verified schema endpoints.
3. **Next.js**: Production build compiled with Turbopack and passed all TypeScript checks without errors (`npm run build` exit code 0).
