"""Подбор модели распознавания под мощность компьютера — мастер первого запуска
(команда ``model_recommend``).

Правила (``choose``):
- видеокарта NVIDIA (её видит CUDA или хотя бы драйвер: при первом запуске cuBLAS ещё не
  скачан, а карта уже есть): видеопамяти от 4 ГБ — large-v3-turbo, cuda, float16;
  2–4 ГБ — large-v3-turbo, cuda, int8_float16 (≈1,5 ГБ видеопамяти); меньше — small, cuda,
  int8_float16; объём не определился — как 2–4 ГБ;
- без видеокарты NVIDIA: от 8 потоков процессора и от 8 ГБ памяти — small, cpu, int8,
  иначе base, cpu, int8 (объём памяти не определился — решают одни потоки).
Пороги — с допуском: 4-гигабайтную карту NVML может показать чуть меньше 4096 МБ, а у
компьютера с 8 ГБ Windows видит чуть меньше 8 ГБ (часть берёт встроенная графика).

Варианты на выбор — tiny … large-v3 (distil-* не предлагаются: они только английские).
Размер — точный, по данным Hugging Face (``fetch.model_sizes``, все запросы вместе не дольше
``SIZE_BUDGET_S``), без сети — из таблицы ``FALLBACK_MB``. ``size_mb`` — мегабайты по 10⁶ байт,
как на сайте Hugging Face.
"""
from __future__ import annotations

import ctypes
import logging
import os
from dataclasses import dataclass
from typing import Any

from . import fetch, i18n
from .i18n import tp, tr

log = logging.getLogger(__name__)

SIZE_BUDGET_S = 4.0       # сколько ждать размеры моделей с Hugging Face (все сразу)
VRAM_FULL_MB = 3800       # «от 4 ГБ видеопамяти» (с допуском)
VRAM_INT8_MB = 1900       # «от 2 ГБ видеопамяти» (с допуском)
RAM_SMALL_GB = 7.5        # «от 8 ГБ памяти» (с допуском)
THREADS_SMALL = 8

MODELS: tuple[str, ...] = ("tiny", "base", "small", "medium", "large-v3-turbo", "large-v3")
# Запасные размеры файлов моделей (МБ по 10⁶ байт), если Hugging Face не ответил
FALLBACK_MB: dict[str, int] = {"tiny": 75, "base": 145, "small": 484, "medium": 1530,
                               "large-v3-turbo": 1620, "large-v3": 3090}
# (качество распознавания русского, скорость) — от 1 до 5
SCORES: dict[str, tuple[int, int]] = {"tiny": (1, 5), "base": (2, 5), "small": (3, 4),
                                      "medium": (4, 2), "large-v3-turbo": (5, 3),
                                      "large-v3": (5, 1)}
NOTE_KEYS: dict[str, str] = {"tiny": "rec.note_tiny", "base": "rec.note_base",
                             "small": "rec.note_small", "medium": "rec.note_medium",
                             "large-v3-turbo": "rec.note_turbo", "large-v3": "rec.note_large"}


@dataclass(frozen=True)
class Hardware:
    gpu_name: str | None      # первая видеокарта NVIDIA (NVML), None — не нашлась
    vram_mb: int | None       # её видеопамять, None — не определилась
    cuda_devices: int         # сколько устройств видит CUDA (CTranslate2)
    ram_gb: float             # оперативная память, ГБ; 0 — не определилась
    cpu_threads: int

    @property
    def cuda_ok(self) -> bool:
        return self.cuda_devices > 0

    @property
    def has_gpu(self) -> bool:
        return self.cuda_ok or self.gpu_name is not None


@dataclass(frozen=True)
class Choice:
    model: str
    device: str
    compute_type: str
    reason: str               # на языке интерфейса


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def ram_gb() -> float:
    """Оперативная память компьютера, ГБ (GlobalMemoryStatusEx); 0 — не определилась."""
    st = _MemoryStatusEx()
    st.dwLength = ctypes.sizeof(_MemoryStatusEx)
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if not k32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return 0.0
    except (OSError, AttributeError):
        log.debug("GlobalMemoryStatusEx", exc_info=True)
        return 0.0
    return round(int(st.ullTotalPhys) / 1073741824, 1)


def hardware(gpu: tuple[str, int] | None, cuda_devices: int) -> Hardware:
    """Сведения о компьютере: GPU — из asr.gpu_info / asr.cuda_device_count (их передаёт
    движок), память и потоки процессора — отсюда."""
    name, vram = (gpu[0] or None, gpu[1] or None) if gpu else (None, None)
    return Hardware(name, vram, max(0, int(cuda_devices)), ram_gb(), os.cpu_count() or 1)


