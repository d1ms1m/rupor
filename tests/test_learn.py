"""Обучение словаря на правках: чистая логика learn.py (без Windows).

Таблица кейсов: что пользователь вставил диктовкой (фрагмент), что стало в поле после
его правок и какие правки должны (или не должны) попасть в словарь."""
from __future__ import annotations

from typing import Any

import pytest

from rupor import learn, textproc


def found(fragment: str, after: str, prefix: str = "",
          dictionary: list[dict[str, Any]] | None = None) -> list[learn.Correction]:
    before = prefix + fragment
    span = learn.fragment_span(before, fragment)
    assert span is not None
    return learn.find_corrections(before, span, after, dictionary or [])


def corrections(fragment: str, after: str, prefix: str = "",
                dictionary: list[dict[str, Any]] | None = None) -> list[tuple[str, str]]:
    return [(c.term, c.variant) for c in found(fragment, after, prefix, dictionary)]


def sure(fragment: str, after: str, prefix: str = "") -> list[tuple[str, str]]:
    """Что режим auto добавит сразу (без «Добавить»)."""
    return [(c.term, c.variant) for c in found(fragment, after, prefix) if c.sure]


# ---------- правки, которые похожи на ошибку распознавания ----------

POSITIVE: list[tuple[str, str, str, list[tuple[str, str]]]] = [
    # (что было в поле до вставки, вставленный фрагмент, поле после правок, ожидание)
    ("", "проверь метабейс сегодня", "проверь Metabase сегодня", [("Metabase", "метабейс")]),
    ("", "данные лежат в клик хаус", "данные лежат в ClickHouse",
     [("ClickHouse", "клик хаус")]),
    ("", "открой графана дашборд", "открой Grafana дашборд", [("Grafana", "графана")]),
    ("", "привет, Сёма, как дела", "привет, Сема, как дела", [("Сема", "")]),
    ("", "залей в гитхаб репозиторий", "залей в GitHub репозиторий", [("GitHub", "гитхаб")]),
    ("", "таблица в эксель готова", "таблица в Excel готова", [("Excel", "эксель")]),
    ("", "задача в джире висит", "задача в Jira висит", [("Jira", "джира")]),
    ("", "пишу на питоне", "пишу на Python", [("Python", "питон")]),
    ("", "запусти в кубернетис", "запусти в Kubernetes", [("Kubernetes", "кубернетис")]),
    ("", "база clickhouse упала", "база ClickHouse упала", [("ClickHouse", "")]),
    ("", "запрос к api сервиса", "запрос к API сервиса", [("API", "")]),
    ("", "проверь Metabays сегодня", "проверь Metabase сегодня",
     [("Metabase", "Metabays")]),
    ("", "клик хаус упал", "ClickHouse упал", [("ClickHouse", "клик хаус")]),
    ("", "это сказал петя вчера", "это сказал Петя вчера", [("Петя", "")]),
    ("", "звонок в зуме", "звонок в Zoom", [("Zoom", "зуме")]),    # ≤ 4 букв: только предложить
    ("", "метабейс и графана работают", "Metabase и Grafana работают",
     [("Metabase", "метабейс"), ("Grafana", "графана")]),
    ("", "метабейс графана", "Metabase Grafana",
     [("Metabase", "метабейс"), ("Grafana", "графана")]),
    ("", "данные в метабейсе", "данные в Metabase", [("Metabase", "метабейс")]),
    ("", "настрой вебхук", "настрой webhook", [("webhook", "вебхук")]),
    ("Коллеги, ", "докер упал", "Коллеги, Docker упал", [("Docker", "докер")]),
    ("Привет! ", "в клик хаусе всё хорошо", "Привет! В ClickHouse всё хорошо",
     [("ClickHouse", "клик хаус")]),
    ("", "разверни на ноушен", "разверни на Notion", [("Notion", "ноушен")]),
    ("", "клик хаус и графана", "Click House и Grafana",
     [("Click House", "клик хаус"), ("Grafana", "графана")]),
    ("", "запусти это питон скрипт", "запусти Python скрипт", [("Python", "питон")]),
]


