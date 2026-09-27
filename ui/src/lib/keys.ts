// Имена клавиш хоткеев (как hotkeys.KEY_NAMES в ядре) и их понятные подписи.
import { t, tDyn } from "../i18n";

/**
 * Сочетания для клавиши диктовки (hotkeys.parse_ptt в ядре): держать оба модификатора.
 * Ctrl+Shift и Alt+Shift не предлагаем — это переключатели раскладки Windows.
 */
export const PTT_COMBOS: string[] = ["ctrl+win", "ctrl+alt"];

/** Модификаторы «любой стороны»: годятся для рассылки/команды, но не как одиночная клавиша диктовки. */
export const GENERIC_MODS: string[] = ["ctrl", "alt", "shift", "win"];

export const KEY_NAMES: string[] = [
  "ctrl",
  "alt",
  "shift",
  "win",
  "rctrl",
  "lctrl",
  "rshift",
  "lshift",
  "ralt",
  "lalt",
  "rwin",
  "lwin",
  "esc",
  "capslock",
  "scrolllock",
  "pause",
  "insert",
  ...Array.from({ length: 24 }, (_, i) => `f${i + 1}`),
];

const CODE_TO_NAME: Record<string, string> = {
  ControlRight: "rctrl",
  ControlLeft: "lctrl",
  ShiftRight: "rshift",
  ShiftLeft: "lshift",
  AltRight: "ralt",
  AltLeft: "lalt",
  MetaRight: "rwin",
  MetaLeft: "lwin",
  OSRight: "rwin",
  OSLeft: "lwin",
  Escape: "esc",
  CapsLock: "capslock",
  ScrollLock: "scrolllock",
  Pause: "pause",
  Insert: "insert",
};

/** KeyboardEvent → имя клавиши для settings.json (rctrl, f13, vk:0x41 …). */
export function eventToKeyName(e: KeyboardEvent): string | null {
  const direct = CODE_TO_NAME[e.code];
  if (direct) return direct;
  const f = /^F(\d{1,2})$/.exec(e.code);
  if (f) {
    const n = Number(f[1]);
    if (n >= 1 && n <= 24) return `f${n}`;
  }
  const vk = e.keyCode;
  if (vk > 0) return `vk:0x${vk.toString(16).padStart(2, "0")}`;
  return null;
}

function vkLabel(code: number): string {
  if (code >= 0x41 && code <= 0x5a) return String.fromCharCode(code);
  if (code >= 0x30 && code <= 0x39) return String.fromCharCode(code);
  if (code >= 0x60 && code <= 0x69) return t("keys.numpad", { n: code - 0x60 });
  return t("keys.vk", { code: `0x${code.toString(16).toUpperCase().padStart(2, "0")}` });
}

/** Сторона модификатора → общее имя: «lctrl» → «ctrl» (для сочетаний клавиши диктовки). */
const GENERIC_MOD: Record<string, string> = {
  lctrl: "ctrl",
  rctrl: "ctrl",
  lalt: "alt",
  ralt: "alt",
  lshift: "shift",
  rshift: "shift",
  lwin: "win",
  rwin: "win",
};
const MOD_ORDER = ["ctrl", "alt", "shift", "win"];

/**
 * Нажатые вместе клавиши → значение клавиши диктовки: одна клавиша — как есть («rctrl»),
 * несколько модификаторов — сочетание без сторон («ctrl+alt»). null — сочетание с
 * обычной клавишей (ядро такое для диктовки не примет).
 */
export function pressedToPtt(pressed: string[]): string | null {
  if (pressed.length === 1) return pressed[0] ?? null;
  const mods = new Set<string>();
  for (const k of pressed) {
    const g = GENERIC_MOD[k];
    if (!g) return null;
    mods.add(g);
  }
  // «левый + правый Ctrl» → одиночный общий модификатор: как клавиша диктовки он мешал бы
  // каждому Ctrl+C, поэтому такое не принимаем (как и ядро)
  if (mods.size < 2 || mods.size > 3) return null;
  return MOD_ORDER.filter((m) => mods.has(m)).join("+");
}

/** «Правый Ctrl», «F13», «Esc», «Ctrl + Alt» … */
export function keyLabel(name: string | null | undefined): string {
  if (!name) return t("keys.none");
  const n = name.trim().toLowerCase();
  if (n.includes("+")) return comboParts(n).map((p) => keyLabel(p)).join(" + ");
  if (/^f\d{1,2}$/.test(n)) return n.toUpperCase();
  if (/^[a-z0-9]$/.test(n)) return n.toUpperCase();
  if (n.startsWith("vk:")) {
    const code = Number(n.slice(3));
    return Number.isFinite(code) ? vkLabel(code) : name;
  }
  return tDyn(`keys.${n}`, name);
}

/** Строка хоткея из State.hotkeys может быть сочетанием «rctrl+rshift». */
export function comboParts(value: string): string[] {
  return value
    .split("+")
    .map((s) => s.trim())
    .filter(Boolean);
}

// ——— Сочетания «Вставить последнее» / «Скопировать последнее» (hotkeys.parse_chord в ядре) ———

/** Основные клавиши сочетаний, кроме букв, цифр и F1–F24 (как _CHORD_KEYS в ядре). */
const CHORD_CODE_TO_NAME: Record<string, string> = {
  Space: "space",
  Enter: "enter",
  NumpadEnter: "enter",
  Tab: "tab",
  Backspace: "backspace",
  Delete: "delete",
  Home: "home",
  End: "end",
  PageUp: "pageup",
  PageDown: "pagedown",
  ArrowLeft: "left",
  ArrowUp: "up",
  ArrowRight: "right",
  ArrowDown: "down",
  Insert: "insert",
  Escape: "esc",
  Pause: "pause",
  ScrollLock: "scrolllock",
};

const MODIFIER_CODES = new Set([
  "ControlLeft",
  "ControlRight",
  "AltLeft",
  "AltRight",
  "ShiftLeft",
  "ShiftRight",
  "MetaLeft",
  "MetaRight",
  "OSLeft",
  "OSRight",
]);

/**
 * KeyboardEvent → сочетание «ctrl+alt+shift+v» для settings.json.
 * null — нажат только модификатор или нет ни одного модификатора (ядро такое не примет).
 */
export function eventToChord(e: KeyboardEvent): string | null {
  if (MODIFIER_CODES.has(e.code)) return null;
  const mods: string[] = [];
  if (e.ctrlKey) mods.push("ctrl");
  if (e.altKey) mods.push("alt");
  if (e.shiftKey) mods.push("shift");
  if (e.metaKey) mods.push("win");
  if (!mods.length) return null;
  let main: string | null = null;
  const letter = /^Key([A-Z])$/.exec(e.code);
  const digit = /^Digit([0-9])$/.exec(e.code); // цифры цифрового блока — через vk:0x6N ниже
  const fn = /^F(\d{1,2})$/.exec(e.code);
  if (letter?.[1]) main = letter[1].toLowerCase();
  else if (digit?.[1]) main = digit[1];
  else if (fn?.[1] && Number(fn[1]) >= 1 && Number(fn[1]) <= 24) main = `f${fn[1]}`;
  else main = CHORD_CODE_TO_NAME[e.code] ?? (e.keyCode > 0 ? `vk:0x${e.keyCode.toString(16).padStart(2, "0")}` : null);
  return main ? [...mods, main].join("+") : null;
}
