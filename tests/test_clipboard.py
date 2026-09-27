"""Буфер обмена по-настоящему (WinAPI), но в изолированной window station отдельного
процесса: буфер пользователя не трогается, нажатия не отправляются (см. _clip_isolated.py).

Проверяется: вставка ждёт, пока окно прочитает текст (отложенный рендеринг) — медленное окно
не вставит прежний буфер; временный текст не попадает в журнал Win+V; Ctrl+Insert вместо
Ctrl+C; поздняя смена буфера после таймаута откатывается; при занятом буфере копирование
не отправляется."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_clipboard_in_isolated_window_station() -> None:
    env = dict(os.environ, PYTHONPATH=str(ROOT / "core"), PYTHONIOENCODING="utf-8")
    cp = subprocess.run([sys.executable, str(ROOT / "tests" / "_clip_isolated.py")],
                        capture_output=True, text=True, encoding="utf-8", errors="replace",
                        timeout=120, env=env, cwd=str(ROOT))
    out = cp.stdout + cp.stderr
    if cp.returncode == 3:
        pytest.skip("Изолированную window station создать не удалось: " + out.strip())
    assert cp.returncode == 0, out
    assert out.count("ok   ") == 8, out
