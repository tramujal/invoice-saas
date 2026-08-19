# Production Readiness (Phase 26)

Audit date: this document reflects the repository as audited in Phase 26.
It is a **technical** readiness assessment, not a legal, compliance, or
security-certification claim.

**Verdict: CONDITIONAL GO.** No P0 blockers. The application is
technically deployable; what remains is external configuration and one
explicit cost decision (the background worker), both listed below.

---

## Architecture

```
                          ┌──────────────────────┐
   browser ──────────────▶│  Next.js frontend    │  (static + SSR, node server.js)
                          │  NEXT_PUBLIC_API_URL │──────┐  baked in at BUILD time
                          └──────────────────────┘      │
                                                        ▼
   Google ◀── OAuth redirect ──┐         ┌───────────────────────────────┐
   Stripe ──── webhook ───────▶│         │   FastAPI backend (uvicorn)   │
   Resend ◀─── email ──────────┤◀───────▶│   /health  /health/ready      │
   Anthropic|Gemini ◀── AI ────┤         │   init_db() on lifespan start │
   customer endpoints ◀ webhook┘         └───────────────┬───────────────┘
                                                         │ SQLAlchemy (psycopg3)
                                    ┌────────────────────┴────────────────────┐
                                    │            PostgreSQL                   │
                                    │  37 tables · 100 idx · 70 FK · 22 uniq  │
                                    └────────────────────┬────────────────────┘
                                                         │ background_jobs table
                          ┌──────────────────────────────┴────────────┐
                          │  Worker: python -m app.jobs.worker        │
                          │  webhook.deliver / webhook.retry /        │
                          │  notification.email /                     │
                          │  financial_insight.generate /             │
                          │  whatsapp.send_document                   │
                          └───────────────────────────────────────────┘

   OPTIONAL, private network only:
                          ┌───────────────────────────────────────────┐
                          │  WhatsApp bridge (Node + Chromium)        │
                          │  HMAC-signed both directions · /health    │
                          │  persistent volume: WHATSAPP_SESSION_PATH │
                          └───────────────────────────────────────────┘

   Scheduled (no in-app scheduler): GitHub Actions cron ──▶
       python -m app.jobs.send_due_invoice_reminders
```

**There is no object/file storage.** PDFs are generated on demand in
memory (`app/invoice_pdf.py`, `app/quote_pdf.py`) and streamed; nothing
is persisted to disk. The only persistent volume any service needs is the
WhatsApp bridge's session directory.

**There is no in-app scheduler.** Recurring work is a standalone CLI
(`app/jobs/send_due_invoice_reminders.py`) triggered externally.

---

## Deployment topology

Two supported paths. Pick one; they are alternatives, not layers.

### Path A — managed (Vercel + Render + Neon)

