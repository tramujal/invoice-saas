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
                     quotes-funnel assembly.
- cashflow.py        AR aging, payment-delay stats, the receivables
                     collections calendar -- receivables forecasting only,
                     never "profit" or "net cash flow" (this app tracks no
                     expenses anywhere).
- forecasting.py      horizon-aware (30d/90d/6mo/12mo), backtested revenue
                     forecasting -- deterministic, no AI.
- backtesting.py       rolling-origin model evaluation/selection.
- anomalies.py          transparent, explainable deterministic anomaly
                     rules (% change, IQR, MAD) -- never opaque claims on
                     tiny samples.
- recommendations.py    the ONLY module in this package that talks to an
                     AIProvider -- sanitized deterministic context in,
                     strictly schema-validated structured output out,
                     modeled on app.insights.narration's own tool-call
                     pattern. Never calculates a raw total independently.
- schemas.py             every Pydantic request/response model.
- service.py              FinancialIntelligenceService -- the one
                     orchestration facade every router endpoint calls;
                     no business calculation lives in a router.

Deterministic calculations (queries.py/metrics.py/cashflow.py/
forecasting.py/backtesting.py/anomalies.py) are computed and returned
independently of the AI layer -- an AI provider outage never breaks any
deterministic figure. recommendations.py only ever interprets numbers
these modules already computed; it never invents or independently
recomputes a total from raw invoice data, and it never mutates a
financial record.
"""
