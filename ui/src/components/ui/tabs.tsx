import { motion } from "framer-motion";
import { useId, type ReactNode } from "react";
import { cn } from "../../lib/cn";

export interface TabItem<T extends string> {
  value: T;
  label: string;
  icon?: ReactNode;
  count?: number;
}

/** Вкладки с подчёркиванием, индикатор переезжает анимацией. */
export function Tabs<T extends string>({
  value,
  items,
  onChange,
  className,
}: {
  value: T;
  items: TabItem<T>[];
  onChange: (v: T) => void;
  className?: string;
}) {
  const id = useId();
  return (
    <div role="tablist" className={cn("flex gap-5 border-b border-line", className)}>
      {items.map((it) => {
        const active = it.value === value;
        return (
          <button
            key={it.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(it.value)}
            className={cn(
              "relative flex h-10 items-center gap-2 text-[13.5px] font-medium transition-colors duration-150 [&>svg]:size-4",
              active ? "text-fg" : "text-muted hover:text-fg",
            )}
          >
            {it.icon}
            {it.label}
            {it.count !== undefined && (
              <span className="rounded-md bg-surface-3 px-1.5 py-px text-[11px] font-medium text-muted tabular">
                {it.count}
              </span>
            )}
            {active && (
              <motion.span
                layoutId={`tab-${id}`}
                className="absolute inset-x-0 -bottom-px h-[2px] rounded-full bg-accent"
                transition={{ type: "spring", stiffness: 520, damping: 40 }}
              />
            )}
          </button>
        );
      })}
    </div>
  );
}