| Service | Build | Start | Health | Network | Disk |
|---|---|---|---|---|---|
| Frontend (Vercel) | `npm run build` in `frontend/` | Vercel-managed | `/` | public | none |
| Backend (Render web) | `pip install -r requirements.txt` | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --forwarded-allow-ips=` | `/health/ready` | public | none |
| Worker (Render background worker, **paid**) | `pip install -r requirements.txt` | `python -m app.jobs.worker` | n/a (no HTTP) | private | none |
| Postgres (Neon) | n/a | n/a | n/a | private | managed |

`render.yaml` is a working Blueprint for the backend. The worker block in
it is **commented out on purpose** — see the decision below.

### Path B — self-hosted (`docker-compose.prod.yml`)

`db` + `backend` + `worker` + `frontend` + `caddy` (automatic HTTPS).
Only Caddy binds host ports (80/443); Postgres and both app services are
reachable only on the internal Compose network. Verified: `docker compose
-f docker-compose.prod.yml config` refuses to start with any required
secret unset.

The WhatsApp bridge is **not** in the production compose file (it is in
`docker-compose.yml` behind a `whatsapp` profile, off by default). Adding
it to production is an explicit opt-in — it needs a persistent volume and
must stay on the private network.

---

## THE ONE DECISION TO MAKE BEFORE DEPLOYING

**Do you run a background worker?** It is a second always-on process
(a paid service on Render; already included in `docker-compose.prod.yml`).

Without a worker, these silently do nothing (everything else is fine):

| Job type | User-visible effect if no worker runs |
|---|---|
| `webhook.deliver` / `webhook.retry` | Webhook events are durably recorded but **never delivered**. |
| `notification.email` | In-app notifications appear; their **emails never send**. |
| `financial_insight.generate` | "Generate analysis" sticks on **pending forever**; the UI polls a status that never changes. |
| `whatsapp.send_document` | Requested PDFs are never delivered over WhatsApp. |

Invoicing, PDFs, quotes, customers, dashboard, analytics, forecasting,
auth, and billing all work normally with no worker. **If you deploy
without one, treat those four features as OFF, not broken** — and
consider hiding the AI Advisor's Generate button, since its pending state
is indefinite.

### Deploying the worker on Render

Service type **Background Worker**, same repo/branch as `invoicing-api`,
root directory left blank (`requirements.txt` and `app/` are both at the
repo root).

| | |
|---|---|
| Build command | `pip install -r requirements.txt` |
| Start command | `python -m app.jobs.worker` |
| Public port / health check | none — it opens no socket |
| Persistent disk | none — no local state; PDFs are re-rendered in memory |
| Instances | more than one is safe on Postgres (`SELECT … FOR UPDATE SKIP LOCKED` + a conditional-UPDATE rowcount check in `claim_jobs`) |

It needs the **same provider configuration as the web service**, not a
subset — it runs the handlers itself. The full list lives in the commented
block in `render.yaml`; copy each value from the API service rather than
regenerating it.

**The trap worth knowing about:** `AI_PROVIDER` defaults to `anthropic`
when unset (`app/ai/factory.py`). A worker that omits it while the API
sets `gemini` will look for `ANTHROPIC_API_KEY`, find nothing, and record
every Financial Advisor report as `failed` — while the API's own AI
surfaces keep working, so the misconfiguration looks like "the Advisor is
broken" rather than "the worker is misconfigured". Set `AI_PROVIDER`,
`AI_MODEL` and the matching key **explicitly on both services**.

There is no `.env` fallback: the app never calls `load_dotenv` anywhere,
so an unset Render variable is simply unset.

### Worker troubleshooting

| Symptom | Cause |
|---|---|
| Worker runs, logs `worker: started`, never claims anything | `DATABASE_URL` unset. It defaults to `sqlite:///./invoices.db` (`app/database.py`), so the worker silently polls an empty local file instead of Neon. |
| Worker crash-loops before `worker: started` | `JWT_SECRET_KEY` unset with `ENVIRONMENT=production`. `app.security` raises at import time; the worker imports it transitively via `app.ai.factory`, even though it never issues a token. |
| Every `notification.email` → `permanently_failed`, `error_code=email_not_configured` | `RESEND_API_KEY` / `EMAIL_FROM` missing on the worker. Not retryable by design — a config condition no backoff can fix. |
| Report `failed`, `error_code=ai_unavailable` | Provider key missing, or `AI_PROVIDER` disagrees with the key that is set (see the trap above). |
| Report `failed`, `error_code=invalid_response` | The provider answered, but the model didn't emit a valid `submit_financial_analysis` tool call. Validate the specific `AI_MODEL` honors function calling before trusting it in production. |
| Every `whatsapp.send_document` → `permanently_failed`, `error_code=whatsapp_not_configured` | Expected when WhatsApp is off; the null provider is the default. |
| `webhook.deliver` job `succeeded` but nothing arrived | Correct and by design — job success means "the row executed", never "the HTTP call was accepted". The business outcome is on the `WebhookDelivery` row. |
| Worker exits immediately, logs `WORKER_ENABLED=false` | `WORKER_ENABLED` is set to a falsy value. |

