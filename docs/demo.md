# Demo Guide

A ready-to-run demo account and a scripted, timed walkthrough for showing
this project live — to a hiring manager, in a technical interview, or to
a first prospective user. Written so someone who has never seen the
codebase before can run the demo cold from this document alone.

See also: [`docs/screenshots.md`](screenshots.md) (this script doubles as
a capture checklist for that list) and
[`docs/portfolio.md`](portfolio.md) (the engineering narrative behind
what you're about to show).

---

## Demo organization & user

The repo ships a minimal, idempotent seed script:

```bash
python -m app.seed_demo
```

| | Value |
| --- | --- |
| Email | `demo@example.com` |
| Password | `demo12345` |
| Organization | "Demo Organization" |
| Role | `member` (see note below) |

**Before you present, read this:** `app/seed_demo.py` creates exactly one
user, one organization, and one membership — no customers, products,
invoices, or quotes, and the membership defaults to the `member` role,
**not** `owner`. That's enough to prove the seed script is idempotent
(safe to run repeatedly against a shared demo database) but it is *not*
enough, on its own, to demo owner-only surfaces (Team management,
Settings → Plan, API Keys, Webhooks, platform admin). Richer, realistic
seed data is on the [roadmap](../README.md#roadmap) — until it lands,
pick one of these two setups:

### Option A — register a fresh account (recommended for a live demo)

Registering through the UI (`POST /auth/register`) auto-creates a brand
new organization **with you as its owner**, giving full access to every
surface with zero setup:

1. Go to `/login` → "Create account".
2. Register with any email (doesn't need to be real — email verification
   gates a couple of write actions, not login) and a memorable
   organization name, e.g. "Acme Consulting".
3. You're immediately signed in as the owner. Spend two minutes before
   recording creating: 2–3 customers, one product, one quote (mark it
   sent → accepted → convert to invoice), and one invoice paid directly.
   This gives the dashboard and insights engine real numbers to show
   instead of empty states.

This is the path used by the script below.

### Option B — the seeded demo account

Use `demo@example.com` / `demo12345` when you specifically want a
**stable, memorized, repeatable login** (e.g. pasted into a portfolio
site as "try it yourself") rather than a fresh registration each time.
Grant it ownership first if you need owner-only surfaces:

```bash
python -c "
from app.database import SessionLocal
from app.models import OrganizationMember
db = SessionLocal()
m = db.query(OrganizationMember).filter_by(user_id='11111111-1111-1111-1111-111111111111').one()
m.role = 'owner'
db.commit()
"
```

(This talks directly to whatever `DATABASE_URL` your shell has set — safe
to run against a disposable local/demo database, **never** against a
real production database with real tenants in it.)

---

## Demo workflow (what to show, roughly in order)

1. **Login** — a clean, fast auth flow; mention JWT + bcrypt.
2. **Dashboard** — revenue/pipeline KPIs and the AI-narrated insights
   engine, populated with the data you seeded.
3. **Customers** — CRUD, then the CSV/XLSX bulk-import flow (the single
   most "enterprise" feature to show off quickly).
4. **Quotes** — create one, send it, open the *public* accept/reject link
   in a private/incognito window (no login required — this is what your
   customer actually sees), accept it, convert it to an invoice.
5. **Invoices** — PDF export, payment status, the "Open in WhatsApp"
   share action.
6. **Billing / Plan & Limits** — Settings → Plan, showing usage against
   limits; if `BILLING_PROVIDER=stripe` is configured, a real checkout
   session.
7. **Notifications** — the in-app inbox picking up the events you just
   generated (quote sent, quote accepted, invoice created).
8. **Audit** — Settings → Audit Log, showing the exact same events as an
   immutable, queryable timeline with actor and timestamp.
9. **Admin dashboard** — `/admin` (requires a platform role — see
   [Before you present](#before-you-present) below), showing the
   operator's-eye view: organizations, plans, background jobs, the
   platform audit log.

---

## Live demo script (3–5 minutes)

Timings assume you're narrating while clicking, not reading a script
verbatim — adjust to your own pace. Everything below assumes **Option
A** (a freshly registered owner account) with a handful of records
already created, as described above.

### 0:00 – 0:20 · Login

> "This is a multi-tenant invoicing and quoting platform — I'll log in
> as the owner of a demo organization."

Land on `/login`, sign in. Call out (don't dwell): JWT auth, bcrypt
password hashing, re-verified against the live database on every
request — not just trusted from the token.

### 0:20 – 1:00 · Dashboard

> "This is the dashboard every organization sees — revenue, pipeline,
> and an insights engine that's part rule-based, part AI-narrated."

Point at one KPI card and one insight. If an AI provider is configured,
mention the insight text is model-generated but every number it
references comes from the deterministic engine, never the model — the
model can rewrite the sentence, never invent the number.

### 1:00 – 1:45 · Customers → bulk import

> "Customers support full CRUD, plus bulk import for anyone migrating
> from a spreadsheet."

Show the customer list, then open the CSV/XLSX import flow — column
mapping, row-level validation preview. You don't need to actually
complete an import live; showing the mapping/preview screen is enough to
demonstrate it's not a toy feature.

### 1:45 – 3:00 · Quotes — the full lifecycle

> "This is the part most invoicing demos skip — the *pre*-invoice
> lifecycle."

1. Create a quote for a customer, add a line item, send it.
2. Open the **public quote link** in a private window — no login. This
   is the moment that lands best live: *"this is exactly what your
   customer receives and sees, with nothing behind a paywall."*
3. Accept it from the public page.
4. Back in the authenticated app, convert the accepted quote to an
   invoice with one click — call out that this creates a fully
   independent invoice (its own line items, its own numbering); editing
   the invoice later can never reach back and change the quote, or vice
   versa.

### 3:00 – 3:45 · Invoices

Open the resulting invoice. Download the PDF (or just show the button —
don't wait on a slow render live). Mark it paid; point out the payment
status badge updates immediately, and mention that "overdue" is computed
at read time from the due date, never a stored value that could drift
out of sync.

### 3:45 – 4:15 · Notifications & Audit

> "Everything I just did — the quote being sent, accepted, converted —
> went through one event pipeline that fans out to four places at once."

Open the notification bell — show the events that just landed in the
inbox. Then Settings → Audit Log — the same events, as an immutable,
timestamped, actor-attributed timeline. This is the fastest way to prove
the event pipeline is real, not just described in a README.

### 4:15 – 5:00 · Admin dashboard (optional close, if you have platform access)

> "Separately from the tenant app, there's a full platform-operations
> console — invisible to any tenant, gated by a completely independent
> permission system."

`/admin` → Organizations (show the one you're demoing from, with its
usage bar), then Background Jobs (point out pending/claimed/failed
counts — this is the same durable queue that would be delivering
webhooks in production), then Audit Log (the *platform*-level one — every
suspend/plan-change/role-grant action, distinct from the tenant audit
log you just showed).

Close with one sentence: *"Every piece you just saw — tenant isolation,
the event pipeline, the background job queue — is covered by its own
dedicated test suite, including tests that specifically try to break the
isolation guarantees, not just the happy path."*

---

## Before you present

- [ ] Confirm you're demoing against a **disposable** database — never a
      real production instance with real tenant data.
- [ ] Seed 2–3 customers, one product, and at least one full
      quote→invoice cycle *before* you start recording — an empty
      dashboard undersells the insights engine.
- [ ] If showing the admin console, grant yourself a platform role first
      (see `app/routers/platform_admin.py` for the granting endpoint, or
      set `platform_role='super_admin'` directly on your `User` row in a
      disposable demo database).
- [ ] If showing real Stripe checkout, use Stripe's own test-mode keys
      and test card numbers — never live keys in a demo.
- [ ] Have a second (private/incognito) browser window ready for the
      public quote link — switching windows live is much smoother than
      logging out and back in.
