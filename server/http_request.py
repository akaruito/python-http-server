"""
HTTP Request — модель входящего HTTP-запроса.

Хранит разобранные поля запроса: метод, путь, query-параметры,
заголовки и тело. Используется роутером и обработчиками.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class HTTPRequest:
    """Представление одного HTTP/1.1 запроса от клиента."""

    method: str
    """HTTP-метод: GET, POST и т.д."""

    path: str
    """Путь без query-строки, например ``/about``."""

    query_params: Mapping[str, list[str]]
    """Параметры URL: имя → список значений (один ключ может повторяться)."""

    headers: Mapping[str, str]
    """Заголовки в нижнем регистре для удобного поиска."""

    body: bytes
    """Тело запроса (для POST), может быть пустым."""

    http_version: str = "HTTP/1.1"
    """Версия протокола из стартовой строки."""

    raw_path: str = ""
    """Исходный путь из запроса, включая ``?query``."""

    def header(self, name: str, default: str | None = None) -> str | None:
        """Вернуть значение заголовка по имени (регистр не важен)."""
        return self.headers.get(name.lower(), default)

    def query(self, name: str, default: str | None = None) -> str | None:
        """Первое значение query-параметра или ``default``."""
        values = self.query_params.get(name)
        if not values:
            return default
        return values[0]

    @property
    def content_type(self) -> str | None:
        """Content-Type из заголовков, если указан."""
        return self.header("content-type")

    @property
    def content_length(self) -> int:
        """Длина тела из заголовка Content-Length (0, если нет)."""
        raw = self.header("content-length")
        if raw is None:
            return 0
        try:
            return int(raw)
        except ValueError:
            return 0
