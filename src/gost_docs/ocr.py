"""OCR для сканов и фотографий таблиц ВП.

Движки:
- Windows OCR (Windows 10/11, языковой пакет «Русский») — работает без установки;
- Tesseract через pytesseract — кросс-платформенный вариант, нужен бинарник.

Оба движка отдают слова с координатами, а таблица собирается по геометрии:
строки — по вертикали, колонки — по центрам ячеек заголовка. Распознавание
не идеальное, поэтому каждая сомнительная строка попадает в отчёт, а не
исчезает молча.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import statistics
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .model import ReadError, Table

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
PDF_SUFFIXES = {".pdf"}
OCR_SUFFIXES = IMAGE_SUFFIXES | PDF_SUFFIXES

PDF_DPI = 300
MIN_CONFIDENCE = 30.0
ROW_TOLERANCE = 0.6
CELL_GAP = 1.6

FOOTER_RE = re.compile(r"^(лист|формат|изм\.|подп\.|дата|масштаб|литера|page)\b", re.IGNORECASE)

_ZERO_MAP = str.maketrans({"О": "0", "O": "0", "о": "0", "o": "0", "С": "0", "с": "0"})
_DIGIT_MAP = str.maketrans(
    {"О": "0", "O": "0", "о": "0", "o": "0", "С": "0", "с": "0", "З": "3", "з": "3", "В": "8"}
)
_NUMERIC_SEGMENT_RE = re.compile(r"^[0-9ОOоoСсЗзВ]+$")


class OCRUnavailable(ReadError):
    """Движок OCR не найден."""


@dataclass(frozen=True)
class Word:
    """Слово с координатами в пикселях страницы."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    conf: float | None = None

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


def available_engine() -> str | None:
    """Вернуть имя доступного движка OCR или None."""
    if _windows_ready():
        return "windows"
    if _tesseract_ready():
        return "tesseract"
    return None


def engine_help() -> str:
    return (
        "OCR недоступен. Варианты:\n"
        "  • Windows 10/11: добавьте язык «Русский» в параметрах системы — "
        "встроенный OCR работает без установки;\n"
        "  • любая ОС: установите Tesseract 5 с языком rus "
        "(Windows: https://github.com/UB-Mannheim/tesseract/wiki) и "
        "pip install \"gost-docs-automation[ocr]\";\n"
        "  • либо пришлите CSV/XLSX вместо скана."
    )


def _windows_ready() -> bool:
    if sys.platform != "win32":
        return False
    try:
        from winrt.windows.media.ocr import OcrEngine  # noqa: F401
        from winrt.windows.storage import StorageFile  # noqa: F401
    except ImportError:
        return False
    return True


def _tesseract_ready() -> bool:
    try:
        import pytesseract
    except ImportError:
        return False
    return bool(_tesseract_cmd(pytesseract))


def _tesseract_cmd(pytesseract) -> str | None:
    import os

    return os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")


def _windows_words(path: Path) -> list[Word]:
    try:
        from winrt.windows.globalization import Language
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage import FileAccessMode, StorageFile
    except ImportError as exc:  # pragma: no cover - зависит от платформы
        raise OCRUnavailable(engine_help()) from exc

    async def recognize() -> tuple[list[Word], bool]:
        engine = OcrEngine.try_create_from_language(Language("ru"))
        localized = engine is not None
        if engine is None:
            engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise OCRUnavailable(
                "Windows OCR не поддерживает русский язык. Добавьте язык «Русский» "
                "в параметрах Windows или установите Tesseract.\n" + engine_help()
            )
        storage = await StorageFile.get_file_from_path_async(str(path))
        stream = await storage.open_async(FileAccessMode.READ)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        result = await engine.recognize_async(bitmap)
        words: list[Word] = []
        for line in result.lines:
            for word in line.words:
                text = (word.text or "").strip()
                rect = word.bounding_rect
                if not text or rect is None:
                    continue
                words.append(
                    Word(text, rect.x, rect.y, rect.x + rect.width, rect.y + rect.height)
                )
        return words, localized

    words, _ = asyncio.run(recognize())
    return words


