from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .mapping import FIELD_LABELS, FIELD_ORDER
from .model import BuildResult, Table
from .normalize import format_quantity


def source_label(table: Table) -> str:
    if table.fmt == "csv":
        return f"CSV, кодировка {table.encoding}, разделитель «{table.delimiter}»"
    return f"XLSX, лист «{table.sheet}»"


def build_report(
    result: BuildResult, product: str = "", output: str | None = None
) -> dict[str, Any]:
    table = result.table
    columns = {
        field: result.header.headers[index]
        for field, index in result.header.mapping.items()
        if field in FIELD_ORDER and index < len(result.header.headers)
    }
    return {
        "tool": "gost-docs-automation",
        "source": {
            "file": table.source.name,
            "format": table.fmt,
            "encoding": table.encoding,
            "delimiter": table.delimiter,
            "sheet": table.sheet,
        },
        "product": product,
        "output": output,
        "header": {
            "line": result.header.line,
            "columns": columns,
            "unmatched": result.header.unmatched,
        },
        "counts": {
            "source_rows": result.source_rows,
            "accepted_rows": result.accepted_rows,
            "items": len(result.items),
            "merged_groups": result.merged_groups,
            "errors": result.errors,
            "warnings": result.warnings,
        },
        "issues": [asdict(issue) for issue in result.issues],
        "items": [
            {
                "line": item.line,
                "designation": item.designation,
                "name": item.name,
                "quantity": format_quantity(item.quantity),
                "unit": item.unit,
                "note": item.note,
            }
            for item in result.items
        ],
    }


def save_report(path: str | Path, report: dict[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def summary_lines(
    result: BuildResult, output: str | Path, report_path: str | Path | None = None
) -> list[str]:
    lines = [
        f"Источник: {result.table.source.name} ({source_label(result.table)})",
        "Заголовок: строка "
        f"{result.header.line}, "
        + ", ".join(
            f"{FIELD_LABELS[field]} → «{result.header.headers[index]}»"
            for field, index in result.header.mapping.items()
            if field in FIELD_ORDER and index < len(result.header.headers)
        ),
        (
            f"Строк: {result.source_rows}, принято: {result.accepted_rows}, "
            f"позиций: {len(result.items)}, объединено групп: {result.merged_groups}"
        ),
        f"Ошибки: {result.errors}, предупреждения: {result.warnings}",
    ]

    notable = [issue for issue in result.issues if issue.level in {"error", "warning"}]
    for issue in notable[:10]:
        prefix = f"стр. {issue.line}: " if issue.line else ""
        lines.append(f"  {prefix}{issue.message}")
    if len(notable) > 10:
        lines.append(f"  …и ещё {len(notable) - 10} замечаний в отчёте.")

    lines.append(f"Документ: {output}")
    if report_path is not None:
        lines.append(f"Отчёт: {report_path}")
    return lines
