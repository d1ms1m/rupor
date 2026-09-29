"""Есть ли такое слово в языке — через проверку орфографии Windows (ISpellChecker).

Нужен похожим написаниям словаря (fuzzy.py): ошибки распознавания — почти всегда
не-слова («Xenoposter», «кубернетис», «графане»), а настоящие слова, созвучные термину
(«курсор» — Cursor, «редис» — Redis, cloud — Claude), трогать нельзя. Свой словарь на
сотни тысяч словоформ не нужен: в Windows он уже есть — со всеми падежами и формами,
для русского (ru-RU) и английского (en-US), если стоит соответствующий язык.

Кириллица проверяется русским словарём, латиница — английским; слово из двух
письменностей («Xeno-браузер») — не слово. Язык не установлен или API недоступен —
``None``: вызывающий решает сам (fuzzy тогда похожих написаний не ищет — без словаря
языка «курсор» не отличить от искажения).

Все вызовы COM — в одном фоновом потоке ``rupor-spell`` (CoInitializeEx MTA), как у
UI Automation (uia.py); ответы кешируются. Слова модуль не логирует."""
from __future__ import annotations

import ctypes
import logging
import queue
import re
import sys
import threading
import time
from collections.abc import Iterable
from ctypes import HRESULT, POINTER, c_int, c_wchar_p
from typing import Any

log = logging.getLogger(__name__)

LANG_RU = "ru-RU"
LANG_EN = "en-US"
CALL_TIMEOUT_S = 2.0
WARM_TIMEOUT_S = 20.0    # прогрев и самопроверка: холодный старт COM может быть долгим
CACHE_MAX = 50_000
COINIT_MULTITHREADED = 0x0
_CLSID = "{7AB36653-1796-484B-BDFA-E74F1DB7C1DC}"   # SpellCheckerFactory

_CYR = re.compile(r"[\u0400-\u04ff]")
_LAT = re.compile(r"[A-Za-z]")


def language_of(word: str) -> str | None:
    """Словарь для слова: кириллица — ru-RU, латиница — en-US; обе сразу или ни одной — None."""
    cyr, lat = bool(_CYR.search(word)), bool(_LAT.search(word))
    if cyr == lat:
        return None
    return LANG_RU if cyr else LANG_EN


class _Com:
    """Интерфейсы spellcheck.h для comtypes (только нужные методы, в порядке vtable)."""

    def __init__(self) -> None:
        import comtypes
        from comtypes import COMMETHOD, GUID, IUnknown

        class ISpellingError(IUnknown):  # type: ignore[misc]
            _iid_ = GUID("{B7C82D61-FBE8-4B47-9B27-6C0D2E0DE0A3}")
            _methods_: list[Any] = []

        class IEnumSpellingError(IUnknown):  # type: ignore[misc]
            _iid_ = GUID("{803E3BD4-2828-4410-8290-418D1D73C762}")
            _methods_ = [
                COMMETHOD([], HRESULT, "Next",
                          (["out"], POINTER(POINTER(ISpellingError)), "value")),
            ]

        class ISpellChecker(IUnknown):  # type: ignore[misc]
            _iid_ = GUID("{B6FD0B71-E2BC-4653-8D05-F197E412770B}")
            _methods_ = [
                COMMETHOD([], HRESULT, "get_LanguageTag", (["out"], POINTER(c_wchar_p), "value")),
                COMMETHOD([], HRESULT, "Check", (["in"], c_wchar_p, "text"),
                          (["out"], POINTER(POINTER(IEnumSpellingError)), "value")),
            ]

        class ISpellCheckerFactory(IUnknown):  # type: ignore[misc]
            _iid_ = GUID("{8E018A9D-2415-4677-BF08-794EA61F94BB}")
            _methods_ = [
                COMMETHOD([], HRESULT, "get_SupportedLanguages",
                          (["out"], POINTER(POINTER(IUnknown)), "value")),
                COMMETHOD([], HRESULT, "IsSupported", (["in"], c_wchar_p, "tag"),
                          (["out"], POINTER(c_int), "value")),
                COMMETHOD([], HRESULT, "CreateSpellChecker", (["in"], c_wchar_p, "tag"),
                          (["out"], POINTER(POINTER(ISpellChecker)), "value")),
            ]

        self.comtypes = comtypes
        self.factory = comtypes.CoCreateInstance(GUID(_CLSID), interface=ISpellCheckerFactory,
                                                 clsctx=comtypes.CLSCTX_INPROC_SERVER)
        self.checkers: dict[str, Any] = {}

    def checker(self, lang: str) -> Any:
        if lang not in self.checkers:
            chk = None
            try:
                if self.factory.IsSupported(lang):
                    chk = self.factory.CreateSpellChecker(lang)
            except Exception:
                log.warning("Проверка орфографии %s недоступна", lang, exc_info=True)
            if chk is None:
                log.info("Словаря языка %s в Windows нет — похожие написания по частотным "
                         "спискам", lang)
            self.checkers[lang] = chk
        return self.checkers[lang]

    def known(self, chk: Any, word: str) -> bool:
        errors = chk.Check(word)
        try:
            first = errors.Next()
        except self.comtypes.COMError:
            return True
        return not bool(first)            # S_FALSE — ошибок нет, указатель пустой


