"""Словарь учится на правках пользователя (как в Wispr Flow) — чистая логика без Windows.

После вставки диктовки движок (engine.py) через UI Automation (uia.py) следит за полем
ввода. Здесь — только сравнение текста поля до и после правок:

1. ``fragment_span`` — где в тексте поля вставленный фрагмент;
2. ``fragment_alive`` — поле ещё содержит большую часть фрагмента (снимок «хороший»);
   очищенное поле (Telegram отправил сообщение) и полностью переписанный текст — нет;
3. ``find_corrections`` — пословный diff (``difflib.SequenceMatcher``) и выбор правок,
   похожих на ошибку распознавания: «метабейс» → Metabase, «клик хаус» → ClickHouse,
   «Сёма» → «Сема». Правки по смыслу («завтра» → «послезавтра»), грамматика
   («Наташа» → «Наташе»), пунктуация, удаление/добавление слов, числа и короткие слова
   отсеиваются;
4. ``held_corrections`` — сколько секунд каждая правка непрерывно держалась в поле
   (по снимкам опроса): слово, которое ещё печатают, не учится.

Вариант словаря — правило замены во ВСЕХ будущих диктовках, поэтому фильтр осторожный:
новое слово должно быть похоже на термин (латиница, цифры, смешанный регистр, заглавная
буква не в начале предложения — имя) и быть похожим на старое по звучанию (транслитерация
кириллицы и простая фонетика, первая согласная та же). Правка, в которой уверенности меньше
(``Correction.sure = False``: имя → похожее имя, только заглавная у русского слова или
у слова в английском тексте, перевод в строчную латиницу, латинское окружение, короткий
вариант), в режиме auto всё равно добавляется сразу — как и любая правка, с кнопкой
«Отменить» (пользователь видит каждое пополнение словаря); sure только пишется в лог. Заглавная
у обычного английского слова в английском тексте («monday» → «Monday», «english» →
«English») — правописание, а не ошибка распознавания: не учится вовсе.

Текст поля — переписка пользователя: модуль ничего не пишет в лог.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable, NamedTuple, Sequence

from .i18n import tr
from .textproc import _ENDINGS, _WORD_RE, apply_dictionary, fold

MAX_OLD_WORDS = 3        # «клик хаус» → ClickHouse: распознанная часть — до 3 слов
MAX_NEW_WORDS = 2        # исправленная — до 2 слов
MIN_CHARS = 3            # короче (букв и цифр) — не учимся: «мы» → «вы»
SIM_CROSS = 0.6          # сходство кириллица ↔ латиница после транслитерации
SIM_SAME = 0.75          # сходство в одной письменности (правка имени, латинского слова)
MIN_LEN_RATIO = 0.6      # длины «скелетов» не должны отличаться сильнее
SHORT_VARIANT = 4        # вариант из одного слова не длиннее — правка без уверенности
ALIVE_WORDS = 0.5        # доля слов фрагмента, которая должна уцелеть в «хорошем» снимке
ALIVE_SIM = 0.5          # …или сходство уцелевшей части с фрагментом
MAX_PER_EVAL = 3         # не больше стольких правок за одно наблюдение
CAPS_NEAR = 2            # две правки «строчная → Заглавная» не дальше стольких слов —
                         # оформление (список, Title Case), а не имена

# Частые слова: ни термином, ни вариантом они не становятся (замена во всех будущих
# диктовках испортила бы обычный текст). Вежливое «Вы/Вас/Вам» — тоже здесь.
STOPWORDS = frozenset(fold(w) for w in """
    вы вас вам вами ваш ваша ваше ваши вашего вашей вашему вашим ваших вашу вашем
    ты тебя тебе тобой твой твоя твое твои твоего твоей твоем
    он она оно они его ее ему ей им их ими нас нам нами наш наша наше наши нашем нашей
    мне меня мной мой моя мое мои моем моей свой своя свое свои своем своей своего
    это этот эта эти этого этой этому этим этих этом тот та то те того той тому тем тех том
    что чтобы как так там тут здесь где когда тогда потом сейчас уже еще тоже также
    или либо если нет да ну вот вон все всё всех всем всего весь вся
    был была было были быть будет будут есть можно нужно надо очень просто только
    даже почти может могу можем хочу хотел хорошо плохо ладно спасибо привет пока
    сегодня завтра вчера день дня года время раз два три один одна
    the and you your for with this that are was were not but have has had from they
    them their there then than what when where which who will would can could should
    about into just also only very much more most some any all our out get got been
