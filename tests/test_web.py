from __future__ import annotations

import json
import re
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient

from gost_docs.web.app import create_app, ru_plural

TOKEN_RE = re.compile(r"/download/([0-9a-f]{32})/docx")


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path / "jobs")
    with TestClient(app) as test_client:
        yield test_client


def sample_bytes(path: Path) -> bytes:
    return path.read_bytes()


def upload_csv(client: TestClient, path: Path, **data: str):
    files = {"file": (path.name, sample_bytes(path), "text/csv")}
    return client.post("/preview", files=files, data=data)


def upload_xlsx(client: TestClient, path: Path, **data: str):
    files = {
        "file": (
            path.name,
            sample_bytes(path),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }
    return client.post("/preview", files=files, data=data)


def token_from(html: str) -> str:
    match = TOKEN_RE.search(html)
    assert match is not None, "на странице результата нет ссылки на DOCX"
    return match.group(1)


def test_index_renders_upload_form(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert "Разобрать файл" in response.text
    assert 'action="/preview"' in response.text
    assert "supplier_export.csv" in response.text


def test_security_headers(client: TestClient):
    headers = client.get("/").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert headers["Referrer-Policy"] == "no-referrer"


def test_healthz(client: TestClient):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_static_css_is_served(client: TestClient):
    response = client.get("/static/style.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert "--accent" in response.text


def test_preview_csv(client: TestClient, csv_sample: Path):
    response = upload_csv(client, csv_sample)
    assert response.status_code == 200
    assert "Проверка данных" in response.text
    assert "позиций" in response.text
    assert "Плата печатная" in response.text
    assert "Дробное количество" in response.text
    assert "strict" in response.text


def test_preview_xlsx_default_sheet(client: TestClient, xlsx_sample: Path):
    response = upload_xlsx(client, xlsx_sample)
    assert response.status_code == 200
    assert "Спецификация" in response.text
    assert "Плата печатная" in response.text


def test_preview_xlsx_sheet_selection(client: TestClient, xlsx_sample: Path):
    response = upload_xlsx(client, xlsx_sample, sheet="Спецификация")
    assert response.status_code == 200
    assert "«Спецификация»" in response.text
    assert "Плата печатная" in response.text


def test_preview_xlsx_non_data_sheet(client: TestClient, xlsx_sample: Path):
    response = upload_xlsx(client, xlsx_sample, sheet="Служебный")
    assert response.status_code == 400
    assert "заголов" in response.text


def test_preview_xlsx_missing_sheet(client: TestClient, xlsx_sample: Path):
    response = upload_xlsx(client, xlsx_sample, sheet="Нет такого")
    assert response.status_code == 400
    assert "не найден" in response.text


def test_preview_header_row_override(client: TestClient, csv_sample: Path):
    response = upload_csv(client, csv_sample, header_row="4")
    assert response.status_code == 200
    assert "строка 4" in response.text


def test_preview_header_row_must_be_positive(client: TestClient, csv_sample: Path):
    response = upload_csv(client, csv_sample, header_row="0")
    assert response.status_code == 400
    assert "начинается с 1" in response.text


def test_generate_downloads_docx_and_report(client: TestClient, csv_sample: Path):
    files = {"file": (csv_sample.name, sample_bytes(csv_sample), "text/csv")}
    response = client.post(
        "/generate",
        files=files,
        data={"product": "АБВГ.000.001", "sort": "designation"},
    )
    assert response.status_code == 200
    assert "Ведомость сформирована" in response.text
    token = token_from(response.text)

    docx = client.get(f"/download/{token}/docx")
    assert docx.status_code == 200
    assert docx.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert "vedomost.docx" in docx.headers["content-disposition"]
    document = Document(BytesIO(docx.content))
    assert "АБВГ.000.001" in "\n".join(p.text for p in document.paragraphs)

    report = client.get(f"/download/{token}/report")
    assert report.status_code == 200
    assert report.headers["content-type"].startswith("application/json")
    payload = json.loads(report.content.decode("utf-8"))
    assert payload["counts"]["items"] == 7
    assert payload["counts"]["errors"] == 3
    assert payload["output"] == "vedomost.docx"


def test_strict_mode_blocks_document(client: TestClient, csv_sample: Path):
    files = {"file": (csv_sample.name, sample_bytes(csv_sample), "text/csv")}
    response = client.post("/generate", files=files, data={"strict": "on"})
    assert response.status_code == 400
    assert "строгий режим" in response.text
    token = re.search(r'name="token" value="([0-9a-f]{32})"', response.text).group(1)
    assert client.get(f"/download/{token}/docx").status_code == 404


def test_invalid_token(client: TestClient):
    response = client.get(f"/download/{'0' * 32}/docx")
    assert response.status_code == 404
    assert "Задание не найдено" in response.text


def test_unknown_download_kind(client: TestClient, csv_sample: Path):
    files = {"file": (csv_sample.name, sample_bytes(csv_sample), "text/csv")}
    response = client.post("/generate", files=files)
    token = token_from(response.text)
    assert client.get(f"/download/{token}/pdf").status_code == 404


def test_download_before_generate(client: TestClient, csv_sample: Path):
    response = upload_csv(client, csv_sample)
    token = re.search(r'name="token" value="([0-9a-f]{32})"', response.text).group(1)
    assert client.get(f"/download/{token}/docx").status_code == 404


def test_unsupported_suffix(client: TestClient):
    response = client.post(
        "/preview",
        files={"file": ("data.docx", b"PK\x03\x04", "application/msword")},
    )
    assert response.status_code == 400
    assert "Неподдерживаемый формат" in response.text


def test_empty_upload(client: TestClient):
    response = client.post("/preview", files={"file": ("empty.csv", b"", "text/csv")})
    assert response.status_code == 400
    assert "Файл пуст" in response.text


def test_missing_file(client: TestClient):
    response = client.post("/preview", data={"product": "АБВГ.000.001"})
    assert response.status_code == 400
    assert "Файл не выбран" in response.text


def test_upload_limit(tmp_path: Path):
    app = create_app(tmp_path / "jobs", max_upload=1024)
    payload = b"a;b\n" + b"1;2\n" * 400
    with TestClient(app) as client:
        response = client.post("/preview", files={"file": ("big.csv", payload, "text/csv")})
    assert response.status_code == 400
    assert "Файл больше" in response.text


def test_samples_are_served(client: TestClient):
    response = client.get("/samples/supplier_export.csv")
    assert response.status_code == 200
    assert "Наименование" in response.text
    assert client.get("/samples/unknown.csv").status_code == 404


def test_unknown_page_returns_404_page(client: TestClient):
    response = client.get("/no-such-page")
    assert response.status_code == 404
    assert "ГОСТ" in response.text


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1, "ошибка"),
        (2, "ошибки"),
        (4, "ошибки"),
        (5, "ошибок"),
        (11, "ошибок"),
        (12, "ошибок"),
        (21, "ошибка"),
        (22, "ошибки"),
        (101, "ошибка"),
        (111, "ошибок"),
    ],
)
def test_ru_plural(value: int, expected: str):
    assert ru_plural(value, "ошибка", "ошибки", "ошибок") == expected
