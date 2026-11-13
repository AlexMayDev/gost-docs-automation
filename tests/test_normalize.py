from __future__ import annotations

from decimal import Decimal

import pytest

from gost_docs.normalize import (
    clean_text,
    format_quantity,
    normalize_designation,
    normalize_unit,
    parse_quantity,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Резистор\u00a0С2-23  0,125 Вт ", "Резистор С2-23 0,125 Вт"),
        ("«Корпус»", "Корпус"),
        ("деталь;", "деталь"),
        (None, ""),
        (42, "42"),
    ],
)
def test_clean_text(raw, expected):
    assert clean_text(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("абвг. 123456.789", "АБВГ.123456.789"),
        ("АБВГ–123-456", "АБВГ-123-456"),
        ("  ту 16—505.757-78  ", "ТУ 16-505.757-78"),
        ("", ""),
    ],
)
def test_normalize_designation(raw, expected):
    assert normalize_designation(raw) == expected


@pytest.mark.parametrize(
    ("raw", "number", "unit"),
    [
        ("1 200 шт.", Decimal(1200), "шт."),
        ("1\u00a0200,5 шт", Decimal("1200.5"), "шт"),
        ("45,5", Decimal("45.5"), None),
        ("0.5 м", Decimal("0.5"), "м"),
        ("1.234,5", Decimal("1234.5"), None),
        ("1,234.5", Decimal("1234.5"), None),
        ("12 компл", Decimal(12), "компл"),
        ("N/A", None, None),
        ("", None, None),
        ("-3 шт", Decimal(-3), "шт"),
    ],
)
def test_parse_quantity(raw, number, unit):
    assert parse_quantity(raw) == (number, unit)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("шт.", "шт"),
        ("ШТУК", "шт"),
        ("комплект", "компл"),
        ("упаковка", "упак"),
        ("пог.м", "м"),
        ("кг.", "кг"),
        ("литр", "л"),
        ("рулон", "рул"),
        ("тонн", "т"),
    ],
)
def test_normalize_unit_known(raw, expected):
    unit, known = normalize_unit(raw)
    assert (unit, known) == (expected, True)


def test_normalize_unit_unknown():
    assert normalize_unit("бухта") == ("бухта", False)
    assert normalize_unit("") == ("", False)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal(1500), "1500"),
        (Decimal("1500.0"), "1500"),
        (Decimal("2.50"), "2,5"),
        (Decimal("0.125"), "0,125"),
        (Decimal("-1.0"), "-1"),
    ],
)
def test_format_quantity(value, expected):
    assert format_quantity(value) == expected
