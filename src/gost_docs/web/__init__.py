"""Локальный веб-интерфейс для ведомости покупных изделий."""

from __future__ import annotations

from .app import app, create_app, main

__all__ = ["app", "create_app", "main"]
