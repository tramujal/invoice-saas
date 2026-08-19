"""Render a credit or debit note as a printable PDF (Phase 29).

Deliberately mirrors app.invoice_pdf's structure and reuses Phase 28's
app.pdf_tax_rows wholesale -- the per-line tax column and the grouped
totals table are IDENTICAL to an invoice's, because a note's tax is
computed identically. No tax layout logic is duplicated here.

CONTAINS NO FISCAL CONTENT. There is no DGI branding, no CFE
terminology, no CAE, no fiscal QR, and no claim that this is a legally
valid electronic document. The note number (CN-000001) is an application
identifier. See docs/credit_debit_notes.md.
"""

from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.adjustment_note_type import AdjustmentNoteType
from app.currency import format_amount, get_currency_code
from app.invoice_numbering import format_invoice_number
from app.localization import get_language, t
from app.models import AdjustmentNote
from app.pdf_tax_rows import build_totals_rows, format_rate_percent, should_show_line_tax_column


def _money(value) -> str:
    """Bare amount for the narrow line-items columns -- same convention as
    the invoice PDF, where repeating the currency code per row risks
    wrapping."""
    return f"{value:,.2f}"


def _format_quantity(value) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text if text else "0"


def render_adjustment_note_pdf(note: AdjustmentNote) -> bytes:
    # Language and currency come from the NOTE's own pinned fields, never
    # the organization's current settings -- so this document renders the
    # same years from now, exactly like an invoice.
    organization = note.organization
    language = get_language(note)
    currency_code = get_currency_code(note)
    note_type = AdjustmentNoteType(note.note_type)
    title_key = "credit_note_title" if note_type is AdjustmentNoteType.credit else "debit_note_title"
    title = t(language, title_key)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        title=f"{title} {note.formatted_number}",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("NoteTitle", parent=styles["Title"], alignment=0, fontSize=20)
    heading_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading3"],
        textColor=colors.HexColor("#475569"),
        fontSize=10,
        spaceAfter=4,
    )
    normal_style = styles["Normal"]

    elements: list = []
    elements.append(Paragraph(title, title_style))
    elements.append(Spacer(1, 4))

    meta_rows = [
        [t(language, "note_no_label"), note.formatted_number],
        [
            t(language, "related_invoice_label"),
            format_invoice_number(note.source_invoice.invoice_number),
        ],
        [
            t(language, "created_label"),
            note.issue_date.strftime("%B %d, %Y")
            if note.issue_date is not None
            else note.created_at.strftime("%B %d, %Y"),
        ],
    ]
    meta_table = Table(meta_rows, colWidths=[1.6 * inch, 4.4 * inch])
    meta_table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#64748b")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    elements.append(meta_table)
    elements.append(Spacer(1, 16))

    elements.append(Paragraph(t(language, "from_label").upper(), heading_style))
    from_lines = [organization.business_name or organization.name]
    if organization.tax_id:
        from_lines.append(f"{organization.tax_label or 'Tax ID'}: {organization.tax_id}")
    for value in (organization.address, organization.phone, organization.email):
        if value:
            from_lines.append(value)
    for line in from_lines:
        elements.append(Paragraph(line, normal_style))
    elements.append(Spacer(1, 20))

    elements.append(Paragraph(t(language, "bill_to_label").upper(), heading_style))
    # The note's own snapshot, forwarded from the invoice at creation --
    # editing the customer afterward never changes an issued document.
    customer_lines = [
        note.customer_name_snapshot,
        note.customer_email_snapshot,
        note.customer_phone_snapshot,
        note.customer_address_snapshot,
    ]
    if any(customer_lines):
        for line in customer_lines:
            if line:
                elements.append(Paragraph(line, normal_style))
    else:
        elements.append(Paragraph(t(language, "no_customer"), normal_style))
    elements.append(Spacer(1, 16))

    if note.reason:
        elements.append(Paragraph(t(language, "note_reason_label").upper(), heading_style))
        elements.append(Paragraph(note.reason, normal_style))
        elements.append(Spacer(1, 16))

    # --- lines: identical treatment to the invoice PDF ------------------
    tax_groups = note.tax_groups
    show_tax_column = should_show_line_tax_column(tax_groups)

    header = [
        t(language, "line_description_label"),
        t(language, "line_quantity_label"),
        t(language, "line_unit_price_label"),
    ]
    if show_tax_column:
        header.append(t(language, "tax_amount_label"))
    header.append(t(language, "line_total_label"))
    rows = [header]

    for item in note.line_items:
        row = [item.description, _format_quantity(item.quantity), _money(item.unit_price)]
        if show_tax_column:
            row.append(
                t(language, "tax_exempt_label")
                if item.tax_rate == 0
                else format_rate_percent(item.tax_rate)
            )
        row.append(_money(item.line_total))
        rows.append(row)

    col_widths = (
        [2.5 * inch, 0.8 * inch, 1.0 * inch, 0.9 * inch, 1.1 * inch]
        if show_tax_column
        else [3.2 * inch, 0.9 * inch, 1.1 * inch, 1.1 * inch]
    )
    items_table = Table(rows, colWidths=col_widths, repeatRows=1)
    items_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#334155")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    elements.append(items_table)
    elements.append(Spacer(1, 16))

    # Phase 28's shared builder -- single-rate notes render the plain
    # three-row summary, mixed-rate notes get the per-rate breakdown.
    totals_table = Table(
        build_totals_rows(
            subtotal=note.subtotal,
            tax_amount=note.tax_amount,
            total=note.total,
            tax_groups=tax_groups,
            language=language,
            currency_code=currency_code,
        ),
        colWidths=[4.9 * inch, 1.4 * inch],
    )
    totals_table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, -1), (-1, -1), 11),
                ("LINEABOVE", (0, -1), (-1, -1), 0.75, colors.HexColor("#94a3b8")),
                ("TOPPADDING", (0, -1), (-1, -1), 8),
            ]
        )
    )
    elements.append(totals_table)

    doc.build(elements)
    return buffer.getvalue()