def _short_gpu(name: str | None) -> str:
    """«NVIDIA GeForce RTX 3060 Ti» → «RTX 3060 Ti»."""
    if not name:
        return tr("rec.gpu_nvidia")
    short = name
    for prefix in ("NVIDIA ", "GeForce "):
        if short.startswith(prefix):
            short = short[len(prefix):]
    return short.strip() or name


def _gb_text(gb: float) -> str:
    return i18n.fmt_num(gb, 0 if abs(gb - round(gb)) < 0.05 else 1)


def _cpu_text(hw: Hardware) -> tuple[str, str]:
    threads = tp("rec.threads", hw.cpu_threads)
    ram = tr("rec.ram", gb=_gb_text(hw.ram_gb)) if hw.ram_gb > 0 else tr("rec.ram_unknown")
    return threads, ram


def choose(hw: Hardware) -> Choice:
    """Модель, устройство и точность под этот компьютер (правила — в описании модуля)."""
    if hw.has_gpu:
        gpu = _short_gpu(hw.gpu_name)
        if hw.vram_mb is None:
            return Choice("large-v3-turbo", "cuda", "int8_float16",
                          tr("rec.reason_gpu_unknown", gpu=gpu))
        vram = _gb_text(hw.vram_mb / 1024)
        if hw.vram_mb >= VRAM_FULL_MB:
            return Choice("large-v3-turbo", "cuda", "float16",
                          tr("rec.reason_gpu_fast", gpu=gpu, vram=vram))
        if hw.vram_mb >= VRAM_INT8_MB:
            return Choice("large-v3-turbo", "cuda", "int8_float16",
                          tr("rec.reason_gpu_int8", gpu=gpu, vram=vram))
        return Choice("small", "cuda", "int8_float16",
                      tr("rec.reason_gpu_small", gpu=gpu, vram=vram))
    threads, ram = _cpu_text(hw)
    ram_ok = hw.ram_gb >= RAM_SMALL_GB or hw.ram_gb <= 0
    if hw.cpu_threads >= THREADS_SMALL and ram_ok:
        return Choice("small", "cpu", "int8", tr("rec.reason_cpu_small", threads=threads, ram=ram))
    return Choice("base", "cpu", "int8", tr("rec.reason_cpu_base", threads=threads, ram=ram))


def _repo(model: str) -> str:
    try:
        return fetch.repo_id(model)
    except fetch.FetchError:
        return fetch._FALLBACK_MODELS.get(model, model)


def options(recommended: str, budget_s: float | None = None) -> list[dict[str, Any]]:
    """Модели на выбор: точный размер с Hugging Face (не дольше budget_s), иначе запасной."""
    repos = {m: _repo(m) for m in MODELS}
    sizes = fetch.model_sizes(list(repos.values()),
                              SIZE_BUDGET_S if budget_s is None else budget_s)
    out: list[dict[str, Any]] = []
    for m in MODELS:
        exact = sizes.get(repos[m], 0)
        quality, speed = SCORES[m]
        out.append({"model": m, "repo": repos[m],
                    "size_mb": round(exact / 1_000_000) if exact > 0 else FALLBACK_MB[m],
                    "quality": quality, "speed": speed, "recommended": m == recommended,
                    "note": tr(NOTE_KEYS[m])})
    return out


def recommend(hw: Hardware, budget_s: float | None = None) -> dict[str, Any]:
    """Ответ команды model_recommend (docs/ARCHITECTURE.md → «Команды»)."""
    c = choose(hw)
    log.info("Подбор модели: GPU %s (%s МБ, CUDA-устройств %d), память %.1f ГБ, потоков %d → "
             "%s на %s (%s)", hw.gpu_name or "нет", hw.vram_mb or "?", hw.cuda_devices,
             hw.ram_gb, hw.cpu_threads, c.model, c.device, c.compute_type)
    return {
        "gpu_name": hw.gpu_name,
        "vram_mb": hw.vram_mb,
        "cuda_ok": hw.cuda_ok,
        "ram_gb": round(hw.ram_gb, 1),
        "cpu_threads": hw.cpu_threads,
        "recommended": {"model": c.model, "device": c.device, "compute_type": c.compute_type},
        "reason": c.reason,
        "options": options(c.model, budget_s),
    }
