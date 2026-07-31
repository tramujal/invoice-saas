# Invoicing SaaS

**A production-grade, multi-tenant SaaS platform** for invoicing and
quoting: a public API and outbound webhooks for integrations, a durable
background-job queue, commercial plan enforcement, and a
platform-administration layer — all built on tenant isolation and a
permission system enforced across every surface, including the AI agent.

![Dashboard overview](docs/screenshots/dashboard-overview.png)

---

## Table of Contents

- [Overview](#overview)
- [Production Features](#production-features)
- [Features](#features)
- [Screenshots](#screenshots)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Environment Variables](#environment-variables)
- [Testing](#testing)
- [Deployment](#deployment)
- [Security](#security)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)
- [Acknowledgements](#acknowledgements)

---

## Overview

Most invoicing tutorials stop at CRUD: create a customer, create an
invoice, done. This project starts from a harder question — what does it
take to run a multi-tenant SaaS platform that other systems can safely
integrate with, that an operations team can administer, and that would
survive contact with production?

Every organization is isolated from every other at the structural level,
not by convention. Every teammate gets exactly the access their role
grants — enforced the same way whether they're clicking a button in the
UI, calling the public REST API with a scoped API key, or asking the AI
assistant to do it for them. Commercial plans gate what an organization
can do and how much of it, enforced at the point of the write, not just
displayed on a pricing page. A platform-operations layer, separate from
any tenant, lets operators suspend organizations, manage plans, and
inspect the job queue, with every action written to an audit log nobody
can edit after the fact.

Integrations are a first-class citizen, not an afterthought. Organizations
can generate scoped, hashed API keys for machine access, and subscribe
external systems to webhook events with HMAC-signed payloads. Delivery is
durable: every event is persisted transactionally before anything is sent
over the network, executed by a background worker process that survives
crashes and restarts, and retried on a backoff schedule if the receiving
end is down.

The result is a feature-complete invoicing and quoting product —
multi-currency, bilingual (English/Spanish), with bulk CSV/XLSX import,
WhatsApp sharing, scheduled payment reminders, and a business-insights
engine — wrapped in the operational scaffolding a SaaS company needs to
run it: audit logging, usage tracking, durable background jobs, and
platform administration.

## Production Features

A snapshot of what's shipped today versus what's still ahead — see
[Roadmap](#roadmap) for specifics.

| Capability | Status |
| --- | --- |
| Multi-tenancy & tenant isolation | Shipped |
| Role-based access control (organization + platform) | Shipped |
| Public REST API (`/api/v1/...`) | Shipped |
| Scoped, hashed API keys | Shipped |
| Outbound webhooks (HMAC-signed) | Shipped |
| Durable background job queue | Shipped |
| Background worker process | Shipped |
| Automatic webhook retries with backoff | Shipped |
| AI business assistant (multi-provider) | Shipped |
| Platform administration console | Shipped |
| Audit logging | Shipped |
| Usage tracking | Shipped |
| Plan & entitlement enforcement | Shipped |
| Optimistic concurrency (admin writes) | Shipped |
| Provider abstraction (AI + email) | Shipped |
| Localization (English/Spanish) | Shipped |
| Public quote portal | Shipped |
| CSV/XLSX bulk import | Shipped |
| Database migrations (Alembic) | Not yet — schema is additive-only on startup |
| CI pipeline | Not yet — tests run locally only |
| Billing / subscription integration | Not yet — plans are enforced, not yet billed |

## Features

- **Invoicing** — create, email, and PDF-export invoices; due dates with
  automatic overdue detection; payment status tracking; scheduled due-date
  reminders.
- **Quotes** — full lifecycle (draft → sent → accepted / rejected / expired
  → converted to invoice); a public, no-login-required accept/reject link
  for customers; scheduled expiring-quote reminders.
- **Customers & Products** — full CRUD plus bulk CSV/XLSX import with
  column mapping and row-level validation.
- **Team & Permissions** — invite teammates by email across four roles
  (owner / admin / member / viewer), backed by 22 fine-grained permissions
  enforced identically on every REST endpoint *and* every AI tool call.
- **Public API & API Keys** — a versioned REST API (`/api/v1/customers`,
  `/products`, `/quotes`, `/invoices`) for programmatic access, authenticated
  by scoped, hashed API keys — never a user's session token — each carrying
  its own permission grants and usage accounting.
- **Outbound Webhooks & Durable Background Jobs** — subscribe external
  systems to lifecycle events (customer/product/quote changes). Every
  event is persisted transactionally and delivered by a database-backed
  job queue running in a separate worker process, with HMAC-signed
  payloads, a full append-only delivery history, and automatic retries on
  a backoff schedule when a receiver is down or slow. Delivery survives a
  worker crash or restart — nothing queued is silently lost.
- **AI Business Assistant** — a chat assistant (Anthropic Claude or Google
  Gemini, swappable via one environment variable) that can draft invoices,
  quotes, and products. Every write action is proposed first and only
  executes after the user explicitly confirms it.
- **Platform Administration** — a separate operator console, invisible to
  tenants, for suspending/reactivating organizations, managing commercial
  plans and platform-wide settings, and inspecting the job queue. Every
  administrative action — a suspension, a plan change, a job retry — is
  logged immutably, with an actor and a reason attached.
- **Usage Tracking & Plan Enforcement** — every organization sits on a
  commercial plan (seats, monthly document volume, storage, feature
  flags); usage is tracked in real time and enforced against the plan's
  limits at the point a limited resource is created.
- **Communications** — transactional email (invoices, quotes, reminders,
  team invitations) via Resend; a one-click "Open in WhatsApp" action that
  prefills a message in the user's own WhatsApp — the app never sends
  anything on the user's behalf.
- **Localization** — a fully translated English/Spanish UI and email
  templates (1,300+ strings per language), with currency-aware number
  formatting.
- **Dashboard & Insights** — revenue and pipeline KPIs, top products/
  services, and a deterministic + AI-narrated insights engine that
  surfaces things like "revenue concentrated in one customer" before you'd
  notice it yourself.

![Invoices list](docs/screenshots/invoices-list.png)

## Screenshots

<table>
<tr>
<td width="50%">

**Quotes — full lifecycle**
![Quotes list](docs/screenshots/quotes-list.png)
Draft → Sent → Accepted / Rejected / Expired, at a glance.

</td>
<td width="50%">

**Public quote page — no login required**
![Public quote page](docs/screenshots/public-quote-page.png)
The link a customer actually receives to accept or reject.

</td>
</tr>
<tr>
<td width="50%">

**Team & permissions**
![Team permissions](docs/screenshots/team-permissions.png)
Role-based access, enforced the same way on the backend and in the AI agent.

</td>
<td width="50%">

**"Open in WhatsApp"**
![WhatsApp share](docs/screenshots/whatsapp-share.png)
Prefills a message in the user's own WhatsApp — never sent by the app itself.

</td>
</tr>
</table>

**Mobile**
![Dashboard on mobile](docs/screenshots/dashboard-mobile.png)

## Architecture

A few decisions in this codebase exist specifically *because* this is
meant to behave like a real product, not because a tutorial said to add
them:

**Multi-tenancy is structural, not incidental.** Every business-data table
foreign-keys to an `Organization`, and every route runs through
`require_org_member` / `require_permission` before touching the database.
Nothing trusts a client-supplied organization id beyond the caller's
verified membership — see `tests/tenants/` for the isolation tests that
prove it, including a dedicated test that the AI agent can't be tricked
into leaking across tenants.

**One permission list, three consumers.** `app/permissions.py` defines a
single `Permission` enum and a `ROLE_PERMISSIONS` map — the one source of
truth for "what can this role do inside its own organization." Backend
routes call `require_permission(...)`; the AI tool registry checks the
same permissions before a tool is even offered to the model; the frontend
never checks `role === "owner"` — it checks
`hasPermission(self, "invoice.send")` against a permissions array the
backend computed. A future custom role would light up the right buttons
and tools everywhere, with zero changes outside that one file.

**Platform administration is a separate permission system, never merged
with the one above.** `app/platform_permissions.py` defines its own
`PlatformPermission` enum and `PlatformRole` set, checked by its own
`require_platform_permission(...)` dependency. An organization owner has
zero platform-level access no matter how their organization is configured,
and a platform operator's access to tenant data is limited to exactly what
the platform-admin surfaces expose (usage, plan, audit history) — never a
backdoor into an organization's actual business records. Keeping the two
systems apart means a bug in one can't silently grant the other.

**AI actions are proposed, then confirmed.** Chat streaming and action
execution are deliberately separate code paths. When the assistant wants
to create an invoice or update a record, it *proposes* the action; nothing
touches the database until the user explicitly confirms it in the UI. The
propose and confirm paths carry their own, tighter rate limits than
ordinary chat.

![AI Assistant proposing an invoice, awaiting confirmation](docs/screenshots/ai-assistant-propose-confirm.png)
The assistant drafts the action and stops — nothing is written until "Confirm and create" is clicked.

**Providers are abstracted, not hardcoded.** Both the AI layer
(`app/ai/base.py`'s `AIProvider` interface, implemented by
`anthropic_provider.py` and `gemini_provider.py`) and the email layer
(`app/email/base.py`) sit behind a small interface. Switching from Claude
to Gemini, or plugging in a different email provider, is a configuration
change — the router, rate limiting, and frontend never know which
concrete provider is running underneath.

**Status is derived, not stored.** An invoice's `payment_status` is only
ever "pending" or "paid" at rest — whether it's actually *overdue* is
computed at read time from the current date, so "overdue" can never drift
out of sync with reality. Quotes follow the same pattern for expiry.

**Money is pinned at creation time.** An invoice or quote's currency (and
language) is snapshotted the moment it's created and never re-derived from
the organization's current settings — changing your organization's default
currency later can never silently rewrite a historical document.

**Outbound webhooks are event-driven, not polled.** Business services
never call a webhook endpoint directly. When something worth notifying
about happens — a customer is created, a quote is sent — the service
performing that mutation calls `record_webhook_event()` from inside its
own transaction. Nothing about invoice or quote creation logic knows
webhooks exist; the event system is additive and could be deleted without
touching the domain logic it observes.

**Webhook events are immutable; delivery history is append-only.** A
`WebhookEvent` row, once created, is never modified — it's the replayable
record of "this happened." Each delivery *attempt* against a
subscribed endpoint gets its own `WebhookDelivery` row rather than
overwriting a single status field, so retrying a failed delivery —
automatically or via a manual resend — never destroys the evidence of what
was tried before. An organization can look at an event from weeks ago and
see every attempt, every response code, every retry, in order.

**Nothing is dispatched until it's durable.** Both `record_webhook_event()`
and `enqueue_job()` (the job queue underneath it) are called from *inside*
an already-open business transaction — neither ever issues its own commit.
If the surrounding request rolls back, the event and the job row it
produced roll back with it. There is no code path where "the write failed,
but a webhook fired anyway."

**Background jobs are durable and worker-driven, not fire-and-forget.**
Webhook delivery — and any future asynchronous work registered the same
way — runs through a `BackgroundJob` table in the same database as the
rest of the app, claimed by a separate `python -m app.jobs.worker` process
via an atomic, lease-based claim, portable across SQLite and Postgres. A
crashed or killed worker's claimed-but-unfinished jobs are automatically
recovered once their lease expires — verified against an
intentionally-crashed worker process, not just asserted in a unit test.
Multiple worker processes can run concurrently against the same queue
with zero double-delivery: the claim is atomic at the database layer,
never coordinated in application code.

**The web process never performs webhook delivery itself.**
`deliver_webhook()` — the function that makes the actual outbound HTTP
call — is invoked from exactly one place: the job handler that runs
inside the worker process. A request handler can enqueue work; it can
never execute it. A slow or unreachable third-party receiver can never
make an API request hang, and a worker outage never blocks the product —
events simply queue up durably until a worker is available again.

**Webhook payloads are signed, not just delivered.** Every outbound
delivery carries an HMAC-SHA256 signature
(`X-Webhook-Signature: t=<timestamp>,v1=<signature>`) computed over the
timestamp and the exact request body, using a per-endpoint secret shown to
the organization exactly once, at creation or rotation, and never again.
Signing the timestamp alongside the body — not just the body — is what
lets a receiver reject a replayed-but-otherwise-valid request outside a
small tolerance window.

**Outbound requests are SSRF-hardened.** A webhook endpoint URL is
entirely organization-controlled, which makes it the textbook target for
a server-side-request-forgery attempt against internal infrastructure.
Every URL is validated — scheme, no embedded credentials, DNS resolution
rejecting loopback/private/link-local/reserved addresses — both at
creation time and again immediately before every delivery attempt, and the
same check re-runs at actual TCP-connect time to close the DNS-rebinding
gap between the two.

**API keys are hashed, never stored reversibly.** An organization's API
key secret is shown exactly once, at creation, and only a salted hash is
ever persisted — structurally identical to how user passwords are
handled, not a separate, weaker scheme for machine credentials.

**Usage and plan limits are enforced where the write happens.** Every
commercially-limited creation path — inviting a teammate past the seat
limit, creating an invoice past the monthly document limit — checks the
organization's live usage against its plan's limits synchronously, in the
same request, before the row is created, never as an async cleanup step
that could let the write through first.

**Optimistic concurrency where conflicting writes are plausible.** Rows a
platform operator might realistically edit concurrently (`Plan`,
`PlatformSettings`) carry a `version` column; an update is applied via a
single conditional `UPDATE ... WHERE id = ... AND version = expected_version`,
and a mismatched rowcount surfaces as an explicit conflict for the caller
to resolve — never a silent last-write-wins.

## Tech Stack

| Layer | Technology |
| --- | --- |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0, Pydantic v2 |
| Database | PostgreSQL in production, SQLite for zero-setup local dev |
| Background Jobs | Database-backed durable queue (`BackgroundJob` table), executed by a separate worker process — no message broker |
| Auth | JWT (PyJWT) + bcrypt password hashing; scoped, hashed API keys for machine-to-machine access |
| AI | Anthropic Claude or Google Gemini, behind a provider abstraction |
| Email | Resend, behind a provider abstraction (swappable / no-op for tests) |
| Documents | ReportLab (PDF generation), openpyxl (XLSX import) |
| Frontend | Next.js 14 (App Router), React 18, TypeScript, Tailwind CSS |
| Charts | Recharts |
| Testing | pytest (567 backend tests) · Vitest + Testing Library (185 frontend tests) |
| Infra | Docker Compose (dev, and prod via `docker-compose.prod.yml` + Caddy), Neon (Postgres), Render (API + worker), Vercel (frontend), GitHub Actions (scheduled jobs) |

## Project Structure

```
app/                      FastAPI backend
├── main.py               App instance, router registration, startup
├── models.py              SQLAlchemy models (25 tables)
├── schemas.py             Pydantic request/response schemas
├── permissions.py         Org-level role → permission map
├── platform_permissions.py  Platform-operator role → permission map
│                             (separate from app/permissions.py)
├── deps.py                Auth / permission FastAPI dependencies
├── rate_limit.py           Rate limiting primitives
├── webhook_signing.py      HMAC request signing for outbound webhooks
├── webhook_ssrf.py         SSRF protection for webhook endpoint URLs
├── api_keys.py             API key generation / hashing
├── job_type.py, job_status.py, job_config.py   Background-job primitives
├── routers/                One file per resource — invoices, quotes,
│                            customers, products, team, assistant,
│                            webhooks, api_key_management, platform_admin
│   └── api_v1/              Public REST API, authenticated by API key
├── services/                Business logic — invoices, quotes, products,
│                            team, webhook_events, webhook_deliveries,
│                            background_jobs, entitlements, plan_limits
├── jobs/                    Durable job registry, handlers, and the
│   ├── worker.py             standalone worker process entrypoint
│   ├── registry.py           job-type registry
│   └── handlers/             one handler module per job type
├── ai/                      Provider abstraction + agent tools
│   └── tools/                 Agent tools + permission-checked registry
├── email/                   Provider abstraction + templates
├── insights/                 Deterministic + AI-narrated insights engine
└── imports/                  CSV/XLSX bulk-import framework

frontend/                 Next.js frontend
├── app/                   App Router pages
│   ├── (dashboard)/        Authenticated tenant app (invoices, quotes,
│   │                       customers, products, team, assistant, settings)
│   └── (admin)/admin/      Platform administration console (organizations,
│                           users, plans, background jobs, audit log, settings)
├── components/             Organized by domain, plus a shared ui/ design system
└── lib/                    API client, permissions, i18n, formatting helpers

tests/                    pytest suite, organized by domain (auth, tenants,
                          permissions, quotes, invoices, imports, AI,
                          insights, webhooks, background jobs, platform_admin)
```

## Getting Started

### Quick start (Docker)

The fastest path — brings up Postgres, the backend, the background-job
worker, and the frontend together, with zero configuration:

```bash
docker compose up --build
```

Frontend at `http://localhost:3000`, API at `http://localhost:8000`
(`/docs` for interactive API docs). Data persists across restarts in a
named volume. To enable real email or the AI assistant locally, copy
[`.env.docker.example`](.env.docker.example) to `.env` and fill in the
keys you want, then rerun the command above.

### Manual setup

```bash
# Backend
pip install -r requirements.txt
cp .env.example .env          # then edit — at minimum set JWT_SECRET_KEY
python -m app.seed_demo       # optional: prints demo login credentials
uvicorn app.main:app --reload

# Frontend (in a separate terminal)
cd frontend
npm install
cp ../.env.example .env.local
npm run dev

# Background worker (optional, separate terminal) — only needed to
# deliver outbound webhooks. Without it, events and jobs still persist
# durably; they simply queue up undelivered until a worker runs.
python -m app.jobs.worker
```

Backend at `http://127.0.0.1:8000`, frontend at `http://localhost:3000`.
On first load you'll land on `/login`, where you can sign in or register
a new account — registering also creates your organization.

### Database

`DATABASE_URL` unset falls back to a local SQLite file with foreign-key
enforcement turned on, so local behavior matches Postgres. Set it to a
`postgresql://` (or legacy `postgres://`) URL to use Postgres instead —
the scheme is rewritten to the `psycopg` v3 driver automatically. Tables
are created on startup via `Base.metadata.create_all()`; there's no
migration tool yet (see [Roadmap](#roadmap)).

## Environment Variables

| Variable | Default | Notes |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./invoices.db` | See [Database](#database) above. Shared by the web and worker processes. |
| `JWT_SECRET_KEY` | insecure dev default (warns) | Generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. **Required** in production — the app refuses to start without it when `ENVIRONMENT=production`. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` (24h) | JWT access token lifetime. |
| `ENVIRONMENT` | `development` | Set to `production` when deploying. |
| `CORS_ALLOWED_ORIGINS` | local Next.js origins | Comma-separated list of frontend origins allowed to call the API. |
| `AI_PROVIDER` | `anthropic` | `anthropic` or `gemini`. Unknown values return a clean 503. |
| `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` | unset (assistant returns 503) | Only the key matching `AI_PROVIDER` is ever read. Optional — the rest of the app works without either. |
| `AI_MODEL` | dev-only fallback; **required** in production | Never silently assumed once `ENVIRONMENT=production` — see `app/ai/factory.py`. |
| `AI_MAX_OUTPUT_TOKENS`, `AI_REQUEST_TIMEOUT_SECONDS`, `AI_MAX_*` | conservative defaults | Cost/abuse controls for the assistant, provider-agnostic. See `.env.example`. |
| `RESEND_API_KEY`, `EMAIL_FROM` | unset | Required for outbound email (invoices, quotes, reminders, invitations). Without them, sending fails safely (503) rather than crashing anything else. |
| `FRONTEND_BASE_URL` | local dev origin | Used to build links in outbound emails and public quote share links. |
| `WORKER_*` (several) | conservative defaults | Poll interval, batch size, lease duration, and other background-worker tuning — every one optional, read only by the worker process. See `app/job_config.py`. |
| `NEXT_PUBLIC_API_URL` | `http://127.0.0.1:8000` | Frontend-side API base URL. |

## Testing

```bash
# Backend — 567 tests across auth, tenant isolation, permissions/rate
# limits, team/invitations, quotes, invoices/reminders, products/imports,
# API keys, the public API, outbound webhooks, the durable background job
# queue, platform administration, plans/entitlements, usage tracking, and
# the AI assistant + insights engine.
pytest

# Frontend — 185 tests across components and lib helpers.
cd frontend && npm test
```

Tenant isolation and AI-agent permission enforcement are each covered by
dedicated test suites (`tests/tenants/`) rather than assumed — including a
test that specifically tries to trick the AI agent into acting across
organizations. The background job queue's crash-recovery and concurrency
guarantees are tested the same way: an abandoned claim past its lease is
picked back up, and two workers racing for the same batch never
double-claim a row — not just the happy path.

## Deployment

> For the full production release-readiness reference (environment
> variable checklist, health endpoints, logging, backup strategy,
> security headers, CORS/rate-limiting verification, monitoring hooks,
> and a release checklist) see [`docs/deployment.md`](docs/deployment.md).
> The walkthrough below covers only the managed Render+Vercel+Neon path;
> `docs/deployment.md` also documents a self-hosted alternative using
> [`docker-compose.prod.yml`](docker-compose.prod.yml) (Postgres + backend
> + worker + frontend + Caddy for automatic HTTPS) for deploying to your
> own server instead.

This application runs as **two cooperating backend processes**, not one:
the **web API** (handles requests, enqueues work, never executes it) and
the **background worker** (claims and executes durable jobs — currently,
webhook delivery). Both read from the same database and the same job
queue table; neither can affect the other except through that shared
state. Running only the web process is a valid deployment — events and
jobs still persist durably — but nothing is *delivered* until a worker
claims the backlog.

Four pieces, in order: a Postgres database (Neon), the web API (Render),
the background worker (Render), then the frontend (Vercel). The API and
frontend have a circular dependency — the API needs the frontend's URL for
CORS, and the frontend needs the API's URL — so you configure one, deploy
the other, then close the loop.

1. **Database (Neon)** — create a project + database, copy the pooled
   connection string as `DATABASE_URL`. No schema migration step needed
   for a fresh database.
2. **Web API (Render)** — point Render's Blueprint feature at this repo
   ([`render.yaml`](render.yaml) has the build/start commands already
   filled in), or create a manual web service with
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Set
   `DATABASE_URL`, `JWT_SECRET_KEY`, `ENVIRONMENT=production`, and a
   placeholder `CORS_ALLOWED_ORIGINS` for now. AI/email variables are
   optional — leave them unset to ship without those features.
3. **Background Worker (Render)** — a second Render service
   (`type: worker`, `python -m app.jobs.worker`) sharing the same
   `DATABASE_URL` and `JWT_SECRET_KEY` as the web service above. The block
   is commented out in [`render.yaml`](render.yaml) because it requires
   Render's paid tier — the free tier covers exactly one web service, not
   a second always-on process. Until this is deployed, the app behaves
   correctly and nothing is lost; webhook events simply queue up
   undelivered. See [Architecture](#architecture) for why that split is
   safe.
4. **Frontend (Vercel)** — import the repo, set **Root Directory** to
   `frontend`, set `NEXT_PUBLIC_API_URL` to the Render URL, deploy.
5. **Close the loop** — back in Render, set `CORS_ALLOWED_ORIGINS` to the
   real Vercel URL and redeploy.

**Scheduled reminders** (invoice due-date and quote-expiry emails) run as
a standalone job, not inside the web service — triggered in production by
[`.github/workflows/send-invoice-reminders.yml`](.github/workflows/send-invoice-reminders.yml),
a daily GitHub Actions cron, unrelated to the webhook worker above.
Wiring it up requires three repo secrets: `DATABASE_URL`,
`RESEND_API_KEY`, `EMAIL_FROM`.

## Security

- Passwords hashed with bcrypt; sessions are short-lived signed JWTs.
- API key secrets are hashed at rest, exactly like passwords, and shown to
  the organization in full exactly once, at creation or rotation.
- Every resource is tenant-scoped at the query layer, not filtered after
  the fact — see [Architecture](#architecture).
- Permissions are enforced identically on REST routes, the public API (via
  API key scopes), and AI tool calls; the frontend's own gating is a UX
  convenience, never the source of truth.
- Outbound webhook deliveries are HMAC-SHA256 signed (timestamp + body)
  with a per-endpoint secret; endpoint URLs are validated against SSRF —
  rejecting loopback/private/link-local/reserved addresses — both at
  creation and again at the moment of every delivery attempt.
- Every webhook event and background job is enqueued transactionally,
  inside the same database transaction as the business write that
  produced it — a rolled-back request can never leave a dangling
  delivery.
- Platform-administration actions (suspending an organization, changing a
  plan, retrying a job) are written to an immutable, sanitized audit log
  with an actor and a reason — never editable after the fact.
- Rate limiting is per-user and per-IP, proxy-hop-aware (`TRUSTED_PROXY_HOPS`)
  so it can't be trivially bypassed by spoofing `X-Forwarded-For` behind a
  misconfigured reverse proxy.
- Bulk CSV/XLSX imports are row-validated before anything is written.
- AI actions are proposed, never executed, until the user explicitly
  confirms — see [Architecture](#architecture).
- Secrets are never committed — `.env*` is gitignored, and
  [`.env.example`](.env.example) documents every variable without values.
- Standard security response headers (`X-Content-Type-Options`,
  `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`,
  `Strict-Transport-Security`) are applied to every backend response
  (`app/security_headers.py`) and every frontend route
  (`frontend/next.config.mjs`).
- `GET /health/ready` verifies real database connectivity (distinct from
  `GET /health`'s plain liveness check) — see
  [`docs/deployment.md`](docs/deployment.md#health-endpoints).
- Backup strategy documented for both deployment paths — Neon's
  automatic continuous backup, or
  [`scripts/backup_postgres.sh`](scripts/backup_postgres.sh) for the
  self-hosted Docker path — see
  [`docs/deployment.md`](docs/deployment.md#backup-strategy).

## Roadmap

- Database migrations via Alembic (schema currently only ever *adds*
  tables/columns on startup).
- Automated CI running the full test suite on every push/PR.
- Billing / subscription integration — commercial plans exist and are
  enforced today, but aren't yet wired to a payment processor.
- Hard job-execution timeouts — a stuck job handler is only reclaimed
  after its lease expires, not interrupted mid-execution.
- Additional AI provider options.
- Richer public demo environment with realistic seed data.

## Contributing

Contributions are welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for
guidelines on running tests locally, coding conventions used throughout
this codebase (in particular: every new organization-scoped route needs
an explicit `require_permission` check, every new platform-admin route
needs `require_platform_permission`, and frontend UI gating should always
go through `hasPermission()`, never a role-name comparison), and how to
open a pull request.

## License

MIT License — see [`LICENSE`](LICENSE) for details.

## Acknowledgements

Built on [FastAPI](https://fastapi.tiangolo.com/),
[Next.js](https://nextjs.org/), [SQLAlchemy](https://www.sqlalchemy.org/),
[Anthropic Claude](https://www.anthropic.com/) and
[Google Gemini](https://ai.google.dev/), [Resend](https://resend.com/),
[Neon](https://neon.tech/), [Render](https://render.com/), and
[Vercel](https://vercel.com/).
