"""Личный словарь частот и подсказка распознаванию — чистая логика без Windows и без базы.

Из итоговых текстов истории (``history.text``) ядро собирает «характерные» слова
пользователя — те, которые Whisper без подсказки пишет неуверенно:

- латиница в русском тексте («Metabase», «pytest», «Redis», «K8s»);
- смешанный регистр и аббревиатуры («ClickHouse», «iPhone», «API», «СДЭК», «ВКонтакте»);
- имена и названия — кириллица с заглавной буквы не в начале предложения («Наташа», «Тимур»);
- редкие слова — строчная кириллица, которой нет среди частых русских слов
  («дашборд», «мерчантов»): они «слабые» и попадают в подсказку, только если повторяются;
- в английском тексте — редкие строчные английские слова («deployment», «webhook»): тоже
  «слабые». В таблице ``vocab`` они хранятся с меткой ``EN_WEAK_MARK`` («~deployment»):
  та же латиница посреди русской речи («pytest», «redis») — термин, «сильное» слово.

Общеупотребительные слова отсеиваются частотными списками ``data/common_ru.txt`` и
``data/common_en.txt`` (по форме и по основе — стеммер Snowball для русского, простые
окончания для английского; личные формы правильных глаголов — ``verb_forms``, частые
формы с приставкой — ``is_common_ru_prefixed``), а также списками ``learn.STOPWORDS``/
``COMMON_WORDS``/``COMMON_NAMES``. Буквы с цифрами берутся, только если похожи на название
(K8s, GPT4, iPhone15), а не на пароль («Summer2024»). Хранение (таблицы ``vocab``,
``vocab_excluded``) — в ``storage.py``.

Формы одного слова сливаются (``group_key``): без регистра и «ё», у кириллицы — по основе
Snowball («Тимуру», «Тимура», «Тимуром» — одно слово; показывается именительный падеж
«Тимур», если он встречался, иначе самая частая форма). Исключение пользователя действует
на все формы слова.

Подсказка ``initial_prompt`` (``build_prompt``) = [контекст окна: 1–2 последних
предложения перед курсором, ≤ ``CONTEXT_CHARS`` символов и ≤ ``CONTEXT_TOKENS`` токенов] +
[термины настроек и словаря] + [частые слова текущего процесса] + [общие частые слова];
всего ≤ ``PROMPT_TOKENS`` токенов Whisper. Токены считает токенизатор модели (движок
передаёт его в ``count_tokens``), без него — осторожная оценка ``estimate_tokens``
(кириллица дробится мельче латиницы: ≈ 1,45 символа на токен против 2). Частых слов —
не больше ``MAX_FREQ_WORDS``.

Слова из переписки пользователя модуль не логирует.
"""
from __future__ import annotations

import logging
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .learn import COMMON_NAMES, COMMON_WORDS, STOPWORDS
from .learn import _sentence_start as _learn_sentence_start
from .textproc import _WORD_RE, fold

log = logging.getLogger(__name__)

PROMPT_TOKENS = 200          # предел подсказки: faster-whisper оставляет её последние 223 токена
CONTEXT_CHARS = 300          # контекст окна — не длиннее
CONTEXT_TOKENS = 100         # …и не больше стольких токенов: остальное — термины и частые слова
CONTEXT_SENTENCES = 2        # …и не больше стольких последних предложений
MAX_FREQ_WORDS = 60          # частых слов в подсказке — не больше
MAX_WEAK_WORDS = 20          # …из них «слабых» (редких строчных) — не больше
MAX_AI_WORDS = 40            # частых терминов в промпте ИИ-очистки — не больше
STRONG_MIN = 2               # «сильное» слово (термин, имя) — в подсказке с такого числа повторов
WEAK_MIN = 3                 # «слабое» (редкое строчное русское) — с такого
WEAK_MIN_LEN = 5             # слабые слова короче — не собираем
MAX_WORD_LEN = 40
GROUP_STEM_MIN = 3           # основа короче — формы сливаются только по написанию («Оля», «Ян»)
VOCAB_TARGETS = frozenset({"window", "rdp_all", ""})   # history.target, из которых собираем