""".split())

# Обычные русские слова: кросс-письменная правка такого слова — перевод («проект» →
# project, «тесты» → tests), а не ошибка распознавания; заглавная буква у него —
# оформление («Заказчик», «с Новым годом», «картой Мир»), а не имя.
COMMON_WORDS = frozenset(fold(w) for w in """
    проект сервер тест браузер файл код сайт бот чат клиент компьютер интернет телефон
    документ отчёт задача команда система программа функция модуль сервис процесс продукт
    дизайн менеджер офис банк карта контент контакт аккаунт пароль логин почта письмо
    сообщение канал группа видео фото аудио музыка игра текст слово язык данные база сеть
    приложение пользователь админ разработчик релиз версия баг фича тикет спринт митинг
    встреча звонок созвон дедлайн ревью коммит деплой билд апдейт стрим пост лайк чек
    план итог итоги список работа договор заказчик исполнитель подрядчик сторона
    покупатель продавец арендатор арендодатель компания фирма заказ оплата счёт акт
    услуга товар цена доставка молоко хлеб сыр
    английский русский немецкий французский испанский итальянский китайский японский
    украинский белорусский польский
    понедельник вторник среда четверг пятница суббота воскресенье
    январь февраль март апрель май июнь июль август сентябрь октябрь ноябрь декабрь
    новый новым новом новая новое новые новых новою год году годом днём днём рождения
    рождество рождеством победа победы мир пасха праздник
""".split())
# Частые имена, города, страны: их кросс-письменная правка («Сергей» → Sergey,
# «Москва» → Moscow) — перевод; заглавная у них — законная правка (без уверенности).
COMMON_NAMES = frozenset(fold(w) for w in """
    москва россия питер петербург минск беларусь киев украина лондон париж берлин
    америка европа германия франция китай япония казахстан
    сергей андрей александр алексей дмитрий михаил иван николай павел владимир евгений
    максим артём антон илья кирилл роман олег игорь юрий виктор никита денис егор
    константин мария анна елена ольга наталья татьяна ирина светлана екатерина юлия
    анастасия дарья марина ксения алина виктория полина
