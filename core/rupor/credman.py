"""Секреты в Windows Credential Manager (ctypes → advapi32) и чтение ключа из .env.

Ключи хранятся как «общие» учётные данные (CRED_TYPE_GENERIC) с сохранением на этом
компьютере (CRED_PERSIST_LOCAL_MACHINE), имя цели — ``Rupor/<провайдер>``.

Кодировка секрета — **UTF-16LE**: так же пишут сам Windows (панель «Диспетчер учётных
данных», ``cmdkey``) и PowerShell-модуль CredentialManager, поэтому ключ, заведённый
руками через панель управления, Рупор тоже прочитает. При чтении распознаётся и UTF-8
(на случай, если запись сделана сторонним инструментом).

Ни одна функция модуля не пишет секрет в логи и не кладёт его в текст исключений.
"""
from __future__ import annotations

import ctypes
import logging
import re
from ctypes import wintypes as wt
from pathlib import Path

from .i18n import tr

log = logging.getLogger(__name__)

TARGETS = {"openrouter": "Rupor/openrouter", "anthropic": "Rupor/anthropic"}

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
CRED_MAX_CREDENTIAL_BLOB_SIZE = 5 * 512  # байт, ограничение Windows
ERROR_NOT_FOUND = 1168


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wt.DWORD), ("dwHighDateTime", wt.DWORD)]


class CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wt.DWORD),
        ("Type", wt.DWORD),
        ("TargetName", wt.LPWSTR),
        ("Comment", wt.LPWSTR),
        ("LastWritten", FILETIME),
        ("CredentialBlobSize", wt.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wt.DWORD),
        ("AttributeCount", wt.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wt.LPWSTR),
        ("UserName", wt.LPWSTR),
    ]


PCREDENTIALW = ctypes.POINTER(CREDENTIALW)

# Отдельный экземпляр DLL: argtypes не пересекаются с другими модулями ядра.
_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

_CredReadW = _advapi32.CredReadW
_CredReadW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.POINTER(PCREDENTIALW)]
_CredReadW.restype = wt.BOOL

_CredWriteW = _advapi32.CredWriteW
_CredWriteW.argtypes = [PCREDENTIALW, wt.DWORD]
_CredWriteW.restype = wt.BOOL

_CredDeleteW = _advapi32.CredDeleteW
_CredDeleteW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD]
_CredDeleteW.restype = wt.BOOL

_CredFree = _advapi32.CredFree
_CredFree.argtypes = [ctypes.c_void_p]
_CredFree.restype = None


def _win_error(what: str, target: str, code: int) -> OSError:
    """Текст ошибки без секрета: только действие (read/write/delete), цель и код Windows."""
    return OSError(code, tr("cred.error", action=tr(f"cred.action_{what}"), target=target,
                            code=code, message=ctypes.FormatError(code).strip()))


def _decode(blob: bytes) -> str:
    """UTF-16LE (наш формат и формат Windows) или UTF-8 (сторонние инструменты)."""
    if not blob:
        return ""
    if len(blob) % 2 == 0:
        # ASCII в UTF-16LE: каждый второй байт нулевой — однозначно UTF-16
        if blob[1::2].count(0) == len(blob) // 2:
            return blob.decode("utf-16-le")
    try:
        s = blob.decode("utf-8")
        # кириллица в UTF-16 даёт байты 0x04 — в UTF-8 это управляющие символы
        if all(c.isprintable() or c in "\t\r\n" for c in s):
            return s
    except UnicodeDecodeError:
        pass
    return blob.decode("utf-16-le", errors="replace")


def read(target: str) -> str | None:
    """Секрет по имени цели; ``None``, если такой записи нет.

    Прочие ошибки Windows (нет доступа и т. п.) — ``OSError`` с кодом, без секрета."""
    pcred = PCREDENTIALW()
    if not _CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(pcred)):
        code = ctypes.get_last_error()
        if code == ERROR_NOT_FOUND:
            return None
        raise _win_error("read", target, code)
    try:
        cred = pcred.contents
        size = int(cred.CredentialBlobSize)
        blob = ctypes.string_at(cred.CredentialBlob, size) if size else b""
    finally:
        _CredFree(pcred)
    return _decode(blob)