def _tesseract_words(path: Path) -> list[Word]:
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - зависит от окружения
        raise OCRUnavailable(engine_help()) from exc

    command = _tesseract_cmd(pytesseract)
    if not command:
        raise OCRUnavailable(engine_help())
    pytesseract.pytesseract.tesseract_cmd = command

    try:
        languages = set(pytesseract.get_languages(config=""))
    except Exception:  # noqa: BLE001 - tesseract отвечает разными ошибками
        languages = set()
    lang = "rus+eng" if "rus" in languages else "eng"

    with Image.open(path) as image:
        data = pytesseract.image_to_data(
            image,
            lang=lang,
            config="--psm 6",
            output_type=pytesseract.Output.DICT,
        )

    words: list[Word] = []
    for index, raw in enumerate(data.get("text", [])):
        text = (raw or "").strip()
        if not text:
            continue
        try:
            confidence = float(data["conf"][index])
        except (KeyError, TypeError, ValueError):
            confidence = -1.0
        if confidence >= 0 and confidence < MIN_CONFIDENCE:
            continue
        left = float(data["left"][index])
        top = float(data["top"][index])
        width = float(data["width"][index])
        height = float(data["height"][index])
        words.append(
            Word(
                text,
                left,
                top,
                left + width,
                top + height,
                confidence if confidence >= 0 else None,
            )
        )
    return words


def _recognize(path: Path, engine: str) -> list[Word]:
    if engine == "windows":
        return _windows_words(path)
    return _tesseract_words(path)


def _page_images(path: Path, workdir: Path) -> list[Path]:
    if path.suffix.lower() in PDF_SUFFIXES:
        try:
            import pypdfium2 as pdfium
        except ImportError as exc:
            raise OCRUnavailable(
                "Для PDF нужен pypdfium2: pip install \"gost-docs-automation[ocr]\"."
            ) from exc
        try:
            document = pdfium.PdfDocument(str(path))
        except Exception as exc:  # noqa: BLE001 - pdfium бросает свои исключения
            raise ReadError(f"Не удалось открыть PDF: {exc}") from exc
        pages: list[Path] = []
        try:
            for index in range(len(document)):
                image = document[index].render(scale=PDF_DPI / 72).to_pil()
                target = workdir / f"page-{index + 1}.png"
                image.save(target)
                pages.append(target)
        except Exception as exc:  # noqa: BLE001
            raise ReadError(f"Не удалось отрисовать страницу PDF: {exc}") from exc
        finally:
            document.close()
        if not pages:
            raise ReadError("PDF не содержит страниц.")
        return pages
    return [path]


def _median(values: list[float], default: float = 1.0) -> float:
    clean = [value for value in values if value > 0]
    return statistics.median(clean) if clean else default


def _merge_cells(words: list[Word], gap: float) -> list[tuple[float, float, str]]:
    ordered = sorted(words, key=lambda word: word.x0)
    cells: list[list[Word]] = []
    for word in ordered:
        if cells and word.x0 - max(item.x1 for item in cells[-1]) <= gap:
            cells[-1].append(word)
        else:
            cells.append([word])
    return [
        (
            min(item.x0 for item in cell),
            max(item.x1 for item in cell),
            " ".join(item.text for item in cell),
        )
        for cell in cells
    ]


def _group_rows(words: list[Word], tolerance: float) -> list[list[Word]]:
    ordered = sorted(words, key=lambda word: word.cy)
    rows: list[list[Word]] = []
    centers: list[float] = []
    for word in ordered:
        if rows and abs(word.cy - centers[-1]) <= tolerance:
            rows[-1].append(word)
            centers[-1] = sum(item.cy for item in rows[-1]) / len(rows[-1])
        else:
            rows.append([word])
            centers.append(word.cy)
    return rows


def _find_header(cells_per_row: list[list[tuple[float, float, str]]]) -> int | None:
    for index, cells in enumerate(cells_per_row):
        joined = " ".join(cell[2] for cell in cells).lower().replace("ё", "е")
        if "наимен" in joined and ("обознач" in joined or "кол" in joined or "ед" in joined):
            return index
    return None


def _column_bounds(centers: list[float]) -> list[float]:
    bounds = [float("-inf")]
    for left, right in zip(centers, centers[1:], strict=False):
        bounds.append((left + right) / 2)
    bounds.append(float("inf"))
    return bounds


def _deskew(path: Path, workdir: Path) -> Path:
    """Выровнять строки по горизонтали: проекция текста максимальна при 0°."""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - зависит от окружения
        raise OCRUnavailable(
            'Для сканов нужен Pillow: pip install "gost-docs-automation[ocr]".'
        ) from exc

    with Image.open(path) as source:
        image = source.convert("RGB")
    gray = image.convert("L")
    scale = 600 / gray.width if gray.width > 600 else 1.0
    small = gray.resize((max(1, int(gray.width * scale)), max(1, int(gray.height * scale))))
    best_angle = 0.0
    best_score = -1.0
    for step in range(-12, 13):
        angle = step * 0.5
        rotated = small.rotate(angle, resample=Image.Resampling.BILINEAR, fillcolor=255)
        values = list(rotated.resize((1, rotated.height), Image.Resampling.BOX).getdata())
        mean = sum(values) / len(values)
        score = sum((value - mean) ** 2 for value in values) / len(values)
        if score > best_score:
            best_score, best_angle = score, angle

    if abs(best_angle) >= 0.5:
        image = image.rotate(
            best_angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white"
        )
    target = workdir / f"{path.stem}-deskew.png"
    image.save(target)
    return target