_DATA = Path(__file__).resolve().parent / "data"
_LATIN = re.compile(r"[a-zA-Z]")
_CYR = re.compile(r"[\u0400-\u04ff]")
_PART_SPLIT = re.compile(r"[-\u2010\u2011'\u2019]+")
# Адреса, почта, пути и имена файлов/доменов — не слова пользователя: «ivan@example.com»,
# «https://…», «C:\\temp», «report.xlsx», «example.com». Точка после кириллицы — не домен:
# «Яндекс.Go», «Яндекс.Маркет» — названия (см. _brand)
_NOISE_RE = re.compile(r"\S*[@/\\]\S*|[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\.[A-Za-z][A-Za-z0-9_-]*")
# Название с точкой одним словом: «Яндекс.Go», «Сбер.ID», «Яндекс.Маркет»
_BRAND_PAT = r"(?<![\w.])[^\W\d_]+\.[^\W\d_]+(?!\w)"
# Английские сокращения — судим по основе: «Metabase's» → Metabase, «doesn't» → does
_EN_CONTRACTION = re.compile(r"^([A-Za-z]+?)(?:n['\u2019]t|['\u2019](?:s|t|re|ve|ll|d|m))$")
# Приставки, после которых частая форма остаётся частой: «подскажи», «передай», «забудь»
_RU_PREFIXES = ("недо", "пере", "подо", "подъ", "пред", "разо", "разъ", "обо", "объ", "ото",
                "воз", "вос", "раз", "рас", "под", "при", "про", "пре", "над", "без", "бес",
                "по", "за", "на", "от", "вы", "до", "об", "из", "ис", "вз", "вс", "со", "съ",
                "не")
# Латиница в русском тексте, которая словом-термином не бывает
_EN_TINY = frozenset({"a", "an", "the", "of", "to", "in", "on", "at", "is", "it", "and", "or",
                      "ok", "okay", "vs", "etc", "eg", "ie", "id"})
# Английские слова, которые пишутся с заглавной всегда (дни, месяцы, языки): не имена
_EN_PROPER_COMMON = frozenset("""
    monday tuesday wednesday thursday friday saturday sunday january february march april
    may june july august september october november december english russian american
    british german french spanish chinese japanese european i
""".split())


# ---------- частотные списки ----------

def _read_list(name: str) -> list[str]:
    try:
        text = (_DATA / name).read_text(encoding="utf-8")
    except OSError as e:
        log.warning("Нет частотного списка %s (%s) — общие слова отсеиваются хуже", name, e)
        return []
    out: list[str] = []
    for line in text.splitlines():
        line = line.split("#", 1)[0]
        out += line.split()
    return out


ALGO_VERSION = 3   # менять при правке правил отбора слов: база пересоберёт частоты
# 3 — редкие строчные слова английского текста хранятся с меткой EN_WEAK_MARK (слабые)

# Метка «слабого» английского слова в таблице vocab (``counts``): «~deployment». В словах
# (_WORD_RE) тильды не бывает; наружу (merge, extract) слово выходит без метки.
EN_WEAK_MARK = "~"


@lru_cache(maxsize=1)
def version() -> str:
    """Версия отбора слов: правила + содержимое частотных списков. Изменилась — storage
    пересобирает частоты по истории (иначе вычитание при удалении истории разойдётся)."""
    import hashlib
    h = hashlib.sha1(str(ALGO_VERSION).encode())
    for name in ("common_ru.txt", "common_en.txt"):
        try:
            h.update((_DATA / name).read_bytes())
        except OSError:
            h.update(b"-")
    return f"{ALGO_VERSION}:{h.hexdigest()[:12]}"


@dataclass(frozen=True)
class _Common:
    ru_forms: frozenset[str]
    ru_stems: frozenset[str]
    en_forms: frozenset[str]


@lru_cache(maxsize=1)
def _common() -> _Common:
    # плюс те же списки, что у обучения словаря (learn.py)
    ru = {fold(w) for w in _read_list("common_ru.txt") if not _LATIN.search(w)}
    ru |= {w for w in STOPWORDS | COMMON_WORDS | COMMON_NAMES if not _LATIN.search(w)}
    en = {fold(w) for w in _read_list("common_en.txt") if not _CYR.search(w)}
    en |= {w for w in STOPWORDS if not _CYR.search(w)}
    stems = frozenset(s for w in ru for s in (stem_ru(w),) if len(s) >= 3)
    # Личные формы и прошедшее время глаголов списка («лежать» → лежу, лежишь, лежат…):
    # основа Snowball у них не совпадает с основой инфинитива. Только точные формы —
    # их основы не добавляем (лишние формы правильных спряжений ничего не отсеют зря).
    forms = set(ru)
    for w in ru:
        forms |= verb_forms(w)
    return _Common(frozenset(forms), stems, frozenset(en))


# ---------- формы глаголов (для отсева общих слов) ----------

_V1 = ("ю", "ешь", "ет", "ем", "ете", "ют", "й", "йте", "я")          # дела-ю, дела-ешь…
_V2 = ("у", "ю", "ишь", "ит", "им", "ите", "ат", "ят", "и", "ь", "ьте")  # леж-у, говор-ишь…
_VU = ("у", "ешь", "ет", "ем", "ете", "ут", "и", "ите")                  # верн-у, верн-ешь…
_PAST = ("л", "ла", "ло", "ли")


