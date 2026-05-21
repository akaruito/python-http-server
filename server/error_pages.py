"""
Error Pages — HTML-страницы для кодов 400, 404, 500.

Встроенные шаблоны лежат в ``server/builtin_pages/`` (не в ``static/``).
В config.json можно указать свои файлы в секции ``error_pages``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from server.http_response import HTTPResponse, STATUS_PHRASES

logger = logging.getLogger(__name__)

# Каталог встроенных страниц (рядом с этим модулем)
BUILTIN_PAGES_DIR = Path(__file__).resolve().parent / "builtin_pages"

SUPPORTED_CODES = frozenset({400, 404, 500})

DEFAULT_MESSAGES: dict[int, tuple[str, str]] = {
    400: ("Некорректный запрос", "Сервер не смог разобрать HTTP-запрос."),
    404: ("Страница не найдена", "Запрошенный ресурс не существует."),
    500: ("Внутренняя ошибка", "Произошла ошибка при обработке запроса."),
}


@dataclass
class ErrorPagesConfig:
    """
    Пути к пользовательским страницам ошибок.

    Ключ — код ответа (400, 404, 500), значение — путь к HTML-файлу
    или ``null`` / отсутствие ключа — встроенная страница.
    """

    pages: dict[int, Path | None] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict | None, base_dir: Path) -> ErrorPagesConfig:
        if not data:
            return cls()

        pages: dict[int, Path | None] = {}
        for key, value in data.items():
            try:
                code = int(key)
            except ValueError as exc:
                raise ValueError(
                    f"error_pages: ключ должен быть кодом HTTP (400, 404, 500): {key!r}",
                ) from exc
            if code not in SUPPORTED_CODES:
                raise ValueError(
                    f"error_pages: неподдерживаемый код {code}, доступны {sorted(SUPPORTED_CODES)}",
                )
            if value is None:
                pages[code] = None
            else:
                path = Path(value)
                if not path.is_absolute():
                    path = base_dir / path
                pages[code] = path

        return cls(pages=pages)


class ErrorPageRenderer:
    """Формирует HTML-ответы для ошибок: встроенные или из конфига."""

    def __init__(
        self,
        config: ErrorPagesConfig | None = None,
        base_dir: Path | None = None,
    ) -> None:
        self._config = config or ErrorPagesConfig()
        self._base_dir = base_dir or Path(__file__).resolve().parent.parent
        self._template_cache: dict[int, str] = {}

    def response(self, status_code: int, detail: str | None = None) -> HTTPResponse:
        """
        Собрать ``HTTPResponse`` с HTML-страницей ошибки.

        :param status_code: 400, 404 или 500.
        :param detail: дополнительный текст (подставляется в ``{message}``).
        """
        if status_code not in SUPPORTED_CODES:
            status_code = 500

        html = self._render_html(status_code, detail)
        response = HTTPResponse(status_code=status_code)
        response.set_body(html.encode("utf-8"), "text/html; charset=utf-8")
        return response

    def _render_html(self, status_code: int, detail: str | None) -> str:
        template = self._load_template(status_code)
        title, default_msg = DEFAULT_MESSAGES[status_code]
        message = detail if detail else default_msg
        phrase = STATUS_PHRASES.get(status_code, "Error")

        return _apply_placeholders(
            template,
            code=str(status_code),
            title=title,
            message=message,
            phrase=phrase,
        )

    def _load_template(self, status_code: int) -> str:
        if status_code in self._template_cache:
            return self._template_cache[status_code]

        custom_path = self._config.pages.get(status_code)
        if custom_path is not None:
            template = self._read_custom_template(custom_path, status_code)
        else:
            template = self._read_builtin_template(status_code)

        self._template_cache[status_code] = template
        return template

    def _read_builtin_template(self, status_code: int) -> str:
        path = BUILTIN_PAGES_DIR / f"{status_code}.html"
        if not path.is_file():
            logger.warning("Встроенная страница %s не найдена, используется fallback", path)
            return self._fallback_template(status_code)
        return path.read_text(encoding="utf-8")

    def _read_custom_template(self, path: Path, status_code: int) -> str:
        resolved = path.resolve()
        if not resolved.is_file():
            logger.warning(
                "Кастомная страница ошибки %s не найдена, используется встроенная %s",
                resolved,
                status_code,
            )
            return self._read_builtin_template(status_code)
        try:
            return resolved.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Не удалось прочитать %s: %s", resolved, exc)
            return self._read_builtin_template(status_code)

    @staticmethod
    def _fallback_template(status_code: int) -> str:
        title, message = DEFAULT_MESSAGES.get(status_code, ("Ошибка", "Что-то пошло не так"))
        return (
            f"<!DOCTYPE html><html lang=\"ru\"><head><meta charset=\"utf-8\">"
            f"<title>{status_code}</title></head><body>"
            f"<h1>{status_code} — {title}</h1><p>{message}</p>"
            f"<p><a href=\"/\">На главную</a></p></body></html>"
        )


def _apply_placeholders(template: str, **values: str) -> str:
    """Подставить ``{key}`` без конфликта с фигурными скобками в CSS."""
    result = template
    for key, value in values.items():
        result = result.replace("{" + key + "}", value)
    return result
