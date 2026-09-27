"""Проверки буфера обмена в изолированной window station (запускается отдельным процессом
из tests/test_clipboard.py).

Процесс создаёт свою window station (у неё свой буфер обмена) и рабочий стол, переключается
на них и только потом трогает буфер — буфер пользователя (WinSta0) не меняется. Нажатия
(SendInput) не отправляются никогда: inject._send подменён, «окно-получатель» — поток,
который читает буфер сам.

Код выхода: 0 — всё прошло, 3 — изоляцию настроить не удалось (тест пропускается),
иначе — ошибка (текст в stdout)."""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
import traceback
from ctypes import wintypes as wt
from typing import Callable

u = ctypes.WinDLL("user32", use_last_error=True)
u.CreateWindowStationW.restype = wt.HANDLE
u.CreateWindowStationW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p]
u.SetProcessWindowStation.argtypes = [wt.HANDLE]
u.SetProcessWindowStation.restype = wt.BOOL
u.CreateDesktopW.restype = wt.HANDLE
u.CreateDesktopW.argtypes = [wt.LPCWSTR, wt.LPCWSTR, ctypes.c_void_p, wt.DWORD, wt.DWORD,
                             ctypes.c_void_p]
u.SetThreadDesktop.argtypes = [wt.HANDLE]
u.SetThreadDesktop.restype = wt.BOOL
u.GetClipboardSequenceNumber.restype = wt.DWORD
u.CountClipboardFormats.restype = ctypes.c_int

u.GetProcessWindowStation.restype = wt.HANDLE
u.GetUserObjectInformationW.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD,
                                        ctypes.POINTER(wt.DWORD)]
u.GetUserObjectInformationW.restype = wt.BOOL

WINSTA_ALL_ACCESS = 0x37F
GENERIC_ALL = 0x10000000
UOI_NAME = 2

_desk: int = 0
_station = ""


def _die_isolation(why: str) -> None:
    print(f"ISOLATION FAILED: {why}", flush=True)
    os._exit(3)