def verb_forms(inf: str) -> set[str]:
    """Формы правильных спряжений глагола-инфинитива (ё уже заменена на е): настоящее или
    простое будущее время, прошедшее, повелительное; возвратные — с «-ся/-сь». Для
    неправильных глаголов часть форм лишние (их нет в языке) — это безвредно: они лишь
    пополняют список частых слов. Не глагол — пустое множество."""
    refl = inf.endswith(("ся", "сь")) and len(inf) > 4
    base = inf[:-2] if refl else inf
    if not base.endswith("ть") or base.endswith("ость"):     # «новость» — не глагол
        return set()
    stem = base[:-2]                       # дела, говори, смотре, верну, откры, использова
    if len(stem) < 3:                      # мать, путь, сеть; дать, быть — в списке формами
        return set()
    out = {stem + e for e in _PAST}        # делал, говорил, смотрел, вернул, открыл
    v = stem[-1]
    if stem.endswith(("ова", "ева")) and len(stem) > 4:
        out |= {stem[:-3] + "у" + e for e in _V1}    # использовать → использую
    if v in "ая":
        out |= {stem + e for e in _V1}               # делаю, гуляю
        out |= {stem[:-1] + e for e in _V2}          # лежу, лежат; стою, стоят
    elif v == "и":
        out |= {stem[:-1] + e for e in _V2}          # говорю, говоришь, учат
    elif v == "е":
        out |= {stem + e for e in _V1}               # имею, умеешь
        out |= {stem[:-1] + e for e in _V2}          # смотрю, смотрят
    elif v == "у":
        out |= {stem[:-1] + e for e in _VU}          # верну, вернёт
    elif v == "ы":
        out |= {stem[:-1] + "о" + e for e in _V1}    # открою, закроешь
    if refl:
        out = {f + ("сь" if f[-1] in _V else "ся") for f in out}
    return out


# ---------- стеммер Snowball (русский) ----------

_V = frozenset("аеиоуыэюя")
_PERF1 = ("в", "вши", "вшись")
_PERF2 = ("ив", "ивши", "ившись", "ыв", "ывши", "ывшись")
_REFL = ("ся", "сь")
_ADJ = ("ее", "ие", "ые", "ое", "ими", "ыми", "ей", "ий", "ый", "ой", "ем", "им", "ым", "ом",
        "его", "ого", "ему", "ому", "их", "ых", "ую", "юю", "ая", "яя", "ою", "ею")
_PART1 = ("ем", "нн", "вш", "ющ", "щ")
_PART2 = ("ивш", "ывш", "ующ")
_VERB1 = ("ла", "на", "ете", "йте", "ли", "й", "л", "ем", "н", "ло", "но", "ет", "ют", "ны",
          "ть", "ешь", "нно")
_VERB2 = ("ила", "ыла", "ена", "ейте", "уйте", "ите", "или", "ыли", "ей", "уй", "ил", "ыл",
          "им", "ым", "ен", "ило", "ыло", "ено", "ят", "ует", "уют", "ит", "ыт", "ены", "ить",
          "ыть", "ишь", "ую", "ю")
_NOUN = ("а", "ев", "ов", "ие", "ье", "е", "иями", "ями", "ами", "еи", "ии", "и", "ией", "ей",
         "ой", "ий", "й", "иям", "ям", "ием", "ем", "ам", "ом", "о", "у", "ах", "иях", "ях",
         "ы", "ь", "ию", "ью", "ю", "ия", "ья", "я")
_SUPER = ("ейше", "ейш")


def _regions(w: str) -> tuple[int, int]:
    rv = len(w)
    for i, ch in enumerate(w):
        if ch in _V:
            rv = i + 1
            break
    r1 = len(w)
    for i in range(1, len(w)):
        if w[i] not in _V and w[i - 1] in _V:
            r1 = i + 1
            break
    r2 = len(w)
    for i in range(r1 + 1, len(w)):
        if w[i] not in _V and w[i - 1] in _V:
            r2 = i + 1
            break
    return rv, r2


def _cut(w: str, rv: int, g1: Sequence[str], g2: Sequence[str]) -> str | None:
    """Убрать самое длинное окончание из групп (g1 — только после «а»/«я») внутри RV."""
    best = 0
    for e in g1:
        n = len(w) - len(e)
        if len(e) > best and n - 1 >= rv and w.endswith(e) and w[n - 1] in "ая":
            best = len(e)
    for e in g2:
        n = len(w) - len(e)
        if len(e) > best and n >= rv and w.endswith(e):
            best = len(e)
    return w[:-best] if best else None


