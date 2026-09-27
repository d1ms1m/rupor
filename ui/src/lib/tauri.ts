// Обёртки над Tauri API. Вне Tauri (обычный браузер) все функции безопасны:
// команды тихо ничего не делают, подписки возвращают пустую отписку.
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import type { CoreStateName, InsertMode, UiLanguage } from "./types";

export function inTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export interface BackendInfo {
  port: number;
  token: string;
}

export async function backendInfo(): Promise<BackendInfo> {
  const info = await invoke<BackendInfo>("backend_info");
  return { port: Number(info.port), token: String(info.token) };
}

export interface TrayInfo {
  state: CoreStateName;
  paused: boolean;
  insert_mode: InsertMode;
  style: string;
  /** Подменю «Стиль» в трее: [{id, name}] из styles_list. */
  styles?: { id: string; name: string }[];
  /**
   * Неактивная строка меню «ИИ: сегодня $0.03 · баланс $12.34»; null — ИИ выключен,
   * строки нет. Интерфейс присылает поле всегда.
   */
  ai_line?: string | null;
  /**
   * Подменю «Рассылка в RDP ▸» с флажками; [] — пункт «Нет открытых RDP-сессий».
   * Клик → tray-action "rdp:<key>" (key как пришёл). null — список ещё не загружен.
   */
  rdp?: TrayRdpItem[] | null;
  /**
   * Все строки меню трея и подсказки значка на языке интерфейса. Пока UI не прислал
   * labels, оболочка берёт встроенные строки по языку Windows.
   */
  labels?: TrayLabels;
}

/**
 * Строки трея (ключи — snake_case, как их разбирает Rust, tray::TrayLabels). Пустой или
 * недостающий ключ — встроенная подпись оболочки на языке lang.
 */
export interface TrayLabels {
  /** Язык интерфейса: на нём встроенные подписи и сообщения самой оболочки. */
  lang: UiLanguage;
  /** Название программы: «Рупор: готов», подсказка «Рупор — запись». */
  app: string;
  status_loading: string;
  status_idle: string;
  status_recording: string;
  status_hands_free: string;
  status_processing: string;
  status_ai: string;
  status_paused: string;
  status_error: string;
  /** Состояния, известные только оболочке (ядро ещё не подключилось или упало). */
  status_starting: string;
  status_restarting: string;
  status_failed: string;
  status_already_running: string;
  pause: string;
  insert_mode: string;
  mode_auto: string;
  mode_type: string;
  mode_clipboard: string;
  style: string;
  last_insert: string;
  rdp: string;
  rdp_empty: string;
  open: string;
  quit: string;
}

export interface TrayRdpItem {
  key: string;
  title: string;
  included: boolean;
}

/**
 * Вне Tauri (демо ?mock=1, проверки в браузере) трея нет: последнее содержимое меню лежит в
 * window.__ruporTray, а window.__ruporTrayAction(id) имитирует пункт меню (tray-action).
 */
interface TrayDebug {
  __ruporTray?: TrayInfo;
  __ruporTrayAction?: (id: string) => void;
}

export async function updateTray(info: TrayInfo): Promise<void> {
  if (!inTauri()) {
    (window as unknown as TrayDebug).__ruporTray = info;
    return;
  }
  try {
    // Rust разбирает тело вызова целиком (tray::TrayUpdate), ключи — snake_case, как в
    // контракте. Нет ключа ai_line/rdp — пункт не меняется, null — скрывается.
    await invoke("update_tray", { ...info });
  } catch (e) {
    console.warn("update_tray", e);
  }
}

export async function relaunchAdmin(): Promise<void> {
  if (!inTauri()) return;
  await invoke("relaunch_admin");
}

export async function showMain(route?: string): Promise<void> {
  if (!inTauri()) return;
  try {
    await invoke("show_main", route ? { route } : {});
  } catch (e) {
    console.warn("show_main", e);
  }
}

/** Вернуть пилюлю вниз по центру основного монитора (Rust). */
export async function resetPillPosition(): Promise<void> {
  if (!inTauri()) return;
  await invoke("reset_pill_position");
}

export async function quitApp(): Promise<void> {
  if (!inTauri()) {
    window.close();
    return;
  }
  await invoke("quit_app");
}

