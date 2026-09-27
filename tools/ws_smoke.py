"""Дымовой тест настоящего ядра по WebSocket.

    .venv\\Scripts\\python tools\\ws_smoke.py [--no-record] [--no-ui-pid-check] [--exe путь]

Запускает `python -m rupor --sidecar --no-hook --no-mutex --ws-port <свободный>
--token <случайный> --ui-pid <pid этого скрипта>` (рабочая папка core, APPDATA — временная
папка: настройки, база и логи пользователя не трогаются; звуки выключены), ждёт hello,
вызывает read-only команды, test_record_start/stop (настоящий микрофон, ~1 с), cuda_check,
setup_status, ai_key_status, stats_get, смену языка интерфейса на лету (ui_language, ошибки
и стили по-английски и снова по-русски) и quit. Печатает сводку и задержки.
С --exe проверяется собранное ядро (PyInstaller) вместо `python -m rupor`.

Ничего не печатает в окна и не шлёт нажатий клавиш: хука нет, команд вставки
(last_insert, history_reinsert) скрипт не вызывает. Звук компьютера не трогает:
duck_mode "off" (иначе проверочная запись приглушила бы музыку или созвон пользователя).
Токен и ключи не выводятся.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, connect

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
CREATE_NO_WINDOW = 0x08000000
CYRILLIC = re.compile(r"[А-Яа-яЁё]")

READONLY = ["get_state", "get_settings", "list_devices", "setup_status", "history_list",
            "dict_list", "snippets_list", "export_data", "stats_get", "draft_get",
            "styles_list", "app_rules_list", "title_rules_list", "recent_apps", "rdp_windows",
            "ai_usage_stats", "vocab_list"]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Core:
    exe: Path | None = None  # собранное ядро вместо python -m rupor

    def __init__(self, appdata: Path, ui_pid: int) -> None:
        self.port = free_port()
        self.token = secrets.token_hex(16)
        self.log = appdata / "core-stdout.txt"
        env = dict(os.environ, APPDATA=str(appdata), PYTHONIOENCODING="utf-8")
        prog = [str(self.exe)] if self.exe else [str(PY), "-m", "rupor"]
        args = [*prog, "--sidecar", "--no-hook", "--no-mutex",
                "--ws-port", str(self.port), "--token", self.token, "--ui-pid", str(ui_pid)]
        self._out = open(self.log, "wb")
        self.t0 = time.perf_counter()
        self.proc = subprocess.Popen(args, cwd=ROOT / "core", env=env, stdout=self._out,
                                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     creationflags=CREATE_NO_WINDOW)

    def url(self, token: str | None = None) -> str:
        t = self.token if token is None else token
        return f"ws://127.0.0.1:{self.port}/?token={t}"

    def wait_port(self, timeout: float = 60) -> float:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"ядро завершилось с кодом {self.proc.returncode}")
            try:
                with socket.create_connection(("127.0.0.1", self.port), 0.2):
                    return (time.perf_counter() - self.t0) * 1000
            except OSError:
                time.sleep(0.1)
        raise TimeoutError("ядро не открыло порт")

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(5)
        self._out.close()


class Client:
    def __init__(self, url: str) -> None:
        self.ws: ClientConnection = connect(url, open_timeout=10, max_size=None, legacy=True)
        self.msgs: list[dict[str, Any]] = []
        self._id = 0

    def recv(self, timeout: float) -> dict[str, Any]:
        raw = self.ws.recv(timeout=timeout)
        msg: dict[str, Any] = json.loads(raw)
        self.msgs.append(msg)
        return msg

    def call(self, cmd: str, args: Any = None, timeout: float = 60) -> tuple[dict[str, Any], float]:
        self._id += 1
        rid = self._id
        req: dict[str, Any] = {"id": rid, "cmd": cmd}
        if args is not None:
            req["args"] = args
        t0 = time.perf_counter()
        self.ws.send(json.dumps(req, ensure_ascii=False))
        deadline = time.monotonic() + timeout
        while True:
            msg = self.recv(max(0.1, deadline - time.monotonic()))
            if msg.get("id") == rid:
                return msg, (time.perf_counter() - t0) * 1000

    def events(self, name: str) -> list[dict[str, Any]]:
        return [m["data"] for m in self.msgs if m.get("event") == name]

    def wait_event(self, name: str, pred: Any = lambda d: True, timeout: float = 60) -> dict[str, Any]:
        for m in self.msgs:
            if m.get("event") == name and pred(m["data"]):
                return dict(m["data"])
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                m = self.recv(0.5)
            except TimeoutError:
                continue
            if m.get("event") == name and pred(m["data"]):
                return dict(m["data"])
        raise TimeoutError(f"нет события {name}")


def short(result: Any) -> str:
    if isinstance(result, list):
        return f"список из {len(result)}"
    if isinstance(result, dict):
        keys = list(result)
        return "{" + ", ".join(keys[:6]) + (", …" if len(keys) > 6 else "") + "}"
    return repr(result)[:60]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-record", action="store_true", help="без test_record и mic_monitor")
    ap.add_argument("--no-ui-pid-check", action="store_true",
                    help="не проверять выход ядра вместе с --ui-pid")
    ap.add_argument("--exe", type=Path, help="собранное ядро (rupor-core.exe) вместо .venv")
    args = ap.parse_args()
    if args.exe:
        Core.exe = args.exe.resolve()
        print(f"Проверяю собранное ядро: {Core.exe}")
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    appdata = Path(tempfile.mkdtemp(prefix="rupor_smoke_"))
    (appdata / "Rupor").mkdir()
    # звуки выключены, мастер не пройден — ядро ничего не станет скачивать само; звук
    # компьютера во время проверочной записи не приглушается (он — пользователя)
    (appdata / "Rupor" / "settings.json").write_text(
        json.dumps({"sounds": False, "first_run_done": False, "default_style": "normal",
                    "duck_mode": "off"}),
        encoding="utf-8")
    rows: list[tuple[str, str, float, str]] = []
    failures: list[str] = []

    def check(name: str, ok: bool, ms: float, note: str) -> None:
        rows.append((name, "ok" if ok else "ОШИБКА", ms, note))
        if not ok:
            failures.append(f"{name}: {note}")

    core = Core(appdata, os.getpid())
    keep_logs = False
    try:
        port_ms = core.wait_port()
        print(f"Порт открыт через {port_ms:.0f} мс после запуска процесса")

        # без токена — 4401
        bad = connect(core.url("wrong"), open_timeout=5, legacy=True)
        try:
            bad.recv(timeout=5)
            check("без токена", False, 0, "соединение не закрыто")
        except ConnectionClosed as e:
            code = e.rcvd.code if e.rcvd else None
            check("без токена", code == 4401, 0, f"закрыто с кодом {code}")

        t0 = time.perf_counter()
        c = Client(core.url())
        hello = c.recv(10)
        hello_ms = (time.perf_counter() - t0) * 1000
        ok = hello.get("event") == "hello" and "state" in hello.get("data", {})
        check("hello", ok, hello_ms, f"state={hello.get('data', {}).get('state')}")

        st = c.wait_event("state", lambda d: d["model_loaded"] or d["state"] == "error",
                          timeout=120) if not hello["data"]["model_loaded"] else hello["data"]
        load_ms = (time.perf_counter() - core.t0) * 1000
        check("модель загружена", bool(st["model_loaded"]), load_ms,
              f"device={st['device']}, state={st['state']}")

        for cmd in READONLY:
            r, ms = c.call(cmd)
            check(cmd, bool(r["ok"]), ms, short(r.get("result")) if r["ok"] else r["error"])

        r, ms = c.call("cuda_check")
        res = r.get("result") or {}
        check("cuda_check", bool(r["ok"]), ms,
              f"ok={res.get('ok')}, {res.get('device')}, {res.get('gpu_name')}, "
              f"{res.get('vram_total_mb')} МБ, ошибка={res.get('error')}")
        for provider in ("openrouter", "anthropic"):
            r, ms = c.call("ai_key_status", {"provider": provider})
            res = r.get("result") or {}
            # маску ключа не печатаем
            check(f"ai_key_status {provider}", bool(r["ok"]), ms,
                  f"has_key={res.get('has_key')}" if r["ok"] else r["error"])

        # изменения — только во временной папке
        r, ms = c.call("set_settings", {"patch": {"theme": "dark", "ptt_key": "f13"}})
        ev = c.wait_event("settings", lambda d: d.get("theme") == "dark", timeout=5)
        check("set_settings", bool(r["ok"]) and ev["ptt_key"] == "f13", ms, "событие settings пришло")
        r, ms = c.call("set_settings", {"patch": {"insert_mode": "fast"}})
        check("set_settings (неверное)", not r["ok"], ms, r.get("error", "принято?!"))
        r, ms = c.call("draft_set", {"text": "Черновик дымового теста"})
        check("draft_set", bool(r["ok"]), ms, "")
        r, ms = c.call("no_such_command")
        check("неизвестная команда", not r["ok"], ms, r.get("error", ""))

        # язык интерфейса — на лету, без перезапуска ядра
        check("hello: ui_language", hello["data"].get("ui_language") in ("ru", "en"), 0,
              f"ui_language={hello['data'].get('ui_language')}")
        for lang in ("en", "ru"):
            r, ms = c.call("set_settings", {"patch": {"language": lang}})
            st = c.wait_event("state", lambda d, lang=lang: d.get("ui_language") == lang,
                              timeout=5)
            err, _ = c.call("no_such_command")
            styles, _ = c.call("styles_list")
            names = " ".join(x["name"] for x in styles.get("result") or [])
            text = f"{err.get('error', '')} {names}"
            ok = bool(r["ok"]) and st["ui_language"] == lang and (
                not CYRILLIC.search(text) if lang == "en" else bool(CYRILLIC.search(text)))
            check(f"язык {lang}", ok, ms, err.get("error", ""))

        if not args.no_record:
            r, ms = c.call("mic_monitor", {"on": True})
            n0 = len(c.events("level"))
            t_end = time.monotonic() + 1.0
            while time.monotonic() < t_end:
                try:
                    c.recv(0.2)
                except TimeoutError:
                    pass
            n = len(c.events("level")) - n0
            c.call("mic_monitor", {"on": False})
            check("mic_monitor", bool(r["ok"]) and n > 0, ms, f"событий level за 1 с: {n}")

            r, ms = c.call("test_record_start")
            check("test_record_start", bool(r["ok"]), ms, "" if r["ok"] else r["error"])
            time.sleep(1.0)
            r, ms = c.call("test_record_stop", timeout=120)
            res = r.get("result") or {}
            check("test_record_stop", bool(r["ok"]), ms,
                  f"аудио {res.get('audio_s')} с, ASR {res.get('asr_ms')} мс, "
                  f"язык {res.get('language')}, распознано символов: {len(res.get('text') or '')}"
                  if r["ok"] else r["error"])

        r, ms = c.call("stats_get")
        check("stats_get (повтор)", bool(r["ok"]), ms, "")

        t_quit = time.perf_counter()
        r, ms = c.call("quit")
        check("quit", bool(r["ok"]) and r.get("result") is None, ms, "")
        try:
            core.proc.wait(10)
            exit_ms = (time.perf_counter() - t_quit) * 1000
            check("выход ядра", core.proc.returncode == 0, exit_ms,
                  f"код {core.proc.returncode}")
        except subprocess.TimeoutExpired:
            check("выход ядра", False, 10000, "ядро не завершилось за 10 с")

        if not args.no_ui_pid_check:
            # ядро должно выйти вместе с «окном» (--ui-pid)
            dummy = subprocess.Popen([str(PY), "-c", "import time; time.sleep(4)"],
                                     creationflags=CREATE_NO_WINDOW)
            core2 = Core(appdata, dummy.pid)
            try:
                core2.wait_port()
                dummy.wait(10)
                t_gone = time.perf_counter()
                try:
                    core2.proc.wait(15)
                    check("выход по --ui-pid", core2.proc.returncode == 0,
                          (time.perf_counter() - t_gone) * 1000,
                          f"код {core2.proc.returncode}")
                except subprocess.TimeoutExpired:
                    check("выход по --ui-pid", False, 15000, "ядро не вышло за 15 с")
            finally:
                core2.close()
    except Exception as e:
        keep_logs = True
        failures.append(f"сбой: {type(e).__name__}: {e}")
    finally:
        core.close()

    print()
    print(f"{'Проверка':<28} {'Итог':<7} {'мс':>8}  Подробности")
    print("-" * 100)
    for name, status, ms, note in rows:
        print(f"{name:<28} {status:<7} {ms:>8.0f}  {note}")
    print()
    log_dir = appdata / "Rupor" / "logs"
    if failures or keep_logs:
        print("НЕ ПРОЙДЕНО:")
        for f in failures:
            print("  -", f)
        print(f"Логи ядра оставлены: {log_dir}")
        return 1
    shutil.rmtree(appdata, ignore_errors=True)
    print("Дымовой тест пройден, временная папка удалена.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