@lru_cache(maxsize=65536)
def stem_ru(word: str) -> str:
    """Основа русского слова (алгоритм Snowball, «ё» → «е»): «делает», «делать», «делал» →
    «дела»; «витрину», «витрины» → «витрин». Для латиницы — само слово в нижнем регистре."""
    w = fold(word)
    if not _CYR.search(w):
        return w
    rv, r2 = _regions(w)
    r = _cut(w, rv, _PERF1, _PERF2)
    if r is not None:
        w = r
    else:
        r = _cut(w, rv, (), _REFL)
        if r is not None:
            w = r
        r = _cut(w, rv, (), _ADJ)
        if r is not None:
            w = r
            r = _cut(w, rv, _PART1, _PART2)
            if r is not None:
                w = r
        else:
            r = _cut(w, rv, _VERB1, _VERB2)
            if r is None:
                r = _cut(w, rv, (), _NOUN)
            if r is not None:
                w = r
    if w.endswith("и") and len(w) - 1 >= rv:
        w = w[:-1]
    for e in ("ость", "ост"):
        if w.endswith(e) and len(w) - len(e) >= r2:
            w = w[:-len(e)]
            break
    if w.endswith("нн") and len(w) - 2 >= rv:
        w = w[:-1]
    else:
        r = _cut(w, rv, (), _SUPER)
        if r is not None:
            w = r
            if w.endswith("нн") and len(w) - 2 >= rv:
                w = w[:-1]
        elif w.endswith("ь") and len(w) - 1 >= rv:
            w = w[:-1]
    return w


def _en_forms(w: str) -> set[str]:
    out = {w}
    for suf, rep in (("ies", "y"), ("es", ""), ("s", ""), ("ed", ""), ("ed", "e"), ("ing", ""),
                     ("ing", "e"), ("ly", ""), ("er", ""), ("est", "")):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            out.add(w[:-len(suf)] + rep)
    return out


SELFTEST_MIN_WORDS = 1000


def selftest() -> tuple[bool, str]:
    """Для ``--uia-selftest``: частотные списки на месте (в сборке — rupor/data/*.txt)."""
    ru = len(_read_list("common_ru.txt"))
    en = len(_read_list("common_en.txt"))
    ok = ru >= SELFTEST_MIN_WORDS and en >= SELFTEST_MIN_WORDS
    return ok, f"частотные списки: {'ok' if ok else 'нет'} (ru {ru}, en {en})"


@lru_cache(maxsize=65536)
def is_common_ru(word: str) -> bool:
    c = _common()
    f = fold(word)
    if f in c.ru_forms:
        return True
    st = stem_ru(f)
    # основа — сама частая форма: «экзамене» → «экзамен» (у «экзамен» Snowball даёт «экзам»)
    return st in c.ru_stems or st in c.ru_forms


@lru_cache(maxsize=65536)
def is_common_ru_prefixed(word: str) -> bool:
    """Частая форма с приставкой: «подскажи» (скажи), «передай» (дай), «забудь» (будь).
    Только для строчных «слабых» слов: имена так не проверяем («Прохор», «Настя»)."""
    f = fold(word)
    forms = _common().ru_forms
    return any(f.startswith(p) and len(f) - len(p) >= 3 and f[len(p):] in forms
               for p in _RU_PREFIXES)


@lru_cache(maxsize=65536)
def is_common_en(word: str) -> bool:
    c = _common()
    return bool(_en_forms(fold(word)) & c.en_forms)


def is_everyday_en(word: str) -> bool:
    """Обычное английское слово: из частотного списка или из тех, что всегда пишутся
    с заглавной (дни недели, месяцы, языки — не имена и не термины)."""
    f = fold(word)
    return f in _EN_PROPER_COMMON or is_common_en(f)


# ---------- что за слово ----------

def _letters(w: str) -> str:
    return "".join(ch for ch in w if ch.isalpha())


def _caps_or_camel(w: str) -> bool:
    """API, СДЭК (все буквы заглавные, их ≥ 2) или ClickHouse, iPhone (заглавная внутри)."""
    letters = _letters(w)
    if len(letters) >= 2 and letters.isupper():
        return True
    return any(ch.isupper() for ch in w[1:]) and any(ch.islower() for ch in w)


def is_strong(word: str) -> bool:
    """«Сильное» слово (термин, имя, название): латиница, цифры или заглавные буквы.
    «Слабое» — строчная кириллица (редкое слово): в подсказке нужно больше повторов.
    Редкое строчное слово английского текста тоже слабое — это видно не по написанию,
    а по метке EN_WEAK_MARK в таблице vocab (см. ``merge``)."""
    return bool(_LATIN.search(word) or any(ch.isdigit() for ch in word)
                or any(ch.isupper() for ch in word))


