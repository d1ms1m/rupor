"""Личный словарь частот (vocab.py): отбор характерных слов, отсев общих, слияние
написаний, контекст окна и сборка подсказки Whisper с лимитами."""
from __future__ import annotations

import pytest

from rupor import vocab
from rupor.textproc import fold
from rupor.vocab import Word


# ---------- стеммер и частотные списки ----------

@pytest.mark.parametrize("forms", [
    ("делать", "делает", "делал", "делали"),
    ("витрина", "витрину", "витрины"),
    ("работа", "работы", "работе"),
    ("сообщение", "сообщения", "сообщений"),
])
def test_stemmer_groups_forms(forms: tuple[str, ...]) -> None:
    assert len({vocab.stem_ru(f) for f in forms}) == 1


def test_common_lists_are_loaded_and_sized() -> None:
    c = vocab._common()
    assert len(c.ru_forms) >= 1500 and len(c.en_forms) >= 1500
    assert not any(any("a" <= ch <= "z" for ch in w) for w in c.ru_forms)


@pytest.mark.parametrize("word", ["сделали", "работе", "Сегодня", "пожалуйста", "проекте",
                                  "возможности", "людей", "Москве"])
def test_common_russian_words(word: str) -> None:
    assert vocab.is_common_ru(word)


@pytest.mark.parametrize("word", ["дашборд", "мерчантов", "витрину", "Наташа"])
def test_rare_russian_words(word: str) -> None:
    assert not vocab.is_common_ru(word)


def test_common_english_words_with_endings() -> None:
    for w in ("the", "meeting", "checked", "updates", "Monday", "really"):
        assert vocab.is_common_en(w), w
    for w in ("kubernetes", "webhook", "pytest", "redis"):
        assert not vocab.is_common_en(w), w


# ---------- отбор слов ----------

def test_extract_terms_names_and_rare_words() -> None:
    text = ("Надо завтра в ClickHouse пересобрать витрину по комиссиям мерчантов, а потом "
            "в Metabase обновить дашборд. Скажи Тимуру про pytest и Redis-кластер. "
            "API и СДЭК, OK.")
    got = vocab.extract(text)
    for w in ("ClickHouse", "Metabase", "pytest", "Redis", "Тимуру", "API", "СДЭК", "дашборд",
              "мерчантов"):
        assert w in got, w
    # общие слова, короткие слова, «OK» — не характерные
    for w in ("Надо", "надо", "завтра", "потом", "обновить", "OK", "по", "и", "Скажи"):
        assert w not in got, w


def test_extract_name_only_mid_sentence() -> None:
    assert "Наташа" in vocab.extract("Я написала Наташа вчера")
    # в начале предложения заглавная — не признак имени: слово хранится строчным (слабым)
    assert vocab.extract("Наташа написала отчёт.") == ["наташа"]
    # заглавная у общего слова не делает его именем
    assert vocab.extract("Встреча с Заказчиком и Новым годом") == []


def test_extract_skips_addresses_paths_and_numbers() -> None:
    text = "Пиши на ivan@example.com, файл report.xlsx в C:\\temp\\x, см. https://x.io 12345 3,5"
    assert vocab.extract(text) == []


def test_extract_splits_compounds_and_suffixes() -> None:
    assert vocab.extract("в Metabase'е и ClickHouse-запросе") == ["Metabase", "ClickHouse"]


def test_extract_english_text_uses_common_list() -> None:
    got = vocab.extract("Please check the Kubernetes deployment and ping Alice on Monday "
                        "about the webhook refactoring.")
    assert "Kubernetes" in got and "Alice" in got and "webhook" in got
    assert "Monday" not in got and "check" not in got and "Please" not in got


def test_extract_latin_in_russian_is_term_even_if_common_english() -> None:
    # Zoom, Slack — обычные английские слова, но латиница в русской речи — термин
    assert vocab.extract("созвонимся в Zoom, потом в slack") == ["Zoom", "slack"]


def test_strength() -> None:
    assert vocab.is_strong("ClickHouse") and vocab.is_strong("Наташа") and vocab.is_strong("K8s")
    assert not vocab.is_strong("дашборд")


# ---------- агрегаты ----------

