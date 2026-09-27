"""Трей старого режима (без UI на Tauri): статус, пауза, режим вставки, стиль, RDP-сессии,
вставить/скопировать последнее, звуки, выход. В режиме --sidecar трей рисует Rust.

Подписи — на языке интерфейса (i18n.tr): пункты меню — функции, которые pystray вызывает
при каждой перестройке меню, поэтому смена языка видна сразу (update_menu по смене языка)."""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

import pystray
from PIL import Image, ImageDraw

from . import ai, broadcast, config, i18n, winutil
from .config import MODE_AUTO, MODE_CLIPBOARD, MODE_TYPE
from .engine import (AI, ERROR, HANDS_FREE, IDLE, LOADING, PAUSED, PROCESSING, RECORDING, Engine,
                     styles_localized)
from .hotkeys import key_label
from .i18n import tr

log = logging.getLogger(__name__)

_COLORS = {
    IDLE: (120, 124, 140), LOADING: (70, 130, 230), RECORDING: (235, 64, 64),
    HANDS_FREE: (235, 64, 160), PROCESSING: (240, 170, 40), AI: (240, 170, 40),
    PAUSED: (70, 70, 70), ERROR: (190, 40, 40),
}
_STATES = (IDLE, LOADING, RECORDING, HANDS_FREE, PROCESSING, AI, PAUSED, ERROR)
_MODES = (MODE_AUTO, MODE_TYPE, MODE_CLIPBOARD)


def _status(state: str) -> str:
    """Статус для меню и подсказки: каталог tray.status_<state>."""
    return tr(f"tray.status_{state}") if state in _STATES else state


def _label(key: str) -> Any:
    """Подпись пункта меню на текущем языке (pystray зовёт её при перестройке меню)."""
    return lambda _i: tr(key)


def _style_name(style_id: str) -> Any:
    def name(_i: Any) -> str:
        return next((st["name"] for st in styles_localized() if st["id"] == style_id),
                    style_id)
    return name


def _icon_image(state: str) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = _COLORS.get(state, _COLORS[IDLE])
    d.ellipse((4, 4, 60, 60), fill=c + (255,))
    # микрофон
    d.rounded_rectangle((25, 13, 39, 37), radius=7, fill=(255, 255, 255, 255))
    d.arc((19, 22, 45, 45), start=0, end=180, fill=(255, 255, 255, 255), width=3)
    d.line((32, 45, 32, 51), fill=(255, 255, 255, 255), width=3)
    return img


