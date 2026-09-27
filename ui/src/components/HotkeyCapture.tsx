// Выбор клавиши хоткея: из списка или «записать» нажатием.
// ChordCapture — сочетание с модификаторами («Вставить последнее» / «Скопировать последнее»).
//
// Пока идёт запись, хоткеи ядра заглушены (muteCoreHotkeys): иначе нажатие текущего
// сочетания выполнит действие ядра (вставку в чужое окно), а до WebView дойдут только
// модификаторы. onChange держим в ref: родитель перерисовывается от событий state,
// и новая стрелочная функция не должна перезапускать эффект (сбрасывать нажатое и таймер).
import { AnimatePresence, motion } from "framer-motion";
import { Ban, Keyboard, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { t } from "../i18n";
import { muteCoreHotkeys } from "../lib/capture";
import { cn } from "../lib/cn";
import { GENERIC_MODS, KEY_NAMES, PTT_COMBOS, eventToChord, eventToKeyName, keyLabel, pressedToPtt } from "../lib/keys";
import { useCore } from "../lib/store";
import { IconButton } from "./ui/controls";
import { KeyCombo } from "./ui/display";
import { Select, type SelectOption } from "./ui/select";

/** Пауза хука ядра на время записи (общая для обоих виджетов). */
function useCaptureSession(capturing: boolean) {
  const { state } = useCore();
  const pausedRef = useRef(Boolean(state?.paused));
  pausedRef.current = Boolean(state?.paused);
  useEffect(() => {
    if (!capturing) return;
    return muteCoreHotkeys(pausedRef.current);
  }, [capturing]);
}

/** Сочетание вида «ctrl+alt+shift+v»: записать нажатием или выключить (""). */
export function ChordCapture({ value, onChange }: { value: string; onChange: (chord: string) => void }) {
  const [capturing, setCapturing] = useState(false);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  useCaptureSession(capturing);

  useEffect(() => {
    if (!capturing) return;
    const onDown = (e: KeyboardEvent) => {
      e.preventDefault();
      e.stopPropagation();
      if (e.repeat) return;
      if (e.code === "Escape" && !e.ctrlKey && !e.altKey && !e.shiftKey && !e.metaKey) {
        setCapturing(false);
        return;
      }
      const chord = eventToChord(e);
      if (chord) {
        setCapturing(false);
        onChangeRef.current(chord);
      }
    };
    const onUp = (e: KeyboardEvent) => {
      e.preventDefault();
      e.stopPropagation();
    };
    const timer = setTimeout(() => setCapturing(false), 10_000);
    window.addEventListener("keydown", onDown, true);
    window.addEventListener("keyup", onUp, true);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("keydown", onDown, true);
      window.removeEventListener("keyup", onUp, true);
    };
  }, [capturing]);

  return (
    <div className="flex items-center gap-1.5">
      <div
        className={cn(
          "flex h-9 w-[200px] items-center gap-2 rounded-[10px] border px-3 text-[13px] transition-colors duration-150",
          capturing ? "border-accent/60 bg-accent-soft font-medium text-accent-text shadow-glow" : "border-line bg-surface-2",
        )}
      >
        {capturing ? (
          <>
            <motion.span
              className="size-2 rounded-full bg-accent"
              animate={{ opacity: [1, 0.3, 1] }}
              transition={{ duration: 1.1, repeat: Infinity }}
            />
            {t("hotkeys.pressChord")}
          </>
        ) : value ? (
          <KeyCombo keys={[value]} wrap={false} />
        ) : (
          <span className="text-subtle">{t("hotkeys.off")}</span>
        )}
      </div>
      {capturing ? (
        <IconButton label={t("common.cancel")} onClick={() => setCapturing(false)}>
          <X className="size-4" />
        </IconButton>
      ) : (
        <IconButton label={t("hotkeys.record")} onClick={() => setCapturing(true)}>
          <Keyboard className="size-4" />
        </IconButton>
      )}
      <IconButton label={t("hotkeys.disable")} disabled={!value || capturing} onClick={() => onChange("")}>
        <Ban className="size-4" />
      </IconButton>
    </div>
  );
}

