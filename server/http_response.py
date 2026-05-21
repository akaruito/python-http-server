"""
HTTP Response — формирование корректных HTTP/1.1 ответов.

Собирает статусную строку, заголовки и тело в байтовый буфер
для отправки через TCP-сокет.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


# Стандартные фразы для кодов, которые поддерживает сервер
STATUS_PHRASES: dict[int, str] = {
    200: "OK",
    400: "Bad Request",
    404: "Not Found",
    500: "Internal Server Error",
}


@dataclass
class HTTPResponse:
    """Исходящий HTTP-ответ, готовый к сериализации в байты."""

    status_code: int = 200
    """Код состояния: 200, 404 или 500."""

    headers: dict[str, str] = field(default_factory=dict)
    """Дополнительные заголовки ответа."""

    body: bytes = b""
    """Тело ответа."""

    def set_header(self, name: str, value: str) -> None:
        """Установить или перезаписать заголовок."""
        self.headers[name] = value

    def set_body(self, body: bytes, content_type: str) -> None:
        """Задать тело и связанные заголовки Content-Type / Content-Length."""
        self.body = body
        self.set_header("Content-Type", content_type)
        self.set_header("Content-Length", str(len(body)))

    def set_text(self, text: str, content_type: str = "text/plain; charset=utf-8") -> None:
        """Удобная запись текстового тела в UTF-8."""
        self.set_body(text.encode("utf-8"), content_type)

    def to_bytes(self) -> bytes:
        """
        Сериализовать ответ в формат HTTP/1.1.

        Формат:
            HTTP/1.1 <код> <фраза>\\r\\n
            Заголовок: значение\\r\\n
            ...
            \\r\\n
            <тело>
        """
        phrase = STATUS_PHRASES.get(self.status_code, "Unknown")
        lines: list[str] = [f"HTTP/1.1 {self.status_code} {phrase}"]

        # Обязательные и служебные заголовки
        headers = dict(self.headers)
        if "Content-Length" not in headers and self.body:
            headers["Content-Length"] = str(len(self.body))
        if "Connection" not in headers:
            headers["Connection"] = "close"
        if self.body and "Content-Type" not in headers:
            headers["Content-Type"] = "application/octet-stream"

        for name, value in headers.items():
            lines.append(f"{name}: {value}")

        header_block = "\r\n".join(lines) + "\r\n\r\n"
        return header_block.encode("iso-8859-1") + self.body

    @classmethod
    def ok(cls, body: bytes = b"", content_type: str = "text/html; charset=utf-8") -> HTTPResponse:
        """Ответ 200 OK."""
        response = cls(status_code=200)
        if body:
            response.set_body(body, content_type)
        else:
            response.set_header("Content-Length", "0")
        return response

    @classmethod
    def not_found(cls, message: str = "Страница не найдена") -> HTTPResponse:
        """Ответ 404 Not Found."""
        response = cls(status_code=404)
        response.set_text(message, "text/plain; charset=utf-8")
        return response

    @classmethod
    def server_error(cls, message: str = "Внутренняя ошибка сервера") -> HTTPResponse:
        """Ответ 500 Internal Server Error."""
        response = cls(status_code=500)
        response.set_text(message, "text/plain; charset=utf-8")
        return response

    @classmethod
    def json(cls, data: str, status_code: int = 200) -> HTTPResponse:
        """JSON-ответ с кодом ``status_code`` (по умолчанию 200)."""
        response = cls(status_code=status_code)
        response.set_text(data, "application/json; charset=utf-8")
        return response
