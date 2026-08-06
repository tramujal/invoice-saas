# Deployment (Phase RC1 — Production Release Readiness)

This is the single consolidated reference for taking this app to
production. It doesn't replace the shorter walkthroughs already in
[README.md](../README.md)'s own Deployment section or in
[render.yaml](../render.yaml)'s comments — it indexes and expands on
them, and covers everything neither of those files does on its own
(backup strategy, security headers, health endpoints, monitoring hooks,
the self-hosted Docker path).

There are **two deployment paths**. Pick one; don't mix them.

| | Path A — Managed (recommended) | Path B — Self-hosted Docker |
|---|---|---|
| Database | [Neon](https://neon.tech/) (Postgres) | `docker-compose.prod.yml`'s own `db` service |
| Backend + worker | [Render](https://render.com/) | `docker-compose.prod.yml`'s `backend` + `worker` services |
| Frontend | [Vercel](https://vercel.com/) | `docker-compose.prod.yml`'s `frontend` service |
| TLS / HTTPS | Handled automatically by Render + Vercel | `docker-compose.prod.yml`'s `caddy` service (automatic Let's Encrypt) |
| Backups | Neon's built-in continuous backup + PITR | `scripts/backup_postgres.sh` (you run/schedule it) |
| Effort | Lowest — three dashboards, no server to maintain | Higher — you own the host, TLS renewal, and backups |

## Path A — Render + Vercel + Neon

Full step-by-step walkthrough: see README.md's own
[Deployment](../README.md#deployment) section — it's not duplicated here.
Everything below this point (environment variables, health endpoints,
security headers, monitoring, CORS, rate limiting) applies equally to
this path.

## Path B — Self-hosted Docker (`docker-compose.prod.yml`)

For deploying to your own server/VM instead of Render+Vercel+Neon.

**Prerequisites:**
- A server with Docker + the Compose plugin installed.
- Two DNS A/AAAA records already pointing at that server's public IP —
  one for the API (e.g. `api.yourdomain.com`), one for the frontend
  (e.g. `app.yourdomain.com`). Caddy's automatic HTTPS (Let's Encrypt)
  cannot obtain a certificate for a domain that doesn't resolve yet.
- Ports 80 and 443 reachable from the internet (Let's Encrypt's HTTP-01/
  TLS-ALPN-01 challenges need them; Caddy also uses 80 to redirect
  plain-HTTP traffic to HTTPS).

**Steps:**

```bash
cp .env.prod.example .env
# edit .env: POSTGRES_PASSWORD, JWT_SECRET_KEY, DOMAIN_API, DOMAIN_FRONTEND
# (generate secrets with the python -c "import secrets; ..." one-liners
# .env.prod.example itself shows inline)

docker compose -f docker-compose.prod.yml up -d --build
```

That single stack brings up, in dependency order (see
`docker-compose.prod.yml`'s own `depends_on`/`condition: service_healthy`
chain — no separate migration step is needed, `app.schema_migrations`
runs idempotently on every backend startup): Postgres → backend (web,
`WEB_CONCURRENCY` uvicorn workers) → worker + frontend → Caddy (TLS +
reverse proxy for both public domains).

**Updating:** `git pull && docker compose -f docker-compose.prod.yml up -d --build` — rebuilds only the images whose source changed; Postgres data and Caddy's certificates persist in their own named volumes across this.

**Structural validation performed for this file:** `docker compose -f docker-compose.prod.yml config` (pure YAML/interpolation resolution, no daemon required) — confirms env-var interpolation, the required-secret `${VAR:?...}` guards, and the resolved `command:`/`healthcheck:` are all well-formed. A full `docker compose up` / `caddy validate` run requires an actual Docker daemon and a real DNS-resolving domain, neither available in this development environment — validate those on the target host as part of your own first deploy.

## Environment variables

The full, authoritative list (with defaults and behavior notes) lives in
[`.env.example`](../.env.example) (Path A / local dev) and
[`.env.prod.example`](../.env.prod.example) (Path B). Do not duplicate
that list here — it will drift. The variables most relevant to a
*production* deployment specifically, regardless of path:

| Variable | Required in production? | Effect if missing |
|---|---|---|
| `DATABASE_URL` | Yes | App fails to start (no fallback in a real deployment) |
| `JWT_SECRET_KEY` | Yes | **Hard startup failure** (`app/security.py`) when `ENVIRONMENT=production` |
| `ENVIRONMENT=production` | Yes | Without it, the JWT/AI_MODEL production-only guards never activate |
| `CORS_ALLOWED_ORIGINS` | Yes (practically) | Falls back to `localhost` origins with a **logged warning** — the real frontend can't call the API until this is set |
| `TRUSTED_PROXY_HOPS` | Yes, if behind any reverse proxy | Defaults to `0` (trust nothing) — rate limiting keys on the proxy's own IP instead of each real client's, weakening it |
| `AI_MODEL` | Only if `AI_PROVIDER` is set | No dev fallback in production — the assistant 503s until this is set |
| `RESEND_API_KEY` / `EMAIL_FROM` | No | Email-sending routes 503; everything else unaffected |

## Health endpoints

Two, deliberately different:

- **`GET /health`** — liveness only. Never touches the database. Answers
  "is the process up and serving requests" — use this for a container
  orchestrator's liveness probe (restarting the process fixes a hung
  process, but restarting it does nothing for a database outage, so a
  liveness probe should never depend on the database).
- **`GET /health/ready`** — readiness. Runs a cheap `SELECT 1` against
  the real database connection and returns **503** (not 200 with an
  error body) if that fails. Use this for a readiness probe / load-
  balancer health check / uptime monitor — the thing you actually want
  to know before routing real traffic here.

`docker-compose.prod.yml`'s own `backend` service healthcheck (which
gates `depends_on: condition: service_healthy` for `worker` and
`frontend`) uses `/health/ready`, not `/health` — see that file's own
comment on why.

