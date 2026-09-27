"""Тестовое окно-приёмник (отдельный процесс): поле ввода, содержимое каждые 100 мс
пишется в файл argv[1]. Используется вместо Блокнота, чтобы не трогать чужие документы."""
from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

out = Path(sys.argv[1])
root = tk.Tk()
root.title("Rupor test target")
root.geometry("600x300+200+200")
text = tk.Text(root, font=("Segoe UI", 12))
text.pack(fill="both", expand=True)


def ctrl_key(e: tk.Event) -> str | None:  # type: ignore[type-arg]
    # Tk при русской раскладке не распознаёт Ctrl+V — ловим по коду клавиши
    if e.keycode == 86 and e.keysym.lower() != "v":
        text.event_generate("<<Paste>>")
        return "break"
    return None


text.bind("<Control-KeyPress>", ctrl_key)


def dump() -> None:
    out.write_text(text.get("1.0", "end-1c"), encoding="utf-8")
    root.after(100, dump)


root.after(100, dump)
root.lift()
root.attributes("-topmost", True)
root.after(300, lambda: (root.focus_force(), text.focus_set()))
root.mainloop()