class _Worker(threading.Thread):
    def __init__(self) -> None:
        super().__init__(name="rupor-spell", daemon=True)
        self.jobs: queue.Queue[tuple[str, list[str], dict[str, bool | None],
                                     threading.Event]] = queue.Queue()
        self.com: _Com | None = None
        self.broken = False

    def run(self) -> None:
        try:
            ctypes.OleDLL("ole32").CoInitializeEx(None, COINIT_MULTITHREADED)
        except OSError:
            pass                          # поток уже в MTA
        prev = getattr(sys, "coinit_flags", None)
        sys.coinit_flags = COINIT_MULTITHREADED  # type: ignore[attr-defined]
        try:
            self.com = _Com()
        except Exception:
            self.broken = True
            log.warning("Проверка орфографии Windows недоступна — похожие написания по "
                        "частотным спискам", exc_info=True)
        finally:
            if prev is None:
                try:
                    del sys.coinit_flags  # type: ignore[attr-defined]
                except AttributeError:
                    pass
            else:
                sys.coinit_flags = prev  # type: ignore[attr-defined]
        while True:
            lang, words, out, done = self.jobs.get()
            try:
                chk = self.com.checker(lang) if self.com is not None else None
                for w in words:
                    out[w] = None if chk is None else self.com.known(chk, w)  # type: ignore[union-attr]
            except Exception:
                log.warning("Проверка орфографии не удалась", exc_info=True)
            finally:
                done.set()


BACKOFF_S = 60.0   # не ответила вовремя — столько не ждём её вовсе (диктовка не тормозит)

_lock = threading.Lock()
_worker: _Worker | None = None
_cache: dict[str, bool | None] = {}
_backoff_until = 0.0


def _get_worker() -> _Worker | None:
    global _worker
    with _lock:
        if _worker is None:
            _worker = _Worker()
            _worker.start()
        return None if _worker.broken else _worker


def ready() -> bool:
    """Словари Windows подняты и отвечают — ответам можно верить надолго (fuzzy запоминает
    их только тогда: иначе ответ «по частотным спискам» закрепился бы до смены словаря)."""
    w = _worker
    return (w is not None and not w.broken and w.com is not None
            and time.monotonic() >= _backoff_until)


def known_words(words: Iterable[str]) -> dict[str, bool | None]:
    """Слово → есть ли оно в словаре своего языка (True/False), None — неизвестно
    (нет словаря языка, API недоступен или не ответил вовремя). Слово из двух
    письменностей — False."""
    return _known(words, CALL_TIMEOUT_S, backoff=True)


def _known(words: Iterable[str], timeout: float, backoff: bool) -> dict[str, bool | None]:
    out: dict[str, bool | None] = {}
    todo: dict[str, list[str]] = {}
    for w in words:
        if w in out:
            continue
        hit = _cache.get(w, ...)
        if hit is not ...:
            out[w] = hit
            continue
        lang = language_of(w)
        if lang is None:
            out[w] = False if _CYR.search(w) and _LAT.search(w) else None
            continue
        todo.setdefault(lang, []).append(w)
    if not todo:
        return out
    global _backoff_until
    worker = _get_worker() if time.monotonic() >= _backoff_until else None
    for lang, ws in todo.items():
        res: dict[str, bool | None] = {}
        if worker is not None:
            done = threading.Event()
            worker.jobs.put((lang, ws, res, done))
            if not done.wait(timeout):
                if backoff:
                    _backoff_until = time.monotonic() + BACKOFF_S
                    log.warning("Проверка орфографии не ответила за %.0f с — %.0f с без неё",
                                timeout, BACKOFF_S)
                worker = None
                for w in ws:
                    out[w] = None             # опоздавшие ответы не кешируем: гонка с потоком
                continue
        for w in ws:
            v = res.get(w)
            out[w] = v
            if worker is not None and w in res:
                if len(_cache) >= CACHE_MAX:
                    _cache.clear()
                _cache[w] = v
    return out


def is_word(word: str) -> bool | None:
    return known_words([word]).get(word)


def warm_up() -> None:
    """Поднять поток и словари заранее (в фоне), чтобы первая диктовка не ждала COM."""
    threading.Thread(target=lambda: _known(["тест", "test"], WARM_TIMEOUT_S, backoff=False),
                     name="rupor-spell-warm", daemon=True).start()


def selftest() -> tuple[bool, str]:
    """Для ``--uia-selftest``: проверка орфографии Windows работает в этой сборке (comtypes,
    интерфейсы spellcheck.h). «орфография: ok (ru да, en да)»; словаря языка на машине может
    не быть — это не ошибка сборки (похожих написаний тогда нет, только точный словарь).
    Словарь языка есть — ответы должны быть верными: слово — да, не-слово — нет."""
    # Слово и не-слово каждого языка: словарь есть — ответы должны быть верными
    probes = {LANG_RU: ("редис", "кубернетис"), LANG_EN: ("cloud", "xenoposter")}
    got = _known([w for pair in probes.values() for w in pair], WARM_TIMEOUT_S, backoff=False)
    w = _get_worker()
    if w is None or w.com is None:
        return False, "орфография: ошибка (API недоступно)"
    present: dict[str, bool] = {}
    for lang, (real, fake) in probes.items():
        if w.com.checkers.get(lang) is None:
            present[lang] = False                 # словаря языка на машине нет
            continue
        if got.get(real) is not True or got.get(fake) is not False:
            return False, f"орфография: ошибка (неверные ответы {lang})"
        present[lang] = True

    def yn(v: bool) -> str:
        return "да" if v else "нет"
    return True, f"орфография: ok (ru {yn(present[LANG_RU])}, en {yn(present[LANG_EN])})"
