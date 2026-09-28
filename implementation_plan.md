# Replace Streamlit UI with a Next.js + FastAPI Dashboard

Node.js v24 / npm v11 is already installed. The plan migrates the dashboard from Streamlit to a **Next.js 15 (App Router) + FastAPI** stack — a proper full-stack setup that gives you a premium SPA-style UI backed by a thin Python REST API that reuses all existing Python modules unchanged.

---

## Architecture Overview

```
Browser (Next.js 15 SPA)
    ↕  REST/JSON  (Axios)
FastAPI (Python)  →  existing db.py / loader.py / narration_parser.py / category_rules.py
    ↕
MySQL
```

- **`/api/` (FastAPI)** — new thin Python server, runs on port `8000`. Calls existing Python modules directly. Started with `uvicorn`.
- **`/dashboard/` (Next.js 15)** — new frontend, runs on port `3000`. Talks to FastAPI via HTTP. Charts with Recharts (React-native, lightweight). UI styled with CSS Modules + design system (dark glassmorphism theme).

All existing Python files (`db.py`, `loader.py`, `narration_parser.py`, `category_rules.py`, `config.py`, etc.) are **untouched**.

---

## User Review Required

> [!IMPORTANT]
> **Framework choice** — Next.js 15 (React 19, App Router, Server + Client Components) is the recommended modern framework for a data dashboard. It gives you file-based routing, server-side rendering, API route co-location, and a rich ecosystem. The alternative would be Vite + React (pure SPA), but Next.js is strictly more capable for this kind of app.

> [!IMPORTANT]
> **Chart library** — Using **Recharts** (React charting library). It natively supports the same chart types used in Streamlit/Plotly: grouped/stacked bars, line/area, donut pie. If you prefer to keep Plotly charts (rendered via `plotly.js`), let me know and I'll use `react-plotly.js` instead.

> [!WARNING]
> **Two servers to run**: After migration you'll start two processes — `uvicorn api.main:app` (Python/FastAPI) and `npm run dev` (Next.js). A `start.py` launcher script can optionally start both with one command.

> [!NOTE]
> **Streamlit is not deleted** — `app.py` and `run_app.py` will remain. You can still run Streamlit in parallel. The new stack sits in a `dashboard/` subdirectory.

---

## Open Questions

> [!IMPORTANT]
> **File upload handling**: The Streamlit app allows uploading `.xls/.xlsx/.csv` files. FastAPI will receive multipart uploads and pipe them to `loader.py`. This works, but uploaded files are processed in-memory (not stored on disk). Is that acceptable?

> [!IMPORTANT]
> **Category editing / cascade UI**: The Streamlit app has a rich inline `st.data_editor` with a cascade-apply dialog. In Next.js this will be an editable table (using TanStack Table) with a modal dialog for cascade options. Same functionality, better UX. Confirm this approach is fine.

---

## Proposed Changes

### Component 1 — Python FastAPI Backend

#### [NEW] `api/__init__.py`
Empty package marker.

#### [NEW] `api/main.py`
FastAPI app with CORS, lifespan DB init, and all routers mounted. Entry point for `uvicorn`.

#### [NEW] `api/routers/transactions.py`
REST endpoints:
- `GET /api/transactions` — returns all transactions with filters (year, month, txn_type, broad_category, direction, search_query)
- `GET /api/transactions/summary/timeline` — grouped by month or year (Credit/Debit aggregates)
- `GET /api/transactions/summary/categories` — grouped by Broad_Category
- `GET /api/transactions/summary/monthly-category` — cross (Year_Month × Broad_Category)
- `GET /api/transactions/balance-trend` — sorted date × Closing_Balance
- `GET /api/transactions/kpis` — total credits, debits, net, count
- `POST /api/transactions/upload` — multipart file upload → parse → store → return count
- `POST /api/transactions/recategorize` — re-run narration parser over all rows

