"""Правила по названию окна (приоритет и валидация), ключи RDP-сессий (ru/en),
рассылка только в отмеченные сессии и перевод broadcast_excluded → broadcast_targets.

Окна — фейковые WindowInfo; настоящие окна пользователя не перечисляются."""
from __future__ import annotations

import json
import types
from pathlib import Path
from typing import Any

import pytest

from rupor import broadcast, config, inject, winutil
from rupor.config import MODE_CLIPBOARD, MODE_TYPE, Settings
from rupor.engine import resolve_mode, resolve_style, title_rules_for
from rupor.winutil import WindowInfo, rdp_session_key


def win(proc: str, title: str, cls: str = "X") -> WindowInfo:
    return WindowInfo(1, cls, title, 1, proc)


def rules(*items: dict[str, Any], **kw: Any) -> Settings:
    s = Settings(title_rules=list(items), **kw)
    s.validate()
    return s


# ---------- приоритет ----------

def test_title_rule_beats_app_rule_and_default() -> None:
    s = rules({"process": "chrome.exe", "title": "YouTube", "insert_mode": "type",
               "style": "messenger"},
              app_rules={"chrome.exe": {"insert_mode": "clipboard", "style": "business"}},
              default_style="normal")
    yt = win("Chrome.exe", "Мой канал — YOUTUBE Studio — Google Chrome")
    other = win("chrome.exe", "Почта — Google Chrome")
    assert resolve_style(yt, s) == "messenger" and resolve_mode(yt, s) == MODE_TYPE
    assert resolve_style(other, s) == "business" and resolve_mode(other, s) == MODE_CLIPBOARD
    assert resolve_style(win("notepad.exe", "YouTube.txt"), s) == "normal"  # другой процесс


def test_longest_title_wins_and_star_matches_any_process() -> None:
    s = rules({"process": "*", "title": "srv", "insert_mode": None, "style": "code"},
              {"process": "*", "title": "srv-analytics", "insert_mode": None,
               "style": "business"},
              {"process": "mstsc.exe", "title": "srv-analytics", "insert_mode": None,
               "style": "messenger"})
    w = win("mstsc.exe", "srv-analytics - Подключение к удалённому рабочему столу",
            "TscShellContainerClass")
    assert [r["style"] for r in title_rules_for(w, s)] == ["messenger", "business", "code"]
    assert resolve_style(w, s) == "messenger"          # та же длина: процесс важнее «*»
    assert resolve_style(win("chrome.exe", "srv-analytics dashboard"), s) == "business"
    assert resolve_style(win("chrome.exe", "srv-dev"), s) == "code"


def test_null_field_falls_through_to_next_level() -> None:
    s = rules({"process": "chrome.exe", "title": "YouTube Studio", "insert_mode": "clipboard",
               "style": None},
              {"process": "*", "title": "YouTube", "insert_mode": None, "style": "messenger"},
              app_rules={"chrome.exe": {"insert_mode": "type", "style": "business"}})
    w = win("chrome.exe", "YouTube Studio — Chrome")
    assert resolve_mode(w, s) == MODE_CLIPBOARD
    # null («Не менять») самого длинного правила — как у приложения, а не как у более
    # короткого правила по названию окна
    assert resolve_style(w, s) == "business"
    s2 = rules({"process": "chrome.exe", "title": "YouTube", "insert_mode": None, "style": None},
               app_rules={"chrome.exe": {"insert_mode": "type", "style": "business"}})
    w2 = win("chrome.exe", "YouTube")
    assert resolve_style(w2, s2) == "business" and resolve_mode(w2, s2) == MODE_TYPE
    # нет правила приложения — настройки
    s3 = rules({"process": "*", "title": "YouTube Studio", "insert_mode": None, "style": None},
               {"process": "*", "title": "YouTube", "insert_mode": "type", "style": "code"},
               default_style="normal", insert_mode="clipboard")
    assert resolve_style(w, s3) == "normal" and resolve_mode(w, s3) == MODE_CLIPBOARD


def test_null_in_longest_rule_takes_app_rule_not_shorter_title_rule() -> None:
    """Регрессия: «Jira Software» (style=null) не наследует стиль правила «Jira»."""
    s = rules({"process": "chrome.exe", "title": "Jira", "insert_mode": None,
               "style": "messenger"},
              {"process": "chrome.exe", "title": "Jira Software", "insert_mode": None,
               "style": None},
              app_rules={"chrome.exe": {"insert_mode": None, "style": "business"}})
    w = win("chrome.exe", "ANL-1 - Jira Software - Google Chrome")
    assert resolve_style(w, s) == "business"
    assert resolve_style(win("chrome.exe", "Jira Service Desk"), s) == "messenger"


def test_title_match_ignores_case_and_yo() -> None:
    s = rules({"process": "*", "title": "Отчёт", "insert_mode": None, "style": "business"})
    assert resolve_style(win("winword.exe", "ОТЧЕТ за квартал — Word"), s) == "business"
    assert resolve_style(win("winword.exe", ""), s) == s.default_style