def _object_name(h: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    need = wt.DWORD()
    if not u.GetUserObjectInformationW(h, UOI_NAME, buf, ctypes.sizeof(buf), ctypes.byref(need)):
        return ""
    return buf.value


def _station_ok() -> bool:
    name = _object_name(u.GetProcessWindowStation())
    return bool(name) and name == _station and name.lower() != "winsta0"


def isolate() -> None:
    """Своя window station (имя даёт Windows: Service-0x0-…$ для сеанса входа) — у неё
    свой буфер обмена; интерактивная WinSta0 с буфером пользователя не затрагивается."""
    global _desk, _station
    parent_seq = int(u.GetClipboardSequenceNumber())
    hws = u.CreateWindowStationW(None, 0, WINSTA_ALL_ACCESS, None)
    if not hws:
        _die_isolation(f"window station: {ctypes.get_last_error()}")
    _station = _object_name(hws)
    if not _station or _station.lower() == "winsta0" or not u.SetProcessWindowStation(hws):
        _die_isolation(f"window station {_station!r}: {ctypes.get_last_error()}")
    hd = u.CreateDesktopW("rupor-test", None, None, 0, GENERIC_ALL, None)
    if not hd or not u.SetThreadDesktop(hd):
        _die_isolation(f"desktop: {ctypes.get_last_error()}")
    _desk = int(hd)
    if not _station_ok() or int(u.GetClipboardSequenceNumber()) == parent_seq:
        _die_isolation("буфер обмена не отделён от пользовательского")


def thread_init() -> None:
    """Каждый поток, который трогает буфер: свой рабочий стол и проверка изоляции."""
    if not _desk or not u.SetThreadDesktop(_desk) or not _station_ok():
        _die_isolation("поток не в изолированной window station")


isolate()

from rupor import _win as w  # noqa: E402
from rupor import inject  # noqa: E402

inject._thread_init = thread_init
inject.pressed_modifiers = lambda: []  # type: ignore[assignment]  # клавиатура не нужна
sent: list[list[inject.KeyEvent]] = []
on_key: list[Callable[[int], None]] = []


def fake_send(events: list[inject.KeyEvent]) -> None:
    """Вместо SendInput: запомнить и сообщить «приложению» о нажатой клавише."""
    sent.append(list(events))
    for e in events:
        if not e.flags & w.KEYEVENTF_KEYUP:
            for fn in on_key:
                fn(e.vk)


inject._send = fake_send  # type: ignore[assignment]


def in_thread(fn: Callable[[], None], delay: float) -> threading.Thread:
    def run() -> None:
        thread_init()
        time.sleep(delay)
        fn()
    th = threading.Thread(target=run, daemon=True)
    th.start()
    return th


def set_plain(text: str) -> None:
    inject.clipboard_set_text(text)


def get() -> str | None:
    return inject.clipboard_get_text()


def formats() -> set[int]:
    inject._open_clipboard()
    try:
        out: set[int] = set()
        f = 0
        while True:
            f = w.user32.EnumClipboardFormats(f)
            if not f:
                return out
            out.add(int(f))
    finally:
        w.user32.CloseClipboard()


def check(cond: bool, what: str) -> None:
    if not cond:
        raise AssertionError(what)


def test_private_formats() -> None:
    private = {f for f, _ in inject._private_formats()}
    check(len(private) == 3, f"private-форматы не зарегистрированы: {private}")
    inject.clipboard_set_text("секрет", private=True)
    check(get() == "секрет", "текст не положен")
    check(private <= formats(), "временный текст без пометок «не в журнал Win+V»")
    set_plain("обычный")
    check(not (private & formats()), "«Скопировать последнее» не должно помечать текст")
    snap = inject.clipboard_snapshot()
    set_plain("другое")
    inject.clipboard_restore(snap)
    check(get() == "обычный", "снимок не восстановлен")
    check(private <= formats(), "восстановление добавило бы запись в журнал Win+V")


def test_paste_waits_for_slow_window() -> None:
    """Окно читает буфер через 0,8 с (дольше restore_ms): вставится диктовка, не пароль."""
    set_plain("пароль")
    got: list[str | None] = []

    def app_reads() -> None:
        got.append(get())

    def on(vk: int) -> None:
        if vk == ord("V"):
            in_thread(app_reads, 0.8)

    on_key[:] = [on]
    t0 = time.monotonic()
    inject.paste_text("диктовка", restore_ms=300)
    dt = time.monotonic() - t0
    time.sleep(0.1)
    check(got == ["диктовка"], f"окно вставило {got!r} вместо диктовки")
    check(get() == "пароль", "прежний буфер не вернулся")
    check(0.8 <= dt < 3.0, f"вставка заняла {dt:.2f} с")


def test_paste_not_read_restores_anyway() -> None:
    set_plain("старое")
    on_key[:] = []
    inject.RENDER_WAIT_S = 0.4
    try:
        t0 = time.monotonic()
        inject.paste_text("никто не прочитал", restore_ms=100)
        dt = time.monotonic() - t0
    finally:
        inject.RENDER_WAIT_S = 2.0
    check(get() == "старое", "буфер не восстановлен, когда окно не прочитало вставку")
    check(dt < 1.5, f"ожидание {dt:.2f} с")


def test_paste_keeps_newer_copy() -> None:
    """Пользователь успел скопировать своё — прежний буфер поверх не возвращаем."""
    set_plain("старое")

    def app() -> None:
        got = get()
        check(got == "диктовка 2", f"окно получило {got!r}")
        inject._open_clipboard()
        try:
            w.user32.EmptyClipboard()
            inject._set_global(inject.CF_UNICODETEXT, inject._text_bytes("новое"))
        finally:
            w.user32.CloseClipboard()

    on_key[:] = [lambda vk: in_thread(app, 0.05) if vk == ord("V") else None]
    inject.paste_text("диктовка 2", restore_ms=200)
    time.sleep(0.1)
    check(get() == "новое", "затёрт текст, который пользователь скопировал сам")


def _app_sets(text: str) -> Callable[[], None]:
    def run() -> None:
        inject._open_clipboard()
        try:
            w.user32.EmptyClipboard()
            inject._set_global(inject.CF_UNICODETEXT, inject._text_bytes(text))
        finally:
            w.user32.CloseClipboard()
    return run


def test_copy_selection_ctrl_insert() -> None:
    set_plain("пароль")
    keys: list[int] = []

    def on(vk: int) -> None:
        keys.append(vk)
        if vk == w.VK_INSERT:
            in_thread(_app_sets("выделенный текст"), 0.05)

    on_key[:] = [on]
    text = inject.copy_selection(400)
    check(text == "выделенный текст", f"прочитано {text!r}")
    check(w.VK_INSERT in keys and ord("C") not in keys, f"нажатия {keys}")
    check(get() == "пароль", "буфер не восстановлен")


def test_copy_selection_falls_back_to_ctrl_c() -> None:
    """Окно не понимает Ctrl+Insert — пробуем Ctrl+C (там, где это разрешено), снимок один."""
    set_plain("пароль")
    keys: list[int] = []

    def on(vk: int) -> None:
        keys.append(vk)
        if vk == ord("C"):
            in_thread(_app_sets("через Ctrl+C"), 0.05)

    on_key[:] = [on]
    text = inject.copy_selection(200, via=(inject.COPY_INSERT, inject.COPY_CTRL_C))
    check(text == "через Ctrl+C", f"прочитано {text!r}")
    check(keys.index(w.VK_INSERT) < keys.index(ord("C")), f"порядок нажатий {keys}")
    check(get() == "пароль", "буфер не восстановлен")


def test_copy_selection_late_change_restored() -> None:
    """Буфер сменился после таймаута (медленный rdpclip) — прежний всё равно возвращается."""
    set_plain("пароль")
    on_key[:] = [lambda vk: in_thread(_app_sets("поздно"), 0.6) if vk == w.VK_INSERT else None]
    text = inject.copy_selection(300)
    check(text is None, f"прочитано {text!r}")
    deadline = time.monotonic() + 3
    while get() != "пароль" and time.monotonic() < deadline:
        time.sleep(0.05)
    check(get() == "пароль", f"буфер пользователя затёрт: {get()!r}")


def test_copy_selection_busy_clipboard_sends_nothing() -> None:
    """Буфер занят и снимок не сделать — Ctrl+C/Ctrl+Insert не шлём вовсе."""
    set_plain("пароль")
    on_key[:] = []
    opened = threading.Event()
    release = threading.Event()

    def hold() -> None:
        # Другое «приложение» держит буфер открытым (со своим окном: OpenClipboard(NULL)
        # из двух потоков одного процесса Windows не различает)
        thread_init()
        hwnd = w.user32.CreateWindowExW(0, "STATIC", "holder", 0, 0, 0, 0, 0,
                                        w.HWND_MESSAGE, None, None, None)
        if hwnd and u.OpenClipboard(hwnd):
            opened.set()
            release.wait(5)
            u.CloseClipboard()

    th = threading.Thread(target=hold, daemon=True)
    th.start()
    check(opened.wait(3), "не удалось занять буфер")
    before = len(sent)
    try:
        inject.copy_selection(300)
        raised = False
    except OSError:
        raised = True
    release.set()
    th.join(3)
    check(raised, "занятый буфер не дал ошибку")
    check(len(sent) == before, "при занятом буфере всё равно отправлено копирование")
    check(get() == "пароль", "буфер изменился")


def main() -> int:
    tests = [test_private_formats, test_paste_waits_for_slow_window,
             test_paste_not_read_restores_anyway, test_paste_keeps_newer_copy,
             test_copy_selection_ctrl_insert, test_copy_selection_falls_back_to_ctrl_c,
             test_copy_selection_late_change_restored,
             test_copy_selection_busy_clipboard_sends_nothing]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"ok   {t.__name__}", flush=True)
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}\n{traceback.format_exc()}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
