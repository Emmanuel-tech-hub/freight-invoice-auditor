from __future__ import annotations

import csv
import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.models import AuditResult


def build_dispute_report_pdf(audit: AuditResult, carrier_name: str = "Carrier") -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.75 * inch, bottomMargin=0.75 * inch)
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["Normal"], spaceAfter=8)

    story = []
    story.append(Paragraph("Freight Invoice Dispute Report", styles["Title"]))
    story.append(Paragraph(f"Prepared: {date.today().isoformat()}", body))
    story.append(Paragraph(f"Carrier: {carrier_name}", body))
    story.append(Spacer(1, 12))

    story.append(
        Paragraph(
            f"This report identifies {len(audit.discrepancies)} billing discrepancy(ies) "
            f"across {audit.shipments_with_discrepancies} shipment(s), totaling "
            f"<b>${audit.total_overcharge:,.2f}</b> in disputed overcharges out of "
            f"${audit.total_billed:,.2f} billed. We request review and credit for the "
            "amounts detailed below.",
            body,
        )
    )
    story.append(Spacer(1, 12))

    summary_data = [
        ["Total Billed", "Total Expected (Contracted)", "Total Disputed Overcharge"],
        [f"${audit.total_billed:,.2f}", f"${audit.total_expected:,.2f}", f"${audit.total_overcharge:,.2f}"],
    ]
    summary_table = Table(summary_data, colWidths=[2.1 * inch] * 3)
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 20))

    story.append(Paragraph("Disputed Line Items", styles["Heading2"]))
    story.append(Spacer(1, 6))

    for i, d in enumerate(audit.discrepancies, start=1):
        story.append(
            Paragraph(
                f"<b>{i}. Shipment {d.shipment_id}</b> — Invoice {d.invoice_number} — "
                f"Lane: {d.lane} ({d.service_level})",
                body,
            )
        )
        story.append(Paragraph(f"<b>Issue:</b> {d.reason}", body))
        story.append(
            Paragraph(
                f"<b>Billed:</b> ${d.billed_amount:,.2f} &nbsp;&nbsp; "
                f"<b>Expected:</b> ${d.expected_amount:,.2f} &nbsp;&nbsp; "
                f"<b>Overcharge:</b> ${d.overcharge_amount:,.2f}",
                body,
            )
        )
        story.append(Paragraph(f"<i>Contract evidence:</i> {d.contract_evidence}", body))
        story.append(Paragraph(f"<i>Invoice evidence:</i> {d.invoice_evidence}", body))
        story.append(Spacer(1, 10))

    doc.build(story)
    return buffer.getvalue()


def build_dispute_report_csv(audit: AuditResult) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "shipment_id",
            "invoice_number",
            "lane",
            "service_level",
            "reason",
            "billed_amount",
            "expected_amount",
            "overcharge_amount",
            "contract_evidence",
            "invoice_evidence",
        ]
    )
    for d in audit.discrepancies:
        writer.writerow(
            [
                d.shipment_id,
                d.invoice_number,
                d.lane,
                d.service_level,
                d.reason,
                f"{d.billed_amount:.2f}",
                f"{d.expected_amount:.2f}",
                f"{d.overcharge_amount:.2f}",
                d.contract_evidence,
                d.invoice_evidence,
            ]
        )
    return buffer.getvalue().encode("utf-8")