---

## Environment variables

Never commit real values. `sync: false` / blank in every manifest.

### Required in production

| Variable | Notes |
|---|---|
| `DATABASE_URL` | Postgres. `postgres://` and `postgresql://` are auto-rewritten to psycopg3. |
| `JWT_SECRET_KEY` | **Hard startup failure** if unset when `ENVIRONMENT=production`. Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. |
| `ENVIRONMENT=production` | Activates the JWT guard, the `AI_MODEL` guard, and closes `/docs` by default. |
| `CORS_ALLOWED_ORIGINS` | Comma-separated frontend origins. Warns (does not fail) if unset — the symptom is every browser call failing CORS. |
| `TRUSTED_PROXY_HOPS` | `1` behind Render or the Caddy stack; `0` with no proxy. Wrong value makes rate limiting bypassable. |
| `FRONTEND_BASE_URL` | Base for **every emailed link** and the Google OAuth landing redirect. Silently defaults to `http://localhost:3000`. |
| `NEXT_PUBLIC_API_URL` | Frontend, **build-time**. Rebuild the frontend to change it. Public by design; contains no secret. |

### Optional — feature stays off, app unaffected

| Variable(s) | Feature | Behavior when unset |
|---|---|---|
| `RESEND_API_KEY`, `EMAIL_FROM` | Outbound email | Sends fail silently server-side by design; app fully functional. |
| `BILLING_PROVIDER`, `STRIPE_API_KEY`, `STRIPE_WEBHOOK_SECRET` | Stripe | `NullBillingProvider`: plan limits **still fully enforced**, nothing charged, checkout/portal 503. |
| `GOOGLE_OAUTH_ENABLED`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` | Google Sign-In | Button never renders; password login unaffected. |
| `AI_PROVIDER`, `AI_MODEL`, `ANTHROPIC_API_KEY` \| `GEMINI_API_KEY` | AI assistant/advisor | AI routes 503; dashboard, invoicing, forecasting all unaffected. |
| `WHATSAPP_*` | WhatsApp | Disabled entirely. |
| `API_DOCS_ENABLED` | `/docs`, `/redoc`, `/openapi.json` | Closed in production by default; set `true` to publish. |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_RECYCLE_SECONDS` | Postgres pool | Defaults 5/5/300s, tuned for Neon. **Per process** — multiply by uvicorn workers + the worker container. |
| `LOG_LEVEL`, `WORKER_*`, `AI_MAX_*`, `INSIGHTS_*`, `FINANCIAL_AI_*`, `IMPORT_*` | tuning | Code defaults are production-sane. |

Secrets: `JWT_SECRET_KEY`, `STRIPE_API_KEY`, `STRIPE_WEBHOOK_SECRET`,
`GOOGLE_CLIENT_SECRET`, `RESEND_API_KEY`, `ANTHROPIC_API_KEY`,
`GEMINI_API_KEY`, `WHATSAPP_BRIDGE_SECRET`, `POSTGRES_PASSWORD`,
`DATABASE_URL`. None of these is ever exposed to the frontend — the only
`NEXT_PUBLIC_*` variable in the entire repository is `NEXT_PUBLIC_API_URL`.

---

## BEFORE DEPLOY