## Startup ordering

Both deployment paths follow the same rule: **the database must be
reachable before the backend's own FastAPI `lifespan` hook runs**
(`app.models.init_db()`, idempotent schema migrations — see
`app/schema_migrations.py`). Neither path needs a *separate* migration
step or job — every process that imports `app.main` (the web service,
and implicitly the worker, since both share `app/`) runs the same
idempotent migrations on its own startup, so whichever process starts
first "wins" the migration and every later one is a no-op.

- **Path A (Render):** Render starts the web service after Neon already
  exists (you created it first, per the numbered steps in README.md).
  The worker (if deployed) can start before or after the web service —
  both call the same idempotent `init_db()`.
- **Path B (Docker):** enforced explicitly via `depends_on: condition:
  service_healthy` (`db` → `backend` → `worker`/`frontend`) — see
  `docker-compose.prod.yml`.

## Data migration notes

`_add_document_customer_snapshots` (`app/schema_migrations.py`, Phase
SEC2/H6) adds `customer_name_snapshot`/`customer_email_snapshot`/
`customer_phone_snapshot`/`customer_address_snapshot` to `invoices` and
`quotes`, and best-effort backfills them for every pre-existing row
linked to a customer. **Known limitation:** this app has never recorded
a `Customer` row's field history, so the backfill can only copy each
document's linked customer's *current* name/email/phone/address at the
moment this migration runs — it has no way to know what those fields
actually were when the document was originally issued. For any
pre-existing invoice/quote whose customer was edited at any point
between original issuance and this migration running, the backfilled
snapshot is **not guaranteed** to match what was actually billed;
reconstructing that is genuinely impossible with the data this app has
ever stored. Only documents created after this migration ships get a
guaranteed-accurate snapshot, immune to any later edit of the customer.

## Logging

Configured once, at import time, in `app/main.py` — every
`logging.getLogger(__name__)` call anywhere in the codebase emits to
stdout/stderr in a consistent `%(asctime)s %(levelname)s %(name)s:
%(message)s` format, which both Render's and Docker's own log
collection capture automatically (no separate log-shipping agent
needed for basic visibility).

`LOG_LEVEL` (env var, default `INFO`) controls verbosity without a code
change or redeploy of a different image — set it to `DEBUG` temporarily
while chasing a production incident, or `WARNING` to cut log volume. An
unrecognized value falls back to `INFO` rather than crashing startup.

## Backup strategy

