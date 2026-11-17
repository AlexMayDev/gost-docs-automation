from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .docx_writer import write_docx
from .mapping import detect_header, parse_overrides
from .model import GostDocsError
from .readers import read_table
from .report import build_report, save_report, summary_lines
from .validate import build_items, sort_items


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gost-docs",
        description=(
            "Превращает грязную CSV/Excel-выгрузку в таблицу ВП в DOCX (6 граф формы 5, ГОСТ Р 2.106-2019)."
        ),
    )
    parser.add_argument(
        "input",
        help="Путь к CSV, XLSX, PNG/JPG или PDF (сканы и фото распознаются через OCR)",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Куда сохранить DOCX (по умолчанию output/<имя>_vedomost.docx)",
    )
    parser.add_argument("--report", help="Путь к JSON-отчёту о качестве данных")
    parser.add_argument("--sheet", help="Лист XLSX (по умолчанию активный)")
    parser.add_argument("--product", default="", help="Обозначение изделия для шапки документа")
    parser.add_argument(
        "--map",
        action="append",
        default=[],
        metavar="FIELD=COLUMN",
        help=(
            "Ручное сопоставление колонки, например quantity=Кол-во. "
            "Поля: designation, name, quantity, unit, note."
        ),
    )
    parser.add_argument("--header-row", type=int, help="Номер строки заголовка (нумерация с 1)")
    parser.add_argument(
        "--sort",
        choices=("designation", "name", "source"),
        default="designation",
        help="Порядок позиций в документе (по умолчанию по обозначению)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Не создавать документ, если в данных есть ошибки",
    )
    parser.add_argument("--json", action="store_true", help="Вывести отчёт в JSON вместо текста")
    parser.add_argument("--quiet", action="store_true", help="Печатать только путь к файлу")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def _default_output(source: str | Path) -> Path:
    return Path("output") / f"{Path(source).stem}_vedomost.docx"


def run(args: argparse.Namespace) -> int:
    table = read_table(args.input, args.sheet)
    overrides = parse_overrides(args.map)
    header = detect_header(table, args.header_row, overrides)

    result = build_items(table, header)
    result.items = sort_items(result.items, args.sort)

    output = Path(args.output) if args.output else _default_output(args.input)
    report = build_report(result, args.product, str(output))

    report_path: Path | None = None
    if args.report:
        report_path = save_report(args.report, report)

    if result.errors and args.strict:
        print(
            f"Ошибка: найдено {result.errors} ошибок в данных, документ не создан (--strict).",
            file=sys.stderr,
        )
        if report_path is not None:
            print(f"Отчёт: {report_path}", file=sys.stderr)
        return 2

    write_docx(output, result.items, product=args.product)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.quiet:
        print(output)
    else:
        for line in summary_lines(result, output, report_path):
            print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    _configure_stdout()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except GostDocsError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