@pytest.mark.parametrize("prefix, fragment, after, expected", POSITIVE)
def test_learns_recognition_errors(prefix: str, fragment: str, after: str,
                                   expected: list[tuple[str, str]]) -> None:
    assert corrections(fragment, after, prefix) == expected


def test_positive_table_is_big_enough() -> None:
    assert len(POSITIVE) >= 15 and len(NEGATIVE) >= 15


def test_merges_with_existing_term() -> None:
    d = [{"term": "Metabase", "variants": ["мета бейс"]}]
    assert corrections("проверь метабейс", "проверь Metabase", dictionary=d) == [
        ("Metabase", "метабейс")]


# ---------- правки по смыслу и прочее — не учимся ----------

NEGATIVE: list[tuple[str, str, str, list[dict[str, Any]]]] = [
    ("", "приду завтра вечером", "приду послезавтра вечером", []),       # смысл
    ("", "мы придём", "вы придём", []),                                  # короткие слова
    ("", "привет как дела", "привет, как дела?", []),                    # пунктуация
    ("", "привет как дела", "Привет как дела", []),                      # начало предложения
    ("", "я думаю что это хорошо", "я думаю это хорошо", []),            # удаление слова
    ("", "это хорошо", "это очень хорошо", []),                          # добавление слова
    ("", "встреча в пять часов", "встреча в 5 часов", []),              # число словами → цифры
    ("", "счёт 2024 года", "счёт 2025 года", []),                        # числа → числа
    ("", "пишу на Java", "пишу на JavaScript", []),                      # расширение слова
    ("", "I think their code works", "I think there code works", []),    # английское слово
    ("", "передай Наташе привет", "передай Даше привет", []),            # другое имя
    ("", "давай встретимся завтра", "давай созвонимся в пятницу", []),  # переписана фраза
    ("Метабейс: ", "всё работает", "Metabase: всё работает", []),        # правка вне вставки
    ("", "проверь метабейс", "проверь Metabase",
     [{"term": "Metabase", "variants": ["метабейс"]}]),                  # уже в словаре
    ("", "проверь метабейс", "проверь Metabaza",
     [{"term": "Metabase", "variants": ["метабейс"]}]),                  # вариант чужого термина
    ("", "база ClickHouse", "база Clickhouse",
     [{"term": "ClickHouse", "variants": []}]),                          # правка термина словаря
    ("", "это всё", "это все", []),                                      # «ё» в обычном слове
    ("", "спасибо вам большое", "спасибо Вам большое", []),              # вежливое «Вам»
    ("", "python is great", "Python is great", []),                      # начало предложения
    ("", "открой метабейс", "открой Grafana", []),                       # не похоже по звучанию
    ("", "позвони Коле", "позвони Васе", []),                            # другое имя
    ("", "пасёт карова", "пасёт корова", []),                            # опечатка обычного слова
]


@pytest.mark.parametrize("prefix, fragment, after, dictionary", NEGATIVE)
def test_ignores_non_recognition_edits(prefix: str, fragment: str, after: str,
                                       dictionary: list[dict[str, Any]]) -> None:
    assert corrections(fragment, after, prefix, dictionary) == []


# ---------- вспомогательное ----------

def test_skeleton_and_similarity() -> None:
    assert learn.skeleton("Клик хаус") == "klikhaus"
    assert learn.skeleton("ClickHouse") == "klikhouse"
    assert learn.skeleton("джира") == learn.skeleton("Jira")
    assert learn.skeleton("эксель") == learn.skeleton("Excel")
    assert learn.similarity("метабейс", "Metabase") >= learn.SIM_CROSS
    assert learn.similarity("графана", "Grafana") == 1.0
    assert learn.similarity("открой", "Grafana") < learn.SIM_CROSS