- [ ] Provision Postgres; copy its connection string into `DATABASE_URL`.
- [ ] Generate a fresh `JWT_SECRET_KEY`. Never reuse a dev value.
- [ ] Set `ENVIRONMENT=production` (verify the app refuses to boot without a real JWT secret — that check is your proof it took effect).
- [ ] Set `CORS_ALLOWED_ORIGINS` to the real frontend origin(s).
- [ ] Set `FRONTEND_BASE_URL` to the real frontend origin.
- [ ] Set `TRUSTED_PROXY_HOPS` to match the real proxy topology.
- [ ] Set `NEXT_PUBLIC_API_URL` in the frontend build to the real API origin.
- [ ] Decide the worker question above; provision it or accept the four features being off.
- [ ] **Email:** verify your sending domain with Resend (SPF + DKIM DNS records). Until that is done, delivery is unreliable regardless of app config. Not configured by this repo.
- [ ] **Stripe (if enabled):** use **live** keys, and register the webhook endpoint `https://<API_DOMAIN>/billing/webhooks/stripe`. Set `STRIPE_PRICE_ID__<PLAN>__<MONTHLY|YEARLY>` for each sellable plan.
- [ ] **Google (if enabled):** in Google Cloud Console create an OAuth 2.0 Web client; add the **exact** redirect URI `https://<API_DOMAIN>/auth/google/callback`; add the frontend origin to authorized JavaScript origins; publish the consent screen. Set `GOOGLE_OAUTH_ENABLED=true`.
- [ ] Confirm backups: on Neon/managed Postgres this is provider-side PITR — **verify the retention window** rather than assuming it.
- [ ] Run the full test suites locally (see below) on the exact commit being deployed.

## DEPLOY

1. Deploy the backend first. Its FastAPI lifespan hook runs `init_db()`, which is idempotent and applies the full migration chain — **there is no separate migration step, and running it twice is safe** (verified 3× consecutively against a clean Postgres).
2. Confirm `GET /health` → 200 and `GET /health/ready` → 200. Readiness performs a real `SELECT 1`; a 503 here means the database is unreachable and no traffic should be routed.
3. Deploy the worker (if provisioned). It requires the same `DATABASE_URL` and `JWT_SECRET_KEY`, **plus** the email and AI provider variables — it executes those jobs itself.
4. Deploy the frontend with `NEXT_PUBLIC_API_URL` baked in.
5. Bootstrap the first platform admin (no UI path exists — by design):
   ```bash
   python -m app.scripts.grant_platform_role <email> super_admin
   ```
   Under Docker: `docker compose -f docker-compose.prod.yml exec backend python -m app.scripts.grant_platform_role <email> super_admin`

## AFTER DEPLOY

- [ ] Run the smoke tests below against the real deployment.
- [ ] Confirm `/docs` returns **404** (default in production) — or 200 if you deliberately set `API_DOCS_ENABLED=true`.
- [ ] Confirm a browser request from the real frontend succeeds (proves CORS).
- [ ] Send one real password-reset email; confirm the link points at the **production** frontend, not localhost (proves `FRONTEND_BASE_URL`).
- [ ] Stripe: fire a test event from the Dashboard; confirm it is accepted and that a **replay of the same event id** returns `already_processed`.
- [ ] Confirm rate limiting works end to end (6 failed logins from one IP → 429). If it does not, `TRUSTED_PROXY_HOPS` is wrong.
- [ ] Watch logs for the `CORS_ALLOWED_ORIGINS is not set` warning — its absence is the confirmation.

## ROLLBACK

The migration chain is **additive only** — it adds tables, columns, and
indexes and never drops or narrows one. Consequences:

- **Redeploying an older application image is safe.** Older code ignores
  newer columns; newer rows stay inert.
- **Do not roll the database back** to restore an older app version. You
  do not need to, and a restore would lose data written since.
- Rolling back the worker is always safe: jobs stop being claimed, none
  are lost (`recover_abandoned_jobs` returns leased jobs to `pending`).
- If a rollback is needed **because of data corruption** rather than a bad
  deploy, that is a provider-side point-in-time restore, and it is
  destructive — take a fresh backup first, and expect to lose writes made
  after the restore point.

Rollback steps: redeploy the previous image/commit for the affected
service → confirm `/health/ready` → re-run smoke tests 1–6.

---

## Smoke test plan

Run **after** deploying, against the real environment, with a throwaway
account. Do not use real customer data.

