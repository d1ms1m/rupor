"""Бенчмарк распознавания: 20 фраз → синтез голосом SAPI Irina → rupor.asr → WER и время.

    .venv\\Scripts\\python tools/wer_bench.py [--resynth] [--repeat 1] [--only ID]
    .venv\\Scripts\\python tools/wer_bench.py --compare [--context] [--repeat 1]

Фразы — tools/data/asr_refs.json (поле tts произносится, ref — эталон). Wav 16 кГц моно
кладутся в samples/asr/ (папка в .gitignore) и переиспользуются. Распознавание —
rupor.asr.Recognizer с настройками по умолчанию (large-v3-turbo, CUDA float16, beam 5,
подсказка-термины). Время меряется так же, как в движке: язык определяется заранее по
первым 2,5 с (движок делает это ещё во время записи), после «отпускания» остаётся только
transcribe; отдельно — полное время transcribe с определением языка.

``--compare`` — замер личного словаря частот (rupor.vocab): каждая фраза распознаётся
дважды — с прежней подсказкой (термины настроек) и с подсказкой, как её собирает движок
(vocab.build_prompt: термины + частые слова процесса + общие частые), где частые слова взяты
из ИСКУССТВЕННОЙ истории во временной базе (термины фраз в других предложениях, доменные
слова и «шум» — посторонние термины и имена). Длина подсказки считается токенизатором
модели, как в движке (``Recognizer.token_counter``).

``--context`` (вместе с ``--compare``) — третий прогон «после + контекст»: к подсказке
добавляется контекст окна максимальной длины (CONTEXT_MAX — длинный рабочий текст перед
курсором, ≥ 300 символов; vocab.build_prompt срезает его до CONTEXT_TOKENS токенов).
Проверяет, что подсказка не выходит за 223 токена (faster-whisper молча срезал бы её
начало) и как длинный контекст влияет на WER и галлюцинации.
Отчёт JSON — samples/asr/wer_report_<время>.json.
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "tools"))

from ai_bench import p90, pct, wer_counts  # noqa: E402  (нормализация общая с ai_bench)

REFS = ROOT / "tools" / "data" / "asr_refs.json"
OUT = ROOT / "samples" / "asr"
EARLY_LANG_S = 2.5
HISTORY_APP = "notepad.exe"

SAFT16kHz16BitMono = 18
SSFMCreateForWrite = 3

# Искусственная история: термины фраз — в ДРУГИХ предложениях (не в самих фразах бенчмарка),
# доменные слова (редкие строчные) и шум — посторонние термины и имена, как у живого человека.
HISTORY_TEMPLATES = (
    "Обсудили {t} на созвоне, вопросов больше нет.",
    "Вчера вечером {t} опять тормозил, посмотрю завтра.",
    "Скинь, пожалуйста, ссылку на {t} в общий чат.",
)
DOMAIN_SENTENCES = (
    "Обнови дашборд и витрину по мерчантам до обеда.",
    "Дашборд по мерчантам уже готов, осталось проверить витрину.",
    "Алерт по мерчантам снова сработал ночью, дашборд красный.",
    "Сделай рефакторинг выгрузки и проверь дашборд.",
)
# Контекст окна максимальной длины: рабочая переписка перед курсором (1–2 предложения,
# длиннее CONTEXT_CHARS — движок оставит хвост ≤ 300 символов и ≤ CONTEXT_TOKENS токенов)
CONTEXT_MAX = (
    "Коллеги, по итогам вчерашнего созвона: мерчанты жалуются на задержки выплат, витрина "
    "комиссий пересчитывается раз в сутки, а дашборд показывает вчерашние цифры, поэтому "
    "поддержка отвечает клиентам наугад. Предлагаю перенести пересчёт ближе к источнику, "
    "настроить алерты на задержку и отдельно проверить выгрузку, которую Наташа смотрела "
    "в пятницу вечером, а пока напишу вам коротко, что именно я предлагаю сделать первым"
)
NOISE_SENTENCES = (
    "Наташа просила выгрузку из Airflow к пятнице.",
    "Тимур обещал поднять Superset на тестовом стенде.",
    "Кирилл смотрел логи Nginx, там всё чисто, Наташа в курсе.",
    "Перенеси встречу с Тимуром, Airflow подождёт.",
)


def synthesize(items: list[dict[str, Any]], force: bool) -> None:
    """Синтез голосом Irina через SAPI (как tools/make_sample.py). Окна не открываются."""
    todo = [it for it in items if force or not (OUT / f"{it['id']}.wav").exists()]
    if not todo:
        return
    import comtypes.client

    voice = comtypes.client.CreateObject("SAPI.SpVoice")
    irina = None
    for tok in voice.GetVoices():
        if "Irina" in tok.GetDescription():
            irina = tok
            break
    if irina is None:
        raise SystemExit("Голос SAPI Irina не найден — установите русский голос Windows")
    voice.Voice = irina
    for it in todo:
        path = OUT / f"{it['id']}.wav"
        stream = comtypes.client.CreateObject("SAPI.SpFileStream")
        fmt = comtypes.client.CreateObject("SAPI.SpAudioFormat")
        fmt.Type = SAFT16kHz16BitMono
        stream.Format = fmt
        stream.Open(str(path), SSFMCreateForWrite)
        voice.AudioOutputStream = stream
        voice.Speak(it["tts"])
        stream.Close()
        print(f"синтез: {path.name}")


def term_hits(hyp: str, terms: list[str]) -> tuple[int, list[str]]:
    miss = [t for t in terms if t.lower() not in hyp.lower()]
    return len(terms) - len(miss), miss


def vocab_prompt(items: list[dict[str, Any]], terms: list[str], context: str | None = None,
                 counter: Callable[[str], int] | None = None) -> tuple[str | None, list[str]]:
    """Подсказка движка с частыми словами из искусственной истории (временная база) и,
    если задан, контекстом окна."""
    from rupor import storage, vocab

    all_terms: list[str] = []
    for it in items:
        for t in it.get("terms", []):
            if t not in all_terms:
                all_terms.append(t)
    with tempfile.TemporaryDirectory(prefix="rupor-wer-") as tmp:
        st = storage.Storage(Path(tmp) / "rupor.db")
        try:
            texts = [tpl.format(t=t) for t in all_terms for tpl in HISTORY_TEMPLATES]
            texts += list(DOMAIN_SENTENCES) + list(NOISE_SENTENCES)
            for i, text in enumerate(texts):
                st.add_history({"ts": time.time() - 3600 + i, "app": HISTORY_APP, "title": "",
                                "raw": text, "text": text, "target": "window"})
            proc, gen = st.vocab_prompt_words(HISTORY_APP)
        finally:
            st.close()
    return vocab.build_prompt(context, terms, proc, gen, count_tokens=counter), proc + gen


def run(rec: Any, items: list[dict[str, Any]], repeat: int, label: str) -> list[dict[str, Any]]:
    from rupor import asr

    rows: list[dict[str, Any]] = []
    for it in items:
        audio = asr.load_wav(str(OUT / f"{it['id']}.wav"))
        dur = len(audio) / asr.SAMPLE_RATE
        after_ms: list[float] = []
        full_ms: list[float] = []
        text = ""
        lang = "ru"
        for _ in range(max(1, repeat)):
            head = audio[: int(EARLY_LANG_S * asr.SAMPLE_RATE)]
            lang = rec.detect_language(head)  # в движке — во время записи
            r = rec.transcribe(audio, language=lang)
            after_ms.append(r.elapsed_ms)
            text = r.text
            r2 = rec.transcribe(audio)  # с определением языка внутри
            full_ms.append(r2.elapsed_ms)
        e, n = wer_counts(it["ref"], text)
        hits, miss = term_hits(text, it.get("terms", []))
        row = {
            "id": it["id"], "audio_s": round(dur, 2), "lang": lang,
            "asr_ms": statistics.median(after_ms), "asr_full_ms": statistics.median(full_ms),
            "errors": e, "ref_words": n, "wer": e / max(1, n),
            "terms": len(it.get("terms", [])), "term_hits": hits, "term_miss": miss,
            "ref": it["ref"], "hyp": text,
        }
        rows.append(row)
        warn = "" if 5.0 <= dur <= 15.0 else "  (!) длительность вне 5–15 с"
        print(f"[{label}] [{it['id']}] {dur:.1f} с → {row['asr_ms']:.0f} мс "
              f"(полное {row['asr_full_ms']:.0f}), WER {pct(row['wer'])}, "
              f"термины {hits}/{row['terms']}" + (f" нет {miss}" if miss else "") + warn)
        print(f"   {text}")
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ms = [r["asr_ms"] for r in rows]
    full = [r["asr_full_ms"] for r in rows]
    durs = [r["audio_s"] for r in rows]
    tot_e = sum(r["errors"] for r in rows)
    tot_n = sum(r["ref_words"] for r in rows)
    return {
        "phrases": len(rows), "audio_s_total": round(sum(durs), 1),
        "audio_s_min": min(durs), "audio_s_max": max(durs),
        "wer_total": tot_e / max(1, tot_n), "wer_mean": statistics.mean(r["wer"] for r in rows),
        "wer_median": statistics.median(r["wer"] for r in rows),
        "exact": sum(1 for r in rows if r["errors"] == 0),
        "terms_hit": sum(r["term_hits"] for r in rows),
        "terms_total": sum(r["terms"] for r in rows),
        "asr_ms_median": statistics.median(ms), "asr_ms_p90": p90(ms), "asr_ms_max": max(ms),
        "asr_full_ms_median": statistics.median(full), "asr_full_ms_p90": p90(full),
        "rtf_median": statistics.median(r["asr_ms"] / 1000 / r["audio_s"] for r in rows),
    }


def print_summary(summary: dict[str, Any], dev: str) -> None:
    print("| Метрика | Значение |\n|---|---|")
    print(f"| Фраз / аудио всего | {summary['phrases']} / {summary['audio_s_total']} с "
          f"({summary['audio_s_min']:.1f}–{summary['audio_s_max']:.1f} с) |")
    print(f"| WER по всем словам | {pct(summary['wer_total'])} |")
    print(f"| WER средний / медиана по фразам | {pct(summary['wer_mean'])} / "
          f"{pct(summary['wer_median'])} |")
    print(f"| Фраз без единой ошибки | {summary['exact']} из {summary['phrases']} |")
    print(f"| Английские термины написаны канонически | {summary['terms_hit']} из "
          f"{summary['terms_total']} |")
    print(f"| ASR после отпускания: медиана / p90 / макс | {summary['asr_ms_median']:.0f} / "
          f"{summary['asr_ms_p90']:.0f} / {summary['asr_ms_max']:.0f} мс |")
    print(f"| ASR с определением языка: медиана / p90 | {summary['asr_full_ms_median']:.0f} / "
          f"{summary['asr_full_ms_p90']:.0f} мс |")
    print(f"| RTF (медиана) | {summary['rtf_median']:.3f} |")
    print(f"| Устройство | {dev} |")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--resynth", action="store_true", help="пересинтезировать wav")
    ap.add_argument("--repeat", type=int, default=1, help="прогонов на фразу (берётся медиана)")
    ap.add_argument("--only", default="", help="id фраз через запятую")
    ap.add_argument("--extra-terms", default="",
                    help="доп. термины подсказки через запятую (как словарь пользователя)")
    ap.add_argument("--compare", action="store_true",
                    help="до/после: прежняя подсказка против подсказки с частыми словами "
                         "из искусственной истории")
    ap.add_argument("--context", action="store_true",
                    help="с --compare: ещё прогон с контекстом окна максимальной длины")
    a = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)

    items: list[dict[str, Any]] = json.loads(REFS.read_text(encoding="utf-8"))["phrases"]
    if a.only:
        ids = set(a.only.split(","))
        items = [it for it in items if it["id"] in ids]
    OUT.mkdir(parents=True, exist_ok=True)
    synthesize(items, a.resynth)

    from rupor import asr, config, vocab

    s = config.Settings()
    extra = [t.strip() for t in a.extra_terms.split(",") if t.strip()]
    if extra:
        s.terms = list(s.terms) + extra
        print("Подсказка распознавания: " + ", ".join(s.terms))
    rec = asr.Recognizer(s, on_notice=lambda m, _lvl: print("!", m))
    t0 = time.perf_counter()
    rec.load()
    load_s = time.perf_counter() - t0
    gpu = ""
    try:
        import ctranslate2
        gpu = f", CUDA-устройств: {ctranslate2.get_cuda_device_count()}"
    except Exception:
        pass
    dev = f"{rec.device}, {s.model}, {s.compute_type}, beam {s.beam_size}"
    print(f"Модель {s.model} на {rec.device} ({s.compute_type}, beam {s.beam_size}) "
          f"загружена за {load_s:.1f} с{gpu}\n")

    counter = rec.token_counter()          # как в движке: длина подсказки в токенах модели

    def tokens(prompt: str | None) -> int:
        if not prompt:
            return 0
        return counter(prompt) if counter is not None else vocab.estimate_tokens(prompt)

    base_prompt = vocab.build_prompt(None, list(s.terms), count_tokens=counter)
    runs: list[tuple[str, str | None, Callable[[], str | None]]] = [
        ("до", base_prompt, lambda: base_prompt)]
    vocab_words: list[str] = []
    if a.compare:
        after_prompt, vocab_words = vocab_prompt(items, list(s.terms), None, counter)
        runs.append(("после", after_prompt, lambda: after_prompt))
        print(f"Частые слова из искусственной истории ({len(vocab_words)}): "
              + ", ".join(vocab_words))
        if a.context:
            ctx_prompt, _ = vocab_prompt(items, list(s.terms), CONTEXT_MAX, counter)
            runs.append(("после + контекст", ctx_prompt, lambda: ctx_prompt))
    report: dict[str, Any] = {"date": time.strftime("%Y-%m-%d %H:%M"),
                              "normalize": "нижний регистр, ё→е, без пунктуации и дефисов",
                              "runs": {}}
    summaries: dict[str, dict[str, Any]] = {}
    for label, prompt, provider in runs:
        n_tok = tokens(prompt)
        print(f"\n### Прогон «{label}»: подсказка {len(prompt or '')} симв., {n_tok} токенов"
              f"{' (!) больше 223 — начало срезается' if n_tok > 223 else ''} — {prompt}\n")
        rec.prompt_provider = provider
        rows = run(rec, items, a.repeat, label)
        summary = summarize(rows)
        summary.update({"device": rec.device, "model": s.model, "compute_type": s.compute_type,
                        "beam_size": s.beam_size, "load_s": round(load_s, 2),
                        "terms": list(s.terms), "prompt": prompt, "prompt_tokens": n_tok})
        summaries[label] = summary
        report["runs"][label] = {"summary": summary, "rows": rows}
        print(f"\n## Итог распознавания — «{label}»")
        print_summary(summary, dev)
    if a.compare:
        b, v = summaries["до"], summaries["после"]
        pairs = list(zip(report["runs"]["до"]["rows"], report["runs"]["после"]["rows"]))
        better = [r2["id"] for r1, r2 in pairs if r2["errors"] < r1["errors"]]
        worse = [r2["id"] for r1, r2 in pairs if r2["errors"] > r1["errors"]]
        print("\n## До / после (личный словарь частот)")
        print("| Метрика | До | После |\n|---|---|---|")
        print(f"| WER по всем словам | {pct(b['wer_total'])} | {pct(v['wer_total'])} |")
        print(f"| WER средний по фразам | {pct(b['wer_mean'])} | {pct(v['wer_mean'])} |")
        print(f"| Фраз без ошибок | {b['exact']} | {v['exact']} |")
        print(f"| Термины канонически | {b['terms_hit']}/{b['terms_total']} | "
              f"{v['terms_hit']}/{v['terms_total']} |")
        print(f"| ASR медиана | {b['asr_ms_median']:.0f} мс | {v['asr_ms_median']:.0f} мс |")
        print(f"| Подсказка, токенов | {b['prompt_tokens']} | {v['prompt_tokens']} |")
        print(f"\nЛучше: {', '.join(better) or '—'}; хуже: {', '.join(worse) or '—'}")
        report.update(vocab_words=vocab_words, better=better, worse=worse)
        if "после + контекст" in summaries:
            x = summaries["после + контекст"]
            rows_x = report["runs"]["после + контекст"]["rows"]
            worse_x = [r2["id"] for r1, r2 in zip(report["runs"]["до"]["rows"], rows_x)
                       if r2["errors"] > r1["errors"]]
            print("\n## С контекстом окна максимальной длины")
            print(f"| WER по всем словам | {pct(x['wer_total'])} |")
            print(f"| WER средний по фразам | {pct(x['wer_mean'])} |")
            print(f"| Фраз без ошибок | {x['exact']} |")
            print(f"| Термины канонически | {x['terms_hit']}/{x['terms_total']} |")
            print(f"| ASR медиана | {x['asr_ms_median']:.0f} мс |")
            print(f"| Подсказка, токенов | {x['prompt_tokens']} (предел faster-whisper 223) |")
            print(f"\nХуже, чем «до»: {', '.join(worse_x) or '—'}")
            report.update(context_worse=worse_x)
    rep = OUT / f"wer_report_{time.strftime('%Y%m%d_%H%M%S')}.json"
    rep.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nОтчёт: {rep}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
