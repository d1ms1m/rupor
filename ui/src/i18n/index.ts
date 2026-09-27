// Строки интерфейса: ru.json и en.json (одинаковые ключи — проверяет npm run check:i18n).
// t(key, params) — подстановка {name}; tp(key, n) — множественное число по правилам локали.
//
// Язык переключается на лету: setLocale() меняет текущий словарь и будит подписчиков
// (useLocale() в корне окна перерисовывает всё дерево). Откуда берётся язык:
// settings.language ("ru" | "en") → иначе State.ui_language (ядро разрешило "system" по языку
// Windows) → до hello — кэш прошлого запуска или navigator.language.
import { useSyncExternalStore } from "react";
import en from "./en.json";
import ru from "./ru.json";

export type Locale = "ru" | "en";
export const LOCALES: readonly Locale[] = ["ru", "en"];

/** Самоназвания языков — всегда на своём языке (выбор языка в настройках и мастере). */
export const NATIVE_NAMES: Record<Locale, string> = { ru: "Русский", en: "English" };

type Dict = typeof ru;
type Join<K extends string, P extends string> = `${K}.${P}`;

type PluralNode = { one: string; few: string; many: string };

/** Все ключи-листья вида "home.title". */
type Leaves<T> = {
  [K in keyof T & string]: T[K] extends string
    ? K
    : T[K] extends readonly unknown[]
      ? never
      : T[K] extends object
        ? Join<K, Leaves<T[K]>>
        : never;
}[keyof T & string];

/** Ключи узлов с формами множественного числа (one/few/many в ru.json). */
type Plurals<T> = {
  [K in keyof T & string]: T[K] extends PluralNode
    ? K
    : T[K] extends string
      ? never
      : T[K] extends object
        ? Join<K, Plurals<T[K]>>
        : never;
}[keyof T & string];

export type TKey = Leaves<Dict>;
export type PKey = Plurals<Dict>;
export type Params = Record<string, string | number>;

// en.json устроен так же, только формы множественного числа другие (one/other),
// поэтому словари хранятся как unknown; паритет ключей проверяет scripts/check-i18n.mjs.
const DICTS: Record<Locale, unknown> = { ru, en };

/** Языки системы по порядку предпочтения (в WebView2 — язык интерфейса Windows). */
function systemTags(): string[] {
  if (typeof navigator === "undefined") return [];
  return [...(navigator.languages ?? []), navigator.language].filter((l): l is string => typeof l === "string" && l !== "");
}

function canonTag(l: string): string | null {
  try {
    return Intl.getCanonicalLocales(l)[0] ?? null;
  } catch {
    return null;
  }
}

/** У Intl есть данные именно для этого тега, а не только для языка без региона. */
function hasRegionData(tag: string): boolean {
  try {
    return new Intl.DateTimeFormat(tag).resolvedOptions().locale.toLowerCase() === tag.toLowerCase();
  } catch {
    return false;
  }
}

/**
 * Тег для английского интерфейса: даты, время и числа — по привычкам пользователя, а не
 * всегда американские. Решает основной язык системы (первый в списке):
 *  - английский — он сам, если с регионом (en-GB, en-AU…), иначе первый en-XX из списка, иначе en-US;
 *  - другой (русская Windows, выбран English) — английский для его региона (de-DE → en-DE),
 *    если у Intl есть такие данные; иначе по часам системы: 24-часовые (ru, uk, de…) — en-GB
 *    («21:05», «24 Sept»), 12-часовые — en-US («9:05 PM», "Sep 24"). en-US вторым языком
 *    у русской Windows (обычное дело) привычек пользователя не меняет.
 */
export function englishTag(tags: readonly string[] = systemTags()): string {
  const list = tags.map(canonTag).filter((c): c is string => c !== null);
  const first = list[0];
  if (!first) return "en-US";
  const enRegional = (c: string) => /^en-[A-Z]{2}$/.test(c) && hasRegionData(c);
  if (first.split("-")[0] === "en") return list.find((c) => c.split("-")[0] === "en" && enRegional(c)) ?? "en-US";
  let region: string | undefined;
  try {
    region = new Intl.Locale(first).maximize().region;
  } catch {
    region = undefined;
  }
  if (region === "US") return "en-US";
  if (region && /^[A-Z]{2}$/.test(region) && hasRegionData(`en-${region}`)) return `en-${region}`;
  try {
    const hc = new Intl.DateTimeFormat(first, { hour: "numeric" }).resolvedOptions().hourCycle;
    return hc === "h23" || hc === "h24" ? "en-GB" : "en-US";
  } catch {
    return "en-US";
  }
}

const TAGS: Record<Locale, string> = { ru: "ru-RU", en: englishTag() };
const CACHE_KEY = "rupor.locale";
const SYSTEM_KEY = "rupor.systemLocale";

function isLocale(v: unknown): v is Locale {
  return v === "ru" || v === "en";
}

function storageGet(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function storageSet(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // нет доступа к хранилищу — просто не запомним
  }
}

/**
 * Язык по языку системы — как ядро разрешает language="system": русский для
 * ru/be/uk/kk, иначе английский. В WebView2 navigator.language — язык интерфейса Windows.
 */
export function navigatorLocale(): Locale {
  if (typeof navigator === "undefined") return "en";
  const first = [...(navigator.languages ?? []), navigator.language].find((l) => typeof l === "string" && l) ?? "en";
  const base = first.toLowerCase().split(/[-_]/)[0] ?? "en";
  return ["ru", "be", "uk", "kk"].includes(base) ? "ru" : "en";
}