# ---------- валидация ----------

def test_title_rule_validation_messages() -> None:
    r = config.title_rule(" Chrome.EXE ", "  YouTube ", "", None)
    assert r == {"process": "chrome.exe", "title": "YouTube", "insert_mode": None, "style": None}
    assert config.title_rule("*", "ab", "type", "code")["process"] == "*"
    with pytest.raises(ValueError, match="не короче 2"):
        config.title_rule("chrome.exe", " a ", None, None)
    with pytest.raises(ValueError, match="способ вставки"):
        config.title_rule("chrome.exe", "YouTube", "fast", None)
    with pytest.raises(ValueError, match="стиль"):
        config.title_rule("chrome.exe", "YouTube", None, "poem")
    with pytest.raises(ValueError, match="имя exe"):
        config.title_rule("C:\\chrome.exe", "YouTube", None, None)
    with pytest.raises(ValueError, match="строка"):
        config.title_rule("chrome.exe", 5, None, None)


def test_duplicate_title_rules_rejected_in_patch_and_skipped_on_load() -> None:
    s = Settings()
    dup = [{"process": "chrome.exe", "title": "YouTube", "insert_mode": None, "style": "code"},
           {"process": "CHROME.exe", "title": "youtube", "insert_mode": "type", "style": None}]
    with pytest.raises(ValueError, match="уже есть"):
        config.apply_patch(s, {"title_rules": dup})
    assert s.title_rules == []
    with pytest.raises(ValueError, match="список"):
        config.apply_patch(s, {"title_rules": {"chrome.exe": "x"}})
    soft = Settings(title_rules=[*dup, "мусор", {"process": "x.exe", "title": "a"}])  # type: ignore[list-item]
    soft.validate()
    assert soft.title_rules == [dup[0]]
    assert Settings().title_rules == []


# ---------- ключи RDP-сессий ----------

@pytest.mark.parametrize("title, key", [
    ("srv-analytics - Подключение к удалённому рабочему столу", "srv-analytics"),
    ("srv-analytics - Подключение к удаленному рабочему столу", "srv-analytics"),
    ("srv-analytics - Remote Desktop Connection", "srv-analytics"),
    ("10.0.0.5 - Remote Desktop Connection", "10.0.0.5"),
    ("work - 10.0.0.5 - Remote Desktop Connection", "work"),       # открыт .rdp-файл
    ("srv-analytics \u2013 Remote Desktop Connection", "srv-analytics"),
    ("srv-analytics", "srv-analytics"),
    ("  srv  -  x ", "srv"),
])
def test_mstsc_session_key(title: str, key: str) -> None:
    assert rdp_session_key(title, "mstsc.exe") == key
    assert rdp_session_key(title, "", "TscShellContainerClass") == key


def test_tabbed_clients_key_ignores_selected_connection() -> None:
    """Регрессия: у mRemoteNG заголовок «mRemoteNG - <файл> - <выбранное подключение>» —
    при переключении вкладки ключ не меняется (иначе рассылка молча пропускала окно)."""
    k1 = rdp_session_key("mRemoteNG - confCons.xml - srv-01", "mRemoteNG.exe")
    k2 = rdp_session_key("mRemoteNG - confCons.xml - srv-02", "mRemoteNG.exe")
    assert k1 == k2 == "mRemoteNG - confCons.xml"
    assert rdp_session_key("mRemoteNG - confCons.xml", "mremoteng.exe") == k1
    assert rdp_session_key("mRemoteNG - C:\\Users\\u\\confCons.xml - srv-01",
                           "mRemoteNG.exe") == k1                    # полный путь к файлу
    assert rdp_session_key("mRemoteNG - other.xml - srv-01", "mRemoteNG.exe") == \
        "mRemoteNG - other.xml"                                      # другой файл — другой ключ
    assert rdp_session_key("mRemoteNG - srv-01", "mRemoteNG.exe") == "mRemoteNG"
    assert rdp_session_key("mRemoteNG", "mRemoteNG.exe") == "mRemoteNG"
    assert rdp_session_key("srv - Remote Desktop Connection Manager v2.93", "RDCMan.exe") == \
        rdp_session_key("Remote Desktop Connection Manager v2.93", "RDCMan.exe") == "RDCMan"


def test_other_clients_key_is_whole_title() -> None:
    t = "prod-db - Royal TS"
    assert rdp_session_key(t, "royalts.exe") == t


# ---------- рассылка только в отмеченные ----------

RDP = [WindowInfo(1, "TscShellContainerClass", "srv1 - Подключение к удалённому рабочему столу",
                  11, "mstsc.exe"),
       WindowInfo(2, "TscShellContainerClass", "SRV2 - Remote Desktop Connection", 12,
                  "mstsc.exe"),
       WindowInfo(3, "WindowsForms10", "mRemoteNG - confCons.xml - prod", 13,
                  "mRemoteNG.exe")]
