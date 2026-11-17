from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from gost_docs.model import ReadError
from gost_docs.readers import list_sheets, read_table


def write_bytes(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_read_csv_utf8_bom(tmp_path: Path):
    content = "Наименование;Количество\nБолт;10\n"
    path = write_bytes(tmp_path, "a.csv", content.encode("utf-8-sig"))
    table = read_table(path)
    assert table.fmt == "csv"
    assert table.encoding == "utf-8-sig"
    assert table.delimiter == ";"
    assert table.rows == [["Наименование", "Количество"], ["Болт", "10"]]
    assert table.row_numbers == [1, 2]


def test_read_csv_cp1251(tmp_path: Path):
    content = "Наименование;Количество\nГайка;4\n"
    path = write_bytes(tmp_path, "cp.csv", content.encode("cp1251"))
    table = read_table(path)
    assert table.encoding == "cp1251"
    assert table.rows[1] == ["Гайка", "4"]


@pytest.mark.parametrize(
    ("delimiter", "content"),
    [
        (";", "a;b\n1;2\n"),
        (",", "a,b\n1,2\n"),
        ("\t", "a\tb\n1\t2\n"),
        ("|", "a|b\n1|2\n"),
    ],
)
def test_delimiter_detection(tmp_path: Path, delimiter: str, content: str):
    path = write_bytes(tmp_path, "d.csv", content.encode("utf-8"))
    table = read_table(path)
    assert table.delimiter == delimiter
    assert table.rows == [["a", "b"], ["1", "2"]]


def test_csv_strips_cells(tmp_path: Path):
    path = write_bytes(tmp_path, "s.csv", b" a ; b \n")
    assert read_table(path).rows == [["a", "b"]]


def test_missing_file(tmp_path: Path):
    with pytest.raises(ReadError, match="не найден"):
        read_table(tmp_path / "nope.csv")


def test_unsupported_format(tmp_path: Path):
    path = write_bytes(tmp_path, "data.docx", b"PK\x03\x04")
    with pytest.raises(ReadError, match="Неподдерживаемый формат"):
        read_table(path)


def test_empty_csv(tmp_path: Path):
    path = write_bytes(tmp_path, "empty.csv", b"")
    with pytest.raises(ReadError, match="пуст"):
        read_table(path)


def test_csv_without_delimiter(tmp_path: Path):
    path = write_bytes(tmp_path, "one.csv", "просто текст\n".encode())
    with pytest.raises(ReadError, match="разделитель"):
        read_table(path)


def test_read_xlsx_fills_merged_cells(tmp_path: Path):
    path = tmp_path / "merged.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Данные"
    sheet.merge_cells("A1:C1")
    sheet["A1"] = "Спецификация"
    sheet.append(["Обозначение", "Наименование", "Кол-во"])
    sheet.append(["АБВГ.1", "Плата", 2])
    workbook.save(path)

    table = read_table(path)
    assert table.fmt == "xlsx"
    assert table.sheet == "Данные"
    assert table.rows[0] == ["Спецификация", "Спецификация", "Спецификация"]
    assert table.rows[1] == ["Обозначение", "Наименование", "Кол-во"]


def test_read_xlsx_number_formatting(tmp_path: Path):
    path = tmp_path / "numbers.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append([25.0, 2.5, "1,5"])
    workbook.save(path)

    assert read_table(path).rows[0] == ["25", "2.5", "1,5"]


def test_read_xlsx_trailing_empty_rows_trimmed(tmp_path: Path):
    path = tmp_path / "trailing.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["a"])
    sheet.cell(row=5, column=1).value = None
    sheet.cell(row=6, column=2).value = "b"
    workbook.save(path)

    table = read_table(path)
    assert table.rows == [["a", ""], ["", ""], ["", ""], ["", ""], ["", ""], ["", "b"]]


def test_read_xlsx_sheet_selection(tmp_path: Path):
    path = tmp_path / "sheets.xlsx"
    workbook = Workbook()
    workbook.active.title = "Первый"
    workbook.active.append(["one"])
    second = workbook.create_sheet("Второй")
    second.append(["two"])
    workbook.save(path)

    assert read_table(path).sheet == "Первый"
    table = read_table(path, sheet="Второй")
    assert table.sheet == "Второй"
    assert table.rows == [["two"]]


def test_read_xlsx_missing_sheet(tmp_path: Path):
    path = tmp_path / "one_sheet.xlsx"
    workbook = Workbook()
    workbook.active.append(["one"])
    workbook.save(path)

    with pytest.raises(ReadError, match="не найден"):
        read_table(path, sheet="Нет такого")


def test_read_xlsx_empty_sheet(tmp_path: Path):
    path = tmp_path / "empty.xlsx"
    workbook = Workbook()
    workbook.save(path)
    with pytest.raises(ReadError, match="пуст"):
        read_table(path)


def test_list_sheets_returns_names(tmp_path: Path):
    path = tmp_path / "sheets.xlsx"
    workbook = Workbook()
    workbook.active.title = "Первый"
    workbook.active.append(["one"])
    workbook.create_sheet("Второй")
    workbook.save(path)

    assert list_sheets(path) == ["Первый", "Второй"]


def test_list_sheets_csv_is_empty(tmp_path: Path):
    path = write_bytes(tmp_path, "a.csv", b"a;b\n1;2\n")
    assert list_sheets(path) == []


def test_list_sheets_missing_file(tmp_path: Path):
    with pytest.raises(ReadError, match="не найден"):
        list_sheets(tmp_path / "nope.xlsx")


def test_list_sheets_broken_file(tmp_path: Path):
    path = write_bytes(tmp_path, "broken.xlsx", b"not a zip")
    with pytest.raises(ReadError, match="Не удалось открыть"):
        list_sheets(path)
