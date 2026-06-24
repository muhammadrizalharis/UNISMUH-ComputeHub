"""Logging terpusat untuk aplikasi (stdout + berkas dengan rotasi)."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

_configured = False

_FMT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _resolve_level(default: int) -> int:
    """Ambil level dari settings (string -> int); fallback ke default."""
    try:
        from app.core.config import settings

        return logging.getLevelName(settings.LOG_LEVEL.upper())  # type: ignore[return-value]
    except Exception:  # noqa: BLE001 - logging tidak boleh menggagalkan startup
        return default


def _file_handler() -> logging.Handler | None:
    """Buat RotatingFileHandler dari settings; None bila dimatikan/gagal."""
    try:
        from app.core.config import settings

        if not settings.LOG_TO_FILE:
            return None
        log_dir = settings.log_dir_path
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_dir / settings.LOG_FILE,
            maxBytes=settings.LOG_MAX_BYTES,
            backupCount=settings.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(_FMT, _DATEFMT))
        return handler
    except Exception:  # noqa: BLE001 - jangan jatuhkan app hanya karena log file
        return None


def setup_logging(level: int = logging.INFO) -> None:
    """Konfigurasi root logger sekali saja (stdout + berkas dengan rotasi)."""
    global _configured
    if _configured:
        return

    fmt = logging.Formatter(_FMT, _DATEFMT)
    handlers: list[logging.Handler] = []

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(fmt)
    handlers.append(stdout_handler)

    file_handler = _file_handler()
    if file_handler is not None:
        handlers.append(file_handler)

    root = logging.getLogger()
    root.setLevel(_resolve_level(level))
    root.handlers[:] = handlers

    # Kurangi noise dari library pihak ketiga
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
