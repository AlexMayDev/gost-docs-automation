from __future__ import annotations

import argparse
import re
import shutil
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from ..docx_writer import write_docx
from ..mapping import FIELD_LABELS, FIELD_ORDER, detect_header, parse_overrides
from ..model import BuildResult, GostDocsError, ReadError
from ..readers import list_sheets, read_table, unsupported_format_message
from ..report import build_report, save_report
from ..validate import build_items, empty_result_message, sort_items

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"
SAMPLE_CANDIDATES = (
    PACKAGE_DIR.parents[2] / "samples",
    Path.cwd() / "samples",
    PACKAGE_DIR / "samples",
)

ALLOWED_SUFFIXES = {".csv", ".tsv", ".txt", ".xlsx", ".xlsm"}
SAMPLE_FILES = {
    "supplier_export.csv": "text/csv; charset=utf-8",
    "purchase_list.xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
SAMPLE_LABELS = {
    "supplier_export.csv": "грязный CSV",
    "purchase_list.xlsx": "XLSX с объединённой шапкой",
}
SAMPLE_ORDER = ("supplier_export.csv", "purchase_list.xlsx")
SORT_MODES = {"designation", "name", "source"}
DEFAULT_MAX_UPLOAD = 20 * 1024 * 1024
TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")


def sample_path(name: str) -> Path | None:
    """Найти пример в репозитории; в установленном пакете примеров может не быть."""
    if name not in SAMPLE_FILES:
        return None
    for base in SAMPLE_CANDIDATES:
        path = base / name
        if path.is_file():
            return path
    return None


@dataclass
class Options:
    product: str = ""
    sheet: str = ""
    header_row: int | None = None
    sort: str = "designation"
    strict: bool = False
    maps: dict[str, str] = field(default_factory=dict)


@dataclass
class Job:
    token: str
    directory: Path
    source: Path
    filename: str
    sheets: list[str]
    created: float
    docx: Path | None = None
    report: Path | None = None


class JobStore:
    """Временные файлы заданий: один каталог на загрузку, TTL и лимит количества."""

    def __init__(self, root: Path, *, ttl: int = 3600, max_jobs: int = 50) -> None:
        self.root = root
        self.ttl = ttl
        self.max_jobs = max_jobs
        self.root.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, Job] = {}

    def _cleanup(self) -> None:
        cutoff = time.time() - self.ttl
        for directory in self.root.iterdir():
            if not directory.is_dir():
                continue
            try:
                expired = directory.stat().st_mtime < cutoff
            except OSError:
                expired = True
            if expired and directory.name not in self._jobs:
                shutil.rmtree(directory, ignore_errors=True)
        for token, job in list(self._jobs.items()):
            if job.created < cutoff:
                self._jobs.pop(token, None)
                shutil.rmtree(job.directory, ignore_errors=True)

    def create(self, filename: str, data: bytes) -> Job:
        self._cleanup()
        while len(self._jobs) >= self.max_jobs:
            oldest = min(self._jobs.values(), key=lambda job: job.created)
            self._jobs.pop(oldest.token, None)
            shutil.rmtree(oldest.directory, ignore_errors=True)

        token = uuid.uuid4().hex
        directory = self.root / token
        directory.mkdir(parents=True, exist_ok=True)
        safe_name = Path(filename).name or "upload.csv"
        source = directory / safe_name
        try:
            source.write_bytes(data)
            sheets = list_sheets(source)
        except (OSError, ReadError):
            shutil.rmtree(directory, ignore_errors=True)
            raise
        job = Job(
            token=token,
            directory=directory,
            source=source,
            filename=safe_name,
            sheets=sheets,
            created=time.time(),
        )
        self._jobs[token] = job
        return job

    def get(self, token: str) -> Job:
        if not TOKEN_RE.fullmatch(token):
            raise KeyError(token)
        job = self._jobs.get(token)
        if job is None:
            raise KeyError(token)
        return job

    def close(self) -> None:
        for job in self._jobs.values():
            shutil.rmtree(job.directory, ignore_errors=True)
        self._jobs.clear()
        shutil.rmtree(self.root, ignore_errors=True)


