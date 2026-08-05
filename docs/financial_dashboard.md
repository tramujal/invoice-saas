# Financial Dashboard (Phase 24.1)

## Status

**Deterministic only.** Every figure on this dashboard is computed directly
from real `Invoice`/`Quote` rows already in the database — no AI, no
estimation, no forecasting. Revenue forecasting (a horizon-based,
backtested projection) and AI-generated recommendations are separate,
later phases (24.2/24.3) and are not implemented here — the plan-capability
flags for them (`revenue_forecasting_enabled`,
`ai_financial_recommendations_enabled`) already exist and are echoed in
this API's `capabilities` block, but nothing behind them exists yet.

Route: **`/analytics/financial`** — a dedicated page, not folded into the
existing `/dashboard` (which gets exactly one shortcut card into this page)
or the existing `/analytics` page (which keeps its own KPI/trend/forecast
content unchanged).

## Architecture

```
app/financial_intelligence/
  queries.py    bounded, org-scoped SQL new to this module (AR aging's
                base row set, customer/product revenue, the monthly
                invoiced/collected series, the historical receivables
                snapshot, ...) -- everything app.analytics.service
                .AnalyticsService (or app.product_analytics /
                app.quote_analytics) already computes is called from
                there directly, never reimplemented here.
  cashflow.py   AR aging buckets, payment-delay statistics, the
                collections calendar. Receivables only -- never "profit"
                or "net cash flow" (this app tracks no expenses).
  metrics.py    assembles queries.py/cashflow.py/AnalyticsService/
                product_analytics/quote_analytics into the 6 response
                shapes below.
  schemas.py    every Pydantic response model.
  service.py    the one thin orchestration facade every router endpoint
                calls -- a capability check plus delegation, no
                calculation of its own.
app/routers/financial_intelligence.py
                7 read-only, independently-loadable REST endpoints.
```

`app/financial_intelligence/forecasting.py`, `backtesting.py`,
`anomalies.py`, and `recommendations.py` (named in this package's own
`__init__.py` as the shape later phases will take) do not exist yet — this
phase deliberately stops at the deterministic layer.

## API

All endpoints: `GET /organizations/{organization_id}/financial-intelligence/...`,
requiring `Permission.financial_intelligence_view` (granted to every
active role, including viewer — read-only, same posture as
`dashboard_view`) and the `advanced_financial_analytics` plan capability
(a hard 403 `feature_not_available` if the organization's plan doesn't
include it — see `app.billing.enforcement.require_advanced_financial_analytics`).

| Endpoint | Returns |
| --- | --- |
| `GET .../overview` | Executive KPIs |
| `GET .../revenue-trends?months=` | Monthly revenue/collections/invoice-count series, rolling averages, MoM/YoY |
| `GET .../receivables-aging` | AR aging buckets + top overdue customers |
| `GET .../customers?limit=` | Top customers, concentration, repeat contribution, growth, at-risk |
| `GET .../products?limit=` | Top products, trend, concentration |
| `GET .../quotes` | Quote funnel counts, conversion rate, time-to-acceptance |
| `GET .../cashflow-calendar?horizon_days=&granularity=` | Expected-collections calendar |

Seven separate endpoints, not one aggregate response, specifically so the
frontend can load (and independently fail/retry) each section on its own
— a slow customers query never blocks the KPI cards from rendering.

## Metric definitions

### Executive KPIs (`/overview`)

Every KPI is a `MetricValue`: `value`, `currency_code`, `data_completeness`
(`complete`/`partial`/`insufficient`), a stable `formula_key`, and — for 6
of the 8 — a genuine previous-period comparison (`previous_value`,
`percent_change`, `trend_direction`: `up`/`down`/`flat`/`unknown`, using
the exact same `app.analytics.comparison.compare_periods` /
`app.analytics.trend_direction` machinery the rest of the app's trend
indicators already use).

