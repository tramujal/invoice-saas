# Credit and debit notes (Phase 29)

> **Credit and debit notes created by Invoicing are not DGI-issued CFEs.**
> Nothing here submits to DGI, signs anything, allocates a CAE, or
> produces an XML. These are ordinary application financial documents.
> What this phase provides is the domain foundation a future CFE
> integration would need — see `docs/competitive_analysis_uruguay.md` for
> what legal issuance actually requires.

Status: **Pass 1 (backend/domain/API) and Pass 2 (frontend/PDFs/email/
verification) complete.**

---

## 1. Domain model, and why it is one model

`AdjustmentNote` + `AdjustmentNoteLineItem`, discriminated by
`note_type` (`credit` | `debit`).

Credit and debit notes have identical structure, identical tax handling,
identical numbering mechanics, identical lifecycle and identical delivery
needs. They differ in exactly two ways: the sign of their economic
effect, and whether line-level source limits apply. Two parallel models
would have duplicated roughly ninety percent of the code to express one
enum, and every future change — a PDF tweak, a new status, an analytics
join — would have had to be made twice and kept in sync.

### Why notes are NOT negative invoices

A negative invoice is the tempting shortcut and it is wrong here:

- It corrupts every existing aggregate. `SUM(Invoice.total)` silently
  becomes net rather than gross, with no name change to warn anyone.
- It destroys the distinction between **gross issued revenue** and **net
  adjusted revenue**, which are different questions that different
  metrics need to answer.
- Invoice numbering would have to absorb documents that are not invoices.
- "Was this a sale or a correction?" becomes a sign test rather than a
  type.

So: note lines carry **positive** amounts, the note has its **own**
document number from its **own** sequence, and direction is applied
exactly once, by `signed_total()`. Nothing else in the codebase writes
`-total`.

---

## 2. Source invoice relationship

`source_invoice_id` is **required and immutable**. There are no
standalone notes in this phase.

The only way to create one is
`POST /organizations/{org}/invoices/{invoice_id}/adjustment-notes/{type}`,
and `organization_id`, `customer_id`, `currency_code` and `language` are
all **derived from that invoice server-side**. None of them is accepted
from the request body — the schema does not even have the fields.

That is what makes a cross-tenant or currency-mismatched note
*structurally impossible* rather than merely validated against: there is
no code path that could construct one. A source invoice belonging to
another organization is reported as `404 Invoice not found`, identical to
one that doesn't exist, so the API cannot be used to probe for foreign
invoice ids.

`ON DELETE` is deliberately absent from the FK: an issued note is
financial history about a specific invoice and has no coherent meaning if
its source vanished.

---

## 3. Credit semantics

A credit note **reduces** the economic value of its invoice: returns,
post-invoice discounts, corrections, partial or complete cancellation.

Partial and full credits are both supported. Credit lines **may
reference** the invoice lines they credit, which is what enables
line-level limits and snapshot inheritance.

The source invoice is never deleted, never rewritten, and never
recalculated. It remains the historical record of what was issued.

## 4. Debit semantics

A debit note **increases** the economic value: an omitted charge, an
upward correction, an additional service.

**Debit lines are free-form** (option B from the brief). A debit note adds
a charge that by definition was *not* on the invoice, so a source-line
reference would have nothing to constrain, and permitting one would give
`source_invoice_line_item_id` a second, contradictory meaning. A debit
line carrying a source reference is rejected with
`debit_line_cannot_reference_source`.

Debit lines carry positive amounts. A negative credit note is never used
to express a debit.

---

## 5. Over-credit protection

### The ceiling

```
remaining_creditable = original_invoice_total − Σ issued credit notes
```

**Debit notes do NOT expand the ceiling.** This is the decision the brief
asked to be made explicitly.

A debit note adds a *new* charge. Letting it raise how much of the
*original* sale can be reversed would permit a round trip — debit +500,
then credit −500 against the original — that nets to zero economically
while quietly increasing total reversibility. Tying the ceiling to the
sale itself keeps "how much of this can still be undone" answerable from
the sale alone. The conservative reading is also the auditable one.

### Two levels, both enforced

**Document level:** a note whose total exceeds `remaining_creditable` is
rejected with `over_credit` (HTTP 409), reporting exactly how much
remains.