def options_from_form(form: Any) -> Options:
    raw_header = str(form.get("header_row") or "").strip()
    try:
        header_row = int(raw_header) if raw_header else None
    except ValueError as exc:
        raise ValueError("Номер строки заголовка должен быть числом.") from exc
    if header_row is not None and header_row < 1:
        raise ValueError("Номер строки заголовка начинается с 1.")

    sort = str(form.get("sort") or "designation")
    if sort not in SORT_MODES:
        sort = "designation"

    maps = {field: str(form.get(f"map_{field}") or "").strip() for field in FIELD_ORDER}
    return Options(
        product=str(form.get("product") or "").strip(),
        sheet=str(form.get("sheet") or "").strip(),
        header_row=header_row,
        sort=sort,
        strict=str(form.get("strict") or "").lower() in {"1", "true", "on", "yes"},
        maps={field: value for field, value in maps.items() if value},
    )


def analyze(job: Job, options: Options) -> tuple[dict[str, Any], BuildResult]:
    table = read_table(job.source, options.sheet or None)
    overrides = parse_overrides([f"{field}={value}" for field, value in options.maps.items()])
    header = detect_header(table, options.header_row, overrides)
    result = build_items(table, header)
    result.items = sort_items(result.items, options.sort)
    return build_report(result, options.product, None), result


def human_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.0f} МБ"
    return f"{max(1, size // 1024)} КБ"


