// Открытые RDP-сессии и белый список рассылки (broadcast_targets) — один источник на окно:
// «Настройки → Вставка → Сессии для рассылки», подменю трея «Рассылка в RDP ▸» и диалог
// правил по названию окна. Окна RDP открываются и закрываются без событий ядра, поэтому
// главное окно перечитывает список раз в 15 с (pollRdp) и после каждого переключения.
import { useSyncExternalStore } from "react";
import { errorText } from "./hub";
import type { RdpWindow } from "./types";
import { backend } from "./ws";

export interface RdpSnapshot {
  windows: RdpWindow[] | null;
  loading: boolean;
  error: string | null;
}

let snap: RdpSnapshot = { windows: null, loading: false, error: null };
const listeners = new Set<() => void>();
let started = false;
let seq = 0;
let targetsSig: string | null = null;

function set(patch: Partial<RdpSnapshot>): void {
  snap = { ...snap, ...patch };
  for (const fn of [...listeners]) fn();
}

function start(): void {
  if (started) return;
  started = true;
  backend.onStatus((s) => {
    if (s === "open") reloadRdp();
  });
  // Белый список поменялся (здесь, в другом окне или в трее) — флажки included другие.
  backend.on("settings", (s) => {
    const sig = (s.broadcast_targets ?? []).map((k) => k.toLowerCase()).sort().join("\u0001");
    const changed = targetsSig !== null && sig !== targetsSig;
    targetsSig = sig;
    if (changed) reloadRdp();
  });
  if (backend.status() === "open") reloadRdp();
}

export function reloadRdp(): void {
  start();
  const my = ++seq;
  set({ loading: true });
  backend
    .call("rdp_windows")
    .then((windows) => {
      if (my === seq) set({ windows, loading: false, error: null });
    })
    .catch((e: unknown) => {
      if (my === seq) set({ loading: false, error: errorText(e) });
    });
}

/** Отметить/снять сессию. Ошибка — список перечитывается, исключение уходит вызывающему. */
export async function toggleRdp(key: string, included: boolean): Promise<void> {
  start();
  const k = key.toLowerCase();
  seq++;
  if (snap.windows) {
    set({ windows: snap.windows.map((w) => (w.key.toLowerCase() === k ? { ...w, included } : w)) });
  }
  try {
    await backend.call("rdp_toggle", { key, included });
  } finally {
    reloadRdp();
  }
}

/** Перечитывать список, пока окно живо (трей должен видеть новые сессии). */
export function pollRdp(periodMs = 15_000): () => void {
  start();
  const id = setInterval(() => {
    if (backend.status() === "open") reloadRdp();
  }, periodMs);
  return () => clearInterval(id);
}

function subscribe(fn: () => void): () => void {
  start();
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

function getSnapshot(): RdpSnapshot {
  return snap;
}

export function useRdpWindows(): RdpSnapshot {
  return useSyncExternalStore(subscribe, getSnapshot);
}

/** Сравнение ключей сессий — без учёта регистра, как в ядре. */
export function sameKey(a: string, b: string): boolean {
  return a.toLowerCase() === b.toLowerCase();
}

/** Куда ведёт уведомление «Не выбраны RDP-сессии для рассылки» (action open_settings_insert). */
export const RDP_SESSIONS_ROUTE = "settings/insert/sessions";