**Line level:** checking only the total is not enough. A note can sit
inside the document ceiling while crediting one invoice line twice over.
Each referenced line is therefore checked against its own remaining
value, *including other lines in the same note* — so splitting an
over-credit across two lines of one document does not slip through.
Rejected with `line_over_credit`, naming the offending line.

Line usage is tracked **by value, not quantity**: a partial credit may be
a discount on the same quantity ("credit 100 off these 10 units") rather
than a return, and value is the only measure that covers both without
inventing a second unit system.

### Re-checked at issue time

The ceiling is verified **twice**: when the note is created, and again
when it is issued. A note can sit in draft while other notes are issued
against the same invoice, so the ceiling that held at creation may not
hold at issue.

---

## 6. Concurrency

Over-credit protection is **transactional, not an application pre-check**.

`_get_source_invoice_locked()` reads the source invoice with
`SELECT … FOR UPDATE` before computing what remains. Two simultaneous
credit notes against the same invoice serialize there, so the second one
observes the first one's committed effect rather than both reading the
same stale remaining balance and both passing.

A real row lock on PostgreSQL; a no-op on SQLite, which serializes
writers at the file level anyway. Same pattern the existing invoice
numbering uses.

**Verification honesty:** `tests/test_adjustment_notes_concurrency.py`
drives two real threads through a genuine race and asserts that exactly
one succeeds. It **skips unless `TEST_POSTGRES_URL` is set**, because on
SQLite it would pass for the wrong reason and prove nothing about
production. It has **not yet been executed against PostgreSQL** — Docker
would not start in this environment. The deterministic half of the
guarantee (re-check at issue time) is covered by a test that always runs.

---

## 7. Taxes — Phase 28, unchanged

No second tax engine. Notes call the **same** `compute_invoice_totals()`
that invoices and quotes use, so they inherit per-line rates, grouping by
rate, one quantization per group, and `ROUND_HALF_EVEN` — automatically
and permanently.

Note lines reuse `InvoiceLineItem`'s exact shape including `tax_rate`,
which means `app.tax_groups` and `app.pdf_tax_rows` work on notes with no
changes at all.

Mixed-rate notes work identically:

```
1000 @ 22% + 500 @ 10% + 200 @ 0%  ->  subtotal 1700, tax 270, total 1970
```

### Historical snapshots

When a credit line references an invoice line, `description`,
`unit_price` and `tax_rate` are copied **from that invoice line** unless
explicitly overridden — never re-read from `Product.default_tax_rate`.

Changing a product's tax later moves neither the invoice nor any note
that credits it. This is the Phase 28 rule extended one document further
along.

A free-form line with no rate supplied is **exempt**, not inherited:
there is nothing to inherit from, and guessing a rate on a financial
document would be worse than requiring the caller to say.

---

## 8. Numbering

Separate per-organization sequences per type, on `Organization`:
`next_credit_note_number`, `next_debit_note_number`.

- Display: `CN-000001`, `DN-000001`, zero-padded to 6, mirroring
  `INV-`/`QUO-`.
- Prefixes are **English-stable identifiers**. Spanish surfaces label the
  document "Nota de crédito" while still showing `CN-000001`, for the
  same reason `INV-000001` is not translated.
- Notes **never consume invoice numbers**.
- `UNIQUE (organization_id, note_type, note_number)` — so `CN-000001` and
  `DN-000001` coexist in one organization, and numbering never collides
  across tenants.
- Allocated under the **same organization-row lock** that hands out
  invoice numbers, so concurrent creations cannot receive the same number.

---

## 9. Lifecycle and immutability

```
draft ──issue──▶ issued ──void──▶ void
  │
  └──delete──▶ (gone)
```

Modelled on the quote lifecycle — the only document lifecycle this
repository already had. Invoices have none; they are final on creation.

- **draft** — editable, and **economically inert**. Affects nothing:
  not the adjusted total, not receivables, not revenue, not forecasting.
- **issued** — financially immutable and effective. The only status any
  derived figure counts.
- **void** — retained forever, visible in history and audit, economically
  inert again.

`AdjustmentNoteStatus.affects_invoice_economics` is the single predicate;
no analytics module re-spells `status == "issued"`.

