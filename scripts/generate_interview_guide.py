#!/usr/bin/env python3
"""Build the polished AegisRAG ownership and interview PDF from Markdown."""

from __future__ import annotations

import html
import re
from datetime import date
from pathlib import Path

from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch, mm
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    HRFlowable,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "AEGISRAG_INTERVIEW_GUIDE.md"
OUTPUT = ROOT / "output" / "pdf" / "AegisRAG_Interview_Ownership_Guide.pdf"

NAVY = HexColor("#10233B")
NAVY_2 = HexColor("#183B56")
TEAL = HexColor("#00A6A6")
TEAL_DARK = HexColor("#007C7C")
ORANGE = HexColor("#F59E0B")
INK = HexColor("#243447")
MUTED = HexColor("#5E7184")
PALE = HexColor("#F3F7FA")
PALE_TEAL = HexColor("#E8F7F6")
RULE = HexColor("#D8E2EA")
WHITE = colors.white


def ascii_clean(text: str) -> str:
    replacements = {
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2192": "->",
        "\u2265": ">=",
        "\u2264": "<=",
        "\u2026": "...",
        "\u00a0": " ",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text.encode("ascii", "replace").decode("ascii")


def inline_markup(text: str) -> str:
    value = html.escape(ascii_clean(text), quote=False)
    value = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", value)
    return value


def make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.2,
            leading=13.2,
            textColor=INK,
            spaceAfter=6,
            allowWidows=0,
            allowOrphans=0,
        ),
        "h1": ParagraphStyle(
            "Heading1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=17,
            leading=20,
            textColor=NAVY,
            spaceBefore=13,
            spaceAfter=7,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "Heading2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12.3,
            leading=15,
            textColor=TEAL_DARK,
            spaceBefore=10,
            spaceAfter=5,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "Heading3",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=10.2,
            leading=13,
            textColor=NAVY_2,
            spaceBefore=8,
            spaceAfter=4,
            keepWithNext=True,
        ),
        "bullet": ParagraphStyle(
            "BulletBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.9,
            leading=12.6,
            textColor=INK,
            leftIndent=0,
            firstLineIndent=0,
            spaceAfter=2,
        ),
        "code": ParagraphStyle(
            "Code",
            parent=base["Code"],
            fontName="Courier",
            fontSize=7.4,
            leading=10.2,
            textColor=NAVY,
            leftIndent=7,
            rightIndent=7,
            borderColor=RULE,
            borderWidth=0.6,
            borderPadding=7,
            backColor=PALE,
            spaceBefore=4,
            spaceAfter=8,
        ),
        "toc_title": ParagraphStyle(
            "TOCTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=28,
            textColor=NAVY,
            spaceAfter=16,
        ),
        "callout": ParagraphStyle(
            "Callout",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=9.2,
            leading=13.5,
            textColor=NAVY,
            backColor=PALE_TEAL,
            borderColor=TEAL,
            borderWidth=0.8,
            borderPadding=9,
            spaceBefore=5,
            spaceAfter=9,
        ),
        "small": ParagraphStyle(
            "Small",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7.8,
            leading=10.5,
            textColor=MUTED,
        ),
    }


class GuideDocTemplate(BaseDocTemplate):
    def __init__(self, filename: str, **kwargs: object) -> None:
        super().__init__(filename, **kwargs)
        content_frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            id="content",
        )
        self.addPageTemplates(
            [PageTemplate(id="guide", frames=[content_frame], onPage=draw_page_chrome)]
        )

    def afterFlowable(self, flowable: Flowable) -> None:  # noqa: N802
        if not isinstance(flowable, Paragraph):
            return
        style_name = flowable.style.name
        levels = {"Heading1": 0, "Heading2": 1, "Heading3": 2}
        if style_name not in levels:
            return
        level = levels[style_name]
        text = flowable.getPlainText()
        key = f"section-{self.seq.nextf('section')}"
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(text, key, level=level, closed=level > 0)
        self.notify("TOCEntry", (level, text, self.page, key))


def draw_page_chrome(canvas: object, doc: BaseDocTemplate) -> None:
    canvas.saveState()
    width, height = A4
    if doc.page == 1:
        canvas.restoreState()
        return
    canvas.setFillColor(NAVY)
    canvas.rect(0, height - 16 * mm, width, 16 * mm, fill=1, stroke=0)
    canvas.setFillColor(WHITE)
    canvas.setFont("Helvetica-Bold", 8.5)
    canvas.drawString(doc.leftMargin, height - 10.2 * mm, "AEGISRAG / ENGINEERING OWNERSHIP GUIDE")
    canvas.setStrokeColor(TEAL)
    canvas.setLineWidth(2)
    canvas.line(doc.leftMargin, 13.5 * mm, width - doc.rightMargin, 13.5 * mm)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(
        doc.leftMargin, 8.5 * mm, "Independent production-style project | Interview edition"
    )
    canvas.drawRightString(width - doc.rightMargin, 8.5 * mm, f"Page {doc.page}")
    canvas.restoreState()


