import { motion } from "framer-motion";
import { CircleAlert, LoaderCircle, RefreshCw } from "lucide-react";
import type { HTMLAttributes, ReactNode } from "react";
import { t } from "../../i18n";
import { cn } from "../../lib/cn";
import { comboParts, keyLabel } from "../../lib/keys";
import { Button } from "./controls";

export function Card({
  className,
  children,
  padded = true,
  ...rest
}: HTMLAttributes<HTMLDivElement> & { padded?: boolean }) {
  return (
    <div
      className={cn("rounded-2xl border border-line bg-surface shadow-card", padded && "p-5", className)}
      {...rest}
    >
      {children}
    </div>
  );
}

export type Tone = "neutral" | "accent" | "success" | "warn" | "danger" | "info";

const TONE: Record<Tone, string> = {
  neutral: "bg-surface-3/70 text-muted",
  accent: "bg-accent-soft text-accent-text",
  success: "bg-success/12 text-success",
  warn: "bg-warn/14 text-warn",
  danger: "bg-danger/12 text-danger",
  info: "bg-info/12 text-info",
};

export function Badge({
  tone = "neutral",
  icon,
  children,
  className,
  title,
}: {
  tone?: Tone;
  icon?: ReactNode;
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex h-5 shrink-0 items-center gap-1 rounded-md px-1.5 text-[11px] font-medium leading-none whitespace-nowrap [&>svg]:size-3",
        TONE[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  );
}

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd
      className={cn(
        "inline-flex h-6 min-w-6 items-center justify-center rounded-md border border-line-strong bg-surface px-1.5",
        "font-sans text-[12px] font-medium text-fg shadow-[0_1px_0_var(--c-line-strong)] whitespace-nowrap",
        className,
      )}
    >
      {children}
    </kbd>
  );
}

