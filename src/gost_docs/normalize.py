from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_SPACE_CHARS = "\u00a0\u2007\u2009\u202f\u200b"
_SPACE_MAP = {ord(char): " " for char in _SPACE_CHARS}
_DASH_RE = re.compile(r"[–—−]")
_NUMBER_RE = re.compile(r"^[-+]?\d[\d\s.,]*")

UNIT_ALIASES: dict[str, tuple[str, ...]] = {
    "шт": ("шт", "шт.", "штук", "штука", "штуки", "pcs", "pc", "ед", "ед.", "единиц", "единица"),
    "компл": ("компл", "компл.", "комплект", "комплектов", "к-т", "кт", "set"),
    "упак": ("упак", "упак.", "упаковка", "упаковок", "уп", "уп.", "пач", "пачка", "пачек", "pack"),
    "м": ("м", "м.", "метр", "метров", "пог.м", "пог м", "м/п"),
    "кг": ("кг", "кг.", "килограмм", "килограммов"),
    "л": ("л", "л.", "литр", "литров"),
    "рул": ("рул", "рул.", "рулон", "рулонов"),
    "т": ("т", "т.", "тонна", "тонн"),
}
PIECE_UNITS = frozenset({"шт", "компл", "упак"})


def clean_text(value: object) -> str:
    """Убрать неразрывные пробелы, лишние пробелы и служебные кавычки по краям."""
    if value is None:
        return ""
    text = str(value).translate(_SPACE_MAP)
    text = re.sub(r"\s+", " ", text).strip()
    return text.strip("«»\"“”';, ")


def _unit_key(value: object) -> str:
    text = clean_text(value).lower().replace("ё", "е")
    return re.sub(r"[\s.]+", "", text)


_UNIT_INDEX = {
    _unit_key(alias): canonical for canonical, aliases in UNIT_ALIASES.items() for alias in aliases
}


def normalize_designation(value: object) -> str:
    """Привести обозначение к единому виду: верхний регистр, одинаковые дефисы, без пробелов у точек."""
    text = clean_text(value).upper()
    text = _DASH_RE.sub("-", text)
    text = re.sub(r"\s*([.\-/])\s*", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .,;")


def normalize_name(value: object) -> str:
    return clean_text(value)


def parse_quantity(value: object) -> tuple[Decimal | None, str | None]:
    """Разобрать количество вида «1 200,5 шт.» → (Decimal("1200.5"), "шт.")."""
    text = clean_text(value)
    if not text:
        return None, None
    match = _NUMBER_RE.match(text)
    if not match:
        return None, None
    number = match.group(0).replace(" ", "")
    unit = clean_text(text[match.end() :]) or None
    if "," in number and "." in number:
        if number.rfind(",") > number.rfind("."):
            number = number.replace(".", "").replace(",", ".")
        else:
            number = number.replace(",", "")
    elif "," in number:
        number = number.replace(",", ".")
    elif number.count(".") > 1:
        number = number.replace(".", "")
    try:
        return Decimal(number), unit
    except InvalidOperation:
        return None, unit


def normalize_unit(value: object) -> tuple[str, bool]:
    """Вернуть (каноническая единица, известна ли она)."""
    key = _unit_key(value)
    if not key:
        return "", False
    if key in _UNIT_INDEX:
        return _UNIT_INDEX[key], True
    return clean_text(value).lower(), False


def format_quantity(value: Decimal) -> str:
    """Число для документа: без экспоненты, с запятой, без хвостовых нулей."""
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")