def test_merge_prefers_marked_spelling_and_sums() -> None:
    words = vocab.merge([("clickhouse", 3, 10.0), ("ClickHouse", 2, 20.0), ("наташа", 5, 5.0),
                         ("Наташа", 1, 1.0), ("дашборд", 4, 7.0)])
    by = {fold(w.word): w for w in words}
    assert by["clickhouse"].word == "ClickHouse" and by["clickhouse"].count == 5
    assert by["clickhouse"].last_ts == 20.0 and by["clickhouse"].strong
    assert by["наташа"].word == "Наташа" and by["наташа"].count == 6
    assert not by["дашборд"].strong
    # сильные слова весят вдвое: Наташа (6·2) > ClickHouse (5·2) > дашборд (4)
    assert [w.word for w in words] == ["Наташа", "ClickHouse", "дашборд"]


def test_eligibility_thresholds() -> None:
    assert not vocab.eligible(Word("Redis", 1, 0, True))
    assert vocab.eligible(Word("Redis", vocab.STRONG_MIN, 0, True))
    assert not vocab.eligible(Word("дашборд", vocab.WEAK_MIN - 1, 0, False))
    assert vocab.eligible(Word("дашборд", vocab.WEAK_MIN, 0, False))


def test_pick_words_limits_excludes_and_dedupes() -> None:
    proc = [Word(f"Proc{i}", 5, 0, True) for i in range(10)]
    gen = [Word("proc0", 9, 0, True), *(Word(f"Gen{i}", 5, 0, True) for i in range(100)),
           Word("редкий", 1, 0, False)]
    p, g = vocab.pick_words(proc, gen, {fold("Proc3")}, limit=60)
    assert "Proc3" not in p and len(p) == 9
    assert "proc0" not in g                        # уже взято из слов процесса
    assert len(p) + len(g) == 60
    p2, g2 = vocab.pick_words([], [Word("дашборд", 9, 0, False), Word("Redis", 2, 0, True)],
                              set(), strong_only=True)
    assert (p2, g2) == ([], ["Redis"])


# ---------- контекст окна ----------

def test_context_tail_takes_last_two_sentences() -> None:
    assert vocab.context_tail("Раз. Два! Три? Четыре, недописанное") == \
        "Три? Четыре, недописанное"
    assert vocab.context_tail("Первая строка\nвторая строка\n\nтретья") == \
        "вторая строка третья"
    assert vocab.context_tail("   ") == "" and vocab.context_tail(None) == ""


def test_context_tail_is_limited_by_chars_on_word_boundary() -> None:
    tail = vocab.context_tail("слово " * 200, max_chars=100)
    assert len(tail) <= 100 and tail.startswith("слово") and tail.endswith("слово")


# ---------- подсказка ----------

def test_build_prompt_order_and_dedupe() -> None:
    p = vocab.build_prompt("Привет. Как дела с отчётом?", ["ClickHouse", "Metabase", "clickhouse"],
                           ["Redis", "pytest"], ["Наташа", "redis"])
    assert p == "Привет. Как дела с отчётом? ClickHouse, Metabase, Redis, pytest, Наташа."


def test_build_prompt_without_anything_is_none() -> None:
    assert vocab.build_prompt(None, [], [], []) is None
    assert vocab.build_prompt("", ["  "], [], []) is None


def test_build_prompt_respects_token_budget_and_word_limit() -> None:
    ctx = "Очень длинный контекст окна. " * 40
    terms = [f"Term{i}" for i in range(50)]
    words = [f"Word{i}" for i in range(200)]
    p = vocab.build_prompt(ctx, terms, words, words)
    assert p is not None
    assert vocab.estimate_tokens(p) <= vocab.PROMPT_TOKENS
    head = vocab.context_tail(ctx)
    assert len(head) <= vocab.CONTEXT_CHARS
    ctx_used = p[:p.index("Term0")].strip()
    assert head.endswith(ctx_used) and vocab.estimate_tokens(ctx_used) <= vocab.CONTEXT_TOKENS
    # без контекста и терминов: частых слов не больше MAX_FREQ_WORDS
    p2 = vocab.build_prompt(None, [], [f"W{i}" for i in range(200)], [])
    assert p2 is not None and len(p2.rstrip(".").split(", ")) == vocab.MAX_FREQ_WORDS
    # термины важнее частых слов: при нехватке места частые не влезают
    big = "X" * 396            # ≈ 199 токенов по оценке — «Redis» уже не помещается
    p3 = vocab.build_prompt(None, [big], ["Redis"], [])
    assert p3 == big + "."