def architecture_drawing() -> Drawing:
    drawing = Drawing(470, 178)
    boxes = [
        (10, 112, 82, 40, "Scenario /\nOTLP events"),
        (108, 112, 82, 40, "Alert\ndetector"),
        (206, 112, 82, 40, "Incident +\ntimeline"),
        (304, 112, 82, 40, "LangGraph\nworkflow"),
        (402, 112, 58, 40, "Verified\nreport"),
        (108, 32, 82, 40, "SQLite /\nPostgres"),
        (255, 32, 82, 40, "Hybrid RAG\nQdrant"),
        (378, 32, 82, 40, "Redis /\nOpenTelemetry"),
    ]
    for x, y, w, h, label in boxes:
        drawing.add(Rect(x, y, w, h, rx=6, ry=6, fillColor=PALE, strokeColor=TEAL, strokeWidth=1.2))
        parts = label.split("\n")
        for index, part in enumerate(parts):
            drawing.add(
                String(
                    x + w / 2,
                    y + h / 2 + 5 - index * 12,
                    part,
                    fontName="Helvetica-Bold",
                    fontSize=7.5,
                    fillColor=NAVY,
                    textAnchor="middle",
                )
            )
    for x1, x2 in [(92, 108), (190, 206), (288, 304), (386, 402)]:
        drawing.add(Line(x1, 132, x2, 132, strokeColor=ORANGE, strokeWidth=2))
        drawing.add(Line(x2 - 4, 135, x2, 132, strokeColor=ORANGE, strokeWidth=2))
        drawing.add(Line(x2 - 4, 129, x2, 132, strokeColor=ORANGE, strokeWidth=2))
    drawing.add(Line(149, 112, 149, 72, strokeColor=MUTED, strokeWidth=1))
    drawing.add(Line(247, 112, 296, 72, strokeColor=MUTED, strokeWidth=1))
    drawing.add(Line(345, 112, 419, 72, strokeColor=MUTED, strokeWidth=1))
    drawing.add(
        String(
            235,
            5,
            "Every request and persistence boundary carries tenant identity and provenance.",
            fontName="Helvetica-Oblique",
            fontSize=7.5,
            fillColor=MUTED,
            textAnchor="middle",
        )
    )
    return drawing


def cover_story(styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    title = ParagraphStyle(
        "CoverTitle",
        fontName="Helvetica-Bold",
        fontSize=31,
        leading=34,
        textColor=WHITE,
        alignment=TA_LEFT,
    )
    subtitle = ParagraphStyle(
        "CoverSubtitle",
        fontName="Helvetica",
        fontSize=14,
        leading=20,
        textColor=HexColor("#CFE9EA"),
    )
    label = ParagraphStyle(
        "CoverLabel",
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=11,
        textColor=ORANGE,
        tracking=1.2,
    )
    note = ParagraphStyle(
        "CoverNote",
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=HexColor("#E6EDF3"),
    )
    tags = Table(
        [["RAG", "LANGGRAPH", "MULTI-TENANCY", "INCIDENT INTELLIGENCE"]],
        colWidths=[0.72 * inch, 1.18 * inch, 1.34 * inch, 1.74 * inch],
        rowHeights=0.34 * inch,
    )
    tags.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), NAVY_2),
                ("TEXTCOLOR", (0, 0), (-1, -1), WHITE),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 6.8),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0.5, TEAL),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, TEAL),
            ]
        )
    )
    cover = Table(
        [
            [Paragraph("ENGINEERING OWNERSHIP MANUAL", label)],
            [Spacer(1, 0.12 * inch)],
            [Paragraph("AegisRAG", title)],
            [Paragraph("AI Incident Commander", title)],
            [Spacer(1, 0.18 * inch)],
            [
                Paragraph(
                    "Architecture, implementation, technology decisions, trade-offs, "
                    "evaluation, safety, scaling, and interview defense.",
                    subtitle,
                )
            ],
            [Spacer(1, 0.35 * inch)],
            [tags],
            [Spacer(1, 2.15 * inch)],
            [
                Paragraph(
                    "Built to help the project author explain every important design choice "
                    "from first principles - without overstating production usage.",
                    note,
                )
            ],
            [Spacer(1, 0.2 * inch)],
            [Paragraph(f"Interview edition | Generated {date.today().isoformat()}", note)],
        ],
        colWidths=[6.65 * inch],
        rowHeights=None,
    )
    cover.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), NAVY),
                ("LEFTPADDING", (0, 0), (-1, -1), 28),
                ("RIGHTPADDING", (0, 0), (-1, -1), 28),
                ("TOPPADDING", (0, 0), (-1, 0), 35),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 28),
            ]
        )
    )
    return [cover, PageBreak()]


