"""Синтез тестовой русской фразы голосом SAPI Irina → wav 16 кГц моно.

python tools/make_sample.py out.wav "текст"
"""
from __future__ import annotations

import sys

import comtypes.client  # type: ignore[import-untyped]

SAFT16kHz16BitMono = 18
SSFMCreateForWrite = 3

out = sys.argv[1]
text = sys.argv[2] if len(sys.argv) > 2 else (
    "Надо завтра в ClickHouse пересобрать витрину по комиссиям мерчантов, "
    "а потом в Metabase обновить дашборд. Созвонимся в одиннадцать и проверим план-факт."
)
voice = comtypes.client.CreateObject("SAPI.SpVoice")
for tok in voice.GetVoices():
    if "Irina" in tok.GetDescription():
        voice.Voice = tok
        break
stream = comtypes.client.CreateObject("SAPI.SpFileStream")
fmt = comtypes.client.CreateObject("SAPI.SpAudioFormat")
fmt.Type = SAFT16kHz16BitMono
stream.Format = fmt
stream.Open(out, SSFMCreateForWrite)
voice.AudioOutputStream = stream
voice.Speak(text)
stream.Close()
print("записано:", out)
