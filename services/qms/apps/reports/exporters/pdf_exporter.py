from datetime import date
from pathlib import Path

from django.http import HttpResponse
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def register_cyrillic_font():
    candidates = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/calibri.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
    ]
    for path in candidates:
        if path.exists():
            pdfmetrics.registerFont(TTFont("QMSCyr", str(path)))
            return "QMSCyr"
    return "Helvetica"


def export_pdf(report):
    filename = f"{report['slug']}_{date.today().isoformat()}.pdf"
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    font_name = register_cyrillic_font()
    doc = SimpleDocTemplate(
        response,
        pagesize=landscape(A4),
        rightMargin=10 * mm,
        leftMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="QmsTitle", fontName=font_name, fontSize=15, leading=18, alignment=TA_CENTER))
    styles.add(ParagraphStyle(name="QmsText", fontName=font_name, fontSize=8, leading=10))
    story = [
        Paragraph("QMS", styles["QmsTitle"]),
        Paragraph(report["definition"].title, styles["QmsTitle"]),
        Paragraph(f"Сформировано: {timezone.localtime().strftime('%d.%m.%Y %H:%M')}", styles["QmsText"]),
        Spacer(1, 4 * mm),
    ]
    summary_rows = [["Показатель", "Значение"]] + [[str(label), str(value)] for label, value in report["summary"]]
    story.append(_table(summary_rows, font_name, repeat=1))
    story.append(Spacer(1, 4 * mm))
    rows = [report["headers"]] + [[format_cell(value) for value in row] for row in report["rows"][:300]]
    if len(rows) == 1:
        rows.append(["По выбранным фильтрам данные не найдены"] + [""] * (len(report["headers"]) - 1))
    story.append(_table(rows, font_name, repeat=1))
    doc.build(story, onFirstPage=page_number, onLaterPages=page_number)
    return response


def _table(rows, font_name, repeat=0):
    table = Table(rows, repeatRows=repeat)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF0FF")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#182230")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D0D5DD")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
    ]))
    return table


def format_cell(value):
    if value is None:
        return "-"
    return str(value)[:180]


def page_number(canvas, doc):
    canvas.setFont("Helvetica", 7)
    canvas.drawRightString(285 * mm, 6 * mm, f"Страница {doc.page}")
