from __future__ import annotations

import json
import logging
from pathlib import Path


def build_file_logger(name: str, log_path: Path) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger


def log_json(logger: logging.Logger, payload: object, *, pretty: bool = True) -> None:
    logger.info(json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None))


def log_section(logger: logging.Logger, title: str) -> None:
    logger.info("")
    logger.info("=== %s ===", title)