| KPI | Formula | Previous-period comparison |
| --- | --- | --- |
| Revenue this month | `SUM(Invoice.total)` for invoices **created** this calendar month | vs. the same figure for the previous month |
| Collected this month | `SUM(Invoice.total)` for invoices **paid** (`paid_at`) this calendar month | vs. the same figure for the previous month |
| Outstanding receivables | `SUM(Invoice.total)` for every currently-unpaid invoice | vs. a conservative reconstruction of what was outstanding as of the end of the previous month (see [Limitations](#limitations)) |
| Overdue receivables | Outstanding, further filtered to `due_date < today` | same reconstruction as above |
| Expected collections (next 30 days) | Sum of the [cash calendar](#cash-calendar-cashflow-calendar)'s known amounts inside the next 30 days | **None** — a forward-looking projection has no "previous" instance of itself |
| Average invoice value | Revenue this month ÷ invoice count this month | vs. the previous month |
| Collection rate | Collected this month ÷ Invoiced this month, as a percentage | vs. the previous month |
| Quote conversion rate | All-time sent quotes that ended accepted or converted, as a percentage | **None** — shown as an all-time rate; a typical organization's monthly quote volume is too small for a month-over-month comparison to be meaningful rather than noise |

### Revenue trends (`/revenue-trends`)

Monthly `invoiced` / `collected` / `invoice_count` series per currency
(12 months by default, `months` query param 2–36), plus:

- **Rolling 3/6-month average** — average of `invoiced` over the most
  recent 3/6 displayed months.
- **Month-over-month** — latest displayed month vs. the one before it.
- **Year-over-year** — latest displayed month vs. the same month one year
  earlier, **only shown when that earlier month actually has invoiced
  revenue on file** (`growth_percent` returns `null` on a zero/absent
  baseline — the API never fabricates a 0%/∞% change from missing
  history).

### Receivables aging (`/receivables-aging`)

Five buckets per currency: `not_yet_due`, `overdue_1_30`, `overdue_31_60`,
`overdue_61_90`, `overdue_90_plus`, classified by `today − due_date`, each
with amount, invoice count, and percentage of that currency's total open
receivables. Unpaid invoices with **no due date on file** are counted
separately in `invoices_missing_due_date` — never silently placed in
"not yet due" or dropped. Also returns the top 10 customers by overdue
total.

### Customers (`/customers`)

Top-5-by-currency lists (revenue, outstanding), the top 10 most-overdue
customers, revenue concentration (top-1 and top-3 customers' share of
that currency's total revenue), repeat-customer contribution (customers
with 2+ invoices, and their share of revenue), customer growth this
month, and a transparent **at-risk list** — every entry names exactly
which deterministic rule fired:

- `repeated_overdue_invoices` — 3 or more currently-unpaid invoices at once.
- `overdue_far_beyond_average_delay` — the oldest overdue invoice is more
  than 2× this organization's own historical average payment delay.

Never an opaque "at risk" flag with no stated reason.

### Products (`/products`)

Top 10 products by revenue per currency, with quantity sold, average
sale value, and each currency's top-product revenue share. A 6-month
`increasing`/`decreasing`/`flat`/`insufficient_data` trend per product
(comparing the first vs. second half of the 6-month window; a difference
under 10% is `flat`; fewer than 3 non-zero observed months is
`insufficient_data`, never guessed at).

### Quotes funnel (`/quotes`)

Counts at every stage (created, sent, accepted, rejected, expired,
converted), overall conversion rate, quoted-vs-converted value per
currency, and average time-to-acceptance — an **approximation**: `Quote`
has no dedicated acceptance timestamp, so this uses `updated_at −
issue_date` for accepted quotes (documented in the metric's own `note`,
also shown in the UI).

### Cash calendar (`/cashflow-calendar`)

Every currently-open invoice's *expected* collection date — its own
`due_date` if not yet overdue, `due_date` + this organization's average
payment delay if it's already overdue and that delay is known, or today
if there's no due date or delay history at all — bucketed into
day/week/month periods within a configurable horizon (default 30 days).
Always carries the disclaimer: **this is a receivables forecast, not a
profit-and-loss or net cash-flow statement** — this application tracks
no expenses anywhere.

## Currency behavior

Money is **never** summed or compared across currencies. Every section
that involves money returns results grouped by `currency_code`; the
frontend renders one full KPI grid / chart set / table per currency
present in the organization's data. If only one currency exists, the
dashboard renders as a single, ungrouped view (no redundant currency
label); with two or more, each currency gets its own labeled block.
Currency-agnostic metrics (quote conversion rate, quote counts, customer
growth count) are counts/ratios, not money, and are shown once regardless
of how many currencies the organization uses.

## Invoice eligibility

- "Revenue"/"invoiced" always means `Invoice.total` at creation time,
  regardless of payment status — the same convention every other revenue
  figure in this app already uses (see `app.product_analytics`'s own note
  on this).
- "Collected" is based on `Invoice.paid_at`, a column this phase adds
  (`app.services.invoices.update_invoice_payment_status_record` sets it
  exactly once, the moment `payment_status` transitions to `paid`, and
  clears it if a mistaken "paid" is corrected away). **An invoice marked
  paid before this column existed has `paid_at = NULL` permanently** — it
  contributes to "outstanding"/"revenue" figures normally, but can never
  contribute to a "collected"/payment-delay figure, since this app
  genuinely has no record of when it was paid. This is an honest gap, not
  a guess.
- Archived/deleted records are excluded the same way every other
  analytics query in this app already excludes them (no separate handling
  needed here).

## Limitations

- **Historical receivables reconstruction is an approximation.**
  "Outstanding"/"overdue receivables" have no dedicated history table —
  there's no record of what the *actual* balance was on a past date. The
  previous-period comparison for these two KPIs is reconstructed
  conservatively: an invoice counts as outstanding-as-of a past date if it
  existed by then and either isn't currently paid, or its real `paid_at`
  is after that date. A currently-paid invoice with **no** `paid_at` on
  file (paid before that column existed) is always treated as *already*
  paid by any past date — the safe assumption that can only ever
  under-count historical outstanding, never over-count it. See
  `queries.get_receivables_snapshot`'s own docstring.
- **No AI tool exists to create customers/products** — unrelated to this
  phase directly, but relevant context: the pre-existing AI Business
  Assistant (reused by the separate WhatsApp phase) only has tools for
  invoices/quotes, not customer/product creation. This dashboard doesn't
  depend on that at all (it's pure read-only reporting), noted here only
  because it's the same underlying data model.
- **Quote acceptance time is approximate** — no dedicated
  `accepted_at` column exists; `updated_at` is used instead (documented in
  the metric's own note).
- **No expenses are tracked anywhere in this application.** Every
  "cash"-flavored figure here is a **receivables** forecast (money owed to
  you), never profit, net cash flow, or a P&L statement.
- **Revenue forecasting and AI recommendations are not implemented.** The
  plan-capability flags and API fields for them already exist (so a
  future phase doesn't need a schema migration to add them), but no
  forecasting or AI logic exists behind them yet — `revenue_forecasting_enabled`
  and `ai_financial_recommendations_enabled` are purely informational in
  this phase's responses.

## Performance

- Every section issues a small, bounded number of SQL queries (typically
  1–3), aggregating with `GROUP BY`/`func.sum`/`func.count` in the
  database — never loading every invoice into memory and summing in
  Python. The one genuinely bounded exception is AR aging's base row set
  (`queries.get_open_invoices`, capped at 2000 rows, matching
  `app/insights/queries.py`'s own existing defensive ceiling for the same
  class of query) — necessary because each open invoice needs its own
  due-date classification, not an aggregate.
- Monthly series (revenue trends, product trends) are bucketed in Python
  from **one** query spanning the whole requested date range, never one
  query per month — the same pattern `app.product_analytics
  .get_product_monthly_revenue` already established.
- No N+1 queries: customer/product names are joined in the same query as
  their aggregates, never fetched per-row afterward.
