"""Проверка вставки в тестовое окно (отдельный процесс tkinter), не в чужие приложения.

python tools/try_inject.py [type|clipboard]
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, "core")
from rupor import inject, winutil  # noqa: E402

TEXT = "Привет, мир! Проверка ClickHouse и API 😀\nВторая строка: ёЁ «кавычки» — тире."
TITLE = "Rupor test target"


def open_target(out: Path) -> subprocess.Popen[bytes]:
    proc = subprocess.Popen([sys.executable, "tools/target_window.py", str(out)])
    for _ in range(50):
        time.sleep(0.2)
        fg = winutil.foreground()
        if fg and fg.title == TITLE:
            time.sleep(0.4)
            return proc
    proc.kill()
    raise SystemExit("Тестовое окно не стало активным")


def guard() -> int:
    """Печатаем только в своё тестовое окно — никогда в чужие приложения. → hwnd окна
    (передаётся в expect_hwnd: если фокус уйдёт посреди печати, остаток не отправится)."""
    fg = winutil.foreground()
    if not fg or fg.title != TITLE:
        raise RuntimeError(f"СТОП: активно чужое окно ({fg.process if fg else '?'}), ввод отменён")
    return fg.hwnd


def _no_private(items: list[tuple[int, bytes]]) -> list[tuple[int, bytes]]:
    """Снимок без пометок «не в журнал Win+V» (их добавляет восстановление буфера)."""
    private = {f for f, _ in inject._private_formats()}
    return [(f, d) for f, d in items if f not in private]


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "type"
    out = Path(tempfile.gettempdir()) / "rupor_target.txt"
    out.write_text("", encoding="utf-8")
    proc = open_target(out)
    try:
        hwnd = guard()
        t0 = time.perf_counter()
        if mode == "clipboard":
            before = _no_private(inject.clipboard_snapshot())
            inject.paste_text(TEXT, expect_hwnd=hwnd)
            print("буфер восстановлен:", _no_private(inject.clipboard_snapshot()) == before)
        else:
            inject.type_text(TEXT, expect_hwnd=hwnd)
        print(f"вставка: {(time.perf_counter() - t0) * 1000:.0f} мс")
        time.sleep(0.5)
        got = out.read_text(encoding="utf-8")
        ok = got == TEXT
        print("совпадает:", ok)
        if not ok:
            print("получено:", repr(got))
        return 0 if ok else 2
    finally:
        proc.kill()


if __name__ == "__main__":
    sys.exit(main())
