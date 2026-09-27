"""UI Automation (uia.py) на СОБСТВЕННОМ невидимом окне Win32 Edit.

Окно создаётся в отдельном потоке с циклом сообщений и никогда не показывается; фокус
не трогается — элемент берётся по hwnd (ElementFromHandle). Поля пользователя здесь не
читаются: ``focused_field()`` (элемент с фокусом) в тестах не вызывается с настоящим
фокусом — это ручная проверка (``python -m rupor --uia-selftest``, итог в логе)."""
from __future__ import annotations

import os
import sys
import time

import pytest

from rupor import uia

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="UI Automation — только Windows")


@pytest.fixture(scope="module", autouse=True)
def _uia_ready() -> None:
    pytest.importorskip("comtypes")
    if not uia.available():
        pytest.skip(f"UI Automation недоступна: {uia._worker.error}")


def test_reads_own_edit_by_handle() -> None:
    with uia.HiddenEdit("Привет, метабейс") as ed:
        f = uia.field_from_handle(ed.hwnd)
        assert f is not None
        assert f.pid == os.getpid()
        assert f.control_type in (uia.UIA_EDIT, uia.UIA_DOCUMENT)
        assert f.runtime_id                       # непустой, у разных полей — разный
        assert f.read_text() == "Привет, метабейс"
        ed.set_text("Привет, Metabase\r\nвторая строка")
        assert f.read_text() == "Привет, Metabase\r\nвторая строка"
        with uia.HiddenEdit("другое") as ed2:
            f2 = uia.field_from_handle(ed2.hwnd)
            assert f2 is not None and f2.runtime_id != f.runtime_id


def test_password_field_is_never_read() -> None:
    with uia.HiddenEdit("секрет", style=uia.ES_PASSWORD) as ed:
        assert uia.field_from_handle(ed.hwnd) is None


def test_readonly_field_is_skipped() -> None:
    with uia.HiddenEdit("только чтение", style=uia.ES_READONLY) as ed:
        assert uia.field_from_handle(ed.hwnd) is None


def test_limit_for_long_text() -> None:
    long = "слово " * 50
    with uia.HiddenEdit(long) as ed:
        f = uia.field_from_handle(ed.hwnd)
        assert f is not None
        assert f.read_text() == long
        got = f.read_text(limit=100)             # длиннее лимита: не весь текст
        assert got is None or len(got) <= 100


@pytest.mark.parametrize("n", [uia.VALUE_CLIP, 6000, 15000])
def test_edit_longer_than_value_clip_is_read_whole(n: int) -> None:
    """ValuePattern поля Win32 Edit отдаёт не больше 4096 символов: длинный текст должен
    читаться целиком (через TextPattern), а не обрезанным — иначе вставленный в конец
    фрагмент не находится и слово на границе попадает в снимок обрезанным."""
    text = ("строка про клик хаус и метабейс " * 600)[:n - 8] + "Metabase"
    with uia.HiddenEdit(text) as ed:
        f = uia.field_from_handle(ed.hwnd)
        assert f is not None
        got = f.read_text()
        assert got is not None and len(got) == n
        assert got.endswith("Metabase") and got == text


def test_timeouts_are_set() -> None:
    assert uia._worker.timeouts                   # IUIAutomation2 есть с Windows 8


def test_hung_call_does_not_block_callers() -> None:
    """Зависший вызов: ждущий получает UiaError по таймауту, следующие — сразу, без очереди."""
    t0 = time.monotonic()
    with pytest.raises(uia.UiaError):
        uia._worker.call(lambda: time.sleep(0.6), timeout=0.1)
    with pytest.raises(uia.UiaError):
        uia._worker.call(lambda: 1, timeout=0.05)
    assert time.monotonic() - t0 < 0.5
    time.sleep(0.7)                               # зависший вызов закончился — работаем дальше
    assert uia._worker.call(lambda: 42) == 42


def test_selftest_does_not_include_field_text(monkeypatch: pytest.MonkeyPatch) -> None:
    # Элемент с фокусом подменён: тест не смотрит в окна пользователя
    monkeypatch.setattr(uia._worker, "focus_summary", lambda: (50004, True, 17))
    ok, summary = uia.selftest()
    assert ok, summary
    assert "UIA: ok" in summary and "тип 50004" in summary and "длина 17" in summary
    assert "своё поле: ok" in summary and "ClickHouse" not in summary


def test_text_before_caret_of_own_edit() -> None:
    """Контекст окна для подсказки: текст ПЕРЕД курсором (не после), с лимитом."""
    with uia.HiddenEdit("Первое. Второе предложение, курсор тут и дальше") as ed:
        ed.set_caret(15)
        got = uia.context_from_handle(ed.hwnd)
        assert got == (os.getpid(), "Первое. Второе ")
        ed.set_caret(1000)                            # в конец
        assert uia.context_from_handle(ed.hwnd, limit=9) == (os.getpid(), " и дальше")


def test_text_before_caret_never_from_password() -> None:
    with uia.HiddenEdit("секрет", style=uia.ES_PASSWORD) as ed:
        ed.set_caret(3)
        assert uia.context_from_handle(ed.hwnd) is None