/** Подписка на событие Tauri с синхронной отпиской (listen асинхронный). */
export function onTauriEvent<T>(name: string, fn: (payload: T) => void): () => void {
  if (!inTauri()) return () => {};
  let disposed = false;
  let unlisten: (() => void) | null = null;
  listen<T>(name, (ev) => fn(ev.payload))
    .then((u) => {
      if (disposed) u();
      else unlisten = u;
    })
    .catch((e: unknown) => console.warn("listen", name, e));
  return () => {
    disposed = true;
    if (unlisten) unlisten();
  };
}

/**
 * Видно ли окно пользователю. Закрытие главного окна в Tauri — это window.hide() (в трей),
 * а WebView2 при этом остаётся «видимым»: document.visibilityState не меняется и
 * visibilitychange не приходит. Поэтому в Tauri раз в periodMs спрашиваем у окна
 * isVisible / isMinimized. Вне Tauri хватает visibilitychange.
 * fn вызывается при каждом изменении (первый раз — сразу после проверки).
 */
export function watchWindowShown(fn: (shown: boolean) => void, periodMs = 1000): () => void {
  const docShown = () => document.visibilityState === "visible";
  if (!inTauri()) {
    const sync = () => fn(docShown());
    sync();
    document.addEventListener("visibilitychange", sync);
    return () => document.removeEventListener("visibilitychange", sync);
  }
  let stopped = false;
  let last: boolean | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  const emit = (v: boolean) => {
    if (stopped || v === last) return;
    last = v;
    fn(v);
  };
  const tick = async () => {
    let shown = docShown();
    if (shown) {
      try {
        const { getCurrentWindow } = await import("@tauri-apps/api/window");
        const w = getCurrentWindow();
        shown = (await w.isVisible()) && !(await w.isMinimized());
      } catch {
        // нет прав на API окна — остаётся только document.visibilityState
      }
    }
    if (stopped) return;
    emit(shown);
    timer = setTimeout(() => void tick(), periodMs);
  };
  const onVis = () => {
    if (!docShown()) emit(false);
  };
  document.addEventListener("visibilitychange", onVis);
  void tick();
  return () => {
    stopped = true;
    if (timer) clearTimeout(timer);
    document.removeEventListener("visibilitychange", onVis);
  };
}

export function onTrayAction(fn: (id: string) => void): () => void {
  if (!inTauri()) {
    const w = window as unknown as TrayDebug;
    w.__ruporTrayAction = fn;
    return () => {
      if (w.__ruporTrayAction === fn) delete w.__ruporTrayAction;
    };
  }
  return onTauriEvent<{ id: string } | string>("tray-action", (p) => {
    fn(typeof p === "string" ? p : p.id);
  });
}

export function onCoreRestarted(fn: () => void): () => void {
  return onTauriEvent<unknown>("core-restarted", () => fn());
}

export function onNavigate(fn: (route: string) => void): () => void {
  return onTauriEvent<{ route: string } | string>("navigate", (p) => {
    fn(typeof p === "string" ? p : p.route);
  });
}

/** Автозапуск (plugin-autostart). Вне Tauri — null (недоступно). */
export async function autostartEnabled(): Promise<boolean | null> {
  if (!inTauri()) return null;
  try {
    const m = await import("@tauri-apps/plugin-autostart");
    return await m.isEnabled();
  } catch (e) {
    console.warn("autostart", e);
    return null;
  }
}

export async function setAutostart(on: boolean): Promise<boolean> {
  if (!inTauri()) return false;
  const m = await import("@tauri-apps/plugin-autostart");
  if (on) await m.enable();
  else await m.disable();
  // Выбор запоминаем: при старте оболочка восстанавливает автозапуск, только если он включён
  const { call } = await import("./ws");
  await call("set_settings", { patch: { autostart: on } }).catch(() => undefined);
  return m.isEnabled();
}

/**
 * Заголовок окна («Рупор» / "Rupor") — на языке интерфейса. Вне Tauri — только
 * document.title. Нет разрешения на setTitle (старая оболочка) — тихо ничего.
 */
export async function setWindowTitle(title: string): Promise<void> {
  if (typeof document !== "undefined") document.title = title;
  if (!inTauri()) return;
  try {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    await getCurrentWindow().setTitle(title);
  } catch {
    // заголовок не главное: окно пилюли без рамки, а у main он уже стоит из tauri.conf.json
  }
}

/** Тема окна (влияет на оттенок Mica). null — как в системе. */
export async function setWindowTheme(theme: "light" | "dark" | null): Promise<void> {
  if (!inTauri()) return;
  try {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    await getCurrentWindow().setTheme(theme);
  } catch (e) {
    console.warn("setTheme", e);
  }
}
