"""Runtime-хук PyInstaller: заглушка вместо PyAV (пакет ``av``) в собранном ядре.

faster-whisper импортирует ``av`` при загрузке пакета, но обращается к нему только в
``decode_audio`` — при чтении аудиофайлов. Рупор распознаёт звук с микрофона (массив numpy),
поэтому PyAV со встроенным FFmpeg в сборку не входит (packaging/rupor-core.spec, excludes):
так в установщик не попадают библиотеки кодеков, в том числе libx264/libx265 под GPL.
Распознавание файла (``--file``) в собранном ядре недоступно — только в окружении
разработки (``python -m rupor --file``).
"""
import sys
import types

_MSG = ("Чтение аудиофайлов недоступно в собранном ядре: PyAV не входит в установщик. "
        "Используйте окружение разработки: python -m rupor --file")


def _getattr(name: str) -> object:
    if name.startswith("__"):  # служебные атрибуты модуля (__path__, __spec__ …) — как обычно
        raise AttributeError(name)
    raise RuntimeError(_MSG)


if "av" not in sys.modules:
    _stub = types.ModuleType("av", "Заглушка PyAV в собранном ядре Рупора.")
    _stub.__getattr__ = _getattr  # type: ignore[method-assign]
    sys.modules["av"] = _stub
