# Customer duplicate detection (Phase UX5)

## Why this exists

Production testing found that the app let a user create multiple customers with identical tax IDs, emails, phone numbers, or names, with zero warning. This causes split invoice/quote history, confused billing, and wasted support time reconciling "which Juan Pérez is this?" after the fact.

This feature adds tiered, per-organization duplicate detection to customer create, edit, and CSV/XLSX import — without redesigning the customer module, without a database-level unique constraint, and without making email globally unique (legitimate cases like family businesses, accounting firms, and shared corporate inboxes routinely reuse the same email across customers).

## The four levels

| Level | Field | Confidence | Behavior |
|---|---|---|---|
| 1 | Tax ID (RUT/RUC/NIT/CUIT/CNPJ/...) | High | **Blocks** creation/edit. Enforced both in the advisory `check-duplicates` endpoint and, unconditionally, server-side in `create_customer_record`/`update_customer_record` — the backend never trusts that the frontend called the check first. |
| 2 | Email | Medium | **Warns**. A confirmation dialog offers "Open existing customer," "Create anyway," or "Cancel" — default focus is always Cancel, never "Create anyway." |
| 3 | Phone | Medium | **Warns**, same dialog as email, never blocks. |
| 4 | Name | Low | **Suggests only**. A small inline hint, never a modal, never a confirmation, never blocks. |

### Why tax ID blocks

A tax ID is a government-issued identifier. Two customers legitimately sharing one inside the same organization is a data-entry mistake essentially 100% of the time (as opposed to, say, a franchise with the same tax ID across *different* organizations, which is a completely different customer and is never compared — see "Tenant isolation" below). Blocking is the right default; there is no "create anyway" for this level.

### Why email and phone only warn

Real businesses legitimately reuse an email or phone across multiple customer records: a family business with one contact for several accounts, an accounting firm that's the point of contact for many clients, a shared corporate inbox, or one company with several billing contacts. Blocking here would actively get in the way of real workflows, so the app warns and requires an explicit, deliberate "Create anyway" instead of silently allowing or silently blocking.

### Why name only suggests

Two different people or companies can plainly share a name ("María González" is not a rare name). A name match is the weakest possible signal, so it never interrupts the flow — the same principle behind explicitly *not* doing fuzzy/typo-tolerant matching (no edit-distance, no phonetic matching) anywhere in this feature: name comparison is a cheap, exact, whitespace/case-insensitive check, nothing more.

## Normalization rules

All normalization lives in `app/customer_validation.py` — the single source of truth reused by the CRUD endpoints, the duplicate-check endpoint, and the CSV/XLSX importer. Nothing else re-implements it.

- **Tax ID** (`normalize_tax_id`, pre-existing): strips spaces/dots/hyphens/slashes, strips accents, lowercases. `"RUT 12.345.678-9"` and `"123456789"` compare equal.
- **Email** (`normalize_customer_email`, pre-existing): trim + lowercase.
- **Phone** (`normalize_customer_phone`, new): strips spaces/parentheses/dashes, folds a leading `"00"` international prefix to `"+"`. `"+598 99 123 456"`, `"(598) 99-123-456"` compare equal. Does **not** attempt to infer a missing country code — `"99123456"` and `"+59899123456"` intentionally do not match, since guessing would be exactly the fuzzy matching this feature avoids.
- **Name** (`normalize_customer_name`, new): trim + collapse repeated whitespace + lowercase.

None of these rewrite the persisted value — a customer's tax ID, email, phone, and name are always stored exactly as typed. Normalization only ever affects *comparison*.

## API

`POST /organizations/{organization_id}/customers/check-duplicates`

Request:

```json
{
  "name": "Juan Pérez",
  "email": "juan@example.com",
  "phone": "+598 99 123 456",
  "tax_id": "",
  "exclude_customer_id": null
}
```

An empty string for any field means "don't check this field" — used by the edit flow to skip fields the user hasn't actually changed (see "Edit flow" below).

Response:

```json
{
  "severity": "warning",
  "matches": [
    {
      "customer_id": "...",
      "customer_name": "Juan Pérez",
      "email": "juan@example.com",
      "phone": "59899123456",
      "tax_id": "217654320019",
      "reasons": ["email"]
    }
  ]
}
```

`severity` is `none | suggestion | warning | blocking` — the maximum severity across every match found. A single match can carry more than one reason (e.g. `["email", "phone"]`).

