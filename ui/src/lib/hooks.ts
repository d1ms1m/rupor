import { useCallback, useEffect, useRef, useState, type DependencyList } from "react";
import { errorText } from "./hub";
import { watchWindowShown } from "./tauri";
import { backend } from "./ws";
import type { ConnStatus, EventMap, EventName } from "./types";

/** Подписка на событие ядра; обработчик всегда актуальный. */
export function useEvent<E extends EventName>(event: E, fn: (data: EventMap[E]) => void): void {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => backend.on(event, (d) => ref.current(d)), [event]);
}

export function useConnStatus(): ConnStatus {
  const [s, setS] = useState<ConnStatus>(backend.status());
  useEffect(() => {
    setS(backend.status());
    return backend.onStatus(setS);
  }, []);
  return s;
}

export interface Loadable<T> {
  data: T | undefined;
  loading: boolean;
  error: string | null;
  reload: () => void;
  setData: (fn: (prev: T | undefined) => T | undefined) => void;
}

/** Загрузка данных из ядра; повторяется при переподключении. */
export function useLoad<T>(fn: () => Promise<T>, deps: DependencyList = []): Loadable<T> {
  const [data, setDataState] = useState<T | undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const status = useConnStatus();
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    if (status !== "open") return;
    let alive = true;
    setLoading(true);
    fnRef
      .current()
      .then((d) => {
        if (!alive) return;
        setDataState(d);
        setError(null);
      })
      .catch((e: unknown) => {
        if (alive) setError(errorText(e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [status, tick, ...deps]);

  const reload = useCallback(() => setTick((x) => x + 1), []);
  const setData = useCallback((f: (prev: T | undefined) => T | undefined) => setDataState(f), []);
  return { data, loading, error, reload, setData };
}

/** Отложенный вызов (последнее значение за delay мс). */
export function useDebounced<A extends unknown[]>(fn: (...args: A) => void, delay: number) {
  const ref = useRef(fn);
  ref.current = fn;
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastArgs = useRef<A | null>(null);

  const flush = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    if (lastArgs.current) {
      const a = lastArgs.current;
      lastArgs.current = null;
      ref.current(...a);
    }
  }, []);

  const call = useCallback(
    (...args: A) => {
      lastArgs.current = args;
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(flush, delay);
    },
    [delay, flush],
  );

  useEffect(() => () => flush(), [flush]);
  return { call, flush };
}

/** Текущее время, обновляется с заданным периодом. */
export function useNow(periodMs: number, enabled = true): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!enabled) return;
    const id = setInterval(() => setNow(Date.now()), periodMs);
    return () => clearInterval(id);
  }, [periodMs, enabled]);
  return now;
}

/**
 * Живой уровень микрофона (mic_monitor), пока компонент на экране и окно видно.
 * Окно скрыли в трей или свернули — рассылку уровня выключаем, чтобы ядро не слало
 * level 30 раз в секунду в невидимое окно. Видимость — watchWindowShown: в Tauri
 * visibilitychange при hide() не приходит.
 */
export function useMicMonitor(enabled: boolean, restartKey?: unknown): void {
  const status = useConnStatus();
  useEffect(() => {
    if (!enabled || status !== "open") return;
    let on = false;
    const set = (v: boolean) => {
      if (v === on) return;
      on = v;
      backend.call("mic_monitor", { on: v }).catch(() => {});
    };
    const stop = watchWindowShown(set);
    return () => {
      stop();
      set(false);
    };
  }, [enabled, status, restartKey]);
}
