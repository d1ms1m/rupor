import { AnimatePresence, motion } from "framer-motion";
import { LoaderCircle, X } from "lucide-react";
import {
  forwardRef,
  useId,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type KeyboardEvent,
  type ReactNode,
  type TextareaHTMLAttributes,
} from "react";
import { cn } from "../../lib/cn";

// ——— Кнопки ———

export type ButtonVariant = "primary" | "secondary" | "ghost" | "soft" | "danger" | "danger-solid";
export type ButtonSize = "sm" | "md" | "lg";

const VARIANT: Record<ButtonVariant, string> = {
  primary:
    "bg-accent text-accent-fg shadow-[inset_0_1px_0_rgb(255_255_255/0.18),0_1px_2px_rgb(0_0_0/0.12)] hover:brightness-[1.08] disabled:brightness-100",
  secondary:
    "bg-surface text-fg border border-line-strong shadow-card hover:bg-surface-2",
  ghost: "text-muted hover:text-fg hover:bg-surface-2",
  soft: "bg-accent-soft text-accent-text hover:bg-accent/20",
  danger: "bg-danger/10 text-danger hover:bg-danger/15",
  "danger-solid": "bg-danger text-white hover:brightness-110",
};

const SIZE: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-[13px] gap-1.5 rounded-[9px]",
  md: "h-9 px-3.5 text-[13.5px] gap-2 rounded-[10px]",
  lg: "h-11 px-5 text-[15px] gap-2 rounded-xl",
};

export interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onDrag" | "onDragStart" | "onDragEnd" | "onAnimationStart"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
  iconRight?: ReactNode;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", icon, iconRight, loading, className, children, disabled, type, ...rest },
  ref,
) {
  return (
    <motion.button
      ref={ref}
      type={type ?? "button"}
      whileTap={disabled || loading ? undefined : { scale: 0.975 }}
      transition={{ duration: 0.12 }}
      disabled={disabled || loading}
      className={cn(
        "relative inline-flex shrink-0 select-none items-center justify-center font-medium whitespace-nowrap",
        "transition-[background-color,color,box-shadow,filter,opacity] duration-150",
        "disabled:opacity-50 disabled:pointer-events-none",
        VARIANT[variant],
        SIZE[size],
        className,
      )}
      {...rest}
    >
      {loading ? <LoaderCircle className="size-4 animate-spin" /> : icon}
      {children}
      {iconRight}
    </motion.button>
  );
});

export interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onDrag" | "onDragStart" | "onDragEnd" | "onAnimationStart"> {
  label: string;
  size?: "sm" | "md";
  tone?: "default" | "danger" | "accent";
  active?: boolean;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, size = "md", tone = "default", active, className, children, type, ...rest },
  ref,
) {
  return (
    <motion.button
      ref={ref}
      type={type ?? "button"}
      aria-label={label}
      title={label}
      whileTap={{ scale: 0.92 }}
      transition={{ duration: 0.12 }}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-[9px] transition-colors duration-150",
        "disabled:opacity-40 disabled:pointer-events-none",
        size === "sm" ? "size-7" : "size-8",
        tone === "danger"
          ? "text-muted hover:text-danger hover:bg-danger/10"
          : tone === "accent"
            ? "text-accent-text hover:bg-accent-soft"
            : "text-muted hover:text-fg hover:bg-surface-2",
        active && "bg-surface-2 text-fg",
        className,
      )}
      {...rest}
    >
      {children}
    </motion.button>
  );
});

// ——— Переключатель ———

