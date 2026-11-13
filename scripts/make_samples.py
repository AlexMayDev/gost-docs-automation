"""Сгенерировать демонстрационные «грязные» выгрузки в samples/.

Запуск: py scripts/make_samples.py
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
FIXED_DATE = datetime(2026, 11, 12, 9, 0, 0)

CSV_CONTENT = """\
Выгрузка из 1С:Торговля и склад; дата 12.11.2026
Поставщик: ООО «Ромашка»; договор 44/2026
;;
№;Артикул;Наименование;Кол-во;Ед. изм.;Цена, руб.;Примечание
1;АБВГ.123456.789;Резистор С2-23 0,125 Вт;1\u00a0200;шт.;12,50;
2;абвг. 123456.789;Резистор С2-23 0,125 Вт;300;штук;12,50;дубль поставки
3;КЛМН.555.001;Конденсатор К50-35 100 мкФ;45,5;шт;98,10;аналог
4;;Винт М3х12 ГОСТ 1491-80;500;шт;2,30;
5;ТУ 16-505.757-78;Провод МГШВ 0,5;25;м;18,00;
6;АБВГ.999.000;Резистор С2-23 0,125 Вт;12;компл;;под заказ
7;АБВГ.777.001;Корпус;0;шт;;
8;АБВГ.777.002;;3;шт;;
9;АБВГ.777.003;Плата печатная;2,5;упак;;
10;АБВГ.777.004;Разъём;N/A;шт;;
11;АБВГ.777.005;Кабель ВВГ 3х1,5;0,5;бухта;;
Итого;;;;;;;
"""


def write_csv() -> Path:
    SAMPLES.mkdir(exist_ok=True)
    path = SAMPLES / "supplier_export.csv"
    path.write_text(CSV_CONTENT, encoding="utf-8-sig", newline="")
    return path


def write_xlsx() -> Path:
    SAMPLES.mkdir(exist_ok=True)
    path = SAMPLES / "purchase_list.xlsx"

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Спецификация"
    sheet.merge_cells("A1:F1")
    sheet["A1"] = "Спецификация покупных изделий"
    sheet["A1"].font = Font(bold=True, size=14)
    sheet.merge_cells("A2:F2")
    sheet["A2"] = "Изделие: АБВГ.000.001"

    rows = [
        ["№", "Обозначение", "Наименование", "Кол-во на изделие", "Ед. изм.", "Примечание"],
        ["1", "АБВГ.100.001", "Плата печатная", "2", "шт", ""],
        ["2", "АБВГ.100.002", "Разъём XP-2", "4,0", "шт", ""],
        ["3", "", "Провод МГШВ 0,5", 25.0, "м", ""],
        ["4", "АБВГ.100.004", "Корпус", "1", "компл", ""],
        ["5", "АБВГ.100.004", "Корпус", "1", "компл", "дубль"],
        [],
        ["Итого", "", "", "", "", ""],
    ]
    for offset, row in enumerate(rows, start=4):
        for column, value in enumerate(row, start=1):
            sheet.cell(row=offset, column=column, value=value if value != "" else None)

    widths = {"A": 6, "B": 20, "C": 34, "D": 20, "E": 12, "F": 22}
    for column, width in widths.items():
        sheet.column_dimensions[column].width = width

    service = workbook.create_sheet("Служебный")
    service["A1"] = "Служебный лист"
    service["A3"] = "Не используется в демо"

    # Фиксируем метаданные, чтобы повторный запуск давал тот же файл.
    workbook.properties.creator = "gost-docs-automation"
    workbook.properties.lastModifiedBy = "gost-docs-automation"
    workbook.properties.title = "Спецификация покупных изделий"
    workbook.properties.created = FIXED_DATE
    workbook.properties.modified = FIXED_DATE

    workbook.save(path)
    return path


def main() -> None:
    print(write_csv())
    print(write_xlsx())


if __name__ == "__main__":
    main()
