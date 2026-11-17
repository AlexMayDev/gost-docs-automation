from __future__ import annotations

from pathlib import Path

import pytest

from gost_docs import ocr
from gost_docs.mapping import detect_header
from gost_docs.model import ReadError, Table
from gost_docs.ocr import OCRUnavailable, Word, fix_designation, rows_from_words
from gost_docs.readers import read_table
from gost_docs.report import build_report, source_label, summary_lines
from gost_docs.validate import build_items

COLUMN_CENTERS = (100.0, 300.0, 500.0, 700.0, 900.0, 1100.0)
HEADER = (
    "п/п",
    "Обозначение",
    "Наименование",
    "Кол. на изделие",
    "Ед. изм.",
    "Примечание",
)


def make_word(text: str, center: float, y: float, height: float = 20.0) -> Word:
    """Слово шириной 8 px на символ, отцентрованное по колонке."""
    width = len(text) * 8
    return Word(text, center - width / 2, y, center + width / 2, y + height)


def make_row(values: list[str], y: float) -> list[Word]:
    return [
        make_word(value, center, y)
        for value, center in zip(values, COLUMN_CENTERS, strict=False)
        if value
    ]


def make_table_words() -> list[Word]:
    words = make_row(list(HEADER), 20.0)
    words += make_row(["1", "АБВГ.ООО.ОО1", "Резистор", "1500", "шт", "дубль поставки"], 60.0)
    words += make_row(["2", "АБВГ.ООО.ОО2", "Конденсатор", "45,5", "шт", ""], 100.0)
    words += make_row(["3", "ТУ 00-000.000-00", "Провод", "25", "м", "под заказ"], 140.0)
    words += [make_word("Лист", 100.0, 180.0), make_word("1", 300.0, 180.0)]
    return words


def test_rows_from_words_builds_table_and_trims_footer():
    rows = rows_from_words(make_table_words())

    assert rows[0] == list(HEADER)
    assert rows[1] == [
        "1",
        "АБВГ.ООО.ОО1",
        "Резистор",
        "1500",
        "шт",
        "дубль поставки",
    ]
    assert rows[2][2] == "Конденсатор"
    assert rows[-1][2] == "Провод"
    assert all("Лист" not in " ".join(row) for row in rows)
    assert len(rows) == 4


def test_rows_from_words_keeps_right_aligned_numbers_in_own_column():
    words = make_row(list(HEADER), 20.0)
    # Количество прижато к правому краю колонки и не должно уехать в «Ед. изм.».
    words.append(Word("1500", 740.0, 60.0, 780.0, 80.0))
    words.append(make_word("шт", 900.0, 60.0))

    rows = rows_from_words(words)

    assert rows[1][3] == "1500"
    assert rows[1][4] == "шт"


def test_rows_from_words_without_header_raises():
    words = [
        make_word("Просто", 100.0, 20.0),
        make_word("текст", 300.0, 20.0),
    ]
    with pytest.raises(ReadError, match="строку заголовка"):
        rows_from_words(words)


def test_rows_from_words_empty_raises():
    with pytest.raises(ReadError, match="не нашёл текста"):
        rows_from_words([])


def test_rows_from_words_requires_three_columns():
    words = [
        make_word("Наименование", 100.0, 20.0),
        make_word("Кол.", 300.0, 20.0),
    ]
    with pytest.raises(ReadError, match="меньше трёх колонок"):
        rows_from_words(words)


def test_rows_from_words_keeps_single_filled_row_with_footer_word_in_middle():
    words = make_row(list(HEADER), 20.0)
    words += make_row(["1", "АБВГ.000.001", "Резистор", "5", "шт", "лист согласован"], 60.0)

    rows = rows_from_words(words)

    assert len(rows) == 2
    assert rows[1][5] == "лист согласован"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("АБВГ.ООО.ОО1", "АБВГ.000.001"),
        ("АБВГ.ООЗ.ОО2", "АБВГ.003.002"),
        ("АБВГ.ВОО.О12", "АБВГ.800.012"),
        ("ТУ 00-000.OOO-OO", "ТУ 00-000.000-00"),
        ("АБВГ.000.001", "АБВГ.000.001"),
        ("", ""),
    ],
)
def test_fix_designation(raw: str, expected: str):
    assert fix_designation(raw) == expected


