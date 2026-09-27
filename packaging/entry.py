r"""Точка входа собранного ядра (PyInstaller): rupor-core.exe → rupor.__main__.main().

До импорта faster-whisper подключает папки с DLL CUDA (rupor.fetch.add_cuda_dll_dirs):
в сборке их нет, они скачиваются при первом запуске в %LOCALAPPDATA%\Rupor\cuda
(для отладки — переменная RUPOR_CUDA_DIRS). Необработанное исключение пишется
в %APPDATA%\Rupor\logs\crash.log: у оконной сборки нет консоли, а окно с трассировкой
PyInstaller отключено, чтобы фоновое ядро ничего не показывало поверх окон пользователя.
"""
from __future__ import annotations

import os
import sys
import time
import traceback


def _crash_log(text: str) -> None:
    try:
        d = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Rupor", "logs")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "crash.log"), "a", encoding="utf-8") as f:
            f.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} rupor-core, pid {os.getpid()} ---\n")
            f.write(text + "\n")
    except OSError:
        pass


def run() -> int:
    try:
        from rupor import fetch
        fetch.add_cuda_dll_dirs()
        from rupor.__main__ import main
        return main()
    except KeyboardInterrupt:
        return 130
    except Exception:
        text = traceback.format_exc()
        _crash_log(text)
        if sys.stderr is not None:
            sys.stderr.write(text)
        return 1


if __name__ == "__main__":
    sys.exit(run())
