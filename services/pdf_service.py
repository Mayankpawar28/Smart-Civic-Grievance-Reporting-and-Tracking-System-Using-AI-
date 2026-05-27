"""
services/pdf_service.py
Generates a styled PDF receipt for a single complaint using ReportLab.
"""
import io
import logging
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib            import colors
from reportlab.lib.units      import cm
from reportlab.lib.styles     import ParagraphStyle
from reportlab.lib.enums      import TA_CENTER, TA_RIGHT
from reportlab.platypus       import (
    SimpleDocTemplate, Paragraph, Spacer,
    Table, TableStyle, HRFlowable,
)

logger = logging.getLogger(__name__)

# ── Colour palette ────────────────────────────────────────────
ACCENT   = colors.HexColor("#4f46e5")
LIGHT_BG = colors.HexColor("#f8fafc")
BORDER   = colors.HexColor("#e5e7eb")
DARK     = colors.HexColor("#0f172a")
MUTED    = colors.HexColor("#64748b")

STATUS_COLORS = {
    "Pending":     colors.HexColor("#f59e0b"),
    "In Progress": colors.HexColor("#3b82f6"),
    "Resolved":    colors.HexColor("#10b981"),
}
PRIORITY_COLORS = {
    "High":   colors.HexColor("#ef4444"),
    "Medium": colors.HexColor("#f59e0b"),
    "Low":    colors.HexColor("#22c55e"),
}


def _ps(name: str, **kw) -> ParagraphStyle:
    return ParagraphStyle(name, **kw)