- **Path A (Neon):** Neon takes continuous backups automatically with
  point-in-time restore built into every plan — nothing to configure.
  See [Neon's own backup docs](https://neon.tech/docs/introduction/backups)
  for retention windows by plan tier.
- **Path B (self-hosted Postgres):** run
  [`scripts/backup_postgres.sh`](../scripts/backup_postgres.sh) — a
  `pg_dump`, gzip-compressed, executed inside the `db` container (never
  needs Postgres exposed to the host, matching that service's own
  no-published-port configuration). The script's own header comment has
  the exact restore command. Schedule it (cron/systemd timer) — it is
  **not** run automatically by `docker-compose.prod.yml` itself, since
  backup cadence and retention are a deployment-specific decision, not
  something this app can safely assume for you.

Neither path backs up anything outside the database — there is no
file-storage subsystem in this app to back up separately (see
`app.services.organization_usage.count_storage`'s own docstring).

## Security headers

`app.security_headers.apply_security_headers` (backend, applied via a
middleware in `app/main.py` to every response) and `next.config.mjs`'s
own `headers()` function (frontend, applied to every route) both set:
`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: strict-origin-when-cross-origin`,
`Permissions-Policy` (denies geolocation/microphone/camera), and
`Strict-Transport-Security` (safe to send unconditionally — browsers
ignore it entirely over plain HTTP per RFC 6797 §7.2).

**Deliberately not included: Content-Security-Policy.** The backend
serves Swagger UI (`/docs`) and ReDoc (`/redoc`), both of which load
their own JS/CSS from a CDN by default — a CSP tight enough to matter
would need to be hand-built around exactly those pages' own asset
origins, and getting it wrong silently breaks the docs UI rather than
failing loudly. If you want a CSP for the *frontend* (a real HTML app
with no such CDN dependency), that's a safer place to add one — it isn't
included here because this phase is about closing gaps, not about
picking a specific policy on the team's behalf without their input.

## CORS

`CORS_ALLOWED_ORIGINS` (comma-separated) — see `app/main.py`'s own
`_cors_origins()`. Falls back to the local dev origins with a **logged
warning** (not a hard failure — see that function's own docstring for
why the failure mode here is annoying-but-self-evident rather than
silently-insecure, unlike the JWT secret) when `ENVIRONMENT=production`
and this is left unset.

**Verify after deploying:** open the deployed frontend, open the browser
devtools Network tab, confirm API requests succeed (no CORS error in the
console) and that `Access-Control-Allow-Origin` in the response matches
the frontend's own origin exactly.

## Rate limiting

Already implemented (`app/rate_limit.py`) and applied across every
sensitive endpoint — auth (`login`, `register`, `forgot-password`,
`reset-password`, `verify-email`), invitations, CSV/XLSX imports,
webhook management, API-key-authenticated public API routes, and quote/
invoice email-sending. Proxy-hop-aware via `TRUSTED_PROXY_HOPS` (see the
Environment Variables table above) — **verify this is set correctly for
your actual topology after deploying**, since an incorrect value doesn't
error, it just silently either trusts a spoofable header (set too high)
or rate-limits your own reverse proxy's IP for every request (set too
low/zero behind a real proxy).

Storage is a single in-process counter (`InMemoryRateLimiterBackend`) —
correct for exactly one running backend process. If Path B's
`WEB_CONCURRENCY` is set above 1, or if you horizontally scale beyond one
container, each process keeps its own counters, so the *effective* limit
becomes roughly `configured limit × process count` — see
`app/rate_limit.py`'s own module docstring, which documents this
explicitly as an accepted single-instance simplification with a
described upgrade path (a Redis-backed `RateLimiterBackend`) if it's
ever outgrown.

## Monitoring hooks

- **`GET /health` / `GET /health/ready`** — wire these into your
  platform's own uptime monitor (Render/Vercel both have one built in;
  for Path B, any external uptime checker — UptimeRobot, Better Stack,
  etc. — or a simple cron+curl+alert script).
- **`GET /admin/dashboard/*`** (platform-admin-authenticated) — business/
  usage/growth metrics plus `_system_health()`'s own queue depth, failed-
  job count, retry count, storage, DB size, request latency (p50/p95/p99
  over an in-memory rolling window — `app.request_metrics`), and error
  rate. This is this app's own internal operations dashboard (Phase 21)
  — not a Prometheus/Grafana-style scrape target, but the first place to
  look when something's wrong, and already deployed with the app itself.
