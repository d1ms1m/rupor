// Тема (system/dark/light), акцентный цвет и эффект Mica.
import { inTauri, setWindowTheme } from "./tauri";
import type { ThemeMode } from "./types";

export const DEFAULT_ACCENT = "#7c5cff";

/** Палитра акцентов (подписи — в src/i18n, settings.accents.*). */
export const ACCENT_PRESETS = [
  { id: "violet", color: "#7c5cff" },
  { id: "blue", color: "#3e7bfa" },
  { id: "teal", color: "#0fa5a0" },
  { id: "green", color: "#2f9e68" },
  { id: "amber", color: "#e8930c" },
  { id: "orange", color: "#f06418" },
  { id: "pink", color: "#e5487a" },
  { id: "graphite", color: "#5f5f6e" },
] as const;

const CACHE_KEY = "rupor.theme";

export function normalizeAccent(c: string | null | undefined): string {
  return c && /^#[0-9a-f]{6}$/i.test(c) ? c.toLowerCase() : DEFAULT_ACCENT;
}

function luminance(hex: string): number {
  const n = parseInt(hex.slice(1), 16);
  const ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * (ch[0] ?? 0) + 0.7152 * (ch[1] ?? 0) + 0.0722 * (ch[2] ?? 0);
}

export function accentForeground(hex: string): string {
  return luminance(hex) > 0.5 ? "#101014" : "#ffffff";
}

export function systemDark(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function isDark(theme: ThemeMode): boolean {
  return theme === "dark" || (theme === "system" && systemDark());
}

let lastWindowTheme: string | undefined;

export function applyTheme(theme: ThemeMode, accentRaw: string): void {
  const accent = normalizeAccent(accentRaw);
  const root = document.documentElement;
  root.classList.toggle("dark", isDark(theme));
  root.style.setProperty("--c-accent", accent);
  root.style.setProperty("--c-accent-fg", accentForeground(accent));
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify({ theme, accent }));
  } catch {
    // хранилище недоступно — не страшно
  }
  const wt = theme === "system" ? "system" : theme;
  if (wt !== lastWindowTheme) {
    lastWindowTheme = wt;
    void setWindowTheme(theme === "system" ? null : theme);
  }
}

/** Тема из прошлого запуска — чтобы не мигать светлым фоном до ответа ядра. */
export function applyCachedTheme(): ThemeMode {
  let theme: ThemeMode = "system";
  let accent = DEFAULT_ACCENT;
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (raw) {
      const v = JSON.parse(raw) as { theme?: ThemeMode; accent?: string };
      if (v.theme === "dark" || v.theme === "light" || v.theme === "system") theme = v.theme;
      accent = normalizeAccent(v.accent);
    }
  } catch {
    // нет кэша
  }
  const root = document.documentElement;
  root.classList.toggle("dark", isDark(theme));
  root.style.setProperty("--c-accent", accent);
  root.style.setProperty("--c-accent-fg", accentForeground(accent));
  return theme;
}

export function onSystemThemeChange(fn: () => void): () => void {
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  mq.addEventListener("change", fn);
  return () => mq.removeEventListener("change", fn);
}

/** Mica доступна в Tauri на Windows 11 (platformVersion ≥ 13). */
export async function enableMicaIfSupported(): Promise<boolean> {
  if (!inTauri()) return false;
  let win11 = false;
  try {
    const uad = (navigator as Navigator & {
      userAgentData?: { getHighEntropyValues(h: string[]): Promise<{ platform?: string; platformVersion?: string }> };
    }).userAgentData;
    if (uad) {
      const v = await uad.getHighEntropyValues(["platformVersion"]);
      win11 = Number((v.platformVersion ?? "0").split(".")[0]) >= 13;
    }
  } catch {
    win11 = false;
  }
  document.documentElement.classList.toggle("mica", win11);
  return win11;
}