def generate_complaint_pdf(complaint: dict) -> bytes:
    """
    Build and return the raw PDF bytes for *complaint*.
    Raises on ReportLab errors so the caller can return a 500.
    """
    buf = io.BytesIO()
    W   = A4[0] - 4 * cm

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm,  bottomMargin=2*cm,
    )

    # ── Styles ────────────────────────────────────────────────
    title_style   = _ps("ctitle",  fontSize=18, fontName="Helvetica-Bold",  textColor=DARK,   spaceAfter=4,  leading=22)
    sub_style     = _ps("csub",    fontSize=9,  fontName="Helvetica",       textColor=MUTED,  spaceAfter=2)
    label_style   = _ps("clabel",  fontSize=7,  fontName="Helvetica-Bold",  textColor=MUTED,  spaceBefore=2, spaceAfter=1)
    value_style   = _ps("cvalue",  fontSize=10, fontName="Helvetica",       textColor=DARK,   spaceAfter=4,  leading=14)
    desc_style    = _ps("cdesc",   fontSize=10, fontName="Helvetica",       textColor=colors.HexColor("#1e293b"), leading=16, spaceAfter=8)
    section_style = _ps("csec",    fontSize=8,  fontName="Helvetica-Bold",  textColor=ACCENT, spaceBefore=14, spaceAfter=6)
    footer_style  = _ps("cfooter", fontSize=7,  fontName="Helvetica",       textColor=colors.HexColor("#94a3b8"), alignment=TA_CENTER)
    white_bold    = _ps("cwbold",  fontSize=11, fontName="Helvetica-Bold",  textColor=colors.white, leading=14)
    white_norm    = _ps("cwnorm",  fontSize=9,  fontName="Helvetica",       textColor=colors.HexColor("#cbd5e1"), alignment=TA_RIGHT, leading=12)

    status   = complaint.get("status",   "Pending")
    priority = complaint.get("priority", "Medium")
    dept     = complaint.get("department", "Unassigned")

    status_color = STATUS_COLORS.get(status,   ACCENT)
    pri_color    = PRIORITY_COLORS.get(priority, colors.gray)

    created     = complaint.get("created_at")
    created_str = created.strftime("%d %B %Y, %I:%M %p UTC") if isinstance(created, datetime) else "-"
    updated     = complaint.get("updated_at")
    updated_str = updated.strftime("%d %B %Y, %I:%M %p UTC") if isinstance(updated, datetime) else "-"

    story = []

    # Header banner
    hdr = Table(
        [[Paragraph("CivicConnect", white_bold),
          Paragraph("Official Complaint Record", white_norm)]],
        colWidths=[W * 0.6, W * 0.4],
    )
    hdr.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#1a2e6b")),
        ("TOPPADDING",    (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("LEFTPADDING",   (0, 0), (0,  0),  20),
        ("RIGHTPADDING",  (-1, 0), (-1, 0), 20),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story += [hdr, Spacer(1, 16)]

    # Title + ID
    story.append(Paragraph(complaint.get("title", "-"), title_style))
    story.append(Paragraph(
        f"Complaint ID: {complaint.get('complaint_id', '-')}   |   Submitted: {created_str}",
        sub_style,
    ))
    story.append(Spacer(1, 10))

    # Status / Priority / Department badges
    badges = Table(
        [[
            Paragraph(f"Status: {status}",     _ps("sb", fontSize=9, fontName="Helvetica-Bold", textColor=colors.white)),
            Paragraph(f"Priority: {priority}", _ps("pb", fontSize=9, fontName="Helvetica-Bold", textColor=colors.white)),
            Paragraph(f"Department: {dept}",   _ps("db", fontSize=9, fontName="Helvetica",      textColor=DARK)),
        ]],
        colWidths=[W * 0.25, W * 0.25, W * 0.50],
    )
    badges.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (0, 0), status_color),
        ("BACKGROUND",    (1, 0), (1, 0), pri_color),
        ("BACKGROUND",    (2, 0), (2, 0), LIGHT_BG),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("BOX",           (2, 0), (2,  0), 0.5, BORDER),
    ]))
    story += [badges, Spacer(1, 16), HRFlowable(width=W, thickness=1, color=BORDER, spaceAfter=14)]

    # Citizen info
    story.append(Paragraph("CITIZEN INFORMATION", section_style))
    ci = Table(
        [
            [Paragraph("Full Name",    label_style), Paragraph(complaint.get("user_name",  "-"), value_style),
             Paragraph("Email",        label_style), Paragraph(complaint.get("user_email", "-"), value_style)],
            [Paragraph("Category",     label_style), Paragraph(complaint.get("category",   "-"), value_style),
             Paragraph("Last Updated", label_style), Paragraph(updated_str,                      value_style)],
        ],
        colWidths=[W * 0.15, W * 0.35, W * 0.15, W * 0.35],
    )
    ci.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), LIGHT_BG),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("BOX",           (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, BORDER),
    ]))
    story.append(ci)

    # Location
    story.append(Paragraph("LOCATION", section_style))
    loc_text = complaint.get("location", "-")
    lat, lng = complaint.get("lat"), complaint.get("lng")
    if lat and lng:
        loc_text += f"<br/><font size='8' color='#64748b'>Coordinates: {lat}, {lng}</font>"
    loc_tbl = Table([[Paragraph(loc_text, desc_style)]], colWidths=[W])
    loc_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), LIGHT_BG),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING",   (0, 0), (-1, -1), 12),
        ("BOX",           (0, 0), (-1, -1), 0.5, BORDER),
    ]))
    story.append(loc_tbl)

    # Description
    story.append(Paragraph("DESCRIPTION", section_style))
    raw = (complaint.get("description") or "-")
    safe = raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
    desc_tbl = Table([[Paragraph(safe, desc_style)]], colWidths=[W])
    desc_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), LIGHT_BG),
        ("TOPPADDING",    (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("LEFTPADDING",   (0, 0), (-1, -1), 14),
        ("BOX",           (0, 0), (-1, -1), 0.5, BORDER),
        ("LINEAFTER",     (0, 0), (0,  -1), 4,   ACCENT),
    ]))
    story.append(desc_tbl)

    # Footer
    story += [
        Spacer(1, 20),
        HRFlowable(width=W, thickness=0.5, color=BORDER),
        Spacer(1, 6),
        Paragraph(
            f"Official record generated by CivicConnect Grievance Management System | "
            f"Generated: {datetime.utcnow().strftime('%d %B %Y, %I:%M %p UTC')}",
            footer_style,
        ),
    ]

    doc.build(story)
    return buf.getvalue()
