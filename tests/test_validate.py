from __future__ import annotations

from decimal import Decimal

import pytest
from conftest import make_table

from gost_docs.mapping import detect_header
from gost_docs.model import Item
from gost_docs.validate import build_items, sort_items


def build(rows: list[list[str]]):
    table = make_table(rows)
    return build_items(table, detect_header(table))


def test_build_items_basic():
    result = build(
        [
            ["Обозначение", "Наименование", "Количество", "Ед. изм.", "Примечание"],
            ["абвг.1", "  Плата ", "1 200,5", "шт.", "заказ"],
            ["АБВГ.2", "Корпус", "2", "компл", ""],
        ]
    )
    assert result.source_rows == 2
    assert result.accepted_rows == 2
    assert [(item.designation, item.quantity, item.unit) for item in result.items] == [
        ("АБВГ.1", Decimal("1200.5"), "шт"),
        ("АБВГ.2", Decimal(2), "компл"),
    ]
    assert result.items[0].name == "Плата"
    assert result.items[0].note == "заказ"
    assert result.errors == 0


def test_blank_rows_are_ignored():
    result = build(
        [
            ["Наименование", "Количество"],
            ["", ""],
            ["Болт", "10"],
            ["  ", ""],
        ]
    )
    assert result.source_rows == 1
    assert result.accepted_rows == 1


def test_summary_rows_are_skipped():
    result = build(
        [
            ["Наименование", "Количество"],
            ["Болт", "10"],
            ["Итого", "10"],
            ["Всего", ""],
        ]
    )
    assert result.source_rows == 3
    assert len(result.items) == 1
    codes = [issue.code for issue in result.issues]
    assert codes.count("summary_row") == 2


@pytest.mark.parametrize(
    ("row", "code"),
    [
        (["", "10"], "empty_name"),
        (["Болт", "N/A"], "bad_quantity"),
        (["Болт", "0"], "non_positive_quantity"),
        (["Болт", "-2"], "non_positive_quantity"),
    ],
)
def test_bad_rows_are_errors(row: list[str], code: str):
    result = build([["Наименование", "Количество"], row])
    assert result.errors == 1
    assert result.accepted_rows == 0
    assert result.issues[-1].code == code


def test_missing_designation_is_info():
    result = build([["Обозначение", "Наименование", "Количество"], ["", "Винт", "5"]])
    issue = next(issue for issue in result.issues if issue.code == "missing_designation")
    assert issue.level == "info"
    assert result.items[0].designation == ""


def test_missing_unit_defaults_to_piece():
    result = build([["Наименование", "Количество"], ["Болт", "5"]])
    assert result.items[0].unit == "шт"
    assert result.warnings == 1
    assert "missing_unit" in [issue.code for issue in result.issues]


def test_unknown_unit_is_kept():
    result = build([["Наименование", "Количество", "Ед. изм."], ["Кабель", "2", "бухта"]])
    assert result.items[0].unit == "бухта"
    assert "unknown_unit" in [issue.code for issue in result.issues]
    assert result.warnings == 1


def test_unit_from_quantity_column():
    result = build([["Наименование", "Количество"], ["Провод", "25 м"]])
    assert result.items[0].unit == "м"
    assert result.items[0].quantity == Decimal(25)
    assert result.warnings == 0


def test_unit_mismatch_warns_and_prefers_column():
    result = build([["Наименование", "Количество", "Ед. изм."], ["Болт", "5 компл", "шт"]])
    assert result.items[0].unit == "шт"
    assert "unit_mismatch" in [issue.code for issue in result.issues]
    assert result.warnings == 1


def test_fractional_piece_quantity_warns():
    result = build([["Наименование", "Количество", "Ед. изм."], ["Плата", "2,5", "упак"]])
    assert result.items[0].quantity == Decimal("2.5")
    assert "fractional_piece_quantity" in [issue.code for issue in result.issues]
    assert result.warnings == 1


def test_duplicates_are_merged():
    result = build(
        [
            ["Обозначение", "Наименование", "Количество", "Ед. изм.", "Примечание"],
            ["АБВГ.1", "Резистор", "1 200", "шт.", ""],
            ["абвг.1", "резистор", "300", "шт", "дубль"],
            ["АБВГ.2", "Корпус", "1", "шт", ""],
        ]
    )
    assert result.accepted_rows == 3
    assert result.merged_groups == 1
    assert len(result.items) == 2
    merged = result.items[0]
    assert merged.quantity == Decimal(1500)
    assert merged.note == "дубль"
    issue = next(issue for issue in result.issues if issue.code == "duplicate_merged")
    assert issue.level == "info"
    assert "2, 3" in issue.message


def test_different_unit_is_not_merged():
    result = build(
        [
            ["Обозначение", "Наименование", "Количество", "Ед. изм."],
            ["АБВГ.1", "Кабель", "2", "м"],
            ["АБВГ.1", "Кабель", "2", "рул"],
        ]
    )
    assert result.merged_groups == 0
    assert len(result.items) == 2


def _item(designation: str, name: str, quantity: str = "1") -> Item:
    return Item(
        designation=designation,
        name=name,
        quantity=Decimal(quantity),
        unit="шт",
        note="",
        line=1,
    )


def test_sort_items_by_designation_puts_empty_last():
    items = [
        _item("", "Винт"),
        _item("БББ.2", "Гайка"),
        _item("ААА.1", "Болт"),
    ]
    assert [item.name for item in sort_items(items)] == ["Болт", "Гайка", "Винт"]


def test_sort_items_by_name():
    items = [_item("Б.2", "Гайка"), _item("А.1", "Болт")]
    assert [item.name for item in sort_items(items, "name")] == ["Болт", "Гайка"]


def test_sort_items_source_keeps_order():
    items = [_item("Б.2", "Гайка"), _item("А.1", "Болт")]
    assert [item.name for item in sort_items(items, "source")] == ["Гайка", "Болт"]
    assert items[0].name == "Гайка"
