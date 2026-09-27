// Живая волна и индикатор уровня микрофона (события level, отрисовка 60 кадров/с).
import { useEffect, useRef } from "react";
import { cn } from "../lib/cn";
import { cssVar, levelFromRms } from "../lib/level";
import { backend } from "../lib/ws";

/** Волна из столбиков: новые значения появляются в центре и расходятся к краям. */
export function LiveWave({
  active,
  bars = 33,
  height = 56,
  className,
  barWidth = 3,
  gap = 3,
  color,
}: {
  active: boolean;
  bars?: number;
  height?: number;
  className?: string;
  barWidth?: number;
  gap?: number;
  /** Цвет столбиков; по умолчанию — акцент темы. */
  color?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const activeRef = useRef(active);
  activeRef.current = active;
  const colorRef = useRef(color);
  colorRef.current = color;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const half = Math.ceil(bars / 2);
    const hist = new Float32Array(half);
    const shown = new Float32Array(bars);
    let target = 0;
    let raf = 0;
    let frame = 0;
    let accent = cssVar(canvas, "--c-accent", "#7c5cff");
    let lastPush = 0;

    const off = backend.on("level", ({ rms }) => {
      if (!activeRef.current) return;
      target = levelFromRms(rms);
    });

    const draw = (now: number) => {
      raf = requestAnimationFrame(draw);
      if (++frame % 30 === 0) accent = cssVar(canvas, "--c-accent", accent);
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
        canvas.width = Math.round(w * dpr);
        canvas.height = Math.round(h * dpr);
      }
      // сдвиг истории ~ 30 раз в секунду
      if (now - lastPush > 33) {
        lastPush = now;
        for (let i = half - 1; i > 0; i--) hist[i] = hist[i - 1] ?? 0;
        hist[0] = activeRef.current ? target : 0;
        if (!activeRef.current) target = 0;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      const total = bars * barWidth + (bars - 1) * gap;
      const x0 = (w - total) / 2;
      const mid = (bars - 1) / 2;
      ctx.fillStyle = colorRef.current ?? accent;
      for (let i = 0; i < bars; i++) {
        const d = Math.abs(i - mid);
        const src = hist[Math.min(half - 1, Math.round(d))] ?? 0;
        const env = Math.cos((d / (mid + 1)) * (Math.PI / 2)) * 0.75 + 0.25;
        const want = src * env;
        const cur = shown[i] ?? 0;
        shown[i] = cur + (want - cur) * (want > cur ? 0.45 : 0.18);
        const bh = Math.max(barWidth, (shown[i] ?? 0) * (h - 4));
        const x = x0 + i * (barWidth + gap);
        const y = (h - bh) / 2;
        ctx.globalAlpha = activeRef.current ? 0.35 + 0.65 * Math.min(1, (shown[i] ?? 0) * 2 + 0.2) : 0.25;
        ctx.beginPath();
        ctx.roundRect(x, y, barWidth, bh, barWidth / 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    };
    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      off();
    };
  }, [bars, barWidth, gap]);

  return <canvas ref={canvasRef} className={cn("block w-full", className)} style={{ height }} />;
}

/** Горизонтальный индикатор уровня с удержанием пика. */
export function LevelBar({ active, className }: { active: boolean; className?: string }) {
  const fillRef = useRef<HTMLDivElement>(null);
  const peakRef = useRef<HTMLDivElement>(null);
  const activeRef = useRef(active);
  activeRef.current = active;

  useEffect(() => {
    let target = 0;
    let shown = 0;
    let peak = 0;
    let peakT = 0;
    let raf = 0;
    const off = backend.on("level", ({ rms }) => {
      if (activeRef.current) target = levelFromRms(rms);
    });
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      const want = activeRef.current ? target : 0;
      shown += (want - shown) * (want > shown ? 0.5 : 0.12);
      if (shown >= peak) {
        peak = shown;
        peakT = now;
      } else if (now - peakT > 700) {
        peak = Math.max(shown, peak - 0.012);
      }
      if (fillRef.current) {
        fillRef.current.style.clipPath = `inset(0 ${(100 - shown * 100).toFixed(1)}% 0 0 round 999px)`;
      }
      if (peakRef.current) peakRef.current.style.left = `calc(${(peak * 100).toFixed(1)}% - 2px)`;
    };
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      off();
    };
  }, []);

  return (
    <div className={cn("relative h-2 w-full overflow-hidden rounded-full bg-surface-3", className)}>
      <div
        ref={fillRef}
        className="absolute inset-0 rounded-full"
        style={{
          clipPath: "inset(0 100% 0 0)",
          background: "linear-gradient(90deg, var(--c-success) 0%, var(--c-success) 60%, var(--c-warn) 85%, var(--c-danger) 100%)",
        }}
      />
      <div ref={peakRef} className="absolute inset-y-0 w-[3px] rounded-full bg-fg/60" style={{ left: "-4px" }} />
    </div>
  );
}