""".split())

_LATIN = re.compile(r"[a-zA-Z]")
_CYR = re.compile(r"[\u0400-\u04ff]")
_SENTENCE_END = frozenset(".!?\u2026\n")
# Перед словом: начало предложения/пункта — после них («купить: Молоко», «1) Отчёт»,
# «• Отчёт», «# Итоги», «итог — Отчёт»)
_CLAUSE_MARKS = frozenset(".!?\u2026\n:;\u2022\u00b7*#)>|\u2014\u2013")
_OPENERS = frozenset("\u00ab\"'\u201c\u201e\u2018([{")
_SPACES = frozenset(" \t\u00a0")
_TERM_SEPS = re.compile(r"[ \t\u00a0\-\u2010\u2011]+")
# Русское окончание после слова: «Metabase'е», «Metabase-ом», «Excel’е»
_SUFFIX_RE = re.compile(r"['\u2019\-]?[\u0430-\u044f\u0451]{1,4}")
_DIGITS = re.compile(r"\d+")
_NOT_LETTERS = re.compile(r"[\W\d_]+")

# Окончания для сравнения форм одного слова (падежи существительных и прилагательных)
_INFL = tuple(sorted(set(_ENDINGS) | {
    "ий", "ия", "ии", "ию", "ей", "ея", "ой", "ую", "юю", "ью", "ье", "ьи", "ый", "ая", "яя",
    "ое", "ее", "ые", "ие", "ого", "его", "ому", "ему", "ым", "им", "ых", "их", "ыми", "ими",
    "ём", "ем", "ом"}, key=len, reverse=True))
# Окончания прилагательных: «Новым», «Рабочую» — не имена
_ADJ = ("ого", "его", "ому", "ему", "ыми", "ими", "ый", "ая", "яя", "ое", "ые", "ым", "ых",
        "ую", "юю")

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "iu",
    "я": "ia", "і": "i", "ї": "i", "є": "e", "ґ": "g", "ў": "u",
}
# Простая фонетика латиницы — чтобы «кликхаус» и «clickhouse», «джира» и «jira»,
# «эксель» и «excel» сводились к похожим строкам.
_PHONETIC: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p), r) for p, r in (
        (r"sch", "sh"), (r"tch", "ch"), (r"tion", "shen"), (r"ph", "f"), (r"th", "t"),
        (r"ck", "k"), (r"qu", "kv"), (r"wh", "v"), (r"x", "ks"), (r"j", "dzh"), (r"w", "v"),
        (r"q", "k"), (r"c(?=[eiy])", "s"), (r"c", "k"), (r"y", "i"), (r"ee", "i"), (r"oo", "u"),
        (r"(.)\1+", r"\1"),
    ))
# Первая согласная «скелета» без звонкости: «жира»/Jira, «гугл»/Google, «вебхук»/webhook
_VOICING = str.maketrans("bvgdzw", "pfktsf")
_VOWELS = frozenset("aeiou")


@dataclass(frozen=True)
class Correction:
    """Правка-кандидат: ``term`` — как исправил пользователь, ``variant`` — как было
    распознано ("" — вариант не нужен: правка только регистра или «ё»).
    ``sure=False`` — уверенности мало. Движок добавляет и такую правку (режим auto, с кнопкой
    «Отменить»), sure — только для лога."""
    term: str
    variant: str
    sure: bool = True


class Token(NamedTuple):
    text: str
    start: int
    end: int


@dataclass(slots=True)
class Snapshot:
    """Снимок текста поля во время наблюдения: когда впервые и когда в последний раз
    прочитан именно такой текст; ``alive`` — в нём ещё есть вставленный фрагмент."""
    text: str
    first: float
    last: float
    alive: bool = True


# ---------- текст ----------

def norm_text(text: str) -> str:
    """Текст поля в единой форме: NFC, переводы строк \\n (Win32 Edit даёт \\r\\n, Word — \\r)."""
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def tokenize(text: str) -> list[Token]:
    """Слова текста с позициями (пунктуация — не слова; «ClickHouse-запрос» — одно слово)."""
    return [Token(m.group(0), m.start(), m.end()) for m in _WORD_RE.finditer(text)]


def has_words(text: str) -> bool:
    return _WORD_RE.search(text) is not None


def _script(s: str) -> str:
    lat, cyr = bool(_LATIN.search(s)), bool(_CYR.search(s))
    if lat and cyr:
        return "mixed"
    return "lat" if lat else "cyr" if cyr else "none"


def skeleton(s: str) -> str:
    """«Звучание» слова латиницей: транслитерация кириллицы, только буквы и цифры,
    простая фонетика. «Клик хаус» → «klikhaus», «ClickHouse» → «klikhouse»."""
    out = "".join(_TRANSLIT.get(ch, ch) for ch in fold(s))
    out = re.sub(r"[^a-z0-9]", "", out)
    for pat, rep in _PHONETIC:
        out = pat.sub(rep, out)
    return out


def similarity(a: str, b: str) -> float:
    """Сходство двух написаний по звучанию, 0..1."""
    sa, sb = skeleton(a), skeleton(b)
    if not sa or not sb:
        return 0.0
    return SequenceMatcher(None, sa, sb, autojunk=False).ratio()


def _head(sk: str) -> str:
    """Первая согласная скелета без звонкости («dzh» и «zh» — одно и то же)."""
    if sk.startswith("dzh"):
        sk = sk[1:]
    for ch in sk:
        if ch.isalpha() and ch not in _VOWELS:
            return ch.translate(_VOICING)
    return ""


def _alnum(s: str) -> int:
    return sum(ch.isalnum() for ch in s)


def pair_key(term: str, variant: str) -> str:
    """Ключ правки «вариант → термин» (счётчик повторов, отменённые правки)."""
    return f"{fold(variant)}→{fold(term)}"


def added_text(term: str, variant: str) -> str:
    """Текст уведомления «добавлено» на языке интерфейса."""
    if variant:
        return tr("learn.added_variant", term=term, variant=variant)
    return tr("learn.added", term=term)


def suggest_text(term: str, variant: str) -> str:
    """Текст уведомления «добавить?» на языке интерфейса."""
    if variant:
        return tr("learn.suggest_variant", term=term, variant=variant)
    return tr("learn.suggest", term=term)


# ---------- где фрагмент и уцелел ли он ----------

def fragment_span(text: str, fragment: str) -> tuple[int, int] | None:
    """Позиция вставленного фрагмента в тексте поля (последнее вхождение его слов подряд):
    пробелы и переводы строк приложение могло поменять. None — фрагмента нет."""
    fw = [t.text for t in tokenize(fragment)]
    if not fw:
        return None
    tw = tokenize(text)
    n = len(fw)
    for i in range(len(tw) - n, -1, -1):
        if tw[i].text == fw[0] and [t.text for t in tw[i:i + n]] == fw:
            return tw[i].start, tw[i + n - 1].end
    return None


def _word_range(tokens: Sequence[Token], span: tuple[int, int]) -> tuple[int, int]:
    """Индексы слов [f1, f2), которые пересекаются с отрезком span."""
    idx = [i for i, t in enumerate(tokens) if t.end > span[0] and t.start < span[1]]
    return (idx[0], idx[-1] + 1) if idx else (0, 0)


def _opcodes(a: list[str], b: list[str]) -> list[tuple[str, int, int, int, int]]:
    """Опкоды SequenceMatcher по словам; общее начало и конец отрезаются заранее —
    длинный документ (Word) не замедляет сравнение."""
    n = min(len(a), len(b))
    p = 0
    while p < n and a[p] == b[p]:
        p += 1
    s = 0
    while s < n - p and a[len(a) - 1 - s] == b[len(b) - 1 - s]:
        s += 1
    ops: list[tuple[str, int, int, int, int]] = []
    if p:
        ops.append(("equal", 0, p, 0, p))
    mid = SequenceMatcher(None, a[p:len(a) - s], b[p:len(b) - s], autojunk=False)
    for tag, i1, i2, j1, j2 in mid.get_opcodes():
        ops.append((tag, i1 + p, i2 + p, j1 + p, j2 + p))
    if s:
        ops.append(("equal", len(a) - s, len(a), len(b) - s, len(b)))
    return ops


def fragment_alive(before: str, span: tuple[int, int], after: str) -> bool:
    """В поле ещё есть большая часть вставленного фрагмента (с правками пользователя).
    Пустое поле (сообщение отправлено) и переписанный целиком текст — False."""
    bw, aw = tokenize(before), tokenize(after)
    f1, f2 = _word_range(bw, span)
    total = f2 - f1
    if total <= 0 or not aw:
        return False
    kept = 0
    region: list[str] = []
    for tag, i1, i2, j1, j2 in _opcodes([t.text for t in bw], [t.text for t in aw]):
        lo, hi = max(i1, f1), min(i2, f2)
        if lo >= hi and not (tag == "insert" and f1 < i1 < f2):
            continue
        if tag == "equal":
            kept += hi - lo
            region += [t.text for t in aw[j1 + lo - i1:j1 + hi - i1]]
        elif tag in ("replace", "insert"):
            region += [t.text for t in aw[j1:j2]]
    if kept >= total * ALIVE_WORDS:
        return True
    frag = " ".join(t.text for t in bw[f1:f2])
    return bool(region) and similarity(frag, " ".join(region)) >= ALIVE_SIM


# ---------- что за слово ----------

def _sentence_start(text: str, pos: int) -> bool:
    """Слово в позиции pos начинает предложение или пункт: начало поля или строки, после
    .!?… и «:» «;», после маркера списка («1)», «•», «*», «-», «#»), тире, эмодзи или
    другого значка в начале строки. Заглавная буква там — не признак имени."""
    i = pos - 1
    while i >= 0 and (text[i] in _SPACES or text[i] in _OPENERS):
        i -= 1
    if i < 0:
        return True
    ch = text[i]
    if ch in _CLAUSE_MARKS:
        return True
    if ch == "-":                       # «- пункт», «итог - Отчёт» (дефис внутри слова — часть слова)
        return i == 0 or not text[i - 1].isalnum()
    if ch.isalnum() or ch in ",\u00bb\u201d\"'":
        return False
    # Значок (эмодзи, ✅, →): начало пункта, если до него в строке нет букв и цифр
    j = i
    while j >= 0 and text[j] != "\n" and not text[j].isalnum():
        j -= 1
    return j < 0 or text[j] == "\n"


def _caps_or_camel(words: Sequence[str]) -> bool:
    """API, СДЭК (все заглавные) или ClickHouse, iPhone, ВКонтакте (заглавная внутри)."""
    for w in words:
        letters = [ch for ch in w if ch.isalpha()]
        if len(letters) >= 2 and all(ch.isupper() for ch in letters):
            return True
        if any(ch.isupper() for ch in w[1:]) and any(ch.islower() for ch in w):
            return True
    return False


def _termlike(words: list[str], sentence_start: bool, cross: bool) -> bool:
    """Новое написание похоже на термин или имя, а не на обычное слово."""
    joined = " ".join(words)
    if not any(ch.isalpha() for ch in joined):
        return False
    if any(ch.isdigit() for ch in joined):
        return True                                   # GPT4, K8s
    if _caps_or_camel(words):
        return True                                   # API, ClickHouse
    if any(w[:1].isupper() for w in words[1:]):
        return True                                   # Visual Studio
    if cross and _LATIN.search(joined):
        return True                                   # «питон» → python
    return words[0][:1].isupper() and not sentence_start   # имя, название


def _stems(w: str) -> set[str]:
    """Слово (fold) и его возможные основы без падежного окончания."""
    out = {w}
    if _CYR.search(w[-1:]):
        for e in _INFL:
            if w.endswith(e) and len(w) - len(e) >= 2:
                out.add(w[:-len(e)])
    return out


def _stems4(ws: Iterable[str]) -> frozenset[str]:
    return frozenset(s for w in ws for s in _stems(w) if len(s) >= 4)


_COMMON_WORD_STEMS = _stems4(COMMON_WORDS)
_COMMON_NAME_STEMS = _stems4(COMMON_NAMES)


def _is_common(word: str, names: bool) -> bool:
    """Обычное русское слово (в любом падеже): «проекте», «тесты», «Заказчику»;
    names — и частые имена/города: «Сергей», «Москве»."""
    forms = _stems(fold(word))
    if forms & COMMON_WORDS or (names and forms & COMMON_NAMES):
        return True
    long = {s for s in forms if len(s) >= 4}
    return bool(long & _COMMON_WORD_STEMS or (names and long & _COMMON_NAME_STEMS))


def _adjective(word: str) -> bool:
    f = fold(word)
    return len(f) >= 5 and f.endswith(_ADJ)


def _grammar(a: str, b: str) -> bool:
    """Правка грамматики, а не распознавания (a, b — fold): другая форма того же слова
    («Наташа» → «Наташе», «Кузнецова» → «Кузнецовой», «Сергей» → «Сергею») или русское
    окончание у латинского слова («Metabase» → «Metabase'е», «Excel» → «Excel-ем»)."""
    for x, y in ((a, b), (b, a)):
        if y.startswith(x) and _SUFFIX_RE.fullmatch(y[len(x):]):
            return True
    wa, wb = a.split(" "), b.split(" ")
    if len(wa) != len(wb):
        return False
    changed = False
    for x, y in zip(wa, wb):
        if x == y:
            continue
        if _script(x) != "cyr" or _script(y) != "cyr" or not (_stems(x) & _stems(y)):
            return False
        changed = True
    return changed


def _digits_only(variant: str, term: str) -> bool:
    """Отличаются только числа: «RUPOR-12» → «RUPOR-13», «GPT-4» → «GPT-5»."""
    if _DIGITS.findall(variant) == _DIGITS.findall(term):
        return False
    return _NOT_LETTERS.sub("", fold(variant)) == _NOT_LETTERS.sub("", fold(term))


def _latin_context(text: str, start: int, end: int) -> bool:
    """Соседние слова — латиница («hi Сергей, see you»): правка в английском тексте,
    а вариант станет правилом и для русских диктовок."""
    prev = _WORD_RE.findall(text[max(0, start - 80):start])
    nxt = _WORD_RE.findall(text[end:end + 80])
    around = prev[-1:] + nxt[:1]
    return bool(around) and all(_script(w) == "lat" for w in around)


def _plain_cap(old: str, new: str) -> bool:
    """Только первая буква стала заглавной: «новым» → «Новым»."""
    return bool(old) and old[:1].islower() and new[:1].isupper() and \
        old[1:] == new[1:] and fold(old[:1]) == fold(new[:1])


def _term_text(tokens: Sequence[Token], text: str) -> str:
    """Исправленное написание: как в тексте, если слова разделены пробелом/дефисом
    («Visual Studio», «Wi-Fi»), иначе — через пробел."""
    if len(tokens) == 1:
        return tokens[0].text
    raw = text[tokens[0].start:tokens[-1].end]
    for a, b in zip(tokens, tokens[1:]):
        if not _TERM_SEPS.fullmatch(text[a.end:b.start]):
            return " ".join(t.text for t in tokens)
    return " ".join(raw.split())


# Окончания косвенных падежей после основы на согласную: «джир|е», «кафк|ой», «графан|у»
_OBLIQUE = tuple(e for e in sorted(_ENDINGS, key=len, reverse=True) if e not in ("а", "я"))


def _stem_variant(variant: str, term: str) -> str:
    """Распознанное слово в косвенном падеже → форма, которую поймают все падежи
    (textproc.apply_dictionary сам допускает окончания после кириллического варианта):

    - латинский термин на «a» (Grafana, Jira, Kafka): «джире», «джиры» → «джира»;
    - иначе окончание отрезается, только если оно лишнее по звучанию термина:
      «метабейсе» → «метабейс», «клик хаусом» → «клик хаус», но «Сергей» (Sergey),
      «тесты» (tests), «Москва» (Moscow) не режутся — окончание там звучит в термине.
    Только для некириллического термина и если основа не короче 4 (3 для «…а») букв."""
    if _CYR.search(term) or not variant:
        return variant
    words = variant.split(" ")
    last = words[-1]
    if not _CYR.search(last[-1:]):
        return variant
    low = fold(last)
    if fold(term).endswith("a"):
        if low.endswith("а"):
            return variant
        for end in _OBLIQUE:
            if low.endswith(end) and len(last) - len(end) >= 3:
                return " ".join([*words[:-1], last[:-len(end)] + "а"])
        return variant
    # Длина звучания ближе к термину — с отрезанным окончанием или без (при равенстве —
    # отрезать: «клик хаусом» → «клик хаус»). Немая «e» на конце (House, Metabase, Google)
    # не звучит: «хаусе» — падеж, а не «house».
    sk = skeleton(term)
    if re.search(r"[^aeiou]e$", sk):
        sk = sk[:-1]
    target = len(sk)
    best, best_gap, stripped = variant, abs(len(skeleton(variant)) - target), False
    for end in sorted(_ENDINGS, key=len, reverse=True):
        if low.endswith(end) and len(last) - len(end) >= 4:
            cand = " ".join([*words[:-1], last[:-len(end)]])
            gap = abs(len(skeleton(cand)) - target)
            if gap < best_gap or (gap == best_gap and not stripped):
                best, best_gap, stripped = cand, gap, True
    return best


# ---------- правки ----------

def _english_text(text: str, start: int, end: int) -> bool:
    """Правка в английском тексте: соседние слова — латиница, или в поле нет кириллицы."""
    return _latin_context(text, start, end) or not _CYR.search(text)


def _everyday_en(word: str) -> bool:
    """Обычное английское слово: из частотного списка или всегда с заглавной (дни недели,
    месяцы, языки — «Monday», «January», «English»)."""
    from .vocab import is_everyday_en    # vocab сам импортирует learn — здесь, не сверху
    return is_everyday_en(word)


def _case_fix(variant: str, term: str, new_words: list[str], start: bool, english: bool
              ) -> tuple[Correction, bool] | None:
    """Правка только регистра или «ё» (fold одинаковый) — термин без варианта.
    english — правка в английском тексте (см. _english_text)."""
    if not _termlike(new_words, start, cross=False):
        return None
    if [ch.isupper() for ch in variant] == [ch.isupper() for ch in term]:
        return Correction(term, ""), False            # только «ё»: «Сёма» → «Сема»
    digits = any(ch.isdigit() for ch in term)
    plain_latin = bool(_LATIN.search(term)) and not _CYR.search(term) and not digits \
        and not _caps_or_camel(new_words)
    if english and plain_latin:
        # Английский текст, у слова только заглавная первая буква: «monday» → «Monday»,
        # «english» → «English» — правописание, а не ошибка распознавания. Обычные слова —
        # никогда; остальное («london» → «London», имя) — без уверенности, как русские имена.
        if all(_everyday_en(w) for w in new_words):
            return None
        return Correction(term, "", sure=False), False
    if _LATIN.search(term) or digits or _caps_or_camel(new_words):
        return Correction(term, ""), False            # clickhouse → ClickHouse, сдэк → СДЭК
    # Русское слово, только заглавная: имя — или оформление («Заказчик», «с Новым годом»).
    # Обычные слова и прилагательные — никогда; остальное — без уверенности.
    if any(_is_common(w, names=False) or _adjective(w) for w in new_words):
        return None
    return Correction(term, "", sure=False), False


def _judge(old: Sequence[Token], new: Sequence[Token], before: str, after: str
           ) -> tuple[Correction, bool] | None:
    """judge + признак «слабой» правки: короткий вариант из одного слова (часть «клик»
    из «клик хаус» → «Click House» сама по себе ничего не значит)."""
    if not old or not new or len(old) > MAX_OLD_WORDS or len(new) > MAX_NEW_WORDS:
        return None
    variant = " ".join(t.text for t in old)
    term = _term_text(new, after)
    if not any(ch.isalpha() for ch in term) or not any(ch.isalpha() for ch in variant):
        return None                                   # числа → числа, «пять» → «5»
    if _alnum(term) < MIN_CHARS or _alnum(variant) < MIN_CHARS or variant == term:
        return None
    fv, ft = fold(variant), fold(term)
    if ft in STOPWORDS or fv in STOPWORDS:
        return None
    new_words = [t.text for t in new]
    start = _sentence_start(after, new[0].start)
    if fv == ft:
        return _case_fix(variant, term, new_words, start,
                         _english_text(after, new[0].start, new[-1].end))
    if _grammar(fv, ft) or _digits_only(variant, term):
        return None                                   # «Наташа» → «Наташе», RUPOR-12 → 13
    cross = _script(variant) != _script(term)
    if not _termlike(new_words, start, cross):
        return None
    if cross and (all(_is_common(t.text, names=True) for t in old)
                  or all(_is_common(w, names=True) for w in new_words)):
        return None                                   # перевод: «проект» → project, Moscow → Москва
    a, b = skeleton(variant), skeleton(term)
    if not a or not b or min(len(a), len(b)) / max(len(a), len(b)) < MIN_LEN_RATIO:
        return None
    if not cross and a != b and (a.startswith(b) or b.startswith(a)):
        return None                                   # Java → JavaScript: не ошибка распознавания
    if _head(a) != _head(b):
        return None                                   # React → Preact, Даше → Маше
    if SequenceMatcher(None, a, b, autojunk=False).ratio() < (SIM_CROSS if cross else SIM_SAME):
        return None
    if cross:
        # «вебхук» → webhook (строчная латиница) — может быть и переводом; латинское
        # окружение — правка в английском тексте. Такое — без уверенности.
        sure = any(ch.isupper() or ch.isdigit() for ch in term) and \
            not _latin_context(after, new[0].start, new[-1].end)
    else:
        # Старое тоже «термин» (MySQL → MSSQL, Валера → Валерий) — скорее смысловая замена
        sure = not _termlike([t.text for t in old], _sentence_start(before, old[0].start),
                             cross=False)
    if apply_dictionary(variant, [{"term": term, "variants": []}]) == term:
        return Correction(term, "", sure), False      # «click house» → ClickHouse: хватит термина
    stemmed = _stem_variant(variant, term)
    if len(old) == 1 and sum(ch.isalpha() for ch in stemmed) <= SHORT_VARIANT:
        return Correction(term, stemmed, sure=False), True   # «слак» → Slack: без уверенности
    return Correction(term, stemmed, sure), False


def judge(old: Sequence[Token], new: Sequence[Token], before: str, after: str
          ) -> Correction | None:
    """Правка old → new похожа на исправление ошибки распознавания? Тогда — Correction.
    old — слова в тексте до правок (before), new — после (after)."""
    r = _judge(old, new, before, after)
    return r[0] if r is not None else None


def _partition(old: Sequence[Token], new: Sequence[Token]) -> list[tuple[int, int]] | None:
    """Разбить старые слова на len(new) идущих подряд групп (по 1–3 слова) так, чтобы
    каждая группа была как можно ближе по звучанию к своему новому слову."""
    n, m = len(old), len(new)
    if not n <= MAX_OLD_WORDS * m or m > n:
        return None
    neg = float("-inf")
    best: list[list[float]] = [[neg] * (n + 1) for _ in range(m + 1)]
    back: list[list[int]] = [[0] * (n + 1) for _ in range(m + 1)]
    best[0][0] = 0.0
    for k in range(1, m + 1):
        for i in range(1, n + 1):
            for size in range(1, MAX_OLD_WORDS + 1):
                j = i - size
                if j < 0 or best[k - 1][j] == neg:
                    continue
                sc = best[k - 1][j] + similarity(" ".join(t.text for t in old[j:i]),
                                                 new[k - 1].text)
                if sc > best[k][i]:
                    best[k][i], back[k][i] = sc, j
    if best[m][n] == neg:
        return None
    bounds: list[tuple[int, int]] = []
    i = n
    for k in range(m, 0, -1):
        j = back[k][i]
        bounds.append((j, i))
        i = j
    return bounds[::-1]


def _words(tokens: Sequence[Token]) -> str:
    return " ".join(t.text for t in tokens)


def _cover(old: Sequence[Token], new: Sequence[Token]
           ) -> tuple[list[Token], list[Token]] | None:
    """Части блока, которые объясняют друг друга по звучанию.

    Крайнее новое слово, без которого сходство не хуже, дописано заодно и в термин не
    входит («клик хаус» → «ClickHouse упал»). Крайнее старое слово, без которого сходство
    не хуже, удалено заодно и в вариант не входит: «в этом метабейсе» → «в Metabase» —
    вариант «метабейсе», а не «этом метабейсе» (иначе слово «этом» молча пропадало бы
    из будущих диктовок). С одного края нельзя отрезать и старое, и новое слово: это уже
    замена по смыслу («клик хаус сегодня» → «ClickHouse вчера»), блок не объясняется."""
    o, n = list(old), list(new)
    cut: set[str] = set()
    while len(n) > 1:
        full = similarity(_words(o), _words(n))
        left = similarity(_words(o), _words(n[1:]))
        right = similarity(_words(o), _words(n[:-1]))
        if max(left, right) < full:
            break
        if left >= right:
            n, side = n[1:], "left"
        else:
            n, side = n[:-1], "right"
        cut.add(side)
    while len(o) > len(n):
        full = similarity(_words(o), _words(n))
        left = similarity(_words(o[1:]), _words(n))
        right = similarity(_words(o[:-1]), _words(n))
        if max(left, right) < full:
            break
        side = "left" if left >= right else "right"
        if side in cut:
            return None
        o = o[1:] if side == "left" else o[:-1]
    return o, n


Found = tuple[Correction, int]   # правка и позиция её первого нового слова в тексте поля


def _block(old: Sequence[Token], new: Sequence[Token], before: str, after: str
           ) -> list[Found]:
    """Правки из одного блока замены.

    Слова, изменившие только регистр, по краям блока отделяются («в клик хаусе» →
    «В ClickHouse»: «в» → «В» — начало предложения, не часть термина). Остальное —
    сначала по словам (каждое новое слово — своя правка: «метабейс графана» → Metabase,
    Grafana), а если так правки выходят «слабыми» — весь блок целиком («клик хаус» →
    «Click House»). Блок, который не объясняется целиком (часть слов переписана по смыслу:
    «я написал Наташе» → «мне написала Наташа»), не даёт ничего."""
    out: list[Found] = []
    old, new = list(old), list(new)
    while old and new and fold(old[0].text) == fold(new[0].text):
        c = judge(old[:1], new[:1], before, after)
        out += [(c, new[0].start)] if c is not None else []
        old, new = old[1:], new[1:]
    while old and new and fold(old[-1].text) == fold(new[-1].text):
        c = judge(old[-1:], new[-1:], before, after)
        out += [(c, new[-1].start)] if c is not None else []
        old, new = old[:-1], new[:-1]
    if not old or not new:
        return out
    parts = _partition(old, new) if len(new) > 1 else None
    fine: list[Found] | None = None
    if parts is not None:
        judged = [_judge(old[i:j], new[k:k + 1], before, after)
                  for k, (i, j) in enumerate(parts)]
        fine = [(r[0], new[k].start) for k, r in enumerate(judged) if r is not None]
        if len(fine) != len(judged):
            fine = None                               # часть блока — не ошибка распознавания
        elif not any(r[1] for r in judged if r is not None):
            return out + fine
    core = _cover(old, new)
    whole = judge(core[0], core[1], before, after) if core is not None else None
    if core is not None and whole is not None:
        return out + [(whole, core[1][0].start)]
    return out + (fine or [])


def _plain_caps(old: Sequence[Token], new: Sequence[Token], j1: int, after: str) -> list[int]:
    """Индексы (в словах after) слов блока, у которых только первая буква стала заглавной —
    не в начале предложения."""
    pairs: list[tuple[Token, int]] = []
    if len(old) == len(new):
        pairs = [(o, k) for k, o in enumerate(old)]
    else:
        i = 0
        while i < min(len(old), len(new)) and fold(old[i].text) == fold(new[i].text):
            pairs.append((old[i], i))
            i += 1
        k = 1
        while k <= min(len(old), len(new)) - i and \
                fold(old[-k].text) == fold(new[-k].text):
            pairs.append((old[-k], len(new) - k))
            k += 1
    return [j1 + k for o, k in pairs
            if _plain_cap(o.text, new[k].text) and not _sentence_start(after, new[k].start)]


def find_corrections(before: str, span: tuple[int, int], after: str,
                     dictionary: Iterable[dict[str, Any]] = (),
                     limit: int | None = MAX_PER_EVAL) -> list[Correction]:
    """Правки пользователя во вставленном фрагменте, похожие на ошибки распознавания.

    before — текст поля сразу после вставки, span — где в нём фрагмент, after — текст
    после правок. Правки вне фрагмента, удаление и добавление слов не учитываются.
    Уже известное словарю (термин с этим вариантом, вариант другого термина, правка
    самого термина словаря) отбрасывается. Несколько слов рядом, у которых пользователь
    только поднял первую букву («Молоко, Хлеб, Сыр», «Project Status Update»), —
    оформление, не имена: они не учатся. limit=None — без ограничения числа правок."""
    bw, aw = tokenize(before), tokenize(after)
    f1, f2 = _word_range(bw, span)
    if f1 >= f2:
        return []
    found: list[Found] = []
    caps: list[int] = []
    for tag, i1, i2, j1, j2 in _opcodes([t.text for t in bw], [t.text for t in aw]):
        if tag != "replace" or i1 < f1 or i2 > f2:
            continue
        caps += _plain_caps(bw[i1:i2], aw[j1:j2], j1, after)
        found += _block(bw[i1:i2], aw[j1:j2], before, after)
    formatting = {aw[k].start for k in caps
                  if any(q != k and abs(q - k) <= CAPS_NEAR for q in caps)}
    out =[c for c, pos in found if pos not in formatting]
    seen: set[str] = set()
    uniq: list[Correction] = []
    for c in filter_known(out, dictionary):
        k = pair_key(c.term, c.variant)
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    return uniq if limit is None else uniq[:limit]


def held_corrections(before: str, span: tuple[int, int], snaps: Sequence[Snapshot],
                     dictionary: Iterable[dict[str, Any]] = (), horizon: float = 1.0
                     ) -> list[tuple[Correction, float]]:
    """Правки последнего «хорошего» снимка (``alive``) и сколько секунд каждая непрерывно
    держалась в поле: от первого снимка, где она уже была такой, до последнего прочтения
    оцениваемого снимка. Слово, которое менялось в последнем интервале опроса («ClickHou»
    перед Enter), держится ~0 с. snaps — по времени; смотрим назад не дальше horizon с."""
    good = next((k for k in range(len(snaps) - 1, -1, -1) if snaps[k].alive), None)
    if good is None:
        return []
    g = snaps[good]
    items = list(dictionary)
    cands = find_corrections(before, span, g.text, items)
    since = {pair_key(c.term, c.variant): g.first for c in cands}
    pending = set(since)
    for k in range(good - 1, -1, -1):
        if not pending or min(g.last - since[key] for key in pending) >= horizon:
            break
        s = snaps[k]
        if not s.alive:
            break
        present = {pair_key(c.term, c.variant)
                   for c in find_corrections(before, span, s.text, items, limit=None)}
        for key in list(pending):
            if key in present:
                since[key] = s.first
            else:
                pending.discard(key)
    return [(c, max(0.0, g.last - since[pair_key(c.term, c.variant)])) for c in cands]


def filter_known(cands: Iterable[Correction], dictionary: Iterable[dict[str, Any]]
                 ) -> list[Correction]:
    """Убрать то, что словарь уже знает или с чем он спорит."""
    terms: dict[str, set[str]] = {}
    owner: dict[str, str] = {}
    for it in dictionary:
        term = it.get("term") if isinstance(it, dict) else None
        if not isinstance(term, str) or not term.strip():
            continue
        ft = fold(term)
        vs = {fold(v) for v in it.get("variants") or [] if isinstance(v, str)}
        terms.setdefault(ft, set()).update(vs)
        for v in vs:
            owner.setdefault(v, ft)
    out: list[Correction] = []
    for c in cands:
        ft, fv = fold(c.term), fold(c.variant)
        if fv and fv in terms:
            continue            # пользователь правит сам термин словаря — не вариант
        if ft in terms and (not fv or fv in terms[ft]):
            continue            # уже есть
        if fv and owner.get(fv, ft) != ft:
            continue            # этот вариант уже ведёт к другому термину
        out.append(c)
    return out