def _sentence_start(text: str, pos: int) -> bool:
    return _learn_sentence_start(text, pos)


def _english_text(text: str) -> bool:
    """Английская диктовка — нет ни одной кириллической буквы. Короткая русская фраза из
    терминов («Kubernetes и Grafana») — русская: латиница в ней — термины."""
    return _CYR.search(text) is None and _LATIN.search(text) is not None


def _term_with_digits(part: str, letters: str) -> bool:
    """Буквы с цифрами — термин, только если похоже на название: аббревиатура с цифрами
    (GPT4, H264, RTX3060, 1С, COVID-19), camelCase (iPhone15, GPT-4o) или коротко (K8s,
    x86, Win11, i18n). «Summer2024», «qwerty123», «Passw0rd» — похоже на пароль: не берём
    (иначе после двух повторов он ушёл бы в промпт ИИ-очистки)."""
    if len(part) < 2:
        return False
    if letters.isupper():
        return len(part) <= 10
    if any(ch.isupper() for ch in part[1:]) and any(ch.islower() for ch in part):
        return len(part) <= 16
    return len(part) <= 6 and sum(ch.isdigit() for ch in part) <= 2


def _judge(part: str, at_start: bool, english: bool) -> str | None:
    """Характерное слово (в форме для хранения) или None."""
    letters = _letters(part)
    if not letters or len(part) > MAX_WORD_LEN:
        return None
    has_digit = any(ch.isdigit() for ch in part)
    lat, cyr = bool(_LATIN.search(part)), bool(_CYR.search(part))
    if has_digit:
        return part if _term_with_digits(part, letters) else None
    if lat and cyr:
        return part                                   # «Яндекс.Go» — как есть
    if lat:
        f = fold(part)
        if "_" in part:
            return part                               # user_id — имя из кода
        if _caps_or_camel(part):
            return None if (letters.isupper() and is_common_en(f) and len(letters) <= 4) \
                else part                             # API, ClickHouse; но не «OK», «TV»
        if not english:
            # Латиница посреди русской речи — почти всегда термин: pytest, Redis, Zoom
            if f in _EN_TINY or (part.islower() and len(letters) < 3):
                return None
            return part
        if part[:1].isupper() and not at_start:
            return None if f in _EN_PROPER_COMMON else part   # имя, продукт
        if is_common_en(f) or len(letters) < WEAK_MIN_LEN:
            return None
        return EN_WEAK_MARK + part.lower()            # редкое английское слово — слабое
    if not cyr:
        return None
    if _caps_or_camel(part):
        return None if is_common_ru(part) else part   # СДЭК, ВКонтакте; но не «СРОЧНО»
    if part[:1].isupper() and not at_start:
        return None if is_common_ru(part) else part   # имя, название
    low = part.lower()
    if len(letters) < WEAK_MIN_LEN or is_common_ru(low) or is_common_ru_prefixed(low):
        return None
    return low                                        # редкое слово (в начале — строчными)


_TOKEN_RE = re.compile(f"(?P<brand>{_BRAND_PAT})|{_WORD_RE.pattern}")


def _brand(tok: str) -> bool:
    """«Яндекс.Go», «Сбер.ID», «Яндекс.Маркет» — название; «Привет.Как» (нет пробела после
    точки) — нет: первая часть с заглавной и кириллицей, вторая — латиница или с заглавной
    после нечастого слова."""
    a, _, b = tok.partition(".")
    if not a[:1].isupper() or not _CYR.search(a):
        return False
    if _LATIN.search(b):
        return True
    return b[:1].isupper() and not is_common_ru(a)


def _parts(tok: str) -> list[str]:
    """Части слова для отбора. Составное с кириллицей и латиницей делится
    («ClickHouse-запрос» → ClickHouse, «Metabase'е» → Metabase); латинское («Wi-Fi»,
    «GPT-4o», «O'Reilly») и имя через дефис («Санкт-Петербург») — целиком; английское
    сокращение — основа («Metabase's» → Metabase)."""
    m = _EN_CONTRACTION.match(tok)
    if m:
        return [m.group(1)]
    parts = [p for p in _PART_SPLIT.split(tok) if p]
    if len(parts) < 2:
        return parts
    if not any(_CYR.search(p) for p in parts):
        return [tok]
    if all(_CYR.search(p) and not _LATIN.search(p) and p[:1].isupper() for p in parts):
        return [tok]
    return parts


def unmark(stored: str) -> tuple[str, bool]:
    """Строка таблицы vocab → (слово, слабое английское?): «~deployment» → (deployment, True)."""
    if stored.startswith(EN_WEAK_MARK):
        return stored[len(EN_WEAK_MARK):], True
    return stored, False


