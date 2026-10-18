"""Подбор модели распознавания под мощность компьютера — мастер первого запуска
(команда ``model_recommend``).

Правила (``choose``):
- видеокарта NVIDIA, которую видит CUDA (``ctranslate2.get_cuda_device_count``; cuBLAS для
  этого не нужен — он грузится только при загрузке модели): видеопамяти от 4 ГБ —
  large-v3-turbo, cuda, float16; 2–4 ГБ — large-v3-turbo, cuda, int8_float16 (≈1,5 ГБ
  видеопамяти); меньше — small, cuda, int8_float16; объём не определился — как 2–4 ГБ;
- точность — только та, что CTranslate2 умеет на этой карте
  (``ctranslate2.get_supported_compute_types("cuda")``; явно заданную неподходящую он не
  подменяет, а отказывается грузить модель): float16 и int8_float16 нет (Pascal, GTX 10xx) —
  int8 на той же карте; нет и int8 (Maxwell и старше) — правила для процессора;
- карту видит только драйвер (NVML), а CUDA — нет (драйвер слишком старый для CUDA 12) —
  правила для процессора;
- без видеокарты NVIDIA: от 8 потоков процессора и от 8 ГБ памяти — small, cpu, int8,
  иначе base, cpu, int8 (объём памяти не определился — решают одни потоки).
Пороги — с допуском: 4-гигабайтную карту NVML может показать чуть меньше 4096 МБ. Память —
установленная (``GetPhysicallyInstalledSystemMemory``: у компьютера с 8 ГБ и встроенной
графикой Windows видит 7,3 ГБ и меньше), не узнать — та, что видит Windows
(``GlobalMemoryStatusEx``).

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
    # точности, которые CTranslate2 умеет на первой карте CUDA; None — не узнать (правила по
    # видеопамяти без поправки)
    cuda_types: frozenset[str] | None = None

    @property
    def cuda_ok(self) -> bool:
        return self.cuda_devices > 0

    @property
    def has_gpu(self) -> bool:
        """Карта годится для CUDA: её видит CUDA. Карта, которую видит только драйвер (NVML),
        не считается — CUDA на ней не запустится (cuBLAS тут ни при чём: для подсчёта
        устройств он не нужен)."""
        return self.cuda_ok


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


def _installed_ram_kb() -> int | None:
    """Установленная память, КиБ (GetPhysicallyInstalledSystemMemory — по данным SMBIOS, без
    вычета того, что берут встроенная графика и прошивка); None — не узнать (бывает в
    виртуальных машинах)."""
    kb = ctypes.c_ulonglong(0)
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if not k32.GetPhysicallyInstalledSystemMemory(ctypes.byref(kb)):
            return None
    except (OSError, AttributeError):
        log.debug("GetPhysicallyInstalledSystemMemory", exc_info=True)
        return None
    return int(kb.value) or None


def _usable_ram_bytes() -> int | None:
    """Память, которую видит Windows, байты (GlobalMemoryStatusEx: установленная минус то,
    что взяли встроенная графика и прошивка); None — не узнать."""
    st = _MemoryStatusEx()
    st.dwLength = ctypes.sizeof(_MemoryStatusEx)
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if not k32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return None
    except (OSError, AttributeError):
        log.debug("GlobalMemoryStatusEx", exc_info=True)
        return None
    return int(st.ullTotalPhys) or None


def ram_gb() -> float:
    """Оперативная память компьютера, ГБ: установленная (8-гигабайтный ноутбук со встроенной
    графикой — 8, а не 7,3), не узнать — та, что видит Windows; 0 — не определилась."""
    kb = _installed_ram_kb()
    if kb:
        return round(kb / 1048576, 1)
    total = _usable_ram_bytes()
    return round(total / 1073741824, 1) if total else 0.0


def hardware(gpu: tuple[str, int] | None, cuda_devices: int,
             cuda_types: frozenset[str] | None = None) -> Hardware:
    """Сведения о компьютере: GPU — из asr.gpu_info / asr.cuda_device_count /
    asr.cuda_compute_types (их передаёт движок), память и потоки процессора — отсюда."""
    name, vram = (gpu[0] or None, gpu[1] or None) if gpu else (None, None)
    return Hardware(name, vram, max(0, int(cuda_devices)), ram_gb(), os.cpu_count() or 1,
                    cuda_types)


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


# Желаемая точность на GPU → что брать, если карта её не умеет (по порядку). int8 на CUDA —
# int8_float32: его умеет и Pascal (GTX 10xx, CC 6.1), где float16 и int8_float16 нет
# (у CTranslate2 обе требуют CC 7.0 — одна есть, есть и другая).
_GPU_FALLBACK: dict[str, tuple[str, ...]] = {
    "float16": ("float16", "int8"),
    "int8_float16": ("int8_float16", "int8"),
}


def _fit(want: str, types: frozenset[str] | None) -> str | None:
    """Точность для карты: want, если CTranslate2 умеет её на этой карте (types; None — не
    узнать, тогда want), иначе ближайшая из умеющих; никакая не подходит — None."""
    if types is None:
        return want
    for ct in _GPU_FALLBACK.get(want, (want,)):
        if ct in types or (ct == "int8" and "int8_float32" in types):
            return ct
    return None


def choose(hw: Hardware) -> Choice:
    """Модель, устройство и точность под этот компьютер (правила — в описании модуля)."""
    gpu = _short_gpu(hw.gpu_name)
    why: str | None = None      # карта NVIDIA есть, но распознавать на ней не выйдет — почему
    if hw.has_gpu:
        if hw.vram_mb is None:
            model, want, key = "large-v3-turbo", "int8_float16", "rec.reason_gpu_unknown"
            kw: dict[str, Any] = {"gpu": gpu}
        else:
            kw = {"gpu": gpu, "vram": _gb_text(hw.vram_mb / 1024)}
            if hw.vram_mb >= VRAM_FULL_MB:
                model, want, key = "large-v3-turbo", "float16", "rec.reason_gpu_fast"
            elif hw.vram_mb >= VRAM_INT8_MB:
                model, want, key = "large-v3-turbo", "int8_float16", "rec.reason_gpu_int8"
            else:
                model, want, key = "small", "int8_float16", "rec.reason_gpu_small"
        ct = _fit(want, hw.cuda_types)
        if ct == want:
            return Choice(model, "cuda", ct, tr(key, **kw))
        if ct is not None:      # float16 карта не умеет (GTX 10xx) — int8 на ней же
            return Choice(model, "cuda", ct, tr("rec.reason_gpu_int8_only", gpu=gpu, model=model))
        why = tr("rec.why_old_gpu")
    elif hw.gpu_name is not None:
        why = tr("rec.why_no_cuda")
    threads, ram = _cpu_text(hw)
    ram_ok = hw.ram_gb >= RAM_SMALL_GB or hw.ram_gb <= 0
    small = hw.cpu_threads >= THREADS_SMALL and ram_ok
    model = "small" if small else "base"
    if why is None:
        key = "rec.reason_cpu_small" if small else "rec.reason_cpu_base"
        return Choice(model, "cpu", "int8", tr(key, threads=threads, ram=ram))
    key = "rec.reason_gpu_off_small" if small else "rec.reason_gpu_off_base"
    return Choice(model, "cpu", "int8", tr(key, gpu=gpu, why=why, threads=threads, ram=ram))


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
    log.info("Подбор модели: GPU %s (%s МБ, CUDA-устройств %d, точности %s), память %.1f ГБ, "
             "потоков %d → %s на %s (%s)", hw.gpu_name or "нет", hw.vram_mb or "?",
             hw.cuda_devices, ",".join(sorted(hw.cuda_types)) if hw.cuda_types else "?",
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