def test_fix_designation_keeps_single_letter_b():
    # Одиночная «В» может быть настоящей буквой в обозначении.
    assert fix_designation("АБВГ.В") == "АБВГ.В"


def test_read_ocr_table_png_routing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "scan.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    words = make_table_words()

    monkeypatch.setattr(ocr, "available_engine", lambda: "windows")
    monkeypatch.setattr(ocr, "_page_images", lambda file_path, workdir: [file_path])
    monkeypatch.setattr(ocr, "_deskew", lambda file_path, workdir: file_path)
    monkeypatch.setattr(ocr, "_recognize", lambda file_path, engine: words)

    table = ocr.read_ocr_table(path)

    assert table.fmt == "ocr"
    assert table.source == path
    assert table.row_numbers == [1, 2, 3, 4]
    assert table.meta["ocr"] == {"engine": "windows", "pages": 1, "words": len(words)}
    assert table.rows[1][1] == "АБВГ.ООО.ОО1"


def test_read_ocr_table_dedupes_repeated_header_on_next_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "scan.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    words = make_table_words()

    monkeypatch.setattr(ocr, "available_engine", lambda: "windows")
    monkeypatch.setattr(ocr, "_page_images", lambda file_path, workdir: [file_path, file_path])
    monkeypatch.setattr(ocr, "_deskew", lambda file_path, workdir: file_path)
    monkeypatch.setattr(ocr, "_recognize", lambda file_path, engine: words)

    table = ocr.read_ocr_table(path)

    assert sum(1 for row in table.rows if row[2] == "Наименование") == 1
    assert len(table.rows) == 7
    assert table.meta["ocr"]["pages"] == 2


def test_read_ocr_table_without_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "scan.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(ocr, "available_engine", lambda: None)

    with pytest.raises(OCRUnavailable, match="OCR недоступен"):
        ocr.read_ocr_table(path)


def test_read_table_routes_image_to_ocr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "scan.jpg"
    path.write_bytes(b"\xff\xd8\xff")
    sentinel = Table(
        source=path,
        rows=[["Обозначение"], ["АБВГ.000.001"]],
        row_numbers=[1, 2],
        fmt="ocr",
    )
    monkeypatch.setattr(ocr, "read_ocr_table", lambda file_path: sentinel)

    assert read_table(path) is sentinel


def test_build_items_fixes_ocr_designation_and_warns_on_suspect_chars():
    table = Table(
        source=Path("scan.png"),
        rows=[
            ["Обозначение", "Наименование", "Количество", "Ед. изм."],
            ["АБВГ.ООО.ОО1", "Резистор", "10", "шт"],
            ["АБВГ.(Ш.ОО2", "Конденсатор", "2", "шт"],
        ],
        row_numbers=[1, 2, 3],
        fmt="ocr",
    )
    header = detect_header(table)
    result = build_items(table, header)

    ocr_warnings = [issue for issue in result.issues if issue.code == "ocr_designation"]
    assert len(ocr_warnings) == 1
    assert ocr_warnings[0].line == 3
    assert result.items[0].designation == "АБВГ.000.001"

    suspect = Table(
        source=Path("scan.png"),
        rows=[
            ["Обозначение", "Наименование", "Количество", "Ед. изм."],
            ["АБВГ.(Ш.ОО2", "Конденсатор", "2", "шт"],
        ],
        row_numbers=[1, 2],
        fmt="ocr",
    )
    suspect_result = build_items(suspect, detect_header(suspect))
    assert [issue.code for issue in suspect_result.issues] == ["ocr_designation"]
    assert "сверьте с исходником" in suspect_result.issues[0].message


def test_report_marks_ocr_source_and_adds_caveat():
    table = Table(
        source=Path("scan.png"),
        rows=[
            ["Обозначение", "Наименование", "Количество", "Ед. изм."],
            ["АБВГ.000.001", "Резистор", "10", "шт"],
        ],
        row_numbers=[1, 2],
        fmt="ocr",
        meta={"ocr": {"engine": "windows", "pages": 2, "words": 120}},
    )
    result = build_items(table, detect_header(table))

    assert source_label(table) == "OCR (windows), страниц: 2"

    report = build_report(result)
    assert report["source"]["format"] == "ocr"
    assert report["source"]["ocr"] == {"engine": "windows", "pages": 2, "words": 120}

    lines = summary_lines(result, "output/vedomost.docx")
    assert any("OCR: сверьте количества и обозначения" in line for line in lines)
