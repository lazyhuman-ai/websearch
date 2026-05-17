from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import get_settings


def configure_logging() -> None:
    settings = get_settings()
    level_name = settings.log_level.upper().strip()
    level = getattr(logging, level_name, logging.INFO)
    root_logger = logging.getLogger()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    log_dir = Path(settings.log_dir)
    if not log_dir.is_absolute():
        log_dir = Path.cwd() / log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / settings.log_file_name

    if root_logger.handlers:
        root_logger.setLevel(level)
        for handler in root_logger.handlers:
            handler.setLevel(level)
        return

    root_logger.setLevel(level)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=settings.log_file_max_bytes,
        backupCount=settings.log_file_backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)


def truncate_for_log(value: object, max_chars: int | None = None) -> str:
    settings = get_settings()
    limit = max_chars or settings.log_payload_chars
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"
