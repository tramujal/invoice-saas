# Revenue Forecasting (Phase 24.2)

## Status

**Deterministic only.** Every forecast on this page is a reproducible
transformation of real `Invoice`/`Quote` history through a small library of
classic time-series models — no AI, no external statistics package, no
hidden state. AI-generated recommendations are a separate, later phase
(24.3) and are not implemented here.

Extends the existing **`/analytics/financial`** page (Phase 24.1) with 8
new sections; nothing from that phase's behavior was changed except the
one spot the earlier phase's own code comments anticipated (see
[Expected collections](#2-expected-collections-forecastcollections)
below).

## Architecture

```
app/financial_intelligence/
  models.py       4 candidate forecast models, pure functions over a
                  chronological list[Decimal] -- seasonal_naive,
                  rolling_average, weighted_moving_average, linear_trend.
                  Each has its own MIN_HISTORY floor below which it
                  reports available=False rather than a number.
  backtesting.py  Rolling-origin (walk-forward) validation: repeatedly
                  trains on a growing prefix of real history and scores
                  the one-step-ahead prediction against the real next
                  month. Never evaluates a model on an observation it was
                  fitted on. select_best_model() picks the eligible
                  candidate with the lowest WAPE.
  confidence.py   Turns (sample_size, backtested WAPE) into a
                  ConfidenceLevel (insufficient_data/low/medium/high) and
                  a horizon-scaled confidence interval.
  forecasting.py  Orchestration + every Pydantic schema for this phase:
                  revenue forecast, expected collections, monthly
                  projection, scenario analysis, anomaly detection,
                  forecast accuracy/methods. The one place
                  revenue_forecasting_enabled's SOFT plan gate is checked
                  (see below).
app/routers/financial_intelligence.py
                  8 new endpoints (7 GET + 1 POST), same router as Phase
                  24.1, still a thin two-liner per endpoint -- no
                  calculation lives in the router.
```

`app/financial_intelligence/anomalies.py` and `recommendations.py` (named
in this package's own `__init__.py` as later phases' shape) still don't
exist as separate files — anomaly detection lives inside `forecasting.py`
in this phase (a small enough addition not to warrant its own module yet),
and `recommendations.py` (AI) remains entirely unbuilt.

## Soft plan gating

Unlike Phase 24.1's dashboard (`advanced_financial_analytics_enabled`,
a hard 403), `revenue_forecasting_enabled` **soft-degrades** — every
forecasting endpoint always returns `200` with a structurally valid body
and `plan_restricted: true` when the organization's plan doesn't include
it, never a 403. This is the exact behavior `app.billing.enforcement`'s
own pre-existing module docstring already promised for this capability,
matching the established pre-Phase-24 `/analytics/trends` forecast's own
soft-degrade convention. `Permission.financial_intelligence_view` is
still hard-required at every endpoint, same as Phase 24.1.

## Forecast models (`models.py`)

| Model | How it forecasts | Minimum history to ever be selected |
| --- | --- | --- |
| Seasonal naive | Repeats the value from the same calendar month one season (12 months) back, cycling for horizons beyond 12 months. The only model that can express a recurring yearly pattern (e.g. a December spike). | 14 months |
| Rolling average | The plain average of the last 3 months, repeated flat for every future month. | 3 months |
| Weighted moving average | Same 3-month window, linearly increasing weights (1, 2, 3) so the most recent month counts most. | 3 months |
| Linear trend | Ordinary least squares through the **entire** available history, extrapolated forward. The only model whose forecast shape actually changes over the horizon. | 3 months |

