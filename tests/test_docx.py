from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from docx import Document

from gost_docs.docx_writer import write_docx
from gost_docs.model import Item


def make_items() -> list[Item]:
    return [
        Item(
            designation="АБВГ.123456.789",
            name="Резистор С2-23 0,125 Вт",
            quantity=Decimal(1500),
            unit="шт",
            note="",
            line=5,
        ),
        Item(
            designation="",
            name="Винт М3х12",
            quantity=Decimal("0.5"),
            unit="м",
            note="под заказ",
            line=6,
        ),
    ]


def test_write_docx_creates_file(tmp_path: Path):
    target = write_docx(tmp_path / "vedomost.docx", make_items(), product="АБВГ.000.001")
    assert target.exists()
    assert target.stat().st_size > 0


def test_docx_structure(tmp_path: Path):
    target = write_docx(
        tmp_path / "vedomost.docx",
        make_items(),
        product="АБВГ.000.001",
        title="Ведомость покупных изделий",
    )
    document = Document(target)

    texts = [paragraph.text for paragraph in document.paragraphs]
    assert "АБВГ.000.001" in texts
    assert "Ведомость покупных изделий" in texts

    table = document.tables[0]
    headers = [cell.text for cell in table.rows[0].cells]
    assert headers == [
        "№ п/п",
        "Обозначение",
        "Наименование",
        "Кол. на изделие",
        "Ед. изм.",
        "Примечание",
    ]
    assert len(table.rows) == 3
    assert [cell.text for cell in table.rows[1].cells] == [
        "1",
        "АБВГ.123456.789",
        "Резистор С2-23 0,125 Вт",
        "1500",
        "шт",
        "",
    ]
    assert [cell.text for cell in table.rows[2].cells] == [
        "2",
        "",
        "Винт М3х12",
        "0,5",
        "м",
        "под заказ",
    ]


def test_docx_header_repeats(tmp_path: Path):
    target = write_docx(tmp_path / "vedomost.docx", make_items())
    document = Document(target)
    header_row = document.tables[0].rows[0]
    properties = header_row._tr.trPr
    assert properties is not None
    assert (
        properties.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tblHeader")
        is not None
    )


def test_docx_page_setup_and_fonts(tmp_path: Path):
    target = write_docx(tmp_path / "vedomost.docx", make_items())
    document = Document(target)
    section = document.sections[0]
    assert round(section.page_width.mm, 1) == 210.0
    assert round(section.page_height.mm, 1) == 297.0
    assert round(section.left_margin.mm, 1) == 20.0
    assert round(section.right_margin.mm, 1) == 10.0

    style = document.styles["Normal"]
    assert style.font.name == "Times New Roman"

    table = document.tables[0]
    run = table.rows[1].cells[2].paragraphs[0].runs[0]
    assert run.font.name == "Times New Roman"
    assert run.font.size.pt == 10

    footer_text = document.sections[0].footer.paragraphs[0].text
    assert "Лист" in footer_text


def test_docx_without_product(tmp_path: Path):
    target = write_docx(tmp_path / "vedomost.docx", make_items())
    document = Document(target)
    assert document.core_properties.title == "Ведомость покупных изделий"
    assert len(document.paragraphs) == 1