def test_tokenize_and_norm_text() -> None:
    assert [t.text for t in learn.tokenize("В ClickHouse-запросе, 3,5 сек.")] == [
        "В", "ClickHouse-запросе", "3,5", "сек"]
    assert learn.norm_text("а\r\nб\rв") == "а\nб\nв"


def test_fragment_span() -> None:
    text = "раз два. раз  два\nтри"
    assert learn.fragment_span(text, "раз два") == (9, 17)       # последнее вхождение
    assert learn.fragment_span(text, "два три") == (14, 21)      # перевод строки вместо пробела
    assert learn.fragment_span(text, "нет такого") is None
    assert learn.fragment_span(text, "...") is None


@pytest.mark.parametrize("after, alive", [
    ("Итог: проверь Metabase сегодня ", True),            # одно слово исправлено
    ("Итог: проверь метабейс сегодня. Спасибо", True),     # дописано после
    ("Итог: проверь Metabase ", True),                     # слово удалено, слово исправлено
    ("", False),                                           # поле очищено (сообщение ушло)
    ("Итог: ", False),                                     # фрагмент удалён
    ("Совсем другой текст про погоду", False),             # переписано целиком
])
def test_fragment_alive(after: str, alive: bool) -> None:
    before = "Итог: проверь метабейс сегодня "
    span = learn.fragment_span(before, "проверь метабейс сегодня ")
    assert span is not None
    assert learn.fragment_alive(before, span, after) is alive


def test_single_word_fragment_alive_after_correction() -> None:
    before = "метабейс"
    span = learn.fragment_span(before, "метабейс ")
    assert span is not None
    assert learn.fragment_alive(before, span, "Metabase")
    assert not learn.fragment_alive(before, span, "привет")


def test_long_document_is_fast() -> None:
    body = " ".join(f"слово{i}" for i in range(4000))
    before = body + " проверь метабейс сегодня " + body
    after = body + " проверь Metabase сегодня " + body
    span = learn.fragment_span(before, "проверь метабейс сегодня")
    assert span is not None
    assert learn.find_corrections(before, span, after) == [
        learn.Correction("Metabase", "метабейс")]


def test_learned_variant_works_in_dictionary() -> None:
    """Выученный вариант (с отрезанным окончанием) ловит и другие падежи."""
    items = [{"term": "Metabase", "variants": ["метабейс"]},
             {"term": "ClickHouse", "variants": ["клик хаус"]},
             {"term": "Jira", "variants": ["джира"]}]
    assert textproc.apply_dictionary("в метабейсе и клик хаусом, задачи из джиры",
                                     items) == "в Metabase и ClickHouse, задачи из Jira"


def test_texts() -> None:
    assert learn.added_text("Metabase", "метабейс") == "В словарь добавлено: «метабейс» → Metabase"
    assert learn.added_text("ClickHouse", "") == "В словарь добавлено: ClickHouse"
    assert learn.suggest_text("Metabase", "метабейс") == \
        "Добавить в словарь: «метабейс» → Metabase?"
    assert learn.pair_key("ClickHouse", "Клик Хаус") == learn.pair_key("clickhouse", "клик хаус")


def test_at_most_three_per_watch() -> None:
    got = corrections("метабейс графана кафка докер", "Metabase Grafana Kafka Docker")
    assert len(got) == learn.MAX_PER_EVAL
    assert len(found("метабейс графана кафка докер", "Metabase Grafana Kafka Docker")) == 3


# ---------- уверенность: что auto добавит сразу, а что только предложит ----------