export function Switch({
  checked,
  onChange,
  disabled,
  label,
  size = "md",
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  label?: string;
  size?: "sm" | "md";
}) {
  const w = size === "sm" ? 30 : 36;
  const h = size === "sm" ? 18 : 20;
  const knob = h - 4;
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex shrink-0 items-center rounded-full p-[2px] transition-colors duration-200",
        checked ? "bg-accent" : "bg-surface-3",
        "disabled:opacity-40",
      )}
      style={{ width: w, height: h }}
    >
      <motion.span
        className="block rounded-full bg-white shadow-[0_1px_3px_rgb(0_0_0/0.25)]"
        style={{ width: knob, height: knob }}
        animate={{ x: checked ? w - knob - 4 : 0 }}
        transition={{ type: "spring", stiffness: 700, damping: 40 }}
      />
    </button>
  );
}

// ——— Сегментный переключатель ———

export interface SegmentOption<T extends string> {
  value: T;
  label: string;
  icon?: ReactNode;
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  size = "md",
  className,
  full,
}: {
  value: T;
  options: SegmentOption<T>[];
  onChange: (v: T) => void;
  size?: "sm" | "md";
  className?: string;
  full?: boolean;
}) {
  const id = useId();
  return (
    <div
      role="radiogroup"
      className={cn(
        "relative inline-flex rounded-[11px] bg-surface-2 p-[3px] border border-line",
        full && "flex w-full",
        className,
      )}
    >
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(o.value)}
            className={cn(
              "relative z-0 inline-flex items-center justify-center gap-1.5 rounded-[8px] font-medium transition-colors duration-150",
              size === "sm" ? "h-7 px-2.5 text-[12.5px]" : "h-8 px-3.5 text-[13px]",
              full && "flex-1",
              active ? "text-fg" : "text-muted hover:text-fg",
            )}
          >
            {active && (
              <motion.span
                layoutId={`seg-${id}`}
                className="absolute inset-0 -z-10 rounded-[8px] bg-surface shadow-[0_1px_2px_rgb(0_0_0/0.08),0_0_0_1px_var(--c-line)]"
                transition={{ type: "spring", stiffness: 520, damping: 40 }}
              />
            )}
            {o.icon}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

// ——— Поля ввода ———

const FIELD =
  "w-full rounded-[10px] bg-surface-2 border border-line text-fg placeholder:text-subtle " +
  "transition-[border-color,background-color,box-shadow] duration-150 outline-none " +
  "hover:border-line-strong focus:border-accent/60 focus:bg-surface focus:shadow-glow";

export const Input = forwardRef<
  HTMLInputElement,
  InputHTMLAttributes<HTMLInputElement> & { icon?: ReactNode; right?: ReactNode; inputSize?: "sm" | "md" }
>(function Input({ className, icon, right, inputSize = "md", ...rest }, ref) {
  return (
    <div className={cn("relative flex items-center", className)}>
      {icon && (
        <span className="pointer-events-none absolute left-3 flex text-subtle [&>svg]:size-4">{icon}</span>
      )}
      <input
        ref={ref}
        className={cn(
          FIELD,
          inputSize === "sm" ? "h-8 text-[13px]" : "h-9 text-[13.5px]",
          icon ? "pl-9" : "pl-3",
          right ? "pr-9" : "pr-3",
        )}
        {...rest}
      />
      {right && <span className="absolute right-1.5 flex">{right}</span>}
    </div>
  );
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className, ...rest }, ref) {
    return (
      <textarea
        ref={ref}
        className={cn(FIELD, "px-3 py-2.5 text-[13.5px] leading-relaxed resize-none", className)}
        {...rest}
      />
    );
  },
);

// ——— Ползунок ———

export function Slider({
  value,
  min,
  max,
  step = 1,
  onChange,
  onCommit,
  format,
  className,
  label,
}: {
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (v: number) => void;
  onCommit?: (v: number) => void;
  format?: (v: number) => string;
  className?: string;
  /** Подпись для экранного диктора (у ползунка нет видимого label). */
  label?: string;
}) {
  const fill = ((value - min) / (max - min || 1)) * 100;
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <input
        type="range"
        className="range"
        aria-label={label}
        aria-valuetext={format?.(value)}
        min={min}
        max={max}
        step={step}
        value={value}
        style={{ ["--fill" as string]: `${fill}%` }}
        onChange={(e) => onChange(Number(e.target.value))}
        onPointerUp={(e) => onCommit?.(Number((e.target as HTMLInputElement).value))}
        onKeyUp={(e) => onCommit?.(Number((e.target as HTMLInputElement).value))}
      />
      {format && (
        <span className="tabular w-16 shrink-0 text-right text-[13px] font-medium text-muted">
          {format(value)}
        </span>
      )}
    </div>
  );
}

