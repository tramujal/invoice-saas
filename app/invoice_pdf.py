"""Render an Invoice as a printable PDF."""

from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

from app.currency import format_amount, get_currency_code
from app.invoice_numbering import format_invoice_number
from app.localization import get_language, payment_status_label, t
from app.models import Invoice
from app.pdf_tax_rows import (
    build_totals_rows,
    format_rate_percent,
    should_show_line_tax_column,
)


def _money(value) -> str:
    """Bare, unprefixed amount for the line-items table — its columns are
    narrow (1.1in), and repeating the currency code on every row there risks
    wrapping. The totals table (more room, and the figures that matter most)
    gets the currency-prefixed format instead."""
    return f"{value:,.2f}"


def _format_quantity(value) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text if text else "0"


def render_invoice_pdf(invoice: Invoice) -> bytes:
    # Permanently pinned on the invoice itself (see Invoice.currency_code /
    # Invoice.language) — never re-derived from the organization's current
    # settings, so this PDF looks the same today as it will years from now
    # even if the organization's defaults change in the meantime.
    organization = invoice.organization
    language = get_language(invoice)
    currency_code = get_currency_code(invoice)
    invoice_number = format_invoice_number(invoice.invoice_number)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        title=f"{t(language, 'invoice_title')} {invoice_number}",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "InvoiceTitle", parent=styles["Title"], alignment=0, fontSize=20
    )
    heading_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading3"],
        textColor=colors.HexColor("#475569"),
        fontSize=10,
        spaceAfter=4,
    )
    normal_style = styles["Normal"]

    elements: list = []

    elements.append(Paragraph(t(language, "invoice_title"), title_style))
    elements.append(Spacer(1, 4))

    # The effective status (derived from due_date, not the raw stored
    # value) -- the same source of truth every other surface displays.
    # See Invoice.effective_payment_status / app.effective_status.
    status_label = payment_status_label(language, invoice.effective_payment_status)

    if invoice.due_date is None:
        payment_terms_label = t(language, "payment_terms_none")
        due_date_text = t(language, "payment_terms_none")
    else:
        due_date_text = invoice.due_date.strftime("%B %d, %Y")
        terms_days = (invoice.due_date - invoice.created_at.date()).days
        payment_terms_label = (
            t(language, "payment_terms_on_receipt")
            if terms_days <= 0
            else t(language, "payment_terms_net_days").format(days=terms_days)
        )

    meta_table = Table(
        [
            [t(language, "invoice_no_label"), invoice_number],
            [t(language, "created_label"), invoice.created_at.strftime("%B %d, %Y")],
            [t(language, "due_date_label"), due_date_text],
            [t(language, "payment_terms_label"), payment_terms_label],
            [t(language, "payment_status_label"), status_label],
        ],
        colWidths=[1.4 * inch, 4.6 * inch],
    )
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
        tax_label = organization.tax_label or "Tax ID"
        from_lines.append(f"{tax_label}: {organization.tax_id}")
    if organization.address:
        from_lines.append(organization.address)
    if organization.phone:
        from_lines.append(organization.phone)
    if organization.email:
        from_lines.append(organization.email)
    for line in from_lines:
        elements.append(Paragraph(line, normal_style))
    elements.append(Spacer(1, 20))

    elements.append(Paragraph(t(language, "bill_to_label").upper(), heading_style))
    # H6: reads the permanent snapshot taken at invoice-creation time
    # (falling back to the live Customer row only for pre-migration
    # invoices whose snapshot is still null) -- never invoice.customer
    # directly, so editing the customer afterward can never change a
    # previously issued PDF. Keyed on customer_id (not the live
    # relationship) so "no customer at all" is judged correctly even
    # when a snapshot exists but the live customer was since deleted.
    if invoice.customer_id is not None:
        customer = invoice.customer
        lines = [
            invoice.customer_name_snapshot
            if invoice.customer_name_snapshot is not None
            else (customer.name if customer is not None else None),
            invoice.customer_email_snapshot
            if invoice.customer_email_snapshot is not None
            else (customer.email if customer is not None else None),
        ]
        phone = (
            invoice.customer_phone_snapshot
            if invoice.customer_phone_snapshot is not None
            else (customer.phone if customer is not None else None)
        )
        address = (
            invoice.customer_address_snapshot
            if invoice.customer_address_snapshot is not None
            else (customer.address if customer is not None else None)
        )
        if phone:
            lines.append(phone)
        if address:
            lines.append(address)
        for line in lines:
            if line:
                elements.append(Paragraph(line, normal_style))
    else:
        elements.append(Paragraph(t(language, "no_customer"), normal_style))
    elements.append(Spacer(1, 20))

    # Phase 28 -- the per-line tax column appears only on a document that
    # actually mixes rates; a single-rate invoice keeps the exact 4-column
    # layout it has always had. See app.pdf_tax_rows for the rationale.
    tax_groups = invoice.tax_groups
    show_tax_column = should_show_line_tax_column(tax_groups)

    header = [
        t(language, "line_description_label"),
        t(language, "line_quantity_label"),
        t(language, "line_unit_price_label"),
    ]
    if show_tax_column:
        header.append(t(language, "tax_amount_label"))
    header.append(t(language, "line_total_label"))
    line_item_rows = [header]

    for item in invoice.line_items:
        row = [
            item.description,
            _format_quantity(item.quantity),
            _money(item.unit_price),
        ]
        if show_tax_column:
            row.append(
                t(language, "tax_exempt_label")
                if item.tax_rate == 0
                else format_rate_percent(item.tax_rate)
            )
        row.append(_money(item.line_total))
        line_item_rows.append(row)

    # The tax column's width is taken from the description column, so the
    # table keeps its overall 6.3in footprint and nothing overflows the
    # page margins.
    col_widths = (
        [2.5 * inch, 0.8 * inch, 1.0 * inch, 0.9 * inch, 1.1 * inch]
        if show_tax_column
        else [3.2 * inch, 0.9 * inch, 1.1 * inch, 1.1 * inch]
    )
    items_table = Table(
        line_item_rows,
        colWidths=col_widths,
        repeatRows=1,
    )
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

    totals_rows = build_totals_rows(
        subtotal=invoice.subtotal,
        tax_amount=invoice.tax_amount,
        total=invoice.total,
        tax_groups=tax_groups,
        language=language,
        currency_code=currency_code,
    )
    totals_table = Table(totals_rows, colWidths=[4.9 * inch, 1.4 * inch])
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