def test_build_prompt_skips_too_long_and_keeps_shorter() -> None:
    p = vocab.build_prompt(None, ["A" * 10, "B" * 700, "C"], [], [], max_tokens=10)
    assert p == "AAAAAAAAAA, C."


# ---------- длина подсказки в токенах Whisper ----------

# Настоящее число токенов (токенизатор large-v3-turbo, как faster-whisper кодирует подсказку:
# " " + текст). Прежняя оценка «символы / 3» занижала кириллицу, и подсказка выходила
# за 223 токена — faster-whisper молча срезал её начало (контекст окна).
REAL_TOKENS = [
    ("Добрый день, коллеги. Обновил дашборд по мерчантам, посмотрите, пожалуйста, до обеда.",
     32),
    ("Наташа просила выгрузку из Airflow к пятнице, Тимур обещал поднять Superset на тестовом "
     "стенде.", 35),
    ("ClickHouse, Metabase, Redis, Kubernetes, Grafana, PostgreSQL, Superset, Airflow, Nginx.",
     32),
    ("дашборд, мерчантов, витрину, рефакторинг, выгрузки, алерт, деплой, релиз, бэклог.", 44),
    ("Тимур, Наташа, Кирилл, Сбербанк, Тинькофф, Яндекс, Озон, Вайлдберриз, Святослав, "
     "Эльвира.", 52),
    ("K8s, GPT-4o, iPhone15, x86, Wi-Fi, Яндекс.Go, 1С, RTX3060.", 33),
]


@pytest.mark.parametrize("text,real", REAL_TOKENS)
def test_estimate_tokens_is_not_below_real(text: str, real: int) -> None:
    assert vocab.estimate_tokens(text) >= real


def test_build_prompt_uses_token_counter_and_limits_context() -> None:
    """С токенизатором модели (здесь — «токен на символ») подсказка ≤ max_tokens, контекст
    ≤ context_tokens и срезается слева по словам; термины идут после него."""
    ctx = "раз два три. " * 30 + "Пишу про"
    terms = [f"Term{i}" for i in range(40)]
    p = vocab.build_prompt(ctx, terms, ["Redis"], [], count_tokens=len)
    assert p is not None and len(p) <= vocab.PROMPT_TOKENS
    head = p[:p.index("Term0")].strip()
    assert 0 < len(head) <= vocab.CONTEXT_TOKENS and head.endswith("Пишу про")
    assert head.split()[0] in ("раз", "два", "три.")       # срез по границе слова
    assert "Term0, Term1" in p
    # итоговая проверка целиком: у этого счётчика запятые дороже, чем при сложении частей
    p2 = vocab.build_prompt(None, [f"T{i}" for i in range(100)], [], [], max_tokens=50,
                            count_tokens=lambda t: len(t) + t.count(",") * 2)
    assert p2 is not None and len(p2) + p2.count(",") * 2 <= 50


def test_build_prompt_long_russian_context_fits_budget() -> None:
    """Регрессия: контекст 300 символов + термины + ~40 русских слов — подсказка в пределах
    200 токенов по оценке, которая не меньше настоящего числа токенов."""
    ctx = ("Коллеги, по итогам созвона: мерчанты жалуются на задержки выплат, витрина комиссий "
           "пересчитывается раз в сутки, а дашборд в Metabase показывает вчерашние цифры. "
           "Предлагаю перенести пересчёт в ClickHouse, настроить алерты в Grafana и отдельно "
           "проверить выгрузку в Superset — Наташа уже смотрела логи Airflow и нашла, где")
    terms = ["ClickHouse", "Metabase", "Redis", "Kubernetes", "Grafana", "PostgreSQL"]
    words = ("мерчантов витрину дашборд выгрузку рефакторинг алерты деплой релиз бэклог "
             "спринт тикет инцидент кластер репозиторий коммит мердж ревью эндпоинт скоуп "
             "бекап Тимуру Наташе Кириллу Святославу Эльвире Сбербанк Тинькофф Вайлдберриз "
             "Озон Хабаровск Щукину Жанне Ксении Екатерине Алексею Лизе Ярославе").split()
    p = vocab.build_prompt(ctx, terms, words, [])
    assert p is not None and vocab.estimate_tokens(p) <= vocab.PROMPT_TOKENS
    assert "ClickHouse, Metabase" in p and p.endswith(".")


