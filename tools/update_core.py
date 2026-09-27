"""Быстрое обновление только ядра в установленном Рупоре (без переустановки интерфейса):
остановить Рупор → скопировать dist/rupor-core в %LOCALAPPDATA%\\Рупор\\core → запустить.

Запускать вне песочницы упакованных приложений (двойным щелчком / через Проводник).
Журнал — %TEMP%\\rupor_install.log."""
from __future__ import annotations

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
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def main() -> int:
    src = ROOT / "dist" / "rupor-core"
    app = Path(os.environ["LOCALAPPDATA"]) / "Рупор"
    dst = app / "core"
    if not (src / "rupor-core.exe").exists() or not (app / "rupor.exe").exists():
        say(f"Нет {src} или установленного Рупора в {app}")
        return 1
    subprocess.run(["taskkill", "/IM", "rupor.exe", "/T", "/F"], capture_output=True)
    for _ in range(20):
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq rupor-core.exe"],
                           capture_output=True, text=True, encoding="cp866", errors="replace")
        if "rupor-core.exe" not in r.stdout:
            break
        time.sleep(0.5)
    tmp = app / "core.new"
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(src, tmp)
    old = app / "core.old"
    shutil.rmtree(old, ignore_errors=True)
    dst.rename(old)
    tmp.rename(dst)
    shutil.rmtree(old, ignore_errors=True)
    say(f"Ядро обновлено: {dst}")
    exe = app / "rupor.exe"
    subprocess.Popen([str(exe)], cwd=str(app), creationflags=0x00000008 | 0x00000200,
                     close_fds=True)
    say("Рупор запущен")
    return 0


if __name__ == "__main__":
    sys.exit(main())