def write(target: str, secret: str, user: str = "Rupor") -> None:
    """Создать или перезаписать секрет (UTF-16LE, сохраняется на этом компьютере)."""
    data = secret.encode("utf-16-le")
    if len(data) > CRED_MAX_CREDENTIAL_BLOB_SIZE:
        raise ValueError(tr("cred.too_long", target=target, size=len(data),
                            max=CRED_MAX_CREDENTIAL_BLOB_SIZE))
    buf = (ctypes.c_ubyte * max(1, len(data))).from_buffer_copy(data or b"\x00")
    cred = CREDENTIALW()
    cred.Flags = 0
    cred.Type = CRED_TYPE_GENERIC
    cred.TargetName = target
    cred.Comment = tr("app.name")
    cred.CredentialBlobSize = len(data)
    cred.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE
    cred.AttributeCount = 0
    cred.Attributes = None
    cred.TargetAlias = None
    cred.UserName = user
    try:
        if not _CredWriteW(ctypes.byref(cred), 0):
            raise _win_error("write", target, ctypes.get_last_error())
    finally:
        # затираем копию секрета в нашем буфере
        ctypes.memset(buf, 0, len(data))
    log.info("Секрет «%s» сохранён в Credential Manager", target)


def delete(target: str) -> None:
    """Удалить секрет; отсутствие записи — не ошибка."""
    if not _CredDeleteW(target, CRED_TYPE_GENERIC, 0):
        code = ctypes.get_last_error()
        if code == ERROR_NOT_FOUND:
            return
        raise _win_error("delete", target, code)
    log.info("Секрет «%s» удалён из Credential Manager", target)


# ---------- .env ----------

def _read_text(p: Path) -> str:
    raw = p.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):  # PowerShell 5 Out-File пишет UTF-16
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")  # UTF-8 с BOM и без
    except UnicodeDecodeError:
        return raw.decode("cp1251", errors="replace")


def _parse_value(v: str) -> str:
    v = v.strip()
    if v[:1] in ("'", '"'):
        q = v[0]
        out: list[str] = []
        i = 1
        while i < len(v):
            c = v[i]
            if q == '"' and c == "\\" and i + 1 < len(v) and v[i + 1] in ('"', "\\"):
                out.append(v[i + 1])
                i += 2
                continue
            if c == q:
                return "".join(out)
            out.append(c)
            i += 1
        return v[1:].strip()  # незакрытая кавычка — берём как есть
    # комментарий после значения: « # …» (решётка внутри значения без пробела — часть значения)
    v = re.split(r"\s+#", v, maxsplit=1)[0]
    return v.strip()


def read_env_key(path: str, name: str = "openrouter_api_key") -> str | None:
    """Значение переменной из .env-файла (``KEY=VALUE``); ``None`` — нет файла или ключа.

    Понимает: BOM (UTF-8/UTF-16), пустые строки и ``#``-комментарии, префикс ``export``,
    пробелы вокруг ``=``, одинарные/двойные кавычки, комментарий после значения.
    Имя сравнивается сначала точно, затем без учёта регистра. Значение в лог не пишется."""
    p = Path(path)
    try:
        text = _read_text(p)
    except FileNotFoundError:
        log.info("Файл %s не найден", p)
        return None
    except OSError as e:
        log.warning("Не удалось прочитать %s: %s", p, e.strerror or type(e).__name__)
        return None
    exact: str | None = None
    loose: str | None = None
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("export "):
            s = s[len("export "):].lstrip()
        k, sep, v = s.partition("=")
        if not sep:
            continue
        k = k.strip()
        if k == name and exact is None:
            exact = _parse_value(v)
        elif k.lower() == name.lower() and loose is None:
            loose = _parse_value(v)
    val = exact if exact is not None else loose
    return val or None


def mask(key: str | None) -> str:
    """Маска для UI: ``sk-or-v1-…XYZ`` (префикс формата + последние 3 символа)."""
    if not key:
        return ""
    key = key.strip()
    if len(key) <= 8:
        return "…"
    m = re.match(r"^((?:[A-Za-z0-9]{1,6}-){1,3})", key)
    prefix = m.group(1) if m and len(m.group(1)) <= 13 else ""
    if len(prefix) >= len(key) - 6:  # ключ почти весь из «префикса» — не раскрываем
        prefix = ""
    return f"{prefix}…{key[-3:]}"
