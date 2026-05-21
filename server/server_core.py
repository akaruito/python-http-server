"""
Server Core — ядро TCP HTTP-сервера.

Поддерживает один или два порта (HTTP и/или HTTPS), в т.ч. 80 и 443.
"""

from __future__ import annotations

import logging
import socket
import ssl
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from server.config import SSLConfig, ServerConfig
from server.error_pages import ErrorPageRenderer
from server.http_parser import HTTPParseError, parse_request
from server.http_response import HTTPResponse
from server.router import Router
from server.ssl_support import SSLError, create_server_ssl_context
from server.static_handler import StaticFileHandler

logger = logging.getLogger(__name__)


class HTTPServer:
    """
    Многопоточный HTTP/1.1 сервер.

    Может слушать HTTP (порт 80), HTTPS (порт 443) или оба одновременно.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        static_dir: Path | None = None,
        workers: int = 8,
        index_files: list[str] | None = None,
        ssl_config: SSLConfig | None = None,
        ssl_base_dir: Path | None = None,
        listen_endpoints: list[tuple[str, int]] | None = None,
        error_pages: ErrorPageRenderer | None = None,
    ) -> None:
        self.host = host
        base = Path(__file__).resolve().parent.parent
        self.static_dir = (static_dir or (base / "static")).resolve()
        self.workers = workers
        self.ssl_config = ssl_config or SSLConfig()
        self.ssl_base_dir = (ssl_base_dir or base).resolve()
        self.listen_endpoints = listen_endpoints or [("http", 8080)]
        self._errors = error_pages or ErrorPageRenderer(base_dir=self.ssl_base_dir)

        static_handler = StaticFileHandler(
            self.static_dir,
            index_files=index_files,
            error_pages=self._errors,
        )
        self.router = Router(static_handler, error_pages=self._errors)

        self._listeners: list[socket.socket] = []
        self._ssl_context: ssl.SSLContext | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._running = False
        self._accept_threads: list[threading.Thread] = []

    @classmethod
    def from_config(cls, config: ServerConfig, static_dir: Path) -> HTTPServer:
        """Создать сервер из ``ServerConfig``."""
        base_dir = static_dir.parent
        error_pages = ErrorPageRenderer(config.error_pages, base_dir=base_dir)
        return cls(
            host=config.host,
            static_dir=static_dir,
            workers=config.workers,
            index_files=config.index_files,
            ssl_config=config.ssl,
            ssl_base_dir=base_dir,
            listen_endpoints=config.listen_endpoints(),
            error_pages=error_pages,
        )

    def start(self) -> None:
        """Запустить все настроенные слушатели (блокирует до остановки)."""
        if self.ssl_config.enabled:
            self._ssl_context = create_server_ssl_context(
                self.ssl_config,
                self.ssl_base_dir,
            )

        self._executor = ThreadPoolExecutor(
            max_workers=self.workers,
            thread_name_prefix="http-worker",
        )
        self._running = True

        for scheme, port in self.listen_endpoints:
            listener = self._create_listener(scheme, port)
            self._listeners.append(listener)
            thread = threading.Thread(
                target=self._accept_loop,
                args=(listener, scheme, port),
                name=f"accept-{scheme}-{port}",
                daemon=True,
            )
            self._accept_threads.append(thread)
            thread.start()

        urls = ", ".join(f"{s}://{self.host}:{p}" for s, p in self.listen_endpoints)
        logger.info(
            "Сервер запущен: %s (статика: %s)",
            urls,
            self.static_dir,
        )

        try:
            while self._running:
                for thread in self._accept_threads:
                    thread.join(timeout=0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def _create_listener(self, scheme: str, port: int) -> socket.socket:
        """Создать и привязать обычный TCP listening-сокет."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((self.host, port))
        except PermissionError as exc:
            raise OSError(
                f"Нет прав слушать порт {port} ({scheme}). "
                f"Порты <1024 (80, 443) на Unix часто требуют root или cap_net_bind_service.",
            ) from exc
        sock.listen(128)
        return sock

    def _accept_loop(
        self,
        listener: socket.socket,
        scheme: str,
        port: int,
    ) -> None:
        """Цикл accept; TLS оборачивается после accept (совместимость с браузерами)."""
        use_tls = scheme == "https"
        while self._running:
            try:
                client_socket, address = listener.accept()
            except OSError:
                if self._running:
                    logger.debug("accept завершён на %s:%s", scheme, port)
                break

            if use_tls:
                assert self._ssl_context is not None
                try:
                    client_socket = self._ssl_context.wrap_socket(
                        client_socket,
                        server_side=True,
                    )
                except ssl.SSLError as exc:
                    logger.warning(
                        "TLS handshake failed %s:%s: %s",
                        address[0],
                        address[1],
                        exc,
                    )
                    try:
                        client_socket.close()
                    except OSError:
                        pass
                    continue

            assert self._executor is not None
            self._executor.submit(self._handle_client, client_socket, address)

    def stop(self) -> None:
        """Остановить сервер."""
        self._running = False

        for listener in self._listeners:
            try:
                listener.close()
            except OSError:
                pass
        self._listeners.clear()

        self._ssl_context = None

        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=False)
            self._executor = None

        logger.info("Сервер остановлен")

    def _handle_client(
        self,
        client_socket: socket.socket,
        address: tuple[str, int],
    ) -> None:
        """Обработка одного клиента."""
        client_ip, client_port = address
        try:
            request = parse_request(client_socket)
            logger.info(
                '%s:%s — %s %s "%s"',
                client_ip,
                client_port,
                request.method,
                request.path,
                request.http_version,
            )

            response = self.router.dispatch(request)
            client_socket.sendall(response.to_bytes())

        except HTTPParseError as exc:
            logger.warning(
                "%s:%s — ошибка разбора HTTP: %s",
                client_ip,
                client_port,
                exc,
            )
            client_socket.sendall(
                self._errors.response(400, str(exc)).to_bytes(),
            )

        except ssl.SSLError as exc:
            logger.warning("%s:%s — ошибка TLS: %s", client_ip, client_port, exc)

        except Exception:
            logger.error(
                "%s:%s — необработанное исключение:\n%s",
                client_ip,
                client_port,
                traceback.format_exc(),
            )
            try:
                client_socket.sendall(self._errors.response(500).to_bytes())
            except OSError:
                pass

        finally:
            try:
                client_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                client_socket.close()
            except OSError:
                pass
