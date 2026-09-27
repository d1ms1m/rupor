"""Разбивка задержки ASR по этапам."""
from __future__ import annotations

import sys
import time

sys.path.insert(0, "core")
from rupor import asr, config  # noqa: E402

s = config.Settings()
r = asr.Recognizer(s)
r.load()
m = r._model
a = asr.load_wav(sys.argv[1])


def t(label: str, fn):  # type: ignore[no-untyped-def]
    best = 1e9
    for _ in range(3):
        t0 = time.perf_counter()
        out = fn()
        best = min(best, (time.perf_counter() - t0) * 1000)
    print(f"{label:40s} {best:6.0f} мс")
    return out


t("detect_language", lambda: m.detect_language(a))
t("transcribe ru, vad", lambda: list(m.transcribe(a, language="ru", beam_size=1, vad_filter=True,
                                                   without_timestamps=True)[0]))
t("transcribe ru, без vad", lambda: list(m.transcribe(a, language="ru", beam_size=1,
                                                       without_timestamps=True)[0]))
t("transcribe auto-lang, vad", lambda: list(m.transcribe(a, beam_size=1, vad_filter=True,
                                                          without_timestamps=True)[0]))
t("transcribe ru, vad, beam 5", lambda: list(m.transcribe(a, language="ru", beam_size=5,
                                                           vad_filter=True, without_timestamps=True)[0]))
kw = dict(language="ru", vad_filter=True, without_timestamps=True, condition_on_previous_text=False)
pr = "ClickHouse, Metabase, Python, API, SQL, RDP, GitHub, Grafana."
t("beam5 + prompt", lambda: list(m.transcribe(a, beam_size=5, initial_prompt=pr, **kw)[0]))
t("beam1 + prompt", lambda: list(m.transcribe(a, beam_size=1, initial_prompt=pr, **kw)[0]))
t("beam5 без prompt", lambda: list(m.transcribe(a, beam_size=5, **kw)[0]))
t("beam5 + hotwords", lambda: list(m.transcribe(a, beam_size=5, hotwords=pr, **kw)[0]))
