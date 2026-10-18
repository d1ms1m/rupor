// Форматирование чисел, дат и длительностей по текущей локали (строки — из src/i18n).
import { formatNumber, getLocale, intlTag, t, tp, type Locale } from "../i18n";

// Форматтеры Intl — по одному на локаль и вид; создаются при первом обращении.
const fmtCache = new Map<string, Intl.DateTimeFormat | Intl.NumberFormat>();

function dateFmt(name: string, opts: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = `d:${getLocale()}:${name}`;
  let f = fmtCache.get(key) as Intl.DateTimeFormat | undefined;
  if (!f) {
    f = new Intl.DateTimeFormat(intlTag(), opts);
    fmtCache.set(key, f);
  }
  return f;
}

function numFmt(name: string, opts: Intl.NumberFormatOptions, locale: Locale | "fixed" = getLocale()): Intl.NumberFormat {
  const key = `n:${locale}:${name}`;
  let f = fmtCache.get(key) as Intl.NumberFormat | undefined;
  if (!f) {
    f = new Intl.NumberFormat(locale === "fixed" ? "en-US" : intlTag(locale), opts);
    fmtCache.set(key, f);
  }
  return f;
}

// Доллары — в обоих языках как в кабинете OpenRouter: «$12.34», «$0.0012» (точка, знак впереди).
const usdFmt = () => numFmt("usd", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 }, "fixed");
const usdSmallFmt = () =>
  numFmt("usdSmall", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 5 }, "fixed");
const usdTinyFmt = () => numFmt("usdTiny", { style: "currency", currency: "USD", maximumSignificantDigits: 2 }, "fixed");

/** Дробное число по локали: 1.5 → «1,5» / "1.5". */
export function fmtDecimal(n: number, maxDigits = 1): string {
  return numFmt(`dec${maxDigits}`, { maximumFractionDigits: maxDigits }).format(n);
}

export function fmtNum(n: number): string {
  return formatNumber(Math.round(n));
}

export function fmtTime(tsSec: number): string {
  // «09:05» / "9:05 AM"
  const hour = getLocale() === "ru" ? "2-digit" : "numeric";
  return dateFmt("time", { hour, minute: "2-digit" }).format(new Date(tsSec * 1000));
}

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

export function dayKey(tsSec: number): string {
  const d = new Date(tsSec * 1000);
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

export function fmtDayLabel(tsSec: number): string {
  const d = new Date(tsSec * 1000);
  const today = startOfDay(new Date());
  const day = startOfDay(d);
  const diff = Math.round((today - day) / 86_400_000);
  if (diff === 0) return t("time.today");
  if (diff === 1) return t("time.yesterday");
  return d.getFullYear() === new Date().getFullYear()
    ? dateFmt("day", { day: "numeric", month: "long" }).format(d)
    : dateFmt("dayYear", { day: "numeric", month: "long", year: "numeric" }).format(d);
}

/** "2026-09-24" → Date в локальной зоне. */
export function parseDate(s: string): Date {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y ?? 1970, (m ?? 1) - 1, d ?? 1);
}

/** «24 сент» / "Sep 24" — подписи оси графиков. */
export function fmtShortDate(s: string): string {
  const v = dateFmt("short", { day: "numeric", month: "short" }).format(parseDate(s));
  return getLocale() === "ru" ? v.replace(".", "") : v;
}

export function fmtWeekday(s: string): string {
  return dateFmt("weekday", { weekday: "short" }).format(parseDate(s));
}

export function fmtLongDate(s: string): string {
  return dateFmt("day", { day: "numeric", month: "long" }).format(parseDate(s));
}

export function fmtSeconds(sec: number): string {
  if (sec < 60) {
    const v = sec < 10 ? Math.round(sec * 10) / 10 : Math.round(sec);
    return t("time.sec", { n: fmtDecimal(v) });
  }
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return s ? t("time.minSec", { m, s }) : t("time.min", { n: m });
}