def test_build_prompt_with_real_tokenizer_if_model_cached() -> None:
    """Модель large-v3-turbo есть в кэше HuggingFace — настоящий счёт ≤ 200 токенов и с
    оценкой, и с токенизатором (так считает движок)."""
    tokenizers = pytest.importorskip("tokenizers")
    from rupor import fetch
    path = fetch.model_path("large-v3-turbo")
    if path is None or not (path / "tokenizer.json").is_file():
        pytest.skip("модель не скачана")
    tok = tokenizers.Tokenizer.from_file(str(path / "tokenizer.json"))

    def real(t: str) -> int:
        return len(tok.encode(" " + t.strip(), add_special_tokens=False).ids)

    ctx = "Наташа просила выгрузку по мерчантам, дашборд в Metabase опять красный. " * 6
    names = [f"{n}{e}" for n in ("Тимур", "Кирилл", "Святослав", "Вячеслав") for e in
             ("", "у", "а", "ом")]
    for counter in (None, real):
        p = vocab.build_prompt(ctx, ["ClickHouse", "Superset"], names, names,
                               count_tokens=counter)
        assert p is not None and real(p) <= vocab.PROMPT_TOKENS


# ---------- отбор слов: регрессии ----------

EVERYDAY = [
    "Можешь подсказать, где лежат ключи от машины?",
    "Передай, пожалуйста, маме, что я перезвоню вечером.",
    "Забудь, это уже неважно, давай лучше посмотрим фильм.",
    "Желаю тебе хорошего дня и удачи на экзамене.",
    "Подскажи, во сколько завтра встреча, я забыл.",
    "Давай встретимся ближе к центру, мне так удобнее.",
    "Купи, пожалуйста, хлеб, молоко и что-нибудь к чаю.",
    "Я уже выхожу, буду минут через двадцать.",
    "Спасибо большое, ты очень помог, с меня кофе.",
    "Не забудь взять зарядку и документы.",
    "Позвони мне, когда освободишься, надо кое-что обсудить.",
    "Мы вчера ходили в кино, фильм был так себе.",
    "Скинь, пожалуйста, фотографии с праздника.",
    "Поздравляю с днём рождения, желаю здоровья и счастья!",
    "Где ты сейчас? Мы ждём тебя у входа.",
    "Напомни мне завтра утром оплатить квитанцию за свет.",
]


def test_everyday_phrases_give_almost_no_words() -> None:
    got = [w for t in EVERYDAY for w in vocab.extract(t)]
    assert len(got) <= 2, got
    for w in ("можешь", "лежат", "подскажи", "желаю", "ближе", "передай", "забудь", "фильм"):
        assert w not in got


@pytest.mark.parametrize("word", ["можешь", "лежат", "лежишь", "подскажи", "подсказал",
                                  "желаю", "передай", "забудь", "говоришь", "смотрят",
                                  "используем", "вернётся", "откроешь", "экзамене"])
def test_common_verb_forms_and_prefixes(word: str) -> None:
    assert vocab.is_common_ru(word) or vocab.is_common_ru_prefixed(word)


def test_verb_forms_regular_conjugations() -> None:
    assert {"лежу", "лежишь", "лежат", "лежал"} <= vocab.verb_forms("лежать")
    assert {"говорю", "говоришь", "говорят", "говорили"} <= vocab.verb_forms("говорить")
    assert {"использую", "используют"} <= vocab.verb_forms("использовать")
    assert {"открою", "откроешь"} <= vocab.verb_forms("открыть")
    assert {"возвращается", "возвращаюсь"} <= vocab.verb_forms("возвращаться")
    assert vocab.verb_forms("дашборд") == set() and vocab.verb_forms("мать") == set()


