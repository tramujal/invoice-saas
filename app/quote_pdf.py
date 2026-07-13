"""Render a Quote as a printable PDF.

Copies app/invoice_pdf.py's exact SimpleDocTemplate/Table/TableStyle
structure and layout constants -- reportlab element lists aren't cleanly
shareable across two different metadata headers, so this is a copy rather
than an import, but every helper it calls (format_amount, t(),
get_currency_code/get_language) is imported and reused unchanged. Differs
from the invoice PDF only in: title, quote number instead of invoice
number, and an Expiry Date + Status row instead of Due Date + Payment
Status.
"""

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
from app.localization import get_language, quote_status_label, t
from app.models import Quote
from app.quote_numbering import format_quote_number


def _money(value) -> str:
    return f"{value:,.2f}"


def _format_quantity(value) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text if text else "0"


def render_quote_pdf(quote: Quote) -> bytes:
    organization = quote.organization
    language = get_language(quote)
    currency_code = get_currency_code(quote)
    quote_number = format_quote_number(quote.quote_number)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        title=f"{t(language, 'quote_title')} {quote_number}",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "QuoteTitle", parent=styles["Title"], alignment=0, fontSize=20
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

    elements.append(Paragraph(t(language, "quote_title"), title_style))
    elements.append(Spacer(1, 4))

    status_label = quote_status_label(language, quote.effective_status)
    expiry_date_text = (
        quote.expiry_date.strftime("%B %d, %Y")
        if quote.expiry_date is not None
        else t(language, "payment_terms_none")
    )

    meta_table = Table(
        [
            [t(language, "quote_no_label"), quote_number],
            [t(language, "created_label"), quote.issue_date.strftime("%B %d, %Y")],
            [t(language, "quote_expiry_date_label"), expiry_date_text],
            [t(language, "quote_status_label"), status_label],
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
    customer = quote.customer
    if customer is not None:
        lines = [customer.name, customer.email]
        if customer.phone:
            lines.append(customer.phone)
        if customer.address:
            lines.append(customer.address)
        for line in lines:
            elements.append(Paragraph(line, normal_style))
    else:
        elements.append(Paragraph(t(language, "no_customer"), normal_style))
    elements.append(Spacer(1, 20))

    line_item_rows = [
        [
            t(language, "line_description_label"),
            t(language, "line_quantity_label"),
            t(language, "line_unit_price_label"),
            t(language, "line_total_label"),
        ]
    ]
    for item in quote.line_items:
        line_item_rows.append(
            [
                item.description,
                _format_quantity(item.quantity),
                _money(item.unit_price),
                _money(item.line_total),
            ]
        )

    items_table = Table(
        line_item_rows,
        colWidths=[3.2 * inch, 0.9 * inch, 1.1 * inch, 1.1 * inch],
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

    totals_rows = [
        [t(language, "subtotal_label"), format_amount(quote.subtotal, currency_code)],
        [t(language, "tax_amount_label"), format_amount(quote.tax_amount, currency_code)],
        [t(language, "total_label"), format_amount(quote.total, currency_code)],
    ]
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