async def read_upload(upload: UploadFile, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise ValueError(f"Файл больше {human_size(limit)}.")
        chunks.append(chunk)
    if not total:
        raise ValueError("Файл пуст.")
    return b"".join(chunks)


def ru_plural(value: Any, one: str, few: str, many: str) -> str:
    """Русская форма слова после числа: 1 ошибка, 3 ошибки, 5 ошибок."""
    number = abs(int(value))
    if 11 <= number % 100 <= 14:
        return many
    last = number % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def create_app(
    root: Path | None = None,
    *,
    max_upload: int = DEFAULT_MAX_UPLOAD,
    ttl: int = 3600,
    max_jobs: int = 50,
) -> FastAPI:
    if root is None:
        root = Path(tempfile.mkdtemp(prefix="gost-docs-web-"))
    store = JobStore(Path(root), ttl=ttl, max_jobs=max_jobs)
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
    templates.env.filters["plural"] = ru_plural

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        store.close()

    app = FastAPI(
        title="ГОСТ-документы",
        description="CSV/XLSX → таблица ВП в DOCX (6 граф формы 5, ГОСТ Р 2.106-2019)",
        lifespan=lifespan,
    )
    app.state.store = store
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; img-src 'self' data:; "
            "form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
        )
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    def context(request: Request, **extra: Any) -> dict[str, Any]:
        base = {
            "request": request,
            "field_labels": FIELD_LABELS,
            "field_order": FIELD_ORDER,
            "samples": [name for name in SAMPLE_ORDER if sample_path(name)],
            "sample_labels": SAMPLE_LABELS,
            "max_upload_mb": max_upload // (1024 * 1024),
        }
        base.update(extra)
        return base

    def index(
        request: Request,
        *,
        error: str | None = None,
        options: Options | None = None,
        status_code: int = 200,
    ):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context=context(request, error=error, options=options or Options()),
            status_code=status_code,
        )

    def preview(
        request: Request,
        job: Job,
        options: Options,
        *,
        report: dict[str, Any] | None = None,
        error: str | None = None,
        blocked: str | None = None,
        status_code: int = 200,
    ):
        return templates.TemplateResponse(
            request=request,
            name="preview.html",
            context=context(
                request,
                job=job,
                options=options,
                report=report,
                error=error,
                blocked=blocked,
            ),
            status_code=status_code,
        )

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        return index(request)

    @app.get("/healthz")
    async def healthz():
        return JSONResponse({"status": "ok"})

    @app.get("/samples/{name}")
    async def sample(name: str):
        media_type = SAMPLE_FILES.get(name)
        path = sample_path(name)
        if media_type is None or path is None:
            raise HTTPException(status_code=404, detail="Пример не найден.")
        return FileResponse(path, media_type=media_type, filename=name)

    async def prepare(request: Request):
        form = await request.form()
        token = str(form.get("token") or "")
        try:
            options = options_from_form(form)
        except ValueError as exc:
            return None, None, str(exc)

        upload = form.get("file")
        if upload is not None and hasattr(upload, "read"):
            filename = getattr(upload, "filename", "") or ""
            if not filename:
                return None, None, "Выберите файл CSV или XLSX."
            suffix = Path(filename).suffix.lower()
            if suffix not in ALLOWED_SUFFIXES:
                return None, None, unsupported_format_message(filename)
            try:
                data = await read_upload(upload, max_upload)
                job = store.create(filename, data)
            except ValueError as exc:
                return None, None, str(exc)
            except (GostDocsError, OSError) as exc:
                return None, None, str(exc)
            return job, options, None

        if not token:
            return None, None, "Файл не выбран. Вернитесь и загрузите выгрузку."
        try:
            return store.get(token), options, None
        except KeyError:
            return None, None, "Задание не найдено или срок его хранения истёк."

    @app.post("/preview", response_class=HTMLResponse)
    async def preview_route(request: Request):
        job, options, error = await prepare(request)
        if job is None:
            return index(request, error=error, status_code=400)
        try:
            report, _ = await run_in_threadpool(analyze, job, options)
        except GostDocsError as exc:
            return preview(request, job, options, error=str(exc), status_code=400)
        return preview(request, job, options, report=report)

    @app.post("/generate", response_class=HTMLResponse)
    async def generate_route(request: Request):
        job, options, error = await prepare(request)
        if job is None:
            return index(request, error=error, status_code=400)
        try:
            report, result = await run_in_threadpool(analyze, job, options)
        except GostDocsError as exc:
            return preview(request, job, options, error=str(exc), status_code=400)

        if result.errors and options.strict:
            return preview(
                request,
                job,
                options,
                report=report,
                blocked=(
                    "В данных есть ошибки, а включён строгий режим. "
                    "Документ не создан — исправьте выгрузку или снимите галочку."
                ),
                status_code=400,
            )

        empty_reason = empty_result_message(result)
        if empty_reason is not None:
            return preview(
                request,
                job,
                options,
                report=report,
                blocked=empty_reason,
                status_code=400,
            )

        output = job.directory / "vedomost.docx"
        report_path = job.directory / "report.json"
        report["output"] = output.name
        await run_in_threadpool(write_docx, output, result.items, product=options.product)
        save_report(report_path, report)
        job.docx = output
        job.report = report_path

        return templates.TemplateResponse(
            request=request,
            name="result.html",
            context=context(
                request,
                job=job,
                options=options,
                report=report,
            ),
        )

    @app.get("/download/{token}/{kind}")
    async def download(token: str, kind: str):
        try:
            job = store.get(token)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Задание не найдено.") from exc
        if kind == "docx":
            path = job.docx
            media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            filename = "vedomost.docx"
        elif kind == "report":
            path = job.report
            media_type = "application/json; charset=utf-8"
            filename = "report.json"
        else:
            raise HTTPException(status_code=404, detail="Неизвестный тип файла.")
        if path is None or not path.is_file():
            raise HTTPException(
                status_code=404,
                detail="Файл ещё не создан. Сначала сформируйте документ.",
            )
        return FileResponse(path, media_type=media_type, filename=filename)

    @app.exception_handler(404)
    async def not_found(request: Request, exc: HTTPException):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context=context(
                request,
                error=exc.detail if isinstance(exc.detail, str) else "Страница не найдена.",
                options=Options(),
            ),
            status_code=404,
        )

    return app


app = create_app()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gost-docs-web",
        description="Локальный веб-интерфейс для сборки таблицы ВП.",
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Интерфейс (по умолчанию только localhost)"
    )
    parser.add_argument("--port", type=int, default=8000, help="Порт (по умолчанию 8000)")
    parser.add_argument("--reload", action="store_true", help="Автоперезапуск для разработки")
    args = parser.parse_args(argv)

    if args.reload:
        uvicorn.run("gost_docs.web.app:app", host=args.host, port=args.port, reload=True)
    else:
        uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