def extract(text: str) -> list[str]:
    """Характерные слова текста (с повторами, в порядке появления).

    Составные слова — см. ``_parts``; адреса, почта, пути и имена файлов пропускаются."""
    return [unmark(w)[0] for w in _extract(text)]


def _extract(text: str) -> list[str]:
    """Как ``extract``, но слабые английские слова — с меткой EN_WEAK_MARK (для vocab)."""
    if not text:
        return []
    text = unicodedata.normalize("NFC", text)
    clean = _NOISE_RE.sub(lambda m: " " * len(m.group(0)), text)
    english = _english_text(clean)
    out: list[str] = []

    def take(tok: str, start: int) -> None:
        at_start = _sentence_start(clean, start)
        for pos, part in enumerate(_parts(tok)):
            w = _judge(part, at_start and pos == 0, english)
            if w is not None:
                out.append(w)

    for m in _TOKEN_RE.finditer(clean):
        tok = m.group(0)
        if m.group("brand") is None:
            take(tok, m.start())
        elif _brand(tok):
            w = _judge(tok, _sentence_start(clean, m.start()), english)
            if w is not None:
                out.append(w)
        else:
            for sub in _WORD_RE.finditer(tok):
                take(sub.group(0), m.start() + sub.start())
    return out


def counts(text: str) -> Counter[str]:
    """Слова для таблицы vocab: слабые английские — с меткой EN_WEAK_MARK."""
    return Counter(_extract(text))


# ---------- агрегаты: разные написания одного слова ----------

@lru_cache(maxsize=65536)
def group_key(word: str) -> str:
    """Ключ слияния форм одного слова: без регистра и «ё»; у кириллицы без латиницы и цифр
    (кроме аббревиатур вроде «СДЭК») — основа Snowball: «Тимуру», «Тимура», «Тимуром»,
    «Тимур» → «тимур»; «дашборда», «дашборду» → «дашборд». Основа короче GROUP_STEM_MIN —
    только написание (иначе «Ян» и «Яна» стали бы одним словом)."""
    f = fold(word)
    if not _CYR.search(f) or _LATIN.search(f) or any(ch.isdigit() for ch in f):
        return f
    letters = _letters(word)
    if len(letters) >= 2 and letters.isupper():
        return f
    st = stem_ru(f)
    return st if len(st) >= GROUP_STEM_MIN else f


@dataclass
class Word:
    word: str          # как показывать и подсказывать
    count: int
    last_ts: float
    strong: bool
    key: str = ""      # group_key: по нему слияние, повторы и исключения

    def __post_init__(self) -> None:
        if not self.key:
            self.key = group_key(self.word)


# Окончания, по которым видно род имени/слова в группе форм (после основы)
_MASC_MARKS = ("ом", "ем")                          # Тимуром, Игорем (ё → е уже в fold)
_FEM_MARKS = ("ой", "ей", "ою", "ею", "ы", "и")     # Наташей, Наташи, витрины


def _display(key: str, forms: dict[str, list[float]]) -> str:
    """Как показывать слово группы: именительный падеж, если он встречался («Тимур» среди
    «Тимуру», «Тимура»; «Наташа» среди «Наташу», «Наташей»), иначе самое частое написание.
    Написание с заглавной важнее («ClickHouse», а не «clickhouse»; «Наташа», а не «наташа»
    из начала предложения)."""
    by_fold: dict[str, list[str]] = {}
    for w in forms:
        by_fold.setdefault(fold(w), []).append(w)
    endings = {f[len(key):] for f in by_fold if f.startswith(key)}
    masc = any(e in _MASC_MARKS for e in endings)
    fem = any(e in _FEM_MARKS for e in endings)
    nom = [f for f in by_fold if f in (key, key + "ь", key + "й")]
    if not nom and fem and not masc:
        nom = [f for f in by_fold if f in (key + "а", key + "я")]

    def weight(spellings: Iterable[str]) -> tuple[float, float]:
        return (sum(forms[w][0] for w in spellings), max(forms[w][1] for w in spellings))

    marked = [w for w in forms if any(ch.isupper() for ch in w)]
    if nom:
        best = max(nom, key=lambda f: weight(by_fold[f]))
        cands = by_fold[best]
        up = [w for w in cands if any(ch.isupper() for ch in w)]
        if up:
            return max(up, key=lambda w: (forms[w][0], forms[w][1], w))
        spelled = max(cands, key=lambda w: (forms[w][0], forms[w][1], w))
        if not marked:
            return spelled
        # «тимур» встречался только в начале предложения, а в середине — «Тимуру»:
        # у имени именительный падеж пишем с заглавной
        if all(w[:1].isupper() and w[1:] == w[1:].lower() for w in marked):
            return spelled[:1].upper() + spelled[1:]
    pool = marked or list(forms)
    return max(pool, key=lambda w: (forms[w][0], forms[w][1], w))