The "minimum history" above is deliberately one month more than what the
model needs to merely *compute* a value — a model is never selected
without at least one real backtested fold to validate it against (see
[Model selection process](#model-selection-process-backtestingpy)), so
the genuinely honest floor is one month beyond the bare arithmetic
minimum. Only models that clear this floor are ever evaluated for
selection — a currency with only 5 months on file never has
`seasonal_naive` "vote," since it's mathematically impossible to validate
that model against real history yet.

## Model selection process (`backtesting.py`)

Rolling-origin (walk-forward) validation: for each eligible model, and for
every origin point from its own `MIN_HISTORY` floor up to the last
available month, the model is trained on everything up to that origin and
scored against the **real** next month — never against an observation it
was fitted on. This produces one fold per validated origin.

Four metrics are computed per model:
- **MAE** — mean absolute error across all folds.
- **WAPE** — sum of absolute errors ÷ sum of absolute actuals, as a
  percentage. The primary selection metric: scale-independent, so it
  compares fairly across organizations of very different revenue sizes.
- **MAPE** — mean absolute percentage error, but **only** computed when
  every single fold's actual value is nonzero (this phase's own "MAPE
  only when the denominator is safe" requirement) — `null` otherwise,
  never a division-by-zero fudge.
- **Directional accuracy** — the percentage of folds where the
  prediction moved in the same direction (up/down) as the real value did,
  relative to the training data's last known point.

The model with the lowest WAPE (ties broken by MAE) is selected. If no
candidate has even one real backtest fold, the whole currency is reported
`insufficient_data` — no model is ever selected without having been
genuinely validated first.

## Confidence methodology (`confidence.py`)

Confidence is never a single opaque score. Two honest signals combine:

1. **Sample size** gates the *ceiling* — fewer than 3 months on file is
   always `insufficient_data`; fewer than 6 can never exceed `low`,
   regardless of how well the model happens to backtest.
2. **Backtested WAPE** (from the selected model) can only pull that
   ceiling *down*, never raise it — `high` additionally requires WAPE
   ≤ 15% with at least 12 months of history; `medium` requires WAPE
   ≤ 35%; anything worse (or with no backtest fold at all) stays `low`.

**Confidence intervals** widen with both a worse backtested WAPE and a
longer horizon: `spread = (WAPE/100, or a wide 50% default when
unvalidated) × √(months ahead)`, clamped between 5% and 100% of the point
forecast. A 12-month-ahead point forecast always carries a visibly wider
band than a 1-month-ahead one built from the identical history — this
phase never claims false precision. The lower bound never goes negative.

## API

All under `GET/POST /organizations/{organization_id}/financial-intelligence/forecast/...`,
requiring `Permission.financial_intelligence_view` (same as every Phase
24.1 endpoint):

| Endpoint | Returns |
| --- | --- |
| `GET .../forecast/revenue` | 30/90/180/365-day revenue forecasts per currency, selected model, confidence, sample size |
| `GET .../forecast/collections` | 30/90/180-day expected collections (known + projected components) per currency |
| `GET .../forecast/monthly-projection?months=` | Month-by-month expected/lower/upper/confidence table (1–12 months, default 6) |
| `GET .../forecast/summary` | Compact per-currency headline: model, confidence, 90-day revenue/collections, anomaly count |
| `GET .../forecast/accuracy` | Every candidate model's full backtest metrics, per currency, selected one flagged |
| `GET .../forecast/methods` | Static description of the 4 candidate models and their history floors |
| `GET .../forecast/anomalies` | Deterministic anomaly flags (see below) |
| `POST .../forecast/scenario` | Base/Optimistic/Conservative (or fully custom) what-if revenue + collections, never touching stored data |

### 1. Revenue forecast (`/forecast/revenue`)

For each currency with at least 2 months of real invoiced-revenue
history: the selected model, its confidence, and a forecast for 30, 90,
and 180 days, **plus 365 days only when at least 13 months of history
exist** — a currency without enough history simply doesn't get a 365-day
number, never a fabricated one. A currency with fewer than 2 months of
history gets `status: "insufficient_data"` and an empty `horizons` list.

### 2. Expected collections (`/forecast/collections`)

For each of the 30/90/180-day horizons: **known** (from currently-open
invoices, using each invoice's own expected collection date) plus
**projected** (forecasted future revenue × this organization's own
historical collection rate, for revenue not yet invoiced at all — these
two sets are disjoint by construction, so nothing is ever double-counted).

The known component is **customer-aware**: each open invoice uses its own
customer's historical payment-delay average when that customer has at
least 5 real observations, falling back to the organization-wide average
otherwise — this is the exact refinement Phase 24.1's own
`cashflow._expected_collection_date` docstring left as a note for "a
future phase" (this one), implemented as a sibling function in
`forecasting.py` rather than a modification to `cashflow.py` itself, so
Phase 24.1's own `/cashflow-calendar` endpoint stays byte-for-byte
unchanged.

### 3. Monthly projection (`/forecast/monthly-projection`)

The next 1–12 calendar months (strictly after the current one, since the
current month's actual-so-far figures already live in the Executive
Overview), one row per currency per month: expected value, lower/upper
bound, confidence, and sample size.

### 4. Forecast accuracy / methods (`/forecast/accuracy`, `/forecast/methods`)

Full transparency: every candidate model's backtest metrics (even the
ones that lost, or weren't even eligible), and a static description of
what each model does and its own history floor — so a user can see not
just which model won, but why.

### 5. Anomaly detection (`/forecast/anomalies`)

Five transparent, deterministic rules, each returning `rule`, `severity`
(low/medium/high), `sample_size`, and a factual `evidence` string:

| Rule | Fires when |
| --- | --- |
| `revenue_drop` | Latest month's invoiced revenue fell ≥20% (medium) or ≥40% (high) vs. the previous month |
| `collection_slowdown` | The last 90 days' average payment delay (≥5 observations) is more than 1.5× this organization's all-time average |
| `overdue_spike` | Current overdue receivables exceed both $100 and 1.5× what they were 30 days ago |
| `large_invoice` | Any currently-open invoice is more than 3× this month's average invoice value |
| `customer_concentration` | One customer accounts for ≥50% (medium) or ≥75% (high) of a currency's all-time revenue |

`evidence` is rendered directly by the frontend (a factual data readout,
the same established precedent as Phase 24.1's `AtRiskCustomer.evidence`)
— unlike every other free-text field in this phase's responses, which the
frontend always re-translates from structured fields instead.

### 6. Scenario analysis (`POST /forecast/scenario`)

Three named presets — **Base** (no adjustment), **Optimistic**
(+10% invoice growth, −5 days collection delay, +10% quote conversion),
**Conservative** (the exact mirror) — or a fully custom set of the same
3 assumptions. Every scenario re-runs the *identical* deterministic math
with these multipliers layered on top of the real historical data; **it
never mutates, re-queries with different filters, or in any way touches
stored business data** — a scenario is purely a recomputation.

## Currency behavior

Unchanged from Phase 24.1: money is never summed or compared across
currencies. Every forecast section groups by `currency_code`, and a
currency with too little history is reported `insufficient_data`
independently — it never drags another, better-established currency's
forecast down, and never gets a currency-mixed number.

## Examples

An organization with 14 months of steadily-growing USD invoiced revenue
(e.g. $1,000 → $1,650 in $50 monthly increments): `linear_trend` backtests
with WAPE ≈ 0% and 100% directional accuracy on this clean synthetic
data, gets selected, and reaches `high` confidence (≥12 months, WAPE
≤15%). Its 90-day forecast is the sum of the next 3 extrapolated monthly
points, with a narrow confidence band; its 365-day forecast is also
present (14 ≥ 13 months). A brand-new organization with 0 invoices gets
`results: []` for revenue forecast (nothing to forecast at all) and
`plan_restricted: false` (that flag reflects the plan capability, not
data availability) — never an error.

## Limitations

- **Pure extrapolation, no external signal.** None of the 4 models know
  about a signed contract, a planned price change, a one-off event, or
  general economic conditions — they only ever extrapolate this
  organization's own past invoice pattern.
- **Projected collections assumes a short conversion window.** The
  "projected" (not-yet-invoiced) component of expected collections
  assumes forecasted future revenue converts to cash within the same
  horizon window it's invoiced in — a reasonable simplification for
  30–180-day horizons where typical payment terms are short relative to
  the horizon, but not a modeled delay of its own.
- **Confidence intervals are a deterministic heuristic, not a proper
  statistical prediction interval.** The √(horizon) × WAPE scaling is
  simple and explainable by design (per this phase's own "no complex
  statistical packages" constraint), not a fitted distribution.
- **Model selection is evaluated at 1-month-ahead, applied to longer
  horizons.** A model's relative ranking is treated as horizon-agnostic —
  evaluating separately at every horizon would need far more history just
  to get a single backtest fold at 12 months ahead.
- **No AI, no forecasting beyond these 4 models, no recommendations.**
  Phase 24.3 (AI-generated recommendations) is not implemented — nothing
  in this phase talks to an AI provider.

## Performance

Every forecast section issues a small, bounded number of SQL queries
(reusing Phase 24.1's `queries.get_monthly_revenue_series`,
`get_open_invoices`, `get_receivables_snapshot`, `get_customer_revenue_all`
directly rather than re-querying). The one per-customer cost (customer-
aware collection delays) issues at most one query per **distinct**
customer with a currently-open invoice, cached and never repeated, bounded
by the same `OPEN_INVOICE_DETAIL_LIMIT` every other detail query in this
package already respects. History lookups are capped at 36 trailing
months (`FORECAST_HISTORY_MONTHS`) — generous enough for two full
seasonal cycles, still bounded.

## Frontend

`/analytics/financial` gains 8 new independently-loading sections after
Phase 24.1's 7: Forecast Confidence, Revenue Forecast (historical-vs-
forecast chart with a shaded confidence band), Expected Collections
(known/projected stacked bars per horizon), Scenario Controls (live-
updating on every preset/assumption change, debounced), Model
Explanation, Forecast Accuracy, Projection Table (with a client-side CSV
export — forecast/lower/upper/currency/confidence/generated_at/
disclaimer, no new backend endpoint needed), and Anomaly Flags. Every
section renders its own `plan_restricted` state independently (distinct
from Phase 24.1's single hard-gated `capabilityDenied`), and its own
loading/insufficient-data/empty state — never a fabricated chart or
number while data is missing.
