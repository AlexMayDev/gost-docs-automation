from __future__ import annotations

import json
from pathlib import Path

import pytest

from gost_docs.cli import main


def test_cli_csv_sample(tmp_path: Path, csv_sample: Path):
    output = tmp_path / "vedomost.docx"
    report = tmp_path / "report.json"

    code = main([str(csv_sample), "-o", str(output), "--report", str(report)])

    assert code == 0
    assert output.exists()
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["counts"] == {
        "source_rows": 12,
        "accepted_rows": 8,
        "items": 7,
        "merged_groups": 1,
        "errors": 3,
        "warnings": 3,
    }
    resistor = next(item for item in data["items"] if item["name"].startswith("Резистор"))
    assert resistor["quantity"] == "1500"
    assert resistor["unit"] == "шт"


def test_cli_xlsx_sample(tmp_path: Path, xlsx_sample: Path):
    output = tmp_path / "vedomost.docx"
    code = main([str(xlsx_sample), "-o", str(output), "--sheet", "Спецификация"])
    assert code == 0
    assert output.exists()


def test_cli_strict_blocks_on_errors(tmp_path: Path, csv_sample: Path):
    output = tmp_path / "vedomost.docx"
    code = main([str(csv_sample), "-o", str(output), "--strict"])
    assert code == 2
    assert not output.exists()


def test_cli_strict_passes_clean_data(tmp_path: Path, xlsx_sample: Path):
    output = tmp_path / "vedomost.docx"
    code = main([str(xlsx_sample), "-o", str(output), "--sheet", "Спецификация", "--strict"])
    assert code == 0
    assert output.exists()


def test_cli_refuses_empty_document(tmp_path: Path, capsys):
    source = tmp_path / "header_only.csv"
    source.write_text("Наименование;Количество\n", encoding="utf-8")
    output = tmp_path / "vedomost.docx"

    code = main([str(source), "-o", str(output)])

    assert code == 1
    assert not output.exists()
    assert "пустой файл" in capsys.readouterr().err


def test_cli_json_output(tmp_path: Path, csv_sample: Path, capsys):
    output = tmp_path / "vedomost.docx"
    assert main([str(csv_sample), "-o", str(output), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["tool"] == "gost-docs-automation"
    assert data["header"]["line"] == 4
    assert data["output"] == str(output)


def test_cli_quiet_prints_only_path(tmp_path: Path, xlsx_sample: Path, capsys):
    output = tmp_path / "vedomost.docx"
    assert main([str(xlsx_sample), "-o", str(output), "--quiet"]) == 0
    assert capsys.readouterr().out.strip() == str(output)


def test_cli_sort_by_name(tmp_path: Path, xlsx_sample: Path):
    report = tmp_path / "report.json"
    assert (
        main(
            [
                str(xlsx_sample),
                "-o",
                str(tmp_path / "vedomost.docx"),
                "--report",
                str(report),
                "--sort",
                "name",
            ]
        )
        == 0
    )
    data = json.loads(report.read_text(encoding="utf-8"))
    names = [item["name"] for item in data["items"]]
    assert names == sorted(names, key=str.casefold)


def test_cli_manual_mapping(tmp_path: Path):
    source = tmp_path / "custom.csv"
    source.write_text(
        "Код;Название;КолШт\nАБВГ.1;Плата;2\n",
        encoding="utf-8",
    )
    output = tmp_path / "vedomost.docx"
    code = main(
        [
            str(source),
            "-o",
            str(output),
            "--header-row",
            "1",
            "--map",
            "designation=Код",
            "--map",
            "quantity=КолШт",
        ]
    )
    assert code == 0
    assert output.exists()


def test_cli_missing_header(tmp_path: Path):
    source = tmp_path / "bad.csv"
    source.write_text("Код;Название\n1;Плата\n", encoding="utf-8")
    assert main([str(source), "-o", str(tmp_path / "out.docx")]) == 1


def test_cli_missing_file(tmp_path: Path, capsys):
    assert main([str(tmp_path / "nope.csv")]) == 1
    assert "не найден" in capsys.readouterr().err


def test_cli_default_output_path(tmp_path: Path, monkeypatch):
    source = tmp_path / "data.csv"
    source.write_text("Наименование;Количество\nБолт;3\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert main([str(source)]) == 0
    assert (tmp_path / "output" / "data_vedomost.docx").exists()


def test_cli_version():
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
