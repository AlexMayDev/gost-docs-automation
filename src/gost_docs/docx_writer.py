from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt

from .model import Item
from .normalize import format_quantity

FONT = "Times New Roman"
TABLE_FONT_SIZE = 10
TITLE_FONT_SIZE = 14
COLUMNS: tuple[tuple[str, int], ...] = (
    ("№ п/п", 10),
    ("Обозначение", 38),
    ("Наименование", 75),
    ("Кол. на изделие", 18),
    ("Ед. изм.", 15),
    ("Примечание", 24),
)
DEFAULT_TITLE = "Ведомость покупных изделий"


def _apply_font(run, size: int, *, bold: bool = False) -> None:
    run.bold = bold
    run.font.name = FONT
    run.font.size = Pt(size)
    rpr = run._element.get_or_add_rPr()
    fonts = rpr.get_or_add_rFonts()
    for attribute in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        fonts.set(qn(attribute), FONT)


def _set_document_defaults(document: Document) -> None:
    style = document.styles["Normal"]
    style.font.name = FONT
    style.font.size = Pt(12)
    rpr = style.element.get_or_add_rPr()
    fonts = rpr.get_or_add_rFonts()
    for attribute in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        fonts.set(qn(attribute), FONT)
    paragraph = style.paragraph_format
    paragraph.space_before = Pt(0)
    paragraph.space_after = Pt(0)
    paragraph.line_spacing = 1.0


def _set_margins(document: Document) -> None:
    section = document.sections[0]
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    section.left_margin = Mm(20)
    section.right_margin = Mm(10)
    section.top_margin = Mm(10)
    section.bottom_margin = Mm(10)


def _add_title(document: Document, title: str, product: str) -> None:
    if product:
        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _apply_font(paragraph.add_run(product), 12)

    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_after = Pt(12)
    _apply_font(paragraph.add_run(title), TITLE_FONT_SIZE, bold=True)


def _write_cell(
    cell,
    text: str,
    *,
    aligned: WD_ALIGN_PARAGRAPH = WD_ALIGN_PARAGRAPH.LEFT,
    size: int = TABLE_FONT_SIZE,
) -> None:
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    paragraph = cell.paragraphs[0]
    paragraph.alignment = aligned
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.line_spacing = 1.0
    _apply_font(paragraph.add_run(text), size)


def _repeat_header(row) -> None:
    properties = row._tr.get_or_add_trPr()
    marker = OxmlElement("w:tblHeader")
    marker.set(qn("w:val"), "true")
    properties.append(marker)


def _fixed_layout(table) -> None:
    properties = table._tbl.tblPr
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    properties.append(layout)
    for row in table.rows:
        for index, (_, width) in enumerate(COLUMNS):
            row.cells[index].width = Mm(width)


def _cell_margins(table) -> None:
    properties = table._tbl.tblPr
    margins = OxmlElement("w:tblCellMar")
    for side, width in (("top", 20), ("bottom", 20), ("left", 60), ("right", 60)):
        node = OxmlElement(f"w:{side}")
        node.set(qn("w:w"), str(width))
        node.set(qn("w:type"), "dxa")
        margins.append(node)
    properties.append(margins)


def _add_page_number(document: Document) -> None:
    paragraph = document.sections[0].footer.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _apply_font(paragraph.add_run("Лист "), TABLE_FONT_SIZE)
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "1"
    run.append(text)
    field.append(run)
    paragraph._p.append(field)


def write_docx(
    path: str | Path,
    items: list[Item],
    *,
    product: str = "",
    title: str = DEFAULT_TITLE,
) -> Path:
    """Сформировать таблицу ВП (6 граф формы 5 по ГОСТ Р 2.106-2019)."""
    document = Document()
    _set_document_defaults(document)
    _set_margins(document)
    _add_title(document, title, product)

    table = document.add_table(rows=1, cols=len(COLUMNS))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    for (label, _), cell in zip(COLUMNS, table.rows[0].cells, strict=True):
        _write_cell(cell, label, aligned=WD_ALIGN_PARAGRAPH.CENTER)
    _repeat_header(table.rows[0])

    for number, item in enumerate(items, start=1):
        cells = table.add_row().cells
        values = (
            str(number),
            item.designation,
            item.name,
            format_quantity(item.quantity),
            item.unit,
            item.note,
        )
        alignments = (
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.LEFT,
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.LEFT,
        )
        for cell, value, aligned in zip(cells, values, alignments, strict=True):
            _write_cell(cell, value, aligned=aligned)

    _fixed_layout(table)
    _cell_margins(table)
    _add_page_number(document)

    properties = document.core_properties
    properties.title = title
    properties.subject = product
    properties.author = "gost-docs-automation"
    properties.comments = "Сформировано из CSV/XLSX-выгрузки"

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    document.save(target)
    return target
