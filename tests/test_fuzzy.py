"""Тесты fuzzy: похожие написания терминов словаря без списка вариантов.

Слово языка или нет — проверка орфографии Windows (spell.py). Без словарей ru-RU/en-US
тесты на неё пропускаются; запасной режим (частотные списки) проверяется отдельно."""
from __future__ import annotations

import time
from typing import Any

import pytest

from rupor import fuzzy, spell, vocab
from rupor.fuzzy import sound_key


def terms(*names: str) -> list[dict[str, Any]]:
    return [{"term": n, "variants": []} for n in names]


# Словарь пользователя, внесённый «одним термином» — без вариантов
USER = terms("GeoNode", "Zennoposter", "Zenno", "Зенка", "Зеннопостер", "ZennoBrowser")
TECH = terms("ClickHouse", "Metabase", "Grafana", "Kubernetes", "Postgres", "Сбербанк",
             "Telegram", "Claude", "Cursor", "Redis", "Signal", "Kafka", "Python", "Docker",
             "Proxmox", "Notion", "Grafana Cloud", "GitHub", "Jira", "Gemini", "Numlex",
             "Cloudflare", "Госуслуги", "Точка", "Consul", "Loki", "Ozon", "Tailscale",
             "Anthropic", "WildDuck", "Proxypool", "Miro", "Asana", "Superset", "Slack",
             "Airflow", "Claude Code")
ALL = USER + TECH


def _lexicon() -> bool:
    got = spell.known_words(["курсор", "кубернетис", "cloud", "Xenoposter"])
    return got == {"курсор": True, "кубернетис": False, "cloud": True, "Xenoposter": False}


needs_lexicon = pytest.mark.skipif(not _lexicon(),
                                   reason="нет проверки орфографии Windows ru-RU/en-US")


def fx(text: str, items: list[dict[str, Any]] = ALL) -> str:
    return fuzzy.apply_text(text, items)


# ---------- звучание ----------

@pytest.mark.parametrize("a, b", [
    ("ZennoBrowser", "Xena браузер"),        # латиница ↔ кириллица, x в начале — «з»
    ("ZennoBrowser", "Zenno Browser"),
    ("ZennoBrowser", "Xeno-браузер"),
    ("Zennoposter", "Xenoposter"),
    ("Zennoposter", "Ксенопостер"),          # «кс» в начале — тоже «з»
    ("Zennoposter", "зеннопостер"),
    ("GeoNode", "Гео ноут"),                 # магическая e, д = т
    ("GeoNode", "GeoNote"),
    ("Metabase", "метабейс"),
    ("ClickHouse", "клик хаус"),             # ou → au, немая e
    ("Grafana", "графана"),
    ("Jira", "джира"),                       # j = «дж» = «ч»
    ("BestChange", "бест чейндж"),           # ch — «ч», не «х»
])
def test_sound_key_same(a: str, b: str) -> None:
    assert sound_key(a) == sound_key(b)


@pytest.mark.parametrize("term, heard, reading", [
    ("GeoNode", "Геонод", "letters"),        # побуквенное прочтение
    ("Metabase", "Метабаз", "letters"),
    ("GitHub", "гитхаб", "closed_u"),        # u как «а»
    ("Gemini", "джемини", "soft_g"),         # мягкое g
])
def test_other_readings_of_latin_terms(term: str, heard: str, reading: str) -> None:
    assert sound_key(term, reading) == sound_key(heard)
    assert sound_key(term) != sound_key(heard)


def test_sound_key_first_sound_keeps_voicing() -> None:
    """Звонкие/глухие сливаются, но первый звук — нет: «Сенька» не звучит как «Зенка»."""
    assert sound_key("Сенька").body == sound_key("Зенка").body
    assert sound_key("Сенька").head != sound_key("Зенка").head


# ---------- замены ----------

