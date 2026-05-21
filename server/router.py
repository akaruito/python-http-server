"""
Router — система маршрутизации HTTP-запросов.

API-маршруты обрабатываются явно; все GET-запросы отдаются
из каталога статики через ``StaticFileHandler``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from server.error_pages import ErrorPageRenderer
from server.http_request import HTTPRequest
from server.http_response import HTTPResponse

if TYPE_CHECKING:
    from server.static_handler import StaticFileHandler

logger = logging.getLogger(__name__)

RouteHandler = Callable[[HTTPRequest], HTTPResponse]

API_ROUTES: frozenset[tuple[str, str]] = frozenset({("POST", "/api/data")})


class Router:
    """Диспетчер запросов."""

    def __init__(
        self,
        static_handler: StaticFileHandler,
        error_pages: ErrorPageRenderer | None = None,
    ) -> None:
        self._static = static_handler
        self._errors = error_pages or ErrorPageRenderer()
        self._api_handlers: dict[tuple[str, str], RouteHandler] = {
            ("POST", "/api/data"): self._handle_api_data,
        }

    def dispatch(self, request: HTTPRequest) -> HTTPResponse:
        """Найти обработчик и вернуть ответ."""
        route_key = (request.method, request.path)

        if route_key in self._api_handlers:
            try:
                return self._api_handlers[route_key](request)
            except Exception:
                logger.exception(
                    "Ошибка в API-обработчике %s %s",
                    request.method,
                    request.path,
                )
                return self._errors.response(500)

        if self._static.can_handle(request):
            return self._static.handle(request)

        logger.info("Маршрут не найден: %s %s", request.method, request.path)
        return self._errors.response(
            404,
            f"Маршрут {request.method} {request.path} не поддерживается",
        )

    def _handle_api_data(self, request: HTTPRequest) -> HTTPResponse:
        """POST /api/data — JSON API (ошибки остаются в JSON, не HTML)."""
        if not request.body:
            return HTTPResponse.json(
                json.dumps({"error": "Пустое тело запроса"}, ensure_ascii=False),
            )

        content_type = request.content_type or ""
        if "application/json" not in content_type:
            return HTTPResponse.json(
                json.dumps(
                    {"error": "Ожидается Content-Type: application/json"},
                    ensure_ascii=False,
                ),
            )

        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return HTTPResponse.json(
                json.dumps({"error": "Некорректный JSON"}, ensure_ascii=False),
            )

        response_data = {
            "status": "ok",
            "received": payload,
            "message": "Данные успешно приняты",
        }
        return HTTPResponse.json(
            json.dumps(response_data, ensure_ascii=False, indent=2),
        )
