"""
HTTP Parser — разбор сырых байтов HTTP/1.1 запроса.

Читает данные из сокета, находит границу заголовков,
при необходимости дочитывает тело по Content-Length
и возвращает объект HTTPRequest.
"""

from __future__ import annotations

import socket
from typing import Iterable
from urllib.parse import unquote_plus

from server.http_request import HTTPRequest

# Максимальный размер заголовков (защита от слишком больших запросов)
MAX_HEADER_SIZE = 64 * 1024

# Поддерживаемые методы
ALLOWED_METHODS = frozenset({"GET", "POST"})


class HTTPParseError(Exception):
    """Ошибка разбора HTTP-запроса (некорректный формат)."""


def _recv_until_headers(connection: socket.socket) -> bytes:
    """
    Читать из сокета порциями, пока не встретим ``\\r\\n\\r\\n``.

    Ограничиваем общий объём MAX_HEADER_SIZE байт.
    """
    buffer = bytearray()
    while True:
        chunk = connection.recv(4096)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > MAX_HEADER_SIZE:
            raise HTTPParseError("Заголовки запроса слишком большие")
        if b"\r\n\r\n" in buffer:
            break
    if not buffer:
        raise HTTPParseError("Пустое соединение")
    return bytes(buffer)


def _read_body(connection: socket.socket, already_read: bytes, content_length: int) -> bytes:
    """
    Дочитать тело запроса до ``content_length`` байт.

    ``already_read`` может уже содержать начало тела после заголовков.
    """
    if content_length <= 0:
        return b""

    body = already_read[:content_length]
    remaining = content_length - len(body)
    while remaining > 0:
        chunk = connection.recv(min(4096, remaining))
        if not chunk:
            break
        body += chunk
        remaining -= len(chunk)
    return body


def _parse_query_string(query: str) -> dict[str, list[str]]:
    """
    Разобрать query-строку вида ``a=1&b=2&a=3`` без внешних HTTP-библиотек.

    Ключи и значения декодируются как в HTML-формах (``+`` → пробел).
    """
    params: dict[str, list[str]] = {}
    if not query:
        return params

    for pair in query.split("&"):
        if not pair:
            continue
        if "=" in pair:
            key, value = pair.split("=", 1)
        else:
            key, value = pair, ""
        decoded_key = unquote_plus(key)
        decoded_value = unquote_plus(value)
        params.setdefault(decoded_key, []).append(decoded_value)
    return params


def _split_path_and_query(raw_target: str) -> tuple[str, str, str]:
    """
    Разделить цель запроса на путь, query и полный raw_path.

    Пример: ``/search?q=hello`` → (``/search``, ``q=hello``, ``/search?q=hello``)
    """
    if "?" in raw_target:
        path, query = raw_target.split("?", 1)
        raw_path = raw_target
    else:
        path, query = raw_target, ""
        raw_path = raw_target
    return path, query, raw_path


def _parse_headers(header_lines: Iterable[str]) -> dict[str, str]:
    """Преобразовать строки заголовков в словарь (ключи в нижнем регистре)."""
    headers: dict[str, str] = {}
    for line in header_lines:
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        headers[name.strip().lower()] = value.strip()
    return headers


def parse_request(connection: socket.socket) -> HTTPRequest:
    """
    Прочитать и разобрать один HTTP/1.1 запрос из TCP-соединения.

    :raises HTTPParseError: если запрос повреждён или метод не поддерживается.
    """
    raw = _recv_until_headers(connection)

    header_end = raw.find(b"\r\n\r\n")
    if header_end == -1:
        raise HTTPParseError("Не найден конец заголовков")

    header_bytes = raw[:header_end]
    body_prefix = raw[header_end + 4 :]

    try:
        header_text = header_bytes.decode("iso-8859-1")
    except UnicodeDecodeError as exc:
        raise HTTPParseError("Некорректная кодировка заголовков") from exc

    lines = header_text.split("\r\n")
    if not lines:
        raise HTTPParseError("Пустая стартовая строка")

    # Стартовая строка: METHOD /path HTTP/1.1
    request_line = lines[0]
    parts = request_line.split()
    if len(parts) != 3:
        raise HTTPParseError(f"Некорректная стартовая строка: {request_line!r}")

    method, target, http_version = parts
    method = method.upper()

    if method not in ALLOWED_METHODS:
        raise HTTPParseError(f"Метод не поддерживается: {method}")

    path, query_string, raw_path = _split_path_and_query(target)
    headers = _parse_headers(lines[1:])
    query_params = _parse_query_string(query_string)

    content_length = 0
    if "content-length" in headers:
        try:
            content_length = int(headers["content-length"])
        except ValueError as exc:
            raise HTTPParseError("Некорректный Content-Length") from exc

    body = _read_body(connection, body_prefix, content_length)

    return HTTPRequest(
        method=method,
        path=path,
        query_params=query_params,
        headers=headers,
        body=body,
        http_version=http_version,
        raw_path=raw_path,
    )