**Correcting an issued note means voiding it and issuing another.** There
is no edit path for issued financial fields. Drafts may be deleted
outright (they never affected anything); issued notes may only be voided.
Financial history is never erased.

## 10. Voiding

Implemented, because the lifecycle needed a terminal state that is not
deletion. A voided note:

- remains stored and visible in history and audit;
- stops affecting the adjusted total, receivables, revenue and forecasting;
- **releases the credit ceiling and the line-level allowance it consumed**,
  so a mistaken credit can be undone and reissued correctly.

Voiding is terminal — a void note is never reopened.

---

## 11. Effective invoice value

```
adjusted_total = original_total − Σ issued credits + Σ issued debits
```

**`Invoice.total` is never mutated.** It stays the historical original.
Adjusted values are computed on demand and exposed separately, via
`GET /invoices/{id}/creditability`.

`get_adjusted_totals_by_invoice()` returns the net signed adjustment per
invoice as **one bounded query** — never per-invoice calls in a loop, and
never note arithmetic re-implemented in a consuming module. Invoices with
no issued notes are simply absent from the result, so the common case
costs nothing.

---

## 12. Payment model interaction — stated limitations

This application has **no payment ledger**: no `payments` table, no
partial payments, no amounts received. An invoice has a three-state
`payment_status` and a nullable `paid_at`.

Therefore, honestly:

| Quantity | Available? |
|---|---|
| Original invoice total | Yes — `Invoice.total` |
| Adjusted invoice total | Yes — computed |
| Payment status | Yes — coarse, three states |
| **Exact remaining balance owed** | **No** |

A credit note reduces what is *economically owed*. It does **not** record
a refund, and it cannot mark an invoice partly paid, because the data
model cannot express partial payment. An invoice credited to zero still
reads as `pending` unless someone marks it paid.

Receivables therefore report the **adjusted economic value of unpaid
invoices**, which is a real improvement over face value, but is not the
same as a true outstanding balance. That gap closes only when a payment
ledger exists — deliberately out of scope here.

---

## 13. Analytics semantics

The rule: **one helper, no duplicated arithmetic**, and each metric keeps
meaning what its name says.

| Surface | Adjusted? | Why |
|---|---|---|
| `get_revenue_by_currency` (analytics) | **Yes** | "Revenue" should mean what was actually earned. |
| Monthly revenue series `invoiced` | **Yes** | Forecasting input; see date semantics below. |
| Monthly revenue series `collected` | **No** | Reports cash received. A credit note is not a refund. |
| Receivables snapshot (outstanding + overdue) | **Yes**, floored at zero | A fully credited invoice is worth nothing outstanding, never negative. |
| Customer revenue (`get_customer_revenue_all`) | **No** | Answers "how much has this customer been billed" — the gross question concentration analysis asks. Netting corrections in would change the metric's meaning without changing its name. |

Every adjusted site draws from the same
`get_adjusted_totals_by_invoice()`. Double counting is impossible because
the sign is applied in exactly one place.

### Forecasting date semantics — the decision

**Adjustments land in the SOURCE INVOICE's month, not the note's issue
month.**

This series is the deterministic input to revenue forecasting.
Attributing a correction to the month of the sale it corrects keeps each
month's figure equal to what that month's sales were actually worth.
Issue-month attribution would inject negative spikes into months that had
no such sales, teaching the forecaster a seasonality that does not exist.

Consequence to be aware of: a historical month's reported revenue can
change when a note is issued later. That is correct for a forecasting
input, and is the standard trade-off — the alternative distorts the
model.

### Receivables as-of reconstruction — a known simplification

`get_receivables_snapshot` applies adjustments at their **current** value
rather than reconstructing them as of the requested date. Notes carry
`issued_at`, so a true historical reconstruction is possible later; doing
it here would require the same treatment for every other as-of metric,
which is beyond this phase. Documented rather than hidden.

## 14. AI Financial Advisor

Unchanged by design. The Advisor consumes the deterministic metrics
above, which are already adjusted — so it receives corrected figures
**without performing any note arithmetic itself**, preserving the Phase
24.3 guarantee that the model never computes a financial value.

A note's free-text `reason` is **never** sent to the model, and is not
included in webhook payloads either. The structured context stays
PII-minimal.