Permission: `customer.read` (read-only lookup; it mutates nothing and returns nothing a `customer.read` holder couldn't already see via `GET .../customers`). Tenant-isolated: the query is always scoped to `organization_id`, so this endpoint can never return another organization's customer.

Tax ID blocking is *also* enforced directly inside `POST /customers` and `PATCH /customers/{id}`: a colliding tax ID returns `409 {"detail": {"code": "duplicate_tax_id", "message": "This tax identification number already belongs to another customer.", "customer_id": ..., "customer_name": ...}}`, mirroring the existing `plan_limit_reached` 409 shape.

## Creation & edit flow

On submit, the frontend calls `check-duplicates` first:

- **none** → create/save immediately.
- **suggestion** → show a small inline hint, create/save immediately anyway (never gated).
- **warning** → open the confirmation dialog; only create/save if the user explicitly picks "Create anyway" (never the default focus/action).
- **blocking** → open a dialog with only "Open existing customer" and "Cancel" — there is no bypass.

**Edit flow** applies the identical rules, with two differences: `exclude_customer_id` is always the customer being edited (so it never matches itself), and any field whose value is unchanged from the original customer is sent as an empty string to `check-duplicates` — the endpoint treats blank as "skip," so editing one field never re-surfaces a warning about a pre-existing collision on a field you didn't touch.

**"Create anyway"** on a warning re-submits the create/update request with `duplicate_warning_acknowledged: true`. This never bypasses the tax ID block (there's nothing to bypass — warnings only ever come from email/phone/name) and is recorded on the emitted event's payload (audit log / webhook / notification), never on the persisted customer row itself.

## Import (CSV/XLSX)

Already-existing import logic (`app/imports/customers.py`) detects tax ID and email duplicates against both the database and rows already seen earlier in the same file, and reports them as `duplicate` — skipped at confirm time, never silently imported. This phase adds `duplicate_customer_id` to each preview/confirm row so the UI can show *which* existing customer a row collided with (`null` for an in-file-only collision, since there's no real customer yet to link to — just another pending row).

Phone- and name-level detection is **deliberately not extended to import**: a bulk import has no per-row interactive dialog to show a warning or suggestion in, so extending the weaker levels there would mean either silently skipping rows on a low-confidence signal (wrong) or silently ignoring the signal entirely (no value added). Tax ID and email are the two levels where "skip and report" is the correct default even without a human in the loop for each row, so import keeps exactly the behavior it already had for those two.

## Migration strategy for historical duplicates

No database migration and no schema change ships with this phase — `Customer.tax_id`/`Customer.email` remain non-unique at the database level, exactly as before (see the existing comment on `Customer.tax_id` in `app/models.py`, which already documented this as a deliberate, application-level-only concern). Concretely:

- Existing duplicate tax IDs, emails, phones, or names are **never touched, flagged, or hidden**. Every historical customer record stays exactly as it is.
- **New** customer creation/edits are blocked (tax ID) or warned (email/phone) going forward.
- `python -m app.scripts.find_duplicate_tax_ids [--organization-id <id>]` is a **read-only** CLI (mirrors `app.scripts.grant_platform_role`'s shape) an operator can run to find organizations with pre-existing duplicate tax IDs, for manual review. It never modifies data.
- Customer *merging* is explicitly out of scope for this phase — if manual cleanup is needed after running the audit script, it happens by hand (or in a future phase) via the existing edit/delete endpoints, not by this feature.

## Performance

- One bounded, single query per `check-duplicates` call: `SELECT id, name, email, phone, tax_id FROM customers WHERE organization_id = :id [AND id != :exclude_id]`, scoped and indexed by `organization_id` (its existing foreign-key index) — no `LIKE '%...%'`, no full table scan, no N+1. This mirrors the exact shape the CSV importer's pre-existing `fetch_existing_keys` already uses for the same reason.
- Normalization comparison happens in Python, not SQL — required anyway, since normalization strips formatting (`.`, `-`, spaces, accents) that a plain-equality `WHERE` clause on the raw stored column can't account for without a functional/generated-column index. No such index is introduced in this phase: per-organization customer counts are already bounded by plan limits, so a single indexed-by-org scan is proportionate today.
- **Future optimization path** (not needed now, documented for when it is): if per-organization customer counts ever grow far beyond current plan limits, the next step would be a normalized, indexed lookup column (e.g. a generated `tax_id_normalized` column with its own index) rather than scanning every row in Python — call this out explicitly if that day comes, since it's a real schema change this phase deliberately avoided.
- The tax-id-only server-side check (`find_tax_id_duplicate`, used by `create_customer_record`/`update_customer_record`) issues **no query at all** when `tax_id` is blank — the common case, since most customers don't have one filled in.

## Security

- Every query in `app.customer_duplicates` is scoped to a single `organization_id` — tax IDs, emails, phones, and names are **never** compared across organizations, and a match can never leak another tenant's customer.
- `check-duplicates` requires `Permission.customer_read`; the tax-id block inside create/update is enforced unconditionally regardless of any client-side check, matching how every other write endpoint in this app never trusts the frontend alone.
- The 403/404-shaped tenant-isolation guarantees already covered elsewhere in the app (`tests/tenants/test_cross_org_isolation.py`) apply identically to the new endpoint — a foreign organization's member gets `403`, never a `200` or `404` that would leak whether a colliding customer exists.

## Known limitations

- **No customer merging.** Explicitly out of scope for this phase, per the original spec.
- **A true race condition remains possible**: two simultaneous requests creating the same tax ID can both pass the pre-check before either commits, since there is no database-level unique constraint (the spec explicitly prohibits adding one without a separate audit). In practice this is a narrow window on a rare event (two users entering the same tax ID at the same instant); documented here rather than solved, since closing it fully would require exactly the breaking constraint change this phase was told not to introduce.
- **Import duplicate detection does not cover phone or name** — see "Import (CSV/XLSX)" above for why.
- **Notification/webhook/audit event copy for customer events is not localized** (a pre-existing, unrelated condition — `app/notifications/copy.py` renders in English regardless of organization language). `duplicate_warning_acknowledged` is added to that same English-only payload; not a regression introduced by this feature, just an existing limitation it inherits.
