"""Логи в %APPDATA%\\Rupor\\logs с ротацией.

Всё, что уходит в лог (сообщения и трассировки исключений), проходит через
``scrub_secrets``: ключ API не должен попасть в файл, даже если оказался в тексте
исключения (например, ValueError http.client о недопустимом заголовке «Bearer <ключ>»).
"""
from __future__ import annotations

import logging
import re
import sys
from logging.handlers import RotatingFileHandler

from .config import app_dir

# Ключи OpenRouter/Anthropic (sk-or-v1-…, sk-ant-…), заголовки авторизации.
# Маска для UI «sk-or-v1-…XYZ» под правило не попадает (после «sk-» мало символов).
_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_-]{12,}|Bearer\s+\S+|x-api-key\S*)", re.IGNORECASE)


def scrub_secrets(text: str) -> str:
    """Убрать из текста всё, похожее на ключ API или заголовок авторизации."""
    return _SECRET_RE.sub("•••", text)


class ScrubFormatter(logging.Formatter):
    """Форматтер, который вычищает секреты из готовой строки (вместе с трассировкой)."""

    def format(self, record: logging.LogRecord) -> str:
        return scrub_secrets(super().format(record))


def setup(verbose: bool = False) -> None:
    d = app_dir() / "logs"
    d.mkdir(exist_ok=True)
    fmt = ScrubFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    fh = RotatingFileHandler(d / "rupor.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    for noisy in ("httpx", "httpcore", "urllib3", "filelock", "huggingface_hub", "PIL",
                  "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if sys.stderr is not None:  # под pythonw stderr нет
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)
