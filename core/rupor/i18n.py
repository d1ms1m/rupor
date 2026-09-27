"""Язык сообщений ядра: русский или английский (settings.language).

Все тексты, которые видит пользователь (notice.text, ошибки WS-команд, тексты ValueError
проверки настроек, ошибки загрузок, Credential Manager, вставки, трей старого режима,
названия и описания стилей), берутся из каталогов ``locales/ru.json`` и ``locales/en.json``
через ``tr(key, **params)``. Ключи в каталогах одинаковые (tests/test_i18n.py).
Журналы (log.*) остаются русскими.

Язык интерфейса:
- ``language`` в настройках: ``system`` | ``ru`` | ``en``;
- ``system`` — русский, если язык интерфейса Windows (GetUserDefaultUILanguage) русский,
  белорусский, украинский или казахский, иначе английский;
- смена — на лету (``set_language`` из Engine при загрузке и при смене настройки):
  следующий ``tr`` уже на новом языке, подписчики (``add_listener``) узнают о смене.

Подстановки — ``str.format``: ``tr("eng.mic_unavailable", error=e)`` для шаблона
``"Микрофон недоступен: {error}"``; фигурные скобки самого текста в каталогах удвоены
(``{{id, cmd, args}}``). Недостающий параметр остаётся в тексте как ``{name}``, а не роняет
вызывающего.

Множественное число — ``tp(key, n, **params)``: формы лежат в каталоге ключами
``<key>.<форма>`` по категориям CLDR (как ``Intl.PluralRules`` в интерфейсе): ru —
``one/few/many/other``, en — ``one/other``; ``{n}`` — число по правилам языка
(«Sent to 1 RDP session» / «Sent to 2 RDP sessions», «в 5 RDP-сессий»).

Текст, который хранится и показывается позже (последняя ошибка GPU для ``cuda_check``),
держат как ``Msg(key, **params)``: ``str(msg)`` переводит на язык, который действует
в момент показа, а не в момент ошибки.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

RU = "ru"
EN = "en"
UI_LANGS: tuple[str, ...] = (RU, EN)            # разрешённый язык интерфейса
SYSTEM = "system"
LANGUAGES: tuple[str, ...] = (SYSTEM, RU, EN)   # значения настройки language
DEFAULT_LANG = RU                               # запасной каталог, если ключа нет

# Основные языки Windows (PRIMARYLANGID), для которых «Системный» — русский:
# русский, белорусский, украинский, казахский
_RU_FAMILY = frozenset({0x19, 0x23, 0x22, 0x3F})

LOCALES_DIR = Path(__file__).resolve().parent / "locales"

_lock = threading.Lock()
_catalogs: dict[str, dict[str, str]] = {}
_setting = SYSTEM
_lang: str | None = None                        # None — ещё не разрешён (лениво)
_listeners: list[Callable[[str], None]] = []
_system_cache: str | None = None

_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")


# ---------- системный язык ----------

def lang_for_langid(langid: int) -> str:
    """LANGID Windows → ru (русский, белорусский, украинский, казахский) или en."""
    return RU if (langid & 0x3FF) in _RU_FAMILY else EN


def _detect_system() -> str:
    """Язык интерфейса Windows (GetUserDefaultUILanguage); ошибка — en."""
    try:
        import ctypes
        langid = int(ctypes.windll.kernel32.GetUserDefaultUILanguage())
    except Exception:  # не Windows или вызов недоступен
        log.debug("GetUserDefaultUILanguage недоступна — язык интерфейса английский")
        return EN
    return lang_for_langid(langid)


def system_language() -> str:
    """Язык интерфейса Windows, приведённый к ru/en (кэшируется на процесс)."""
    global _system_cache
    if _system_cache is None:
        _system_cache = _detect_system()
    return _system_cache


def resolve(setting: str | None) -> str:
    """Значение настройки language → разрешённый язык ru/en."""
    if setting in UI_LANGS:
        return str(setting)
    return system_language()


# ---------- текущий язык ----------

def current() -> str:
    """Разрешённый язык интерфейса сейчас: ``ru`` или ``en`` (State.ui_language)."""
    global _lang
    lang = _lang
    if lang is None:
        lang = resolve(_setting)
        _lang = lang
    return lang


def setting() -> str:
    """Текущее значение настройки language (system | ru | en)."""
    return _setting


def set_language(value: str | None) -> bool:
    """Применить настройку language (system | ru | en; неизвестное — system).
    True — разрешённый язык сменился (подписчики уже уведомлены)."""
    global _setting, _lang
    value = value if value in LANGUAGES else SYSTEM
    new = resolve(value)
    with _lock:
        old = _lang
        _setting = str(value)
        _lang = new
        listeners = list(_listeners)
    if old == new:
        return False
    log.info("Язык интерфейса ядра: %s (настройка %s)", new, value)
    for fn in listeners:
        try:
            fn(new)
        except Exception:
            log.exception("Подписчик смены языка упал")
    return True


def add_listener(fn: Callable[[str], None]) -> None:
    """fn(новый язык) — после каждой смены разрешённого языка."""
    with _lock:
        _listeners.append(fn)


def remove_listener(fn: Callable[[str], None]) -> None:
    with _lock:
        if fn in _listeners:
            _listeners.remove(fn)


# ---------- каталоги ----------

def _load(lang: str) -> dict[str, str]:
    path = LOCALES_DIR / f"{lang}.json"
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.error("Каталог сообщений %s не прочитан: %s", path.name, e)
        return {}
    if not isinstance(raw, dict):
        log.error("Каталог сообщений %s: ожидается JSON-объект", path.name)
        return {}
    return {str(k): str(v) for k, v in raw.items()
            if isinstance(v, str) and not str(k).startswith("_")}


def catalog(lang: str) -> dict[str, str]:
    """Каталог ``locales/<lang>.json`` (ключи ``_…`` — комментарии, пропускаются)."""
    cat = _catalogs.get(lang)
    if cat is None:
        with _lock:
            cat = _catalogs.get(lang)
            if cat is None:
                cat = _load(lang)
                _catalogs[lang] = cat
    return cat


def reload() -> None:
    """Сбросить кэш каталогов (тесты, правка каталога без перезапуска)."""
    with _lock:
        _catalogs.clear()


class _Params(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _format(template: str, params: dict[str, Any]) -> str:
    """Подстановка всегда (фигурные скобки текста в каталогах удвоены: ``{{id}}``)."""
    try:
        return template.format_map(_Params(params))
    except (ValueError, IndexError, AttributeError, KeyError, TypeError):
        log.warning("Шаблон сообщения не подставился (%d симв.)", len(template))
        return template


def has(key: str, lang: str | None = None) -> bool:
    return key in catalog(lang or current())


def tr_in(lang: str, key: str, /, **params: Any) -> str:
    """Сообщение на заданном языке; нет ключа — из русского каталога, нет и там — сам ключ."""
    template = catalog(lang).get(key)
    if template is None:
        template = catalog(DEFAULT_LANG).get(key)
        if template is None:
            log.warning("Нет сообщения «%s» в каталогах", key)
            return key
    return _format(template, params)


def tr(key: str, /, **params: Any) -> str:
    """Сообщение на текущем языке интерфейса."""
    return tr_in(current(), key, **params)


def tr_or(key: str, fallback: str, /, **params: Any) -> str:
    """Сообщение, если ключ есть в каталоге текущего языка, иначе fallback (как есть)."""
    template = catalog(current()).get(key)
    return fallback if template is None else _format(template, params)


# ---------- множественное число ----------

PLURAL_FORMS: tuple[str, ...] = ("zero", "one", "two", "few", "many", "other")
# Категории CLDR, которые бывают у языка (у ru other — дробные числа: «1,5 сессии»)
PLURAL_CATEGORIES: dict[str, tuple[str, ...]] = {
    RU: ("one", "few", "many", "other"),
    EN: ("one", "other"),
}


def plural_form(n: float, lang: str | None = None) -> str:
    """Категория множественного числа CLDR для числа n: ru — one (1, 21), few (2–4, 22),
    many (0, 5–20, 25), other (дробные); en — one (1), other."""
    lang = lang or current()
    whole = float(n).is_integer()
    if lang == RU:
        if not whole:
            return "other"
        i = abs(int(n))
        if i % 10 == 1 and i % 100 != 11:
            return "one"
        if 2 <= i % 10 <= 4 and not 12 <= i % 100 <= 14:
            return "few"
        return "many"
    return "one" if whole and abs(int(n)) == 1 else "other"


def plural_base(key: str) -> str | None:
    """«eng.rdp_sent.one» → «eng.rdp_sent»; ключ не формы множественного числа → None."""
    base, _, form = key.rpartition(".")
    return base if base and form in PLURAL_FORMS else None


def _plural_template(lang: str, key: str, n: float) -> str | None:
    cat = catalog(lang)
    for form in (plural_form(n, lang), "other", "many"):
        template = cat.get(f"{key}.{form}")
        if template is not None:
            return template
    return None


def tp_in(lang: str, key: str, n: float, /, **params: Any) -> str:
    """Сообщение с числом n на заданном языке: форма ``<key>.<категория>``; ``{n}`` —
    число по правилам языка (fmt_num). Нет форм — из русского каталога, нет и там — ключ."""
    template = _plural_template(lang, key, n)
    if template is None:
        template = _plural_template(DEFAULT_LANG, key, n)
        if template is None:
            log.warning("Нет форм сообщения «%s» в каталогах", key)
            return key
    decimals = 0 if float(n).is_integer() else 1
    return _format(template, {"n": fmt_num(n, decimals, lang), **params})


def tp(key: str, n: float, /, **params: Any) -> str:
    """Сообщение с числом на текущем языке: ``tp("eng.rdp_sent", 2)`` → «Sent to 2 RDP
    sessions» / «Отправлено в 2 RDP-сессии»."""
    return tp_in(current(), key, n, **params)


# ---------- отложенный перевод ----------

class Msg:
    """Сообщение, которое переводится при показе (``str``), а не при создании: хранит ключ
    и параметры. Для текстов, которые ядро запоминает и отдаёт позже (последняя ошибка
    GPU), — после смены языка они показываются уже на новом."""

    __slots__ = ("key", "params")

    def __init__(self, key: str, /, **params: Any) -> None:
        self.key = key
        self.params = params

    def __str__(self) -> str:
        return tr(self.key, **self.params)

    def __repr__(self) -> str:
        return f"Msg({self.key!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Msg) and (self.key, self.params) == (other.key, other.params)

    def __hash__(self) -> int:
        return hash(self.key)


# ---------- числа и язык текста ----------

def fmt_num(value: float, decimals: int = 0, lang: str | None = None) -> str:
    """Число по правилам языка: ru — «1 234,5» (разряды через неразрывный пробел),
    en — «1,234.5»."""
    s = f"{value:,.{decimals}f}"
    if (lang or current()) == RU:
        s = s.replace(",", " ").replace(".", ",")
    return s


def text_language(text: str) -> str:
    """Грубо: есть кириллица — ru, иначе en (для проверки очистки без распознавания)."""
    return RU if _CYRILLIC_RE.search(text or "") else EN


# ---------- самопроверка сборки ----------

def catalog_problems(cats: dict[str, dict[str, str]]) -> list[str]:
    """Расхождения каталогов: разные ключи (формы множественного числа сравниваются по
    основе), недостающие или невозможные для языка формы. Пусто — каталоги согласованы."""
    problems: list[str] = []
    bases: dict[str, set[str]] = {}
    plural: dict[str, dict[str, set[str]]] = {}
    for lang, cat in cats.items():
        if not cat:
            problems.append(f"{lang}: empty catalog")
        out = bases.setdefault(lang, set())
        forms = plural.setdefault(lang, {})
        for key in cat:
            base = plural_base(key)
            if base is None:
                out.add(key)
            else:
                out.add(base)
                forms.setdefault(base, set()).add(key.rsplit(".", 1)[1])
    langs = list(cats)
    for lang in langs[1:]:
        if bases[lang] != bases[langs[0]]:
            problems.append(f"{lang}: keys differ from {langs[0]}")
    names = set().union(*(set(f) for f in plural.values())) if plural else set()
    for lang in langs:
        need = set(PLURAL_CATEGORIES.get(lang, ("one", "other")))
        for base in sorted(names):
            got = plural[lang].get(base, set())
            if got != need:
                problems.append(f"{lang}: {base} has forms {sorted(got)}, needs {sorted(need)}")
    return problems


def selftest() -> tuple[bool, str]:
    """Каталоги на месте и согласованы (для --uia-selftest)."""
    cats = {lang: catalog(lang) for lang in UI_LANGS}
    ok = not catalog_problems(cats)
    sizes = ", ".join(f"{lang} {len(c)}" for lang, c in cats.items())
    return ok, f"локализация: {'ok' if ok else 'нет'} ({sizes})"
