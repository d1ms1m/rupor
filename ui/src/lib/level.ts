// Уровень микрофона: RMS float32 → 0..1 по шкале децибел (−55…−12 дБ).
export function levelFromRms(rms: number): number {
  if (!Number.isFinite(rms) || rms <= 0) return 0;
  const db = 20 * Math.log10(rms);
  return Math.max(0, Math.min(1, (db + 55) / 43));
}

/** Акцентный цвет из CSS-переменной (для canvas). */
export function cssVar(el: Element, name: string, fallback: string): string {
  const v = getComputedStyle(el).getPropertyValue(name).trim();
  return v || fallback;
}