def flush_paragraph(
    buffer: list[str], story: list[Flowable], styles: dict[str, ParagraphStyle]
) -> None:
    if not buffer:
        return
    text = " ".join(line.strip() for line in buffer).strip()
    style = styles["callout"] if text.startswith("The important qualifier") else styles["body"]
    story.append(Paragraph(inline_markup(text), style))
    buffer.clear()


def flush_list(
    items: list[str], story: list[Flowable], styles: dict[str, ParagraphStyle], ordered: bool
) -> None:
    if not items:
        return
    flow_items = [
        ListItem(Paragraph(inline_markup(item), styles["bullet"]), leftIndent=8) for item in items
    ]
    options = {
        "bulletType": "1" if ordered else "bullet",
        "leftIndent": 18,
        "bulletFontName": "Helvetica-Bold",
        "bulletFontSize": 7.8,
        "bulletColor": TEAL_DARK,
        "spaceAfter": 6,
    }
    if ordered:
        options["start"] = "1"
    story.append(ListFlowable(flow_items, **options))
    items.clear()


def markdown_story(markdown: str, styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    story: list[Flowable] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    list_ordered = False
    code_lines: list[str] = []
    in_code = False
    first_heading_skipped = False

    def flush_all() -> None:
        flush_paragraph(paragraph, story, styles)
        flush_list(list_items, story, styles, list_ordered)

    for raw_line in markdown.splitlines():
        line = ascii_clean(raw_line.rstrip())
        if line.startswith("```"):
            flush_all()
            if in_code:
                story.append(Preformatted("\n".join(code_lines), styles["code"], maxLineLength=92))
                code_lines.clear()
            in_code = not in_code
            continue
        if in_code:
            code_lines.append(line)
            continue
        heading = re.match(r"^(#{1,4})\s+(.+)$", line)
        if heading:
            flush_all()
            level = len(heading.group(1))
            text = heading.group(2)
            if level == 1 and not first_heading_skipped:
                first_heading_skipped = True
                continue
            style_key = "h1" if level == 2 else "h2" if level == 3 else "h3"
            story.append(Paragraph(inline_markup(text), styles[style_key]))
            if text == "3. System context":
                story.extend(
                    [
                        Spacer(1, 3),
                        KeepTogether(
                            [
                                architecture_drawing(),
                                Paragraph(
                                    "Figure 1. Executable local path and replaceable "
                                    "production adapters.",
                                    styles["small"],
                                ),
                            ]
                        ),
                        Spacer(1, 5),
                    ]
                )
            continue
        unordered = re.match(r"^-\s+(.+)$", line)
        ordered = re.match(r"^\d+\.\s+(.+)$", line)
        if unordered or ordered:
            flush_paragraph(paragraph, story, styles)
            current_ordered = bool(ordered)
            if list_items and list_ordered != current_ordered:
                flush_list(list_items, story, styles, list_ordered)
            list_ordered = current_ordered
            list_items.append((ordered or unordered).group(1))
            continue
        if not line.strip():
            flush_all()
            continue
        if list_items:
            flush_list(list_items, story, styles, list_ordered)
        paragraph.append(line)

    flush_all()
    if code_lines:
        story.append(Preformatted("\n".join(code_lines), styles["code"], maxLineLength=92))
    return story


def build_pdf() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    styles = make_styles()
    doc = GuideDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=17 * mm,
        rightMargin=17 * mm,
        topMargin=22 * mm,
        bottomMargin=19 * mm,
        title="AegisRAG Engineering Ownership and Interview Guide",
        author="AegisRAG project",
        subject="Complete architecture, implementation, trade-off, and interview guide",
    )

    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle(
            "TOCLevel1",
            fontName="Helvetica-Bold",
            fontSize=9.2,
            leading=13,
            leftIndent=0,
            firstLineIndent=0,
            textColor=NAVY,
            spaceBefore=3,
        ),
        ParagraphStyle(
            "TOCLevel2",
            fontName="Helvetica",
            fontSize=8.2,
            leading=11,
            leftIndent=13,
            firstLineIndent=0,
            textColor=TEAL_DARK,
        ),
        ParagraphStyle(
            "TOCLevel3",
            fontName="Helvetica",
            fontSize=7.5,
            leading=10,
            leftIndent=27,
            firstLineIndent=0,
            textColor=MUTED,
        ),
    ]

    story = cover_story(styles)
    story.extend(
        [
            Paragraph("Contents", styles["toc_title"]),
            Paragraph(
                "Use this as a study sequence: understand the system, trace one incident, "
                "defend the retrieval and orchestration choices, then rehearse the "
                "interview questions.",
                styles["body"],
            ),
            HRFlowable(width="100%", thickness=1.2, color=TEAL, spaceBefore=4, spaceAfter=10),
            toc,
            PageBreak(),
        ]
    )
    story.extend(markdown_story(SOURCE.read_text(encoding="utf-8"), styles))
    doc.multiBuild(story)
    print(f"Created {OUTPUT}")


if __name__ == "__main__":
    build_pdf()
