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

from app.invoice_numbering import format_invoice_number
from app.models import Invoice
from app.payment_status import PaymentStatus

PAYMENT_STATUS_LABELS = {
    PaymentStatus.pending: "Pending",
    PaymentStatus.paid: "Paid",
    PaymentStatus.overdue: "Overdue",
}


def _money(value) -> str:
    return f"{value:,.2f}"


def _format_quantity(value) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text if text else "0"


def render_invoice_pdf(invoice: Invoice) -> bytes:
    invoice_number = format_invoice_number(invoice.invoice_number)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        title=f"Invoice {invoice_number}",
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

    elements.append(Paragraph("Invoice", title_style))
    elements.append(Spacer(1, 4))

    status_label = PAYMENT_STATUS_LABELS.get(
        PaymentStatus(invoice.payment_status), invoice.payment_status
    )
    meta_table = Table(
        [
            ["Invoice No.", invoice_number],
            ["Created", invoice.created_at.strftime("%B %d, %Y")],
            ["Payment status", status_label],
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

    elements.append(Paragraph("BILL TO", heading_style))
    customer = invoice.customer
    if customer is not None:
        lines = [customer.name, customer.email]
        if customer.phone:
            lines.append(customer.phone)
        if customer.address:
            lines.append(customer.address)
        for line in lines:
            elements.append(Paragraph(line, normal_style))
    else:
        elements.append(Paragraph("No customer on file", normal_style))
    elements.append(Spacer(1, 20))

    line_item_rows = [["Description", "Quantity", "Unit price", "Line total"]]
    for item in invoice.line_items:
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
        ["Subtotal", _money(invoice.subtotal)],
        ["Tax", _money(invoice.tax_amount)],
        ["Total", _money(invoice.total)],
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