#### [NEW] `api/routers/categories.py`
- `GET /api/categories` — list all broad categories
- `GET /api/categories/custom` — list user-added only
- `POST /api/categories` — add new category `{name}`
- `DELETE /api/categories/{name}` — delete custom category
- `POST /api/categories/rules` — apply cascade rules `[{rule_type, rule_key, category}]`
- `DELETE /api/categories/rules` — delete specific txn rules by `Chq_Ref_Number`

#### [NEW] `api/deps.py`
Shared SQLAlchemy engine dependency (created once, injected via `Depends`).

---

### Component 2 — Next.js 15 Dashboard

All files under `dashboard/`.

#### [NEW] `dashboard/` (Next.js 15 project)
Bootstrapped with `npx create-next-app@latest ./dashboard --typescript --app --no-tailwind --eslint --src-dir --import-alias "@/*"`.

Key directories:
```
dashboard/
├── src/
│   ├── app/
│   │   ├── layout.tsx          # Root layout (fonts, global CSS)
│   │   ├── page.tsx            # Main dashboard page
│   │   ├── globals.css         # Design tokens, base styles
│   ├── components/
│   │   ├── Sidebar.tsx         # Filters + upload + category management
│   │   ├── KpiCards.tsx        # 4-card metrics row
│   │   ├── TabNav.tsx          # Tab switcher (Analytics / Explorer / Categories)
│   │   ├── charts/
│   │   │   ├── TimelineChart.tsx       # Grouped bar (Credit vs Debit)
│   │   │   ├── CategoryStackChart.tsx  # Stacked bar (by Broad_Category)
│   │   │   ├── PieChart.tsx            # Donut breakdown
│   │   │   ├── BalanceTrendChart.tsx   # Line chart
│   │   │   └── CategoryTrendChart.tsx  # Category-specific line chart
│   │   ├── tables/
│   │   │   ├── TransactionTable.tsx    # TanStack Table with sorting + pagination
│   │   │   ├── SummaryTable.tsx        # Click-to-drilldown summary
│   │   │   └── CategoryEditorTable.tsx # Editable category column + cascade modal
│   │   └── modals/
│   │       └── CascadeModal.tsx        # "Apply to: txn / merchant / keyword" dialog
│   ├── hooks/
│   │   ├── useTransactions.ts   # SWR data fetching hooks
│   │   └── useCategories.ts
│   ├── lib/
│   │   ├── api.ts              # Axios client pointing to FastAPI
│   │   └── formatters.ts       # ₹ formatting, date helpers
│   └── types/
│       └── index.ts            # TypeScript interfaces matching FastAPI response shapes
├── package.json
└── next.config.ts              # rewrites /api/* → http://localhost:8000/api/*
```

#### Design System (globals.css)
- **Dark glassmorphism theme**: deep navy (`#0a0f1e`) background, card backdrop-blur panels, subtle gradient accents.
- **Accent colors**: emerald green for credits, rose red for debits, indigo for neutrals.
- **Typography**: `Inter` (Google Fonts) with numeric tabular figures.
- **Animations**: Framer Motion entry animations on cards and charts (fade-slide-in).
- **Responsive**: Full sidebar on desktop, bottom sheet on mobile.

---

### Component 3 — Launcher

#### [NEW] `start.py`
Convenience launcher — starts FastAPI (`uvicorn`) and Next.js (`npm run dev`) as subprocesses and streams both logs to the terminal with colored prefixes.

---

## Verification Plan

### Automated Tests
- None (matching existing project — no test suite).

### Manual Verification
1. Run `python start.py` — both servers start, no port conflicts.
2. Navigate to `http://localhost:3000` — dashboard loads with dark theme.
3. Upload a masked `.xls` file — transactions appear in the table.
4. Switch filters (year, category) — charts and KPIs update reactively.
5. Edit a category in the editor table — cascade modal appears, rule applied.
6. Run "Recategorize All" — spinner shown, data refreshes.
7. Add/delete a custom broad category — appears in dropdowns immediately.
