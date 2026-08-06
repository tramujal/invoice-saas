"""Phase 24 -- the Financial Intelligence module: an advanced financial
dashboard, deterministic revenue forecasting, and AI-generated business
recommendations, all built on top of the EXISTING analytics engine
(app.analytics, app.product_analytics, app.quote_analytics) rather than a
second one.

Package layout:
- queries.py        tenant-scoped SQL queries genuinely new to this phase
                     (AR aging buckets, customer concentration, payment
                     delay observations, ...) -- everything already
                     computed by app.analytics.service.AnalyticsService is
                     called from there directly, never reimplemented here.
- metrics.py         deterministic executive-overview/customers/products/
                     quotes-funnel assembly (Phase 24.1).
- cashflow.py        AR aging, payment-delay stats, the receivables
                     collections calendar -- receivables forecasting only,
                     never "profit" or "net cash flow" (this app tracks no
                     expenses anywhere).
- models.py           4 candidate deterministic forecast models
                     (Phase 24.2): seasonal_naive, rolling_average,
                     weighted_moving_average, linear_trend.
- backtesting.py       rolling-origin model evaluation/selection.
- confidence.py         sample-size + backtested-error -> ConfidenceLevel
                     and horizon-scaled confidence intervals.
- forecasting.py      horizon-aware (30d/90d/180d/365d), backtested
                     revenue/collections forecasting, monthly projection,
                     scenario analysis, and anomaly detection (Phase
                     24.2) -- deterministic, no AI. Also this package's
                     one place revenue_forecasting_enabled's SOFT plan
                     gate is checked.
- insight_builder.py   assembles the ONE structured, PII-minimal context
                     object the AI Financial Advisor is ever shown, from
                     metrics.py/forecasting.py's own already-computed
                     response shapes -- issues zero new queries (Phase
                     24.3).
- prompt_builder.py     the AI Financial Advisor's system prompt (explicit
                     anti-hallucination / no-tax-or-legal-advice /
                     prompt-injection-defense rules) and bounded context
                     rendering (Phase 24.3).
- schemas_ai.py          FinancialAnalysisPayload -- the AI's strictly-
                     validated structured output schema (Phase 24.3).
- cache.py               fingerprinting + FinancialInsightReport reuse
                     (Phase 24.3) -- the durable cache IS that table,
                     there is no separate in-memory layer here.
- recommendations.py    the ONLY module in this package that talks to an
                     AIProvider (Phase 24.3) -- sanitized deterministic
                     context in, strictly schema-validated structured
                     output out, modeled on app.insights.narration's own
                     tool-call pattern. Never calculates a raw total
                     independently, retries once on any failure, never
                     persists or exposes an invalid response.
- schemas.py             every Phase 24.1 deterministic-dashboard Pydantic
                     response model.
- service.py              FinancialIntelligenceService -- the one
                     orchestration facade every router endpoint calls;
                     no business calculation lives in a router.

Deterministic calculations (queries.py/metrics.py/cashflow.py/models.py/
backtesting.py/confidence.py/forecasting.py) are computed and returned
independently of the AI layer -- an AI provider outage never breaks any
deterministic figure, and a failed/pending AI report never blocks the
rest of the dashboard from loading. recommendations.py only ever
interprets numbers these modules already computed; it never invents or
independently recomputes a total from raw invoice data, and it never
mutates a financial record.
"""