// ——— Чипы (варианты, классы RDP, термины) ———

export function ChipInput({
  values,
  onChange,
  placeholder,
  autoFocus,
  className,
  mono,
}: {
  values: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  autoFocus?: boolean;
  className?: string;
  mono?: boolean;
}) {
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const add = (raw: string) => {
    const parts = raw
      .split(/[,;\n]/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (!parts.length) return;
    const next = [...values];
    for (const p of parts) {
      if (!next.some((v) => v.toLowerCase() === p.toLowerCase())) next.push(p);
    }
    onChange(next);
    setDraft("");
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === "," || e.key === "Tab") {
      if (draft.trim()) {
        e.preventDefault();
        add(draft);
      }
    } else if (e.key === "Backspace" && !draft && values.length) {
      onChange(values.slice(0, -1));
    }
  };

  return (
    <div
      onClick={() => inputRef.current?.focus()}
      className={cn(
        FIELD,
        "flex min-h-9 flex-wrap items-center gap-1.5 px-2 py-1.5 focus-within:border-accent/60 focus-within:bg-surface focus-within:shadow-glow",
        className,
      )}
    >
      <AnimatePresence initial={false}>
        {values.map((v) => (
          <motion.span
            key={v}
            layout
            initial={{ opacity: 0, scale: 0.85 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.85 }}
            transition={{ duration: 0.15 }}
            className={cn(
              "inline-flex h-6 items-center gap-1 rounded-md bg-surface-3 pl-2 pr-1 text-[12.5px] text-fg",
              mono && "font-mono text-[12px]",
            )}
          >
            {v}
            <button
              type="button"
              className="flex size-4 items-center justify-center rounded text-subtle hover:bg-line-strong hover:text-fg"
              onClick={(e) => {
                e.stopPropagation();
                onChange(values.filter((x) => x !== v));
              }}
            >
              <X className="size-3" />
            </button>
          </motion.span>
        ))}
      </AnimatePresence>
      <input
        ref={inputRef}
        value={draft}
        autoFocus={autoFocus}
        placeholder={values.length ? undefined : placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKey}
        onBlur={() => draft.trim() && add(draft)}
        onPaste={(e) => {
          const text = e.clipboardData.getData("text");
          if (/[,;\n]/.test(text)) {
            e.preventDefault();
            add(text);
          }
        }}
        className="h-6 min-w-24 flex-1 bg-transparent px-1 text-[13px] outline-none placeholder:text-subtle"
      />
    </div>
  );
}

// ——— Флажок ———

export function Checkbox({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label?: string;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={cn(
        "flex size-[18px] shrink-0 items-center justify-center rounded-[5px] border transition-colors duration-150",
        checked ? "border-accent bg-accent text-accent-fg" : "border-line-strong bg-surface hover:border-subtle",
      )}
    >
      <AnimatePresence>
        {checked && (
          <motion.svg
            viewBox="0 0 16 16"
            className="size-3"
            initial={{ opacity: 0, scale: 0.6 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.6 }}
            transition={{ duration: 0.12 }}
          >
            <motion.path
              d="M3.5 8.5l3 3 6-7"
              fill="none"
              stroke="currentColor"
              strokeWidth={2.2}
              strokeLinecap="round"
              strokeLinejoin="round"
              initial={{ pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={{ duration: 0.18 }}
            />
          </motion.svg>
        )}
      </AnimatePresence>
    </button>
  );
}