@needs_lexicon
@pytest.mark.parametrize("src, out", [
    # случаи из истории пользователя (термины внесены без вариантов)
    ("у тебя MCP к Xenobowser. Может быть", "у тебя MCP к ZennoBrowser. Может быть"),
    ("на открытый Zenobowser посмотреть", "на открытый ZennoBrowser посмотреть"),
    ("если использовать Xena браузер или обычный", "если использовать ZennoBrowser или обычный"),
    ("путь с браузером обычным или Xeno-браузером.", "путь с браузером обычным или ZennoBrowser."),
    ("Мне нужен именно шаблон Xenoposter. Понял?", "Мне нужен именно шаблон Zennoposter. Понял?"),
    ("в следующий раз GeoNote еще раз", "в следующий раз GeoNode еще раз"),
    # раздельно, падежи, кириллический термин получает окончание
    ("в зенно браузере открой", "в ZennoBrowser открой"),
    ("в Ксено браузере открой", "в ZennoBrowser открой"),
    ("шаблон ксенопостера готов", "шаблон Зеннопостера готов"),
    ("Xeno poster не видит", "Zennoposter не видит"),
    ("на гео ноуте", "на GeoNode"),
    ("Геонод прокси", "GeoNode прокси"),
    ("метабейс дашборд", "Metabase дашборд"),
    ("Метабаза дашборд", "Metabase дашборд"),
    ("в графане алерт", "в Grafana алерт"),
    ("кубернетис кластер", "Kubernetes кластер"),
    ("в постгресе таблица", "в Postgres таблица"),
    ("в телеграме", "в Telegram"),
    ("в сбер банке", "в Сбербанке"),
    ("на гитхабе репо", "на GitHub репо"),
    ("в джире задача", "в Jira задача"),     # 4 звука — буква в букву
    ("Джемини ответил", "Gemini ответил"),
    ("Намлекс отчёт", "Numlex отчёт"),
    # раздельное написание термина и термин + соседнее слово — как в словаре
    ("Cloud Flare DNS", "Cloudflare DNS"),
    ("Zenno Poster", "Zennoposter"),
    ("Zenno браузер открыт", "ZennoBrowser открыт"),
    ("Zenno постер открыл", "Zennoposter открыл"),   # письменность — по первому слову
    ("Zenno Bowser открыл", "ZennoBrowser открыл"),  # одна часть точно, другая — с правкой
    ("Zeno Poster обновился", "Zennoposter обновился"),
    ("шаблон в Xeno", "шаблон в Zenno"),             # 4 звука — буква в букву
    ("сервер Proxy-pool упал", "сервер Proxypool упал"),
    ("в клод коде сессия", "в Claude Code сессия"),
    # другие прочтения латиницы
    ("через Тейлскейл", "через Tailscale"),
    ("ключ Энтропик", "ключ Anthropic"),
    ("почта на Вайлд Дак", "почта на WildDuck"),
    # имя собственное в начале фразы — для длинного термина
    ("Телеграм упал сегодня", "Telegram упал сегодня"),
    # окончание и частица через дефис/апостроф у исправленного слова сохраняются
    ("в Zenobowser'е баг", "в ZennoBrowser'е баг"),
    ("Xenoposter'ом займусь", "Zennoposter'ом займусь"),
    ("в Графане-то пусто", "в Grafana-то пусто"),
    # лишнее короткое слово рядом не поглощается
    ("Постгрес и Редис", "Postgres и Редис"),
])
def test_similar_spellings_become_the_term(src: str, out: str) -> None:
    assert fx(src) == out


@needs_lexicon
@pytest.mark.parametrize("src", [
    # настоящие слова, созвучные термину
    "Наведи курсор на кнопку.", "Выдели курсором всю функцию.", "Салат из редиса с яйцом.",
    "Бабушка получила телеграмму от внука.", "Центральный телеграф закрыли.",
    "Уровень сигнала низкий.", "Кафка писал по ночам.", "Питон проглотил кролика.",
    "Докер в порту.", "Загони тачку в гараж.", "Записаться через сайт госуслуг.",
    "Логи смотри в журнале.", "The nation is watching.", "We store backups in the cloud.",
    "Сенька пришёл", "купил графин воды", "повесь постер на стену", "открой браузер",
    "Звонил Зенько из бухгалтерии.",
    # обычные слова не склеиваются в термин
    "Купи редис и огурцы.", "Скинь прокси Максу, он просил.", "У графа Анна была дочерью.",
    "Рабочая зона браузера узкая.", "Ксения постер повесила", "Zen Browser хороший",
    "Яндекс Браузер обновился", "Let me get hub access", "Xena это сериал",
    # уже термины: с окончанием, внутри многословного термина, в другой письменности
    "Логи в Grafana Cloud, алерты в Telegram.", "Посмотри в Postgres'е таблицу.",
    "В Zennoposter-е обновили движок.", "Python-ом пишем", "Pay via Sberbank today.",
    "Zennoposter и ZennoBrowser уже верно", "шаблон Зеннопостера готов", "Поставь Zenno на сервер",
    # слово через дефис из настоящих частей, цифры
    "GUI из CC-консоли не поднимается", "версия Postgres16 и Grafana2", "по-русски говоря",
    # кириллица против кириллического термина — буква в букву; имена и фамилии
    "Ксенька написала.", "Созвонись с Ксенькой.", "Зинко прислал отчёт.",
    "Гриша Слаков звонил.",
    # несклоняемые термины и мужские окончания; «ь» на конце; au — «о», а не «ау»
    "Созвонись с Мирой.", "С Асаном работаем.", "Суперсеть объединяет подсети.",
    "Хранить бэкапы в клауде.", "Перенесли всё в Яндекс Клауд.",
    # раздельное написание из обычных слов; многословный термин с окончанием
    "The air flow is weak.", "в Grafana Cloud'е пусто",
    # короткая часть термина — только точно; частые имена; уменьшительные без «ь»
    "Поставил Зен браузер вместо хрома.", "В Зен браузере вкладки сбоку.",
    "Ксена браузер закрыла.", "Ксена постер нарисовала.", "Ксенка сказала, что придёт.",
    "Позвони Ксенке вечером.",
    # термин из двух слов: слово-термин + настоящее слово; дефис из обычных слов; тире
    "Попроси Claude код переписать.", "The air-flow is weak.",
    "Обновил Zenno – браузер пока не трогай.",
    # ударение и мягкий перенос внутри слова
    "Ксено́постер готов", "ксено­постер готов",
])
def test_no_false_replacements(src: str) -> None:
    assert fx(src) == src


