from __future__ import annotations

import pytest
from conftest import make_table

from gost_docs.mapping import apply_overrides, detect_header, parse_overrides
from gost_docs.model import HeaderError


def test_detect_header_skips_preamble():
    table = make_table(
        [
            ["Выгрузка", ""],
            ["", ""],
            ["№", "Артикул", "Наименование", "Кол-во", "Ед. изм.", "Примечание"],
            ["1", "АБВГ.1", "Плата", "2", "шт", ""],
        ]
    )
    header = detect_header(table)
    assert header.line == 3
    assert header.mapping == {
        "designation": 1,
        "name": 2,
        "quantity": 3,
        "unit": 4,
        "note": 5,
    }
    assert header.unmatched == []


def test_detect_header_english_synonyms():
    table = make_table([["Part Number", "Description", "Qty", "UOM"]])
    header = detect_header(table)
    assert header.mapping == {"designation": 0, "name": 1, "quantity": 2, "unit": 3}


def test_detect_header_requires_name_and_quantity():
    table = make_table([["Артикул", "Ед. изм."], ["1", "шт"]])
    with pytest.raises(HeaderError, match="Наименование"):
        detect_header(table)


def test_detect_header_skips_data_rows():
    table = make_table(
        [
            ["Наименование", "Количество"],
            ["Болт", "10"],
            ["Гайка", "20"],
        ]
    )
    assert detect_header(table).line == 1


def test_explicit_header_row_out_of_range():
    table = make_table([["Наименование", "Количество"]])
    with pytest.raises(HeaderError, match="вне диапазона"):
        detect_header(table, header_row=5)


def test_explicit_header_row_incomplete():
    table = make_table([["Наименование", "Цена"], ["Болт", "10"]])
    with pytest.raises(HeaderError, match="обязательные колонки"):
        detect_header(table, header_row=1)


def test_duplicate_column_warning():
    table = make_table([["Наименование", "Количество", "Кол-во"]])
    header = detect_header(table)
    assert header.mapping["quantity"] == 1
    assert [issue.code for issue in header.issues] == ["duplicate_column"]


def test_parse_overrides():
    assert parse_overrides(["quantity=Кол-во", "name = Название"]) == [
        ("quantity", "Кол-во"),
        ("name", "Название"),
    ]


@pytest.mark.parametrize(
    ("value", "match"),
    [
        ("quantity", "FIELD=COLUMN"),
        ("price=Стоимость", "Неизвестное поле"),
        ("name=", "не указана колонка"),
    ],
)
def test_parse_overrides_errors(value: str, match: str):
    with pytest.raises(HeaderError, match=match):
        parse_overrides([value])


def test_apply_overrides_by_name_and_index():
    table = make_table([["Номенклатура", "Кол-во", "Ед."], ["Болт", "10", "шт"]])
    header = detect_header(table)
    assert set(header.mapping) == {"name", "quantity", "unit"}

    updated = apply_overrides(table, header, [("designation", "2")])
    assert updated.mapping["designation"] == 1

    updated = apply_overrides(table, header, [("note", "Кол-во")])
    assert updated.mapping["note"] == 1


def test_apply_overrides_unknown_column():
    table = make_table([["Наименование", "Количество"]])
    header = detect_header(table)
    with pytest.raises(HeaderError, match="не найдена"):
        apply_overrides(table, header, [("note", "Комментарий")])