def _assign(words: list[Word], bounds: list[float]) -> list[str]:
    cells = ["" for _ in range(len(bounds) - 1)]
    for word in sorted(words, key=lambda item: item.x0):
        column = 0
        for index in range(1, len(bounds)):
            if word.cx < bounds[index]:
                column = index - 1
                break
        else:
            column = len(cells) - 1
        cells[column] = f"{cells[column]} {word.text}".strip()
    return cells


def rows_from_words(words: list[Word]) -> list[list[str]]:
    """Собрать строки таблицы из слов OCR по их геометрии."""
    words = [word for word in words if word.text.strip()]
    if not words:
        raise ReadError("OCR не нашёл текста на изображении. Нужен более резкий скан.")

    median_height = _median([word.height for word in words])
    median_char = _median([word.width / max(len(word.text), 1) for word in words])

    grouped = _group_rows(words, ROW_TOLERANCE * median_height)
    cells_per_row = [
        _merge_cells(row, CELL_GAP * median_char) for row in grouped
    ]
    header_index = _find_header(cells_per_row)
    if header_index is None:
        raise ReadError(
            "Не нашёл строку заголовка таблицы («Обозначение», «Наименование», "
            "«Кол.»). Сфотографируйте таблицу целиком и ровно либо пришлите CSV/XLSX."
        )

    header_cells = cells_per_row[header_index]
    centers = [(left + right) / 2 for left, right, _ in header_cells]
    if len(centers) < 3:
        raise ReadError(
            "В заголовке распознано меньше трёх колонок. Нужен скан лучше "
            "или ручное сопоставление через --map на CSV/XLSX."
        )
    bounds = _column_bounds(centers)

    rows: list[list[str]] = [[text for _, _, text in header_cells]]
    for row in grouped[header_index + 1 :]:
        rows.append(_assign(row, bounds))

    while len(rows) > 1:
        last = rows[-1]
        filled = [cell for cell in last if cell.strip()]
        joined = " ".join(filled)
        if len(filled) < 2 or FOOTER_RE.match(joined):
            rows.pop()
            continue
        break
    return rows


def fix_designation(text: str) -> str:
    """Поправить типичные ошибки OCR в обозначениях: О→0, З→3, В→8."""
    if not text:
        return text
    parts = re.split(r"([.\-/\s]+)", text)
    fixed: list[str] = []
    for part in parts:
        if part and _NUMERIC_SEGMENT_RE.fullmatch(part):
            # Одиночная «В» может быть настоящей буквой в обозначении,
            # а «ООЗ» или «ОО1» — почти наверняка цифры.
            use_digits = any(char.isdigit() for char in part) or len(part) >= 2
            fixed.append(part.translate(_DIGIT_MAP if use_digits else _ZERO_MAP))
        else:
            fixed.append(part)
    return "".join(fixed)


def read_ocr_table(path: str | Path) -> Table:
    """Распознать скан/PDF и вернуть таблицу для обычного конвейера."""
    file_path = Path(path)
    if not file_path.exists():
        raise ReadError(f"Файл не найден: {file_path}")
    engine = available_engine()
    if engine is None:
        raise OCRUnavailable(engine_help())

    with tempfile.TemporaryDirectory(prefix="gost-docs-ocr-") as tmp:
        pages = _page_images(file_path, Path(tmp))
        prepared = [_deskew(page, Path(tmp)) for page in pages]
        all_rows: list[list[str]] = []
        total_words = 0
        for page in prepared:
            page_words = _recognize(page, engine)
            total_words += len(page_words)
            if not page_words:
                continue
            page_rows = rows_from_words(page_words)
            if all_rows and page_rows and page_rows[0] == all_rows[0]:
                page_rows = page_rows[1:]  # повтор шапки на следующей странице
            all_rows.extend(page_rows)
    if not all_rows:
        raise ReadError("OCR не нашёл текста. Нужен более резкий скан или фотография ровнее.")

    return Table(
        source=file_path,
        rows=all_rows,
        row_numbers=list(range(1, len(all_rows) + 1)),
        fmt="ocr",
        encoding=None,
        delimiter=None,
        sheet=None,
        meta={"ocr": {"engine": engine, "pages": len(pages), "words": total_words}},
    )