def merge(rows: Iterable[tuple[str, int, float]]) -> list[Word]:
    """Строки (написание, повторов, последний раз) → слова: формы одного слова (group_key —
    регистр, «ё», падежи) складываются, написание — см. ``_display``. Слово «сильное», если
    хоть одна его форма сильная (is_strong) и записана без метки EN_WEAK_MARK: «deployment»
    из английского текста — слабое, оно же посреди русской речи — сильное.
    Сортировка: по «весу» (сильные слова вдвое важнее), затем по свежести."""
    groups: dict[str, dict[str, list[float]]] = {}
    strong_keys: set[str] = set()
    for stored, n, ts in rows:
        if not isinstance(stored, str) or not stored or n <= 0:
            continue
        word, weak_en = unmark(stored)
        if not word:
            continue
        key = group_key(word)
        g = groups.setdefault(key, {})
        cur = g.setdefault(word, [0.0, 0.0])
        cur[0] += n
        cur[1] = max(cur[1], float(ts or 0.0))
        if not weak_en and is_strong(word):
            strong_keys.add(key)
    out: list[Word] = []
    for key, forms in groups.items():
        total = int(sum(v[0] for v in forms.values()))
        last = max(v[1] for v in forms.values())
        display = _display(key, forms)
        out.append(Word(display, total, last, key in strong_keys, key))
    out.sort(key=lambda x: (-score(x), -x.last_ts, fold(x.word)))
    return out


def excluded_keys(raw: Iterable[str]) -> frozenset[str]:
    """Ключи исключений: как сохранены (fold слова) и ключ группы — исключение действует на
    все формы слова («Тимуру» исключает и «Тимура», «Тимуром»)."""
    out: set[str] = set()
    for e in raw:
        if e:
            out.add(e)
            out.add(group_key(e))
    return frozenset(out)


def is_excluded(w: Word, keys: Iterable[str] | frozenset[str]) -> bool:
    ks = keys if isinstance(keys, (set, frozenset)) else frozenset(keys)
    return w.key in ks or fold(w.word) in ks


def score(w: Word) -> int:
    return w.count * (2 if w.strong else 1)


def eligible(w: Word) -> bool:
    """Слово достаточно частое для подсказки."""
    return w.count >= (STRONG_MIN if w.strong else WEAK_MIN)


# ---------- контекст окна ----------

_SENT_SPLIT = re.compile(r"(?<=[.!?\u2026])[\"'\u00bb\u201d)\]]*\s+")


def context_tail(text: str | None, max_chars: int = CONTEXT_CHARS,
                 sentences: int = CONTEXT_SENTENCES) -> str:
    """1–2 последних предложения текста перед курсором (последнее может быть недописанным),
    пробелы и переводы строк схлопнуты, не длиннее max_chars (обрезка слева по слову)."""
    if not text or max_chars <= 0:
        return ""
    lines = [" ".join(ln.split()) for ln in text.replace("\r", "\n").split("\n")]
    parts: list[str] = []
    for ln in lines:
        if ln:
            parts += [p for p in _SENT_SPLIT.split(ln) if p.strip()]
    if not parts:
        return ""
    tail = " ".join(parts[-max(1, sentences):]).strip()
    if len(tail) > max_chars:
        cut = tail[-max_chars:]
        sp = cut.find(" ")
        tail = cut[sp + 1:] if 0 <= sp < len(cut) - 1 else cut
    return tail.strip()


# ---------- подсказка распознаванию ----------

TokenCounter = Callable[[str], int]

# Осторожная оценка без токенизатора модели (символов на токен). Замер на токенизаторе
# large-v3-turbo (600 подсказок: контекст окна + термины, имена в падежах, редкие слова,
# английские слова, термины с цифрами): оценка не меньше настоящего числа токенов (хуже
# всего — на 0,2 %), для обычной речи — с запасом в 1,4 раза. Прежняя оценка «символы / 3»
# занижала кириллицу в полтора раза: подсказка выходила за 223 токена, и faster-whisper
# молча срезал её начало — контекст окна.
_EST_CYR = 1.45
_EST_LAT = 2.0
_EST_PUNCT = 0.6


def _estimate(text: str) -> float:
    cyr = lat = other = 0
    punct = 0
    for ch in text:
        if "\u0400" <= ch <= "\u04ff":
            cyr += 1
        elif ch.isascii() and ch.isalpha():
            lat += 1
        elif ch.isalnum():
            other += 1                 # цифры и прочие буквы — токен на символ
        elif not ch.isspace():
            punct += 1
    return cyr / _EST_CYR + lat / _EST_LAT + other + punct * _EST_PUNCT


