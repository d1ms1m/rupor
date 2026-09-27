"""Защиты вставки на уровне функций движка: проверка выделения перед заменой, способ
копирования выделения, рассылка при потере фокуса, удалённые окна.

Всё, что шлёт ввод или трогает буфер (inject.*, winutil.activate), подменено — тесты ничего
не печатают в окна пользователя."""
from __future__ import annotations

import types
from typing import Any

import pytest

from rupor import broadcast, engine, inject, winutil
from rupor._win import VK_RIGHT
from rupor.config import MODE_CLIPBOARD, MODE_TYPE, Settings
from rupor.engine import Delivery, read_selection, replace_text, resolve_mode

NOTEPAD = winutil.WindowInfo(10, "Notepad", "Заметки", 1, "notepad.exe")


class Input:
    """Что движок отправил бы в окно вместо настоящего SendInput/буфера."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, selected: str | None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.selected = selected
        monkeypatch.setattr(inject, "select_left",
                            lambda n, **kw: self.calls.append(("select", n)))
        monkeypatch.setattr(inject, "copy_selection", self.copy)
        monkeypatch.setattr(inject, "press_key", lambda vk: self.calls.append(("key", vk)))
        monkeypatch.setattr(inject, "paste_text",
                            lambda text, ms, **kw: self.calls.append(("paste", text)))
        monkeypatch.setattr(inject, "type_text",
                            lambda text, **kw: self.calls.append(("type", text)))

    def copy(self, timeout_ms: int = 400, via: Any = inject.COPY_INSERT, **_kw: Any) -> str | None:
        self.calls.append(("copy", via))
        return self.selected


def test_replace_checks_selection_first(monkeypatch: pytest.MonkeyPatch) -> None:
    inp = Input(monkeypatch, "сырой текст ")
    d = Delivery(ok=True, hwnd=10, mode=MODE_CLIPBOARD, info=NOTEPAD)
    assert replace_text(12, "Чистый текст. ", d, Settings(), expected="сырой текст ") is True
    assert inp.calls == [("select", 12), ("copy", (inject.COPY_INSERT, inject.COPY_CTRL_C)),
                         ("paste", "Чистый текст. ")]


@pytest.mark.parametrize("selected", [
    None,                     # выделение не прочитать (RDP без общего буфера, пустое поле)
    "т…сырой текст ",         # автозамена «...»→«…» укоротила вставленное: захвачен чужой символ
    "A5\tB5\tC5\r\n",         # Excel: Shift+← расширил диапазон ячеек
])
def test_replace_refuses_wrong_selection(monkeypatch: pytest.MonkeyPatch,
                                         selected: str | None) -> None:
    inp = Input(monkeypatch, selected)
    d = Delivery(ok=True, hwnd=10, mode=MODE_TYPE, info=NOTEPAD)
    assert replace_text(12, "Чистый. ", d, Settings(), expected="сырой текст ") is False
    assert ("key", VK_RIGHT) in inp.calls            # выделение снято
    assert not any(k in ("paste", "type") for k, _ in inp.calls)   # поверх ничего не вставлено


def test_replace_accepts_crlf_from_clipboard(monkeypatch: pytest.MonkeyPatch) -> None:
    Input(monkeypatch, "1. раз\r\n2. два ")
    d = Delivery(ok=True, hwnd=10, mode=MODE_TYPE, info=NOTEPAD)
    assert replace_text(12, "x", d, Settings(), expected="1. раз\n2. два ") is True


@pytest.mark.parametrize("info, vias", [
    (NOTEPAD, (inject.COPY_INSERT, inject.COPY_CTRL_C)),
    (winutil.WindowInfo(1, "Chrome_WidgetWin_1", "VS Code", 1, "Code.exe"),
     (inject.COPY_INSERT,)),     # встроенный терминал: Ctrl+C — SIGINT
    (winutil.WindowInfo(1, "WindowsForms10", "mRemoteNG", 1, "mRemoteNG.exe"),
     (inject.COPY_INSERT,)),     # вкладка SSH (PuTTY внутри)
    (winutil.WindowInfo(1, "TscShellContainerClass", "srv", 1, "mstsc.exe"),
     (inject.COPY_INSERT,)),     # удалённая консоль
    (winutil.WindowInfo(1, "RAIL_WINDOW", "Excel (удалённый)", 1, "mstsc.exe"),
     (inject.COPY_INSERT,)),
])
def test_selection_is_read_without_ctrl_c_where_it_interrupts(
        monkeypatch: pytest.MonkeyPatch, info: winutil.WindowInfo,
        vias: tuple[str, ...]) -> None:
    inp = Input(monkeypatch, "текст")
    assert read_selection(info, Settings()) == "текст"
    assert inp.calls == [("copy", vias)]


def test_remote_windows_are_typed_not_pasted() -> None:
    s = Settings()
    for info in (winutil.WindowInfo(1, "RAIL_WINDOW", "Word (RemoteApp)", 1, "mstsc.exe"),
                 winutil.WindowInfo(1, "Transparent Windows Client", "Citrix", 1,
                                    "wfica32.exe"),
                 winutil.WindowInfo(1, "WindowsForms10", "ВМ", 1, "vmconnect.exe")):
        assert resolve_mode(info, s) == MODE_TYPE
    # в рассылку «во все RDP» они не попадают — там только RDP-клиенты
    assert not winutil.is_rdp("RAIL_WINDOW", "x.exe", s.rdp_classes, s.rdp_processes)


def test_deliver_passes_expected_window(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(winutil, "foreground", lambda: NOTEPAD)
    monkeypatch.setattr(winutil, "blocked_by_uipi", lambda info: False)
    monkeypatch.setattr(inject, "paste_text",
                        lambda text, ms, expect_hwnd=None: seen.update(hwnd=expect_hwnd))
    d = engine.deliver("текст ", Settings(), False, lambda *a, **k: None)
    assert d.ok and seen["hwnd"] == NOTEPAD.hwnd   # фокус ушёл — остаток не уйдёт в чужое


def test_broadcast_stops_when_focus_is_lost(monkeypatch: pytest.MonkeyPatch) -> None:
    wins = [winutil.WindowInfo(i, "TscShellContainerClass", f"srv{i}", i, "mstsc.exe")
            for i in (1, 2, 3)]
    activated: list[int] = []
    typed: list[int | None] = []
    monkeypatch.setattr(winutil, "foreground", lambda: NOTEPAD)
    monkeypatch.setattr(winutil, "list_rdp_windows", lambda c, p: wins)
    monkeypatch.setattr(winutil, "activate", lambda hwnd: activated.append(hwnd) or True)
    monkeypatch.setattr(inject, "wait_modifiers_released", lambda: None)
    monkeypatch.setattr(broadcast, "time", types.SimpleNamespace(sleep=lambda s: None))

    def type_text(text: str, delay_ms: int = 0, chunk: int = 32,
                  expect_hwnd: int | None = None) -> None:
        typed.append(expect_hwnd)
        if expect_hwnd == 2:
            raise inject.FocusLost("фокус ушёл")

    monkeypatch.setattr(inject, "type_text", type_text)
    rep = broadcast.send_all("текст", Settings(broadcast_targets=["srv1", "SRV2", "srv3"]))
    assert rep.sent == ["srv1"] and rep.failed == ["srv2", "srv3"]
    assert typed == [1, 2]                  # в каждое окно — с проверкой фокуса
    assert activated == [1, 2]              # за фокус дальше не воюем и не возвращаем его