---

## 15. API

One unified resource; `?note_type=` filters. Splitting into
`/credit-notes` and `/debit-notes` would have duplicated every endpoint
to express one enum.

| Method | Path | Purpose |
|---|---|---|
| POST | `/invoices/{id}/adjustment-notes/{credit\|debit}` | Create (the only creation path) |
| GET | `/invoices/{id}/creditability` | Ceiling + per-line remaining, for prefill |
| GET | `/invoices/{id}/adjustment-notes` | All notes on one invoice, including drafts and voids |
| GET | `/adjustment-notes` | List, filter by `note_type` / `status`, paginated |
| GET | `/adjustment-notes/{id}` | Detail |
| POST | `/adjustment-notes/{id}/issue` | draft → issued |
| POST | `/adjustment-notes/{id}/void` | issued → void |
| DELETE | `/adjustment-notes/{id}` | Drafts only |

There is **no endpoint that updates financial fields after issuance** —
the capability simply does not exist in the API surface.

Error codes: `over_credit` (409), `line_over_credit` (409),
`note_not_draft` (409), `note_not_issued` (409), `note_already_void`
(409), `source_line_not_on_invoice` (422),
`debit_line_cannot_reference_source` (422), `empty_note` (422).

Over-credit is **409, not 422**: the request is well-formed and conflicts
with current state — and that state can change between two identical
requests, which is exactly what 409 means.

**Public `/api/v1`:** notes are deliberately **not** exposed there yet.
The v1 surface is a stable published contract, and the note API should
settle against a real UI (Pass 2) before being frozen. Nothing in the
design prevents adding it.

## 16. Permissions

Reuses the invoice family. A credit note is an invoice correction, not a
new capability, and someone trusted to issue an invoice is by definition
trusted to correct one.

| Action | Permission |
|---|---|
| read, list, creditability | `invoice.read` |
| create, issue, void, delete draft | `invoice.create` |
| send (Pass 2) | `invoice.send` |

Mutating endpoints additionally require a verified email, matching the
invoice router. Adding `note.*` permissions would have forced every role
definition and test fixture to be revisited for no security gain.

**Plan limits:** note creation is **not** metered and does **not** count
against the invoice quota. Correcting a billing mistake is not a billable
event, and charging for it would create an incentive to leave invoices
wrong. Notes are also not gated behind any plan tier — they are core
financial-document capability.

## 17. Events, audit, webhooks

One canonical path: `emit_event()`. Audit, in-app notification, email
fan-out and webhook delivery all follow from that single call — never
from separate ones.

Events: `adjustment_note.created`, `.issued`, `.voided`, `.sent`
(reserved for Pass 2). One family for both types, distinguished by the
payload's `note_type`, so a subscriber wanting "any adjustment" needs one
subscription rather than two kept in sync.

Payload: `note_id`, `note_type`, `note_number`, `source_invoice_id`,
`organization_id`, `status`, `currency_code`, `subtotal`, `tax_amount`,
`total`. The user's free-text `reason` is **excluded**.

Existing signing, retries, delivery jobs and failure handling are reused
unchanged.

---

## 18. Migration

`_add_adjustment_notes` — purely additive, idempotent, guarded on
table/column existence, in the existing hand-rolled system. No Alembic,
so no downgrade.

Two tables plus two `INTEGER NOT NULL DEFAULT 1` counters on
`organizations`. No existing column is altered and no existing row is
rewritten. Counters start at 1 for every organization including existing
ones — these are new sequences that have never issued a document, so 1 is
simply correct rather than a backfill decision.

Verified by `tests/test_adjustment_notes_migration.py`: clean database,
existing populated database, repeated runs, existing invoice/quote
sequences preserved, and per-type uniqueness allowing `CN-000001` and
`DN-000001` to coexist.

---

## 19. Frontend (Pass 2)

### Entry points

The only way to reach note creation is **Invoice detail → Actions**.
There is no separate "New note" navigation entry and no route that lets
someone create a note without first landing on the invoice it corrects —
matching the backend, which has no standalone-note creation path either.

