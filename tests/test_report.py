from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from conftest import make_table

from gost_docs.mapping import detect_header, parse_overrides
from gost_docs.report import build_report, save_report, source_label
from gost_docs.validate import build_items


def build_result(marker: str = "csv"):
    table = make_table(
        [
            ["Обозначение", "Наименование", "Количество", "Ед. изм.", "Примечание"],
            ["АБВГ.1", "Плата", "2", "шт", ""],
            ["АБВГ.2", "Корпус", "1", "компл", "заказ"],
        ]
    )
    header = detect_header(table)
    return table, build_items(table, header)


def test_source_label_csv():
    table, _ = build_result()
    assert source_label(table) == "CSV, кодировка utf-8, разделитель «;»"


def test_source_label_xlsx():
    table, _ = build_result()
    table = replace(table, fmt="xlsx", sheet="Спецификация")
    assert source_label(table) == "XLSX, лист «Спецификация»"


def test_build_report_structure():
    _, result = build_result()
    report = build_report(result, product="АБВГ.000.001", output="out.docx")

    assert report["source"]["file"] == "test.csv"
    assert report["product"] == "АБВГ.000.001"
    assert report["header"]["line"] == 1
    assert report["header"]["columns"]["name"] == "Наименование"
    assert report["header"]["unmatched"] == []
    assert report["counts"]["items"] == 2
    assert report["items"][0]["quantity"] == "2"


def test_save_report(tmp_path: Path):
    _, result = build_result()
    target = save_report(tmp_path / "nested" / "report.json", build_report(result))
    text = target.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert "gost-docs-automation" in text


def test_report_reflects_overrides():
    table = make_table([["Название", "КолШт"], ["Плата", "2"]])
    header = detect_header(
        table,
        1,
        parse_overrides(["name=Название", "designation=Название", "quantity=КолШт"]),
    )
    result = build_items(table, header)
    report = build_report(result)
    assert report["header"]["columns"]["designation"] == "Название"
    assert report["header"]["columns"]["quantity"] == "КолШт"
    assert report["counts"]["items"] == 1
