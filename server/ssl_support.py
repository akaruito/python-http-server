"""
TLS/SSL — загрузка сертификатов и автогенерация самоподписанного сертификата.

При ``auto_generate`` пути из конфига (cert_file/key_file) не используются —
файлы всегда создаются в ``certs/.auto-generated/``.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import ssl
from pathlib import Path

from server.config import SSLConfig

logger = logging.getLogger(__name__)

# Фиксированный каталог автогенерации (относительно корня проекта)
AUTO_GENERATED_DIR = Path("certs/.auto-generated")
AUTO_GENERATED_CERT = "server.pem"
AUTO_GENERATED_KEY = "server.key"


class SSLError(Exception):
    """Ошибка настройки или использования TLS."""


def auto_generated_paths(base_dir: Path) -> tuple[Path, Path]:
    """
    Пути к самоподписанному сертификату и ключу (всегда одни и те же).

    Не зависят от cert_file/key_file в config.json.
    """
    directory = (base_dir / AUTO_GENERATED_DIR).resolve()
    return (
        directory / AUTO_GENERATED_CERT,
        directory / AUTO_GENERATED_KEY,
    )


def resolve_manual_ssl_paths(ssl_config: SSLConfig, base_dir: Path) -> tuple[Path, Path]:
    """Пути из конфига — только когда ``auto_generate`` выключен."""
    cert = ssl_config.cert_file
    key = ssl_config.key_file
    if not cert.is_absolute():
        cert = base_dir / cert
    if not key.is_absolute():
        key = base_dir / key
    return cert.resolve(), key.resolve()


def ensure_certificate(ssl_config: SSLConfig, base_dir: Path) -> tuple[Path, Path]:
    """
    Подготовить файлы сертификата и ключа.

    ``auto_generate=true``: всегда ``certs/.auto-generated/server.{pem,key}``.
    Иначе — ``cert_file`` и ``key_file`` из конфига.
    """
    if ssl_config.auto_generate:
        cert_path, key_path = auto_generated_paths(base_dir)
        if not cert_path.is_file() or not key_path.is_file():
            logger.info(
                "Автогенерация TLS в %s (cert_file/key_file из конфига игнорируются)",
                cert_path.parent,
            )
            generate_self_signed_cert(
                cert_path=cert_path,
                key_path=key_path,
                days=ssl_config.cert_days,
                common_name=ssl_config.cert_cn,
            )
        else:
            logger.debug("Используется автогенерированный сертификат: %s", cert_path)
        return cert_path, key_path

    cert_path, key_path = resolve_manual_ssl_paths(ssl_config, base_dir)
    if not cert_path.is_file():
        raise SSLError(f"Файл сертификата не найден: {cert_path}")
    if not key_path.is_file():
        raise SSLError(f"Файл ключа не найден: {key_path}")
    return cert_path, key_path


def generate_self_signed_cert(
    *,
    cert_path: Path,
    key_path: Path,
    days: int = 365,
    common_name: str = "localhost",
) -> None:
    """Создать самоподписанный сертификат и ключ (RSA 2048) через OpenSSL."""
    if shutil.which("openssl") is None:
        raise SSLError(
            "Для auto_generate нужен openssl в PATH. "
            "Либо отключите auto_generate и укажите cert_file/key_file.",
        )

    cert_path.parent.mkdir(parents=True, exist_ok=True)

    # SAN обязателен для браузеров при открытии 127.0.0.1 и localhost
    san = "subjectAltName=DNS:localhost,DNS:127.0.0.1,IP:127.0.0.1"
    command = [
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-sha256",
        "-nodes",
        "-keyout",
        str(key_path),
        "-out",
        str(cert_path),
        "-days",
        str(days),
        "-subj",
        f"/CN={common_name}",
        "-addext",
        san,
    ]

    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr or exc.stdout or str(exc)
        raise SSLError(f"openssl завершился с ошибкой: {stderr}") from exc

    logger.info(
        "Самоподписанный сертификат: %s, ключ: %s (CN=%s, %s дн.)",
        cert_path,
        key_path,
        common_name,
        days,
    )


def create_server_ssl_context(
    ssl_config: SSLConfig,
    base_dir: Path,
) -> ssl.SSLContext:
    """Создать ``SSLContext`` для сервера."""
    cert_path, key_path = ensure_certificate(ssl_config, base_dir)

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    if hasattr(ssl, "TLSVersion"):
        context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    # Браузеры (Chrome/Safari) ожидают ALPN для HTTPS
    try:
        context.set_alpn_protocols(["http/1.1"])
    except (ssl.SSLError, NotImplementedError):
        logger.debug("ALPN недоступен в этой сборке Python/OpenSSL")
    try:
        context.set_ciphers(
            "ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20:!aNULL:!MD5:!DSS",
        )
    except ssl.SSLError:
        logger.debug("Не удалось задать набор шифров, используются системные")

    return context