def test_extract_keeps_latin_compounds_and_brands() -> None:
    assert vocab.extract("Подключи Wi-Fi и проверь GPT-4o") == ["Wi-Fi", "GPT-4o"]
    assert vocab.extract("Закажи через Яндекс.Go, а не Яндекс.Маркет.") == [
        "Яндекс.Go", "Яндекс.Маркет"]
    assert vocab.extract("Привет.Как дела") == []           # нет пробела после точки
    assert vocab.extract("Встреча в Санкт-Петербурге") == ["Санкт-Петербурге"]
    assert vocab.extract("книга O’Reilly и Metabase's API") == [
        "O’Reilly", "Metabase", "API"]


def test_extract_drops_password_like_tokens() -> None:
    assert vocab.extract("Пароль Summer2024, логин qwerty123, код Passw0rd и abc123") == []
    assert vocab.extract("K8s, GPT4, iPhone15, x86, Win11, RTX3060, 1С и H264") == [
        "K8s", "GPT4", "iPhone15", "x86", "Win11", "RTX3060", "1С", "H264"]


# ---------- слияние падежей ----------

def test_group_key_merges_case_forms() -> None:
    assert len({vocab.group_key(w) for w in ("Тимуру", "Тимура", "Тимуром", "Тимур")}) == 1
    assert len({vocab.group_key(w) for w in ("Наташе", "Наташа", "Наташу", "Наташи")}) == 1
    assert vocab.group_key("СДЭК") == "сдэк" and vocab.group_key("ClickHouse") == "clickhouse"
    assert vocab.group_key("Ян") != vocab.group_key("Яна")         # короткая основа


def test_merge_prefers_nominative_and_sums_cases() -> None:
    ws = vocab.merge([("Тимуру", 3, 1.0), ("Тимура", 2, 2.0), ("Тимуром", 1, 3.0),
                      ("Тимур", 1, 4.0), ("Наташе", 2, 1.0), ("Наташу", 1, 1.0),
                      ("Наташа", 1, 1.0), ("Наташей", 1, 1.0), ("дашборда", 2, 1.0),
                      ("дашборд", 1, 1.0)])
    by = {w.word: w for w in ws}
    assert by["Тимур"].count == 7 and by["Наташа"].count == 5 and by["дашборд"].count == 3
    # без именительного — самая частая форма; «тимур» из начала предложения — с заглавной
    assert [w.word for w in vocab.merge([("Тимуру", 3, 1.0), ("Тимура", 2, 1.0)])] == ["Тимуру"]
    assert [w.word for w in vocab.merge([("Тимуру", 3, 1.0), ("тимур", 1, 1.0)])] == ["Тимур"]
    # родительный мужского рода («Тимура» при «Тимуром») именительным не считается
    assert [w.word for w in vocab.merge([("Тимура", 3, 1.0), ("Тимуром", 1, 1.0)])] == [
        "Тимура"]


def test_exclusion_covers_all_forms() -> None:
    ws = vocab.merge([("Тимуру", 3, 1.0), ("Тимура", 2, 1.0), ("Redis", 2, 1.0)])
    assert vocab.pick_words([], ws, {"тимуру"}) == ([], ["Redis"])
    assert vocab.pick_words([], ws, {"тимура"}, strong_only=True) == ([], ["Redis"])
    assert vocab.pick_words([], ws, set()) == ([], ["Тимуру", "Redis"])


def test_weak_english_words_are_marked_only_in_storage_form() -> None:
    """Редкое строчное слово английского текста — слабое: в строке для vocab — с меткой,
    наружу (extract, merge) — без неё; сильная форма того же слова делает сильным всё слово."""
    text = "Please review the deployment checklist."
    assert vocab.extract(text) == ["deployment", "checklist"]
    assert dict(vocab.counts(text)) == {"~deployment": 1, "~checklist": 1}
    assert dict(vocab.counts("проверь deployment")) == {"deployment": 1}   # термин
    words = vocab.merge([("~deployment", 3, 1.0), ("Kubernetes", 2, 2.0),
                         ("~kubernetes", 1, 3.0)])
    by = {fold(w.word): w for w in words}
    assert by["deployment"].word == "deployment" and not by["deployment"].strong
    assert by["kubernetes"].word == "Kubernetes" and by["kubernetes"].strong
    assert by["kubernetes"].count == 3
    assert vocab.is_everyday_en("Monday") and vocab.is_everyday_en("english")
    assert not vocab.is_everyday_en("Kubernetes")