/** ?lang=en|ru в адресе — демо-режим и проверки в браузере. */
export function urlLocale(): Locale | null {
  if (typeof window === "undefined") return null;
  const q = new URLSearchParams(window.location.search).get("lang");
  return isLocale(q) ? q : null;
}

function initialLocale(): Locale {
  const q = urlLocale();
  if (q) return q;
  const cached = storageGet(CACHE_KEY);
  if (isLocale(cached)) return cached;
  return navigatorLocale();
}

let current: Locale = initialLocale();
let dict: unknown = DICTS[current];
let pluralRules = new Intl.PluralRules(TAGS[current]);
let numberFmt = new Intl.NumberFormat(TAGS[current]);
const listeners = new Set<() => void>();

function applyDocument(l: Locale): void {
  if (typeof document !== "undefined") document.documentElement.lang = l;
}
applyDocument(current);

export function getLocale(): Locale {
  return current;
}

/** BCP 47 для Intl: "ru-RU" / английский по региону системы ("en-US", "en-GB"…, см. englishTag). */
export function intlTag(l: Locale = current): string {
  return TAGS[l];
}

/**
 * Название языка на текущем языке интерфейса — для текста фраз: «(сейчас русский)»,
 * "(currently Russian)". Самоназвания для выбора языка — NATIVE_NAMES.
 */
export function languageName(l: Locale, inLocale: Locale = current): string {
  try {
    return new Intl.DisplayNames([TAGS[inLocale]], { type: "language" }).of(l) ?? NATIVE_NAMES[l];
  } catch {
    return NATIVE_NAMES[l];
  }
}

/** Сменить язык интерфейса на лету (без перезагрузки окна). */
export function setLocale(l: Locale): void {
  if (!isLocale(l) || l === current) return;
  current = l;
  dict = DICTS[l];
  pluralRules = new Intl.PluralRules(TAGS[l]);
  numberFmt = new Intl.NumberFormat(TAGS[l]);
  applyDocument(l);
  storageSet(CACHE_KEY, l);
  for (const fn of [...listeners]) fn();
}

export function subscribeLocale(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

/** Текущий язык; компонент перерисуется при смене. */
export function useLocale(): Locale {
  return useSyncExternalStore(subscribeLocale, getLocale, getLocale);
}

/**
 * Какой язык показывать: явный выбор в настройках важнее, "system" — как разрешило ядро
 * (State.ui_language). null — ни того, ни другого (старое ядро): язык не трогаем.
 */
export function resolveLocale(pref: string | null | undefined, uiLanguage: string | null | undefined): Locale | null {
  if (isLocale(pref)) return pref;
  if (isLocale(uiLanguage)) return uiLanguage;
  return null;
}

/**
 * Применить язык из настроек и State. Запоминает, как ядро разрешает "system" (язык
 * Windows), — для подписи «Системный · Русский» и выбора языка в мастере.
 */
export function syncLocale(pref: string | null | undefined, uiLanguage: string | null | undefined): void {
  if (pref === "system" && isLocale(uiLanguage)) storageSet(SYSTEM_KEY, uiLanguage);
  const l = resolveLocale(pref, uiLanguage);
  if (l) setLocale(l);
}

/**
 * Язык Windows. При language="system" его прямо сейчас сообщает ядро (State.ui_language);
 * иначе — как ядро разрешило его в прошлый раз, иначе по navigator.language.
 */
export function systemLocale(pref?: string | null, uiLanguage?: string | null): Locale {
  if (pref === "system" && isLocale(uiLanguage)) return uiLanguage;
  const v = storageGet(SYSTEM_KEY);
  return isLocale(v) ? v : navigatorLocale();
}

function lookup(key: string): unknown {
  let node: unknown = dict;
  for (const part of key.split(".")) {
    if (node && typeof node === "object" && part in node) {
      node = (node as Record<string, unknown>)[part];
    } else {
      return undefined;
    }
  }
  return node;
}

function fill(s: string, params?: Params): string {
  if (!params) return s;
  return s.replace(/\{(\w+)\}/g, (m, name: string) => (name in params ? String(params[name]) : m));
}

export function t(key: TKey, params?: Params): string {
  const v = lookup(key);
  return typeof v === "string" ? fill(v, params) : key;
}

/** Строка на заданном языке, не на текущем (карточки выбора языка: «Интерфейс на русском»). */
export function tIn(l: Locale, key: TKey, params?: Params): string {
  let node: unknown = DICTS[l];
  for (const part of key.split(".")) {
    node = node && typeof node === "object" ? (node as Record<string, unknown>)[part] : undefined;
  }
  return typeof node === "string" ? fill(node, params) : key;
}

/** Для ключей, собранных из данных (например, `state.${name}`) — с запасным значением. */
export function tDyn(key: string, fallback: string, params?: Params): string {
  const v = lookup(key);
  return typeof v === "string" ? fill(v, params) : fallback;
}

/**
 * Множественное число: tp("units.words", 5) → «5 слов» / "5 words". Форма — по
 * Intl.PluralRules текущей локали (ru: one/few/many/other, en: one/other). {n} — число.
 */
export function tp(key: PKey, n: number, params?: Params): string {
  const node = lookup(key);
  if (!node || typeof node !== "object") return String(n);
  const forms = node as Record<string, string | undefined>;
  const s = forms[pluralRules.select(n)] ?? forms.other ?? forms.many ?? "";
  return fill(s, { n: formatNumber(n), ...params });
}

/** Число с разделителями разрядов по локали: «48 214» / "48,214". */
export function formatNumber(n: number): string {
  return numberFmt.format(n);
}