`frontend/app/(dashboard)/invoices/[id]/page.tsx` is a **new route**:
before Pass 2 the app had no invoice detail page at all, every invoice
action lived as a row action in the list. It hosts the line items,
grouped tax summary (Phase 28), a PDF download action, and the
adjustments panel described below.

### Credit note creation

`frontend/app/(dashboard)/invoices/[id]/notes/new/page.tsx` (mode
`?type=credit`) renders one row per creditable invoice line, seeded from
`GET .../creditability`: description, original amount, tax rate
(inherited, never re-entered), remaining creditable on that line, and an
amount-to-credit input. "Credit full remaining balance" selects every
line with `remaining_creditable > 0` at its full value in one click. A
live totals panel groups by tax rate using the **same** grouping rule the
backend uses when it saves the note, so the number shown while editing
is never a cent away from the number that gets persisted.

Client-side ceiling checks (document total and per line) disable submit
and show an inline message — **a convenience only**. The backend
re-verifies both ceilings inside the row-locked transaction described in
§6 and is the sole source of truth; a 409 from the server is rendered
verbatim, never suppressed because the client also checked.

### Debit note creation

Same page, `?type=debit`. Free-form lines only — nothing to pick from,
matching §4. Uses the Phase 28 tax preset selector unmodified. `min="0"`
on both quantity and price inputs — a debit line is a positive charge,
never a negative-priced trick.

### List

One unified **Credit & Debit Notes** page
(`frontend/app/(dashboard)/notes/page.tsx`), not split by type, for the
same reason the backend API is unified (§15). Columns: number, type
badge, customer, status badge, issue date, total (signed for display
only — see below). Filters for type and status are sent to the API as
query params; free-text search over number/customer is client-side.

### Detail

`frontend/app/(dashboard)/notes/[id]/page.tsx`: type/number/status,
related-invoice link, reason, per-line breakdown, grouped or single tax
summary matching the invoice/PDF layout. Actions are gated by **status**,
mirroring §9: a draft offers Issue and Delete; an issued note offers
Download PDF, Send by email (permission-gated) and Void; a void note is
read-only with an explanatory notice. Void and delete both ask for
confirmation naming the note number.

### Invoice detail integration

`InvoiceAdjustmentsPanel` renders nothing at all when there are no notes
and the viewer cannot create one, so an ordinary invoice is completely
untouched by this feature. When adjustments exist, it shows Original
total / Credit notes / Debit notes / Adjusted total as a small table —
the **original total is never relabelled, restyled, or hidden**, it
stays exactly what the invoice list already shows, with the adjusted
figure appearing as a clearly separate, derived line below it — plus a
list of linked notes, each navigable to its own detail page.

### Status and type badges

`NoteStatusBadge` (draft = slate, issued = emerald, void = muted rose —
void is a deliberate retirement, not an error, so it must not read like
one) and `NoteTypeBadge` (credit = rose, debit = sky, chosen so debit is
never visually confused with "paid"). `signedAmountPrefix()` supplies a
leading `-`/`+` for **display only** — the stored `total` is always
positive, per §1.

---

## 20. PDFs (Pass 2)

`app/adjustment_note_pdf.py` mirrors `app/invoice_pdf.py` structurally
and reuses `app.pdf_tax_rows` (`build_totals_rows`,
`format_rate_percent`, `should_show_line_tax_column`) with **zero**
modification to those helpers — the same Phase 28 tax layout that
renders invoices and quotes renders notes.

Title is `CREDIT NOTE` / `DEBIT NOTE` (`NOTA DE CRÉDITO` / `NOTA DE
DÉBITO` in Spanish). Content: note number, issue date, related invoice
number, organization letterhead, the note's own customer snapshot, an
optional reason section, line items (with a tax column only when rates
actually differ, matching the invoice PDF rule), and the grouped totals
table. A draft note's PDF renders too — an operator needs to review a
note before issuing it.

`tests/test_adjustment_notes_pdf_email.py::test_pdf_never_contains_fiscal_content`
asserts the raw PDF bytes never contain `DGI`, `CFE`, `CAE`, `e-Factura`,
`e-Ticket`, `fiscal QR`, or `electronic signature` — a blunt but
effective automated guard against ever slipping fiscal claims in here by
accident.

## 21. Email (Pass 2)