@pytest.mark.parametrize("fragment, after, expected, is_sure", [
    ("проверь метабейс сегодня", "проверь Metabase сегодня", ("Metabase", "метабейс"), True),
    ("данные лежат в клик хаус", "данные лежат в ClickHouse", ("ClickHouse", "клик хаус"),
     True),
    ("привет, Сёма, как дела", "привет, Сема, как дела", ("Сема", ""), True),     # только «ё»
    ("база clickhouse упала", "база ClickHouse упала", ("ClickHouse", ""), True),
    ("посылку привёз сдэк", "посылку привёз СДЭК", ("СДЭК", ""), True),
    ("это сказал петя вчера", "это сказал Петя вчера", ("Петя", ""), False),   # имя? оформление?
    ("настрой вебхук", "настрой webhook", ("webhook", "вебхук"), False),         # строчная латиница
    ("звонок в зуме", "звонок в Zoom", ("Zoom", "зуме"), False),                 # короткий вариант
    ("напиши в слак", "напиши в Slack", ("Slack", "слак"), False),
    ("проверь Metabays сегодня", "проверь Metabase сегодня", ("Metabase", "Metabays"),
     False),                                                                      # оба — термины
    ("база на MySQL", "база на MSSQL", ("MSSQL", "MySQL"), False),
    ("hi Жора, see you", "hi Zhora, see you", ("Zhora", "Жора"), False),         # латинское окружение
])
def test_confidence(fragment: str, after: str, expected: tuple[str, str],
                    is_sure: bool) -> None:
    got = found(fragment, after)
    assert [(c.term, c.variant) for c in got] == [expected]
    assert got[0].sure is is_sure


# ---------- регрессии: правки, которые испортили бы будущие диктовки ----------

# (фрагмент, поле после правки, будущая диктовка — она не должна измениться)
NOT_LEARNED: list[tuple[str, str, str]] = [
    # находка 1: грамматика — падеж имени, города, термина; русское окончание у латиницы
    ("передай Наташа что всё готово", "передай Наташе что всё готово", "Наташа придёт"),
    ("я сейчас в Москва", "я сейчас в Москве", "Москва большая"),
    ("позвони Наталья сегодня", "позвони Наталье сегодня", "Наталья звонила"),
    ("скажи Оксана спасибо", "скажи Оксане спасибо", "Оксана молодец"),
    ("напиши Александре Петровичу", "напиши Александру Петровичу", "об Александре"),
    ("спроси у Кузнецова", "спроси у Кузнецовой", "Кузнецова сказал"),
    ("тикет в Джира висит", "тикет в Джире висит", "Джира тормозит"),
    ("отчёт в Metabase готов", "отчёт в Metabase'е готов", "открой Metabase"),
    ("отчёт в Metabase готов", "отчёт в Metabase-е готов", "открой Metabase"),
    ("таблица в Excel готова", "таблица в Excel’е готова", "открой Excel"),
    ("я написал Наташе вчера", "мне написала Наташа вчера", "позвони Наташе"),
    ("передай Валере привет", "передай Валерии привет", "Валере скажи"),
    # находки 2 и 14: только регистр — оформление, праздник, обычное слово, список
    ("поздравляю с новым годом", "поздравляю с Новым годом", "с новым сотрудником"),
    ("поздравляю с днём рождения", "поздравляю с Днём рождения", "приду днём"),
    ("с днём победы", "с Днём Победы", "до победы далеко"),
    ("оплачу картой мир", "оплачу картой Мир", "мир тесен"),
    ("оплату производит заказчик", "оплату производит Заказчик", "заказчик доволен"),
    ("это компания рога и копыта", "это компания Рога и Копыта", "рога оленя"),
    ("купить: молоко, хлеб, сыр", "купить: Молоко, Хлеб, Сыр", "молоко и хлеб"),
    ("план:\n1) отчёт\n2) звонок", "план:\n1) Отчёт\n2) Звонок", "отчёт готов"),
    ("• отчёт\n• звонок", "• Отчёт\n• Звонок", "звонок в пять"),
    ("* задачи на неделю", "* Задачи на неделю", "задачи на завтра"),
    ("# итоги встречи", "# Итоги встречи", "итоги подведём"),
    ("✅ отчёт готов", "✅ Отчёт готов", "отчёт готов"),
    ("итог — отчёт готов", "итог — Отчёт готов", "отчёт готов"),
    ("project status update", "Project Status Update", "status is fine"),
    ("quarterly report for review", "Quarterly Report for Review", "send the report"),
    ("проверь рабочую почту", "проверь Рабочую почту", "рабочую неделю"),
    ("пришли договор", "пришли Договор", "подпиши договор и верни договоры"),
    ("в понедельник", "в Понедельник", "в понедельник"),
    # находка 4: смысловая замена похожего имени, продукта, номера
    ("перейдём на React", "перейдём на Preact", "React хорош"),
    ("см. задачу RUPOR-12", "см. задачу RUPOR-13", "RUPOR-12 закрыта"),
    ("модель GPT-4 лучше", "модель GPT-5 лучше", "GPT-4"),
    ("спроси в чатике", "спроси в ChatGPT", "напиши в чатике"),
    ("позвони Даше", "позвони Маше", "Даше"),
    # находки 5 и 15: перевод обычного слова на английский
    ("это наш проект", "это наш project", "проект сдан"),
    ("прогони тесты", "прогони tests", "тест прошёл, тесты упали"),
    ("упал сервер", "упал server", "сервер упал"),
    ("открой браузер", "открой browser", "браузер завис"),
    ("говорю на русском", "говорю на Russian", "русский язык"),
    ("английский клуб", "English клуб", "английский клуб"),
    ("flight to Москва tomorrow", "flight to Moscow tomorrow", "я в Москве, из Москвы"),
    ("hi Сергей, see you", "hi Sergey, see you", "Сергей придёт"),
    ("hi Андрей", "hi Andrey", "Андрей, Андрею"),
    ("живу в Moscow", "живу в Москва", "Moscow is big"),                 # и обратно
]


