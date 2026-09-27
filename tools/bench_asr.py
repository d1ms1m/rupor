"""Замер распознавания: python tools/bench_asr.py file.wav [повторов]"""
from __future__ import annotations

import logging
import sys

sys.path.insert(0, "core")
from rupor import asr, config  # noqa: E402

logging.basicConfig(level=logging.INFO)
s = config.Settings()
r = asr.Recognizer(s, on_notice=print)
r.load()
audio = asr.load_wav(sys.argv[1])
n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
for _ in range(n):
    res = r.transcribe(audio)
    print(f"{res.audio_s:.1f} с → {res.elapsed_ms:.0f} мс [{res.language}] на {r.device}: {res.text}")
