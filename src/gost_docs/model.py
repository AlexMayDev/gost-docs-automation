from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path


class GostDocsError(Exception):
    """Базовая ошибка приложения."""


class ReadError(GostDocsError):
    """Не удалось прочитать входной файл."""


class HeaderError(GostDocsError):
    """Не удалось найти или разобрать строку заголовка."""


@dataclass(frozen=True)
class Table:
    """Сырые строки источника: значения уже приведены к строкам."""

    source: Path
    rows: list[list[str]]
    row_numbers: list[int]
    fmt: str
    encoding: str | None = None
    delimiter: str | None = None
    sheet: str | None = None


@dataclass
class Item:
    """Нормализованная позиция ведомости."""

    designation: str
    name: str
    quantity: Decimal
    unit: str
    note: str
    line: int


@dataclass
class Issue:
    """Замечание к строке источника."""

    level: str
    code: str
    message: str
    line: int | None = None
    column: str | None = None


@dataclass
class HeaderMatch:
    row_index: int
    line: int
    mapping: dict[str, int]
    headers: list[str]
    unmatched: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)


@dataclass
class BuildResult:
    table: Table
    header: HeaderMatch
    items: list[Item]
    issues: list[Issue]
    source_rows: int
    accepted_rows: int
    merged_groups: int

    @property
    def errors(self) -> int:
        return sum(1 for issue in self.issues if issue.level == "error")

    @property
    def warnings(self) -> int:
        return sum(1 for issue in self.issues if issue.level == "warning")
