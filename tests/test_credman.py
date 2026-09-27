import secrets
import sys
from pathlib import Path

import pytest

from rupor import credman


def env(tmp_path: Path, text: str, encoding: str = "utf-8") -> str:
    p = tmp_path / ".env"
    p.write_bytes(text.encode(encoding))
    return str(p)


# ---------- read_env_key ----------

def test_env_plain_and_spaces(tmp_path: Path) -> None:
    p = env(tmp_path, "a=1\n  openrouter_api_key  =  sk-or-v1-abc  \nb=2\n")
    assert credman.read_env_key(p) == "sk-or-v1-abc"


def test_env_quotes(tmp_path: Path) -> None:
    assert credman.read_env_key(env(tmp_path, 'openrouter_api_key="sk-or-v1-q"\n')) == "sk-or-v1-q"
    assert credman.read_env_key(env(tmp_path, "openrouter_api_key='sk-or-v1-s' # к\n")) == "sk-or-v1-s"
    # внутри кавычек решётка и экранированная кавычка — часть значения
    p = env(tmp_path, 'openrouter_api_key="a # b \\" c"\n')
    assert credman.read_env_key(p) == 'a # b " c'


def test_env_comments_export_and_inline(tmp_path: Path) -> None:
    text = ("# openrouter_api_key=закомментировано\n"
            "\n"
            "export openrouter_api_key=sk-or-v1-exp # комментарий\n")
    assert credman.read_env_key(env(tmp_path, text)) == "sk-or-v1-exp"
    # решётка без пробела перед ней и знак = — часть значения
    assert credman.read_env_key(env(tmp_path, "openrouter_api_key=ab#c=d\n")) == "ab#c=d"


def test_env_bom_and_crlf(tmp_path: Path) -> None:
    p = env(tmp_path, "﻿openrouter_api_key=sk-bom\r\nx=1\r\n")
    assert credman.read_env_key(p) == "sk-bom"
    p16 = env(tmp_path, "﻿openrouter_api_key=sk-utf16\r\n", "utf-16-le")
    assert credman.read_env_key(p16) == "sk-utf16"


def test_env_case_and_exact_priority(tmp_path: Path) -> None:
    assert credman.read_env_key(env(tmp_path, "OPENROUTER_API_KEY=up\n")) == "up"
    p = env(tmp_path, "OPENROUTER_API_KEY=up\nopenrouter_api_key=exact\n")
    assert credman.read_env_key(p) == "exact"
    assert credman.read_env_key(env(tmp_path, "other=1\n"), "other") == "1"


def test_env_missing(tmp_path: Path) -> None:
    assert credman.read_env_key(str(tmp_path / "нет.env")) is None
    assert credman.read_env_key(env(tmp_path, "x=1\n")) is None
    assert credman.read_env_key(env(tmp_path, "openrouter_api_key=\n")) is None
    assert credman.read_env_key(env(tmp_path, 'openrouter_api_key=""\n')) is None


# ---------- mask ----------

def test_mask() -> None:
    k = "sk-or-v1-" + "0123456789abcdef" * 4 + "XYZ"
    assert credman.mask(k) == "sk-or-v1-…XYZ"
    assert credman.mask("sk-ant-api03-" + "Xy_z" * 20 + "9QA") == "sk-ant-api03-…9QA"
    assert credman.mask("abcdefghijklmnopqrstuvwxyz") == "…xyz"
    assert credman.mask("short") == "…"
    assert credman.mask("") == ""
    assert credman.mask(None) == ""
    m = credman.mask(k)
    assert "0123456789" not in m


def test_decode_formats() -> None:
    assert credman._decode("sk-or-v1-x".encode("utf-16-le")) == "sk-or-v1-x"
    assert credman._decode("sk-or-v1-xy".encode("utf-8")) == "sk-or-v1-xy"
    assert credman._decode("ключ".encode("utf-16-le")) == "ключ"
    assert credman._decode("ключ-1".encode("utf-8")) == "ключ-1"
    assert credman._decode(b"") == ""


# ---------- настоящий Credential Manager (только цели Rupor/test-*) ----------

@pytest.mark.skipif(sys.platform != "win32", reason="только Windows")
def test_credential_manager_roundtrip() -> None:
    target = f"Rupor/test-{secrets.token_hex(6)}"
    assert target.startswith("Rupor/test-")
    try:
        assert credman.read(target) is None
        credman.write(target, "sk-or-v1-тест-1")
        assert credman.read(target) == "sk-or-v1-тест-1"
        credman.write(target, "sk-or-v1-второй")  # перезапись
        assert credman.read(target) == "sk-or-v1-второй"
        credman.delete(target)
        assert credman.read(target) is None
        credman.delete(target)  # повторное удаление — не ошибка
    finally:
        credman.delete(target)
    assert credman.read(target) is None


@pytest.mark.skipif(sys.platform != "win32", reason="только Windows")
def test_credential_manager_too_long() -> None:
    target = f"Rupor/test-{secrets.token_hex(6)}"
    try:
        with pytest.raises(ValueError):
            credman.write(target, "x" * 2000)  # 4000 байт в UTF-16 > 2560
        assert credman.read(target) is None
    finally:
        credman.delete(target)
