from __future__ import annotations

import re

from .model import HeaderError, HeaderMatch, Issue, Table
from .normalize import clean_text

FIELD_ORDER = ("designation", "name", "quantity", "unit", "note")
FIELD_LABELS = {
    "designation": "Обозначение",
    "name": "Наименование",
    "quantity": "Количество",
    "unit": "Единица измерения",
    "note": "Примечание",
}

SYNONYMS: dict[str, tuple[str, ...]] = {
    "designation": (
        "обозначение",
        "обозначение изделия",
        "артикул",
        "код",
        "код позиции",
        "номер",
        "номенклатурный номер",
        "позиция",
        "designation",
        "part number",
        "pn",
    ),
    "name": (
        "наименование",
        "наименование товара",
        "название",
        "номенклатура",
        "товар",
        "продукция",
        "описание",
        "name",
        "description",
    ),
    "quantity": (
        "количество",
        "кол-во",
        "кол во",
        "колво",
        "кол",
        "колич",
        "количество на изделие",
        "кол-во на изделие",
        "норма расхода",
        "qty",
        "quantity",
    ),
    "unit": (
        "единица",
        "единица измерения",
        "ед изм",
        "ед. изм.",
        "ед",
        "уом",
        "unit",
        "uom",
    ),
    "note": (
        "примечание",
        "комментарий",
        "комментарии",
        "примечания",
        "note",
        "notes",
        "remarks",
    ),
}


def _key(text: str) -> str:
    lowered = text.lower().replace("ё", "е")
    cleaned = re.sub(r"[^\wа-я]+", " ", lowered, flags=re.UNICODE)
    return re.sub(r"\s+", " ", cleaned).strip()


_SYNONYM_INDEX = {_key(alias): field for field, aliases in SYNONYMS.items() for alias in aliases}


def _match_row(table: Table, index: int) -> HeaderMatch:
    row = table.rows[index]
    mapping: dict[str, int] = {}
    unmatched: list[str] = []
    issues: list[Issue] = []
    line = table.row_numbers[index] if index < len(table.row_numbers) else index + 1
    for column, cell in enumerate(row):
        title = clean_text(cell)
        key = _key(title)
        if not key:
            continue
        field = _SYNONYM_INDEX.get(key)
        if field is None:
            unmatched.append(title)
            continue
        if field in mapping:
            issues.append(
                Issue(
                    level="warning",
                    code="duplicate_column",
                    message=(
                        f"Колонка «{title}» повторяет поле «{FIELD_LABELS[field]}»; "
                        "использована первая."
                    ),
                    line=line,
                    column=title,
                )
            )
            continue
        mapping[field] = column
    return HeaderMatch(
        row_index=index,
        line=line,
        mapping=mapping,
        headers=[clean_text(cell) for cell in row],
        unmatched=unmatched,
        issues=issues,
    )


def detect_header(
    table: Table,
    header_row: int | None = None,
    overrides: list[tuple[str, str]] | None = None,
) -> HeaderMatch:
    """Найти строку заголовка и сопоставить колонки с полями ведомости."""
    if header_row is not None:
        index = header_row - 1
        if not 0 <= index < len(table.rows):
            raise HeaderError(
                f"Строка заголовка {header_row} вне диапазона: в файле {len(table.rows)} строк."
            )
        match = _match_row(table, index)
        if overrides:
            match = apply_overrides(table, match, overrides)
        if "name" not in match.mapping or "quantity" not in match.mapping:
            raise HeaderError(
                f"В строке {header_row} не найдены обязательные колонки "
                "«Наименование» и «Количество». Укажите соответствие через --map."
            )
        return match

    best: tuple[int, HeaderMatch] | None = None
    for index in range(min(len(table.rows), 20)):
        match = _match_row(table, index)
        score = len(match.mapping)
        if {"name", "quantity"} <= set(match.mapping):
            score += 5
        if best is None or score > best[0]:
            best = (score, match)

    if best is None or not {"name", "quantity"} <= set(best[1].mapping):
        raise HeaderError(
            "Не нашёл строку заголовка с колонками «Наименование» и «Количество». "
            "Проверьте файл или укажите --header-row и --map."
        )
    match = best[1]
    if overrides:
        match = apply_overrides(table, match, overrides)
    return match


def parse_overrides(values: list[str]) -> list[tuple[str, str]]:
    """Разобрать --map field=column в список пар."""
    overrides: list[tuple[str, str]] = []
    for value in values:
        if "=" not in value:
            raise HeaderError(f"--map ожидает FIELD=COLUMN, получено: «{value}».")
        field, column = value.split("=", 1)
        field = field.strip()
        column = column.strip()
        if field not in FIELD_ORDER:
            raise HeaderError(f"Неизвестное поле «{field}». Допустимые: {', '.join(FIELD_ORDER)}.")
        if not column:
            raise HeaderError(f"В --map {field}=... не указана колонка.")
        overrides.append((field, column))
    return overrides


def apply_overrides(
    table: Table, match: HeaderMatch, overrides: list[tuple[str, str]]
) -> HeaderMatch:
    """Применить ручное сопоставление полей поверх автоопределения."""
    mapping = dict(match.mapping)
    for field, column in overrides:
        index: int | None = None
        if column.isdigit():
            candidate = int(column) - 1
            if 0 <= candidate < len(match.headers):
                index = candidate
        if index is None:
            wanted = _key(column)
            for candidate, title in enumerate(match.headers):
                if _key(title) == wanted:
                    index = candidate
                    break
        if index is None:
            raise HeaderError(
                f"Колонка «{column}» не найдена в строке заголовка. "
                f"Доступные колонки: {', '.join(t for t in match.headers if t)}."
            )
        mapping[field] = index
    if "name" not in mapping or "quantity" not in mapping:
        raise HeaderError(
            "После применения --map не хватает обязательных полей «name» и «quantity»."
        )
    return HeaderMatch(
        row_index=match.row_index,
        line=match.line,
        mapping=mapping,
        headers=match.headers,
        unmatched=match.unmatched,
        issues=match.issues,
    )
