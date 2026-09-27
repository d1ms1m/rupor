"""Рассылка текста в отмеченные RDP-сессии: активировать → напечатать → вернуть фокус.

Рассылка идёт ТОЛЬКО в открытые окна RDP-клиентов, чьи ключи сессий есть в
``Settings.broadcast_targets`` (белый список; ключ — ``winutil.rdp_session_key``: для mstsc —
имя сервера из заголовка, для mRemoteNG — «mRemoteNG - <файл подключений>», для RDCMan —
«RDCMan» (не зависит от выбранной вкладки), для прочих клиентов — заголовок целиком; без
учёта регистра).
Ни одной отмеченной открытой сессии — ничего не рассылается (движок покажет notice).

Пока идёт печать, проверяется, что активно именно это RDP-окно: если фокус ушёл (щелчок,
Alt+Tab, окно разрыва mstsc), остаток текста в чужое окно не печатается, а рассылка
прерывается — оставшиеся сессии попадают в failed.

Ограничение: рассылка идёт по окнам верхнего уровня. Вкладки mRemoteNG и RDCMan — одно окно,
текст получит только активная вкладка."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from . import inject, winutil
from .config import Settings

log = logging.getLogger(__name__)


@dataclass
class BroadcastReport:
    sent: list[str]      # ключи сессий, куда текст ушёл
    failed: list[str]


def session_key(wi: winutil.WindowInfo) -> str:
    return winutil.rdp_session_key(wi.title, wi.process, wi.cls)


def selected(s: Settings) -> set[str]:
    """Отмеченные сессии (ключи без учёта регистра)."""
    return {k.casefold() for k in s.broadcast_targets}


def targets(s: Settings) -> list[winutil.WindowInfo]:
    """Открытые RDP-окна отмеченных сессий (в z-порядке)."""
    chosen = selected(s)
    if not chosen:
        return []
    return [wi for wi in winutil.list_rdp_windows(s.rdp_classes, s.rdp_processes)
            if session_key(wi).casefold() in chosen]


def target_keys(s: Settings) -> list[str]:
    """Ключи сессий, куда уйдёт рассылка (событие recording.targets), без повторов."""
    out: list[str] = []
    for wi in targets(s):
        k = session_key(wi)
        if all(k.casefold() != x.casefold() for x in out):
            out.append(k)
    return out


def send_all(text: str, s: Settings) -> BroadcastReport:
    origin = winutil.foreground()
    rep = BroadcastReport([], [])
    wins = targets(s)
    if not wins:
        log.info("Рассылка: нет открытых отмеченных RDP-сессий")
        return rep
    inject.wait_modifiers_released()
    aborted = False
    for i, wi in enumerate(wins):
        key = session_key(wi)
        try:
            if not winutil.activate(wi.hwnd):
                rep.failed.append(key)
                log.warning("Рассылка: не удалось активировать окно сессии")
                continue
            time.sleep(0.15)  # mstsc нужно время, чтобы подхватить ввод
            inject.type_text(text, delay_ms=s.rdp_type_delay_ms, chunk=s.type_chunk,
                             expect_hwnd=wi.hwnd)
            time.sleep(0.05)
            rep.sent.append(key)
        except inject.FocusLost:
            # Пользователь (или окно разрыва) увёл фокус — дальше не воюем за фокус
            rep.failed.extend(session_key(x) for x in wins[i:])
            log.warning("Рассылка прервана: фокус ушёл из окна сессии")
            aborted = True
            break
        except OSError as e:
            rep.failed.append(key)
            log.warning("Рассылка в сессию не удалась: %s", e)
    if origin and not aborted:
        winutil.activate(origin.hwnd)
    log.info("Рассылка: отправлено %d, ошибок %d", len(rep.sent), len(rep.failed))
    return rep
