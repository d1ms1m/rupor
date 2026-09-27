import { motion } from "framer-motion";
import { cn } from "../lib/cn";

const BARS = [
  { x: 7.5, h: 10, o: 0.75 },
  { x: 12.5, h: 17, o: 1 },
  { x: 17.5, h: 22, o: 1 },
  { x: 22.5, h: 13, o: 0.85 },
];

/** Знак «Рупора»: столбики волны на акцентной плитке; при записи — оживают. */
export function Logo({ size = 30, live, className }: { size?: number; live?: boolean; className?: string }) {
  return (
    <span
      className={cn("relative inline-flex shrink-0 overflow-hidden rounded-[9px] shadow-[0_2px_8px_-2px_var(--c-accent-ring)]", className)}
      style={{
        width: size,
        height: size,
        background:
          "linear-gradient(145deg, color-mix(in oklab, var(--c-accent) 70%, white) 0%, var(--c-accent) 55%, color-mix(in oklab, var(--c-accent) 80%, black) 100%)",
      }}
    >
      <svg viewBox="0 0 30 30" className="size-full">
        {BARS.map((b, i) => (
          <motion.rect
            key={b.x}
            x={b.x - 1.4}
            width={2.8}
            rx={1.4}
            fill="white"
            opacity={b.o}
            initial={false}
            animate={
              live
                ? { height: [b.h, b.h * 0.45, b.h * 1.1, b.h], y: [15 - b.h / 2, 15 - (b.h * 0.45) / 2, 15 - (b.h * 1.1) / 2, 15 - b.h / 2] }
                : { height: b.h, y: 15 - b.h / 2 }
            }
            transition={
              live
                ? { duration: 0.9, repeat: Infinity, delay: i * 0.12, ease: "easeInOut" }
                : { duration: 0.25 }
            }
          />
        ))}
      </svg>
    </span>
  );
}
