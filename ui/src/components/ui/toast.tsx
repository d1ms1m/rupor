import { AnimatePresence, motion } from "framer-motion";
import { CircleAlert, CircleCheck, Info, TriangleAlert, X } from "lucide-react";
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { t } from "../../i18n";
import { cn } from "../../lib/cn";

export type ToastTone = "info" | "success" | "warn" | "error";

export interface ToastInput {
  title: string;
  description?: string;
  tone?: ToastTone;
  action?: { label: string; onClick: () => void };
  duration?: number;
  /** Своя иконка вместо иконки тона (например, словарь у уведомлений «словарь учится»). */
  icon?: ReactNode;
}

interface ToastItem extends ToastInput {
  id: number;
}

type ToastFn = (t: ToastInput) => void;
const ToastCtx = createContext<ToastFn>(() => {});

const ICON: Record<ToastTone, ReactNode> = {
  info: <Info className="size-[18px] text-info" />,
  success: <CircleCheck className="size-[18px] text-success" />,
  warn: <TriangleAlert className="size-[18px] text-warn" />,
  error: <CircleAlert className="size-[18px] text-danger" />,
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setItems((xs) => xs.filter((x) => x.id !== id));
  }, []);

  const push = useCallback<ToastFn>(
    (input) => {
      const id = nextId.current++;
      setItems((xs) => [...xs.slice(-3), { ...input, id }]);
      const ms = input.duration ?? (input.action ? 7000 : input.tone === "error" ? 6000 : 3800);
      setTimeout(() => dismiss(id), ms);
    },
    [dismiss],
  );

  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div
        role="status"
        aria-live="polite"
        className="pointer-events-none fixed bottom-5 right-5 z-[120] flex w-[360px] flex-col items-end gap-2"
      >
        <AnimatePresence initial={false}>
          {items.map((it) => (
            <motion.div
              key={it.id}
              layout
              initial={{ opacity: 0, y: 16, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, x: 24, transition: { duration: 0.16 } }}
              transition={{ type: "spring", stiffness: 480, damping: 36 }}
              className={cn(
                "pointer-events-auto flex w-full items-start gap-3 rounded-xl border border-line-strong bg-surface p-3.5 pr-2.5 shadow-pop",
              )}
            >
              <span className="mt-px shrink-0">{it.icon ?? ICON[it.tone ?? "info"]}</span>
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-medium leading-snug text-fg">{it.title}</div>
                {it.description && (
                  <div className="mt-0.5 text-[12.5px] leading-snug text-muted">{it.description}</div>
                )}
                {it.action && (
                  <button
                    type="button"
                    onClick={() => {
                      it.action?.onClick();
                      dismiss(it.id);
                    }}
                    className="mt-2 text-[12.5px] font-semibold text-accent-text hover:underline"
                  >
                    {it.action.label}
                  </button>
                )}
              </div>
              <button
                type="button"
                aria-label={t("common.close")}
                onClick={() => dismiss(it.id)}
                className="flex size-6 shrink-0 items-center justify-center rounded-md text-subtle hover:bg-surface-2 hover:text-fg"
              >
                <X className="size-3.5" />
              </button>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast(): ToastFn {
  return useContext(ToastCtx);
}