/** Сочетание клавиш: «Правый Ctrl» + «Правый Shift». */
export function KeyCombo({ keys, className, wrap = true }: { keys: string[]; className?: string; wrap?: boolean }) {
  const parts = keys.flatMap(comboParts);
  return (
    <span className={cn("inline-flex items-center gap-1", wrap ? "flex-wrap" : "flex-nowrap", className)}>
      {parts.map((k, i) => (
        <span key={`${k}-${i}`} className="inline-flex items-center gap-1">
          {i > 0 && <span className="text-[12px] text-subtle">+</span>}
          <Kbd>{keyLabel(k)}</Kbd>
        </span>
      ))}
    </span>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton", className)} />;
}

export function Spinner({ className }: { className?: string }) {
  return <LoaderCircle className={cn("size-4 animate-spin text-muted", className)} />;
}

export function ProgressBar({
  value,
  indeterminate,
  className,
  tone = "accent",
}: {
  value: number;
  indeterminate?: boolean;
  className?: string;
  tone?: "accent" | "danger";
}) {
  return (
    <div className={cn("relative h-1.5 w-full overflow-hidden rounded-full bg-surface-3", className)}>
      {indeterminate ? (
        <motion.div
          className={cn("absolute inset-y-0 w-1/3 rounded-full", tone === "danger" ? "bg-danger" : "bg-accent")}
          animate={{ x: ["-100%", "300%"] }}
          transition={{ duration: 1.2, repeat: Infinity, ease: "easeInOut" }}
        />
      ) : (
        <motion.div
          className={cn("h-full rounded-full", tone === "danger" ? "bg-danger" : "bg-accent")}
          initial={false}
          animate={{ width: `${Math.max(0, Math.min(100, value))}%` }}
          transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
        />
      )}
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-[24px] font-semibold tracking-[-0.02em] text-fg">{title}</h1>
        {subtitle && <p className="mt-1 max-w-2xl text-[13.5px] text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function SectionTitle({
  children,
  hint,
  right,
  className,
}: {
  children: ReactNode;
  hint?: ReactNode;
  right?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("mb-3 flex items-end justify-between gap-3", className)}>
      <div>
        <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-fg">{children}</h2>
        {hint && <p className="mt-0.5 text-[12.5px] text-muted">{hint}</p>}
      </div>
      {right}
    </div>
  );
}

/** Строка настройки: подпись слева, элемент управления справа. */
export function SettingRow({
  title,
  description,
  children,
  stacked,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  stacked?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex gap-6 border-b border-line px-5 py-4 last:border-b-0",
        stacked ? "flex-col gap-3" : "items-center justify-between",
        className,
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="text-[13.5px] font-medium text-fg">{title}</div>
        {description && <div className="mt-0.5 text-[12.5px] leading-relaxed text-muted">{description}</div>}
      </div>
      {children !== undefined && <div className={cn(stacked ? "w-full" : "shrink-0")}>{children}</div>}
    </div>
  );
}

/** Пустое состояние: иконка-иллюстрация в мягких кольцах. */
export function EmptyState({
  icon,
  title,
  text,
  action,
  className,
  compact,
}: {
  icon: ReactNode;
  title: string;
  text?: ReactNode;
  action?: ReactNode;
  className?: string;
  compact?: boolean;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
      className={cn("flex flex-col items-center justify-center text-center", compact ? "py-8" : "py-14", className)}
    >
      <div className={cn("relative mb-5 flex items-center justify-center", compact ? "size-20" : "size-28")}>
        <div className="absolute inset-0 rounded-full bg-accent/[0.06]" />
        <div className="absolute inset-[14%] rounded-full bg-accent/[0.08]" />
        <motion.span
          className="absolute right-[12%] top-[10%] size-1.5 rounded-full bg-accent/60"
          animate={{ y: [0, -4, 0], opacity: [0.6, 1, 0.6] }}
          transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.span
          className="absolute bottom-[16%] left-[10%] size-1 rounded-full bg-accent/50"
          animate={{ y: [0, 3, 0], opacity: [0.5, 0.9, 0.5] }}
          transition={{ duration: 3.6, repeat: Infinity, ease: "easeInOut", delay: 0.6 }}
        />
        <div
          className={cn(
            "relative flex items-center justify-center rounded-2xl border border-line bg-surface text-accent-text shadow-card",
            compact ? "size-11 [&>svg]:size-5" : "size-14 [&>svg]:size-6",
          )}
        >
          {icon}
        </div>
      </div>
      <div className="text-[15px] font-semibold text-fg">{title}</div>
      {text && <div className="mt-1.5 max-w-sm text-[13px] leading-relaxed text-muted">{text}</div>}
      {action && <div className="mt-5">{action}</div>}
    </motion.div>
  );
}

/**
 * Данные не загрузились (ошибка БД, таймаут): причина и «Повторить».
 * Не путать с пустым состоянием — иначе сбой выглядит как «Словарь пуст».
 */
export function LoadError({
  error,
  onRetry,
  title,
  compact,
  className,
}: {
  error: string;
  onRetry: () => void;
  title?: string;
  compact?: boolean;
  className?: string;
}) {
  return (
    <motion.div
      role="alert"
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
      className={cn("flex flex-col items-center justify-center text-center", compact ? "py-6" : "py-14", className)}
    >
      <div
        className={cn(
          "mb-4 flex items-center justify-center rounded-2xl border border-line bg-surface text-danger shadow-card",
          compact ? "size-10 [&>svg]:size-5" : "size-14 [&>svg]:size-6",
        )}
      >
        <CircleAlert />
      </div>
      <div className="text-[15px] font-semibold text-fg">{title ?? t("errors.load")}</div>
      <div className="mt-1.5 max-w-sm text-[13px] leading-relaxed text-muted selectable">{error}</div>
      <Button className="mt-5" variant="secondary" icon={<RefreshCw className="size-4" />} onClick={onRetry}>
        {t("common.retry")}
      </Button>
    </motion.div>
  );
}

/** Анимация появления содержимого страницы. */
export function FadeIn({
  children,
  delay = 0,
  className,
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
}) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.24, delay, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  );
}
