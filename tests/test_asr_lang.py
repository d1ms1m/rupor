"""Язык распознавания и подсказка initial_prompt (rupor.asr) — без модели и GPU:
модель faster-whisper подменяется заглушкой."""
from types import SimpleNamespace
from typing import Any, Iterator

import numpy as np
import pytest

from rupor import asr, i18n


@pytest.fixture(autouse=True)
def windows_ru(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Язык Windows — русский (для language=system), глобальный язык i18n — как был."""
    monkeypatch.setattr(i18n, "system_language", lambda: "ru")
    prev = i18n.setting()
    yield
    i18n.set_language(prev)


def cfg(**kw: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "model": "large-v3-turbo", "device": "cpu", "compute_type": "int8", "beam_size": 5,
        "en_threshold": 0.8, "terms": ["ClickHouse", "Metabase"],
        "language": "system", "dictation_language": "auto",
    }
    base.update(kw)
    return SimpleNamespace(**base)


# ---------- выбор языка ----------

@pytest.mark.parametrize("ui,detected,prob,expected", [
    # русский интерфейс: английский — только при уверенности ≥ порога
    ("ru", "en", 0.95, "en"),
    ("ru", "en", 0.8, "en"),
    ("ru", "en", 0.79, "ru"),
    ("ru", "ru", 0.99, "ru"),
    ("ru", "uk", 0.99, "ru"),
    ("ru", None, 0.0, "ru"),
    # английский интерфейс — зеркально: русский только при уверенности
    ("en", "ru", 0.95, "ru"),
    ("en", "ru", 0.5, "en"),
    ("en", "en", 0.3, "en"),
    ("en", "uk", 0.99, "en"),
    ("en", "de", 0.99, "en"),
])
def test_auto_prefers_ui_language(ui: str, detected: str | None, prob: float,
                                  expected: str) -> None:
    assert asr.choose_language(cfg(language=ui), detected, prob) == expected


@pytest.mark.parametrize("mode", ["ru", "en"])
@pytest.mark.parametrize("detected,prob", [("ru", 0.99), ("en", 0.99), ("de", 0.9)])
def test_fixed_dictation_language(mode: str, detected: str, prob: float) -> None:
    for ui in ("ru", "en", "system"):
        s = cfg(language=ui, dictation_language=mode)
        assert asr.choose_language(s, detected, prob) == mode


def test_threshold_setting_is_used() -> None:
    assert asr.choose_language(cfg(en_threshold=0.5), "en", 0.6) == "en"
    assert asr.choose_language(cfg(language="en", en_threshold=0.95), "ru", 0.9) == "en"


def test_system_language_and_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    assert asr.primary_language(cfg(language="system")) == "ru"
    monkeypatch.setattr(i18n, "system_language", lambda: "en")
    assert asr.primary_language(cfg(language="system")) == "en"
    assert asr.primary_language(cfg(language="ru")) == "ru"
    # старые настройки без полей language/dictation_language
    bare = SimpleNamespace(en_threshold=0.8)
    i18n.set_language("ru")
    assert asr.primary_language(bare) == "ru"
    assert asr.dictation_mode(bare) == "auto"
    assert asr.choose_language(bare, "en", 0.9) == "en"
    assert asr.choose_language(bare, "en", 0.7) == "ru"
    i18n.set_language("en")
    assert asr.choose_language(bare, "ru", 0.7) == "en"
    assert asr.dictation_mode(cfg(dictation_language="fr")) == "auto"


# ---------- подсказка ----------

@pytest.mark.parametrize("prompt,lang,expected", [
    (None, "en", None),
    ("", "en", ""),
    # русская диктовка — подсказка как есть
    ("Надо проверить витрину. ClickHouse, Тимур, Metabase.", "ru",
     "Надо проверить витрину. ClickHouse, Тимур, Metabase."),
    # латиница — как есть
    ("Let me check the build. ClickHouse, Metabase.", "en",
     "Let me check the build. ClickHouse, Metabase."),
    # русский контекст и русские слова уходят, латинские термины — в том же порядке
    ("Надо проверить витрину в ClickHouse-запросе. ClickHouse, Тимур, Metabase, Redis.", "en",
     "ClickHouse, Metabase, Redis."),
    ("Привет, как дела? Let me check the build. Kubernetes, Иван, GPT-4o, C++, Node.js.", "en",
     "Let me check the build. Kubernetes, GPT-4o, C++, Node.js."),
    ("Metabase'е и в Grafana смотри. Postgres.", "en", "Metabase, Grafana, Postgres."),
    ("Тимур, Иван, СДЭК.", "en", None),
])
def test_adapt_prompt(prompt: str | None, lang: str, expected: str | None) -> None:
    out = asr.adapt_prompt(prompt, lang)
    assert out == expected
    if lang == "en" and out:
        assert not asr._CYR_RE.search(out)


# ---------- Recognizer с заглушкой модели ----------

class FakeModel:
    def __init__(self, lang: str = "en", prob: float = 0.9) -> None:
        self.lang, self.prob = lang, prob
        self.detect_calls = 0
        self.transcribe_calls: list[dict[str, Any]] = []

    def detect_language(self, audio: np.ndarray) -> tuple[str, float, list[Any]]:
        self.detect_calls += 1
        return self.lang, self.prob, []

    def transcribe(self, audio: np.ndarray, **kw: Any) -> tuple[list[Any], Any]:
        self.transcribe_calls.append(kw)
        return [SimpleNamespace(text=" Hello there. ")], None


def make_rec(s: SimpleNamespace, model: FakeModel,
             prompt: str | None = None) -> asr.Recognizer:
    rec = asr.Recognizer(s)  # type: ignore[arg-type]
    rec._model = model              # load() видит загруженную модель и ничего не грузит
    rec.device = "cpu"
    if prompt is not None:
        rec.prompt_provider = lambda: prompt
    return rec


AUDIO = np.zeros(16000, dtype=np.float32)
PROMPT = "Надо проверить витрину. ClickHouse, Тимур, Metabase."


def test_fixed_language_skips_detection() -> None:
    m = FakeModel("ru", 0.99)
    rec = make_rec(cfg(dictation_language="en"), m)
    assert rec.detect_language(AUDIO) == "en"
    res = rec.transcribe(AUDIO)
    assert res.language == "en" and m.detect_calls == 0
    assert m.transcribe_calls[0]["language"] == "en"


def test_fixed_language_does_not_load_model_early() -> None:
    rec = asr.Recognizer(cfg(dictation_language="ru"))  # type: ignore[arg-type]
    assert rec.detect_language(AUDIO) == "ru"            # модели нет — и не нужна
    assert not rec.loaded


@pytest.mark.parametrize("ui,lang,prob,expected", [
    ("ru", "en", 0.9, "en"), ("ru", "en", 0.6, "ru"),
    ("en", "ru", 0.9, "ru"), ("en", "ru", 0.6, "en"),
])
def test_auto_detection_through_recognizer(ui: str, lang: str, prob: float,
                                           expected: str) -> None:
    m = FakeModel(lang, prob)
    rec = make_rec(cfg(language=ui), m)
    assert rec.detect_language(AUDIO) == expected
    assert rec.transcribe(AUDIO).language == expected
    assert m.detect_calls == 2


def test_detection_failure_falls_back_to_ui_language() -> None:
    class Broken(FakeModel):
        def detect_language(self, audio: np.ndarray) -> tuple[str, float, list[Any]]:
            raise RuntimeError("boom")
    assert make_rec(cfg(language="en"), Broken()).detect_language(AUDIO) == "en"
    assert make_rec(cfg(language="ru"), Broken()).detect_language(AUDIO) == "ru"


def test_english_dictation_gets_latin_prompt() -> None:
    m = FakeModel("en", 0.99)
    rec = make_rec(cfg(), m, PROMPT)
    res = rec.transcribe(AUDIO)
    assert res.language == "en" and res.text == "Hello there."
    assert m.transcribe_calls[0]["initial_prompt"] == "ClickHouse, Metabase."


def test_russian_dictation_keeps_prompt() -> None:
    m = FakeModel("ru", 0.99)
    rec = make_rec(cfg(), m, PROMPT)
    rec.transcribe(AUDIO)
    assert m.transcribe_calls[0]["initial_prompt"] == PROMPT
    # язык, определённый заранее (движок), тоже решает, какой будет подсказка
    rec.transcribe(AUDIO, language="en")
    assert m.transcribe_calls[1]["initial_prompt"] == "ClickHouse, Metabase."
    assert m.transcribe_calls[1]["language"] == "en"


def test_default_prompt_is_adapted_too() -> None:
    m = FakeModel("en", 0.99)
    rec = make_rec(cfg(terms=["ClickHouse", "СДЭК", "Grafana"]), m)
    rec.transcribe(AUDIO)
    assert m.transcribe_calls[0]["initial_prompt"] == "ClickHouse, Grafana."