def estimate_tokens(text: str) -> int:
    """Оценка числа токенов Whisper для текста подсказки (сверху)."""
    return math.ceil(_estimate(text))


def _fit_left(text: str, max_tokens: float, cost: Callable[[str], float]) -> str:
    """Самый длинный хвост текста (по словам) не дороже max_tokens."""
    if not text or cost(text) <= max_tokens:
        return text
    words = text.split(" ")
    lo, hi = 1, len(words)            # ищем наименьший i: хвост words[i:] влезает
    while lo < hi:
        mid = (lo + hi) // 2
        if cost(" ".join(words[mid:])) <= max_tokens:
            hi = mid
        else:
            lo = mid + 1
    return " ".join(words[lo:]).strip()


def build_prompt(context: str | None, terms: Iterable[object],
                 process_words: Iterable[str] = (), general_words: Iterable[str] = (),
                 max_tokens: int = PROMPT_TOKENS, max_words: int = MAX_FREQ_WORDS,
                 context_chars: int = CONTEXT_CHARS, context_tokens: int = CONTEXT_TOKENS,
                 count_tokens: TokenCounter | None = None) -> str | None:
    """initial_prompt для faster-whisper: «<контекст окна> ClickHouse, Metabase, Redis.».

    Порядок и приоритет: контекст окна (≤ context_chars символов и ≤ context_tokens
    токенов, лишнее срезается слева по словам) → термины (настройки + словарь) → частые
    слова процесса → общие частые слова. Всего не больше max_tokens токенов: считает
    count_tokens (токенизатор модели — так, как faster-whisper кодирует подсказку), без
    него — осторожная оценка estimate_tokens. Частых слов — не больше max_words. Дубли
    без учёта регистра и «ё» убираются; то, что не влезает, пропускается (более короткое
    после него ещё может войти). Пусто → None."""
    cost: Callable[[str], float] = (
        (lambda t: float(count_tokens(t))) if count_tokens is not None else _estimate)
    limit = float(max(0, max_tokens))
    ctx = context_tail(context, context_chars) if context else ""
    ctx = _fit_left(ctx, min(float(context_tokens), limit), cost)
    used = (cost(ctx) if ctx else 0.0) + cost(".")    # завершающая точка
    items: list[str] = []
    seen: set[str] = set()

    def add(raw: object) -> bool:
        nonlocal used
        if not isinstance(raw, str):
            return False
        t = " ".join(unicodedata.normalize("NFC", raw).split())
        k = fold(t)
        if not t or k in seen:
            return False
        extra = cost(", " + t if items else t)
        if used + extra > limit:
            return False
        seen.add(k)
        items.append(t)
        used += extra
        return True

    for t in terms:
        add(t)
    n = 0
    for w in [*process_words, *general_words]:
        if n >= max_words:
            break
        if add(w):
            n += 1

    def assemble() -> str:
        glossary = ", ".join(items) + "." if items else ""
        return " ".join(p for p in (ctx, glossary) if p)

    prompt = assemble()
    # Токены на стыках складываются не строго: проверяем подсказку целиком
    while prompt and cost(prompt) > limit:
        if items:
            items.pop()
        elif ctx:
            ctx = _fit_left(ctx, max(0.0, cost(ctx) - 1), cost)
        else:
            break
        prompt = assemble()
    return prompt or None


def pick_words(process_words: Sequence[Word], general_words: Sequence[Word],
               excluded: Iterable[str], limit: int = MAX_FREQ_WORDS,
               strong_only: bool = False) -> tuple[list[str], list[str]]:
    """Частые слова для подсказки: (слова процесса, общие) без исключённых (excluded —
    как в vocab_excluded: fold слова; действует на все формы — см. excluded_keys), только
    достаточно частые; всего не больше limit.

    Порядок: сильные слова процесса → сильные общие → слабые (редкие строчные) процесса →
    слабые общие; слабых — не больше MAX_WEAK_WORDS: термины и имена важнее, а частое
    обычное слово, которого нет в частотном списке, не вытесняет их из подсказки."""
    keys = excluded_keys(excluded)
    seen: set[str] = set()
    out: tuple[list[str], list[str]] = ([], [])
    weak = 0
    for strong in (True, False):
        if not strong and strong_only:
            break
        for i, src in enumerate((process_words, general_words)):
            for w in src:
                if sum(len(x) for x in out) >= limit:
                    return out
                if (w.strong != strong or w.key in seen or not eligible(w)
                        or is_excluded(w, keys)):
                    continue
                if not strong:
                    if weak >= MAX_WEAK_WORDS:
                        break
                    weak += 1
                seen.add(w.key)
                out[i].append(w.word)
    return out