@needs_lexicon
def test_two_real_words_need_a_variant() -> None:
    """Термин из двух настоящих слов («клик хаус») по звучанию не узнаётся — иначе «Зина
    браузер» стал бы ZennoBrowser; такому термину нужен вариант."""
    assert fx("в клик хаусе витрина") == "в клик хаусе витрина"
    items = [{"term": "ClickHouse", "variants": ["клик хаус"]}]
    assert fx("в клик хаусе витрина", items) == "в ClickHouse витрина"


def test_paths_addresses_and_files_untouched() -> None:
    items = terms("Grafana", "Zennoposter")
    for src in ("cd /opt/графана/x", "почта ксенопостер@mail.ru", "файл ксенопостер.ini",
                "C:\\Xenoposter\\bin"):
        assert fuzzy.find(src, items) == [], src


def test_punctuation_and_newline_split_fragments() -> None:
    assert fx("Xena, браузер") == "Xena, браузер"
    assert fx("Xena\nбраузер") == "Xena\nбраузер"


@needs_lexicon
def test_capitalization_at_sentence_start() -> None:
    items = terms("kubectl")
    assert fx("Кубектл упал", items) == "Kubectl упал"
    assert fx("запусти кубектл", items) == "запусти kubectl"


def test_exact_variants_come_first() -> None:
    """Точный вариант словаря важнее похожего написания другого термина."""
    items = [{"term": "ZennoBrowser", "variants": []},
             {"term": "ZennoDroid", "variants": ["Зенно браузер"]}]
    assert fx("открой Зенно браузер", items) == "открой ZennoDroid"


@needs_lexicon
def test_same_script_term_preferred() -> None:
    """Термин есть и латиницей, и кириллицей — берётся тот, что в письменности фрагмента;
    латиница кириллическим термином не заменяется."""
    assert fx("открой Ксенопостер") == "открой Зеннопостер"
    assert fx("открой Xenopostr") == "открой Zennoposter"
    assert fx("открой Xenopostr", terms("Зеннопостер")) == "открой Xenopostr"


@needs_lexicon
def test_disabled_is_exact_only() -> None:
    assert fuzzy.apply("открой Zenobowser", USER, fuzzy=False) == ("открой Zenobowser", 0)
    assert fuzzy.apply("открой Zenobowser", USER) == ("открой ZennoBrowser", 1)


def test_without_lexicon_only_exact(monkeypatch: pytest.MonkeyPatch) -> None:
    """Нет словарей Windows (или не ответили вовремя) — похожих написаний нет: без словаря
    языка «курсор» не отличить от искажения. Точные варианты работают."""
    monkeypatch.setattr(spell, "known_words", lambda words: {w: None for w in words})
    assert fx("открой Zenobowser и Xena браузер") == "открой Zenobowser и Xena браузер"
    assert fx("наведи курсор") == "наведи курсор"
    items = [{"term": "ZennoBrowser", "variants": ["Zenobowser"]}]
    assert fx("открой Zenobowser", items) == "открой ZennoBrowser"