@pytest.mark.parametrize("fragment, after, future", NOT_LEARNED)
def test_regressions_not_learned(fragment: str, after: str, future: str) -> None:
    got = found(fragment, after)
    assert got == [], [(c.term, c.variant) for c in got]


def test_regressions_table_future_is_safe() -> None:
    """Даже если бы кейс из таблицы выучился — проверяем, что будущая диктовка цела."""
    for fragment, after, future in NOT_LEARNED:
        items = [{"term": c.term, "variants": [c.variant] if c.variant else []}
                 for c in found(fragment, after)]
        assert textproc.apply_dictionary(future, items) == future, fragment


# Находка 6: удалённое заодно соседнее слово не входит в вариант
@pytest.mark.parametrize("fragment, after, expected, future", [
    ("посмотри в этом метабейсе", "посмотри в Metabase", ("Metabase", "метабейс"),
     "в этом метабейсе"),
    ("лежит в нашем метабейсе", "лежит в Metabase", ("Metabase", "метабейс"),
     "в нашем метабейсе"),
    ("открой новый метабейс", "открой Metabase", ("Metabase", "метабейс"),
     "открой новый метабейс"),
    ("запусти это питон скрипт", "запусти Python скрипт", ("Python", "питон"), "это питон"),
])
def test_deleted_neighbour_word_is_not_in_variant(fragment: str, after: str,
                                                 expected: tuple[str, str],
                                                 future: str) -> None:
    got = found(fragment, after)
    assert [(c.term, c.variant) for c in got] == [expected]
    items = [{"term": expected[0], "variants": [expected[1]]}]
    kept = future.split()[:-1]
    assert textproc.apply_dictionary(future, items).split()[:-1] == kept   # слова не пропали


def test_multiword_variant_kept_when_every_word_sounds() -> None:
    assert corrections("пароль от вай фай", "пароль от Wi-Fi") == [("Wi-Fi", "вай фай")]
    assert corrections("видео в тик так", "видео в TikTok") == [("TikTok", "тик так")]
    assert corrections("кэш в ред ис", "кэш в Redis") == [("Redis", "ред ис")]


