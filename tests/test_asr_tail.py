"""Служебное окончание — повод проверить звук, а не удалить слова по списку."""
import numpy as np
import pytest
import threading

from rupor import asr

FIRST = "Проверь тесты. Спасибо за просмотр."


def test_transcribe_preserves_first_decode_and_uses_only_two_passes() -> None:
    rec = asr.Recognizer.__new__(asr.Recognizer)
    rec.load = lambda: None
    rec._lock = threading.Lock()
    rec._model = object()
    rec.prompt_provider = lambda: "Проверь тесты."
    calls = []

    def decode(audio, lang, prompt, guess):
        calls.append((prompt, guess))
        return (FIRST if len(calls) == 1 else "Проверь тесты."), [(0.0, -0.2)]

    rec._decode = decode
    result = rec._transcribe(np.zeros(16000), "ru")
    assert result.text == "Проверь тесты."
    assert result.original_text == FIRST
    assert calls == [("Проверь тесты.", True), (None, False)]


@pytest.mark.parametrize("second, expected", [
    ("Проверь тесты.", "Проверь тесты."),
    (FIRST, FIRST),
    ("Измени настройки.", FIRST),
    ("", FIRST),
    ("Проверь тесты. Продолжение следует.", FIRST),
])
def test_tail_retry_is_conservative(second: str, expected: str) -> None:
    rec = asr.Recognizer.__new__(asr.Recognizer)
    calls = []

    def decode(audio, lang, prompt, guess):
        calls.append((prompt, guess))
        return second, [(0.0, -0.2)]

    rec._decode = decode
    assert rec._second_opinion(np.zeros(16000), "ru", FIRST, [(0.0, -0.2)]) == expected
    assert calls == [(None, False)]


def test_tail_retry_failure_preserves_original() -> None:
    rec = asr.Recognizer.__new__(asr.Recognizer)

    def fail(*args, **kwargs):
        raise RuntimeError("decoder failed")

    rec._decode = fail
    assert rec._second_opinion(np.zeros(16000), "ru", FIRST, [(0.0, -0.2)]) == FIRST


def test_clean_unprompted_pass_is_not_repeated() -> None:
    rec = asr.Recognizer.__new__(asr.Recognizer)
    rec._decode = lambda *a, **kw: pytest.fail("redundant decode")
    assert rec._second_opinion(np.zeros(16000), "ru", FIRST, [(0.0, -0.2)],
                               had_prompt=False) == FIRST


@pytest.mark.parametrize("text", ["Скажи спасибо за просмотр",
    "Спасибо за просмотр. Затем проверь тесты.", "Проверь тесты."])
def test_ordinary_text_does_not_trigger_retry(text: str) -> None:
    rec = asr.Recognizer.__new__(asr.Recognizer)
    rec._decode = lambda *a, **kw: pytest.fail("unnecessary decode")
    assert rec._second_opinion(np.zeros(16000), "ru", text, [(0.0, -0.2)]) == text


def test_tail_and_existing_signal_share_one_retry() -> None:
    rec = asr.Recognizer.__new__(asr.Recognizer)
    calls = []

    def decode(*args, **kwargs):
        calls.append(1)
        return FIRST, [(0.0, -0.2)]

    rec._decode = decode
    assert rec._second_opinion(np.zeros(16000), "ru", FIRST, [(0.8, -0.2)]) == FIRST
    assert len(calls) == 1


def test_unconfident_tail_retry_is_not_used() -> None:
    rec = asr.Recognizer.__new__(asr.Recognizer)
    rec._decode = lambda *a, **kw: ("Проверь тесты.", [(0.0, -2.0)])
    assert rec._second_opinion(np.zeros(16000), "ru", FIRST, [(0.0, -0.2)]) == FIRST