@needs_lexicon
def test_users_own_words_are_real_words() -> None:
    """Слово, которое пользователь сам часто диктует, но которого нет в словаре Windows
    («ноды»), — обычная речь; своё частое искажение («кубернетис») так не защищается."""
    src = "Поменяй гео ноды на Германию."
    assert fuzzy.apply_text(src, USER) == "Поменяй GeoNode на Германию."
    mine = frozenset(vocab.group_key(w) for w in ("ноды", "кубернетис"))
    assert fuzzy.apply_text(src, USER, True, mine) == src
    assert fuzzy.apply_text("кубернетис упал", ALL, True, mine) == "Kubernetes упал"
    # через дефис — так же; своё слово, которое в точности часть термина, не мешает
    mine = frozenset(vocab.group_key(w) for w in ("ноды", "гео"))
    assert fuzzy.apply_text("Гео-нода отвалилась.", USER, True, mine) == "Гео-нода отвалилась."
    assert fuzzy.apply_text("в гео ноуте", USER, True, mine) == "в GeoNode"


def test_long_multiword_term_is_protected() -> None:
    items = terms("Proxypool", "Proxy Pool Admin Panel")
    assert fx("Открой Proxy Pool Admin Panel сейчас", items) ==         "Открой Proxy Pool Admin Panel сейчас"
    assert fx("сервер Proxy-pool упал", items) == "сервер Proxypool упал"


def test_empty_and_broken_input() -> None:
    assert fuzzy.apply("", USER) == ("", 0)
    assert fuzzy.apply("текст", []) == ("текст", 0)
    assert fuzzy.find("текст", [{"term": " "}, "мусор"]) == []  # type: ignore[list-item]


# ---------- ошибки распознавания для подсказок ----------

@needs_lexicon
def test_misrecognition_filter_fuzzy() -> None:
    bad = fuzzy.misrecognition_filter(ALL)
    assert bad is not None
    for w in ("Xenoposter", "Zenobowser", "Xenobowser", "GeoNote", "Ксенопостер", "кубернетис"):
        assert bad(w), w
    for w in ("Zennoposter", "ZennoBrowser", "Зеннопостер", "Kubernetes", "браузер", "Xena",
              "Cloud", "курсор", "телеграмма", "логи"):
        assert not bad(w), w
    exact = fuzzy.misrecognition_filter(USER, fuzzy=False)
    assert exact is not None and not exact("Xenoposter")      # без вариантов — только точно
    assert fuzzy.misrecognition_filter([]) is None


def test_speed_with_big_dictionary() -> None:
    items = [{"term": f"Termin{i}Name", "variants": [f"термин {i}"]} for i in range(500)]
    text = " ".join(["открой Zenobowser и проверь графану в клик хаусе"] * 40)
    fuzzy.apply(text, items)                  # индекс словаря строится один раз
    t = time.perf_counter()
    fuzzy.apply(text, items)
    assert time.perf_counter() - t < 0.5


# ---------- словарь языка ----------

@needs_lexicon
def test_spell_known_words() -> None:
    got = spell.known_words(["редис", "телеграмма", "графане", "Zenobowser", "nation",
                             "Xeno-браузер"])
    assert got == {"редис": True, "телеграмма": True, "графане": False, "Zenobowser": False,
                   "nation": True, "Xeno-браузер": False}
    assert spell.language_of("курсор") == spell.LANG_RU
    assert spell.language_of("cursor") == spell.LANG_EN
    assert spell.language_of("123") is None
    ok, summary = spell.selftest()
    assert ok and summary == "орфография: ok (ru да, en да)"


def test_spell_timeout_backs_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Проверка орфографии не ответила — одно ожидание, потом минуту её не ждём (None:
    fuzzy берёт частотные списки), и такие ответы fuzzy не запоминает."""
    import queue
    import types

    stuck = types.SimpleNamespace(jobs=queue.Queue(), broken=False, com=None)
    monkeypatch.setattr(spell, "_worker", stuck)
    monkeypatch.setattr(spell, "_cache", {})
    monkeypatch.setattr(spell, "_backoff_until", 0.0)
    monkeypatch.setattr(spell, "CALL_TIMEOUT_S", 0.05)
    t = time.perf_counter()
    assert spell.known_words(["редис"]) == {"редис": None}
    assert spell.known_words(["кубернетис"]) == {"кубернетис": None}
    assert time.perf_counter() - t < 1.0 and stuck.jobs.qsize() == 1   # второй раз не ждал
    assert not spell.ready()