@pytest.mark.parametrize("variant, term, stem", [
    ("метабейсе", "Metabase", "метабейс"),
    ("клик хаусе", "ClickHouse", "клик хаус"),
    ("клик хаусом", "ClickHouse", "клик хаус"),
    ("питона", "Python", "питон"),
    ("докером", "Docker", "докер"),
    ("гугле", "Google", "гугл"),
    ("джире", "Jira", "джира"),
    # находка 5: окончание, которое звучит в термине, не режется
    ("Сергей", "Sergey", "Сергей"),
    ("Андрей", "Andrey", "Андрей"),
    ("тесты", "tests", "тесты"),
    ("Москва", "Moscow", "Москва"),
])
def test_stem_variant(variant: str, term: str, stem: str) -> None:
    assert learn._stem_variant(variant, term) == stem


def test_short_variant_after_stemming_is_only_suggested() -> None:
    """Находки 5 и 8: короткий вариант (в том числе после отрезания окончания) —
    не правило сразу, а предложение с вариантом (не «слабый» термин без варианта)."""
    got = found("поищи в гугле", "поищи в Google")
    assert [(c.term, c.variant, c.sure) for c in got] == [("Google", "гугл", False)]
    got = found("доска в миро", "доска в Miro")
    assert [(c.term, c.variant, c.sure) for c in got] == [("Miro", "миро", False)]


def test_cyrillic_case_only_name_is_only_suggested() -> None:
    """Находка 14: падежная форма имени (заглавная) — не в словарь сразу."""
    for fragment, after, term in [("позвони маше", "позвони Маше", "Маше"),
                                  ("напиши сергею", "напиши Сергею", "Сергею")]:
        got = found(fragment, after)
        assert [(c.term, c.variant, c.sure) for c in got] == [(term, "", False)]


def test_two_camel_case_terms_next_to_each_other_are_learned() -> None:
    """Правило «несколько заглавных рядом — оформление» не трогает ClickHouse/API."""
    assert corrections("clickhouse и metabase", "ClickHouse и Metabase") == [
        ("ClickHouse", ""), ("Metabase", "")]


@pytest.mark.parametrize("text, word, start", [
    ("привет", "привет", True),
    ("Итог. Отчёт", "Отчёт", True),
    ("купить: Молоко", "Молоко", True),
    ("план:\n1) Отчёт", "Отчёт", True),
    ("• Отчёт", "Отчёт", True),
    ("- Отчёт", "Отчёт", True),
    ("* Задачи", "Задачи", True),
    ("# Итоги", "Итоги", True),
    ("✅ Отчёт", "Отчёт", True),
    ("итог — Отчёт", "Отчёт", True),
    ("«Привет", "Привет", True),
    ("сказал Петя", "Петя", False),
    ("привет, Сема", "Сема", False),
    ("фильм «Интерстеллар»", "Интерстеллар", False),
    ("ок ✅ Отчёт", "Отчёт", False),
])
def test_sentence_start(text: str, word: str, start: bool) -> None:
    assert learn._sentence_start(text, text.rindex(word)) is start


# ---------- held_corrections: сколько правка держалась в поле ----------

def _snaps(*items: tuple[str, float, float]) -> list[learn.Snapshot]:
    before = "данные в клик хаус "
    span = learn.fragment_span(before, "данные в клик хаус")
    assert span is not None
    out = [learn.Snapshot(before, 0.0, 0.0)]
    for text, first, last in items:
        out.append(learn.Snapshot(text, first, last, bool(text.strip()) and
                                  learn.fragment_alive(before, span, text)))
    return out


def _held(snaps: list[learn.Snapshot], horizon: float = 1.0) -> list[tuple[str, float]]:
    before = snaps[0].text
    span = learn.fragment_span(before, "данные в клик хаус")
    assert span is not None
    return [(c.term, round(h, 3)) for c, h in learn.held_corrections(before, span, snaps,
                                                                      horizon=horizon)]


def test_held_truncated_last_snapshot() -> None:
    """Enter через 0,15 с после последней буквы: оцениваемый снимок прочитан один раз —
    правка «держалась» 0 с, какой бы она ни была."""
    snaps = _snaps(("данные в Click ", 1.0, 1.0), ("данные в ClickHou ", 1.4, 1.4), ("", 1.8, 1.8))
    assert _held(snaps) == [("ClickHou", 0.0)]


