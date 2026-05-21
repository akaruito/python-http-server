"""
Static File Handler — отдача всех файлов из корневого каталога статики.
"""

from __future__ import annotations

from pathlib import Path

from server.error_pages import ErrorPageRenderer
from server.http_request import HTTPRequest
from server.http_response import HTTPResponse

MIME_TYPES: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class StaticFileHandler:
    """Обработчик файлов из каталога статики (document root)."""

    def __init__(
        self,
        static_dir: Path,
        index_files: list[str] | None = None,
        error_pages: ErrorPageRenderer | None = None,
    ) -> None:
        self.static_dir = static_dir.resolve()
        self.index_files = index_files or ["index.html", "index.htm"]
        self._errors = error_pages or ErrorPageRenderer()

        if not self.static_dir.is_dir():
            raise FileNotFoundError(
                f"Каталог статики не найден: {self.static_dir}",
            )

    def can_handle(self, request: HTTPRequest) -> bool:
        return request.method == "GET"

    def handle(self, request: HTTPRequest) -> HTTPResponse:
        url_path = request.path
        if ".." in url_path.split("/"):
            return self._errors.response(404, "Недопустимый путь")

        file_path = self._resolve_path(url_path)
        if file_path is None:
            return self._errors.response(404, f"Файл не найден: {url_path}")

        if not self._is_inside_static(file_path):
            return self._errors.response(404, "Доступ запрещён")

        if not file_path.is_file():
            return self._errors.response(404, f"Файл не найден: {url_path}")

        content_type = self._guess_content_type(file_path)
        try:
            data = file_path.read_bytes()
        except OSError:
            return self._errors.response(500, "Не удалось прочитать файл")

        return HTTPResponse.ok(data, content_type)

    def _resolve_path(self, url_path: str) -> Path | None:
        relative = url_path.lstrip("/")

        if not relative:
            return self._first_existing(self._index_candidates(""))

        direct = self.static_dir / relative
        if direct.is_file():
            return direct

        if direct.is_dir():
            found = self._first_existing(self._index_candidates(relative))
            if found is not None:
                return found

        if not Path(relative).suffix:
            html_path = self.static_dir / f"{relative}.html"
            if html_path.is_file():
                return html_path
            htm_path = self.static_dir / f"{relative}.htm"
            if htm_path.is_file():
                return htm_path

            found = self._first_existing(self._index_candidates(relative))
            if found is not None:
                return found

        return None

    def _index_candidates(self, relative_dir: str) -> list[Path]:
        candidates: list[Path] = []
        for name in self.index_files:
            if relative_dir:
                candidates.append(self.static_dir / relative_dir / name)
            else:
                candidates.append(self.static_dir / name)
        return candidates

    def _first_existing(self, paths: list[Path]) -> Path | None:
        for path in paths:
            if path.is_file():
                return path
        return None

    def _is_inside_static(self, file_path: Path) -> bool:
        try:
            file_path.resolve().relative_to(self.static_dir)
            return True
        except ValueError:
            return False

    @staticmethod
    def _guess_content_type(file_path: Path) -> str:
        suffix = file_path.suffix.lower()
        return MIME_TYPES.get(suffix, "application/octet-stream")
