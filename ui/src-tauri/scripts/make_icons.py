"""Генератор иконок Рупора.

Рисует исходник иконки приложения (1024×1024: скруглённый квадрат с градиентом акцента
#7c5cff и белым рупором) и иконки трея по состояниям (32×32).

Запуск (из корня проекта):
    .venv\\Scripts\\python ui\\src-tauri\\scripts\\make_icons.py
    npx --yes @tauri-apps/cli@2 icon ui\\src-tauri\\icons\\app-icon.png -o ui\\src-tauri\\icons
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

ICONS = Path(__file__).resolve().parent.parent / "icons"
SS = 4  # сглаживание: рисуем в 4 раза крупнее и уменьшаем

Color = tuple[int, int, int]


def _hex(c: str) -> Color:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _gradient(size: int, c1: Color, c2: Color) -> Image.Image:
    """Диагональный градиент от левого верхнего угла к правому нижнему."""
    small = 256
    img = Image.new("RGB", (small, small))
    px = img.load()
    assert px is not None
    for y in range(small):
        for x in range(small):
            t = (x + y) / (2 * (small - 1))
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(c1, c2))
    return img.resize((size, size), Image.Resampling.BICUBIC)


def _megaphone_layer(size: int, fill: tuple[int, int, int, int], waves: int = 2,
                    scale: float = 1.0, dx: float = 0, dy: float = 0,
                    tilt: float = 14) -> Image.Image:
    """Слой с рупором: рисуется в координатах 1024×1024 и поворачивается раструбом вверх."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 1024 * scale
    c = size / 2

    def p(x: float, y: float) -> tuple[float, float]:
        return c + (x - 512 + dx) * s, c + (y - 512 + dy) * s

    # мундштук
    x0, y0 = p(236, 458)
    x1, y1 = p(344, 566)
    d.rounded_rectangle((x0, y0, x1, y1), radius=30 * s, fill=fill)
    # ручка
    x0, y0 = p(372, 540)
    x1, y1 = p(440, 694)
    d.rounded_rectangle((x0, y0, x1, y1), radius=32 * s, fill=fill)
    # раструб
    d.polygon([p(330, 446), p(632, 304), p(632, 720), p(330, 578)], fill=fill)
    # кромка раструба — вытянутый эллипс
    x0, y0 = p(596, 292)
    x1, y1 = p(676, 732)
    d.ellipse((x0, y0, x1, y1), fill=fill)
    # звуковые волны
    width = max(1, round(38 * s))
    for rad in (118, 204)[:waves]:
        cx, cy = p(660, 512)
        rr = rad * s
        d.arc((cx - rr, cy - rr, cx + rr, cy + rr), start=-36, end=36, fill=fill, width=width)
        for ang in (-36, 36):
            a = math.radians(ang)
            mid = rr - width / 2
            ex, ey = cx + mid * math.cos(a), cy + mid * math.sin(a)
            cr = width / 2
            d.ellipse((ex - cr, ey - cr, ex + cr, ey + cr), fill=fill)
    return img.rotate(tilt, resample=Image.Resampling.BICUBIC, center=(c, c))


def app_icon(size: int = 1024) -> Image.Image:
    big = size * SS
    base = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    grad = _gradient(big, _hex("#9a82ff"), _hex("#5f3ff0")).convert("RGBA")
    mask = Image.new("L", (big, big), 0)
    m = 40 * big // 1024
    ImageDraw.Draw(mask).rounded_rectangle(
        (m, m, big - m - 1, big - m - 1), radius=230 * big // 1024, fill=255)
    base.paste(grad, (0, 0), mask)
    glyph = _megaphone_layer(big, (255, 255, 255, 255), waves=2, scale=0.98, dx=-26, dy=20)
    base = Image.alpha_composite(base, glyph)
    return base.resize((size, size), Image.Resampling.LANCZOS)


# Цветные значки трея — градиенты, как у иконки приложения (одноцветный серый терялся
# на тёмной панели задач)
TRAY: dict[str, tuple[str, str]] = {
    "idle": ("#9a82ff", "#5f3ff0"),        # фирменный фиолетовый — готов
    "recording": ("#ff6b6b", "#dc2626"),   # красный — запись
    "processing": ("#fbbf24", "#ea8a0c"),  # янтарный — распознавание / ИИ
    "paused": ("#b4b9c4", "#7d838f"),      # светло-серый — пауза
    "loading": ("#60a5fa", "#2563eb"),     # синий — загрузка модели / ядра
    "error": ("#f87171", "#b91c1c"),       # красный — ошибка
}


def tray_icon(colors: tuple[str, str], size: int = 32) -> Image.Image:
    big = size * SS * 4
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    pad = int(big * 0.03)
    grad = _gradient(big, _hex(colors[0]), _hex(colors[1])).convert("RGBA")
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle((pad, pad, big - pad, big - pad),
                                           radius=int(big * 0.24), fill=255)
    img.paste(grad, (0, 0), mask)
    img = Image.alpha_composite(
        img, _megaphone_layer(big, (255, 255, 255, 255), waves=1, scale=1.2, dx=-44, dy=34))
    return img.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    ICONS.mkdir(parents=True, exist_ok=True)
    app_icon().save(ICONS / "app-icon.png")
    tray = ICONS / "tray"
    tray.mkdir(exist_ok=True)
    for name, colors in TRAY.items():
        tray_icon(colors).save(tray / f"{name}.png")
    print(f"Готово: {ICONS / 'app-icon.png'} и {len(TRAY)} иконок трея в {tray}")


if __name__ == "__main__":
    main()