- **No external error-tracking SDK (Sentry, etc.) is wired in.** Adding
  one is a reasonable next step but was deliberately left out of this
  phase — it's a real third-party dependency + account + cost decision,
  not something to silently opt an operator into. If you want it: the
  cleanest integration point is `app/main.py`'s own middleware stack
  (add an exception-capturing middleware alongside `_record_request_metrics`)
  plus `app/routers/*`'s existing `logging.getLogger(__name__).exception(...)`
  call sites, which already fire on every unexpected error.

## Static asset configuration

The frontend build already uses `output: "standalone"`
(`next.config.mjs`) — `frontend/Dockerfile`'s runtime image never
installs `node_modules`, it runs the pruned, generated `server.js`
directly. Next.js's own server (both `next start` and the standalone
`server.js`) sets long-lived, immutable `Cache-Control` headers on
`/_next/static/*` assets automatically — no extra configuration needed,
including on Vercel, which additionally serves those from its own CDN
edge network.

## Build optimization

- **Backend:** single-stage `Dockerfile` — every dependency in
  `requirements.txt` ships prebuilt wheels, so a multi-stage build
  wouldn't shrink the image (see that file's own comment).
  `docker-compose.prod.yml`'s `backend` service overrides the image's
  default single-worker `CMD` with `--workers ${WEB_CONCURRENCY:-2}` to
  use more than one CPU core — see that service's own comment for the
  one caveat (rate-limit counters are per-worker, not shared).
- **Frontend:** multi-stage `frontend/Dockerfile` (`deps` → `builder` →
  `runner`) — the final runtime image contains only
  `.next/standalone` + `.next/static`, never the `~97MB` `next` package
  itself or the full `node_modules` tree.

## Release checklist

Copy this into your own tracking issue/PR before a first public deploy:

- [ ] `JWT_SECRET_KEY` set to a real, freshly generated secret (never the
      dev default) — verified by the app's own hard startup failure if
      you forget, under `ENVIRONMENT=production`.
- [ ] `DATABASE_URL` points at the real production database.
- [ ] `CORS_ALLOWED_ORIGINS` set to the real frontend URL(s) — check the
      startup logs for the "CORS_ALLOWED_ORIGINS is not set" warning;
      its absence confirms this was actually set.
- [ ] `TRUSTED_PROXY_HOPS` matches your actual reverse-proxy topology (1
      for Render or the Path-B Caddy setup; 0 for anything with no proxy
      in front of it).
- [ ] If enabling Google Sign-In: `GOOGLE_REDIRECT_URI` is the real
      `https://<your-api-domain>/auth/google/callback` and is registered
      exactly (scheme, host, path) as an authorized redirect URI on the
      Google Cloud OAuth client — a mismatch fails the callback, not
      silently. See [`docs/google_auth.md`](google_auth.md).
- [ ] `GET /health` and `GET /health/ready` both return 200 against the
      deployed URL.
- [ ] Backend and frontend are on HTTPS (Render/Vercel: automatic; Path
      B: confirm Caddy actually obtained a certificate — check its logs).
- [ ] Security headers present on a real deployed response (`curl -I` the
      deployed API and frontend, confirm `X-Frame-Options`,
      `X-Content-Type-Options`, `Strict-Transport-Security`).
- [ ] Background worker is running somewhere (Path A: the commented-out
      `render.yaml` worker service, upgraded to a paid plan; Path B:
      the `worker` service is part of the same `docker compose up`) —
      otherwise webhook deliveries and notification emails queue up but
      never send.
- [ ] Scheduled reminders wired up (`.github/workflows/send-invoice-reminders.yml`'s
      three repo secrets: `DATABASE_URL`, `RESEND_API_KEY`, `EMAIL_FROM`)
      if you want due-date/expiry email reminders to actually fire.
- [ ] Backup path confirmed: Neon's automatic backups (Path A, nothing to
      do) or `scripts/backup_postgres.sh` actually scheduled (Path B).
- [ ] Full test suite green (`python -m pytest -q`; `npx tsc --noEmit &&
      npx vitest run && npm run build` in `frontend/`) on the exact
      commit being deployed.
- [ ] AI Business Assistant either fully configured (`AI_PROVIDER`,
      matching `*_API_KEY`, `AI_MODEL`) or deliberately left unconfigured
      (clean 503, not a half-configured broken state).
- [ ] Billing provider (`BILLING_PROVIDER`, Stripe) either fully
      configured or deliberately left as `NullBillingProvider` — see
      [`docs/billing_providers.md`](billing_providers.md).
