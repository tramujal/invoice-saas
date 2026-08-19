# Taxes and tax identifiers (Phase 28)

> **This does NOT make Invoicing DGI/CFE compliant.** Nothing here issues
> a legally valid electronic tax document in Uruguay. There is no CFE, no
> e-Factura, no e-Ticket, no CAE, no XML, no digital signature, no DGI
> submission, and no fiscal QR. The documents this application produces
> remain ordinary application documents. See
> `docs/competitive_analysis_uruguay.md` for what legal issuance would
> actually require.
>
> What this phase provides is the *foundation* those things would need:
> a document that can represent mixed tax rates correctly, and a tax
> identifier that is structurally validated.

---

## 1. The per-line tax model

### What changed

Before Phase 28, tax was a single rate applied to the whole document.
That cannot represent an ordinary Uruguayan invoice:

```
Servicio A   1.000    IVA 22%
Producto B     500    IVA 10%
Servicio C     200    Exento
```

Now every line carries its own rate.

| | Before | After |
|---|---|---|
| `invoice_line_items.tax_rate` | did not exist | `NUMERIC(5,4)`, NOT NULL, default 0 |
| `quote_line_items.tax_rate` | did not exist | `NUMERIC(5,4)`, NOT NULL, default 0 |
| `quotes.tax_rate` | document rate | **kept** — see §6 |
| `invoices.tax_rate` | **never existed** | still does not exist |

Invoices never had a document-level rate column: they store only
`tax_amount`. That asymmetry shaped the migration (§4).

### Semantics: default vs snapshot

Two different things, deliberately kept apart:

- **`Product.default_tax_rate` is a PREFILL.** It seeds a new line when
  that product is added. Nothing reads it afterward.
- **`InvoiceLineItem.tax_rate` / `QuoteLineItem.tax_rate` are HISTORICAL
  SNAPSHOTS.** They record what applied when the document was issued.

Consequences, all covered by tests:

- Editing a line's tax never modifies the product.
- Changing a product's `default_tax_rate` never alters an already-issued
  document — not its rate, not its tax, not its total.
- A line that inherited the request's document-level rate persists that
  concrete number, so an invoice always describes its own tax even
  though invoices have no rate column.

---

## 2. Calculation and rounding

One function, `app.services.invoices.compute_invoice_totals`, used by
both invoices and quotes.

```
line_total = quantize(quantity × unit_price)      # per line, NET of tax
subtotal   = quantize(Σ line_total)

# grouped by rate:
group_base = Σ line_total of lines sharing a rate
group_tax  = quantize(group_base × rate)

tax_amount = quantize(Σ group_tax)
total      = quantize(subtotal + tax_amount)
```

**Rounding happens per TAX-RATE GROUP, not per line.** This is the
load-bearing decision of the whole phase, for two reasons:

1. **Backwards compatibility.** For a single-rate document the formula
   reduces to `quantize(subtotal × rate)` — character for character the
   pre-Phase-28 computation. No historical document can shift by a cent.
   Rounding per line would *not* be equivalent: two `0.05` lines at 10%
   give `0.02` line-by-line but `0.01` document-wide.
2. **It is the conventional fiscal model.** Tax is assessed on each
   taxable base, which is exactly what the grouped summary displays.

**Rounding mode is `ROUND_HALF_EVEN`** (Python's `Decimal` context
default), inherited unchanged from `_quantize_money`. So `83.325`
becomes `83.32`, not `83.33`. Phase 28 did not change this; a test pins
it so any future change is a visible decision.

All money is `Decimal`/`NUMERIC`. No floats anywhere in the calculation.

---

## 3. Mixed-tax presentation

`TaxGroup(rate, base, tax)` — computed, never stored — is exposed as
`tax_groups` on invoice and quote responses, and derived on the models
from the line snapshots.

Each group carries its **taxable base**, not just the tax. That is what
lets a 0% group be shown honestly:

```
Subtotal                        2.200,00
IVA 22%  (base 1.000,00)          220,00
IVA 10%  (base 1.000,00)          100,00
Exento   (base 200,00)              0,00
Total IVA                         320,00
Total                           2.520,00
```

An exempt group is labelled **"Exento" / "Exempt"**, never "Tax 0%": no
tax was applied to those lines, and a `0,00` in a tax column would imply
otherwise.

A single-rate document renders the plain `Subtotal / Tax / Total` it
always did — the breakdown appears only when it carries information.

---

## 4. Migration and backfill

`app.schema_migrations._add_line_item_tax_rates`, idempotent and guarded
on column existence like every other migration in this project. There is
no Alembic here and **no downgrade concept**, so none is provided.

**No stored total is ever touched.** Totals are recomputed only when a
document is *edited*; reads return stored columns. The backfill only
decides what a future edit would recompute from.

| Table | Backfill | Exactness |
|---|---|---|
| `quote_line_items` | inherit the parent quote's `tax_rate` | exact by definition |
| `invoice_line_items` | `ROUND(tax_amount * 1.0 / subtotal, 4)` | exact for every real rate |
| either, when `subtotal = 0` | `0` | a rate is undefined with nothing to apply it to |

**The `* 1.0` is not cosmetic.** SQLite gives `NUMERIC` columns integer
affinity, so a subtotal stored as `1000.00` becomes the integer `1000`
and `tax_amount / subtotal` performs *integer division* — `220 / 1000 =
0`, silently backfilling every rate as zero. This was caught by
`tests/test_line_item_tax_migration.py` before it could reach anything.

Verified on the real development database: 45 existing invoices, rates
recovered as 0.22 / 0.10 / 0, and every one recomputes to its stored tax
exactly.

---

## 5. API compatibility

The invoice/quote schemas are shared verbatim with the public
`/api/v1` surface, so all of this applies to both.

