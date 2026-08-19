"""Grouping a document's lines by tax rate -- the single source of truth
for "how was this total actually arrived at" (Phase 28).

Deliberately a leaf module with no app imports of its own: both
app.models (as a computed property on Invoice/Quote) and
app.services.invoices (when computing totals for a write) need it, and
putting it here is what keeps models -> services -> models from becoming
a cycle.

There are two callers with two different inputs, which is why the
grouping function takes anything with `.line_total` and `.tax_rate`
rather than a concrete type:

  - persisted ORM rows, when serializing an existing document
  - request line items, when computing totals for a create/update

Both must produce identical groups for identical numbers, so they share
this one implementation rather than each rolling their own.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

# Rates are stored as Numeric(5, 4); quantizing group keys to the same
# scale means Decimal("0.22") and Decimal("0.2200") land in one bucket
# instead of rendering as two identical-looking 22% rows.
RATE_EXPONENT = Decimal("0.0001")
MONEY_EXPONENT = Decimal("0.01")


@dataclass(frozen=True)
class TaxGroup:
    """`base` is the net amount taxed at `rate`; `tax` is what that
    produced. Carrying the base is what lets a 0% group be presented
    honestly -- "Exento, base 200" rather than a row reading "0.00" that
    reads as tax collected and rounded away."""

    rate: Decimal
    base: Decimal
    tax: Decimal


class _TaxableLine(Protocol):
    line_total: Decimal
    tax_rate: Decimal


def group_lines_by_tax_rate(lines: "list[_TaxableLine]") -> list[TaxGroup]:
    """Groups already-computed line totals by their own tax rate.

    Tax is quantized once per group, never per line -- see
    app.services.invoices.compute_invoice_totals for why that choice is
    what keeps every pre-Phase-28 document's total unchanged.

    Sorted by rate descending so the headline rate reads first and exempt
    lines sit at the bottom, deterministically, regardless of the order
    the lines happen to be in.
    """
    bases: dict[Decimal, Decimal] = {}
    for line in lines:
        rate = Decimal(line.tax_rate or 0).quantize(RATE_EXPONENT)
        bases[rate] = bases.get(rate, Decimal("0")) + Decimal(line.line_total)

    return [
        TaxGroup(
            rate=rate,
            base=base.quantize(MONEY_EXPONENT),
            tax=(base * rate).quantize(MONEY_EXPONENT),
        )
        for rate, base in sorted(bases.items(), key=lambda kv: kv[0], reverse=True)
    ]