MRNG = "mRemoteNG - confCons.xml"


def test_targets_are_whitelist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(winutil, "list_rdp_windows", lambda c, p: RDP)
    assert broadcast.targets(Settings()) == []                   # ничего не отмечено
    s = Settings(broadcast_targets=["srv2", MRNG.lower(), "closed-srv"])
    assert [w.hwnd for w in broadcast.targets(s)] == [2, 3]
    assert broadcast.target_keys(s) == ["SRV2", MRNG]
    # в mRemoteNG выбрали другую вкладку — окно по-прежнему отмечено
    other = [*RDP[:2], WindowInfo(3, "WindowsForms10", "mRemoteNG - confCons.xml - dev", 13,
                                  "mRemoteNG.exe")]
    monkeypatch.setattr(winutil, "list_rdp_windows", lambda c, p: other)
    assert [w.hwnd for w in broadcast.targets(s)] == [2, 3]


def test_send_all_types_only_into_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    typed: list[int | None] = []
    monkeypatch.setattr(winutil, "list_rdp_windows", lambda c, p: RDP)
    monkeypatch.setattr(winutil, "foreground", lambda: None)
    monkeypatch.setattr(winutil, "activate", lambda hwnd: True)
    monkeypatch.setattr(inject, "wait_modifiers_released", lambda: None)
    monkeypatch.setattr(broadcast, "time", types.SimpleNamespace(sleep=lambda s: None))
    monkeypatch.setattr(inject, "type_text",
                        lambda text, delay_ms=0, chunk=32, expect_hwnd=None:
                        typed.append(expect_hwnd))
    rep = broadcast.send_all("текст", Settings(broadcast_targets=["srv1"]))
    assert typed == [1] and rep.sent == ["srv1"] and rep.failed == []
    typed.clear()
    rep = broadcast.send_all("текст", Settings(broadcast_targets=[]))
    assert typed == [] and rep.sent == [] and rep.failed == []


def test_engine_deliver_without_targets_gives_notice(monkeypatch: pytest.MonkeyPatch) -> None:
    from rupor import engine
    monkeypatch.setattr(winutil, "list_rdp_windows", lambda c, p: RDP)
    seen: list[dict[str, Any]] = []
    d = engine.deliver("текст", Settings(broadcast_targets=["nope"]), True,
                       lambda text, **kw: seen.append({"text": text, **kw}))
    assert not d.ok
    assert seen == [{"text": "Не выбраны RDP-сессии для рассылки", "level": "warn",
                     "action": "open_settings_insert"}]


# ---------- миграция broadcast_excluded → broadcast_targets ----------

def _write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, data: dict[str, Any]) -> Path:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    d = tmp_path / "Rupor"
    d.mkdir()
    (d / "settings.json").write_text(json.dumps(data), encoding="utf-8")
    return d / "settings.json"


def test_old_file_migrates_open_sessions_minus_excluded(tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(winutil, "list_rdp_windows", lambda c, p: RDP)
    f = _write(tmp_path, monkeypatch, {"default_style": "normal", "broadcast_excluded": [
        "SRV2 - Remote Desktop Connection"]})
    s = config.load()
    assert s.broadcast_targets == ["srv1", MRNG]
    assert json.loads(f.read_text(encoding="utf-8"))["broadcast_targets"] == ["srv1", MRNG]
    # повторная загрузка ничего не пересчитывает, даже если окна другие
    monkeypatch.setattr(winutil, "list_rdp_windows", lambda c, p: [])
    assert config.load().broadcast_targets == ["srv1", MRNG]


def test_old_file_excluded_by_key_and_no_windows(tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(winutil, "list_rdp_windows", lambda c, p: RDP)
    _write(tmp_path, monkeypatch, {"default_style": "normal",
                                   "broadcast_excluded": ["srv1",
                                                          "mRemoteNG - confCons.xml - prod"]})
    assert config.load().broadcast_targets == ["SRV2"]


def test_old_file_without_windows_gets_empty_list(tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path, monkeypatch, {"default_style": "normal"})   # conftest: окон нет
    assert config.load().broadcast_targets == []


def test_file_with_targets_is_not_migrated(tmp_path: Path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(winutil, "list_rdp_windows", lambda c, p: RDP)
    _write(tmp_path, monkeypatch, {"default_style": "normal", "broadcast_targets": ["x"]})
    assert config.load().broadcast_targets == ["x"]


def test_new_settings_defaults() -> None:
    s = Settings()
    assert s.vocab_enabled is True and s.context_enabled is True
    assert s.title_rules == [] and s.broadcast_targets == []
    with pytest.raises(ValueError, match="Учитывать мои частые слова"):
        config.apply_patch(s, {"vocab_enabled": "да"})
