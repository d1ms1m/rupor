"""Установка Рупора на этой машине из свежей сборки: библиотеки cuBLAS берутся из .venv
(чтобы не качать 0,55 ГБ заново), затем тихая установка NSIS и запуск.

Запускать через install-rupor.cmd двойным щелчком (или из Проводника), а не из окружения
упакованного (MSIX) приложения: иначе Windows перенаправит AppData в песочницу этого
приложения. Журнал — %TEMP%\\rupor_install.log.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = Path(tempfile.gettempdir()) / "rupor_install.log"


def say(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def copy_cublas() -> None:
    src = ROOT / ".venv" / "Lib" / "site-packages" / "nvidia" / "cublas" / "bin"
    dst = Path(os.environ["LOCALAPPDATA"]) / "Rupor" / "cuda"
    if not src.is_dir():
        say("В .venv нет cuBLAS — Рупор предложит скачать его сам")
        return
    dst.mkdir(parents=True, exist_ok=True)
    files = []
    for f in sorted(src.glob("*.dll")):
        target = dst / f.name
        if not target.exists() or target.stat().st_size != f.stat().st_size:
            shutil.copy2(f, target)
        files.append({"name": f.name, "size": target.stat().st_size})
    marker = dst / "nvidia-cublas-cu12-12.9.2.10.done.json"
    marker.write_text(json.dumps({"name": "nvidia-cublas-cu12", "version": "12.9.2.10",
                                  "files": files}, ensure_ascii=False, indent=1),
                      encoding="utf-8")
    say(f"cuBLAS: {len(files)} DLL в {dst}")


def stop_running() -> None:
    """Установщик не заменит запущенный rupor.exe — останавливаем Рупор (с ядром)."""
    r = subprocess.run(["taskkill", "/IM", "rupor.exe", "/T", "/F"], capture_output=True)
    if r.returncode == 0:
        say("Запущенный Рупор остановлен")
        time.sleep(1.5)


def reset_first_run() -> None:
    """--first-run: снова пройти первый запуск (автозапуск, проверка модели и CUDA)."""
    p = Path(os.environ["APPDATA"]) / "Rupor" / "settings.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    data["first_run_done"] = False
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    say("first_run_done сброшен")


def main() -> int:
    say(f"Установка Рупора; LOCALAPPDATA={os.environ.get('LOCALAPPDATA')}")
    stop_running()
    if "--first-run" in sys.argv:
        reset_first_run()
    if "Packages" in (os.environ.get("LOCALAPPDATA") or "") or \
            "Packages" in str(Path(os.environ.get("LOCALAPPDATA", "")).resolve()):
        say("ВНИМАНИЕ: похоже на песочницу упакованного приложения")
    copy_cublas()
    setups = sorted((ROOT / "ui" / "src-tauri" / "target" / "release" / "bundle" / "nsis")
                    .glob("*-setup.exe"), key=lambda p: p.stat().st_mtime)
    if not setups:
        say("Установщик не найден — сначала build.cmd")
        return 1
    setup = setups[-1]
    say(f"Запускаю {setup.name} /S")
    rc = subprocess.run([str(setup), "/S"], timeout=600).returncode
    say(f"Установщик завершился с кодом {rc}")
    exe = Path(os.environ["LOCALAPPDATA"]) / "Рупор" / "rupor.exe"
    for _ in range(30):
        if exe.exists():
            break
        time.sleep(1)
    if not exe.exists():
        say(f"Не найден {exe}")
        return 1
    subprocess.Popen([str(exe)], cwd=str(exe.parent),
                     creationflags=0x00000008 | 0x00000200, close_fds=True)
    say(f"Рупор запущен: {exe}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
