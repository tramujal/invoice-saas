# Engineering Portfolio Notes

Written for a technical interview or a portfolio walkthrough, not as a
changelog — this is the story of the harder decisions in this codebase,
what broke, how it was found, and why the fix is shaped the way it is.
Every claim below points at a real file, test, or commit in this repo;
none of it is aspirational. For the architecture itself, see
[`docs/architecture.md`](architecture.md).

---

## Table of contents

- [Biggest engineering challenges](#biggest-engineering-challenges)
- [Architectural decisions](#architectural-decisions)
- [Scaling decisions](#scaling-decisions)
- [Testing strategy](#testing-strategy)
- [Security strategy](#security-strategy)
- [Production readiness](#production-readiness)
- [Lessons learned](#lessons-learned)

---

## Biggest engineering challenges

### Making "the last owner can never be removed" actually true under concurrency

The business rule is simple to state: an organization must always have
at least one active owner. The naive implementation — count active
owners, reject if the count would hit zero — is correct for a single
request and **wrong** the instant two requests run concurrently: two
owners each demoting the other can both read "one other owner remains"
before either commits, and both succeed, leaving zero.

The fix reuses a row lock (`app.services.plan_limits._lock_organization`,
`SELECT ... FOR UPDATE` on the organization row) that already existed
for a completely different purpose — serializing concurrent
plan-quota checks — rather than inventing a second locking primitive for
what is structurally the same problem (two writers, one invariant, one
row to serialize on). The interesting engineering decision wasn't the
lock itself; it was recognizing that a lock built for quota enforcement
and a lock needed for a headcount invariant are the same lock, and
building a second one would have been the kind of "obviously different
because it *sounds* different" duplication that's easy to miss under
deadline pressure.

Proven with a genuine two-thread race
(`tests/team/test_ownership_concurrency.py`) — two real `threading.Thread`
workers, synchronized with a `threading.Barrier` so both actually
contend for the lock, against a real SQLite file with `BEGIN IMMEDIATE`
forced on every transaction (SQLite's ordinary deferred-transaction mode
doesn't serialize the way Postgres's row lock would, so a naive test
would pass even with the bug present) — not a mock, not a single-threaded
sequential simulation.

### Closing a Stripe integration gap that was silently a money bug

An earlier phase built the entire billing *domain* (`Plan`, `Subscription`,
`BillingService`) and a full `BillingProvider` abstraction with a working
`StripeProvider` implementation — and then never actually called it from
the four lifecycle methods that matter (`cancel_immediately`,
`cancel_at_period_end`, `reactivate`, `change_plan`). Every test passed.
The API returned 200. The local `Subscription` row updated correctly.
And an admin canceling a subscription never actually stopped Stripe from
billing the customer's card.

This is the class of bug that's genuinely dangerous precisely *because*
nothing observable is wrong — no error, no failed test, no user
complaint until a real invoice shows up on a canceled account weeks
later. It surfaced from a functional/UX audit that asked "does this
button do what it says," not from a stack trace.

The fix had a subtlety worth naming: `BillingService.sync_from_webhook_event`
*also* calls `cancel_immediately` — but that call site is Stripe telling
the app a cancellation already happened, not the app telling Stripe to
cancel. Wiring the provider push into `cancel_immediately` unconditionally
would have made every incoming Stripe webhook re-issue a cancel request
back to Stripe — redundant at best, an API error at worst (Stripe
correctly rejects canceling an already-canceled subscription). The fix
is a `sync_to_provider: bool = True` parameter, defaulting to the
tenant/admin-initiated path and explicitly set `False` on the three call
sites inside the webhook handler — a small signature change that encodes
a real distinction ("I am telling the provider" vs. "the provider is
telling me") that the original design had no way to express.

### The N+1 that only showed up at scale, and the one that showed up as a lost write

Two different classes of bug, both found by treating "it works" as an
insufficient bar:

- **Notification fan-out** (`emit_event`) looped once per organization
  member, calling `is_email_enabled()` and re-fetching the `User` row
  individually for each one — invisible with 2 test members, a
  linear-in-team-size cost on every single business write once a real
  organization had 30. Fixed by batching both checks into two
  `IN (...)` queries regardless of member count, verified by a test that
  asserts the *query count*, not just the output (`tests/test_notifications.py`)
  — a test that only checks results would pass on the slow version too.
- **Quote-to-invoice conversion** committed the new invoice, then
  separately committed the quote's `converted_invoice_id` update. A
  crash between those two commits left a real, paid-for invoice with no
  record it came from a quote — and because the "already converted"
  guard only checks the quote's own field, a retry would silently create
  a *second* invoice for the same quote. Fixed by giving the shared
  invoice-creation helper a `commit: bool` parameter so the one caller
  that needs cross-step atomicity can own a single final commit instead
  of two.

### Proving tenant isolation instead of asserting it

The scariest bug class in a multi-tenant system is "organization A can
see organization B's data" — and the scariest version of that bug is one
that only exists in a code path nobody thought to test, like the AI
assistant. `tests/tenants/` includes a dedicated test that tries to
trick the agent into acting across organizations by manipulating tool
arguments — not because a specific exploit was found, but because
*every* new capability that touches business data is a new surface that
needs the same proof the REST API already had.

---

## Architectural decisions

**One frozen event-pipeline entry point, four consumers.**
`emit_event()` is the only place a business service ever says "this
happened" — it fans out, inside the caller's own open transaction, to
outbound webhooks, in-app notifications, transactional email, and the
tenant audit timeline. The alternative — each subsystem hooking into
business logic independently — is how most real codebases end up with
webhooks firing for some events and not others, or an audit log that's
quietly missing whatever the last engineer forgot to instrument. Freezing
this as governance (documented, not just habitual) means a fifth channel
is a one-line addition inside the fan-out, never a second call site that
can drift out of sync with the first. See
[`docs/architecture.md#event-pipeline`](architecture.md#event-pipeline).

**Provider abstractions for everything that talks to the outside world.**
AI (Claude/Gemini), email (Resend), and billing (Stripe) each sit behind
a small interface the domain layer depends on, never a concrete SDK.
This wasn't done speculatively "in case we switch providers someday" —
it was done because `BillingService`'s actual business rules (upgrade
vs. downgrade classification, trial handling, cancellation semantics)
needed to be fully testable *before* a payment processor was even
chosen, and a `NullBillingProvider`/`FakeBillingProvider` pair makes that
possible. The abstraction paid for itself before Stripe was ever
integrated.

**Two permission systems, deliberately never merged.** Organization RBAC
(`app/permissions.py`) and platform RBAC (`app/platform_permissions.py`)
share no code. The alternative — one big permission enum with an
`is_platform` flag, or platform admins granted org-scoped permissions
under the hood — is exactly the kind of "convenient" unification that
turns into a privilege-escalation bug the day someone adds a permission
check that doesn't distinguish the two axes correctly. Keeping them
structurally separate means that class of bug is unreachable, not just
tested against.

**Status computed at read time, never stored.** Whether an invoice is
"overdue" or a quote has "expired" is derived from the current date at
the moment it's read, not a value written once and left to go stale.
This trades a small amount of read-time computation for eliminating an
entire category of "the stored status is wrong because nothing updated
it" bugs — no cron job, no background reconciliation pass, nothing that
can fail silently and leave data lying.

**Snapshot money-relevant data at creation time.** An invoice's
currency, language, and — after the most recent hardening pass — the
billed customer's name/email/phone/address are all copied at the moment
the document is created, never re-derived from the organization's or
customer's *current* settings. The alternative (a live join) means
editing your organization's default currency, or fixing a typo in a
customer's address, would silently rewrite the appearance of every past
invoice — a genuine compliance problem for a document that's supposed to
be a permanent record of what was actually billed.

---

## Scaling decisions

**A database-backed job queue instead of a message broker.** At this
project's actual scale, a `BackgroundJob` table with an atomic,
lease-based claim gets 90% of what Redis/RabbitMQ/SQS would provide —
durability, at-least-once delivery, crash recovery — with one fewer
service to operate, monitor, and pay for. The explicit tradeoff: this
doesn't scale to thousands of jobs/second the way a dedicated broker
would. That ceiling is well above what a project at this stage needs,
and the migration path (swap the claim query for a broker client behind
the same `enqueue_job()`/handler interface) doesn't require touching any
of the ~30 call sites that enqueue work today.

**Batch, don't loop, once "per row" stops being free.** The notification
fan-out fix above is the general pattern applied everywhere usage
tracking or plan-limit checks happen inside a loop (CSV/XLSX bulk
import): resolve the organization's plan/limit/usage numbers *once* per
import via `open_limit_tracker()`, then have each row check against an
in-memory running total (`LimitTracker.consume()`) instead of
re-querying the database per row. The query cost of importing 500 rows
went from ~500× the single-row cost to a small constant plus 500 cheap
in-memory comparisons.

**Indexes added for the query shapes that actually run**, not
speculatively — every index in `app/schema_migrations.py`'s
high-priority-index migration is tied to a named, real query pattern
(e.g. `ix_invoices_organization_due_date` for the reminder job's own
`WHERE organization_id = ? AND due_date <= ?`), added after profiling
showed the pattern, not before.

**Optimistic concurrency, not pessimistic locking, for rows that are
rarely-but-plausibly contended.** `Subscription`, `Plan`, and
`PlatformSettings` use a `version` column and a conditional
`UPDATE ... WHERE version = expected_version` rather than holding a
lock for the duration of a request. Two writers racing is rare enough
(a platform admin and an incoming webhook, or two admins editing the
same plan) that paying the throughput cost of pessimistic locking on
every read isn't justified — a mismatched version surfaces as an
explicit, recoverable 409 instead.

---

## Testing strategy

**985 backend tests, 285 frontend tests** — but the number that matters
more than the count is *what class of bug each layer is responsible for
catching*:

- **Unit/service-level tests** (the majority) prove business logic in
  isolation — totals math, status transitions, permission-hierarchy
  edge cases — fast, no HTTP, no real concurrency.
- **Router/integration tests** prove the HTTP contract: status codes,
  error shapes, permission enforcement at the actual boundary a client
  hits.
- **Genuine concurrency tests, used sparingly and deliberately.** Most of
  this suite doesn't need real threads — but the handful of invariants
  that are *specifically* about concurrent behavior (the last-owner
  race, `Subscription` version conflicts, background-worker double-claim
  prevention) are tested with real `threading.Thread`/`threading.Barrier`
  reproductions against a real SQLite file with forced-serializable
  transactions, never mocked. A mocked "concurrency" test would pass
  whether or not the actual locking logic works — it would only prove
  the code *compiles*.
- **Tenant-isolation tests as their own dedicated suite**
  (`tests/tenants/`), not folded into each resource's own test file —
  the goal is a test that fails loudly the moment *any* new resource
  type or new caller (including the AI agent) forgets to scope a query,
  not a hope that ordinary CRUD tests would happen to catch it.
- **Frontend responsive-layout regression tests** assert the actual CSS
  classes that produce overflow-safe behavior (`min-w-0`, `break-words`,
  `overflow-x-auto` containers) rather than measured pixel widths, since
  `jsdom` doesn't compute real layout — paired with real, in-browser
  verification at five viewport widths (320/375/390/430px + tablet)
  before calling the fix done, because a class-name assertion alone
  can't prove a browser actually renders it correctly.

**A recurring pattern worth naming**: several of the tests above exist
specifically because an *earlier* version of the same feature had a bug
that a weaker test would have missed — the webhook-receipt/subscription
-mutation atomicity test checks durability across **separate database
connections**, not just same-session state, because a same-session check
can't tell "committed" from "merely pending in this one session's
uncommitted view."

---

## Security strategy

Layered, and audited in explicit passes rather than assumed complete
after the first one:

1. **Structural tenant isolation** — see
   [Architectural decisions](#architectural-decisions) and
   [`docs/architecture.md#organization-isolation-multi-tenancy`](architecture.md#organization-isolation-multi-tenancy).
2. **RBAC enforced at the boundary, everywhere, identically** — REST
   routes, the public API (via API key scopes), and AI tool calls all
   check the same `Permission` map; the frontend's own gating is
   explicitly documented as a UX convenience, never trusted as the
   security boundary.
3. **SSRF hardening for the one genuinely attacker-controlled URL in the
   system** — a webhook endpoint URL is entirely organization-supplied,
   which makes it the textbook SSRF vector against internal
   infrastructure. Validated at creation *and* again immediately before
   every delivery attempt, with the same check re-run at actual
   TCP-connect time specifically to close the DNS-rebinding gap between
   "this hostname resolved safely when we checked" and "this hostname
   resolves somewhere else by the time we connect."
4. **Everything that's hashed is hashed the same way** — user passwords
   and API key secrets both use the identical bcrypt-family approach;
   there's no "lesser" scheme for machine credentials that would be an
   easier target.
5. **A dedicated, multi-pass audit process**, each pass narrower and more
   targeted than the last:
   - **RC2 — functional/UX audit**: seven parallel, independently-scoped
     agents, each covering one subsystem (auth, orgs/permissions,
     documents, billing/webhooks, jobs/notifications/audit,
     AI/insights, platform-admin/frontend), explicitly instructed *not*
     to invent hypothetical issues — only report what's demonstrable
     from the code. Found 3 Critical, 7 High, ~13 Medium, ~8 Low —
     including the Stripe-sync gap above and a last-owner race that had
     existed, unnoticed, since the ownership-transfer feature shipped.
   - **SEC2 — remediation of the Critical/High findings**: implemented
     with an explicit stop condition (exactly the 8 findings named, no
     scope creep), each with its own regression test proving the
     specific failure mode is now closed, not just "the code changed."
   - **UX1 — mobile-responsiveness pass**: a narrower, UI-only audit
     that found real horizontal-overflow bugs missed by the earlier
     functional pass (different failure mode, different audit lens) —
     a good example of why "audited" needs to specify *audited for
     what*.
6. **Honest documentation of what a fix can't guarantee.** The
   customer-snapshot migration (closing the "editing a customer
   retroactively changes a past invoice" bug) includes an explicit,
   prominent note that its backfill for *pre-existing* documents can only
   copy the customer's *current* data — this system never recorded
   customer field history, so true historical accuracy for old
   documents whose customer was edited before the fix shipped is
   genuinely unrecoverable. Documenting a limitation honestly is part of
   the security/data-integrity story, not a footnote to it.

---

## Production readiness

- **CI is merge-blocking**, not advisory — `.github/workflows/ci.yml`
  runs backend (`pytest`) and frontend (`tsc`, `vitest`, `next build`)
  as independent required checks on every PR and push to `main`.
- **Two deployment paths, both documented end-to-end**: a managed path
  (Neon + Render + Vercel) and a self-hosted path
  (`docker-compose.prod.yml` + Caddy for automatic HTTPS) — see
  [`docs/deployment.md`](deployment.md).
- **Liveness and readiness are separate health checks** (`/health` vs.
  `/health/ready`, the latter verifying real database connectivity) —
  the Kubernetes/Render-standard distinction, not a single combined
  endpoint that conflates "the process is up" with "the process can
  actually serve traffic."
- **Security response headers on every response**, backend and frontend,
  not just the ones someone remembered to add manually.
- **A backup story for both deployment paths** — Neon's own continuous
  backup for the managed path, a documented `pg_dump`-based script for
  the self-hosted one — rather than "backups are the hosting provider's
  problem" left unstated.
- **Structured error responses with stable `code` fields** throughout
  (`plan_limit_reached`, `subscription_version_conflict`,
  `organization_suspended`, ...) so a frontend (or an API integrator) can
  branch on a contract, never on parsing a human-readable message string.
- **Known, explicitly-tracked gaps, not silently absent ones** — no
  Alembic yet (schema grows via a small, idempotent, additive-only
  migration module instead), Stripe env vars not yet wired into the
  one-click deploy configs, no hard job-execution timeout — all called
  out in the [README's Roadmap](../README.md#roadmap) rather than
  discovered by a reader the hard way.

---

## Lessons learned

**A feature can be "fully built" and still not actually work.** The
Stripe-sync gap is the sharpest example: the interface existed, the
implementation existed, the tests for the implementation passed — and
the four places that should have called it, didn't. "Is this wired up
end-to-end" turned out to be a different question than "is this
implemented," and only a pass that specifically asked the first question
found the gap.

**Mocked concurrency tests prove the code compiles, not that it's
correct.** Every genuine race-condition fix in this codebase (last-owner
protection, subscription version conflicts, background-job double-claim
prevention) is tested with real threads against a real, forced-serializable
database file. That decision came directly from an earlier near-miss:
a first draft of a concurrency test used two sequential calls on one
shared connection, which would have passed identically whether the
actual locking fix was present or not.

**Governance rules only work if they're written down where the next
change will actually see them.** The event-pipeline's "one entry point,
never a second call site" rule is documented directly in `emit_event`'s
own module docstring, not in a wiki or a design doc nobody re-reads six
months later — the exact place someone adding a sixth event type will be
looking when they write the code.

**Different audits find different bugs, on purpose.** A security-focused
pass and a mobile-responsiveness pass looked at overlapping code and
found non-overlapping issues, because they were asking different
questions of it. Treating "we did a security review" as covering UX
correctness (or vice versa) is a category error worth naming explicitly
rather than assuming one audit's clean bill of health generalizes to
concerns it was never scoped to check.

**Honest limitations are part of the deliverable, not a gap in it.**
Documenting precisely what a historical-data backfill *can't* guarantee,
or that Stripe env vars aren't yet wired into every deploy path, is more
useful — to a future engineer, a code reviewer, or an interviewer — than
a README that implies everything is uniformly finished. The goal was a
codebase that's honest about its edges, not one that reads as
flawless.
