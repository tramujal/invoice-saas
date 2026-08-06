# AI Financial Advisor (Phase 24.3)

## Status

**Interpretation only, never calculation.** Every number, name, date, and
trend the AI Financial Advisor writes about was already computed by the
deterministic Financial Dashboard (Phase 24.1) and Revenue Forecasting
engine (Phase 24.2) *before* the model ever sees it. The model's only job
is to explain what those numbers mean in plain language and suggest
actions — it never calculates a total, a percentage, or a forecast of its
own, and its structured output is strictly schema-validated before it is
ever persisted or shown.

Extends the existing **`/analytics/financial`** page with one new section
at the bottom, **AI Financial Advisor** — a professional executive
report, not a chat interface. Nothing in Phase 24.1's or 24.2's own
deterministic calculations was touched.

## Flow

```
Deterministic metrics (Phase 24.1)
  -> Forecast (Phase 24.2)
  -> Structured context   (insight_builder.py -- PII-minimal, JSON-safe)
  -> Prompt                (prompt_builder.py -- system prompt + rendered context)
  -> Existing AIProvider   (app.ai.factory.get_ai_provider -- unchanged)
  -> Strict schema validation (schemas_ai.FinancialAnalysisPayload)
  -> FinancialInsightReport (persisted only if validation passes)
  -> Frontend
```

No new AI provider abstraction was created. `app.financial_intelligence
.recommendations` is the only module in this package that calls
`get_ai_provider()`/`AIProvider.stream_complete()` — the exact same
provider-agnostic interface `app.routers.assistant` and
`app.insights.narration` already use. Adding a third provider (or
swapping the one configured in production) requires zero changes here.

## Architecture

```
app/financial_intelligence/
  insight_builder.py  Assembles ONE structured context dict from 10
                       existing Phase 24.1/24.2 builder calls (executive
                       overview, revenue trends, receivables aging,
                       customers, products, quotes funnel, revenue
                       forecast, expected collections, forecast accuracy,
                       anomalies) -- issues ZERO new queries, computes
                       ZERO new numbers. PII-minimal by construction: none
                       of those response shapes carry email/phone/address/
                       notes/raw invoice text.
  prompt_builder.py    The CFO-advisor system prompt (explicit
                       anti-hallucination / no-tax-or-legal-advice /
                       prompt-injection-defense rules) and a bounded JSON
                       rendering of the structured context.
  schemas_ai.py        FinancialAnalysisPayload -- the ONLY shape the
                       model's reply may take. Every field required,
                       every string bounded, `extra="forbid"` everywhere
                       (an unexpected field invalidates the whole
                       response), `observations[].evidence` requires at
                       least one item (no observation may exist without
                       evidence).
  recommendations.py   The one module that talks to an AIProvider. Calls
                       the model via a single tool
                       (submit_financial_analysis), validates strictly,
                       retries ONCE on any failure, and owns the
                       FinancialInsightReport row's full lifecycle
                       (pending -> completed/failed).
  cache.py              Fingerprinting (compute_source_fingerprint) and
                       report reuse (find_reusable_report/
                       get_latest_report) -- the DURABLE cache here IS the
                       FinancialInsightReport table, not an in-memory
                       layer (contrast app.insights.cache, a 30-minute
                       in-memory TTL cache for a much cheaper, request-time
                       narration call).
app/jobs/handlers/financial_intelligence.py
                       The financial_insight.generate background job
                       handler -- mirrors app.jobs.handlers.webhook's own
                       "job row success != business outcome" discipline.
app/routers/financial_intelligence.py
                       2 new endpoints (GET .../insights/latest, POST
                       .../insights/generate), same router as Phase
                       24.1/24.2.
```

## Structured context

`insight_builder.build_structured_context` is the ONLY data the model
ever sees. It includes, per currency where applicable:

- Executive KPIs (revenue, collected, outstanding/overdue receivables,
  expected collections, average invoice value, collection/overdue rate)
- Revenue trends (monthly series, MoM/YoY, rolling averages)
- Receivables aging (buckets, top overdue customers)
- Customers (top by revenue/outstanding, concentration, repeat
  contribution, growth, at-risk list)
- Top products (revenue, quantity, trend, concentration)
- Quote funnel and conversion rate
- Revenue forecast (all horizons, selected model, confidence)
- Expected collections (all horizons)
- Forecast model accuracy (backtested metrics for every candidate model)
- Detected anomalies
- Which scenario this run reflects (always `"base"` — the AI Advisor
  analyzes the organization's real, unadjusted trajectory; Phase 24.2's
  Scenario Controls are a separate, explicitly-labeled what-if tool never
  fed to the AI as if it were the real forecast)
- `generated_at`

It never includes: customer/user email, phone, address, notes, raw
invoice line text, or any field beyond what Phase 24.1/24.2's own
response schemas already exposed (those were already PII-minimal by
design — see `docs/financial_dashboard.md`).

