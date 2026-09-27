// Общее состояние окна: связь с ядром, State, настройки, список стилей.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { syncLocale, t, useLocale } from "../i18n";
import { useToast } from "../components/ui/toast";
import { errorText } from "./hub";
import { backend, call } from "./ws";
import type { ConnStatus, CoreState, Settings, SettingsPatch, StyleInfo } from "./types";

interface CoreValue {
  status: ConnStatus;
  state: CoreState | null;
  settings: Settings | null;
  styles: StyleInfo[];
  /** styles_list не загрузился (иначе страница «Стили» навсегда осталась бы скелетоном). */
  stylesError: string | null;
  reloadStyles: () => void;
  updateSettings: (patch: SettingsPatch) => Promise<boolean>;
  setState: (s: CoreState) => void;
}

const CoreCtx = createContext<CoreValue | null>(null);

export function CoreProvider({ children }: { children: ReactNode }) {
  const toast = useToast();
  const [status, setStatus] = useState<ConnStatus>(backend.status());
  const [state, setState] = useState<CoreState | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [styles, setStyles] = useState<StyleInfo[]>([]);
  const [stylesError, setStylesError] = useState<string | null>(null);
  const [stylesTick, setStylesTick] = useState(0);
  const settingsRef = useRef<Settings | null>(null);
  settingsRef.current = settings;

  // Язык интерфейса: settings.language, для "system" — State.ui_language (ядро знает язык Windows)
  const uiLanguage = state?.ui_language;
  const langPref = settings?.language;
  useEffect(() => syncLocale(langPref, uiLanguage), [langPref, uiLanguage]);

  useEffect(() => {
    const offs = [
      backend.onStatus(setStatus),
      backend.on("hello", setState),
      backend.on("state", setState),
      backend.on("settings", setSettings),
    ];
    backend.start();
    setStatus(backend.status());
    return () => offs.forEach((f) => f());
  }, []);

  useEffect(() => {
    if (status !== "open") return;
    let alive = true;
    call("get_state")
      .then((s) => alive && setState(s))
      .catch(() => {});
    call("get_settings")
      .then((s) => alive && setSettings(s))
      .catch((e: unknown) => toast({ tone: "error", title: t("errors.settingsLoad"), description: errorText(e) }));
    return () => {
      alive = false;
    };
  }, [status, toast]);

  useEffect(() => {
    if (status !== "open") return;
    let alive = true;
    let retry: ReturnType<typeof setTimeout> | null = null;
    const load = (attempt: number) => {
      call("styles_list")
        .then((s) => {
          if (!alive) return;
          setStyles(s);
          setStylesError(null);
        })
        .catch((e: unknown) => {
          if (!alive) return;
          setStylesError(errorText(e));
          // пара тихих повторов: сбой бывает разовым (ядро ещё поднимается)
          if (attempt < 2) retry = setTimeout(() => load(attempt + 1), 2000 * (attempt + 1));
        });
    };
    load(0);
    return () => {
      alive = false;
      if (retry) clearTimeout(retry);
    };
  }, [status, stylesTick]);

  // Названия и описания стилей ядро отдаёт на языке интерфейса: язык сменился — перечитываем
  // (первое появление ui_language — не смена, стили и так грузятся при подключении)
  const stylesLang = useRef(uiLanguage);
  useEffect(() => {
    if (stylesLang.current && uiLanguage && stylesLang.current !== uiLanguage) setStylesTick((x) => x + 1);
    if (uiLanguage) stylesLang.current = uiLanguage;
  }, [uiLanguage]);

  const reloadStyles = useCallback(() => setStylesTick((x) => x + 1), []);

  const updateSettings = useCallback(
    async (patch: SettingsPatch): Promise<boolean> => {
      const prev = settingsRef.current;
      if (prev) setSettings({ ...prev, ...patch });
      try {
        const next = await call("set_settings", { patch });
        setSettings(next);
        return true;
      } catch (e) {
        if (prev) setSettings(prev);
        toast({ tone: "error", title: t("errors.settingsSave"), description: errorText(e) });
        return false;
      }
    },
    [toast],
  );

  const value = useMemo<CoreValue>(
    () => ({ status, state, settings, styles, stylesError, reloadStyles, updateSettings, setState }),
    [status, state, settings, styles, stylesError, reloadStyles, updateSettings],
  );
  return <CoreCtx.Provider value={value}>{children}</CoreCtx.Provider>;
}

export function useCore(): CoreValue {
  const v = useContext(CoreCtx);
  if (!v) throw new Error("CoreProvider missing");
  return v;
}

/** Имя стиля по id (из styles_list — ядро отдаёт на языке интерфейса). */
export function useStyleName(): (id: string | null | undefined) => string {
  const { styles } = useCore();
  const locale = useLocale();
  return useCallback(
    (id) => {
      if (!id) return t("styles.default");
      return styles.find((s) => s.id === id)?.name ?? id;
    },
    [styles, locale], // locale: t() читает текущий язык
  );
}