class Tray:
    def __init__(self, engine: Engine) -> None:
        self.e = engine
        self.s = engine.s
        self._stop = threading.Event()
        self.icon = pystray.Icon("rupor", _icon_image(engine.state), self._title(engine.state),
                                 self._menu())
        engine.bus.subscribe(self._on_event)
        i18n.add_listener(self._on_language)

    # ---------- меню ----------

    def _menu(self) -> pystray.Menu:
        item = pystray.MenuItem
        mode_items = [item(_label(f"tray.mode_{m}"), self._set("insert_mode", m),
                           checked=self._is("insert_mode", m), radio=True) for m in _MODES]
        style_items = [item(_style_name(st["id"]), self._set("default_style", st["id"]),
                            checked=self._is("default_style", st["id"]), radio=True)
                       for st in ai.STYLES]
        items: list[Any] = [
            item(lambda _i: f"{self._title(self.e.state)}"
                 f" · {'GPU' if self.e.rec.device == 'cuda' else 'CPU'}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            item(_label("tray.pause"), self._toggle_pause, checked=lambda _i: self.e.paused),
            item(_label("tray.insert_mode"), pystray.Menu(*mode_items)),
            item(_label("tray.style"), pystray.Menu(*style_items)),
            item(_label("tray.ai_cleanup"), self._toggle("ai_enabled"),
                 checked=lambda _i: self.s.ai_enabled),
            item(_label("tray.rdp"), pystray.Menu(self._rdp_items)),
            item(_label("tray.last_insert"), self._insert_last),
            item(_label("tray.copy_last"), self._copy_last),
            item(_label("tray.sounds"), self._toggle("sounds"), checked=lambda _i: self.s.sounds),
            pystray.Menu.SEPARATOR,
        ]
        if not winutil.self_elevated():
            items.append(item(_label("tray.relaunch_admin"), self._relaunch_admin))
        items += [
            item(_label("tray.open_settings_dir"), lambda: os.startfile(config.app_dir())),
            item(_label("tray.quit"), self._quit),
        ]
        return pystray.Menu(*items)

    def _rdp_items(self) -> list[Any]:
        wins = winutil.list_rdp_windows(self.s.rdp_classes, self.s.rdp_processes)
        if not wins:
            return [pystray.MenuItem(tr("tray.rdp_empty"), None, enabled=False)]
        out = []
        for wi in wins:
            key = broadcast.session_key(wi)
            out.append(pystray.MenuItem(
                key[:60], self._toggle_rdp(key),
                checked=lambda _i, k=key: k.casefold() in broadcast.selected(self.s)))
        n = len(broadcast.targets(self.s))
        keys = key_label(f"{self.s.ptt_key}+{self.s.broadcast_modifier}")
        out += [pystray.Menu.SEPARATOR,
                pystray.MenuItem(i18n.tp("tray.rdp_hint", n, keys=keys), None, enabled=False)]
        return out

    def _update(self, patch: dict[str, Any]) -> None:
        try:
            self.e.update_settings(patch)
        except ValueError as e:
            self._notify(str(e))

    def _set(self, key: str, value: Any) -> Any:
        def f() -> None:
            self._update({key: value})
        return f

    def _is(self, key: str, value: Any) -> Any:
        return lambda _i: getattr(self.s, key) == value

    def _toggle(self, key: str) -> Any:
        def f() -> None:
            self._update({key: not getattr(self.s, key)})
        return f

    def _toggle_rdp(self, key: str) -> Any:
        def f() -> None:
            rest = [k for k in self.s.broadcast_targets if k.casefold() != key.casefold()]
            if len(rest) == len(self.s.broadcast_targets):
                rest.append(key)                  # не была отмечена — отметить
            self._update({"broadcast_targets": rest})
            self.icon.update_menu()
        return f

    def _toggle_pause(self) -> None:
        self.e.set_paused(not self.e.paused)

    def _insert_last(self) -> None:
        try:
            self.e.insert_last()
        except ValueError as e:
            self._notify(str(e))

    def _copy_last(self) -> None:
        try:
            self.e.copy_last()
        except (ValueError, OSError) as e:
            self._notify(str(e))

    def _relaunch_admin(self) -> None:
        if winutil.relaunch_as_admin():
            self._quit()

    def _quit(self) -> None:
        self._stop.set()
        i18n.remove_listener(self._on_language)
        self.e.shutdown()
        self.icon.stop()

    # ---------- события движка ----------

    @staticmethod
    def _title(state: str) -> str:
        return f"{tr('app.name')} — {_status(state)}"

    def _on_language(self, _lang: str) -> None:
        """Язык сменился: подсказка иконки и меню — на новом языке."""
        try:
            self.icon.title = self._title(self.e.state)
            self.icon.update_menu()
        except Exception:
            log.debug("Трей: подписи не обновились после смены языка", exc_info=True)

    def _on_event(self, event: str, data: dict[str, Any]) -> None:
        if event == "state":
            st = str(data.get("state", IDLE))
            self.icon.icon = _icon_image(st)
            self.icon.title = self._title(st)
            self.icon.update_menu()
        elif event == "notice" and data.get("toast"):
            self._notify(str(data.get("text", "")))
        elif event == "ready" and data.get("device") == "cpu":
            self._notify(tr("tray.cpu_warning"))

    def _notify(self, text: str) -> None:
        try:
            self.icon.notify(text[:250], tr("app.name"))
        except Exception:
            log.exception("notify")

    def _refresh_loop(self) -> None:
        # win32-меню pystray строится заранее — периодически обновляем список RDP-окон
        while not self._stop.wait(5):
            try:
                self.icon.update_menu()
            except Exception:
                log.debug("update_menu", exc_info=True)

    def run(self) -> None:
        threading.Thread(target=self._refresh_loop, daemon=True).start()
        self.icon.run()