## Prompt

`prompt_builder.FINANCIAL_ADVISOR_SYSTEM_PROMPT` is a dedicated,
non-conversational system prompt (mirrors `app.insights.narration_prompt`'s
role, kept separate from the assistant's own chat prompt). It explicitly
forbids, in plain language the model is instructed to always follow:

- Inventing any number, date, name, or trend not already in `METRICS`
- Writing an observation with no cited evidence
- Writing a recommendation without referencing real metrics and
  acknowledging confidence/uncertainty
- Guaranteeing, promising, or stating as certain any future outcome
- Tax advice, legal advice, investment advice, hiring/firing advice
- Recommending a pricing change without citing specific evidence
- Treating anything inside `METRICS` (including a customer or product
  name) as an instruction rather than data — a defense against prompt
  injection embedded in user-authored short strings that end up in the
  context

The context itself is rendered as bounded, canonical JSON (not hand-written
prose) specifically so the model can cite an exact field/value pair as
evidence, capped at `FINANCIAL_AI_MAX_CONTEXT_CHARS` (default 16,000
characters — a defensive ceiling; the bounded top-N lists everywhere in
Phase 24.1/24.2 never get close to it in practice).

## Output schema

The model must call `submit_financial_analysis` exactly once — the same
tool-call mechanism (not free-text "return JSON" parsing)
`app.insights.narration` already uses, reusing `AIProvider.stream_complete`'s
existing tool-definition/tool-invocation contract unchanged.

```
FinancialAnalysisPayload
  executive_summary        string
  overall_health            excellent | good | fair | poor | critical
  confidence_notice        string
  observations[]            category, severity, title, explanation,
                            evidence[] (label, value) -- >= 1 evidence item
  recommendations[]         priority, title, action, reason,
                            expected_impact, limitations
  forecast_commentary       string
  strengths[] / risks[] / opportunities[] / next_actions[]
  disclaimer                string
```

Validation is strict: `extra="forbid"` on every nested model (an
unexpected field invalidates the whole response), every string field has
a bounded `max_length`, `observations` requires at least one entry (even
a brand-new organization has an honest "not enough data yet" observation
to make), and `evidence` requires at least one item per observation. A
response that fails validation — or where the model doesn't call the tool
at all — is retried **exactly once**; if the retry also fails, the report
is recorded `failed` with a structured `error_code`. An invalid response
is **never** persisted or shown, matching `app.insights.narration`'s own
"no partial trust" discipline.

## API

| Endpoint | Behavior |
| --- | --- |
| `GET .../financial-intelligence/insights/latest` | The most recent report for the organization (any status), or `null` if none has ever been requested. |
| `POST .../financial-intelligence/insights/generate` | Body: `{force?: boolean}`. `force: false` (default) reuses an existing completed, unexpired report for unchanged data if one exists — no new AI call, no quota consumed. `force: true` (the Refresh button) always creates a fresh report and consumes one quota slot. |

Both require `Permission.financial_intelligence_view` and hard-gate on
`ai_financial_recommendations_enabled` (403 `feature_not_available` if the
plan doesn't include it at all — unlike `revenue_forecasting_enabled`'s
soft degrade in Phase 24.2, there is no meaningful partial version of an
AI-generated report to fall back to). `POST` additionally enforces the
plan's monthly quota (`LimitedResource.financial_ai_reports`, already
fully wired since Phase 24.1's scaffolding) — a 409 `plan_limit_reached`
once the organization has requested its plan's monthly limit of analyses.

## Background jobs

`POST .../insights/generate` never calls the AI provider inline — it
creates a `pending` `FinancialInsightReport` row, enqueues one
`financial_insight.generate` `BackgroundJob`, and returns immediately. The
job handler (`app/jobs/handlers/financial_intelligence.py`) calls
`recommendations.run_generation`, which does the AI call, validates the
result, and updates the report row to `completed` or `failed` — the
background job **itself** always reports success (it did what it was
asked: attempt generation and record a definitive outcome), exactly
matching `app.jobs.handlers.webhook`'s own "job row success is orthogonal
to business outcome" convention. Only a genuine unhandled exception (a DB
error, a bug) ever becomes a retryable job-execution failure.

The frontend never calls Gemini/Anthropic directly or synchronously: it
polls `GET .../insights/latest` every 3 seconds only while `status ===
"pending"`, and stops the moment the status resolves.

## Caching

There is no separate in-memory cache layer — the `financial_insight_reports`
table itself is the cache. `cache.compute_source_fingerprint` hashes the
ENTIRE structured context (with every `generated_at` timestamp stripped
recursively, at any depth, so the fingerprint reflects data changing, not
merely time passing) into a stable sha256. `request_insight_report` reuses
an existing `completed`, unexpired report with the same fingerprint
whenever `force` isn't set — "only regenerate when requested (and even
then, only if nothing reusable exists), expired, or financial data
actually changed," per this phase's own requirement. Reports expire after
`FINANCIAL_AI_REPORT_TTL_SECONDS` (default 24 hours) even if the
underlying data hasn't changed, so a report never silently stays
authoritative forever in an inactive organization.