def test_held_counts_from_first_snapshot_with_same_word() -> None:
    snaps = _snaps(("данные в Click ", 1.0, 1.1), ("данные в ClickHouse ", 1.2, 1.6),
                   ("данные в ClickHouse упал ", 1.7, 2.5), ("", 2.6, 2.6))
    assert _held(snaps) == [("ClickHouse", 1.3)]           # 2.5 − 1.2: дописывали дальше


def test_held_stops_at_dead_snapshot_and_horizon() -> None:
    snaps = _snaps(("данные в ClickHouse ", 1.0, 1.0), ("", 1.1, 1.1),
                   ("данные в ClickHouse ", 2.0, 2.2))
    assert _held(snaps) == [("ClickHouse", 0.2)]           # поле очищали — отсчёт заново
    long = _snaps(*[(f"данные в ClickHouse {'x' * k}", float(k), k + 0.5) for k in range(1, 8)])
    assert _held(long, horizon=1.0) == [("ClickHouse", 1.5)]   # дальше горизонта не смотрим


def test_held_nothing_alive() -> None:
    assert _held(_snaps(("", 1.0, 1.0))) == []


@pytest.mark.parametrize("fragment, after, expected", [
    ("данные в клик хаус", "данные в ClickHouse упал", [("ClickHouse", "клик хаус")]),
    ("открой метабейс", "открой новый Metabase", [("Metabase", "метабейс")]),
    ("данные в клик хаус сегодня", "данные в ClickHouse вчера", []),   # «сегодня» → «вчера»
])
def test_appended_word_is_not_in_term(fragment: str, after: str,
                                      expected: list[tuple[str, str]]) -> None:
    assert corrections(fragment, after) == expected


# ---------- английский текст: заглавная у обычного слова — не термин ----------

@pytest.mark.parametrize("fragment, after", [
    ("Let's talk on monday after lunch.", "Let's talk on Monday after lunch."),
    ("See you in january then.", "See you in January then."),
    ("I can write it in english if needed.", "I can write it in English if needed."),
    ("He speaks russian and german fluently.", "He speaks Russian and German fluently."),
    ("we moved it to friday", "we moved it to Friday"),
    ("monday", "Monday"),                                   # одно слово в поле без кириллицы
])
def test_english_everyday_capitalization_is_not_learned(fragment: str, after: str) -> None:
    """Правка регистра у дня недели, месяца, языка в английском тексте — правописание:
    ни в словарь, ни в предложения (раньше такое добавлялось сразу, sure=True)."""
    assert found(fragment, after) == []


@pytest.mark.parametrize("fragment, after, term", [
    ("Happy thanksgiving to the whole team.", "Happy Thanksgiving to the whole team.",
     "Thanksgiving"),
    ("She flew to london last week.", "She flew to London last week.", "London"),
    ("we deploy to kubernetes today", "we deploy to Kubernetes today", "Kubernetes"),
])
def test_english_plain_capitalization_is_only_suggested(fragment: str, after: str,
                                                        term: str) -> None:
    """Прочие слова с поднятой первой буквой в английском тексте (имя, название) — только
    предложить, как «петя» → «Петя» в русском."""
    got = found(fragment, after)
    assert [(c.term, c.variant, c.sure) for c in got] == [(term, "", False)]


@pytest.mark.parametrize("fragment, after, term", [
    ("we store events in clickhouse now", "we store events in ClickHouse now", "ClickHouse"),
    ("ping me on github later", "ping me on GitHub later", "GitHub"),
    ("the api is down again", "the API is down again", "API"),
    ("созвон в zoom завтра", "созвон в Zoom завтра", "Zoom"),        # латиница в русской речи
    ("напиши в slack", "напиши в Slack", "Slack"),
])
def test_terms_are_still_learned_in_english_and_russian_text(fragment: str, after: str,
                                                             term: str) -> None:
    got = found(fragment, after)
    assert [(c.term, c.variant, c.sure) for c in got] == [(term, "", True)]
