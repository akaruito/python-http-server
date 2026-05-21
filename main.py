#!/usr/bin/env python3
"""
Точка входа: запуск HTTP-сервера из командной строки.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from server.config import DEFAULT_CONFIG_PATH, load_config, merge_with_cli
from server.server_core import HTTPServer
from server.ssl_support import SSLError

PROJECT_ROOT = Path(__file__).resolve().parent


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="HTTP/1.1 сервер на Python (TCP, без фреймворков)",
    )
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Устаревший общий порт (перекрывает http/https в зависимости от режима)",
    )
    parser.add_argument(
        "--http-port",
        type=int,
        default=None,
        help="Порт HTTP (по умолчанию 8080, стандартный 80)",
    )
    parser.add_argument(
        "--https-port",
        type=int,
        default=None,
        help="Порт HTTPS при --ssl (по умолчанию 8443, стандартный 443)",
    )
    parser.add_argument(
        "--standard-ports",
        action="store_true",
        default=None,
        help="Использовать порты 80 (HTTP) и 443 (HTTPS)",
    )
    parser.add_argument("--static-dir", type=Path, default=None)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("-v", "--verbose", action="store_true", default=None)

    ssl_group = parser.add_argument_group("TLS/SSL")
    ssl_group.add_argument("--ssl", action="store_true", default=None)
    ssl_group.add_argument(
        "--ssl-auto-generate",
        action="store_true",
        default=None,
        help="Сертификат в certs/.auto-generated/ (cert_file/key_file игнорируются)",
    )
    ssl_group.add_argument(
        "--ssl-serve-http",
        action="store_true",
        default=None,
        help="Параллельно слушать HTTP (например 80) вместе с HTTPS",
    )
    ssl_group.add_argument("--ssl-cert", type=Path, default=None)
    ssl_group.add_argument("--ssl-key", type=Path, default=None)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        config = load_config(config_path=args.config, base_dir=PROJECT_ROOT)
    except ValueError as exc:
        logging.error("%s", exc)
        return 1

    verbose = args.verbose if args.verbose is not None else config.verbose
    merge_with_cli(
        config,
        host=args.host,
        port=args.port,
        http_port=args.http_port,
        https_port=args.https_port,
        static_dir=args.static_dir,
        workers=args.workers,
        verbose=verbose,
        ssl_enabled=args.ssl,
        ssl_auto_generate=args.ssl_auto_generate,
        ssl_serve_http=args.ssl_serve_http,
        ssl_cert_file=args.ssl_cert,
        ssl_key_file=args.ssl_key,
        use_standard_ports=True if args.standard_ports else None,
    )

    configure_logging(config.verbose)
    static_path = config.resolve_static_dir(PROJECT_ROOT)

    for scheme, port in config.listen_endpoints():
        if port < 1024:
            logging.warning(
                "Порт %s (%s) < 1024 — на Linux/macOS может понадобиться запуск от root "
                "или setcap cap_net_bind_service.",
                port,
                scheme,
            )

    try:
        server = HTTPServer.from_config(config, static_path)
    except (FileNotFoundError, SSLError, OSError) as exc:
        logging.error("%s", exc)
        return 1

    try:
        server.start()
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Остановка по Ctrl+C")
        server.stop()
    except (SSLError, OSError) as exc:
        logging.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