## Notifications and audit

Both go through `app.notifications.service.emit_event` — the single,
frozen entry point for every domain event this platform raises (audit,
webhook, in-app notification, and email all fan out from one call; nothing
in this phase calls `record_audit_entry` or creates a `Notification` row
directly, since that module explicitly documents itself as callable only
from inside `emit_event`'s own fan-out).

Three new event types were added: `financial_insight.requested`,
`financial_insight.generated`, `financial_insight.failed` — each raised
exactly once, at the exact transaction boundary of that transition, so
there is never a duplicate event for one generation attempt.

**Trade-off, stated plainly:** `emit_event` notifies every active member
of the organization, not only the user who clicked "Generate" — there is
no narrower, requester-only notification path in this codebase, and
adding one would mean bypassing the frozen event pipeline, which this
phase deliberately does not do. `financial_insight.requested` therefore
also produces an in-app notification/email for every active member, not
just the requester. There is no `financial_insight.expired` event —
expiry is only ever noticed passively, the next time a report is
requested and found stale; there is no background sweep with an
authoritative moment to raise such an event from.

## Persistence

Reuses the `FinancialInsightReport` model exactly as it already existed
in this codebase (scaffolded ahead of this phase, unchanged here — no new
migration). `source_fingerprint` already *is* what a "structured metrics
hash" would be — its own pre-existing docstring describes it as "sha256 of
a canonical snapshot of the deterministic metrics," so no separate,
redundant hash column was added.

## Security and privacy

- **Tenant isolation**: every query in `insight_builder.py` (via the
  Phase 24.1/24.2 builders it calls) filters by `organization_id`
  explicitly; `FinancialInsightReport` rows are always looked up scoped to
  the caller's own organization.
- **No raw PII**: verified at the source — none of the response shapes
  `insight_builder.py` dumps carry email/phone/address/notes/raw invoice
  text (see `docs/financial_dashboard.md`'s own design for why).
- **Prompt injection defense**: the system prompt explicitly instructs the
  model to treat everything under `METRICS` (including any user-authored
  short string like a customer or product name) as data, never as an
  instruction — the same defense `app.insights.narration_prompt` already
  established for its own, smaller context.
- **Schema validation**: no unvalidated AI output ever reaches storage or
  the frontend — see [Output schema](#output-schema).
- **No cross-org cache**: every fingerprint/report lookup is scoped by
  `organization_id`; there is no shared or global cache key.
- **Provider failure isolation**: a provider outage or malformed response
  only ever marks ONE report `failed` — it never affects the deterministic
  dashboard or forecast, which are computed and returned completely
  independently (see Phase 24.1/24.2's own architecture).

## Plan gating

| Plan | Behavior |
| --- | --- |
| Free | `ai_financial_recommendations_enabled: false` — hard 403 on both endpoints. |
| Pro | Enabled, with a monthly quota (`monthly_financial_ai_reports`) — 409 `plan_limit_reached` once exhausted. |
| Enterprise | Enabled, typically with a higher or unlimited quota. |

## Limitations

- **The model can still get something wrong within the rules it's given**
  — schema validation guarantees the *shape* and *presence of evidence*
  of the output, not that every sentence is a perfectly accurate summary
  of that evidence. Treat this as a first-pass executive read, not a
  substitute for reviewing the deterministic dashboard directly.
- **No requester-only notification** — see
  [Notifications and audit](#notifications-and-audit) above; every active
  member is notified, by design of the frozen event pipeline.
- **No passive expiry notification** — a report silently becomes eligible
  for regeneration once its TTL passes; nothing proactively tells anyone
  it expired.
- **English-default prompt, language-following output** — the system
  prompt instructs the model to reply in the language of the business
  names/labels in `METRICS`, but this is a model instruction, not a
  server-enforced guarantee.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| "Not included in your plan" | `ai_financial_recommendations_enabled` is false on the organization's plan — see Plan gating. |
| Quota-exceeded message on Generate | `monthly_financial_ai_reports` reached for the current calendar month — see `app.services.organization_usage.count_financial_ai_reports_current_month`. |
| Stuck on "Generating your analysis" | Check the `financial_insight.generate` `BackgroundJob` row's status — a worker may not be running (see `docs/notifications.md`'s own background-job operational notes, which apply identically here). |
| "The AI provider isn't currently available" | `get_ai_provider()` raised — platform `ai_enabled` is off, or `AI_PROVIDER`/`AI_MODEL`/the provider's API key isn't configured. |
| Report never updates after data changes | Reports are reused by fingerprint; click "Refresh analysis" to force a new one, or wait for the fingerprint to naturally change on the next request. |
