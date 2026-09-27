// Столбики по дням (30 дней): свой SVG, столбики вырастают, подсказка при наведении.
// Полный вид — с осью и датами (слова на Главной, расход в настройках ИИ), compact — мини-график
// без осей (карточка «ИИ» на Главной).
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { cn } from "../lib/cn";
import { fmtLongDate, fmtShortDate, fmtWeekday, todayIso } from "../lib/format";

export function niceMax(v: number): number {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  const n = v / p;
  const steps = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];
  const step = steps.find((s) => n <= s + 1e-9) ?? 10;
  return step * p;
}

export interface DayBarsProps<T extends { date: string }> {
  data: T[];
  value: (d: T) => number;
  /** Подписи оси (только полный вид). */
  axisFormat?: (v: number) => string;
  /** Содержимое подсказки под датой. */
  tooltip: (d: T) => ReactNode;
  height?: number;
  compact?: boolean;
  /** Ширина под подписи оси слева (полный вид). */
  padLeft?: number;
  /** Пустой максимум (все нули): высота шкалы. */
  emptyMax?: number;
  className?: string;
}

export function DayBars<T extends { date: string }>({
  data,
  value,
  axisFormat,
  tooltip,
  height,
  compact,
  padLeft,
  emptyMax = 100,
  className,
}: DayBarsProps<T>) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(compact ? 200 : 640);
  const [hover, setHover] = useState<number | null>(null);
  const today = todayIso();

  const H = height ?? (compact ? 48 : 188);
  const PAD_TOP = compact ? 4 : 14;
  const PAD_BOTTOM = compact ? 1 : 26;
  const PAD_LEFT = compact ? 0 : (padLeft ?? 38);
  const minW = compact ? 90 : 280;

  useLayoutEffect(() => {
    const el = wrapRef.current;
    if (el) setWidth(Math.max(minW, el.getBoundingClientRect().width));
  }, [minW]);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      if (entry) setWidth(Math.max(minW, entry.contentRect.width));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [minW]);

  const values = useMemo(() => data.map(value), [data, value]);
  const top = Math.max(...values, 0);
  const max = useMemo(() => (top > 0 ? niceMax(top) : emptyMax), [top, emptyMax]);
  const plotW = width - PAD_LEFT;
  const plotH = H - PAD_TOP - PAD_BOTTOM;
  const n = Math.max(1, data.length);
  const slot = plotW / n;
  const barW = compact ? Math.max(2, Math.min(7, slot * 0.64)) : Math.max(4, Math.min(18, slot * 0.62));
  const ticks = compact ? [] : [0, max / 2, max];

  const hovered = hover !== null ? data[hover] : undefined;
  const hv = hover !== null ? (values[hover] ?? 0) : 0;
  const hx = hover !== null ? PAD_LEFT + hover * slot + slot / 2 : 0;
  const hy = hovered !== undefined ? PAD_TOP + plotH - (hv / max) * plotH : 0;
  // У краёв подсказку не центрируем, а прижимаем — иначе она вылезает за карточку/окно
  const EDGE = 96;
  const align = hx < EDGE ? "left" : hx > width - EDGE ? "right" : "center";

  return (
    <div
      ref={wrapRef}
      className={className ? `relative w-full select-none ${className}` : "relative w-full select-none"}
      onMouseLeave={() => setHover(null)}
    >
      <svg width={width} height={H} className="block overflow-visible">
        {ticks.map((v) => {
          const y = PAD_TOP + plotH - (v / max) * plotH;
          return (
            <g key={v}>
              <line
                x1={PAD_LEFT}
                x2={width}
                y1={y}
                y2={y}
                stroke="var(--c-line)"
                strokeDasharray={v === 0 ? undefined : "3 4"}
              />
              <text x={PAD_LEFT - 10} y={y + 4} textAnchor="end" className="fill-subtle text-[11px] tabular">
                {axisFormat ? axisFormat(v) : String(v)}
              </text>
            </g>
          );
        })}
        {compact && <line x1={0} x2={width} y1={PAD_TOP + plotH} y2={PAD_TOP + plotH} stroke="var(--c-line)" />}
        {data.map((d, i) => {
          const v = values[i] ?? 0;
          const h = v > 0 ? Math.max(compact ? 2 : 3, (v / max) * plotH) : compact ? 1 : 2;
          const x = PAD_LEFT + i * slot + (slot - barW) / 2;
          const y = PAD_TOP + plotH - h;
          const isToday = d.date === today;
          const dim = hover !== null && hover !== i;
          return (
            <g key={d.date}>
              <motion.rect
                x={x}
                width={barW}
                rx={Math.min(compact ? 2 : 5, barW / 2)}
                initial={{ height: 0, y: PAD_TOP + plotH }}
                animate={{ height: h, y }}
                transition={{ duration: 0.55, delay: i * (compact ? 0.008 : 0.012), ease: [0.22, 1, 0.36, 1] }}
                fill={v > 0 ? "var(--c-accent)" : "var(--c-surface-3)"}
                style={{
                  opacity: v === 0 ? 1 : dim ? 0.35 : isToday || hover === i ? 1 : 0.72,
                  transition: "opacity 150ms",
                }}
              />
              {!compact && (n - 1 - i) % 5 === 0 && (
                <text
                  x={PAD_LEFT + i * slot + slot / 2}
                  y={H - 6}
                  textAnchor="middle"
                  className={isToday ? "fill-fg text-[11px] font-medium" : "fill-subtle text-[11px]"}
                >
                  {fmtShortDate(d.date)}
                </text>
              )}
              <rect
                x={PAD_LEFT + i * slot}
                y={0}
                width={slot}
                height={H - PAD_BOTTOM + (compact ? 1 : 6)}
                fill="transparent"
                onMouseEnter={() => setHover(i)}
              />
            </g>
          );
        })}
      </svg>
      <AnimatePresence>
        {hovered && (
          <motion.div
            key="tip"
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0, left: hx, top: hy }}
            exit={{ opacity: 0 }}
            transition={{ type: "spring", stiffness: 600, damping: 42, opacity: { duration: 0.12 } }}
            className={cn(
              "pointer-events-none absolute z-10 -translate-y-[calc(100%+10px)] rounded-lg border border-line-strong bg-surface px-3 py-2 shadow-pop",
              align === "center" && "-translate-x-1/2",
              align === "left" && "-translate-x-4",
              align === "right" && "-translate-x-[calc(100%-16px)]",
            )}
          >
            <div className="whitespace-nowrap text-[11.5px] text-muted">
              {fmtWeekday(hovered.date)}, {fmtLongDate(hovered.date)}
            </div>
            <div className="whitespace-nowrap text-[13px] font-semibold text-fg tabular">{tooltip(hovered)}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