| # | Check | Pass criteria |
|---|---|---|
| 1 | Landing page loads | 200, no console errors |
| 2 | Register a new account | Lands in the app; exactly one organization created |
| 3 | Google login (if enabled) | Returns to the app signed in; no token in the URL bar |
| 4 | Email verification | Email arrives; link points at the **production** domain |
| 5 | Organization onboarding | Settings shows the org; language/currency editable |
| 6 | Create a customer | Appears in the list; persists across reload |
| 7 | Create a product | Appears in the catalog |
| 8 | Create a quote | Numbered sequentially; totals correct |
| 9 | Create an invoice | Numbered `INV-000001`; totals correct |
| 10 | Download the invoice PDF | `200`, `application/pdf`, opens correctly |
| 11 | Notification appears | Bell shows the new event, in the recipient's language |
| 12 | Audit log | Settings → Audit Log lists the actions just performed |
| 13 | Dashboard | Loads with real figures, no errors |
| 14 | Financial Intelligence | `/analytics/financial` loads (or shows an honest plan-gated state) |
| 15 | Forecast | Renders, or honestly reports insufficient history |
| 16 | AI Advisor | Generates, **or** shows a clean plan/AI-unavailable state — never a stuck spinner (if no worker: expect the stuck-pending state; see the worker decision) |
| 17 | Stripe test flow | Checkout opens; webhook received; subscription reflects the change |
| 18 | WhatsApp status/QR | Settings → WhatsApp shows an honest state (disabled/unconfigured/QR) |
| 19 | Logout → login | Session cleared; re-login works |
| 20 | Mobile viewport | No horizontal overflow on dashboard, invoices, financial pages |

**Cross-tenant probe (do this too):** register a second account and
confirm every `/organizations/<other-org-id>/...` request returns 403.

---

## Backup & recovery

| Responsibility | Owner |
|---|---|
| Postgres backups / PITR | **Provider** (Neon, or your own `pg_dump` via `scripts/backup_postgres.sh` on the self-hosted path). This repo implements no custom backup system, deliberately. |
| Retention window | **You** — verify it; do not assume. |
| Restore drill | **You** — a backup never verified by a restore is not a backup. |
| WhatsApp session volume | Ephemeral-ish: losing it forces a QR re-scan, no business data lost. Not worth backing up. |
| Generated PDFs | Ephemeral by design — regenerated on demand from invoice rows. |
| In-memory rate-limit counters, insight narration cache | Ephemeral; reset on restart, by design. |
| Must persist | The Postgres database. That is the entire durable state of this application. |

---

## Verification performed in this audit

All executed, not assumed:

- Full migration chain from **zero** against a disposable Postgres 16 container → 37 tables, 100 indexes, 70 FKs, 22 unique constraints, 4 plans seeded (`free` default).
- `init_db()` run **3× consecutively** — idempotent, no error, no drift.
- **Upgrade path**: simulated a pre-Phase-25 schema holding an existing user row, ran the chain to HEAD → new columns added, legacy row correctly backfilled (`password_set=True`), zero data loss.
- Backend booted with `ENVIRONMENT=production` against that Postgres; full flow exercised: register → verify → customer → product → invoice (`INV-000001`, `500.00 USD`) → **real PDF** (`%PDF`, 2463 bytes) → dashboard → insights.
- **Runtime cross-tenant probe**: a second tenant's token against 16 of the first tenant's endpoints → **403 on every one**; unauthenticated → 401; ordinary user against 5 `/admin` endpoints → **403 on every one**.
- Security headers, CORS allow/deny, and absence of stack traces verified on live responses.
- Docker images built for all three services; backend container ran **healthy** against Postgres as non-root (`uid=1000 appuser`); no `.env` present in the image.
- `docker compose config` validated for both compose files; the production file correctly **refuses** to start with secrets unset.
- Secret scan across all git-tracked files and full history: no real secrets; `.env` never committed.
