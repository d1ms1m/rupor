// Общие куски фичи «словарь учится на правках»: текст уведомления с выделенным
// термином (пилюля, пример на странице «Словарь») и выбор режима learn_mode.
import { BookCheck, BookPlus, CircleOff } from "lucide-react";
import type { ReactNode } from "react";
import { t } from "../i18n";
import type { LearnMode } from "../lib/types";
import { Segmented } from "./ui/controls";

/** Кавычки, в которые ядро берёт вариант: «ёлочки» (ru), “лапки” (en), прямые. */
const QUOTES: [string, string][] = [
  ["«", "»"],
  ["“", "”"],
  ['"', '"'],
  ["‘", "’"],
];

/**
 * Текст уведомления («В словарь добавлено: «метабейс» → Metabase» / "Added to dictionary:
 * “meta base” → Metabase") как есть из ядра, но с выделением: вариант приглушён, термин —
 * жирный. Не нашли их в тексте — просто текст.
 */
export function LearnText({
  text,
  term,
  variant,
  termClass,
  variantClass,
}: {
  text: string;
  term: string;
  variant: string;
  termClass: string;
  variantClass: string;
}) {
  const parts: ReactNode[] = [];
  let rest = text;
  let k = 0;
  let quoted = "";
  let vi = -1;
  for (const [open, close] of variant ? QUOTES : []) {
    const q = `${open}${variant}${close}`;
    const i = rest.indexOf(q);
    if (i >= 0) {
      quoted = q;
      vi = i;
      break;
    }
  }
  if (vi >= 0) {
    parts.push(rest.slice(0, vi));
    parts.push(
      <span key={k++} className={variantClass}>
        {quoted}
      </span>,
    );
    rest = rest.slice(vi + quoted.length);
  }
  const ti = term ? rest.lastIndexOf(term) : -1;
  if (ti >= 0) {
    parts.push(rest.slice(0, ti));
    parts.push(
      <span key={k++} className={termClass}>
        {term}
      </span>,
    );
    rest = rest.slice(ti + term.length);
  }
  parts.push(rest);
  return <>{parts}</>;
}

const MODES: LearnMode[] = ["auto", "suggest", "off"];
const ICONS: Record<LearnMode, ReactNode> = {
  auto: <BookCheck className="size-3.5" />,
  suggest: <BookPlus className="size-3.5" />,
  off: <CircleOff className="size-3.5" />,
};

/** Переключатель режима: сразу добавлять / спрашивать / выключено. */
export function LearnModePicker({
  value,
  onChange,
  size,
}: {
  value: LearnMode;
  onChange: (v: LearnMode) => void;
  size?: "sm" | "md";
}) {
  return (
    <Segmented<LearnMode>
      value={value}
      onChange={onChange}
      size={size}
      options={MODES.map((m) => ({ value: m, label: t(`learn.modes.${m}`), icon: ICONS[m] }))}
    />
  );
}