export function HotkeyCapture({
  value,
  onChange,
  allowNone,
  combo,
}: {
  value: string;
  onChange: (name: string) => void;
  allowNone?: boolean;
  /** Клавиша диктовки: можно записать сочетание модификаторов («Ctrl + Alt»). */
  combo?: boolean;
}) {
  const [capturing, setCapturing] = useState(false);
  const pressed = useRef<string[]>([]);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  useCaptureSession(capturing);

  useEffect(() => {
    if (!capturing) return;
    pressed.current = [];
    const finish = (name: string | null) => {
      setCapturing(false);
      if (name) onChangeRef.current(name);
    };
    const onDown = (e: KeyboardEvent) => {
      e.preventDefault();
      e.stopPropagation();
      if (e.repeat) return;
      // AltGr приходит как «левый Ctrl + правый Alt»; левый Ctrl тут ненастоящий (ядро его
      // тоже игнорирует) — выбрасываем, иначе запишется «Ctrl + Alt», который AltGr не нажмёт
      if (e.key === "AltGraph") pressed.current = pressed.current.filter((k) => k !== "lctrl");
      const name = eventToKeyName(e);
      if (name && !pressed.current.includes(name)) pressed.current.push(name);
    };
    const onUp = (e: KeyboardEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const list = pressed.current;
      if (!list.length) return;
      if (combo && list.length > 1) {
        finish(pressedToPtt(list));
        return;
      }
      // AltGr в Windows приходит как «левый Ctrl + правый Alt» — берём правый Alt
      const pick = list.includes("ralt") ? "ralt" : list[0] ?? null;
      finish(pick);
    };
    const timer = setTimeout(() => finish(null), 10_000);
    window.addEventListener("keydown", onDown, true);
    window.addEventListener("keyup", onUp, true);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("keydown", onDown, true);
      window.removeEventListener("keyup", onUp, true);
    };
  }, [capturing, combo]);

  const base = combo ? [...PTT_COMBOS, ...KEY_NAMES.filter((n) => !GENERIC_MODS.includes(n))] : KEY_NAMES;
  const names = base.includes(value) || !value ? base : [value, ...base];
  const options: SelectOption<string>[] = names.map((n) => ({ value: n, label: keyLabel(n) }));
  if (allowNone) options.unshift({ value: "", label: t("keys.none") });

  return (
    <div className="flex items-center gap-1.5">
      <AnimatePresence mode="wait" initial={false}>
        {capturing ? (
          <motion.div
            key="cap"
            initial={{ opacity: 0, scale: 0.97 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.97 }}
            transition={{ duration: 0.14 }}
            className="flex h-9 w-[200px] items-center gap-2 rounded-[10px] border border-accent/60 bg-accent-soft px-3 text-[13px] font-medium text-accent-text shadow-glow"
          >
            <motion.span
              className="size-2 rounded-full bg-accent"
              animate={{ opacity: [1, 0.3, 1] }}
              transition={{ duration: 1.1, repeat: Infinity }}
            />
            {combo ? t("hotkeys.pressKeyOrCombo") : t("hotkeys.pressKey")}
          </motion.div>
        ) : (
          <motion.div
            key="sel"
            initial={{ opacity: 0, scale: 0.97 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.97 }}
            transition={{ duration: 0.14 }}
          >
            <Select value={value} options={options} onChange={onChange} className="w-[200px]" />
          </motion.div>
        )}
      </AnimatePresence>
      {capturing ? (
        <IconButton label={t("common.cancel")} onClick={() => setCapturing(false)}>
          <X className="size-4" />
        </IconButton>
      ) : (
        <IconButton label={t("hotkeys.record")} onClick={() => setCapturing(true)}>
          <Keyboard className="size-4" />
        </IconButton>
      )}
    </div>
  );
}
