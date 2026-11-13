from __future__ import annotations

from pathlib import Path

import pytest

from gost_docs.model import Table

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "samples"


def make_table(rows: list[list[str]], fmt: str = "csv") -> Table:
    """Собрать Table из списка строк, как будто он прочитан из файла."""
    return Table(
        source=Path("test.csv"),
        rows=rows,
        row_numbers=list(range(1, len(rows) + 1)),
        fmt=fmt,
        encoding="utf-8",
        delimiter=";" if fmt == "csv" else None,
    )


@pytest.fixture
def csv_sample() -> Path:
    path = SAMPLE_DIR / "supplier_export.csv"
    if not path.exists():
        pytest.skip("нет samples/supplier_export.csv — запустите scripts/make_samples.py")
    return path


@pytest.fixture
def xlsx_sample() -> Path:
    path = SAMPLE_DIR / "purchase_list.xlsx"
    if not path.exists():
        pytest.skip("нет samples/purchase_list.xlsx — запустите scripts/make_samples.py")
    return path