**Additive only. Nothing was removed or renamed.**

Requests:

```jsonc
{
  "tax_rate": "0.22",              // document-level: STILL SUPPORTED
  "line_items": [
    { "description": "A", "quantity": "1", "unit_price": "1000.00" },
    // no tax_rate -> inherits the document rate above
    { "description": "B", "quantity": "1", "unit_price": "500.00",
      "tax_rate": "0.10" }          // per-line: NEW, optional
  ]
}
```

The rule: **`tax_rate` absent on a line means "inherit the document
rate".** An existing client that has never heard of per-line tax keeps
sending only the document rate and keeps getting byte-identical results.

`null`/absent is **not** the same as `0`. An explicit `0` means "this
line is genuinely exempt" and overrides the document rate.

Responses gain `line_items[].tax_rate` and `tax_groups[]`. Every
pre-existing field is unchanged.

**Deprecation:** the document-level `tax_rate` is *not* deprecated and
has no removal date. It remains the documented compatibility path, and
for quotes it is still persisted. `PATCH` on a quote with only
`tax_rate` (no `line_items`) re-stamps every line with that rate —
exactly what it did before per-line tax existed.

---

## 6. Why `quotes.tax_rate` was kept

Option (C), "migrate and remove", was rejected: it is a live field on a
public API response, it still has a defined meaning (the rate applied
when no per-line value is given), and removing it would break clients
for no functional gain. Option (A), keep temporarily, is what happened
in practice — but with no deprecation timer, because there is nothing
to deprecate. Invoices needed no such decision, having never had the
column.

---

## 7. Uruguayan RUT

### Two separate responsibilities

```
normalize_tax_id(value)      -> canonical COMPARISON key
                                (country-agnostic, never rejects)
validate_uruguay_rut(value)  -> is this a structurally valid RUT?
                                (Uruguay-specific, never rewrites)
```

`app/uruguay_rut.py` holds the second; `app/customer_validation.py`
keeps the first. Neither reimplements the other.

### Format and algorithm

12 digits: `NN NNNNNN NNN D` — 2 office, 6 taxpayer, 3 dependency, 1
check digit. The check digit is modulus 11 over the first 11 digits with
weights `[4,3,2,9,8,7,6,5,4,3,2]` applied left to right; the expected
digit is `(11 - (sum % 11)) % 11`.

Corroborated by two independent public sources and verified against a
**publicly listed** RUT (Antel, `21-100342-001-7`): weighted sum 70,
`70 % 11 = 4`, `11 - 4 = 7` ✓. No customer or production identifier was
used anywhere, in code or tests.

This is a *structural* check only. A RUT that passes may still not
exist; verifying existence would require DGI, which is out of scope.

### When validation applies

Deliberately narrow, so adding validation cannot start rejecting
existing international customers. Validate when **either**:

1. the user explicitly wrote a `RUT` label in the value, **or**
2. the organization's own `tax_label` says RUT **and** the value is
   entirely digits.

Everything else is a generic international tax identifier, stored
exactly as before with no validation whatsoever.

`Organization.tax_label` already exists to express "what is the tax
identifier called here", so it is reused as the country signal rather
than adding a `country`/`tax_id_type` column that would duplicate
information the model already carries. An organization needing numeric
identifiers from several countries simply labels the field something
else — which is what that field is for.

**Known limitation:** in a RUT-labelled organization, a numeric
identifier from another country (an Argentine CUIT, say) would be
rejected as an invalid RUT. The escape hatch is the tax label. A
mistyped RUT that happens to satisfy the check digit still passes —
inherent to any checksum.

### Ordering: validity before duplication

An invalid RUT raises `InvalidUruguayRutError` (**HTTP 422** — a
malformed field) *before* any duplicate lookup runs. Reporting
"duplicate tax id" for a value that isn't even a valid RUT would be
actively misleading, and the fixed order keeps the outcome deterministic
rather than dependent on what happens to be in the table. Duplicates
remain **HTTP 409** with `duplicate_tax_id`, unchanged.

The frontend translates the error code (`El RUT ingresado no es válido.`
/ `The RUT entered is not valid.`) and never exposes checksum mechanics.

### Bug fixed along the way

`normalize_tax_id` documented that `"RUT 12.345.678-9"` and
`"123456789"` must normalize identically — but it only stripped
punctuation, producing `"rut123456789"` vs `"123456789"`. They did not
collide, so the same taxpayer could be created twice. The label token is
now stripped first. Other alphanumeric identifiers (a Spanish CIF
`B12345678`) are untouched.

### Import

Customer CSV/XLSX import applies the same rule and the same ordering,
via the organization's `tax_label`. An invalid RUT is a row-level
`invalid_rut` error, distinct from `duplicate_tax_id`. A caller that
passes no `tax_label` gets the exact pre-Phase-28 behavior.

### Organization vs customer

`Organization.tax_id` (the issuer's own identifier) and
`Customer.tax_id` are different business concepts and remain separate
columns. This phase did not conflate them and did not change the
organization side.

---

## 8. What analytics had to change: nothing

Financial Intelligence, forecasting, receivables and the AI context all
consume `Invoice.subtotal` / `tax_amount` / `total`, which keep their
exact previous meanings — `line_total` is still net of tax. No analytics
code duplicates tax calculation, and none needed updating.

---

## 9. Deferred to later phases

- **Credit and debit notes** — required by DGI's minimum mandatory set, and the natural next phase. Nothing here models a document that references and reverses another.
- **CFE / DGI** — see the warning at the top.
- **Tax reports / IVA returns** — the data now exists to build them; the reports do not.
- **Withholding, surcharges, per-line discounts, tax-inclusive pricing** — no support, and none implied.
