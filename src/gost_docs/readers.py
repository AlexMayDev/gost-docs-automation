from __future__ import annotations

import csv
import io
from datetime import date, datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from .model import ReadError, Table

CSV_ENCODINGS = ("utf-8-sig", "utf-8", "cp1251")
DELIMITERS = (";", "\t", ",", "|")
XLSX_SUFFIXES = {".xlsx", ".xlsm"}
CSV_SUFFIXES = {".csv", ".tsv", ".txt"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}

SCAN_MESSAGE = (
    "Похоже, это скан или фотография. Инструмент работает с текстовыми таблицами: "
    "CSV, TSV, XLSX, XLSM. Пересохраните таблицу в Excel или CSV из исходной программы. "
    "Если есть только скан — напишите, обсудим разбор вручную."
)
PDF_MESSAGE = (
    "PDF не поддерживается: инструмент не распознаёт сканы. Если в PDF есть текстовый "
    "слой, сохраните таблицу в Excel или CSV; если это скан — это ручной разбор, "
    "обсудим отдельно."
)


def unsupported_format_message(name: str) -> str:
    """Объяснить отказ по формату: скан, PDF и всё остальное — разные причины."""
    suffix = Path(name).suffix.lower()
    if suffix == ".pdf":
        return PDF_MESSAGE
    if suffix in IMAGE_SUFFIXES:
        return f"«{suffix}» — {SCAN_MESSAGE}"
    return f"Неподдерживаемый формат «{suffix or Path(name).name}». Нужен CSV, TSV или XLSX."


def read_table(path: str | Path, sheet: str | None = None) -> Table:
    """Прочитать CSV или XLSX и вернуть сырые строки, приведённые к тексту."""
    file_path = Path(path)
    if not file_path.exists():
        raise ReadError(f"Файл не найден: {file_path}")
    suffix = file_path.suffix.lower()
    if suffix in XLSX_SUFFIXES:
        return _read_xlsx(file_path, sheet)
    if suffix in CSV_SUFFIXES:
        return _read_csv(file_path)
    raise ReadError(unsupported_format_message(file_path.name))


def _decode(raw: bytes) -> tuple[str, str]:
    for encoding in CSV_ENCODINGS:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ReadError("Не удалось определить кодировку CSV (пробовали UTF-8, UTF-8 с BOM и CP1251).")


def _guess_delimiter(text: str) -> str:
    lines = [line for line in text.splitlines() if line.strip()][:30]
    if not lines:
        raise ReadError("CSV пуст.")
    scores = {delimiter: sum(line.count(delimiter) for line in lines) for delimiter in DELIMITERS}
    delimiter = max(scores, key=lambda item: scores[item])
    if scores[delimiter] == 0:
        raise ReadError(
            "Не удалось определить разделитель CSV: в файле нет «;», «,», табуляции или «|». "
            "Сохраните таблицу как CSV с разделителем «;» или «,» либо пришлите XLSX."
        )
    return delimiter


def _read_csv(path: Path) -> Table:
    text, encoding = _decode(path.read_bytes())
    delimiter = _guess_delimiter(text)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    rows: list[list[str]] = []
    numbers: list[int] = []
    try:
        for row in reader:
            rows.append([cell.strip() for cell in row])
            numbers.append(reader.line_num)
    except csv.Error as exc:
        raise ReadError(f"Не удалось разобрать CSV: {exc}") from exc
    if not rows:
        raise ReadError("CSV не содержит строк.")
    return Table(
        source=path,
        rows=rows,
        row_numbers=numbers,
        fmt="csv",
        encoding=encoding,
        delimiter=delimiter,
    )


def _cell_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.10f}".rstrip("0").rstrip(".")
    if isinstance(value, (datetime, date)):
        return value.strftime("%d.%m.%Y")
    return str(value).strip()


def _read_xlsx(path: Path, sheet: str | None) -> Table:
    try:
        workbook = load_workbook(path, data_only=True)
    except Exception as exc:
        raise ReadError(f"Не удалось открыть XLSX: {exc}") from exc
    try:
        if sheet is None:
            worksheet = workbook.active
        elif sheet in workbook.sheetnames:
            worksheet = workbook[sheet]
        else:
            available = ", ".join(workbook.sheetnames) or "нет"
            raise ReadError(f"Лист «{sheet}» не найден. Доступные листы: {available}.")

        grid = [
            [
                _cell_to_text(worksheet.cell(row=row, column=column).value)
                for column in range(1, worksheet.max_column + 1)
            ]
            for row in range(1, worksheet.max_row + 1)
        ]
        # openpyxl хранит значение объединённой ячейки только в левой верхней:
        # размножаем его, чтобы шапка с объединёнными заголовками читалась целиком.
        for merged in worksheet.merged_cells.ranges:
            value = _cell_to_text(worksheet.cell(row=merged.min_row, column=merged.min_col).value)
            for row in range(merged.min_row, merged.max_row + 1):
                for column in range(merged.min_col, merged.max_col + 1):
                    grid[row - 1][column - 1] = value

        last_filled = 0
        for index, row in enumerate(grid, start=1):
            if any(cell.strip() for cell in row):
                last_filled = index
        if not last_filled:
            pictures = len(getattr(worksheet, "_images", []) or [])
            if pictures:
                raise ReadError(
                    f"В листе «{worksheet.title}» нет текстовой таблицы: найдено "
                    f"изображений — {pictures}. Похоже, данные вставлены картинкой. "
                    "Инструмент не распознаёт изображения: пришлите XLSX с текстовыми "
                    "ячейками или CSV."
                )
            raise ReadError(f"Лист «{worksheet.title}» пуст.")
        rows = grid[:last_filled]
        numbers = list(range(1, last_filled + 1))
        return Table(
            source=path,
            rows=rows,
            row_numbers=numbers,
            fmt="xlsx",
            sheet=worksheet.title,
        )
    finally:
        workbook.close()


def list_sheets(path: str | Path) -> list[str]:
    """Вернуть имена листов XLSX. Для CSV и других форматов — пустой список."""
    file_path = Path(path)
    if not file_path.exists():
        raise ReadError(f"Файл не найден: {file_path}")
    if file_path.suffix.lower() not in XLSX_SUFFIXES:
        return []
    try:
        workbook = load_workbook(file_path, read_only=True)
    except Exception as exc:  # noqa: BLE001 - openpyxl бросает разные типы
        raise ReadError(f"Не удалось открыть XLSX: {exc}") from exc
    try:
        return list(workbook.sheetnames)
    finally:
        workbook.close()
