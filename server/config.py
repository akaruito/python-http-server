"""
Конфигурация сервера — загрузка из JSON-файла и слияние с аргументами CLI.

Приоритет: значения из командной строки перекрывают файл конфигурации.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from server.error_pages import ErrorPagesConfig

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"

# Стандартные порты HTTP/HTTPS
STANDARD_HTTP_PORT = 80
STANDARD_HTTPS_PORT = 443
DEFAULT_DEV_HTTP_PORT = 8080
DEFAULT_DEV_HTTPS_PORT = 8443


@dataclass
class SSLConfig:
    """Параметры TLS/SSL."""

    enabled: bool = False
    auto_generate: bool = False
    """
    При True сертификат создаётся в ``certs/.auto-generated/``;
    поля ``cert_file`` и ``key_file`` из конфига не используются.
    """

    cert_file: Path = field(default_factory=lambda: Path("certs/server.pem"))
    """Только при ``auto_generate=false``."""

    key_file: Path = field(default_factory=lambda: Path("certs/server.key"))
    """Только при ``auto_generate=false``."""

    cert_days: int = 365
    cert_cn: str = "localhost"

    serve_http: bool = False
    """
    При включённом SSL дополнительно слушать обычный HTTP на ``http_port``
    (например 80 параллельно с HTTPS на 443).
    """


@dataclass
class ServerConfig:
    """Параметры HTTP-сервера."""

    host: str = "127.0.0.1"
    http_port: int = DEFAULT_DEV_HTTP_PORT
    https_port: int = DEFAULT_DEV_HTTPS_PORT
    port: int | None = None
    """Устаревший общий порт: перекрывает http_port или https_port в зависимости от SSL."""

    static_dir: Path = field(default_factory=lambda: Path("static"))
    workers: int = 8
    index_files: list[str] = field(
        default_factory=lambda: ["index.html", "index.htm"],
    )
    verbose: bool = False
    ssl: SSLConfig = field(default_factory=SSLConfig)
    error_pages: ErrorPagesConfig = field(default_factory=ErrorPagesConfig)

    def resolve_static_dir(self, base_dir: Path) -> Path:
        """Абсолютный путь к каталогу статики."""
        path = self.static_dir
        if not path.is_absolute():
            path = base_dir / path
        return path.resolve()

    def listen_endpoints(self) -> list[tuple[str, int]]:
        """
        Список сокетов для прослушивания: ``(схема, порт)``.

        Примеры:
            только HTTP  → ``[("http", 8080)]``
            только HTTPS → ``[("https", 8443)]``
            оба (80+443) → ``[("http", 80), ("https", 443)]`` при ``serve_http`` и SSL.
        """
        endpoints: list[tuple[str, int]] = []

        if self.ssl.enabled:
            https_port = self.https_port
            if self.port is not None:
                https_port = self.port

            endpoints.append(("https", https_port))

            if self.ssl.serve_http:
                http_port = self.http_port
                endpoints.insert(0, ("http", http_port))
        else:
            http_port = self.http_port
            if self.port is not None:
                http_port = self.port
            endpoints.append(("http", http_port))

        return endpoints

    def apply_standard_ports(self) -> None:
        """Выставить порты 80 (HTTP) и 443 (HTTPS) — типичный продакшен-вариант."""
        self.http_port = STANDARD_HTTP_PORT
        self.https_port = STANDARD_HTTPS_PORT
        self.port = None


def _parse_ssl_config(data: dict) -> SSLConfig:
    """Разобрать секцию ``ssl`` из JSON."""
    ssl_data = data.get("ssl")
    if ssl_data is None:
        return SSLConfig()
    if not isinstance(ssl_data, dict):
        raise ValueError("Поле ssl должно быть объектом")

    return SSLConfig(
        enabled=bool(ssl_data.get("enabled", False)),
        auto_generate=bool(ssl_data.get("auto_generate", False)),
        cert_file=Path(ssl_data.get("cert_file", "certs/server.pem")),
        key_file=Path(ssl_data.get("key_file", "certs/server.key")),
        cert_days=int(ssl_data.get("cert_days", 365)),
        cert_cn=str(ssl_data.get("cert_cn", "localhost")),
        serve_http=bool(ssl_data.get("serve_http", False)),
    )


def load_config_file(path: Path) -> dict:
    """Прочитать JSON-конфиг; вернуть пустой dict, если файла нет."""
    if not path.is_file():
        logger.debug("Файл конфигурации не найден: %s", path)
        return {}

    try:
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Не удалось прочитать конфиг {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Конфиг должен быть JSON-объектом: {path}")

    return data


def config_from_dict(data: dict, base_dir: Path) -> ServerConfig:
    """Собрать ServerConfig из словаря."""
    static_dir = data.get("static_dir", "static")
    index_files = data.get("index_files", ["index.html", "index.htm"])

    if not isinstance(index_files, list) or not all(isinstance(x, str) for x in index_files):
        raise ValueError("index_files должен быть списком строк")

    ssl = _parse_ssl_config(data)

    # Порты: http_port / https_port / legacy port / use_standard_ports
    use_standard = bool(data.get("use_standard_ports", False))

    http_port = int(data["http_port"]) if "http_port" in data else DEFAULT_DEV_HTTP_PORT
    https_port = int(data["https_port"]) if "https_port" in data else DEFAULT_DEV_HTTPS_PORT
    legacy_port = int(data["port"]) if "port" in data else None

    error_pages = ErrorPagesConfig.from_dict(data.get("error_pages"), base_dir)

    config = ServerConfig(
        host=str(data.get("host", "127.0.0.1")),
        http_port=http_port,
        https_port=https_port,
        port=legacy_port,
        static_dir=Path(static_dir),
        workers=int(data.get("workers", 8)),
        index_files=index_files,
        verbose=bool(data.get("verbose", False)),
        ssl=ssl,
        error_pages=error_pages,
    )

    if use_standard:
        config.apply_standard_ports()

    if ssl.enabled and not ssl.auto_generate:
        cert = ssl.cert_file if ssl.cert_file.is_absolute() else base_dir / ssl.cert_file
        key = ssl.key_file if ssl.key_file.is_absolute() else base_dir / ssl.key_file
        if not cert.is_file():
            raise ValueError(f"SSL включён, но сертификат не найден: {cert}")
        if not key.is_file():
            raise ValueError(f"SSL включён, но ключ не найден: {key}")

    return config


def load_config(
    config_path: Path | None = None,
    base_dir: Path | None = None,
) -> ServerConfig:
    """Загрузить конфигурацию из файла."""
    root = base_dir or Path(__file__).resolve().parent.parent
    path = config_path or (root / "config.json")

    if config_path is not None and not path.is_file():
        raise ValueError(f"Указанный конфиг не найден: {path}")

    data = load_config_file(path)
    return config_from_dict(data, root)


def merge_with_cli(
    config: ServerConfig,
    *,
    host: str | None = None,
    port: int | None = None,
    http_port: int | None = None,
    https_port: int | None = None,
    static_dir: Path | None = None,
    workers: int | None = None,
    verbose: bool | None = None,
    ssl_enabled: bool | None = None,
    ssl_auto_generate: bool | None = None,
    ssl_serve_http: bool | None = None,
    ssl_cert_file: Path | None = None,
    ssl_key_file: Path | None = None,
    use_standard_ports: bool | None = None,
) -> ServerConfig:
    """Перекрыть поля конфига значениями из CLI."""
    if host is not None:
        config.host = host
    if http_port is not None:
        config.http_port = http_port
        config.port = None
    if https_port is not None:
        config.https_port = https_port
        if config.ssl.enabled:
            config.port = None
    if port is not None:
        config.port = port
    if static_dir is not None:
        config.static_dir = static_dir
    if workers is not None:
        config.workers = workers
    if verbose is not None:
        config.verbose = verbose
    if ssl_enabled is not None:
        config.ssl.enabled = ssl_enabled
    if ssl_auto_generate is not None:
        config.ssl.auto_generate = ssl_auto_generate
    if ssl_serve_http is not None:
        config.ssl.serve_http = ssl_serve_http
    if ssl_cert_file is not None:
        config.ssl.cert_file = ssl_cert_file
    if ssl_key_file is not None:
        config.ssl.key_file = ssl_key_file
    if use_standard_ports is True:
        config.apply_standard_ports()
    return config