`send_adjustment_note_email()` reuses the existing `EmailSender`
abstraction, background job architecture, and localized copy —
**no second mail path**. Requires `status == issued`; drafts are not
sendable (`note_not_sendable`, 409). Recipient resolves from the note's
own customer-email snapshot, falling back to the live customer record.
Subject and body are built from the same localization keys the PDF title
uses. On success, `adjustment_note.sent` is emitted through the
canonical `emit_event()` path — no manual duplication of the audit/
notification/webhook fan-out.

If no email provider is configured (this repository's local dev
environment, and any deployment that hasn't set one), the shared
`get_email_sender()` factory raises before this code ever runs, and the
router lets that `503` bubble through unmodified — identical to how
`app.routers.invoices` already handles invoice sending. This is existing
behavior, not something Pass 2 introduced.

## 22. Responsive and live verification (Pass 2)

All new pages checked at 320/375/768/1024/1440/1920 with no horizontal
page overflow; wide content (line tables, note lists) scrolls inside its
own container rather than the page. No regression observed against the
earlier PageContainer/sidebar work or the Phase 28 tax layout.

A full local workflow was run end to end against a real invoice with
mixed rates (1000 @ 22% + 500 @ 10% + 200 @ 0% = subtotal 1700, tax 270,
total 1970):

- Partial credit on one line, "Credit full remaining balance", exact-
  remaining credit, and an over-credit attempt (client-side blocked,
  disabled submit, both per-line and document-level messages shown) were
  all exercised.
- The issued credit note (1220.00) and issued debit note (122.00) both
  produced correctly-typed, forbidden-term-free PDFs.
- The invoice's adjusted-total panel showed `1970.00 − 1220.00 +
  122.00 = 872.00`, with `Invoice.total` unchanged at `1970.00`
  throughout — confirmed again after a full page reload.
- `remaining_creditable` correctly stayed at `750.00` after the debit
  note was issued, confirming debit notes do not expand the ceiling.
- The audit timeline recorded `adjustment_note.created` and
  `adjustment_note.issued` for both notes with the correct actor and
  timestamp; the in-app notification feed showed correctly localized
  copy (e.g. "Debit note issued — DN-000001 was issued for USD 122.00.");
  and matching rows exist in `webhook_events` for both event types.
- A **draft** credit note was created and left unissued: the
  organization's total-revenue figure on the dashboard did not move,
  confirming draft notes are economically inert exactly as §9 specifies.
- Analytics: the dashboard's `TOTAL REVENUE` figure reflected net
  adjusted revenue (`4410.00 gross − 1220.00 + 122.00 = 3312.00`,
  confirmed by direct arithmetic against the three invoices in the test
  organization), matching `get_revenue_by_currency`'s documented
  behavior in §13. The dedicated Financial Dashboard's receivables
  snapshot (`app/financial_intelligence/queries.py`) was confirmed by
  source inspection to also draw from `get_adjusted_totals_by_invoice`
  — not re-exercised live in this pass since it sits behind a paid-plan
  gate this test organization does not have.

**Known, minor, out-of-scope limitation found during this pass:** the
tenant Audit Log page's `Event` and `Resource type` filter dropdowns
were not extended to include `adjustment_note.*` / `adjustment_note` —
the events themselves are recorded correctly and appear in the raw
timeline (confirmed live), they just cannot be isolated via those two
filter controls yet. Does not affect correctness of what is recorded.

## 23. Deferred

**To a future phase:** public `/api/v1` exposure; standalone notes with
no source invoice; a payment ledger (the prerequisite for a true
outstanding balance); as-of historical reconstruction of adjustments in
receivables; IVA/tax reporting built on the tax-group data these notes
already preserve; adjustment-note event/resource types in the tenant
Audit Log's filter dropdowns (see §22).

**To DGI/CFE:** everything fiscal. Uruguayan credit and debit notes are
CFE types 102/103 (e-Ticket) and 112/113 (e-Factura), and DGI's minimum
mandatory set requires them — which is why this phase existed. But
issuing one legally needs XML in DGI's schema, a qualified digital
certificate, a CAE-authorised number from a DGI-registered sequence,
submission and acknowledgement. **None of that is here.** The document
number `CN-000001` is an application identifier, not a fiscal one.