export function fmtMinutes(min: number): string {
  const total = Math.max(0, Math.round(min));
  if (total < 60) return t("time.min", { n: total });
  const h = Math.floor(total / 60);
  const m = total % 60;
  return m ? t("time.hourMin", { h: formatNumber(h), m }) : t("time.hour", { n: formatNumber(h) });
}

export function fmtMs(ms: number): string {
  if (ms < 1000) return t("time.ms", { n: Math.round(ms) });
  return t("time.sec", { n: fmtDecimal(Math.round(ms / 100) / 10) });
}

export function fmtUsd(v: number): string {
  return usdFmt().format(v);
}

export function fmtCost(v: number): string {
  return usdSmallFmt().format(v);
}

/**
 * Расход: «$0» / «$0.0012» / «$0.034» / «$0.84» / «$12.34». Мелкие суммы — с двумя
 * значащими цифрами (копейки за фразу не превращаются в «$0.00»).
 */
export function fmtSpend(v: number): string {
  if (!Number.isFinite(v) || v <= 0) return "$0";
  if (v >= 0.1) return usdFmt().format(v);
  return usdTinyFmt().format(v);
}

/** Токены: 950 → «950», 12 400 → «12 тыс.» / "12K", 1 240 000 → «1,2 млн» / "1.2M". */
export function fmtTokens(n: number): string {
  return n < 10_000 ? formatNumber(Math.round(n)) : numFmt("compact", { notation: "compact" }).format(n);
}

/**
 * Размер файлов в МБ по 10⁶ байт (как на Hugging Face и в model_recommend.size_mb): 484 →
 * «484 МБ», 1620 → «1,6 ГБ» / "1.6 GB", 3090 → «3,1 ГБ».
 */
export function fmtMb(mb: number): string {
  if (mb < 1000) return t("units.mb", { n: formatNumber(Math.max(1, Math.round(mb))) });
  return t("units.gb", { n: fmtDecimal(mb / 1000) });
}

/** «только что», «5 мин назад», «2 ч назад», иначе дата. */
export function fmtAgo(tsSec: number, nowMs = Date.now()): string {
  const sec = Math.max(0, nowMs / 1000 - tsSec);
  if (sec < 60) return t("time.justNow");
  if (sec < 3600) return t("time.minAgo", { n: Math.floor(sec / 60) });
  if (sec < 86_400) return t("time.hourAgo", { n: Math.floor(sec / 3600) });
  const label = fmtDayLabel(tsSec);
  // «проверено вчера» / "checked yesterday"; названия месяцев в английском — с заглавной
  return getLocale() === "ru" || label === t("time.yesterday") ? label.toLowerCase() : label;
}

export function fmtClock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function fmtWords(n: number): string {
  return tp("units.words", n);
}

export function countWords(text: string): number {
  return text.split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w)).length;
}

/** "telegram.exe" → "Telegram" */
export function appName(process: string): string {
  const base = process.replace(/\.exe$/i, "");
  const known: Record<string, string> = {
    mstsc: "RDP",
    code: "VS Code",
    "code - insiders": "VS Code Insiders",
    winword: "Word",
    excel: "Excel",
    msedge: "Edge",
    olk: "Outlook",
    rdcman: "RDCMan",
    mremoteng: "mRemoteNG",
  };
  const k = known[base.toLowerCase()];
  if (k) return k;
  return base ? base.charAt(0).toUpperCase() + base.slice(1) : process;
}

export function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/**
 * Название окна для сравнения — как `config.fold_title` ядра: без учёта регистра и «ё».
 * toUpperCase().toLowerCase() ближе к casefold Питона, чем один toLowerCase («ß» → «ss»).
 */
export function foldTitle(title: string): string {
  // \u0451 = «ё», \u0435 = «е» (кириллица в строках кода запрещена — check:i18n)
  return title.trim().toUpperCase().toLowerCase().replace(/\u0451/g, "\u0435");
}

/** Ключ правила по названию окна — как `config.title_rule_key`: процесс + название, дубли запрещены. */
export function titleRuleKey(r: { process: string; title: string }): string {
  return `${r.process.trim().toLowerCase()}\u0001${foldTitle(r.title)}`;
}
