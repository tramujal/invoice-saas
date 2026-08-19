"""Shared tax presentation for the invoice and quote PDFs (Phase 28).

Both documents render taxes identically -- a quote and the invoice it
converts into must not disagree about how a total was reached -- so the
logic lives here once instead of being copy-pasted into two renderers
that could drift.

Contains no CFE/DGI/fiscal-authority concepts of any kind. These remain
ordinary application documents.
"""

from decimal import Decimal

from app.currency import format_amount
from app.localization import t
from app.tax_groups import TaxGroup


def format_rate_percent(rate: Decimal) -> str:
    """"0.22" -> "22%", "0.105" -> "10.5%". Trailing zeros are trimmed so
    the common whole-number rates read cleanly rather than as "22.00%"."""
    percent = (Decimal(rate) * 100).normalize()
    # normalize() renders small integers in scientific notation
    # ("1E+1"); quantizing to an integer first avoids that for the whole-
    # percent rates that make up essentially all real usage.
    if percent == percent.to_integral_value():
        return f"{int(percent)}%"
    return f"{percent}%"


def tax_group_label(group: TaxGroup, language: str) -> str:
    """The label for one tax bucket.

    A 0% bucket is labelled "Exempt"/"Exento" rather than "Tax 0%": those
    lines had no tax applied, and presenting them as a tax that happened
    to be zero would misrepresent what occurred.

    Every label carries its taxable base, because a bare "0.00" in an
    amount column is exactly the ambiguity this is meant to remove -- the
    reader can see WHAT was taxed at each rate, not just the result.
    """
    if group.rate == 0:
        return t(language, "tax_exempt_label")
    return f"{t(language, 'tax_amount_label')} {format_rate_percent(group.rate)}"


def build_totals_rows(
    *,
    subtotal: Decimal,
    tax_amount: Decimal,
    total: Decimal,
    tax_groups: list[TaxGroup],
    language: str,
    currency_code: str,
) -> list[list[str]]:
    """The rows of a document's totals table.

    A single-rate document (which is every pre-Phase-28 document, and
    still the common case) renders EXACTLY the three rows it always did
    -- Subtotal / Tax / Total -- so existing PDFs are unchanged. The
    per-rate breakdown appears only when a document actually mixes rates
    and the reader therefore needs it.
    """
    rows = [[t(language, "subtotal_label"), format_amount(subtotal, currency_code)]]

    if len(tax_groups) > 1:
        for group in tax_groups:
            rows.append(
                [
                    f"{tax_group_label(group, language)} "
                    f"({t(language, 'tax_base_label')} {format_amount(group.base, currency_code)})",
                    format_amount(group.tax, currency_code),
                ]
            )
    else:
        rows.append([t(language, "tax_amount_label"), format_amount(tax_amount, currency_code)])

    rows.append([t(language, "total_label"), format_amount(total, currency_code)])
    return rows


def should_show_line_tax_column(tax_groups: list[TaxGroup]) -> bool:
    """Per-line tax is shown only when the document mixes rates.

    On a single-rate document the column would repeat the same value on
    every row while stealing width from the description -- and it would
    change the layout of every historical invoice for no informational
    gain.
    """
    return len(tax_groups) > 1
