from __future__ import annotations

import re
from decimal import Decimal

from .model import BuildResult, HeaderMatch, Issue, Item, Table
from .normalize import (
    PIECE_UNITS,
    clean_text,
    format_quantity,
    normalize_designation,
    normalize_name,
    normalize_unit,
    parse_quantity,
)

SUMMARY_RE = re.compile(r"^(итого|всего|итог)\b", re.IGNORECASE)


def _cell(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return clean_text(row[index])


def _merge_duplicates(items: list[Item], issues: list[Issue]) -> tuple[list[Item], int]:
    groups: dict[tuple[str, str, str], list[Item]] = {}
    order: list[tuple[str, str, str]] = []
    for item in items:
        key = (item.designation, item.name.casefold(), item.unit)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)

    merged_items: list[Item] = []
    merged_groups = 0
    for key in order:
        group = groups[key]
        if len(group) == 1:
            merged_items.append(group[0])
            continue
        merged_groups += 1
        total = sum((item.quantity for item in group), Decimal(0))
        notes: list[str] = []
        for item in group:
            if item.note and item.note not in notes:
                notes.append(item.note)
        lines = ", ".join(str(item.line) for item in group)
        issues.append(
            Issue(
                level="info",
                code="duplicate_merged",
                message=(
                    f"Объединены дубли со строк {lines}; "
                    f"итоговое количество {format_quantity(total)}."
                ),
                line=group[0].line,
            )
        )
        first = group[0]
        merged_items.append(
            Item(
                designation=first.designation,
                name=first.name,
                quantity=total,
                unit=first.unit,
                note="; ".join(notes),
                line=first.line,
            )
        )
    return merged_items, merged_groups


def build_items(table: Table, header: HeaderMatch) -> BuildResult:
    """Пройти по строкам после заголовка, нормализовать позиции и собрать замечания."""
    items: list[Item] = []
    issues: list[Issue] = list(header.issues)
    source_rows = 0
    accepted_rows = 0

    for index in range(header.row_index + 1, len(table.rows)):
        row = table.rows[index]
        line = table.row_numbers[index] if index < len(table.row_numbers) else index + 1
        if not any(clean_text(cell) for cell in row):
            continue
        source_rows += 1

        designation_raw = _cell(row, header.mapping.get("designation"))
        name_raw = _cell(row, header.mapping.get("name"))
        quantity_raw = _cell(row, header.mapping.get("quantity"))
        unit_raw = _cell(row, header.mapping.get("unit"))
        note_raw = _cell(row, header.mapping.get("note"))
        first_cell = clean_text(row[0]) if row else ""

        if (
            SUMMARY_RE.match(name_raw)
            or SUMMARY_RE.match(designation_raw)
            or SUMMARY_RE.match(first_cell)
        ):
            issues.append(Issue("info", "summary_row", "Строка итогов пропущена.", line))
            continue

        if not name_raw:
            issues.append(
                Issue(
                    level="error",
                    code="empty_name",
                    message="Не заполнено наименование — строка пропущена.",
                    line=line,
                    column="Наименование",
                )
            )
            continue

        quantity, unit_hint = parse_quantity(quantity_raw)
        if quantity is None:
            issues.append(
                Issue(
                    level="error",
                    code="bad_quantity",
                    message=(
                        f"Не удалось распознать количество «{quantity_raw}» — строка пропущена."
                    ),
                    line=line,
                    column="Количество",
                )
            )
            continue
        if quantity <= 0:
            issues.append(
                Issue(
                    level="error",
                    code="non_positive_quantity",
                    message=(
                        "Количество должно быть больше нуля, получено "
                        f"{format_quantity(quantity)} — строка пропущена."
                    ),
                    line=line,
                    column="Количество",
                )
            )
            continue

        if unit_raw and unit_hint:
            from_unit, _ = normalize_unit(unit_raw)
            hinted_unit, hinted_known = normalize_unit(unit_hint)
            if hinted_known and from_unit != hinted_unit:
                issues.append(
                    Issue(
                        level="warning",
                        code="unit_mismatch",
                        message=(
                            f"В колонке единица «{unit_raw}», а в количестве — "
                            f"«{unit_hint}»; принята «{from_unit}»."
                        ),
                        line=line,
                        column="Единица измерения",
                    )
                )

        unit_source = unit_raw or unit_hint or ""
        unit, unit_known = normalize_unit(unit_source)
        if not unit_source:
            issues.append(
                Issue(
                    level="warning",
                    code="missing_unit",
                    message="Не указана единица измерения; принято «шт».",
                    line=line,
                    column="Единица измерения",
                )
            )
            unit = "шт"
        elif not unit_known:
            issues.append(
                Issue(
                    level="warning",
                    code="unknown_unit",
                    message=f"Неизвестная единица «{unit_source}» — оставлена как есть.",
                    line=line,
                    column="Единица измерения",
                )
            )

        if unit in PIECE_UNITS and quantity != quantity.to_integral_value():
            issues.append(
                Issue(
                    level="warning",
                    code="fractional_piece_quantity",
                    message=(
                        f"Дробное количество {format_quantity(quantity)} для единицы «{unit}»."
                    ),
                    line=line,
                    column="Количество",
                )
            )

        if not designation_raw:
            issues.append(
                Issue(
                    level="info",
                    code="missing_designation",
                    message="Не заполнено обозначение — позиция останется без обозначения.",
                    line=line,
                    column="Обозначение",
                )
            )

        items.append(
            Item(
                designation=normalize_designation(designation_raw),
                name=normalize_name(name_raw),
                quantity=quantity,
                unit=unit,
                note=note_raw,
                line=line,
            )
        )
        accepted_rows += 1

    merged_items, merged_groups = _merge_duplicates(items, issues)
    return BuildResult(
        table=table,
        header=header,
        items=merged_items,
        issues=issues,
        source_rows=source_rows,
        accepted_rows=accepted_rows,
        merged_groups=merged_groups,
    )


def empty_result_message(result: BuildResult) -> str | None:
    """Объяснить, почему документ пуст, вместо выдачи пустого DOCX."""
    if result.items:
        return None
    if result.source_rows == 0:
        return (
            "Строк с данными не найдено: после шапки нет ни одной заполненной строки. "
            "Документ не создан, чтобы не отдавать пустой файл. Проверьте лист, "
            "номер строки заголовка и диапазон данных."
        )
    return (
        f"Ни одна строка не прошла проверку: ошибок {result.errors} из "
        f"{result.source_rows}. Документ не создан, чтобы не отдавать пустой файл — "
        "смотрите отчёт."
    )


def sort_items(items: list[Item], mode: str = "designation") -> list[Item]:
    """Упорядочить позиции для документа."""
    if mode == "source":
        return list(items)
    if mode == "name":
        return sorted(items, key=lambda item: (item.name.casefold(), item.designation))
    return sorted(
        items,
        key=lambda item: (not item.designation, item.designation, item.name.casefold()),
    )
